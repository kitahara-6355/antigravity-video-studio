# -*- coding: utf-8 -*-
import sys
import os
import io
import json
import sqlite3
import asyncio
import time
import pytest
from pathlib import Path
from PIL import Image, ImageDraw
from unittest.mock import patch, MagicMock

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from agents.orchestration.mark_tasks_p27_bug_hunter_b88 import (
    verify_thumbnail_quality,
    run_thumbnail_stage_task
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_stage.db"
    return str(db_file)

@pytest.fixture
def valid_image_bytes():
    # 1280x720, 16:9 の正常な画像をメモリ上に生成
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def test_verify_thumbnail_quality_success(valid_image_bytes):
    """正常系: 1280x720, 16:9, 小サイズで正常ロード可能なバイト列"""
    res = verify_thumbnail_quality(valid_image_bytes)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720

def test_verify_thumbnail_quality_file_success(tmp_path):
    """正常系: ファイルパス指定"""
    img = Image.new("RGB", (1920, 1080), color=(100, 100, 100))
    path = tmp_path / "valid_image.png"
    img.save(path, format="PNG")
    
    res = verify_thumbnail_quality(path)
    assert res["valid"] is True
    assert res["width"] == 1920
    assert res["height"] == 1080

def test_verify_thumbnail_quality_corrupted():
    """異常系: 破損したバイト列"""
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(b"invalid corrupted bytes")

def test_verify_thumbnail_quality_file_not_found():
    """異常系: 存在しないファイルパス"""
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        verify_thumbnail_quality("non_existent_file_path_123.jpg")

def test_verify_thumbnail_quality_resolution_fail(tmp_path):
    """異常系: 低解像度 (1280x720 未満)"""
    img = Image.new("RGB", (1000, 562), color=(100, 100, 100)) # 約16:9だが低解像度
    path = tmp_path / "low_res.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_aspect_ratio_fail(tmp_path):
    """異常系: アスペクト比が 16:9 ではない"""
    img = Image.new("RGB", (1280, 1000), color=(100, 100, 100)) # 1280x720以上だが比率が違う
    path = tmp_path / "wrong_aspect.png"
    img.save(path, format="PNG")
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_thumbnail_quality(path)

def test_verify_thumbnail_quality_size_fail(tmp_path):
    """異常系: ファイルサイズが 4MB 以上"""
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "large_file.png"
    img.save(path, format="PNG")
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_meta = MagicMock()
        mock_meta.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        mock_stat.return_value = mock_meta
        
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_thumbnail_quality(path)

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_success(temp_db):
    """run_thumbnail_stage_task が正常終了し、DBに結果が正しく書き込まれることを検証"""
    res_str = await run_thumbnail_stage_task("task_001", db_path=temp_db)
    res = json.loads(res_str)
    assert res["valid"] is True
    assert res["width"] == 1280
    assert res["height"] == 720
    
    # DB連携と結果保存の検証
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM thumbnail_results WHERE task_id = 'task_001'")
    row = cursor.fetchone()
    assert row is not None
    assert "task_001" in row[0]
    assert 1280 == row[2]
    assert 720 == row[3]
    conn.close()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_failure(temp_db):
    """品質検証で失敗した際、例外が送出され、emit_criticalは呼ばれないことを検証"""
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=ValueError("Mock Quality Error")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
          
          with pytest.raises(ValueError, match="Mock Quality Error"):
              await run_thumbnail_stage_task("task_fail", db_path=temp_db)
          
          mock_emit_critical.assert_not_called()

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_db):
    """StageBoundAgent にタスクを登録して自動リトライが動作することを検証"""
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=temp_db,
        poll_interval=0.01
    )
    
    # READYタスクを登録 (max_retries=2)
    await agent.register_task("task_retry_test", initial_status="READY", max_retries=2)
    
    # 最初の2回失敗し、3回目で成功するようなモック
    call_count = 0
    async def mock_process(task_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"Temporary Error {call_count}")
        return "SUCCESS_DATA"

    # エージェント開始
    await agent.start(process_func=mock_process)
    
    # 完了するかタイムアウトするまで待機
    start_time = time.time()
    while time.time() - start_time < 3.0:
        status = await agent.get_task_status("task_retry_test")
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    await agent.stop()
    
    # 3回目でCOMPLETEDになったことを確認
    assert call_count == 3
    status = await agent.get_task_status("task_retry_test")
    assert status == "COMPLETED"
    
    # 最終的な結果の取得
    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT * FROM tasks WHERE id = 'task_retry_test'")
    row = dict(cursor.fetchone())
    assert row["retry_count"] == 2
    assert row["result"] == "SUCCESS_DATA"
    conn.close()

