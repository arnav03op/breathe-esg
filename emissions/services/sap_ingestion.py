"""
SAP CSV ingestion service.

Reads a CSV exported from SAP (fuel & procurement data), normalises each row
into a UniversalEmissionRow, and records the upload in a DataIngestionLog.

Expected CSV headers (German/mixed SAP style):
    BUKRS, Plant, Material, Quantity, MEINS, Date, Cost

Usage:
    from emissions.services.sap_ingestion import ingest_sap_csv
    result = ingest_sap_csv("path/to/export.csv", company_id=1, user_id=1)
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from emissions.models import (
    ClientCompany,
    DataIngestionLog,
    UniversalEmissionRow,
)

logger = logging.getLogger(__name__)

User = get_user_model()

# ---------------------------------------------------------------------------
# SAP header mapping
# ---------------------------------------------------------------------------
# Maps the messy/German SAP column names to our internal canonical keys.
# If the real export uses slightly different casing, we normalise in
# _normalise_header() before lookup.
SAP_HEADER_MAP: dict[str, str] = {
    "bukrs":    "company_code",     # SAP company code (Buchungskreis)
    "plant":    "plant",            # SAP plant / facility code
    "material": "material",         # Material description (DIESEL, PETROL, …)
    "quantity": "quantity",         # Numeric amount
    "meins":    "unit",             # Unit of measure (Mengeneinheit)
    "date":     "date",             # Activity / posting date
    "cost":     "cost",             # Cost in local currency (informational)
}

# ---------------------------------------------------------------------------
# Material → scope + sub-category mapping
# ---------------------------------------------------------------------------
_MATERIAL_SCOPE: dict[str, tuple[str, str]] = {
    # material_key → (scope_category, sub_category)
    "DIESEL":  ("SCOPE_1", "diesel"),
    "PETROL":  ("SCOPE_1", "petrol"),
    "NATGAS":  ("SCOPE_1", "natural_gas"),
}

# ---------------------------------------------------------------------------
# Dummy emission factors  (kgCO₂e per litre)
# In production these would come from a versioned lookup table.
# ---------------------------------------------------------------------------
_EMISSION_FACTORS: dict[str, float] = {
    "DIESEL":  2.68,    # approx. EPA / DEFRA factor for diesel
    "PETROL":  2.31,    # approx. EPA / DEFRA factor for petrol / gasoline
    "NATGAS":  1.55,    # simplified – real factor depends on unit (m³, therm)
}

_EMISSION_FACTOR_SOURCE = "Dummy EPA/DEFRA factor (prototype)"

# ---------------------------------------------------------------------------
# Unit conversion table  →  target unit: litres
# ---------------------------------------------------------------------------
_UNIT_CONVERSIONS: dict[str, tuple[float, str]] = {
    # source_unit → (multiplier, target_unit)
    "L":   (1.0,   "L"),
    "LTR": (1.0,   "L"),       # alternate SAP unit code for litres
    "GAL": (3.785, "L"),       # US gallons → litres
}

# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d",      # ISO: 2024-03-15
    "%d.%m.%Y",      # German: 15.03.2024
    "%d/%m/%Y",      # Slash variant: 15/03/2024
    "%Y%m%d",        # SAP compact: 20240315
)


def _parse_date(raw: str) -> datetime | None:
    """Try multiple date formats. Return None on total failure."""
    cleaned = raw.strip()
    if not cleaned:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _normalise_header(header: str) -> str:
    """Lower-case and strip whitespace so that 'Plant', ' PLANT', 'plant' all match."""
    return header.strip().lower()


def _safe_float(value: str, field_name: str = "value") -> tuple[float | None, str | None]:
    """
    Attempt to parse a string as float.
    Returns (parsed_value, error_string_or_None).
    """
    cleaned = value.strip().replace(",", "")  # handle thousand-separator commas
    if not cleaned:
        return None, f"{field_name} is empty"
    try:
        return float(cleaned), None
    except (ValueError, TypeError):
        return None, f"Cannot parse {field_name}: '{value}'"


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------
def ingest_sap_csv(
    file_path: str | Path,
    company_id: int,
    user_id: int,
) -> dict[str, Any]:
    """
    Ingest a SAP fuel/procurement CSV export into the emissions database.

    The ingestion log is created OUTSIDE the atomic block so that it survives
    even if the row-processing transaction rolls back on an unexpected error.
    This lets us always have a record of the attempt (with status=FAILED).

    Args:
        file_path: Path to the CSV file.
        company_id: PK of the ClientCompany.
        user_id: PK of the Django User who triggered the upload.

    Returns:
        dict with keys: ingestion_log_id, total_rows, created, flagged, errors.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"SAP CSV not found: {file_path}")

    company = ClientCompany.objects.get(pk=company_id)
    user = User.objects.filter(pk=user_id).first()

    # -- Create ingestion log BEFORE the atomic block so it persists on failure.
    log = DataIngestionLog.objects.create(
        client=company,
        source_type=DataIngestionLog.SourceType.SAP,
        uploaded_by=user,
        status=DataIngestionLog.Status.PROCESSING,
    )

    stats: dict[str, Any] = {
        "ingestion_log_id": log.pk,
        "total_rows": 0,
        "created": 0,
        "flagged": 0,
        "errors": [],
    }

    try:
        with transaction.atomic():
            _process_csv(file_path, company, user, log, stats)

        # If we reach here, the transaction committed successfully.
        log.status = DataIngestionLog.Status.COMPLETED
        log.save(update_fields=["status"])
        logger.info(
            "SAP ingestion completed: log=%s, created=%s, flagged=%s",
            log.pk, stats["created"], stats["flagged"],
        )

    except Exception as exc:
        # Transaction rolled back — mark the log as FAILED.
        log.status = DataIngestionLog.Status.FAILED
        log.save(update_fields=["status"])
        stats["errors"].append(f"Unhandled error: {exc}")
        logger.exception("SAP ingestion failed: log=%s", log.pk)

    return stats


