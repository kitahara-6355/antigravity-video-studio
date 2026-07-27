import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
import sys
import stat
import PIL.ImageFont

_REAL_TRUETYPE = PIL.ImageFont.truetype

from agents.pipeline_types import PipelineContext, StageResult
from agents.workers.preview_worker import PreviewWorker

@pytest.fixture
def temp_video(tmp_path):
    video = tmp_path / "dummy_video.mp4"
    video.write_bytes(b"dummy video content")
    return video

@pytest.mark.asyncio
async def test_execute_ctx_none():
    worker = PreviewWorker()
    result = await worker.execute(None)
    assert not result.success
    assert "PipelineContext が None です" in result.detail

@pytest.mark.asyncio
async def test_execute_no_video_path():
    worker = PreviewWorker()
    ctx = PipelineContext(video_path="temp.mp4")
    ctx.video_path = None
    result = await worker.execute(ctx)
    assert not result.success
    assert "video_path が指定されていません" in result.detail

@pytest.mark.asyncio
async def test_execute_invalid_video_path_type():
    worker = PreviewWorker()
    ctx = PipelineContext(video_path="temp.mp4")
    ctx.video_path = 12345
    result = await worker.execute(ctx)
    assert not result.success
    assert "video_path の型が不正です" in result.detail

@pytest.mark.asyncio
async def test_execute_video_path_not_exists():
    worker = PreviewWorker()
    ctx = PipelineContext(video_path="non_existent_file.mp4")
    result = await worker.execute(ctx)
    assert not result.success
    assert "元動画ファイルが存在しません" in result.detail

@pytest.mark.asyncio
async def test_execute_no_segments(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = None
    ctx.segments = None
    result = await worker.execute(ctx)
    assert not result.success
    assert "セグメントなし — プレビュー生成不可" in result.detail

@pytest.mark.asyncio
async def test_execute_fallback_segments(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = None
    ctx.segments = [{"start": 0, "end": 10}]
    
    mock_stat = MagicMock()
    mock_stat.st_size = 2048
    mock_stat.st_mode = stat.S_IFREG
    
    def exists_se(self_path):
        return True

    with patch("smart_cut_engine.render_smart_cut", return_value=True) as mock_render,          patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)),          patch.object(Path, "exists", autospec=True, side_effect=exists_se),          patch.object(Path, "stat", return_value=mock_stat):
        
        result = await worker.execute(ctx)
        assert result.success
        assert ctx.selected_segments == [{"start": 0, "end": 10}]
        assert "preview_" in ctx.preview_path

@pytest.mark.asyncio
async def test_execute_invalid_selected_segments_type(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = "invalid_type"
    result = await worker.execute(ctx)
    assert not result.success
    assert "selected_segments の型が不正です" in result.detail

@pytest.mark.asyncio
async def test_execute_empty_selected_segments_list(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = []
    ctx.segments = None
    result = await worker.execute(ctx)
    assert not result.success
    assert "セグメントなし — プレビュー生成不可" in result.detail

@pytest.mark.asyncio
async def test_execute_invalid_segment_item_type(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = ["not_a_dict"]
    result = await worker.execute(ctx)
    assert not result.success
    assert "辞書ではありません" in result.detail

@pytest.mark.asyncio
async def test_execute_import_error(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    with patch("builtins.__import__", side_effect=ImportError("mock import error")):
        result = await worker.execute(ctx)
        assert not result.success
        assert "インポートエラー" in result.detail

@pytest.mark.asyncio
async def test_execute_os_error(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)),          patch("pathlib.Path.mkdir", side_effect=OSError("mock OS error")):
        result = await worker.execute(ctx)
        assert not result.success
        assert "システムエラー" in result.detail

@pytest.mark.asyncio
async def test_execute_general_exception(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    with patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)),          patch("pathlib.Path.mkdir", side_effect=Exception("mock general exception")):
        result = await worker.execute(ctx)
        assert not result.success
        assert "mock general exception" in result.detail

@pytest.mark.asyncio
async def test_execute_render_failure(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    with patch("smart_cut_engine.render_smart_cut", return_value=False),          patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)):
        result = await worker.execute(ctx)
        assert not result.success
        assert "プレビュー生成失敗" in result.detail

@pytest.mark.asyncio
async def test_execute_render_file_not_exists(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    def exists_se(self_path):
        if "preview" in str(self_path):
            return False
        return True

    with patch("smart_cut_engine.render_smart_cut", return_value=True),          patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)),          patch.object(Path, "exists", autospec=True, side_effect=exists_se):
        result = await worker.execute(ctx)
        assert not result.success
        assert "プレビュー生成失敗" in result.detail

