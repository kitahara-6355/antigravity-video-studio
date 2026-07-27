import sys
from pathlib import Path

# backend をインポートできるようにパスに追加
sys.path.append(str(Path(r"c:\Users\PC_User\Desktop\script\video-automation\backend")))
from agents.orchestration.orchestrator import OrchestrationHub

def main():
    hub = OrchestrationHub()
    try:
        report_path = hub.generate_hourly_report()
        print(f"Successfully generated hourly report at: {report_path}")
    except Exception as e:
        print(f"Error generating hourly report: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