# ---------------------------------------------------------------------------
# Internal CSV processing (runs inside the atomic block)
# ---------------------------------------------------------------------------
def _process_csv(
    file_path: Path,
    company: ClientCompany,
    user: Any,
    log: DataIngestionLog,
    stats: dict[str, Any],
) -> None:
    """Parse and process every row of the SAP CSV."""

    with open(file_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            raise ValueError("CSV file appears to be empty or has no header row.")

        # Build a mapping from our canonical keys → actual CSV column names.
        column_map: dict[str, str] = {}
        for raw_col in reader.fieldnames:
            norm = _normalise_header(raw_col)
            if norm in SAP_HEADER_MAP:
                column_map[SAP_HEADER_MAP[norm]] = raw_col

        # Verify we have the minimum required columns.
        required = {"material", "quantity", "unit", "date"}
        missing = required - column_map.keys()
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {missing}. "
                f"Found headers: {reader.fieldnames}"
            )

        for row_num, raw_row in enumerate(reader, start=2):  # row 1 = header
            stats["total_rows"] += 1
            _process_single_row(
                raw_row, row_num, column_map,
                company, user, log, stats,
            )


def _process_single_row(
    raw_row: dict[str, str],
    row_num: int,
    column_map: dict[str, str],
    company: ClientCompany,
    user: Any,
    log: DataIngestionLog,
    stats: dict[str, Any],
) -> None:
    """Process a single CSV row into a UniversalEmissionRow."""

    errors: list[str] = []
    status = UniversalEmissionRow.Status.PENDING

    # -- Helper to read a column using our canonical key.
    def col(key: str) -> str:
        csv_col = column_map.get(key)
        if csv_col is None:
            return ""
        return (raw_row.get(csv_col) or "").strip()

    # ---- Material / scope categorisation --------------------------------
    material_raw = col("material").upper()
    scope_info = _MATERIAL_SCOPE.get(material_raw)

    if scope_info:
        scope_category, sub_category = scope_info
    else:
        # Unknown material — still create the row, but flag it.
        scope_category = "SCOPE_1"  # default; analyst must review
        sub_category = material_raw.lower() if material_raw else "unknown"
        status = UniversalEmissionRow.Status.FLAGGED
        errors.append(f"Unknown material: '{material_raw}'")

    # ---- Date parsing ---------------------------------------------------
    date_raw = col("date")
    parsed_date = _parse_date(date_raw)
    if date_raw and parsed_date is None:
        errors.append(f"Unparseable date: '{date_raw}'")
        status = UniversalEmissionRow.Status.FLAGGED

    activity_date = parsed_date.date() if parsed_date else None

    # ---- Quantity -------------------------------------------------------
    quantity_raw = col("quantity")
    quantity, qty_err = _safe_float(quantity_raw, "Quantity")
    if qty_err:
        errors.append(qty_err)
        status = UniversalEmissionRow.Status.FLAGGED

    # ---- Unit normalisation ---------------------------------------------
    unit_raw = col("unit").upper()

    if not unit_raw:
        errors.append("Unit (MEINS) is blank")
        status = UniversalEmissionRow.Status.FLAGGED
        normalized_value = quantity
        normalized_unit = ""
    elif unit_raw in _UNIT_CONVERSIONS:
        multiplier, normalized_unit = _UNIT_CONVERSIONS[unit_raw]
        normalized_value = quantity * multiplier if quantity is not None else None
    else:
        # Unknown unit — keep the raw value, flag for review.
        errors.append(f"Unknown unit: '{unit_raw}'")
        status = UniversalEmissionRow.Status.FLAGGED
        normalized_value = quantity
        normalized_unit = unit_raw

    # ---- Emission factor & CO₂e ----------------------------------------
    ef = _EMISSION_FACTORS.get(material_raw)
    co2e = None
    if ef is not None and normalized_value is not None:
        co2e = round(normalized_value * ef, 4)

    # ---- Facility -------------------------------------------------------
    plant_code = col("plant")
    company_code = col("company_code")  # BUKRS

    # ---- Build error_notes string (or None) -----------------------------
    error_notes = "; ".join(errors) if errors else None

    # ---- Create the emission row ----------------------------------------
    UniversalEmissionRow.objects.create(
        client=company,
        ingestion_log=log,
        raw_payload=dict(raw_row),              # verbatim CSV row as JSON
        normalized_value=normalized_value,
        normalized_unit=normalized_unit,
        sub_category=sub_category,
        facility_code=plant_code,
        facility_name=f"Plant {plant_code}" if plant_code else "",
        activity_start_date=activity_date,
        emission_factor=ef,
        emission_factor_source=_EMISSION_FACTOR_SOURCE if ef else "",
        co2e_kg=co2e,
        scope_category=scope_category,
        status=status,
        error_notes=error_notes,
    )

    stats["created"] += 1
    if status == UniversalEmissionRow.Status.FLAGGED:
        stats["flagged"] += 1
        logger.warning("Row %d flagged: %s", row_num, error_notes)