@pytest.mark.asyncio
async def test_execute_render_file_too_small(temp_video):
    worker = PreviewWorker()
    ctx = PipelineContext(video_path=str(temp_video))
    ctx.selected_segments = [{"start": 0, "end": 5}]
    
    mock_stat = MagicMock()
    mock_stat.st_size = 500
    mock_stat.st_mode = stat.S_IFREG

    def exists_se(self_path):
        return True

    with patch("smart_cut_engine.render_smart_cut", return_value=True),          patch("safe_io.VAULT_OUTPUTS_DIR", Path(temp_video.parent)),          patch.object(Path, "exists", autospec=True, side_effect=exists_se),          patch.object(Path, "stat", return_value=mock_stat):
        result = await worker.execute(ctx)
        assert not result.success
        assert "プレビュー生成失敗" in result.detail

@pytest.mark.asyncio
async def test_execute_ctx_missing_attributes(temp_video):
    worker = PreviewWorker()
    
    class CustomContext:
        def __init__(self, video_path):
            self.video_path = video_path
            
    ctx = CustomContext(video_path=str(temp_video))
    result = await worker.execute(ctx)
    assert not result.success
    assert "セグメントなし — プレビュー生成不可" in result.detail
    assert ctx.selected_segments is None
    assert ctx.segments is None

def test_verify():
    worker = PreviewWorker()
    
    res_success = StageResult(stage_name="プレビュー生成", success=True, data={"path": "dummy.mp4"})
    with patch("pathlib.Path.exists", return_value=True):
        assert worker.verify(res_success)
        
    res_fail1 = StageResult(stage_name="プレビュー生成", success=False, data={"path": "dummy.mp4"})
    assert not worker.verify(res_fail1)

    res_fail2 = StageResult(stage_name="プレビュー生成", success=True, data={})
    assert not worker.verify(res_fail2)

    res_fail3 = StageResult(stage_name="プレビュー生成", success=True, data={"path": "dummy.mp4"})
    with patch("pathlib.Path.exists", return_value=False):
        assert not worker.verify(res_fail3)

def test_get_definition_of_done():
    worker = PreviewWorker()
    dod = worker.get_definition_of_done()
    assert "1KB以上" in dod


# ============================================================
# Phase 27 Thumbnail & Quality Validation & StageBoundAgent Tests
# ============================================================

def test_thumbnail_quality_success(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "thumb.png"
    # 正常系: 1280x720 サムネイル生成
    res_path = worker.generate_thumbnail(out_path, width=1280, height=720, text="Test Success")
    assert res_path.exists()
    
    # 品質検証
    val_res = worker.validate_thumbnail(res_path)
    assert val_res["width"] == 1280
    assert val_res["height"] == 720
    assert val_res["size_bytes"] > 0
    assert val_res["size_bytes"] < 4 * 1024 * 1024

def test_thumbnail_validation_errors(tmp_path):
    worker = PreviewWorker()
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        worker.validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. アスペクト比異常 (1:1)
    from PIL import Image
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 1280), color=(255, 0, 0))
    img.save(bad_ratio_path, "PNG")
    with pytest.raises(ValueError, match="Aspect ratio"):
        worker.validate_thumbnail(bad_ratio_path)
        
    # 3. 解像度不足 (640x360, 16:9だが小さい)
    too_small_path = tmp_path / "too_small.png"
    img2 = Image.new("RGB", (640, 360), color=(0, 255, 0))
    img2.save(too_small_path, "PNG")
    with pytest.raises(ValueError, match="Resolution"):
        worker.validate_thumbnail(too_small_path)

    # 4. 破損画像
    corrupt_path = tmp_path / "corrupt.png"
    with open(corrupt_path, "wb") as f:
        f.write(b"not a valid image")
    with pytest.raises((ValueError, OSError)):
        worker.validate_thumbnail(corrupt_path)

