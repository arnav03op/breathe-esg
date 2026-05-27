"""
Utility (electricity) CSV ingestion service.

Reads a utility portal CSV export, normalises each row into a
UniversalEmissionRow (Scope 2), and validates billing-period chronology.

Expected CSV headers:
    meter_id, site_name, tariff, kwh_consumed, unit,
    billing_start, billing_end, amount_inr

Usage:
    from emissions.services.utility_ingestion import ingest_utility_csv
    result = ingest_utility_csv("path/to/export.csv", company_id=1, user_id=1)
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
# Header mapping  (CSV column → internal key)
# ---------------------------------------------------------------------------
UTILITY_HEADER_MAP: dict[str, str] = {
    "meter_id":       "meter_id",
    "site_name":      "site_name",
    "tariff":         "tariff",
    "kwh_consumed":   "kwh_consumed",
    "unit":           "unit",
    "billing_start":  "billing_start",
    "billing_end":    "billing_end",
    "amount_inr":     "amount_inr",
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# CEA (Central Electricity Authority) publishes India's grid emission factor.
# The 2023 value is ~0.71 tCO₂/MWh = 0.71 kgCO₂e/kWh.
INDIAN_GRID_EF = 0.71           # kgCO₂e per kWh
EMISSION_FACTOR_SOURCE = "CEA India Grid Average 2023 (dummy prototype)"

# Threshold above which consumption is considered suspiciously high.
HIGH_CONSUMPTION_THRESHOLD = 1_000_000  # kWh

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%d-%b-%Y",     # 14-Feb-2024  (primary utility format)
    "%d/%m/%Y",     # 14/02/2024
    "%Y-%m-%d",     # 2024-02-14
    "%d.%m.%Y",     # 14.02.2024
    "%d-%m-%Y",     # 14-02-2024
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
    return header.strip().lower()


def _safe_float(value: str, field_name: str = "value") -> tuple[float | None, str | None]:
    """Parse a string as float. Returns (value, error_or_None)."""
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None, f"{field_name} is empty"
    try:
        return float(cleaned), None
    except (ValueError, TypeError):
        return None, f"Cannot parse {field_name}: '{value}'"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def ingest_utility_csv(
    file_path: str | Path,
    company_id: int,
    user_id: int,
) -> dict[str, Any]:
    """
    Ingest a utility electricity CSV into the emissions database.

    The DataIngestionLog is created OUTSIDE the atomic block so that it
    survives even if the row-processing transaction rolls back.

    Returns:
        dict with keys: ingestion_log_id, total_rows, created, flagged, errors.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Utility CSV not found: {file_path}")

    company = ClientCompany.objects.get(pk=company_id)
    user = User.objects.filter(pk=user_id).first()

    # Log created outside atomic — persists on failure.
    log = DataIngestionLog.objects.create(
        client=company,
        source_type=DataIngestionLog.SourceType.UTILITY,
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

        log.status = DataIngestionLog.Status.COMPLETED
        log.save(update_fields=["status"])
        logger.info(
            "Utility ingestion completed: log=%s, created=%s, flagged=%s",
            log.pk, stats["created"], stats["flagged"],
        )

    except Exception as exc:
        log.status = DataIngestionLog.Status.FAILED
        log.save(update_fields=["status"])
        stats["errors"].append(f"Unhandled error: {exc}")
        logger.exception("Utility ingestion failed: log=%s", log.pk)

    return stats


# ---------------------------------------------------------------------------
# Internal CSV processing
# ---------------------------------------------------------------------------
def _process_csv(
    file_path: Path,
    company: ClientCompany,
    user: Any,
    log: DataIngestionLog,
    stats: dict[str, Any],
) -> None:
    with open(file_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            raise ValueError("CSV file appears to be empty or has no header row.")

        # Build column mapping (case-insensitive).
        column_map: dict[str, str] = {}
        for raw_col in reader.fieldnames:
            norm = _normalise_header(raw_col)
            if norm in UTILITY_HEADER_MAP:
                column_map[UTILITY_HEADER_MAP[norm]] = raw_col

        # Verify minimum required columns.
        required = {"kwh_consumed", "billing_start", "billing_end"}
        missing = required - column_map.keys()
        if missing:
            raise ValueError(
                f"CSV is missing required columns: {missing}. "
                f"Found headers: {reader.fieldnames}"
            )

        for row_num, raw_row in enumerate(reader, start=2):
            stats["total_rows"] += 1
            _process_single_row(
                raw_row, row_num, column_map,
                company, log, stats,
            )


def _process_single_row(
    raw_row: dict[str, str],
    row_num: int,
    column_map: dict[str, str],
    company: ClientCompany,
    log: DataIngestionLog,
    stats: dict[str, Any],
) -> None:
    """Process a single utility CSV row into a UniversalEmissionRow."""

    errors: list[str] = []
    status = UniversalEmissionRow.Status.PENDING

    def col(key: str) -> str:
        csv_col = column_map.get(key)
        if csv_col is None:
            return ""
        return (raw_row.get(csv_col) or "").strip()

    # ---- Facility / site ------------------------------------------------
    meter_id = col("meter_id")
    site_name = col("site_name")
    tariff = col("tariff")

    # ---- Unit -----------------------------------------------------------
    unit_raw = col("unit").strip()
    if not unit_raw:
        # Assume kWh for electricity, but warn.
        normalized_unit = "kWh"
        errors.append("Unit missing — defaulted to kWh (assumed electricity)")
    else:
        normalized_unit = unit_raw  # expected: kWh

    # ---- Consumption (kwh_consumed) ------------------------------------
    consumption_raw = col("kwh_consumed")
    consumption, cons_err = _safe_float(consumption_raw, "kwh_consumed")

    if cons_err:
        errors.append(cons_err)
        status = UniversalEmissionRow.Status.FLAGGED
    elif consumption is not None and consumption > HIGH_CONSUMPTION_THRESHOLD:
        errors.append(
            f"Suspiciously high consumption: {consumption:,.0f} kWh "
            f"(threshold: {HIGH_CONSUMPTION_THRESHOLD:,})"
        )
        status = UniversalEmissionRow.Status.FLAGGED

    # ---- Billing period dates ------------------------------------------
    start_raw = col("billing_start")
    end_raw = col("billing_end")

    parsed_start = _parse_date(start_raw)
    parsed_end = _parse_date(end_raw)

    if start_raw and parsed_start is None:
        errors.append(f"Unparseable billing_start: '{start_raw}'")
        status = UniversalEmissionRow.Status.FLAGGED

    if end_raw and parsed_end is None:
        errors.append(f"Unparseable billing_end: '{end_raw}'")
        status = UniversalEmissionRow.Status.FLAGGED

    # Chronology validation: end must not precede start.
    if parsed_start and parsed_end and parsed_end < parsed_start:
        errors.append(
            "Chronology error: End date precedes start date "
            f"({parsed_end.strftime('%Y-%m-%d')} < {parsed_start.strftime('%Y-%m-%d')})"
        )
        status = UniversalEmissionRow.Status.FLAGGED

    activity_start = parsed_start.date() if parsed_start else None
    activity_end = parsed_end.date() if parsed_end else None

    # ---- Emission factor & CO₂e ----------------------------------------
    co2e = None
    if consumption is not None:
        co2e = round(consumption * INDIAN_GRID_EF, 4)

    # ---- Error notes ----------------------------------------------------
    error_notes = "; ".join(errors) if errors else None

    # ---- Create the emission row ----------------------------------------
    UniversalEmissionRow.objects.create(
        client=company,
        ingestion_log=log,
        raw_payload=dict(raw_row),
        normalized_value=consumption,
        normalized_unit=normalized_unit,
        sub_category=tariff if tariff else "electricity",
        facility_code=meter_id,
        facility_name=site_name,
        activity_start_date=activity_start,
        activity_end_date=activity_end,
        emission_factor=INDIAN_GRID_EF,
        emission_factor_source=EMISSION_FACTOR_SOURCE,
        co2e_kg=co2e,
        scope_category=UniversalEmissionRow.ScopeCategory.SCOPE_2,
        status=status,
        error_notes=error_notes,
    )

    stats["created"] += 1
    if status == UniversalEmissionRow.Status.FLAGGED:
        stats["flagged"] += 1
        logger.warning("Row %d flagged: %s", row_num, error_notes)
