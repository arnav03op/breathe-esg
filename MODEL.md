# MODEL.md — Data Model Design

## Overview

The data model is built around one central insight: **the hardest part of emissions tracking is not the math — it is reconciling messy, inconsistent source data into a shape you can trust enough to hand to an auditor.**

Every table in this schema exists to answer one of two questions:

1. **Where did this number come from?** (provenance)
2. **Can I trust it?** (review workflow)

The schema has four models. The relationships are intentionally linear — a directed chain from tenant → ingestion event → normalised row → audit entry — because emissions data flows in one direction: raw input → cleaned output → human review → locked record.

```
ClientCompany
  └── DataIngestionLog          (one per upload / API pull)
        └── UniversalEmissionRow  (one per normalised data-point)
              └── AuditLog          (one per status change)
```

---

## Entity-Relationship Diagram

```
┌──────────────┐       ┌───────────────────┐
│ ClientCompany│       │   Django User      │
│──────────────│       │  (auth.User)       │
│ name         │       └─────┬──────┬───────┘
│ slug (unique)│             │      │
└──────┬───────┘             │      │
       │ 1:N                 │      │
       ▼                     │      │
┌──────────────────┐         │      │
│ DataIngestionLog │◄────────┘      │
│──────────────────│ uploaded_by    │
│ source_type      │                │
│ upload_timestamp │                │
│ status           │                │
└──────┬───────────┘                │
       │ 1:N                        │
       ▼                            │
┌───────────────────────┐           │
│ UniversalEmissionRow  │◄──────────┘
│───────────────────────│ approved_by
│ raw_payload (JSON)    │
│ normalized_value/unit │
│ sub_category          │
│ facility_name/code    │
│ activity_start/end    │
│ emission_factor       │
│ co2e_kg               │
│ scope_category        │
│ status (workflow)     │
│ is_edited             │
│ ingested_at           │
└──────┬────────────────┘
       │ 1:N
       ▼
┌──────────────┐
│  AuditLog    │
│──────────────│
│ changed_by   │→ Django User
│ changed_at   │
│ old_status   │
│ new_status   │
│ note         │
└──────────────┘
```

---

## Models in Detail

### 1. `ClientCompany`

| Field | Type | Notes |
|-------|------|-------|
| `name` | CharField(255) | Display name of the organisation |
| `slug` | SlugField(unique) | URL-safe identifier, used in API routes and multi-tenant filtering |

**Why it exists:** Multi-tenancy. Every emission row, every ingestion log, every query in this system is scoped to a client. We chose a lightweight foreign-key-per-row approach over schema-per-tenant or database-per-tenant because:

- This is a prototype with a small number of clients (< 100).
- Django's ORM makes FK-based tenant filtering trivial (`EmissionRow.objects.filter(client=client)`).
- Schema-per-tenant adds deployment complexity that is not justified at this stage.

The `slug` field gives us stable, human-readable identifiers for API URLs (e.g. `/api/clients/acme-corp/emissions/`) without exposing auto-increment PKs.

**What we'd change at scale:** Move to `django-tenants` or a shared-schema approach with row-level security if the client count grows past a few hundred, mainly for query isolation and data-leak prevention.

---

### 2. `DataIngestionLog`

| Field | Type | Notes |
|-------|------|-------|
| `client` | FK → ClientCompany | Which tenant this upload belongs to |
| `source_type` | CharField (choices: SAP, UTILITY, TRAVEL) | Identifies the source system |
| `upload_timestamp` | DateTimeField (auto_now_add) | When the file was uploaded / API pull executed |
| `uploaded_by` | FK → User (nullable) | Who triggered the ingestion |
| `status` | CharField (choices: PROCESSING, COMPLETED, FAILED) | Current state of the ingestion job |

**Why it exists:** Source-of-truth tracking. When an auditor asks "where did row #4827 come from?", the answer is a specific `DataIngestionLog` entry that records: *SAP export, uploaded by jane@client.com on 2025-03-12 at 14:32, status: completed.*

We chose to model this as a **separate table** rather than denormalising source metadata onto each emission row because:

- One file upload produces many rows. Repeating source metadata on every row wastes storage and creates update anomalies.
- The ingestion log has its own lifecycle (`PROCESSING → COMPLETED | FAILED`) that is independent of individual row statuses.
- It lets us answer operational questions cheaply: "How many uploads failed this week?" "What was the last successful SAP import?"