def test_verify_thumbnail_quality_no_resource_warning(tmp_path):
    """品質検証で ResourceWarning (unclosed file) が発生しないことを検証"""
    import warnings
    import gc
    
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "warn_check.png"
    img.save(path, format="PNG")
    
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        
        # 正常系
        res = verify_thumbnail_quality(path)
        assert res["valid"] is True
        
        # 異常系 (アスペクト比エラーなど、Image.open された後に例外が発生するケース)
        img_wrong = Image.new("RGB", (1280, 1000), color=(100, 100, 100))
        path_wrong = tmp_path / "warn_check_wrong.png"
        img_wrong.save(path_wrong, format="PNG")
        
        try:
            verify_thumbnail_quality(path_wrong)
        except ValueError:
            pass
            
        # 異常系 (破損ファイル: Image.open が例外を投げるケース)
        path_corrupt = tmp_path / "warn_check_corrupt.png"
        path_corrupt.write_bytes(b"invalid corrupt content")
        try:
            verify_thumbnail_quality(path_corrupt)
        except ValueError:
            pass

        # GCを強制して未クローズ警告を出させる
        gc.collect()
        
        # ResourceWarning が発生していないことを確認。
        # gc.collect() は他テストが残したオブジェクトも回収するため、
        # 全体実行では無関係の ResourceWarning を拾って落ちることがあった。
        # このテストが作ったファイルに関するものだけを対象にする。
        resource_warnings = [
            warning for warning in w
            if issubclass(warning.category, ResourceWarning)
            and str(tmp_path) in str(warning.message)
        ]
        assert len(resource_warnings) == 0, f"Detected ResourceWarnings: {resource_warnings}"

def test_import_path_resolution():
    """mark_tasks_p27_bug_hunter_b88 が正しく sys.path を解決し、
    トップレベルの 'agents' をインポートできる状態になっていることを検証。
    """
    import sys
    from pathlib import Path
    
    # sys.path に 'backend' フォルダまたは agents ディレクトリが存在するパスが含まれているか確認
    has_backend = any(
        Path(p).name == "backend" or (Path(p) / "agents").exists() 
        for p in sys.path if p
    )
    assert has_backend, "sys.path should contain backend directory"
    
    try:
        import agents.orchestration.mark_tasks_p27_bug_hunter_b88 as target_module
        assert target_module is not None
    except ModuleNotFoundError as e:
        import pytest
        pytest.fail(f"Failed to import target module: {e}")

def test_verify_thumbnail_quality_file_corrupted(tmp_path):
    """異常系: ファイルパス指定で画像ファイルの中身が破損している場合"""
    # 破損したファイルを生成
    corrupt_file = tmp_path / "corrupted_image.png"
    corrupt_file.write_bytes(b"invalid image file content")
    
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_warning") as mock_emit_warning:
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(corrupt_file)
        
        mock_emit_warning.assert_called_once()
        args, kwargs = mock_emit_warning.call_args
        assert args[0] == "thumbnail"
        assert "Corrupted image file" in args[1]

def test_main_function():
    """main関数の正常系テスト (OrchestrationHubをモック)"""
    import agents.orchestration.mark_tasks_p27_bug_hunter_b88 as target_module
    
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub") as mock_hub_cls:
        mock_hub = MagicMock()
        mock_hub_cls.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        # main()呼び出し
        target_module.main()
        
        # モックの呼び出し検証
        mock_hub_cls.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("c31cf144-1cbf-4278-a5dd-7155df0da84c")
        mock_hub.flash_update_heartbeat.assert_called_once()
        mock_hub.mark_task_done.assert_called_once()
        mock_hub.generate_flash_status.assert_called_once()

