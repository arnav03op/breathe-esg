"""
Corporate travel JSON ingestion service.

Reads a Navan/Concur-style JSON export, normalises each trip into a
UniversalEmissionRow (Scope 3), and applies category-specific emission
calculations with fallback to spend-based estimation.

Expected JSON structure:
    {
        "provider": "...",
        "export_date": "...",
        "trips": [
            {
                "expense_id": "EXP-9901",
                "employee_id": "E001",
                "date": "2024-03-10",
                "category": "flight",
                "origin": "BLR",
                "destination": "DEL",
                "distance_km": null,
                "cabin_class": "Economy",
                "amount": 8500,
                "currency": "INR"
            },
            ...
        ]
    }

Usage:
    from emissions.services.travel_ingestion import ingest_travel_json
    result = ingest_travel_json("path/to/export.json", company_id=1, user_id=1)
"""

from __future__ import annotations

import json
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
# Mock route-distance dictionary  (IATA origin-destination → km)
#
# In production this would be replaced by a great-circle calculation using
# an IATA airport coordinate database (e.g. OpenFlights).
# Routes are stored in both directions for convenience.
# ---------------------------------------------------------------------------
_ROUTE_DISTANCES_KM: dict[str, float] = {
    "BLR-DEL": 1740,
    "DEL-BLR": 1740,
    "BOM-LHR": 7190,
    "LHR-BOM": 7190,
    "BLR-BOM": 845,
    "BOM-BLR": 845,
    "DEL-BOM": 1150,
    "BOM-DEL": 1150,
    "DEL-DXB": 2200,
    "DXB-DEL": 2200,
    "BLR-SIN": 3030,
    "SIN-BLR": 3030,
    "DEL-LHR": 6700,
    "LHR-DEL": 6700,
}

# ---------------------------------------------------------------------------
# Emission factors  (dummy / prototype)
# ---------------------------------------------------------------------------
# Flights — kgCO₂e per passenger-km, by cabin class.
# DEFRA 2024 approximate ranges: economy 0.13–0.16, business 0.33–0.43.
_FLIGHT_FACTORS: dict[str, float] = {
    "Economy":         0.15,     # kgCO₂e / passenger-km
    "Premium Economy": 0.23,
    "Business":        0.40,
    "First":           0.55,
}
_FLIGHT_FACTOR_DEFAULT = 0.15   # fall back to economy if class unknown

# Hotels — kgCO₂e per room-night (DEFRA average).
_HOTEL_FACTOR = 30.5            # kgCO₂e / night

# Ground transport — kgCO₂e per km (average car).
_GROUND_FACTOR = 0.20           # kgCO₂e / km

