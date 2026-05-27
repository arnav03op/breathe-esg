"""Full end-to-end smoke test for SAP + Utility + Travel ingestion."""
import django
import os
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from emissions.models import ClientCompany, DataIngestionLog, UniversalEmissionRow

# Clear old test data
UniversalEmissionRow.objects.all().delete()
DataIngestionLog.objects.all().delete()
print("=== Cleared old data ===\n")

User = get_user_model()
user = User.objects.get(username="testadmin")
co = ClientCompany.objects.get(slug="acme-corp")

# --- SAP ---
from emissions.services.sap_ingestion import ingest_sap_csv

print("========== SAP INGESTION ==========")
sap_result = ingest_sap_csv("sample_data/sap_export.csv", co.pk, user.pk)
print(json.dumps(sap_result, indent=2))
print()

# --- Utility ---
from emissions.services.utility_ingestion import ingest_utility_csv

print("========== UTILITY INGESTION ==========")
util_result = ingest_utility_csv("sample_data/utility_export.csv", co.pk, user.pk)
print(json.dumps(util_result, indent=2))
print()

# --- Travel ---
from emissions.services.travel_ingestion import ingest_travel_json

print("========== TRAVEL INGESTION ==========")
travel_result = ingest_travel_json("sample_data/travel_export.json", co.pk, user.pk)
print(json.dumps(travel_result, indent=2))
print()

# --- Summary ---
print("========== DATABASE SUMMARY ==========")
total_logs = DataIngestionLog.objects.count()
completed = DataIngestionLog.objects.filter(status="COMPLETED").count()
failed = DataIngestionLog.objects.filter(status="FAILED").count()
print(f"Ingestion Logs:  {total_logs}")
print(f"  COMPLETED:     {completed}")
print(f"  FAILED:        {failed}")
print()

total_rows = UniversalEmissionRow.objects.count()
pending = UniversalEmissionRow.objects.filter(status="PENDING").count()
flagged = UniversalEmissionRow.objects.filter(status="FLAGGED").count()
scope1 = UniversalEmissionRow.objects.filter(scope_category="SCOPE_1").count()
scope2 = UniversalEmissionRow.objects.filter(scope_category="SCOPE_2").count()
scope3 = UniversalEmissionRow.objects.filter(scope_category="SCOPE_3").count()
print(f"Emission Rows:   {total_rows}")
print(f"  PENDING:       {pending}")
print(f"  FLAGGED:       {flagged}")
print(f"  SCOPE_1:       {scope1}")
print(f"  SCOPE_2:       {scope2}")
print(f"  SCOPE_3:       {scope3}")
print()

# --- All rows ---
print("========== ALL ROWS ==========")
for r in UniversalEmissionRow.objects.select_related("ingestion_log").order_by("pk"):
    src = r.ingestion_log.get_source_type_display()
    flag = " [FLAGGED]" if r.status == "FLAGGED" else ""
    val = f"{r.normalized_value:>12,.1f}" if r.normalized_value is not None else "        None"
    co2 = f"{r.co2e_kg:>10,.2f}" if r.co2e_kg is not None else "      None"
    unit = r.normalized_unit or "---"
    name = (r.facility_name or "—").replace("\u2192", "->")
    print(
        f"  {src:7s} | {name:20s} | {r.sub_category:15s} | "
        f"{val} {unit:6s} | co2e={co2} | {r.scope_category}{flag}"
    )
    if r.error_notes:
        print(f"           => {r.error_notes}")

print("\n=== ALL CHECKS PASSED ===")