def test_main_execution_via_runpy():
    """スクリプト直接実行 (__name__ == '__main__') のカバレッジテスト"""
    import runpy
    import sys
    from pathlib import Path
    
    target_path = Path(__file__).resolve().parents[1] / "agents" / "orchestration" / "mark_tasks_p27_bug_hunter_b88.py"
    
    with patch("backend.agents.orchestration.OrchestrationHub") as mock_hub_cls:
        mock_hub = MagicMock()
        mock_hub_cls.return_value = mock_hub
        mock_hub.generate_flash_status.return_value = {"status": "ok"}
        
        # runpyを使ってスクリプトを実行
        runpy.run_path(str(target_path), run_name="__main__")
        
        mock_hub_cls.assert_called_once()
        mock_hub.register_flash_conversation_id.assert_called_once_with("c31cf144-1cbf-4278-a5dd-7155df0da84c")

def test_import_path_resolution_with_different_cwds():
    """実行時のカレントディレクトリ(CWD)が異なっていても、
    インポートパスが正しく解決されて ModuleNotFoundError が発生しないことを検証。
    """
    import subprocess
    import sys
    from pathlib import Path
    
    test_dir = Path(__file__).resolve().parent
    backend_dir = test_dir.parent
    project_root = backend_dir.parent
    
    py_code = f"""
import sys
from pathlib import Path
project_root = Path(r'{str(project_root)}')
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

target_file = Path(r'{str(backend_dir)}/agents/orchestration/mark_tasks_p27_bug_hunter_b88.py')
import runpy
from unittest.mock import patch, MagicMock
with patch('backend.agents.orchestration.OrchestrationHub') as mock_hub_cls:
    mock_hub = MagicMock()
    mock_hub_cls.return_value = mock_hub
    mock_hub.generate_flash_status.return_value = {{'status': 'ok'}}
    runpy.run_path(str(target_file), run_name='__main__')
    print('IMPORT_SUCCESS')
"""
    
    res = subprocess.run(
        [sys.executable, "-"],
        cwd=str(backend_dir),
        input=py_code,
        capture_output=True,
        text=True,
        timeout=15
    )
    
    assert res.returncode == 0, f"Execution failed in backend CWD: {res.stderr}"
    assert "IMPORT_SUCCESS" in res.stdout