@pytest.mark.asyncio
async def test_stage_bound_agent_integration_preview(tmp_path):
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    db_file = tmp_path / "tasks.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    worker = PreviewWorker()
    # 必要に応じて設定を注入
    worker.output_dir = str(tmp_path)
    worker.width = 1280
    worker.height = 720
    worker.text = "Agent Integrated Preview"
    
    task_id = "task_preview_thumb_success"
    await agent.register_task(task_id, initial_status="READY", max_retries=1)
    
    # 起動
    await agent.start(worker.resolve_thumbnail_task)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # DB結果検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[1] is None or row[1] == "" # error is empty
    result_json = json.loads(row[0])
    assert result_json["width"] >= 1280
    assert result_json["height"] >= 720
    assert Path(result_json["path"]).exists()
    assert row[2] == 0 # retry_count
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_preview(tmp_path):
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import asyncio
    
    db_file = tmp_path / "tasks_retry.db"
    agent = StageBoundAgent(
        stage_name="thumbnail",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    worker = PreviewWorker()
    # 意図的にエラーを起こす設定にする (無効な出力先ディレクトリを指定)
    worker.output_dir = ":/invalid_path/\\/?*"
    
    task_id = "task_preview_thumb_fail"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 起動
    await agent.start(worker.resolve_thumbnail_task)
    
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.05)
        
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    
    # リトライ回数とエラーの検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 2  # max_retries = 2
    assert row[1] is not None and len(row[1]) > 0
    
    await agent.stop()


