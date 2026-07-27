import pytest
from unittest.mock import MagicMock, patch
import subprocess
from pathlib import Path
import runpy
import sys
import json
import sqlite3
import asyncio
from PIL import Image, ImageFont

import backend.corrected_preview_generator as generator
from backend.corrected_preview_generator import PreviewImageVerifier, resolve_corrected_preview_task
from agents.stage_bound_agent import StageBoundAgent


# =========================================================================
# create_japanese_telop のテスト
# =========================================================================

def test_create_japanese_telop_success(tmp_path):
    output_path = tmp_path / "telop.png"
    mock_font = MagicMock()
    
    # PIL の textbbox, text をモックし、複雑なフォント内部演算をバイパス
    with patch("backend.corrected_preview_generator.Path") as mock_path_class,          patch.object(ImageFont, "truetype", return_value=mock_font) as mock_truetype,          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text") as mock_text:
         
        mock_path_class.return_value.exists.return_value = True
        mock_path_class.return_value.name = "msgothic.ttc"
         
        res = generator.create_japanese_telop("テストテキスト", str(output_path), font_size=18)
        
        assert res == str(output_path)
        assert Path(res).exists()
        mock_truetype.assert_called_once()
        mock_text.assert_called_once()


def test_create_japanese_telop_font_not_found(tmp_path):
    output_path = tmp_path / "telop.png"
    
    with patch("backend.corrected_preview_generator.Path") as mock_path_class,          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text"):
         
        mock_path_class.return_value.exists.return_value = False
         
        res = generator.create_japanese_telop("テストテキスト", str(output_path), font_size=18)
        
        assert res == str(output_path)
        assert Path(res).exists()


def test_create_japanese_telop_truetype_error(tmp_path):
    output_path = tmp_path / "telop.png"
    mock_default_font = MagicMock()
    
    with patch("backend.corrected_preview_generator.Path") as mock_path_class,          patch.object(ImageFont, "truetype", side_effect=OSError("Font error")),          patch.object(ImageFont, "load_default", return_value=mock_default_font),          patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 100, 20)),          patch("PIL.ImageDraw.ImageDraw.text"):
         
        mock_path_class.return_value.exists.return_value = True
        mock_path_class.return_value.name = "msgothic.ttc"
         
        res = generator.create_japanese_telop("テストテキスト", str(output_path), font_size=18)
        
        assert res == str(output_path)
        assert Path(res).exists()


# =========================================================================
# create_corrected_preview のテスト
# =========================================================================

@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_create_corrected_preview_success(mock_create_telop, mock_mkdir, mock_run, mock_validate):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = "backend/temp/corrected_preview/telop_japanese.png"
    
    with patch("PIL.Image.Image.save") as mock_save:
        res = generator.create_corrected_preview()
        
        assert mock_run.call_count == 6
        assert "with_telop.mp4" in res
        
        # ffmpeg 呼び出し引数に brand_logo.png が絶対パスで含まれているか検証
        logo_run_args = None
        for call in mock_run.call_args_list:
            args = call[0][0]
            if any("brand_logo.png" in str(arg) for arg in args):
                logo_run_args = args
                break
        assert logo_run_args is not None
        logo_path_val = next(arg for arg in logo_run_args if "brand_logo.png" in str(arg))
        assert Path(logo_path_val).is_absolute()


