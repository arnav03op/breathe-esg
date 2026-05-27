import urllib.request
import urllib.error
import json
import os

url = "http://127.0.0.1:8000/api/upload/sap/"
file_path = "sample_data/sap_export.csv"

# Simple multipart form-data without external libraries
boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
body = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="company_id"\r\n\r\n'
    f"1\r\n"
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="sap_export.csv"\r\n'
    f"Content-Type: text/csv\r\n\r\n"
).encode('utf-8')

with open(file_path, "rb") as f:
    body += f.read()

body += f"\r\n--{boundary}--\r\n".encode('utf-8')

req = urllib.request.Request(url, data=body)
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')

try:
    response = urllib.request.urlopen(req)
    print("Success:", response.read().decode('utf-8'))
except urllib.error.HTTPError as e:
    print(f"Failed with {e.code}:")
    print(e.read().decode('utf-8'))