**`source_type` as an enum, not a separate table:** With only three known source types, a `TextChoices` enum is simpler and faster than a normalised `SourceType` table. If we needed to add metadata per source type (e.g., parser configuration, API credentials), we'd promote this to a model. For now, YAGNI.

**`uploaded_by` uses `SET_NULL`:** If a user account is deleted, we preserve the ingestion record. The data doesn't disappear just because someone left the company.

---

### 3. `UniversalEmissionRow`

This is the **central table** — the single normalised representation of every emission data-point regardless of whether it came from SAP, a utility CSV, or a travel platform.

| Field | Type | Why |
|-------|------|-----|
| `client` | FK → ClientCompany | Tenant scoping (denormalised from ingestion_log for query performance) |
| `ingestion_log` | FK → DataIngestionLog | Which upload produced this row |
| `raw_payload` | JSONField | Original source row, stored verbatim |
| `normalized_value` | FloatField (nullable) | Cleaned numeric value after unit conversion |
| `normalized_unit` | CharField | Target unit after normalisation (e.g. kWh, litres, km) |
| `sub_category` | CharField | Source-specific sub-type (e.g. `flight_short_haul`, `diesel`, `grid_electricity`) |
| `facility_name` | CharField | Human-readable site name |
| `facility_code` | CharField | Source-system ID: SAP plant code, meter number, etc. |
| `activity_start_date` | DateField (nullable) | Start of the billing / activity period |
| `activity_end_date` | DateField (nullable) | End of the billing / activity period |
| `emission_factor` | FloatField (nullable) | Conversion factor applied (e.g. 0.82 kgCO₂e/kWh) |
| `emission_factor_source` | CharField | Where the factor came from (e.g. "DEFRA 2024") |
| `co2e_kg` | FloatField (nullable) | Final calculated CO₂ equivalent in kilograms |
| `scope_category` | CharField (choices: SCOPE_1, SCOPE_2, SCOPE_3) | GHG Protocol scope |
| `status` | CharField (choices: PENDING, APPROVED, FLAGGED, LOCKED) | Review workflow state |
| `error_notes` | TextField (nullable) | Why a row was flagged or failed normalisation |
| `approved_by` | FK → User (nullable) | Who signed off on this row |
| `approved_at` | DateTimeField (nullable) | When they signed off |
| `is_edited` | BooleanField | Whether a human modified normalised values after ingestion |
| `ingested_at` | DateTimeField (auto_now_add) | When this row was created |

#### Design decisions explained

**Why "universal" — one table, not three:**

The alternative was separate models for SAP rows, utility rows, and travel rows. We rejected this because:

- The *output* of normalisation is the same regardless of source: a numeric value, a unit, a scope, and a CO₂e result. Source-specific quirks belong in `raw_payload`, not in the schema.
- A single table makes the analyst review dashboard trivial — one query, one table, sortable and filterable by any dimension.
- Adding a fourth source type (e.g., manual spreadsheet uploads) requires zero schema changes.

The tradeoff is that some fields are only relevant to certain source types (e.g., `facility_code` is meaningful for SAP/utility but not travel). We accept this — nullable/blank fields are a small cost compared to the complexity of a polymorphic model hierarchy.

**`raw_payload` as JSONField:**

Every source format is different. SAP exports have German column headers and plant codes. Utility CSVs have tariff tiers. Travel data has airport codes and cabin classes. Rather than trying to anticipate every possible column, we store the **original row verbatim** as JSON and normalise *out of it* into the structured fields.

This gives us:

- **Full provenance:** An auditor can always see exactly what the source system sent.
- **Debugging:** When normalisation produces a suspicious value, an analyst can inspect the raw data without re-uploading.
- **Forward compatibility:** New fields in source exports don't require migrations.

**`client` FK — deliberate denormalisation:**

`client` could be derived by following `emission_row.ingestion_log.client`. We store it directly on the row because:

- Every API query filters by client. Joining through `DataIngestionLog` on every request adds latency for no benefit.
- Django's ORM generates cleaner queries with a direct FK.
- The value never diverges — it's set once at ingestion time and never updated.

**`sub_category` as a free-text CharField, not an enum:**

Sub-categories vary by source type and evolve as we add support for new formats. `flight_short_haul`, `flight_long_haul`, `hotel`, `rail`, `diesel`, `natural_gas`, `grid_electricity` — hardcoding these as `TextChoices` would require a migration every time we encounter a new fuel type or travel mode. A free-text field with application-level validation gives us flexibility without schema churn.

**Activity period (`activity_start_date` / `activity_end_date`):**