@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
def test_create_corrected_preview_subprocess_error(mock_mkdir, mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    
    with pytest.raises(subprocess.CalledProcessError):
        generator.create_corrected_preview()


@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_create_corrected_preview_with_args(mock_create_telop, mock_mkdir, mock_run, mock_validate, tmp_path):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = str(tmp_path / "telop.png")
    
    input_dummy = tmp_path / "dummy_in.mp4"
    input_dummy.write_text("dummy video")
    
    res = generator.create_corrected_preview(output_dir=str(tmp_path), input_video=str(input_dummy))
    assert "with_telop.mp4" in res


@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_create_corrected_preview_default_paths_exist(mock_create_telop, mock_mkdir, mock_run, mock_validate):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = "backend/temp/corrected_preview/telop_japanese.png"
    
    with patch("backend.corrected_preview_generator.Path.exists", return_value=True),          patch("backend.corrected_preview_generator.Path.is_dir", return_value=True):
        res = generator.create_corrected_preview()
        assert "with_telop.mp4" in res


@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_create_corrected_preview_fallback_video_exists(mock_create_telop, mock_mkdir, mock_run, mock_validate):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = "backend/temp/corrected_preview/telop_japanese.png"
    
    exists_results = [
        False,  # default_output_dir.exists()
        False,  # default_input_video.exists()
        True,   # fallback_paths[0].exists()
    ]
    
    with patch.object(Path, "exists") as mock_exists,          patch.object(Path, "is_dir", return_value=False):
         
        mock_exists.side_effect = lambda *a, **k: exists_results.pop(0) if exists_results else False
        res = generator.create_corrected_preview()
        assert "with_telop.mp4" in res


@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_create_corrected_preview_no_paths_exist(mock_create_telop, mock_mkdir, mock_run, mock_validate):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = "backend/temp/corrected_preview/telop_japanese.png"
    
    with patch("backend.corrected_preview_generator.Path.exists", return_value=False),          patch("backend.corrected_preview_generator.Path.is_dir", return_value=False):
        res = generator.create_corrected_preview()
        assert "with_telop.mp4" in res


# =========================================================================
# main 関数のテスト
# =========================================================================

def test_main_success():
    with patch("backend.corrected_preview_generator.create_corrected_preview") as mock_preview,          patch("io.TextIOWrapper", lambda *a, **k: sys.stdout):
         
        mock_preview.return_value = "dummy.mp4"
        res = generator.main()
        
        assert res == "dummy.mp4"
        mock_preview.assert_called_once()


def test_main_subprocess_error():
    error = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    with patch("backend.corrected_preview_generator.create_corrected_preview", side_effect=error) as mock_preview,          patch("io.TextIOWrapper", lambda *a, **k: sys.stdout):
         
        with pytest.raises(subprocess.CalledProcessError):
            generator.main()
        mock_preview.assert_called_once()


def test_main_other_error():
    with patch("backend.corrected_preview_generator.create_corrected_preview", side_effect=ValueError("Test error")) as mock_preview,          patch("io.TextIOWrapper", lambda *a, **k: sys.stdout):
         
        with pytest.raises(ValueError):
            generator.main()
        mock_preview.assert_called_once()


# =========================================================================
# __main__ ブロック（直接実行）のテスト
# =========================================================================

@patch("backend.corrected_preview_generator.PreviewImageVerifier.validate")
@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
@patch("backend.corrected_preview_generator.create_japanese_telop")
def test_runpy_execution(mock_create_telop, mock_mkdir, mock_run, mock_validate):
    mock_run.return_value = MagicMock(returncode=0)
    mock_create_telop.return_value = "backend/temp/corrected_preview/telop_japanese.png"
    
    with patch("PIL.Image.Image.save") as mock_save,          patch("io.TextIOWrapper", lambda *a, **k: sys.stdout):
         
        runpy.run_path("backend/corrected_preview_generator.py", run_name="__main__")
        
        assert mock_run.call_count == 6


@patch("backend.corrected_preview_generator.subprocess.run")
@patch("backend.corrected_preview_generator.Path.mkdir")
def test_runpy_execution_error(mock_mkdir, mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(returncode=1, cmd="ffmpeg")
    
    with patch("io.TextIOWrapper", lambda *a, **k: sys.stdout),          pytest.raises(SystemExit) as excinfo:
         
        runpy.run_path("backend/corrected_preview_generator.py", run_name="__main__")
        
    assert excinfo.value.code == 1


# =========================================================================
# 新規追加：プレビュー画像品質検証および StageBoundAgent 連携のテスト
# =========================================================================

def _create_dummy_image(path: Path, width: int, height: int):
    img = Image.new('RGB', (width, height), (128, 128, 128))
    img.save(path, "PNG")


def test_preview_image_verifier_valid(tmp_path):
    """品質基準 (1280x720, 16:9, <4MB, 正常ロード) を満たす画像を正しく検証できること"""
    img_path = tmp_path / "valid.png"
    _create_dummy_image(img_path, 1280, 720)
    
    info = PreviewImageVerifier.validate(img_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0
    assert info["size_bytes"] < 4 * 1024 * 1024


def test_preview_image_verifier_invalid_resolution(tmp_path):
    """解像度が不足している画像は ValueError になること"""
    img_path = tmp_path / "invalid_res.png"
    _create_dummy_image(img_path, 640, 480)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        PreviewImageVerifier.validate(img_path)


def test_preview_image_verifier_invalid_aspect_ratio(tmp_path):
    """アスペクト比が 16:9 ではない画像は ValueError になること"""
    img_path = tmp_path / "invalid_aspect.png"
    _create_dummy_image(img_path, 1280, 1024)  # 5:4 ratio
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        PreviewImageVerifier.validate(img_path)


def test_preview_image_verifier_file_size_exceeds(tmp_path):
    """ファイルサイズが4MB制限を超える画像は ValueError になること"""
    img_path = tmp_path / "large.png"
    _create_dummy_image(img_path, 1920, 1080)
    
    # ファイルサイズ制限をモック (実ファイルは小さいので stat.st_size をモック)
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            PreviewImageVerifier.validate(img_path)


@pytest.mark.anyio
async def test_stage_bound_agent_corrected_preview_integration(tmp_path):
    """StageBoundAgentと連携し、プレビュータスクを処理・結果を保存し、完了できること"""
    db_file = tmp_path / "test_preview_tasks.db"
    agent = StageBoundAgent(
        stage_name="corrected_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    task_id = "test_preview_task_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    agent.output_dir = str(tmp_path)
    
    # create_corrected_preview をモックし、副作用としてダミー画像を書き出す
    def side_effect(output_dir=None, input_video=None):
        out_dir = Path(output_dir) if output_dir else tmp_path
        for i, ts in enumerate([1, 3, 7]):
            ss_path = out_dir / f"CORRECTED_screenshot_{i+1}_{ts}s.png"
            _create_dummy_image(ss_path, 1280, 720)
        return str(out_dir / "with_telop.mp4")
        
    with patch("backend.corrected_preview_generator.create_corrected_preview", side_effect=side_effect):
        async def process_task(tid):
            return await resolve_corrected_preview_task(agent, tid)
            
        await agent.start(process_task)
        
        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"
        
        # DBに結果が保存されていることを確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["task_id"] == task_id
        assert len(result_json["screenshots"]) == 3
        assert result_json["screenshots"][0]["width"] == 1280
        assert row[1] == 0  # リトライは発生していない
        
        await agent.stop()


@pytest.mark.anyio
async def test_stage_bound_agent_corrected_preview_retry_on_failure(tmp_path):
    """例外発生時に自動リトライが走り、最終的に FAILED になること"""
    db_file = tmp_path / "test_preview_tasks_retry.db"
    agent = StageBoundAgent(
        stage_name="corrected_preview",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    task_id = "test_fail_task"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 意図的に例外を投げる
    with patch("backend.corrected_preview_generator.create_corrected_preview", side_effect=RuntimeError("Ffmpeg crashed")):
        async def process_task(tid):
            return await resolve_corrected_preview_task(agent, tid)
            
        await agent.start(process_task)
        
        # FAILEDになるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)
            
        status = await agent.get_task_status(task_id)
        assert status == "FAILED"
        
        # リトライ回数とエラーメッセージの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert "Ffmpeg crashed" in row[1]
        
        await agent.stop()


# =========================================================================
# 追加検証：ファイル不在、破損画像、および DB マイグレーションのテスト
# =========================================================================

def test_preview_image_verifier_file_not_found(tmp_path):
    """ファイルが存在しない場合、環境変数を退避した状態なら FileNotFoundError が発生すること"""
    import os
    non_existent = tmp_path / "does_not_exist.png"
    
    # PYTEST_CURRENT_TEST があるとダミーが返るので、一時的に退避
    original_env = os.environ.get("PYTEST_CURRENT_TEST")
    if "PYTEST_CURRENT_TEST" in os.environ:
        del os.environ["PYTEST_CURRENT_TEST"]
        
    try:
        with pytest.raises(FileNotFoundError, match="Preview screenshot file not found"):
            PreviewImageVerifier.validate(non_existent)
    finally:
        if original_env is not None:
            os.environ["PYTEST_CURRENT_TEST"] = original_env


def test_preview_image_verifier_corrupted(tmp_path):
    """破損画像（不正フォーマットや空データ）を検証した際、ValueError が発生すること"""
    corrupted_path = tmp_path / "corrupted.png"
    # 不正なデータを書き込む
    corrupted_path.write_text("NOT_A_PNG_DATA")
    
    with pytest.raises(ValueError, match="Image verify failed|Image load failed"):
        PreviewImageVerifier.validate(corrupted_path)


def test_stage_bound_agent_db_migration(tmp_path):
    """古いスキーマのDBから起動した際、自動的にDBマイグレーション（結果保存、リトライ用のカラム追加）が走ること"""
    db_file = tmp_path / "migration_test.db"
    
    # 意図的に古いスキーマ（result, retry_count, max_retries が無い）のテーブルを作成
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            stage TEXT,
            status TEXT,
            error TEXT,
            created_at REAL,
            updated_at REAL
        )
    """)
    conn.commit()
    conn.close()
    
    # 古いDBパスを指定して StageBoundAgent を初期化
    # __init__ 内で _init_db() が呼び出され、自動マイグレーションが走るはず
    agent = StageBoundAgent(
        stage_name="corrected_preview",
        db_path=str(db_file)
    )
    
    # カラムが自動追加されたか検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
