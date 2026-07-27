import warnings
warnings.simplefilter('error')
import sys
import json
import pytest
import runpy
from unittest.mock import MagicMock, patch
from backend.agents.orchestration import mark_tasks_p27_multi14

def test_main_success(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi14.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            mark_tasks_p27_multi14.main()
        
    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    # flash_update_heartbeat は開始時と終了前の計2回呼ばれる
    assert mock_hub_instance.flash_update_heartbeat.call_count == 2
    
    assert mock_hub_instance.mark_task_done.call_count == 2
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_ac027b-ds-ds-025",
        "pass",
        {
            "message": "バッチ batch_b5de01 でのタイムアウト失敗原因（ハング）に対し、subprocess.Popenモック安全規約および心拍レジリエンス規約、タイムアウト処理の改善（OrchestrationHubによる600秒タスクkillとタイムアウト復旧）が適用済みであることを確認し、対策完了と判定。",
            "changed_files": []
        }
    )
    mock_hub_instance.mark_task_done.assert_any_call(
        "T-batch_ac027b-test_weaver-000",
        "pass",
        {
            "message": "test_youtube_optimizer_router.py において routers/youtube_optimizer.py に対する 125 件のテストが 100% PASS し、カバレッジも 99% 達成していることを確認。",
            "changed_files": [
                "backend/tests/test_youtube_optimizer_router.py"
            ]
        }
    )
    
    # バッチ報告の検証
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_ac027b",
        {
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "total": 2,
        }
    )
    
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "ok"}' in captured.out

def test_main_as_script(capsys):
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "script_ok"}
    
    import os
    script_path = os.path.abspath("backend/agents/orchestration/mark_tasks_p27_multi14.py")
    
    with patch("backend.agents.orchestration.mark_tasks_p27_multi14.OrchestrationHub", return_value=mock_hub_instance):
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
            runpy.run_path(script_path, run_name="__main__")

    mock_hub_instance.register_flash_conversation_id.assert_called_once_with("129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096")
    assert mock_hub_instance.flash_update_heartbeat.call_count == 2
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_ac027b",
        {
            "passed": 2,
            "failed": 0,
            "skipped": 0,
            "total": 2,
        }
    )
    mock_hub_instance.generate_flash_status.assert_called_once()
    
    captured = capsys.readouterr()
    assert "TASKS_MARKED_DONE" in captured.out
    assert "BATCH_SUBMITTED" in captured.out
    assert "FLASH_STATUS" in captured.out
    assert '{"status": "script_ok"}' in captured.out


def test_sys_path_insertion(capsys):
    import sys
    import importlib
    import os
    from pathlib import Path
    
    # 堅牢なプロジェクトルート特定
    current = Path(__file__).resolve()
    project_root = None
    for parent in [current] + list(current.parents):
        if (parent / "backend").exists() or (parent / "pytest.ini").exists():
            project_root = parent
            break
    if project_root is None:
        project_root = current.parents[1]
        
    norm_root = os.path.normcase(os.path.abspath(str(project_root)))
    norm_backend = os.path.normcase(os.path.abspath(str(project_root / 'backend')))
    
    # sys.path から対象パスを一時的に除去（表記ゆれも考慮）
    original_path = list(sys.path)
    sys.path = [
        p for p in sys.path 
        if os.path.normcase(os.path.abspath(p)) != norm_root 
        and os.path.normcase(os.path.abspath(p)) != norm_backend
    ]
    
    mock_hub_instance = MagicMock()
    mock_hub_instance.generate_flash_status.return_value = {"status": "ok"}
    
    try:
        with patch("backend.agents.orchestration.mark_tasks_p27_multi14.OrchestrationHub", return_value=mock_hub_instance):
            with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub_instance):
                importlib.reload(mark_tasks_p27_multi14)
                mark_tasks_p27_multi14.main()
                
                # reload によって sys.path に追加されたことを確認（元の sys.path に戻す前に検証）
                normalized_sys_path = {os.path.normcase(os.path.abspath(p)) for p in sys.path if p}
                assert norm_root in normalized_sys_path
                assert norm_backend in normalized_sys_path
    finally:
        sys.path = original_path


def test_add_to_sys_path_behavior():
    import sys
    import os
    from pathlib import Path
    from backend.agents.orchestration.mark_tasks_p27_multi14 import _add_to_sys_path

    original_path = list(sys.path)
    try:
        # 2026-07-26: 以前は "C:/dummy/test/path1" と "c:\dummy\test\path1" を
        # 「表記ゆれ」として同一視していたが、これは Windows でしか成立しない。
        # Linux ではバックスラッシュは区切り文字ではなく、後者は
        # "c:\dummy\test\path1" という1個のファイル名になるため別パス扱いになり、
        # 重複回避のアサーションが assert 2 == 1 で失敗していた。
        #
        # 検証したいのは「正規化して等しいパスは二重登録しない」ことなので、
        # 実行中のプラットフォームの正規化規則で等価なペアを作る。
        base = Path("dummy") / "test" / "path1"
        dummy_path_1 = base
        # normcase は Windows では小文字化＋区切り統一、POSIX では恒等変換
        dummy_path_2 = Path(os.path.normcase(str(base)))

        # 1. 新規追加
        sys.path = []
        _add_to_sys_path(dummy_path_1)
        assert len(sys.path) == 1
        assert sys.path[0] == str(dummy_path_1.resolve())

        # 2. 重複追加の回避（正規化して等価なパス）
        _add_to_sys_path(dummy_path_2)
        assert len(sys.path) == 1  # 増えていないこと

        # 3. 異なるパスの追加
        dummy_path_3 = Path("dummy") / "test" / "path2"
        _add_to_sys_path(dummy_path_3)
        assert len(sys.path) == 2
        assert sys.path[0] == str(dummy_path_3.resolve())  # 先頭に追加されていること
    finally:
        sys.path = original_path