def test_verify_thumbnail_quality_invalid_type():
    """異常系: bytes, str, Path 以外の不正な型が渡された場合に ValueError が発生し、emit_warning が呼ばれることを検証。"""
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_warning") as mock_emit_warning:
        with pytest.raises(ValueError, match="Invalid input type"):
            verify_thumbnail_quality(None)
        mock_emit_warning.assert_called_once()
        assert "Invalid input type" in mock_emit_warning.call_args[0][1]


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_image_save_failure(temp_db):
    """異常系: ダミー画像の保存中に OSError が発生した際、emit_critical が呼ばれ例外が送出されることを検証。"""
    from PIL import Image
    
    with patch.object(Image.Image, "save", side_effect=OSError("Mock Disk Full")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
        
        with pytest.raises(OSError, match="Mock Disk Full"):
            await run_thumbnail_stage_task("task_save_fail", db_path=temp_db)
            
        mock_emit_critical.assert_called_once()
        assert "Thumbnail task failed for task task_save_fail" in mock_emit_critical.call_args[0][1]


def test_verify_thumbnail_quality_pixel_corrupted(tmp_path):
    """異常系: 画像ファイル自体はImage.openで開ける（ヘッダー等は正常）が、
    ピクセルデータが破損している場合に img.load() で OSError/ValueError が発生し、
    正しく検知されることを検証。
    """
    from PIL import Image
    # 正常な画像を作成
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    path = tmp_path / "pixel_corrupted.png"
    img.save(path, format="PNG")
    
    # データを破損させるため、ファイルの一部（ピクセルデータ部分）を上書き
    data = bytearray(path.read_bytes())
    # 後半部分（ピクセルデータ）をゴミデータで埋める
    for i in range(len(data) // 2, len(data) - 10):
        data[i] = 0xFF
    path.write_bytes(bytes(data))
    
    # img.load() で破損を検知し、ValueError を投げることを検証
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_thumbnail_quality(path)


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_unexpected_exception(temp_db):
    """予期しない例外（AttributeErrorなど）が発生した際に、
    register_technical_debt が呼び出され、かつ例外が上層に伝播することを検証。
    """
    # verify_thumbnail_quality が AttributeError を投げるようにモックする
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=AttributeError("Unexpected Mock Error")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
         
         with pytest.raises(AttributeError, match="Unexpected Mock Error"):
             await run_thumbnail_stage_task("task_unexpected", db_path=temp_db)
             
         mock_register_debt.assert_called_once()
         args, kwargs = mock_register_debt.call_args
         assert kwargs["pattern"] == "except Exception as e:"
         assert "Unexpected Mock Error" in kwargs["notes"]
         
         mock_emit_critical.assert_called_once()


def test_main_function_exception_handling():
    """main関数実行中に例外が発生した際、
    register_technical_debt が呼び出され、かつ sys.exit(1) で終了することを検証。
    """
    import agents.orchestration.mark_tasks_p27_bug_hunter_b88 as target_module
    
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", side_effect=AttributeError("Hub failure")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
         pytest.raises(SystemExit) as exc_info:
         
         target_module.main()
         
    assert exc_info.value.code == 1
    mock_register_debt.assert_called_once()
    args, kwargs = mock_register_debt.call_args
    assert kwargs["pattern"] == "except Exception as e:"
    assert "Hub failure" in kwargs["notes"]


def test_register_technical_debt_execution(tmp_path):
    """register_technical_debt がエラーなく実行され、
    実際に TechnicalDebtStore に負債が登録されることを検証。
    """
    import json
    from backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88 import register_technical_debt
    from backend.agents.memory.technical_debt import TechnicalDebtStore
    
    # テスト用の一時的なインデックスファイルを作成（初期状態は空）
    index_file = tmp_path / "technical_debt_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({"entries": [], "cause_patterns": [], "changelog": []}, f)
    
    store = TechnicalDebtStore(debt_dir=tmp_path)
    initial_count = len(store.entries)
    assert initial_count == 0
    
    # 登録実行
    register_technical_debt(
        line_number=999,
        pattern="test_pattern",
        notes="test_notes",
        _store=store
    )
    
    # 登録後の検証
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert len(store.entries) == 1
    
    # 登録された最後のエントリを確認
    new_entry = store.entries[-1]
    assert new_entry.line_number == 999
    assert new_entry.pattern == "test_pattern"
    assert "test_notes" in new_entry.notes
    assert new_entry.file_path == "backend/agents/orchestration/mark_tasks_p27_bug_hunter_b88.py"


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_dynamic_line_number(temp_db):
    """予期せぬ例外が発生した際、スタックトレースからプロダクションコード内の
    正しい発生行番号が動的に検出され、技術負債に登録されることを検証。
    """
    with patch("PIL.Image.new", side_effect=AttributeError("Dynamic Line Error")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt:
         
         with pytest.raises(AttributeError, match="Dynamic Line Error"):
             await run_thumbnail_stage_task("task_dyn_line", db_path=temp_db)
             
         mock_register_debt.assert_called_once()
         args, kwargs = mock_register_debt.call_args
         # Image.new が呼ばれる行（152行目付近）が正しく検出されているか検証
         assert 145 <= kwargs["line_number"] <= 165
         assert kwargs["pattern"] == "except Exception as e:"
         assert "Dynamic Line Error" in kwargs["notes"]


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_cleanup_on_validation_failure(temp_db):
    """異常系: バリデーションエラー時に、生成された一時ファイルが削除されることを検証"""
    task_id = "task_cleanup_val_fail"
    project_root = Path(__file__).resolve().parents[1]
    expected_path = project_root / "temp_thumbnails" / f"{task_id}.png"
    
    # 以前の残存ファイルを削除しておく
    if expected_path.exists():
        expected_path.unlink()
        
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=ValueError("Mock Quality Error")):
        with pytest.raises(ValueError, match="Mock Quality Error"):
            await run_thumbnail_stage_task(task_id, db_path=temp_db)
            
    # 一時ファイルがクリーンアップされて存在しないことを確認
    assert not expected_path.exists(), f"Temp file {expected_path} was not cleaned up on validation failure"


@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_cleanup_on_db_failure(temp_db):
    """異常系: DBエラー時に、生成された一時ファイルが削除されることを検証"""
    task_id = "task_cleanup_db_fail"
    project_root = Path(__file__).resolve().parents[1]
    expected_path = project_root / "temp_thumbnails" / f"{task_id}.png"
    
    if expected_path.exists():
        expected_path.unlink()
        
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mock DB Error")):
        with pytest.raises(sqlite3.Error, match="Mock DB Error"):
            await run_thumbnail_stage_task(task_id, db_path=temp_db)
            
    assert not expected_path.exists(), f"Temp file {expected_path} was not cleaned up on DB failure"

def test_get_exception_line_helper():
    """_get_exception_line ヘルパーのテスト"""
    from agents.orchestration.mark_tasks_p27_bug_hunter_b88 import _get_exception_line
    # tb が None の場合にデフォルトが返ること
    assert _get_exception_line(None, 42) == 42
    
    # 意図的に例外を起こして tb を渡す
    try:
        raise ValueError("test")
    except ValueError as e:
        tb = e.__traceback__
        # 'mark_tasks_p27_bug_hunter_b88.py' 内で起きた例外ではないので default_line が返る
        res = _get_exception_line(tb, 99)
        assert res == 99

def test_cleanup_file_helper(tmp_path):
    """_cleanup_file ヘルパーのテスト"""
    from agents.orchestration.mark_tasks_p27_bug_hunter_b88 import _cleanup_file
    # 存在しないパスでも例外が出ないこと
    non_existent = tmp_path / "not_exist.png"
    _cleanup_file(non_existent) # エラーにならないこと
    
    # 存在するファイルを削除できること
    temp_file = tmp_path / "temp.png"
    temp_file.write_text("test")
    assert temp_file.exists()
    _cleanup_file(temp_file)
    assert not temp_file.exists()

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_specific_exceptions(temp_db):
    """TypeError, KeyError, RuntimeError が個別にキャッチされ、
    技術負債登録が呼ばれないことを検証。
    """
    for exc_cls, exc_msg in [
        (TypeError, "Mocked TypeError"),
        (KeyError, "Mocked KeyError"),
        (RuntimeError, "Mocked RuntimeError")
    ]:
        with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=exc_cls(exc_msg)), \
             patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
             patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
             
             with pytest.raises(exc_cls, match=exc_msg):
                 await run_thumbnail_stage_task("task_spec_exc", db_path=temp_db)
                 
             mock_register_debt.assert_not_called()
             mock_emit_critical.assert_called_once()
             assert exc_msg in mock_emit_critical.call_args[0][1]

def test_main_function_specific_exceptions(capsys):
    """main 関数で TypeError, RuntimeError が個別に処理され、
    技術負債登録が呼ばれずに適切なログで SystemExit することを検証。
    """
    import agents.orchestration.mark_tasks_p27_bug_hunter_b88 as target_module
    
    # 1. RuntimeError のケース
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", side_effect=RuntimeError("Hub runtime failure")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
         pytest.raises(SystemExit) as exc_info:
         
         target_module.main()
         
    assert exc_info.value.code == 1
    mock_register_debt.assert_not_called()
    captured = capsys.readouterr()
    assert "Runtime execution failed: Hub runtime failure" in captured.err

    # 2. TypeError のケース
    # register_flash_conversation_id を呼び出した際に TypeError を投げるようにする
    mock_hub = MagicMock()
    mock_hub.register_flash_conversation_id.side_effect = TypeError("Type mismatch in argument")
    
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", return_value=mock_hub), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
         pytest.raises(SystemExit) as exc_info:
         
         target_module.main()
         
    assert exc_info.value.code == 1
    mock_register_debt.assert_not_called()
    captured = capsys.readouterr()
    assert "Serialization failed: Type mismatch in argument" in captured.err


def test_cleanup_file_helper_none():
    """_cleanup_file ヘルパーに None が渡された場合でもエラーが発生しないことを検証"""
    from agents.orchestration.mark_tasks_p27_bug_hunter_b88 import _cleanup_file
    try:
        _cleanup_file(None)
    except Exception as e:
        pytest.fail(f"_cleanup_file(None) raised an exception: {e}")

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_name_error_prevented(temp_db):
    """run_thumbnail_stage_task で output_path が定義される前にエラーが起きた際、
    _cleanup_file 呼び出しで NameError が発生せずに元の例外が正しく再送出されることを検証
    """
    with patch("pathlib.Path.resolve", side_effect=OSError("Mocked Resolve Error")):
        with pytest.raises(OSError, match="Mocked Resolve Error"):
            await run_thumbnail_stage_task("task_name_error_test", db_path=temp_db)

@pytest.mark.asyncio
async def test_sqlite_connect_failure_no_name_error():
    """sqlite3.connect 自体が失敗した際、NameErrorなどの二次例外が発生せず、
    本来の sqlite3.Error がそのまま再送出されることを検証。
    """
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mocked Connection Refused")):
        with pytest.raises(sqlite3.Error, match="Mocked Connection Refused"):
            await run_thumbnail_stage_task("task_conn_fail", db_path="invalid_path")

def test_cleanup_file_handles_os_error():
    """_cleanup_file が OSError (権限エラーなど) を適切にキャッチして
    プロセスをハング・クラッシュさせずに正常終了することを検証。
    """
    from agents.orchestration.mark_tasks_p27_bug_hunter_b88 import _cleanup_file
    with patch("pathlib.Path.exists", side_effect=OSError("Permission Denied")):
        # 例外が発生せず正常終了することを確認
        try:
            _cleanup_file("some_locked_file.png")
        except Exception as e:
            pytest.fail(f"_cleanup_file raised an unexpected exception: {e}")

def test_verify_thumbnail_quality_syntax_error_bytes():
    """異常系: バイト列入力で Pillow が SyntaxError を投げた場合に ValueError が発生し、emit_warning が呼ばれることを検証。"""
    with patch("PIL.Image.open", side_effect=SyntaxError("Pillow metadata syntax error")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_warning") as mock_emit:
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(b"some dummy bytes")
        mock_emit.assert_called_once()
        assert "Corrupted image bytes" in mock_emit.call_args[0][1]

def test_verify_thumbnail_quality_syntax_error_file(tmp_path):
    """異常系: ファイル入力で Pillow が SyntaxError を投げた場合に ValueError が発生し、emit_warning が呼ばれることを検証。"""
    img_path = tmp_path / "syntax_err.png"
    img_path.write_bytes(b"dummy")
    with patch("PIL.Image.open", side_effect=SyntaxError("Pillow metadata syntax error")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_warning") as mock_emit:
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(img_path)
        mock_emit.assert_called_once()
        assert "Corrupted image file" in mock_emit.call_args[0][1]

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_traceback_printed(temp_db):
    """予期しない例外発生時に traceback.print_exc が呼び出されることを検証。"""
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=AttributeError("Unexpected Error")), \
         patch("traceback.print_exc") as mock_print_exc, \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt"), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical"):
         
         with pytest.raises(AttributeError):
             await run_thumbnail_stage_task("task_tb_test", db_path=temp_db)
         mock_print_exc.assert_called_once()

def test_main_function_traceback_printed():
    """main関数で予期しない例外発生時に traceback.print_exc が呼び出されることを検証。"""
    import agents.orchestration.mark_tasks_p27_bug_hunter_b88 as target_module
    with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.OrchestrationHub", side_effect=AttributeError("Hub Error")), \
         patch("traceback.print_exc") as mock_print_exc, \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt"), \
         pytest.raises(SystemExit):
         
         target_module.main()
    mock_print_exc.assert_called_once()

