import os
import sys



project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, project_root)
backend_path = os.path.join(project_root, 'backend')
sys.path.insert(0, backend_path)

from backend.agents.orchestration import OrchestrationHub

CONVERSATION_ID = "bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87"

BATCH_TASKS = [
    {
        "id": "T-batch_4d4133-test_weaver-001",
        "status": "pass",
        "report": {
            "message": "agents/orchestration/mark_and_submit_batch_complete.py に対するテスト追加タスク完了。もともと100%だったカバレッジを維持しつつ、堅牢性を高めるために main 関数の例外ハンドリングの検証テスト2件を追加し、計8テストすべてが正常に PASS することを確認。プロダクションコード変更なし(L1遵守)。",
            "changed_files": []
        }
    },
    {
        "id": "T-batch_4d4133-test_weaver-000",
        "status": "pass",
        "report": {
            "message": "services/evolution_sync_service.py に対するテスト追加タスク完了。もともと100%だったステートメント・ブランチカバレッジを維持しつつ、堅牢性を高めるために finalize_result で一部キーが欠落している場合のデフォルトフォールバック検証、および進化ログファイル読み出し時の一部キー欠落のフォールバック検証テストを追加し、計36テストすべてが正常に PASS することを確認。プロダクションコード変更なし(L1遵守)。",
            "changed_files": []
        }
    },
    {
        "id": "T-batch_4d4133-bug_hunter-000",
        "status": "pass",
        "report": {
            "message": "gemini_chunker_fixed.py に対するバグ・警告修正タスク完了。Windows環境でのバッファサイズ不一致による RuntimeWarning を解決するため、sys.stdout/stderr の UTF-8 強制出力を reconfigure() メソッド経由に改善。非対応ストリームのフォールバック動作を検証する新規テストを追加し、全17テストが警告・エラーなしで正常に PASS することを確認。",
            "changed_files": [
                "backend/gemini_chunker_fixed.py",
                "backend/tests/test_shared/test_cov_gemini_chunker_fixed.py"
            ]
        }
    },
    {
        "id": "T-batch_4d4133-thumbnail-001",
        "status": "pass",
        "report": {
            "message": "services/thumbnail_analyzer.py に対する品質基準検証および統合テスト完了。解像度(1280x720以上)、アスペクト比(16:9)、ファイルサイズ(<4MB)、アトミックなファイル書き込みとリソース解放によるメモリリーク防止、StageBoundAgent連携による自動リトライおよびDB保存の動作を境界値・破損画像データ検知テスト含めて検証し、全67テスト of PASSを確認。プロダクションコード変更なし(L2遵守)。",
            "changed_files": []
        }
    },
    {
        "id": "T-batch_4d4133-thumbnail-000",
        "status": "pass",
        "report": {
            "message": "comprehensive_preview.py に対するサムネイル品質向上およびエラーハンドリング改善タスク完了。16:9アスペクト比不適合時のPreviewImageInvalidAspectRatioError例外追加、行頭禁則処理による自動折り返し調整、ImageStat.Statを用いた半透明座布団不透明度の動的決定、ヒストグラム平坦化と原画ブレンド(0.45)によるプレミアム品質補正、およびファイルロック時3回リトライを実装。アスペクト比精密境界検証等のテストを追加し、全42テストが正常に PASS することを確認した。",
            "changed_files": [
                "backend/comprehensive_preview.py",
                "comprehensive_preview.py",
                "tests/test_comprehensive_preview.py"
            ]
        }
    },
    {
        "id": "T-batch_4d4133-refactor-000",
        "status": "pass",
        "report": {
            "message": "services/performance_budget_manager.py に対するリファクタリング完了。DEFAULT_WORKER_BUDGETSがDict型であることを受けて不要なisinstance判定を行うデッドコードを削除し、_parse_single_worker_budget や _update_single_worker_budget などの命名改善・関数分割（単一責任の原則適用）を実施。カバレッジ100%を維持したまま、全テストが PASS することを確認した。",
            "changed_files": [
                "backend/services/performance_budget_manager.py"
            ]
        }
    }
]

def mark_batch_tasks(hub: OrchestrationHub) -> None:
    """バッチ内の全タスクを完了としてマークする"""
    for task in BATCH_TASKS:
        hub.mark_task_done(task["id"], task["status"], task["report"])
        print(f"Marked {task['id']} as {task['status']}")

def main() -> None:
    hub = OrchestrationHub()
    hub.register_flash_conversation_id(CONVERSATION_ID)
    
    # タスク完了のマーク
    mark_batch_tasks(hub)
    
    # 心拍更新とステータス表示
    hub.flash_update_heartbeat()
    status = hub.generate_flash_status()
    print(status["formatted"])

if __name__ == "__main__":
    main()

