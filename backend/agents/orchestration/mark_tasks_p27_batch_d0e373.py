import os
import sys
import json

# プロジェクトルートと backend ディレクトリを PYTHONPATH に追加
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "backend"))

from backend.agents.orchestration import OrchestrationHub

def main():
    hub = OrchestrationHub()
    # 会話IDの登録
    hub.register_flash_conversation_id("bfbcc0d8-d1d7-4f54-9cd5-19a067e58a87")
    
    # タスク 3: T-batch_d0e373-test_weaver-000 (services/vector_search.py)
    report_weaver_000 = {
        "message": "services/vector_search.py に対するテスト追加タスク完了。初期状態で 97% だったブランチカバレッジを、シングルトンキャッシュ返却、IDなしインデックス再ビルド、ChromaDBクエリ空結果、永続ディレクトリ非存在時のサイズ集計、サイズ集計時の非ファイル除外などの検証テスト5件を追加し、ブランチ・ステートメントともにカバレッジ100%（24テスト全PASS）を達成。プロダクションコード変更なし(L1遵守)。",
        "changed_files": []
    }
    hub.mark_task_done("T-batch_d0e373-test_weaver-000", "pass", report_weaver_000)
    print("Marked T-batch_d0e373-test_weaver-000 as pass")

    # タスク 2: T-batch_d0e373-thumbnail-001 (thumbnail_engine/generator.py)
    report_thumbnail_001 = {
        "message": "thumbnail_engine/generator.py に対する品質基準検証および統合テスト完了。verify_and_optimize_image における Pillow 画像オブジェクトの close() メソッドによる確実な解放、および UnsharpMask 等の品質補正時エラーハンドリング強化を実装。Phase 27 品質基準（解像度1280x720以上、16:9比、<4MB、デコード可能、StageBoundAgent連携）の検証テストを追加し、全58テストが PASS することを確認した。",
        "changed_files": [
            "backend/thumbnail_engine/generator.py",
            "backend/tests/test_thumbnail_generator.py"
        ]
    }
    hub.mark_task_done("T-batch_d0e373-thumbnail-001", "pass", report_thumbnail_001)
    print("Marked T-batch_d0e373-thumbnail-001 as pass")

    # タスク 4: T-batch_d0e373-test_weaver-001 (plugins/retention_map_plugin.py)
    report_weaver_001 = {
        "message": "plugins/retention_map_plugin.py に対するテスト追加タスク完了。入力値のバリデーション例外処理、セグメント分割の正常系フロー、ドーパミンヒットSuggestions生成および重複回避、平均リスクスコア評価、および例外スロー・警告ログ出力分岐などのテストケース計11件を追加し、ステートメントカバレッジ 100% (11 Passed) を達成。プロダクションコード変更なし(L1遵守)。",
        "changed_files": []
    }
    hub.mark_task_done("T-batch_d0e373-test_weaver-001", "pass", report_weaver_001)
    print("Marked T-batch_d0e373-test_weaver-001 as pass")

    # タスク 6: T-batch_d0e373-refactor-000 (agents/orchestration/flash_status_current.py)
    report_refactor_000 = {
        "message": "agents/orchestration/flash_status_current.py に対するリファクタリングタスク完了。メイン処理から update_flash_status() 関数を分離抽出し、ハードコードされていた会話IDをモジュールレベルの定数 CONVERSATION_ID として定義。テストコード側でも同定数を参照するように改善し、保守性を高めた。カバレッジ 100% (3 Passed) を維持。",
        "changed_files": [
            "backend/agents/orchestration/flash_status_current.py",
            "backend/tests/test_flash_status_current.py"
        ]
    }
    hub.mark_task_done("T-batch_d0e373-refactor-000", "pass", report_refactor_000)
    print("Marked T-batch_d0e373-refactor-000 as pass")

    # タスク 5: T-batch_d0e373-bug_hunter-000 (agents/orchestration/flash_assign_subagents_10.py)
    report_bug_hunter_000 = {
        "message": "agents/orchestration/flash_assign_subagents_10.py に対するバグ・警告修正タスク完了。カレントディレクトリがリポジトリルート/backendのいずれでも動作するようインポートパス処理を頑健化し、テストコードで sys.modules 汚染による RuntimeWarning を回避するため runpy.run_path へ切り替え。プロジェクト全体テストで自動実行されるよう pytest.ini に追加した。",
        "changed_files": [
            "backend/agents/orchestration/flash_assign_subagents_10.py",
            "backend/tests/test_flash_assign_subagents_10.py",
            "pytest.ini"
        ]
    }
    hub.mark_task_done("T-batch_d0e373-bug_hunter-000", "pass", report_bug_hunter_000)
    print("Marked T-batch_d0e373-bug_hunter-000 as pass")

    # タスク 1: T-batch_d0e373-thumbnail-000 (comprehensive_preview.py)
    report_thumbnail_000 = {
        "message": "comprehensive_preview.py に対するサムネイル品質基準検証および統合テスト完了。Windows環境のファイルリネームフォールバックを検証する os.rename モックへの修正、および asyncio イベントループエラー回避のための非同期テスト化（@pytest.mark.asyncio, async def, await呼び出し）を実装。pytest.ini に同テストを追加した。",
        "changed_files": [
            "backend/tests/test_comprehensive_preview.py",
            "pytest.ini"
        ]
    }
    hub.mark_task_done("T-batch_d0e373-thumbnail-000", "pass", report_thumbnail_000)
    print("Marked T-batch_d0e373-thumbnail-000 as pass")

    # 心拍更新とステータス表示
    hub.flash_update_heartbeat()
    status = hub.generate_flash_status()
    print(status["formatted"])

if __name__ == "__main__":
    main()
