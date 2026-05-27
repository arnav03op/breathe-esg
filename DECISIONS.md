# DECISIONS.md — Ambiguities Resolved

Every design ambiguity we encountered, what we chose, why, and what we'd ask the PM if we could.

---

## 1. Data Model: One Universal Table vs. Source-Specific Tables

**Ambiguity:** Should SAP rows, utility rows, and travel rows live in separate tables with different schemas, or in a single unified table?

**Decision:** Single `UniversalEmissionRow` table for all source types.

**Why:** The output of normalisation is structurally identical regardless of source — a numeric value, a unit, a scope, and a CO₂e result. Source-specific quirks (German headers, airport codes, tariff tiers) are captured verbatim in `raw_payload` (JSONField) and don't need dedicated columns. A single table means the analyst review dashboard is one query, adding a fourth source type requires zero migrations, and cross-source reporting is trivial.

**Tradeoff:** Some fields are only meaningful for certain sources (e.g. `facility_code` matters for SAP/utility but not travel). We accept nullable fields over schema complexity.

**What we'd ask the PM:** "Will analysts ever need source-specific filtering that goes beyond what `sub_category` and `raw_payload` provide? If yes, we'd add indexed virtual columns or a supplementary detail table."

---

## 2. Ingestion Log: Created Outside the Atomic Transaction

**Ambiguity:** When a data upload fails mid-processing and the database transaction rolls back, should the ingestion log entry also disappear?

**Decision:** I explicitly designed the ingestion service to create the `DataIngestionLog` outside of the atomic database transaction. If a critical failure forces a database rollback, the system still preserves the failed log entry, ensuring a 100% accurate source-of-truth audit trail for all data pipeline attempts.

**Why:** If the log were inside the transaction, a crash would erase all evidence that the upload was ever attempted. Ops would have no visibility into failures. By creating the log first (status=`PROCESSING`), then wrapping row processing in `transaction.atomic()`, we guarantee that every attempt — successful or not — is recorded. On success we flip to `COMPLETED`; on crash we flip to `FAILED` and the log persists with error details.

**What we'd ask the PM:** "Should we also store the original uploaded file (or a reference to it in object storage) on the ingestion log, so that failed uploads can be retried without re-uploading?"

---

## 3. Multi-Tenancy: FK-per-Row vs. Schema-per-Tenant

**Ambiguity:** How do we isolate client data?

**Decision:** Simple foreign-key-per-row approach — every `DataIngestionLog` and `UniversalEmissionRow` has a `client` FK to `ClientCompany`.

**Why:** This is a prototype with a small number of clients. Schema-per-tenant (`django-tenants`) adds deployment complexity, complicates migrations, and is overkill when row-count is manageable. The FK approach is trivial to query (`queryset.filter(client=client)`) and easy to reason about.

**What we'd ask the PM:** "How many clients do you expect in the first year? If it's 500+, we'd revisit row-level security or schema isolation for performance and data-leak prevention."

---

## 4. `sub_category`: Free-Text vs. Enum

**Ambiguity:** Should travel sub-types (flight_short_haul, hotel, rail) and fuel types (diesel, petrol, natgas) be a fixed enum or a free-text field?

**Decision:** Free-text `CharField` with application-level validation.

**Why:** Sub-categories vary by source type and will grow as we onboard new clients with different fuel types or travel modes. A `TextChoices` enum would require a database migration every time we encounter a new sub-type. Free text with validation in the ingestion services gives us flexibility without schema churn.

**What we'd ask the PM:** "Is there a canonical list of sub-categories that the business already uses? If so, we'd codify it as an enum."

---

## 5. SAP Ingestion: File Upload, Not API Pull

**Ambiguity:** SAP data can be accessed via IDoc, BAPI, OData, or flat-file export. Which mechanism should we support?

**Decision:** CSV file upload (flat-file export).

**Why:** Most mid-market SAP installations don't expose OData or BAPI endpoints externally — getting API access typically requires SAP Basis involvement and weeks of procurement. A CSV export from transaction `SE16` or a scheduled background job is the lowest-friction option that works across SAP versions (ECC 6.0 through S/4HANA). The facilities team or a sustainability lead can export and upload without IT involvement.

**What we'd ask the PM:** "Does this client have SAP S/4HANA Cloud with OData enabled? If yes, we could build a direct API connector later — but the CSV path is the safe default."

---

## 6. Date Parsing: Multi-Format, Fail Gracefully

**Ambiguity:** SAP date formats vary by system locale (ISO `YYYY-MM-DD`, German `DD.MM.YYYY`, compact `YYYYMMDD`).

**Decision:** Try four formats in sequence. On total failure, set `activity_start_date` to `None`, append an error to `error_notes`, and flag the row — but still create it.

**Why:** Rejecting the entire row on a bad date loses data unnecessarily. The numeric value and material are still useful. An analyst can review the flagged row, manually correct the date, and approve it. This is more resilient than hard-failing.

---

## 7. Emission Factors: Hardcoded Dummies, Not a Lookup Table

**Ambiguity:** Where should emission factors come from? A database table? An API? A config file?

**Decision:** Hardcoded dummy constants in the ingestion service, clearly labelled as "Dummy EPA/DEFRA factor (prototype)".

**Why:** This is a prototype. Building a versioned emission factor table with year/region/source dimensions is a significant feature in itself. The dummy factors let us demonstrate the full pipeline (raw → normalised → CO₂e) without over-engineering. The `emission_factor` and `emission_factor_source` fields on each row mean we can swap in real factors later without schema changes — every row records exactly which factor was used.

