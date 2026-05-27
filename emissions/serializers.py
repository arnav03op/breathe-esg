"""
DRF serializers for the emissions app.
"""

from rest_framework import serializers

from emissions.models import (
    AuditLog,
    ClientCompany,
    DataIngestionLog,
    UniversalEmissionRow,
)


# ---------------------------------------------------------------------------
# Lightweight nested serializers (read-only context for the frontend)
# ---------------------------------------------------------------------------
class ClientCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientCompany
        fields = ["id", "name", "slug"]


class DataIngestionLogSerializer(serializers.ModelSerializer):
    """Read-only summary embedded inside each emission row."""

    client_name = serializers.CharField(source="client.name", read_only=True)
    source_type_display = serializers.CharField(
        source="get_source_type_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username", default=None, read_only=True
    )

    class Meta:
        model = DataIngestionLog
        fields = [
            "id",
            "client_name",
            "source_type",
            "source_type_display",
            "upload_timestamp",
            "uploaded_by_username",
            "status",
            "status_display",
        ]


# ---------------------------------------------------------------------------
# Main emission-row serializer
# ---------------------------------------------------------------------------
class EmissionRowSerializer(serializers.ModelSerializer):
    """
    Full representation of a UniversalEmissionRow.

    Includes nested read-only info about the ingestion log so the frontend
    knows where the data came from, plus human-readable display values for
    all choice fields.
    """

    ingestion_log = DataIngestionLogSerializer(read_only=True)
    client_name = serializers.CharField(source="client.name", read_only=True)
    scope_category_display = serializers.CharField(
        source="get_scope_category_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    approved_by_username = serializers.CharField(
        source="approved_by.username", default=None, read_only=True
    )

    class Meta:
        model = UniversalEmissionRow
        fields = [
            "id",
            # Tenant
            "client",
            "client_name",
            # Provenance
            "ingestion_log",
            "raw_payload",
            # Normalised data
            "normalized_value",
            "normalized_unit",
            "sub_category",
            # Facility
            "facility_name",
            "facility_code",
            # Activity period
            "activity_start_date",
            "activity_end_date",
            # Emission calculation
            "emission_factor",
            "emission_factor_source",
            "co2e_kg",
            # Classification
            "scope_category",
            "scope_category_display",
            # Workflow
            "status",
            "status_display",
            "error_notes",
            # Approval
            "approved_by",
            "approved_by_username",
            "approved_at",
            # Edit tracking
            "is_edited",
            "ingested_at",
        ]
        read_only_fields = [
            "id",
            "client",
            "client_name",
            "ingestion_log",
            "raw_payload",
            "ingested_at",
            "approved_by",
            "approved_by_username",
            "approved_at",
        ]


# ---------------------------------------------------------------------------
# Compact list serializer (for dashboard table — less payload)
# ---------------------------------------------------------------------------
class EmissionRowListSerializer(serializers.ModelSerializer):
    """
    Lighter serializer for list views — omits raw_payload and heavy nested
    objects to keep the dashboard snappy.
    """

    client_name = serializers.CharField(source="client.name", read_only=True)
    source_type = serializers.CharField(
        source="ingestion_log.source_type", read_only=True
    )
    scope_category_display = serializers.CharField(
        source="get_scope_category_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )

    class Meta:
        model = UniversalEmissionRow
        fields = [
            "id",
            "client_name",
            "source_type",
            "normalized_value",
            "normalized_unit",
            "sub_category",
            "facility_name",
            "facility_code",
            "activity_start_date",
            "activity_end_date",
            "co2e_kg",
            "scope_category",
            "scope_category_display",
            "status",
            "status_display",
            "error_notes",
            "is_edited",
            "ingested_at",
        ]


# ---------------------------------------------------------------------------
# Audit log serializer
# ---------------------------------------------------------------------------
class AuditLogSerializer(serializers.ModelSerializer):
    changed_by_username = serializers.CharField(
        source="changed_by.username", default=None, read_only=True
    )

    class Meta:
        model = AuditLog
        fields = [
            "id",
            "emission_row",
            "changed_by",
            "changed_by_username",
            "changed_at",
            "old_status",
            "new_status",
            "note",
        ]
        read_only_fields = fields
