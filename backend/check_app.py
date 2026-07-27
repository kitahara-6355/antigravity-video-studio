import sys
import os

# Add src to path so main.py can import its dependencies
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))
# Add backend to path too
sys.path.append(os.path.dirname(__file__))

print("Importing main...")
try:
    from main import app
    print("ROUTES FOUND:", len(app.routes))
    for r in app.routes:
        print(f"{r.path} [{r.name}]")
except ImportError as e:
    print(f"ImportError: Failed to import 'main' or its dependencies: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
except Exception as e:
    print(f"Unexpected error during application initialization: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