Utility billing periods don't align with calendar months. A meter reading might cover 2025-02-14 to 2025-03-17. Without these fields, we can't correctly pro-rate consumption into reporting periods or detect overlapping bills. These are `DateField` (not `DateTimeField`) because billing periods are day-granularity in practice.

**Emission factor fields:**

Storing the factor *used* and its *source* on each row is non-negotiable for audit. If DEFRA updates their factors, we need to know which rows used the old values vs. the new ones. `co2e_kg` is the computed output — `normalized_value × emission_factor` — stored rather than computed on the fly so that:

- Dashboard queries don't recompute on every request.
- A locked row's CO₂e value is immutable, even if the factor source is later updated.

**Status workflow — `PENDING → APPROVED | FLAGGED → LOCKED`:**

| Status | Meaning |
|--------|---------|
| `PENDING` | Freshly ingested, awaiting analyst review |
| `APPROVED` | Analyst confirmed the data looks correct |
| `FLAGGED` | Something looks suspicious — needs investigation |
| `LOCKED` | Approved and frozen for audit — no further edits allowed |

This is a simple state machine. We enforce transitions in application code (not the database) because:

- Django doesn't have native state-machine constraints.
- Business rules for valid transitions may change (e.g., "can a FLAGGED row go directly to LOCKED?").
- The `AuditLog` table records every transition, so invalid ones are detectable even if a bug allows them.

**`is_edited` flag:**

A boolean that flips to `True` if an analyst manually changes `normalized_value`, `normalized_unit`, `scope_category`, or any other derived field after initial ingestion. This is critical for auditors — they need to distinguish machine-normalised values from human-overridden ones.

---

### 4. `AuditLog`

| Field | Type | Notes |
|-------|------|-------|
| `emission_row` | FK → UniversalEmissionRow | Which row changed |
| `changed_by` | FK → User (nullable) | Who made the change |
| `changed_at` | DateTimeField (auto_now_add) | When |
| `old_status` | CharField | Status before the change |
| `new_status` | CharField | Status after the change |
| `note` | TextField (nullable) | Free-text reason (e.g. "Value corrected per client email 2025-03-15") |

**Why it exists:** The brief requires an audit trail. This is an **append-only log** — rows are never updated or deleted. Every status transition on an emission row produces one `AuditLog` entry.

**Why status-change tracking, not full field-level versioning:**

Full field-level audit (django-reversion, django-simple-history) captures every change to every field. That's powerful but expensive — both in storage and query complexity. For this prototype, status transitions are the primary audit concern:

- "Who approved this row?"
- "When was it locked?"
- "Was it ever flagged, and why?"

If field-level versioning becomes necessary (e.g., tracking changes to `normalized_value`), we would add `django-simple-history` to `UniversalEmissionRow`. The `AuditLog` table would remain as the lightweight, fast-query layer for status history.

**`old_status` and `new_status` are CharFields, not FK to an enum table:** These are snapshot values. Even if we rename a status in the future, historical audit entries should reflect what the status was *called at the time*, not what it's called now.

---

## How the Model Addresses Each Requirement

| Requirement | How it's handled |
|-------------|-----------------|
| **Multi-tenancy** | `ClientCompany` FK on `DataIngestionLog` and `UniversalEmissionRow`. Every query is tenant-scoped. |
| **Scope 1/2/3 categorisation** | `scope_category` enum on `UniversalEmissionRow` with GHG Protocol scope values. |
| **Source-of-truth tracking** | `DataIngestionLog` records which source, when, and who. `raw_payload` preserves the original data. `is_edited` flags human modifications. |
| **Unit normalisation** | `raw_payload` holds the original; `normalized_value` + `normalized_unit` hold the cleaned output. Separation makes the normalisation step explicit and auditable. |
| **Audit trail** | `AuditLog` is an append-only table recording every status transition with who, when, and why. |

---

## What We'd Ask the PM

1. **Do we need to track emission factor versions over time?** Currently we store the factor and its source per row. If factors are updated centrally, should we maintain a `EmissionFactor` lookup table with versioning?

2. **Should LOCKED rows be truly immutable at the DB level?** Right now, "locked" is enforced in application logic. A database trigger or row-level permission would be stronger but adds operational complexity.

3. **Multi-tenant access control:** Should users be scoped to a single client, or can one analyst work across multiple clients? This affects whether we need a `UserClientMembership` many-to-many table.

4. **Historical re-computation:** If an emission factor is corrected, should we re-compute `co2e_kg` for all affected rows? Or is the original calculation considered the source of truth once locked?