# Spend-based fallback — kgCO₂e per INR.
# Derived from EPA EEIO spend-based factor (~0.4 kgCO₂e/USD)
# adjusted for INR at ~₹83/USD → ≈ 0.005. We round up to 0.015 for
# conservatism (travel is carbon-intensive per rupee).
_SPEND_FACTOR = 0.015           # kgCO₂e / INR

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def ingest_travel_json(
    file_path: str | Path,
    company_id: int,
    user_id: int,
) -> dict[str, Any]:
    """
    Ingest a corporate travel JSON export into the emissions database.

    Returns:
        dict with keys: ingestion_log_id, total_rows, created, flagged, errors.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Travel JSON not found: {file_path}")

    company = ClientCompany.objects.get(pk=company_id)
    user = User.objects.filter(pk=user_id).first()

    # Log created outside atomic — persists on failure.
    log = DataIngestionLog.objects.create(
        client=company,
        source_type=DataIngestionLog.SourceType.TRAVEL,
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

    # --- Parse JSON -------------------------------------------------------
    try:
        with open(file_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        log.status = DataIngestionLog.Status.FAILED
        log.save(update_fields=["status"])
        stats["errors"].append(f"Invalid JSON: {exc}")
        logger.error("Travel ingestion failed — invalid JSON: log=%s", log.pk)
        return stats

    trips = data.get("trips")
    if not isinstance(trips, list):
        log.status = DataIngestionLog.Status.FAILED
        log.save(update_fields=["status"])
        stats["errors"].append("JSON has no 'trips' array")
        logger.error("Travel ingestion failed — no trips array: log=%s", log.pk)
        return stats

    # --- Process trips inside atomic block --------------------------------
    try:
        with transaction.atomic():
            for idx, trip in enumerate(trips, start=1):
                stats["total_rows"] += 1
                _process_trip(trip, idx, company, log, stats)

        log.status = DataIngestionLog.Status.COMPLETED
        log.save(update_fields=["status"])
        logger.info(
            "Travel ingestion completed: log=%s, created=%s, flagged=%s",
            log.pk, stats["created"], stats["flagged"],
        )

    except Exception as exc:
        log.status = DataIngestionLog.Status.FAILED
        log.save(update_fields=["status"])
        stats["errors"].append(f"Unhandled error: {exc}")
        logger.exception("Travel ingestion failed: log=%s", log.pk)

    return stats


# ---------------------------------------------------------------------------
# Per-trip processing
# ---------------------------------------------------------------------------
def _process_trip(
    trip: dict[str, Any],
    idx: int,
    company: ClientCompany,
    log: DataIngestionLog,
    stats: dict[str, Any],
) -> None:
    """Process a single trip record into a UniversalEmissionRow."""

    errors: list[str] = []
    status = UniversalEmissionRow.Status.PENDING

    category = str(trip.get("category", "")).lower().strip()
    expense_id = str(trip.get("expense_id", ""))
    origin = str(trip.get("origin", "") or "").upper().strip()
    destination = str(trip.get("destination", "") or "").upper().strip()
    cabin_class = str(trip.get("cabin_class", "") or "").strip()
    amount = trip.get("amount")
    distance_km = trip.get("distance_km")
    nights = trip.get("nights")

    # --- Date ---
    date_raw = trip.get("date")
    parsed_date = _parse_date(date_raw)
    if date_raw and parsed_date is None:
        errors.append(f"Unparseable date: '{date_raw}'")
        status = UniversalEmissionRow.Status.FLAGGED
    activity_date = parsed_date.date() if parsed_date else None

    # --- Facility name from location or route ---
    location = trip.get("location", "")
    if location:
        facility_name = str(location)
    elif origin and destination:
        facility_name = f"{origin} → {destination}"
    else:
        facility_name = ""

    # --- Dynamic emission calculation ------------------------------------
    normalized_value = None
    normalized_unit = ""
    emission_factor = None
    emission_factor_source = ""
    co2e = None
    used_fallback = False

    if category == "hotel":
        normalized_value, normalized_unit, emission_factor, emission_factor_source, co2e = (
            _calc_hotel(nights, errors)
        )

    elif category == "car_rental":
        normalized_value, normalized_unit, emission_factor, emission_factor_source, co2e = (
            _calc_ground(distance_km, errors)
        )

    elif category == "flight":
        normalized_value, normalized_unit, emission_factor, emission_factor_source, co2e = (
            _calc_flight(origin, destination, cabin_class, distance_km, errors)
        )
        # If flight calculation returned nothing (route not in dictionary,
        # no explicit distance), fall back to spend-based.
        if co2e is None and amount is not None:
            used_fallback = True

    else:
        # Unknown category (taxi, train, etc.) → spend-based fallback.
        used_fallback = True

    # --- Spend-based fallback --------------------------------------------
    if used_fallback:
        normalized_value, normalized_unit, emission_factor, emission_factor_source, co2e = (
            _calc_spend(amount, category, errors)
        )

    # --- Final validation ------------------------------------------------
    if co2e is None and normalized_value is None:
        errors.append(
            "Cannot calculate emissions: no distance, nights, or amount available"
        )
        status = UniversalEmissionRow.Status.FLAGGED

    if status == UniversalEmissionRow.Status.PENDING and errors:
        # Non-fatal warnings were collected (e.g. missing cabin class).
        # Don't override an already-flagged status.
        pass

    error_notes = "; ".join(errors) if errors else None

    # --- Create row ------------------------------------------------------
    UniversalEmissionRow.objects.create(
        client=company,
        ingestion_log=log,
        raw_payload=trip,
        normalized_value=normalized_value,
        normalized_unit=normalized_unit,
        sub_category=category,
        facility_code=expense_id,
        facility_name=facility_name,
        activity_start_date=activity_date,
        emission_factor=emission_factor,
        emission_factor_source=emission_factor_source,
        co2e_kg=co2e,
        scope_category=UniversalEmissionRow.ScopeCategory.SCOPE_3,
        status=status,
        error_notes=error_notes,
    )

    stats["created"] += 1
    if status == UniversalEmissionRow.Status.FLAGGED:
        stats["flagged"] += 1
        logger.warning("Trip %d flagged: %s", idx, error_notes)


# ---------------------------------------------------------------------------
# Calculation helpers — each returns:
#   (normalized_value, normalized_unit, emission_factor,
#    emission_factor_source, co2e_kg)
# ---------------------------------------------------------------------------

def _calc_hotel(
    nights: Any,
    errors: list[str],
) -> tuple[float | None, str, float | None, str, float | None]:
    """Hotel: co2e = nights × 30.5 kgCO₂e/night."""
    if nights is None:
        errors.append("Hotel trip missing 'nights' field")
        return None, "nights", None, "", None

    try:
        n = float(nights)
    except (ValueError, TypeError):
        errors.append(f"Cannot parse nights: '{nights}'")
        return None, "nights", None, "", None

    co2e = round(n * _HOTEL_FACTOR, 4)
    return n, "nights", _HOTEL_FACTOR, "DEFRA Hotel Night Average (dummy)", co2e


def _calc_ground(
    distance_km: Any,
    errors: list[str],
) -> tuple[float | None, str, float | None, str, float | None]:
    """Ground transport (car rental): co2e = distance_km × 0.20 kgCO₂e/km."""
    if distance_km is None:
        errors.append("Ground transport trip missing 'distance_km'")
        return None, "km", None, "", None

    try:
        d = float(distance_km)
    except (ValueError, TypeError):
        errors.append(f"Cannot parse distance_km: '{distance_km}'")
        return None, "km", None, "", None

    co2e = round(d * _GROUND_FACTOR, 4)
    return d, "km", _GROUND_FACTOR, "DEFRA Average Car (dummy)", co2e


def _calc_flight(
    origin: str,
    destination: str,
    cabin_class: str,
    explicit_distance: Any,
    errors: list[str],
) -> tuple[float | None, str, float | None, str, float | None]:
    """
    Flight: look up route distance, then apply cabin-class factor.

    Returns all-None if the route is unknown AND no explicit distance
    is provided — caller should fall back to spend-based.
    """
    # Try explicit distance first, then dictionary lookup.
    distance: float | None = None

    if explicit_distance is not None:
        try:
            distance = float(explicit_distance)
        except (ValueError, TypeError):
            pass

    if distance is None and origin and destination:
        route_key = f"{origin}-{destination}"
        distance = _ROUTE_DISTANCES_KM.get(route_key)
        if distance is None:
            errors.append(
                f"Flight route {route_key} not in distance dictionary — "
                f"falling back to spend-based estimation"
            )
            return None, "km", None, "", None

    if distance is None:
        errors.append("Flight has no distance and no origin/destination codes")
        return None, "km", None, "", None

    # Look up cabin-class factor.
    factor = _FLIGHT_FACTORS.get(cabin_class, _FLIGHT_FACTOR_DEFAULT)
    if cabin_class and cabin_class not in _FLIGHT_FACTORS:
        errors.append(
            f"Unknown cabin class '{cabin_class}' — defaulting to economy factor"
        )

    co2e = round(distance * factor, 4)
    source = f"Flight {cabin_class or 'Economy'} (distance-based, DEFRA dummy)"
    return distance, "km", factor, source, co2e


def _calc_spend(
    amount: Any,
    category: str,
    errors: list[str],
) -> tuple[float | None, str, float | None, str, float | None]:
    """Spend-based fallback: co2e = amount_INR × 0.015 kgCO₂e/INR."""
    if amount is None:
        errors.append(f"No amount available for spend-based fallback ({category})")
        return None, "INR", None, "", None

    try:
        amt = float(amount)
    except (ValueError, TypeError):
        errors.append(f"Cannot parse amount: '{amount}'")
        return None, "INR", None, "", None

    co2e = round(amt * _SPEND_FACTOR, 4)
    return amt, "INR", _SPEND_FACTOR, "Spend-based proxy (EPA EEIO, adjusted for INR)", co2e
