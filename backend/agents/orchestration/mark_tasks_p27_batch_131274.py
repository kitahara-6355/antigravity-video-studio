import os
import sys

# プロジェクトルートを PYTHONPATH に追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from backend.agents.orchestration import OrchestrationHub

# バッチに属するタスクの定義
BATCH_TASKS = [
    {
        "id": "T-batch_131274-test_weaver-000",
        "status": "pass",
        "report": {
            "message": "agents/orchestration/copy_artifacts_pipeline_tools.py に対するテスト追加タスク完了。もともと100%だったステートメント・ブランチカバレッジの堅牢性を高めるため、一部ファイル混在、os.makedirs エラー、shutil.copy2 エラーの例外伝播検証テストを追加し、計5テストすべてが正常に PASS することを確認。プロダクションコード変更なし(L1遵守)。",
            "changed_files": []
        }
    },
    {
        "id": "T-batch_131274-bug_hunter-000",
        "status": "pass",
        "report": {
            "message": "agents/orchestration/submit_and_next.py に対するバグ修正および警告解消タスク完了。runpy 実行時の重複警告(RuntimeWarning)を patch.dict(sys.modules) で解消し、引数の型エラー検証時の ValueError キャッチで exit(1) 終了する堅牢化を実装。例外伝播や引数型エラーのテストを追加し全PASSを確認（L2遵守、変更2ファイル）。",
            "changed_files": [
                "backend/agents/orchestration/submit_and_next.py",
                "tests/test_submit_and_next.py"
            ]
        }
    },
    {
        "id": "T-batch_131274-thumbnail-000",
        "status": "pass",
        "report": {
            "message": "thumbnail_engine/generator.py に対する品質基準境界値検証およびStageBoundAgent自動リトライフロー連携のテスト追加タスクが完了。解像度(>=1280x720)、アスペクト比(16:9)、ファイルサイズ(<4MB)、破損チェックおよびStageBoundAgentのSQLite保存、最大5回自動リトライ of インテグレーションテストを実装し、全26テストがPASSすることを確認した。",
            "changed_files": [
                "tests/test_generator_thumbnail.py"
            ]
        }
    },
    {
        "id": "T-batch_131274-refactor-000",
        "status": "pass",
        "report": {
            "message": "agents/vector_utils.py のリファクタリングおよびカバレッジ保証タスク完了。cosine_similarity計算での到達不能デッドコード(try-exceptブロック)を除去し、プライベートバリデータ関数(_is_valid_numeric_list)への抽出と計算パラメータ検証・ノルム計算の明確な分離を適用。追加テストケース(cosine_similarity_empty_listなど)の実装によりカバレッジ100%を維持。",
            "changed_files": [
                "backend/agents/vector_utils.py",
                "backend/tests/test_vector_utils_additional.py"
            ]
        }
    },
    {
        "id": "T-batch_131274-thumbnail-001",
        "status": "pass",
        "report": {
            "message": "services/thumbnail_analyzer.py に対する品質基準検証および統合テスト完了。解像度(1280x720以上)、アスペクト比(16:9)、ファイルサイズ(<4MB)、アトミックなファイル書き込みとリソース解放によるメモリリーク防止、StageBoundAgent連携による自動リトライおよびDB保存の動作を境界値・破損画像データ検知テスト含めて検証し、全96テストのPASSを確認。プロダクションコード変更なし(L2遵守)。",
            "changed_files": []
        }
    },
    {
        "id": "T-batch_131274-test_weaver-001",
        "status": "pass",
        "report": {
            "message": "routers/quality.py に対するテスト追加タスク完了。もともと100%だったステートメント・ブランチカバレッジを維持しつつ、堅牢性を高めるために run_cleanup で req=None が渡された時の正常処理、quick_decision や approve_review で timestamp や approved_at が空の時の自動補完の検証テスト3件を追加し、計15テストすべてが正常に PASS することを確認。プロダクションコード変更なし(L1遵守)。",
            "changed_files": []
        }
    }
]

CONVERSATION_ID = "bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87"

def mark_batch_tasks_done(hub: OrchestrationHub) -> None:
    """バッチに定義された各タスクを OrchesrationHub で完了としてマークします。"""
    for task in BATCH_TASKS:
        hub.mark_task_done(task["id"], task["status"], task["report"])
        print(f"Marked {task['id']} as {task['status']}")

def main() -> None:
    hub = OrchestrationHub()
    # 会話IDの登録
    hub.register_flash_conversation_id(CONVERSATION_ID)
    
    # 各タスクのマーク処理を実行
    mark_batch_tasks_done(hub)
    
    # 心拍更新とステータス表示
    hub.flash_update_heartbeat()
    status = hub.generate_flash_status()
    print(status["formatted"])

if __name__ == "__main__":
    main()

