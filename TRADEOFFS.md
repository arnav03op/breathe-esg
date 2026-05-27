# TRADEOFFS.md — What We Deliberately Skipped

Building an ESG data ingestion engine from scratch within a tight timeframe requires ruthless prioritization. Our goal was to prove the core mechanics: defensive parsing, data normalisation, dynamic CO₂e fallbacks, and a responsive analyst workflow. 

To achieve that, here are three major things we deliberately did *not* build, and why:

---

### 1. Dynamic Emission Factor (EF) Database
**What we skipped:** In our current implementation, the Emission Factors (like `2.5 kg CO2e/L` for Diesel or `0.71 kg CO2e/kWh` for the Indian grid) are hardcoded directly into the Python ingestion services. 
**Why:** Real-world emission factors are incredibly complex. They change annually (e.g., the EPA or DEFRA releases new tables every year), they are hyper-regional, and they depend on the specific calculation methodology chosen. Building a robust, version-controlled Emission Factor database table—along with the UI to map specific facility zip codes to specific EF versions—is a massive undertaking. Hardcoding a subset of representative EFs allowed us to prove that our Scope 1/2/3 calculation logic and fallbacks (like distance vs. spend-based proxies for travel) work perfectly, without getting bogged down in database management.

### 2. File and Row-Level Deduplication Engine
**What we skipped:** If you upload the exact same `sap_export.csv` file twice today, the system will happily ingest it twice, resulting in duplicate emission rows on the dashboard.
**Why:** Building a reliable deduplication engine requires computing cryptographic hashes for both the file contents and the individual row signatures (e.g., `hash(employee_id + expense_id + date)`). You also have to handle edge cases: what if the client updates one row in the CSV and re-uploads? Does it overwrite or append? Since our focus was strictly on parsing messy data and the analyst approval workflow, we skipped deduplication. We relied on the Analyst Dashboard's "Pending Review" table as the human-in-the-loop safety net to catch duplicates.

### 3. Authentication & Multi-Tenant Routing
**What we skipped:** The dashboard currently hardcodes uploads to `company_id=1` (Acme Corp) and the React frontend makes anonymous requests to the API without requiring a login or JWT token.
**Why:** ESG software is inherently multi-tenant; consultants manage dozens of clients. However, building login screens, role-based access control (RBAC), and tenant-switching dropdowns is standard boilerplate that every web app needs. It doesn't prove our ability to solve complex sustainability engineering problems. We structured the database defensively (every row is tied to a `ClientCompany` and `DataIngestionLog`), but we bypassed the frontend auth layer entirely so we could dedicate 100% of our time to the data ingestion pipeline and the review interface.
