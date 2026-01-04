import urllib.request
import json
try:
    with urllib.request.urlopen("http://localhost:8000/api/documents", timeout=5) as response:
        print(f"Status: {response.getcode()}")
        print(f"Body: {response.read().decode()}")
except Exception as e:
    print(f"Error: {e}")