def test_thumbnail_multi_line_text(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "multi_line.png"
    res_path = worker.generate_thumbnail(
        out_path,
        width=1280,
        height=720,
        text="NHK Premium\nVideo Standards\nVerification OK"
    )
    assert res_path.exists()
    val_res = worker.validate_thumbnail(res_path)
    assert val_res["width"] == 1280
    assert val_res["height"] == 720


def test_thumbnail_strict_aspect_ratio(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "bad_aspect.png"
    # アスペクト比がわずかにずれているケース (1280x730 -> 約1.753, 16:9=1.777)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        worker.generate_thumbnail(out_path, width=1280, height=730, text="Bad Aspect")


def test_thumbnail_size_fallback_simulation(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "compressed_fallback.png"
    
    # PNGでの保存時に4MBを超える状況をシミュレート
    # PIL.Image.Image.save をパッチして、最初のPNG保存時に巨大なダミーファイルを作成し、
    # 段階的フォールバックが機能することを確認
    original_save = pytest.importorskip("PIL.Image.Image").save
    
    call_count = 0
    def mock_save(self_img, fp, format_type, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if format_type == "PNG":
            # PNGで保存された場合に、一時的に 5MB のファイルを書き出す
            with open(fp, "wb") as f:
                f.write(b"\0" * (5 * 1024 * 1024))
        else:
            # JPEG等での保存時は通常の処理を行う
            original_save(self_img, fp, format_type, *args, **kwargs)
            
    with patch("PIL.Image.Image.save", side_effect=mock_save):
        res_path = worker.generate_thumbnail(out_path, width=1280, height=720, text="Compressed")
        assert res_path.exists()
        # PNGで1回 (5MB)、その後JPEGで1回 (1MB以下になる) 保存が呼ばれるため、計2回以上になる
        assert call_count >= 2
        
        # 最終的なファイルサイズが4MB未満であることを検証
        assert res_path.stat().st_size < 4 * 1024 * 1024


def test_thumbnail_write_error_handling(tmp_path):
    worker = PreviewWorker()
    # 既存のファイルを作成
    existing_file = tmp_path / "already_a_file.txt"
    existing_file.write_text("just a file")
    
    # 既存のファイルを親ディレクトリとするパスを指定（親ディレクトリを作成しようとするとOSErrorが発生する）
    invalid_path = existing_file / "thumb.png"
    with pytest.raises(OSError):
        worker.generate_thumbnail(invalid_path, width=1280, height=720, text="Write Error")


# ============================================================
# 新規追加: サムネイル画像生成品質および異常系の自動検証テスト
# ============================================================

def test_thumbnail_strict_verification_criteria(tmp_path):
    """
    最優先ルール:
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    """
    worker = PreviewWorker()
    out_path = tmp_path / "strict_quality_test.png"
    
    # プレミアムサムネイルを生成 (Glassmorphismバナー、サークル、矢印つき)
    res_path = worker.generate_thumbnail(
        out_path,
        width=1920,
        height=1080,
        text="Strict Quality\nValidation\nNHK Standard PASS",
        draw_arrow=True,
        draw_circle=True,
        use_banner=True
    )
    
    assert res_path.exists()
    
    # 品質検証
    val_res = worker.validate_thumbnail(res_path)
    
    # 1. 解像度が 1280x720 以上であること
    assert val_res["width"] >= 1280
    assert val_res["height"] >= 720
    assert val_res["width"] == 1920
    assert val_res["height"] == 1080
    
    # 2. アスペクト比が 16:9 であること
    aspect = val_res["width"] / val_res["height"]
    assert abs(aspect - 16.0 / 9.0) < 0.01
    
    # 3. ファイルサイズが 4MB 未満であること
    assert val_res["size_bytes"] < 4 * 1024 * 1024
    
    # 4. 出力ファイルが破損なく Pillow でロード可能であること
    from PIL import Image
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1920, 1080)
        # tobytes がエラーなく完了することで破損のないことを検証
        img.tobytes()


def test_thumbnail_invalid_extensions_and_paths(tmp_path):
    """
    異常系: サポートされていない画像形式や無効なパス指定時のエラーハンドリング
    """
    worker = PreviewWorker()
    
    # 1. サポート外の拡張子 (.gif)
    bad_ext_path = tmp_path / "thumb.gif"
    with pytest.raises(ValueError, match="Unsupported file format"):
        worker.generate_thumbnail(bad_ext_path, width=1280, height=720, text="Bad Ext")
        
    # 2. 空のパス
    with pytest.raises(ValueError, match="Output path must not be empty or None"):
        worker.generate_thumbnail("", width=1280, height=720, text="Empty Path")
        
    # 3. ディレクトリをパスに指定した場合
    with pytest.raises(ValueError, match="must be a file path, not a directory"):
        worker.generate_thumbnail(tmp_path, width=1280, height=720, text="Dir Path")


def test_thumbnail_extreme_resolutions(tmp_path):
    """
    異常系: 極端な解像度や無効なパラメータのバリデーション
    """
    worker = PreviewWorker()
    out_path = tmp_path / "extreme_res.png"
    
    # 1. 8K解像度を超えるサイズ (OutOfMemory 防止)
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit of 8K"):
        worker.generate_thumbnail(out_path, width=7681, height=4321, text="Too Big")
        
    # 2. 負の解wiseな解像度
    with pytest.raises(ValueError, match="must be positive integers"):
        worker.generate_thumbnail(out_path, width=-1280, height=720, text="Negative Width")

    # 3. ゼロ解像度
    with pytest.raises(ValueError, match="must be positive integers"):
        worker.generate_thumbnail(out_path, width=1280, height=0, text="Zero Height")


@pytest.mark.asyncio
async def test_stage_bound_agent_db_migration_and_save(tmp_path):
    """
    最優先ルール:
    - StageBoundAgent等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること。
    """
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    
    db_file = tmp_path / "agent_integration.db"
    
    # 1. DBマイグレーションを適用するために Agent を初期化
    agent = StageBoundAgent(
        stage_name="thumbnail_test_stage",
        db_path=str(db_file),
        poll_interval=0.01
    )
    
    # 2. 正常系連携のテスト
    worker = PreviewWorker()
    worker.output_dir = str(tmp_path)
    worker.width = 1920
    worker.height = 1080
    worker.text = "Agent DB Verification"
    
    task_id = "task_db_integration_check"
    # タスクの初期状態を登録
    await agent.register_task(task_id, initial_status="READY", max_retries=3)
    
    # エージェント開始
    await agent.start(worker.resolve_thumbnail_task)
    
    # 完了を待機 (最大2秒)
    for _ in range(40):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.05)
        
    # ステータス検証
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 3. 結果の保存およびDBマイグレーションの連携検証
    conn = sqlite3.connect(str(db_file))
    cursor = conn.execute("SELECT result, error, retry_count, status FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[3] == "COMPLETED"
    assert row[1] is None or row[1] == ""  # エラーは空
    assert row[2] == 0  # リトライなしで成功
    
    result_data = json.loads(row[0])
    assert result_data["width"] == 1920
    assert result_data["height"] == 1080
    assert Path(result_data["path"]).exists()
    assert result_data["size_bytes"] < 4 * 1024 * 1024  # 4MB未満の保証
    
    await agent.stop()


def test_thumbnail_additional_coverage(tmp_path):
    from PIL import Image
    worker = PreviewWorker()
    out_path = tmp_path / "coverage_extra.png"

    # 1. 181-182: TypeError, ValueError 例外のハンドラ。width と height が整数変換できない場合。
    with pytest.raises(ValueError, match="Width and height must be integers"):
        worker.generate_thumbnail(out_path, width="not_an_integer", height=720)

    # 2. 188: width < 1280 or height < 720 の場合の ValueError。
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        worker.generate_thumbnail(out_path, width=640, height=360)

    # 3. 216: width > 1920 or height > 1080 の場合。
    out_path_4k = tmp_path / "coverage_4k.png"
    res_4k = worker.generate_thumbnail(out_path_4k, width=3840, height=2160, text="4K Scale Check")
    assert res_4k.exists()

    # 4. 208: Parent directory does not exist after creation attempt: {parent_dir}
    with patch("pathlib.Path.exists", return_value=False):
        with pytest.raises(IOError, match="Parent directory does not exist after creation attempt"):
            worker.generate_thumbnail(tmp_path / "unreal_dir" / "thumb.png", width=1280, height=720)

    # 5. 211: PermissionError (親ディレクトリが書き込み不可の場合)。
    with patch("os.access", return_value=False):
        with pytest.raises(PermissionError, match="Parent directory is not writeable"):
            worker.generate_thumbnail(tmp_path / "unwriteable" / "thumb.png", width=1280, height=720)

    # 6. 625: output_path.unlink() の実行
    existing_file = tmp_path / "existing.png"
    existing_file.write_bytes(b"dummy")
    res = worker.generate_thumbnail(existing_file, width=1280, height=720, text="Overwrite Test")
    assert res.exists()


def test_thumbnail_font_and_bbox_failures(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    worker = PreviewWorker()
    out_path = tmp_path / "font_bbox.png"

    # 330-331: ImageFont.truetype で OSError が発生した場合のフォールバック
    def mock_truetype(font, size=10, index=0, encoding="", layout_engine=None):
        if isinstance(font, str) and (font.startswith("/") or ":" in font or font.endswith(".ttf") or font.endswith(".ttc")):
            raise OSError("Font loading failed")
        return _REAL_TRUETYPE(font, size, index, encoding, layout_engine)

    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        res = worker.generate_thumbnail(out_path, width=1280, height=720, text="Truetype Fail")
        assert res.exists()

    # ImageFont.load_default(size=...) が TypeError を出す場合のフォールバック (335-336)
    orig_load_default = ImageFont.load_default
    def mock_load_default(*args, **kwargs):
        if "size" in kwargs:
            raise TypeError("size is not supported")
        return orig_load_default()

    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        with patch("PIL.ImageFont.load_default", side_effect=mock_load_default):
            res = worker.generate_thumbnail(tmp_path / "font_default_fail.png", width=1280, height=720, text="Default Font Fail")
            assert res.exists()

    # d_temp.textbbox/d.textbbox で AttributeError を発生させる
    # かつ d.text に stroke_width が指定された際に TypeError を発生させる
    orig_draw = ImageDraw.Draw
    def mock_draw(im, mode=None):
        draw_obj = orig_draw(im, mode)
        draw_obj.textbbox = MagicMock(side_effect=AttributeError("Mock AttributeError"))
        orig_text = draw_obj.text
        def mock_text(*args, **kwargs):
            if "stroke_width" in kwargs:
                raise TypeError("stroke_width not supported")
            return orig_text(*args, **kwargs)
        draw_obj.text = mock_text
        return draw_obj

    with patch("PIL.ImageDraw.Draw", side_effect=mock_draw):
        res = worker.generate_thumbnail(tmp_path / "bbox_fail.png", width=1280, height=720, text="Bbox Fail")
        assert res.exists()


def test_thumbnail_autoscale_long_text(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "long_text.png"
    long_text = "A" * 1000
    res = worker.generate_thumbnail(out_path, width=1280, height=720, text=long_text)
    assert res.exists()


def test_thumbnail_compressions(tmp_path):
    import stat
    worker = PreviewWorker()
    
    # 正常系 JPG 生成テスト (589行目カバー用)
    out_path_jpg_normal = tmp_path / "normal.jpg"
    res_jpg = worker.generate_thumbnail(out_path_jpg_normal, width=1280, height=720, text="Normal JPG")
    assert res_jpg.exists()

    mock_stat_res = MagicMock()
    mock_stat_res.st_size = 5 * 1024 * 1024
    mock_stat_res.st_mode = stat.S_IFREG
    
    # 580-592: .jpg / .jpeg で 4MB を超える場合
    out_path_jpg = tmp_path / "compress_fail.jpg"
    with patch("pathlib.Path.mkdir", return_value=None):
        with patch("pathlib.Path.stat", return_value=mock_stat_res):
            with patch("pathlib.Path.exists", return_value=True):
                with pytest.raises(ValueError, match="Failed to compress JPEG below 4MB"):
                    worker.generate_thumbnail(out_path_jpg, width=1280, height=720, text="JPEG Comp Fail")

    # 597-615: PNG で 4MB を超えて JPEG フォールバックでも 4MB 未満にならない場合
    out_path_png = tmp_path / "compress_fail.png"
    with patch("pathlib.Path.mkdir", return_value=None):
        with patch("pathlib.Path.stat", return_value=mock_stat_res):
            with patch("pathlib.Path.exists", return_value=True):
                with pytest.raises(ValueError, match="Failed to compress PNG below 4MB"):
                    worker.generate_thumbnail(out_path_png, width=1280, height=720, text="PNG Comp Fail")


def test_thumbnail_rename_failure(tmp_path):
    worker = PreviewWorker()
    out_path = tmp_path / "rename_fail.png"
    
    with patch("pathlib.Path.rename", side_effect=OSError("Rename failed")):
        with patch("shutil.move", side_effect=Exception("Move failed")):
            with patch("time.sleep", return_value=None):
                with pytest.raises(IOError, match="Failed to move temporary file"):
                    worker.generate_thumbnail(out_path, width=1280, height=720, text="Rename Fail")


def test_thumbnail_rename_fallback_success(tmp_path):
    worker = PreviewWorker()
    out_path_move = tmp_path / "move_fallback.png"
    
    def mock_move(src, dst):
        from pathlib import Path
        Path(dst).write_bytes(Path(src).read_bytes())
        Path(src).unlink()

    # 633-634: rename が OSError になり、shutil.move が成功するパス
    with patch("pathlib.Path.rename", side_effect=OSError("Rename failed")):
        with patch("shutil.move", side_effect=mock_move):
            with patch("time.sleep", return_value=None):
                res = worker.generate_thumbnail(out_path_move, width=1280, height=720, text="Move Success")
                assert res.exists()


def test_validate_thumbnail_coverage(tmp_path):
    from PIL import Image
    worker = PreviewWorker()
    
    # 691: validate_thumbnail(None)
    with pytest.raises(ValueError, match="File path must not be empty or None"):
        worker.validate_thumbnail(None)
        
    # 698: validate_thumbnail("test.gif")
    with pytest.raises(ValueError, match="Unsupported file format"):
        worker.validate_thumbnail(tmp_path / "test.gif")
        
    # 705: size_bytes == 0
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError, match="Thumbnail file is empty"):
        worker.validate_thumbnail(empty_file)
        
    # 709: size_bytes >= max_size
    large_file = tmp_path / "large.png"
    with open(large_file, "wb") as f:
        f.seek(5 * 1024 * 1024 - 1)
        f.write(b"\0")
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        worker.validate_thumbnail(large_file)
        
    # 721: JPEG マジックナンバー違反
    fake_jpg = tmp_path / "fake.jpg"
    fake_jpg.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(ValueError, match="File extension is JPEG/JPG but header is not JPEG"):
        worker.validate_thumbnail(fake_jpg)
        
    # 724-725: f_head.read で OSError
    read_fail_file = tmp_path / "read_fail.png"
    read_fail_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch("builtins.open", side_effect=OSError("Read error")):
        with pytest.raises(ValueError, match="Failed to verify file magic number"):
            worker.validate_thumbnail(read_fail_file)

    # 731-732: img.verify() で例外
    corrupt_file = tmp_path / "corrupt.png"
    corrupt_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    
    orig_open = Image.open
    def mock_image_open(fp, mode="r", formats=None):
        if str(fp) == str(corrupt_file):
            img_mock = MagicMock()
            img_mock.verify.side_effect = OSError("Verify error")
            img_mock.__enter__.return_value = img_mock
            return img_mock
        return orig_open(fp, mode, formats)
        
    with patch("PIL.Image.open", side_effect=mock_image_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format: Verify error"):
            worker.validate_thumbnail(corrupt_file)

    # 740-741: img.load() で例外
    def mock_image_open_load_fail(fp, mode="r", formats=None):
        if str(fp) == str(corrupt_file):
            img_mock = MagicMock()
            img_mock.verify.return_value = None
            img_mock.load.side_effect = OSError("Load error")
            img_mock.size = (1280, 720)
            img_mock.__enter__.return_value = img_mock
            return img_mock
        return orig_open(fp, mode, formats)

    with patch("PIL.Image.open", side_effect=mock_image_open_load_fail):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format: Load error"):
            worker.validate_thumbnail(corrupt_file)

    # 747: 8Kを超える解像度の検証
    too_large_file = tmp_path / "too_large.png"
    too_large_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    def mock_image_open_too_large(fp, mode="r", formats=None):
        if str(fp) == str(too_large_file):
            img_mock = MagicMock()
            img_mock.verify.return_value = None
            img_mock.load.return_value = None
            img_mock.size = (7681, 4321)
            img_mock.tobytes.return_value = b""
            img_mock.__enter__.return_value = img_mock
            return img_mock
        return orig_open(fp, mode, formats)
        
    with patch("PIL.Image.open", side_effect=mock_image_open_too_large):
        with pytest.raises(ValueError, match="Resolution exceeds maximum limit of 8K"):
            worker.validate_thumbnail(too_large_file)


def test_thumbnail_cleanup_on_exception(tmp_path):
    from PIL import Image
    worker = PreviewWorker()
    out_path = tmp_path / "cleanup_fail.png"

    # Image.close が例外を投げるモック
    orig_new = Image.new
    def mock_image_new(mode, size, color=0):
        img_obj = orig_new(mode, size, color)
        img_obj.close = MagicMock(side_effect=Exception("Close error"))
        return img_obj
        
    with patch("PIL.Image.new", side_effect=mock_image_new):
        with patch("PIL.ImageDraw.Draw", side_effect=ValueError("Mock Draw Error")):
            with pytest.raises(ValueError, match="Mock Draw Error"):
                worker.generate_thumbnail(out_path, width=1280, height=720)

    # resized_img が存在した状態で例外が発生し、かつ close が例外を投げるパス
    orig_resize = Image.Image.resize
    def mock_resize(self, size, resample=None, box=None, reducing_gap=None):
        resized_obj = orig_resize(self, size, resample, box, reducing_gap)
        resized_obj.save = MagicMock(side_effect=ValueError("Save error"))
        resized_obj.close = MagicMock(side_effect=Exception("Close error"))
        return resized_obj
        
    with patch("PIL.Image.Image.resize", mock_resize):
        with pytest.raises(ValueError, match="Save error"):
            worker.generate_thumbnail(out_path, width=1280, height=720)

    # temp_path.unlink が OSError を投げるパス
    with patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")):
        with patch("PIL.ImageDraw.Draw", side_effect=ValueError("Mock Draw Error")):
            with pytest.raises(ValueError, match="Mock Draw Error"):
                with patch("pathlib.Path.exists", return_value=True):
                    worker.generate_thumbnail(out_path, width=1280, height=720)


def test_thumbnail_cleanup_on_base_exception(tmp_path):
    from PIL import Image
    worker = PreviewWorker()
    out_path = tmp_path / "base_cleanup.png"

    orig_new = Image.new
    def mock_image_new(mode, size, color=0):
        img_obj = orig_new(mode, size, color)
        img_obj.close = MagicMock(side_effect=Exception("Close error"))
        return img_obj

    with patch("PIL.Image.new", side_effect=mock_image_new):
        with patch("PIL.ImageDraw.Draw", side_effect=KeyboardInterrupt("Mock Interrupt")):
            with pytest.raises(KeyboardInterrupt):
                worker.generate_thumbnail(out_path, width=1280, height=720)

    orig_resize = Image.Image.resize
    def mock_resize_interrupt(self, size, resample=None, box=None, reducing_gap=None):
        resized_obj = orig_resize(self, size, resample, box, reducing_gap)
        resized_obj.close = MagicMock(side_effect=Exception("Close error"))
        raise KeyboardInterrupt("Mock Interrupt")

    with patch("PIL.Image.Image.resize", mock_resize_interrupt):
        with pytest.raises(KeyboardInterrupt):
            worker.generate_thumbnail(out_path, width=1280, height=720)
