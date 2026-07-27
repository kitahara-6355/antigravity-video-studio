import os
import sys
import json
import traceback

# プロジェクトルートと backend ディレクトリを PYTHONPATH に追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
backend_dir = os.path.join(project_root, "backend")
sys.path.insert(0, project_root)
sys.path.insert(1, backend_dir)

from backend.agents.orchestration import OrchestrationHub

def main():
    """
    タスク完了マークスクリプトのメイン関数。
    OrchestrationHubを介してタスクをpassとしてマークし、レポートを送信する。
    例外が発生した場合はエラーログを出力し、技術負債台帳への登録を行う。
    """
    try:
        hub = OrchestrationHub()
        # Flash conversation ID
        hub.register_flash_conversation_id("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
        
        # 心拍更新
        hub.flash_update_heartbeat()
        
        # 1. T-batch_449dfb-test_weaver-000 完了マーク
        hub.mark_task_done("T-batch_449dfb-test_weaver-000", "pass", {
            "message": "prediction_validator.pyへのユニットテスト追加。テストケース4件追加し、エッジケースへの逆引きを向上。",
            "changed_files": [
                "backend/tests/test_prediction_validator.py"
            ]
        })
        print("Marked T-batch_449dfb-test_weaver-000 as pass")
        
        # 2. T-batch_449dfb-refactor-000 完了マーク
        hub.mark_task_done("T-batch_449dfb-refactor-000", "pass", {
            "message": "mark_tasks_multi.pyのリファクタリング。関数分割、命名改善、デッドコード削除。テスト全PASS、カバレッジ維持。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_multi.py",
                "tests/test_mark_tasks_p27_multi.py"
            ]
        })
        print("Marked T-batch_449dfb-refactor-000 as pass")

        # 3. T-batch_449dfb-test_weaver-001 完了マーク
        hub.mark_task_done("T-batch_449dfb-test_weaver-001", "pass", {
            "message": "schema_migration.pyのテストカバレッジを100%に向上。JSONDecodeError/OSErrorのハンドリングテストを追加。",
            "changed_files": [
                "backend/tests/test_ux_verification/test_schema_migration.py"
            ]
        })
        print("Marked T-batch_449dfb-test_weaver-001 as pass")

        # 4. T-batch_449dfb-thumbnail-000 完了マーク
        hub.mark_task_done("T-batch_449dfb-thumbnail-000", "pass", {
            "message": "generator.pyの適応型コントラスト・輝度補正、解像度適応型シャープネス、一時ファイル削除確実化、sqlite3デッドロック耐性向上、および境界値テスト追加。",
            "changed_files": [
                "backend/thumbnail_engine/generator.py",
                "backend/tests/test_thumbnail_generator.py"
            ]
        })
        print("Marked T-batch_449dfb-thumbnail-000 as pass")

        # 5. T-batch_449dfb-thumbnail-001 完了マーク
        hub.mark_task_done("T-batch_449dfb-thumbnail-001", "pass", {
            "message": "thumbnail_analyzer.pyのグラデーションコサイン補間平滑化、テキスト・バナー配色の自動反転・最適化、詳細例外検知、ファイル競合gc強制解放、および境界値・不完全画像検証テスト追加。",
            "changed_files": [
                "backend/services/thumbnail_analyzer.py",
                "backend/tests/test_thumbnail_analyzer.py"
            ]
        })
        print("Marked T-batch_449dfb-thumbnail-001 as pass")

        # 6. T-batch_449dfb-bug_hunter-000 完了マーク
        hub.mark_task_done("T-batch_449dfb-bug_hunter-000", "pass", {
            "message": "get_batch_details.py of バグ修正。インポートパス設定を絶対パスベースに変更しModuleNotFoundErrorを防止。",
            "changed_files": [
                "backend/agents/orchestration/get_batch_details.py",
                "tests/test_get_batch_details.py",
                "pytest.ini"
            ]
        })
        print("Marked T-batch_449dfb-bug_hunter-000 as pass")
        
        # バッチ全体のレポート送信
        report_data = {
            "passed": 6,
            "failed": 0,
            "skipped": 0,
            "total": 6,
        }
        hub.submit_batch_report("batch_449dfb", report_data)
        
        # 最新ステータス表示
        hub.flash_update_heartbeat()
        status = hub.generate_flash_status()
        print(status["formatted"])
        
    except Exception as e:
        print(f"Error occurred: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        
        # テスト実行中はデフォルトで技術負債の登録をスキップ（FORCE_DEBT_REGISTRATIONが設定されている場合のみ登録）
        if "pytest" not in sys.modules or os.environ.get("FORCE_DEBT_REGISTRATION"):
            try:
                from backend.agents.memory.technical_debt import TechnicalDebtStore
                store = TechnicalDebtStore()
                store.register_debt(
                    category="ACCEPTED_SAFETY",
                    file_path="agents/orchestration/mark_tasks_p27_batch_449dfb.py",
                    line_number=91,
                    pattern="except Exception as e:",
                    cause_pattern="DP-01",
                    fix_pattern="OrchestrationHub呼び出しのエラーハンドリング追加",
                    registered_by="Phase 33 bug_hunter #5",
                    notes=f"OrchestrationHub例外発生時のエラーハンドリング: {e}"
                )
            except Exception as tdr_err:
                print(f"Failed to register technical debt: {tdr_err}", file=sys.stderr)
                
        raise e

if __name__ == "__main__":
    main()
