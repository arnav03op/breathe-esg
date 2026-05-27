"""API endpoint smoke test."""
import json
import urllib.request


BASE = "http://127.0.0.1:8000/api"


def get_json(path):
    url = f"{BASE}{path}"
    resp = urllib.request.urlopen(url)
    return resp.status, json.loads(resp.read())


# Test 1: List emissions
print("=== GET /api/emissions/ ===")
code, data = get_json("/emissions/?format=json")
print(f"Status: {code}")
print(f"Count: {data['count']}")
print(f"First row status: {data['results'][0]['status']}")
print()

# Test 2: Filter by status=FLAGGED
print("=== GET /api/emissions/?status=FLAGGED ===")
_, data = get_json("/emissions/?status=FLAGGED&format=json")
print(f"Flagged rows: {data['count']}")
print()

# Test 3: Filter by scope
print("=== GET /api/emissions/?scope_category=SCOPE_3 ===")
_, data = get_json("/emissions/?scope_category=SCOPE_3&format=json")
print(f"Scope 3 rows: {data['count']}")
print()

# Test 4: Summary
print("=== GET /api/emissions/summary/ ===")
_, data = get_json("/emissions/summary/?format=json")
print(json.dumps(data, indent=2))
print()

# Test 5: Ingestion logs
print("=== GET /api/ingestion-logs/ ===")
_, data = get_json("/ingestion-logs/?format=json")
print(f"Ingestion logs: {data['count']}")
for log in data["results"]:
    print(f"  Log {log['id']}: {log['source_type']} - {log['status']}")
print()

# Test 6: Detail with nested ingestion log
print("=== GET /api/emissions/{id}/ (detail) ===")
_, list_data = get_json("/emissions/?format=json")
first_id = list_data["results"][0]["id"]
_, detail = get_json(f"/emissions/{first_id}/?format=json")
print(f"Row {detail['id']}: {detail['sub_category']} | {detail['status']}")
print(f"Ingestion log source: {detail['ingestion_log']['source_type']}")
print(f"Ingestion log uploaded_by: {detail['ingestion_log']['uploaded_by_username']}")
print()

print("=== ALL API TESTS PASSED ===")
