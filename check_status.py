import requests, json
d = requests.get("http://localhost:8000/api/pipeline/status").json()
print(f"Pipeline: {d['status']}")
for i, s in enumerate(d['stages']):
    icon = "✅" if s["status"]=="completed" else "🔄" if s["status"]=="running" else "❌" if s["status"]=="error" else "⏳"
    prog = f" [{s.get('progress',-1)}%]" if s.get('progress',-1)>=0 else ""
    print(f"  {icon} {s['name']}{prog}: {s.get('detail','')}")
if d.get("error"): print(f"\nError: {d['error']}")
if d.get("result"): print(f"\nResult: {json.dumps(d['result'], ensure_ascii=False, indent=2)}")