**What we'd ask the PM:** "Which emission factor database does the business use? DEFRA, EPA, GHG Protocol? Do we need region-specific grid factors for Scope 2?"

---

## 8. Denormalised `client` FK on `UniversalEmissionRow`

**Ambiguity:** `client` can be derived via `emission_row.ingestion_log.client`. Should we store it directly?

**Decision:** Yes — deliberate denormalisation.

**Why:** Every API query and dashboard view filters by client. Joining through `DataIngestionLog` on every request adds latency for zero benefit. The value is set once at ingestion and never changes. The cost is one extra FK column; the benefit is simpler, faster queries across the entire application.

---

## 9. Unit Conversion: Handled at Ingestion Time, Not Query Time

**Ambiguity:** Should we store raw units and convert at display time, or convert during ingestion?

**Decision:** Convert during ingestion. Store the converted value in `normalized_value` and the target unit in `normalized_unit`. The original is preserved in `raw_payload`.

**Why:** Converting at query time means every dashboard render repeats the same work, and different views could theoretically produce different results if conversion logic changes. Converting once at ingestion gives a single source of truth. If the conversion was wrong, the analyst can see the original in `raw_payload`, flag the row, and correct it.

---

## 10. Chronology Validation for Utility Billing Periods

**Ambiguity:** What should happen when a scraped utility portal export contains an inverted billing period (end date before start date)?

**Decision:** I implemented chronology validation for utility bills. If a scraped portal export results in an inverted billing period (end date < start date), the system ingests the raw data but flags it for analyst review rather than generating negative emissions or failing the upload.

**Why:** Inverted dates are a real-world data quality problem — they happen when portals display dates inconsistently, when CSVs are manually edited, or when meter readings are corrected retroactively. Silently accepting them could produce negative consumption or negative CO₂e. Hard-rejecting them loses data that might be trivially fixable (swap the two dates). Flagging is the correct middle ground: the raw data is preserved, the analyst is alerted, and no bad numbers enter the approved dataset.

**What we'd ask the PM:** "Should we auto-correct obvious inversions (swap start/end) or always require manual review? Auto-correction is convenient but hides data quality problems from the upstream team."

---

## 11. India-Specific Grid Emission Factor for Utility Data

**Ambiguity:** Which emission factor should we use for Scope 2 (purchased electricity)?

**Decision:** Applied the official CEA India 2023 grid emission factor (0.71 kgCO₂e/kWh) to Indian facility data, labelled as `CEA India Grid Average 2023 (dummy prototype)`.

**Why:** Using a generic global average would be inaccurate. India's grid is coal-heavy (≈70% thermal), so the national factor (0.71) is significantly higher than, say, France (0.05) or Norway (0.01). Since the sample data uses Indian sites (Manesar, Gurgaon, Pune, Chennai), applying the CEA factor demonstrates regional awareness. In production, this would be refined to state-level factors — Himachal Pradesh (mostly hydro) has a much lower factor than Jharkhand (mostly coal).

**What we'd ask the PM:** "Do your clients operate across multiple countries? If so, we need a region-to-factor lookup table indexed by country/state and year."

---

## 12. Travel Ingestion: Dynamic Fallbacks and Defensive JSON Parsing

**Ambiguity:** How should we handle incomplete travel records and structural JSON errors?

**Decision:** For the Travel ingestion, I implemented dynamic distance overrides and reverse route lookups. I also added a defensive JSON structure validator that catches missing arrays without crashing the ingestion service, allowing the upload log to correctly reflect a FAILED state instead of causing an unhandled server exception.

**Why:** Real-world travel data is messy. If we can't find a flight route in our database and the user didn't provide a distance, falling back to a spend-based proxy (emissions per dollar spent) ensures we don't lose the data entirely. Additionally, wrapping the JSON parsing and validation steps with a defensive try/except block ensures that ops has a clear failure log rather than a silent 500 error.

---

## 13. API Layer Architectural Wins

**Performance Optimization (Serializers):** I explicitly created two distinct serializers (List vs. Detail). To optimize frontend performance and reduce bandwidth, the list view omits the raw_payload JSON field. The full raw data is only fetched when an analyst drills down into a specific row.

**State Machine Validation:** I enforced strict status transition validation at the API layer (e.g., a row cannot transition from PENDING directly to LOCKED without being APPROVED first). This prevents frontend bugs from corrupting the audit trail.

**Analyst UX (Bulk Operations):** I prioritized building a bulk-approve endpoint. In a real enterprise environment, analysts need the ability to quickly clear hundreds of clean, validated rows rather than clicking 'approve' one-by-one.

---

## 14. Prototype Tradeoff: Authentication & Multi-Tenant Context

**Ambiguity:** Should the upload endpoints dynamically resolve the `company_id` and authenticate the user, or should we hardcode them for the MVP?

**Decision:** I chose to bypass full User Authentication (login/JWT) and multi-tenant client selection in the React frontend. The upload components currently hardcode `company_id=1` (Acme Corp) and make anonymous requests to the API, which the backend safely handles by leaving the `uploaded_by` tracking field as `null`.

**Why:** Building robust auth flows and tenant-switching UI requires significant boilerplate that distracts from the core engineering challenge: building the complex ESG data ingestion engine, Scope categorizations, calculation fallbacks, and the Analyst Review UX. By hardcoding the company ID, we rapidly proved the viability of the data pipeline. In a production environment, the frontend would pull the `company_id` dynamically from a dropdown or the user's session token, and the backend would authorize the upload against the logged-in user's permissions.
