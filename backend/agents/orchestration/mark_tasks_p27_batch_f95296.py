import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'backend'))
from backend.agents.orchestration import OrchestrationHub
import json

def main():
    hub = OrchestrationHub()
    # Flash conversation ID
    hub.register_flash_conversation_id("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    
    # 心拍更新
    hub.flash_update_heartbeat()
    
    # 1. T-batch_f95296-test_weaver-000 完了マーク
    hub.mark_task_done("T-batch_f95296-test_weaver-000", "pass", {
        "message": "generate_status.pyへのユニットテスト追加。テストケース5件追加し、エッジケースへの逆引きを向上。",
        "changed_files": [
            "backend/tests/scratch/test_generate_status.py"
        ]
    })

    # 2. T-batch_f95296-test_weaver-001 完了マーク
    hub.mark_task_done("T-batch_f95296-test_weaver-001", "pass", {
        "message": "agents/graph.pyへのユニットテスト追加。例外再送出やエクスポート整合性のテストを追加し、堅牢性を向上。",
        "changed_files": [
            "backend/tests/test_graph.py"
        ]
    })

    # 3. T-batch_f95296-bug_hunter-000 完了マーク
    hub.mark_task_done("T-batch_f95296-bug_hunter-000", "pass", {
        "message": "create_subtitle_samples.pyのテストバグ修正。確実に存在しないランダムなパスの動的生成により、ファイル書き込み例外テストを確実に通過させ、デフォルトフォルダへのフォールバック挙動の検証テストも追加。",
        "changed_files": [
            "backend/tests/test_create_subtitle_samples.py"
        ]
    })

    # 4. T-batch_f95296-refactor-000 完了マーク
    hub.mark_task_done("T-batch_f95296-refactor-000", "pass", {
        "message": "mark_task_f076d6_005_done.pyのリファクタリング。命名改善、関数分割、デッドコード削除。テスト全PASS、カバレッジ維持。",
        "changed_files": [
            "scratch/mark_task_f076d6_005_done.py",
            "backend/scratch/mark_task_f076d6_005_done.py",
            "backend/tests/test_scratch_mark_task_f076d6_005_done.py"
        ]
    })

    # 5. T-batch_f95296-thumbnail-001 完了マーク
    hub.mark_task_done("T-batch_f95296-thumbnail-001", "pass", {
        "message": "thumbnail_analyzer.pyの画像品質向上（スーパサンプリング、プレミアムダブルフレーム、L字装飾、Glassmorphismバナー、日本語フォールバック）、例外安全設計、および品質検証テスト追加。",
        "changed_files": [
            "backend/services/thumbnail_analyzer.py",
            "tests/test_thumbnail_analyzer_quality.py"
        ]
    })

    # 6. T-batch_f95296-thumbnail-000 完了マーク
    hub.mark_task_done("T-batch_f95296-thumbnail-000", "pass", {
        "message": "comprehensive_preview.pyのエラーハンドリング修正。選択的モックによるフォントロード例外テスト通過、およびPillowバージョン差異/保存/Windowsリネーム失敗時リトライの検証テストを追加。",
        "changed_files": [
            "backend/comprehensive_preview.py",
            "backend/tests/test_comprehensive_preview_thumbnail.py"
        ]
    })
    
    print("TASKS_MARKED_DONE")

    # 最新ステータス表示
    status = hub.generate_flash_status()
    print("FLASH_STATUS:" + json.dumps(status))

if __name__ == "__main__":
    main()
