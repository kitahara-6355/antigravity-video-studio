import sys
import os
import json

# パスを追加
sys.path.append(os.path.abspath("backend"))
sys.path.append(os.path.abspath("."))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # バッチ報告
    try:
        hub.submit_batch_report('batch_43915c', {'passed': 6, 'failed': 0, 'skipped': 0, 'total': 6})
    except ValueError as e:
        print(f"Validation error: {e}")
    except OSError as e:
        print(f"I/O error during submit: {e}")
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        print(f"Data format error: {e}")
        
    # ステータス表示
    status = hub.generate_flash_status()
    print("STATUS_START")
    print(json.dumps(status))
    print("STATUS_END")

if __name__ == "__main__":
    main()
