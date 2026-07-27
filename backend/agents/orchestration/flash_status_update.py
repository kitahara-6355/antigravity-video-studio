import os
import sys
import argparse

def main(argv=None):
    """Update flash session heartbeat and print status.
    
    This function parses arguments, resolves the flash conversation ID,
    updates the heartbeat via OrchestrationHub, and prints the formatted status.
    
    Args:
        argv (list, optional): Command line arguments. Defaults to None.
    """
    # 1. パス解決: プロジェクトルートと backend ディレクトリを sys.path に追加
    # インポートが 'backend...' から始まるものと、'agents...'（backend/ 直下）から始まるものを両方解決可能にする
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
    backend_dir = os.path.join(project_root, "backend")
    
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
        
    from backend.agents.orchestration import OrchestrationHub

    parser = argparse.ArgumentParser(description="Update flash session heartbeat and print status.")
    parser.add_argument(
        "--conversation-id", "-id",
        type=str,
        help="Specify the flash conversation ID."
    )
    parser.add_argument(
        "--heartbeat-only",
        action="store_true",
        help="Only update heartbeat and skip printing status."
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only print status and skip updating heartbeat."
    )
    
    args = parser.parse_args(argv)
    
    try:
        hub = OrchestrationHub()
        
        # 1. Conversation ID の解決
        conv_id = args.conversation_id
        if not conv_id:
            conv_id = os.environ.get("FLASH_CONVERSATION_ID") or os.environ.get("CONVERSATION_ID")
            
        if not conv_id:
            try:
                session = hub.get_flash_session()
                conv_id = session.get("conversation_id") if isinstance(session, dict) else None
            except (OSError, ValueError, KeyError, AttributeError):
                pass
                
        if not conv_id:
            conv_id = "ce05d36d-f2c8-452b-8ea9-9053a1e718a0"
            
        # IDの登録
        hub.register_flash_conversation_id(conv_id)
        
        # 2. 心拍更新
        if not args.status_only:
            hub.flash_update_heartbeat()
            
        # 3. ステータス表示
        if not args.heartbeat_only:
            status = hub.generate_flash_status()
            if isinstance(status, dict) and "formatted" in status:
                print(status["formatted"])
            else:
                raise ValueError("Status dictionary is empty or missing 'formatted' key.")
                
    except (OSError, ValueError, KeyError, AttributeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        try:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            store.register_debt(
                category="MINOR_INFRA",
                file_path="backend/agents/orchestration/flash_status_update.py",
                line_number=74,
                pattern="except Exception as e:",
                cause_pattern="DP-01",
                fix_pattern="具体的な例外の捕捉またはロギングの洗練",
                registered_by="Phase 33 bug_hunter #10",
                notes=f"予期せぬ例外キャッチ: {type(e).__name__}: {str(e)}"
            )
        except Exception:
            pass
        print(f"Unexpected Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()