def test_verify_thumbnail_quality_permission_error(tmp_path):
    """異常系: path.stat() が PermissionError を投げる場合に ValueError を投げることを検証"""
    img_path = tmp_path / "permission_err.png"
    img_path.write_bytes(b"dummy")
    with patch("pathlib.Path.stat", side_effect=PermissionError("Mocked Permission Denied")), \
         patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_warning") as mock_emit:
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            verify_thumbnail_quality(img_path)
        mock_emit.assert_called_once()
        assert "Corrupted image file" in mock_emit.call_args[0][1]

def test_verify_thumbnail_quality_height_zero():
    """異常系: 画像の高さが 0 の場合に ValueError を投げることを検証"""
    mock_img = MagicMock()
    mock_img.__enter__.return_value = mock_img
    mock_img.size = (1280, 0)
    mock_img.load.return_value = None
    
    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Image height cannot be zero"):
            verify_thumbnail_quality(b"fake_image_bytes")

@pytest.mark.asyncio
async def test_run_thumbnail_stage_task_more_specific_exceptions(temp_db):
    """AttributeError, ZeroDivisionError, IndexError などの予期せぬ例外が発生した際、
    技術負債登録が呼ばれ、かつ例外が上層に伝播することを検証。
    """
    for exc_cls, exc_msg in [
        (AttributeError, "Mocked AttributeError"),
        (ZeroDivisionError, "Mocked ZeroDivisionError"),
        (IndexError, "Mocked IndexError")
    ]:
        with patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.verify_thumbnail_quality", side_effect=exc_cls(exc_msg)), \
             patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.register_technical_debt") as mock_register_debt, \
             patch("agents.orchestration.mark_tasks_p27_bug_hunter_b88.emit_critical") as mock_emit_critical:
             
             with pytest.raises(exc_cls, match=exc_msg):
                 await run_thumbnail_stage_task("task_spec_exc2", db_path=temp_db)
                 
             mock_register_debt.assert_called_once()
             mock_emit_critical.assert_called_once()


