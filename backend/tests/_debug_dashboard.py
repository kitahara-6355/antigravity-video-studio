import sys, os
base_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(base_dir, ".."))
os.chdir(os.path.join(base_dir, ".."))

try:
    from usage_tracker import usage_tracker
    summary = usage_tracker.get_daily_summary()
    print("summary keys:", list(summary.keys()))
    print("models type:", type(summary.get("models")))
    print("models:", summary.get("models"))
except Exception as e:
    import traceback
    traceback.print_exc()
