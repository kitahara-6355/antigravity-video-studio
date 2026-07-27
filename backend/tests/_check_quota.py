import urllib.request, json
try:
    r = urllib.request.urlopen("http://localhost:8000/api/usage/dashboard", timeout=10)
    d = json.loads(r.read())
    for m in d.get("models", []):
        print(f"{m['model']}: {m['used']}/{m['daily_limit']} ({m.get('alert_level','?')})")
except Exception as e:
    if hasattr(e, 'read'):
        body = e.read().decode('utf-8', errors='replace')
        print(f"ERROR {e.code}: {body[:300]}")
    else:
        print(f"ERROR: {e}")

# Also check a simple endpoint
try:
    r = urllib.request.urlopen("http://localhost:8000/api/pipeline/status", timeout=5)
    print(f"\nPipeline status: OK ({r.status})")
except Exception as e2:
    print(f"\nPipeline status: {e2}")
