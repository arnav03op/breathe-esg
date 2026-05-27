import urllib.request
import urllib.error
from html.parser import HTMLParser

class ExceptionParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_exception = False
        self.exception_text = ""
        self.capture = False
        
    def handle_starttag(self, tag, attrs):
        if tag == "textarea" and dict(attrs).get("id") == "traceback_area":
            self.capture = True
            
    def handle_data(self, data):
        if self.capture:
            self.exception_text += data
            
    def handle_endtag(self, tag):
        if tag == "textarea" and self.capture:
            self.capture = False

url = "http://127.0.0.1:8000/api/upload/sap/"
file_path = "sample_data/sap_export.csv"
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
    print("Success")
except urllib.error.HTTPError as e:
    html = e.read().decode('utf-8', errors='ignore')
    parser = ExceptionParser()
    parser.feed(html)
    print("Exception Traceback:")
    print(parser.exception_text)