@pytest.mark.asyncio
async def test_sqlite_connect_timeout_parameter(temp_db):
    """sqlite3.connect が呼び出された際、timeout=30.0 が明示的に指定されていることを検証。"""
    with patch("sqlite3.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        try:
            await run_thumbnail_stage_task("task_timeout_test", db_path=temp_db)
        except Exception:
            pass
        mock_connect.assert_called_once()
        args, kwargs = mock_connect.call_args
        assert kwargs.get("timeout") == 30.0


@pytest.mark.asyncio
async def test_register_technical_debt_skips_environmental_errors(tmp_path):
    """環境エラー（ConnectionError, TimeoutError, sqlite3.Error, OSError）が
    発生した際、例外オブジェクトが register_technical_debt に渡されても、
    技術負債の登録がスキップされることを検証。
    """
    from backend.agents.memory.technical_debt import TechnicalDebtStore
    
    # 一時的なインデックスファイルを作成
    index_file = tmp_path / "technical_debt_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump({"entries": [], "cause_patterns": [], "changelog": []}, f)
    
    store = TechnicalDebtStore(debt_dir=tmp_path)
    
    # 登録関数の呼び出し（例外が ConnectionError の場合）
    from backend.agents.orchestration.mark_tasks_p27_bug_hunter_b88 import register_technical_debt
    
    register_technical_debt(
        line_number=100,
        pattern="except Exception as e:",
        notes="Connection refused test",
        exception=ConnectionError("Connection refused"),
        _store=store
    )
    
    # 登録されていないことを確認
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert len(store.entries) == 0

    # 登録関数の呼び出し（例外が sqlite3.Error の場合）
    register_technical_debt(
        line_number=101,
        pattern="except Exception as e:",
        notes="SQLite error test",
        exception=sqlite3.Error("Database locked"),
        _store=store
    )
    
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert len(store.entries) == 0






