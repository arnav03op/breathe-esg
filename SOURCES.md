# SOURCES.md — Data Source Research

For each of the three sources: what real-world format we researched, what we learned, what our sample data looks like and why, and what would break in a real deployment.

---

## 1. SAP — Fuel & Procurement Data

### What we researched

SAP exposes data through multiple channels: IDocs (intermediate documents), BAPIs (function modules), OData services (S/4HANA), and flat-file exports (SE16/SE38 background jobs). We chose **flat-file CSV export** because:

- Most mid-market SAP installations (ECC 6.0) don't expose OData endpoints externally.
- Getting BAPI/IDoc access requires SAP Basis team involvement and procurement cycles that don't fit a 4-day prototype.
- CSV export from `SE16` or a scheduled background job is the lowest-friction option that works across SAP versions.

### What we learned

- **Column headers are locale-dependent.** A German-configured SAP system uses `BUKRS` (Buchungskreis = company code), `MEINS` (Mengeneinheit = unit of measure). English-configured systems use `Company Code`, `Unit`.
- **Units are inconsistent.** The same material may appear in litres (`L`, `LTR`) or gallons (`GAL`) depending on the plant's locale.
- **Dates vary by system locale.** ISO (`2024-03-15`), German (`15.03.2024`), and compact (`20240315`) are all common.
- **Material descriptions are not standardised.** One plant's `DIESEL` is another's `DIESEL_FUEL_B7`. We normalise to uppercase and match against a known set.
- **Plant codes are meaningless without a lookup table.** `P100` tells you nothing unless you know it maps to "Manesar Plant."

### What our sample data looks like

```
BUKRS,Plant,Material,Quantity,MEINS,Date,Cost
1000,P100,DIESEL,500.00,L,2024-03-15,1250.00
1000,P100,DIESEL,120.50,GAL,15.03.2024,980.00
```

We deliberately included:
- Mixed date formats (ISO + German) to test multi-format parsing.
- `GAL` unit to test gallon-to-litre conversion.
- `UNKNOWN` material to test graceful flagging.
- An invalid date (`33.03.2024`) to test date-parse failure handling.
- A blank unit to test missing-field flagging.

### What would break in a real deployment

- **Material master mismatch.** Real SAP exports use material numbers (e.g., `MAT-00042`), not human-readable names. We'd need a material-master lookup table.
- **Multi-currency cost.** We ignore the `Cost` column. In production, currency conversion would be needed for financial reporting.
- **Character encoding.** SAP exports may use ISO-8859-1 or Windows-1252, not UTF-8. We'd need encoding detection (e.g., `chardet`).
- **Volume vs. mass.** Natural gas may come in `m³` or `therms`, not litres. Our current unit conversion only handles `L`/`GAL`.

---

## 2. Utility Data — Electricity

### What we researched

Facilities teams get electricity data via:
- **Portal CSV exports** — most utility portals (Tata Power, BSES, Adani) offer a "download usage" feature.
- **PDF bills** — common but requires OCR/parsing; not viable for a prototype.
- **API** — rare in India; some US/EU utilities offer Green Button or similar.

We chose **portal CSV export** because it's the most common path for Indian enterprise clients, requires no OCR, and the facilities team can do it without IT involvement.

### What we learned

- **Billing periods don't align with calendar months.** A meter reading might cover 14-Feb to 13-Mar. This is why we store `activity_start_date` and `activity_end_date` separately rather than a single month field.
- **Tariff codes matter.** Indian commercial tariffs (`B1`, `B2`, `HT-1`) affect cost but not emissions. We store them as `sub_category` for context.
- **Meter IDs are the true primary key.** A site can have multiple meters. `MET-MNS-001` is the unique identifier, not the site name.
- **Grid emission factors are regional.** India's CEA publishes a national average (0.71 kgCO₂e/kWh for 2023), but state-level factors vary significantly (e.g., Himachal Pradesh is mostly hydro → lower factor).

