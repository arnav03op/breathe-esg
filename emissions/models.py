"""
Emissions tracking models.

Four core models:
  - ClientCompany:         tenant / organisation
  - DataIngestionLog:      metadata for each file upload
  - UniversalEmissionRow:  normalised emission record (the central table)
  - AuditLog:              immutable change history for emission rows
"""

from django.conf import settings
from django.db import models


# ---------------------------------------------------------------------------
# ClientCompany
# ---------------------------------------------------------------------------
class ClientCompany(models.Model):
    """An organisation whose emissions are being tracked."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    class Meta:
        verbose_name_plural = "client companies"
        ordering = ["name"]

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# DataIngestionLog
# ---------------------------------------------------------------------------
class DataIngestionLog(models.Model):
    """Tracks every data-upload event (SAP, utility bill, travel report)."""

    class SourceType(models.TextChoices):
        SAP = "SAP", "SAP"
        UTILITY = "UTILITY", "Utility"
        TRAVEL = "TRAVEL", "Travel"

    class Status(models.TextChoices):
        PROCESSING = "PROCESSING", "Processing"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    client = models.ForeignKey(
        ClientCompany,
        on_delete=models.CASCADE,
        related_name="ingestion_logs",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
    )
    upload_timestamp = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ingestion_logs",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )

    class Meta:
        ordering = ["-upload_timestamp"]

    def __str__(self):
        return (
            f"[{self.get_source_type_display()}] "
            f"{self.client} — {self.get_status_display()} "
            f"({self.upload_timestamp:%Y-%m-%d %H:%M})"
        )


# ---------------------------------------------------------------------------
# UniversalEmissionRow
# ---------------------------------------------------------------------------
class UniversalEmissionRow(models.Model):
    """
    A single normalised emission data-point.

    `raw_payload` stores the original messy row exactly as it came in (JSON).
    After normalisation the cleaned values live in `normalized_value` /
    `normalized_unit`.
    """

    class ScopeCategory(models.TextChoices):
        SCOPE_1 = "SCOPE_1", "Scope 1"
        SCOPE_2 = "SCOPE_2", "Scope 2"
        SCOPE_3 = "SCOPE_3", "Scope 3"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        FLAGGED = "FLAGGED", "Flagged"
        LOCKED = "LOCKED", "Locked"

    client = models.ForeignKey(
        ClientCompany,
        on_delete=models.CASCADE,
        related_name="emission_rows",
    )
    ingestion_log = models.ForeignKey(
        DataIngestionLog,
        on_delete=models.CASCADE,
        related_name="emission_rows",
    )

    # Raw data
    raw_payload = models.JSONField(
        help_text="Original messy row exactly as it came in.",
    )

    # Normalised data
    normalized_value = models.FloatField(null=True, blank=True)
    normalized_unit = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="e.g. kWh, kgCO2e",
    )

    # Sub-category (e.g. flight_domestic, hotel, diesel, natural_gas)
    sub_category = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Source-specific sub-type, e.g. flight_short_haul, diesel, grid_electricity",
    )

    # Facility / site identifiers
    facility_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Human-readable site name, e.g. 'Mumbai HQ'",
    )
    facility_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Source-system identifier: SAP plant code, utility meter ID, etc.",
    )

    # Activity period (billing/reporting window the data covers)
    activity_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Start of the billing or activity period",
    )
    activity_end_date = models.DateField(
        null=True,
        blank=True,
        help_text="End of the billing or activity period",
    )

    # Emission factor & computed CO₂e
    emission_factor = models.FloatField(
        null=True,
        blank=True,
        help_text="Conversion factor used, e.g. 0.82 kgCO2e/kWh",
    )
    emission_factor_source = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Origin of the factor, e.g. 'DEFRA 2024', 'EPA eGRID 2023'",
    )
    co2e_kg = models.FloatField(
        null=True,
        blank=True,
        help_text="Calculated CO₂ equivalent in kilograms",
    )

    # Classification
    scope_category = models.CharField(
        max_length=20,
        choices=ScopeCategory.choices,
    )

    # Workflow
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    error_notes = models.TextField(null=True, blank=True)

    # Approval
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_emission_rows",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    # Edit tracking
    is_edited = models.BooleanField(default=False)

    # Timestamps
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-ingested_at"]

    def __str__(self):
        return (
            f"Row #{self.pk} | {self.client} | "
            f"{self.get_scope_category_display()} | "
            f"{self.get_status_display()}"
        )


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AuditLog(models.Model):
    """Immutable log entry recording every status change on an emission row."""

    emission_row = models.ForeignKey(
        UniversalEmissionRow,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="emission_audit_logs",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    note = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return (
            f"Audit #{self.pk} | Row {self.emission_row_id}: "
            f"{self.old_status} → {self.new_status}"
        )