### Emission factor choice

For Utility data, I applied the official CEA India 2023 grid emission factor (0.71 kgCO₂e/kWh) to Indian facility data to demonstrate regional accuracy. In production, this would be sourced from the CEA's published CO₂ Baseline Database and could be refined to state-level grid factors.

### What our sample data looks like

```
meter_id,site_name,tariff,kwh_consumed,unit,billing_start,billing_end,amount_inr
MET-MNS-001,Manesar Plant,B1,42500,kWh,14-Feb-2024,13-Mar-2024,319875
```

We deliberately included:
- Indian site names (Manesar, Gurgaon, Pune, Chennai) for realism.
- Missing unit (to test the "assume kWh" default).
- Suspiciously high consumption (1,200,000 kWh) to test the threshold flag.
- Blank consumption to test missing-value handling.
- Inverted billing dates (end < start) to test chronology validation.
- An invalid date (`33-Apr-2024`) to test date-parse failure.

### What would break in a real deployment

- **Overlapping billing periods.** Two bills for the same meter covering overlapping date ranges would cause double-counting. We don't deduplicate yet.
- **Multiple meters per site.** Aggregation at the site level requires summing across meters, which we don't do at ingestion time.
- **State-level emission factors.** The national average (0.71) over/under-estimates for states with high renewable penetration. We'd need a state-grid factor lookup.
- **PDF bills.** Many Indian utilities still primarily issue PDF bills. Supporting this would require OCR (Tesseract, Azure Document Intelligence, etc.).

---

## 3. Corporate Travel — Flights, Hotels, Ground Transport

### What we researched

Corporate travel data comes from platforms like:
- **Concur (SAP)** — dominant in enterprise, exposes data via REST API and flat-file exports.
- **Navan (formerly TripActions)** — growing competitor, JSON API.
- **Manual expense reports** — Excel/CSV exports from internal systems.

We modelled our sample data after a **Navan-style JSON API response** because:
- JSON is the native format for modern travel platforms.
- It demonstrates handling of a structurally different source format (nested JSON vs. flat CSV).
- Navan's schema is publicly documented and representative of the category.

### What we learned

- **Distance is often missing.** Travel platforms record origin/destination airport codes (IATA), not distances. Computing distance requires a lookup (e.g., great-circle calculation from airport coordinates).
- **Categories imply different emission factors.** A short-haul economy flight has a different factor than a long-haul business flight. Hotels have per-night factors. Ground transport has per-km factors.
- **Cabin class matters.** Business class has ~2-3x the emissions of economy (larger seat footprint = fewer passengers per flight).
- **Some trips have no location data.** A taxi receipt might only have an amount, with no origin, destination, or distance.

### What our sample data looks like

```json
{
    "provider": "MockNavanAPI",
    "export_date": "2024-04-01T10:00:00Z",
    "trips": [
        {
            "expense_id": "EXP-9901",
            "category": "flight",
            "origin": "BLR",
            "destination": "DEL",
            "distance_km": null,
            "cabin_class": "Economy"
        }
    ]
}
```

We deliberately included:
- Flights with no `distance_km` (only airport codes) — requires distance lookup.
- A hotel entry with `nights` instead of distance — different emission factor model.
- A `car_rental` with known distance — straightforward per-km calculation.
- An international flight (BOM→LHR) in Business class — different factor.
- A taxi with no origin, destination, or distance — maximum ambiguity, should be flagged.

### What would break in a real deployment

- **Airport code resolution.** We'd need an IATA airport database to compute great-circle distances from codes like `BLR` and `DEL`.
- **Emission factor granularity.** DEFRA publishes factors by: domestic/short-haul/long-haul × economy/premium-economy/business/first. We'd need a multi-dimensional lookup.
- **Currency conversion.** Travel expenses in multiple currencies need a date-specific exchange rate for cost reporting.
- **Return flights.** A round-trip booking might appear as one record or two. Deduplication logic would be needed.
