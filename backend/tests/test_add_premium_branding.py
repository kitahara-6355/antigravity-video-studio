import os
import sys
import runpy
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, ImageFont, ImageDraw

import backend.add_premium_branding as apb

# 2026-07-25: テストが Windows のフォントパスを直書きしており、
# CI(Linux) で OSError: cannot open resource になっていた。
# プラットフォーム非依存の解決に変更。
from font_resolver import load_japanese_font


@pytest.fixture
def temp_workspace(tmp_path):
    """テスト用の一時ワークスペースを作成し、BASE_DIRと環境変数を差し替える"""
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    
    # 環境変数も設定する
    original_env = os.environ.get("ANTIGRAVITY_BASE_DIR")
    os.environ["ANTIGRAVITY_BASE_DIR"] = str(tmp_path)
    
    # 必要なディレクトリとロゴ画像を作成
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    
    # ダミーロゴ画像 (23x45) を作成して保存
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")
    
    yield tmp_path
    
    apb.BASE_DIR = original_base
    if original_env is None:
        if "ANTIGRAVITY_BASE_DIR" in os.environ:
            del os.environ["ANTIGRAVITY_BASE_DIR"]
    else:
        os.environ["ANTIGRAVITY_BASE_DIR"] = original_env


def test_create_premium_branding_yu_gothic(temp_workspace):
    """Yu Gothic Bold で正常にブランディング画像が生成されるケース"""
    # 本物のフォントオブジェクトを使用して PIL 内部の ValueError を防ぐ
    real_font = load_japanese_font(20)
    
    with patch("PIL.ImageFont.truetype") as mock_truetype:
        mock_truetype.return_value = real_font
        
        output_path = apb.create_premium_branding()
        
        assert output_path.exists()
        assert output_path.name == "premium_branding.png"
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\YuGothB.ttc", 20)


def test_create_premium_branding_meiryo_fallback(temp_workspace):
    """Yu Gothic が失敗し、Meiryo で成功するケース"""
    real_font = load_japanese_font(20)
    
    def side_effect(font_path, size):
        if "YuGothB" in font_path:
            raise OSError("Font not found")
        return real_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype:
        output_path = apb.create_premium_branding()
        
        assert output_path.exists()
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\meiryob.ttc", 20)


def test_create_premium_branding_ms_gothic_fallback(temp_workspace):
    """Yu Gothic と Meiryo が失敗し、MS Gothic で成功するケース"""
    real_font = load_japanese_font(20)
    
    def side_effect(font_path, size):
        if "YuGothB" in font_path or "meiryob" in font_path:
            raise OSError("Font not found")
        return real_font

    with patch("PIL.ImageFont.truetype", side_effect=side_effect) as mock_truetype:
        output_path = apb.create_premium_branding()
        
        assert output_path.exists()
        mock_truetype.assert_any_call(r"C:\Windows\Fonts\msgothic.ttc", 20)


def test_add_premium_branding_success(temp_workspace):
    """ffmpeg および ffprobe が正常終了し、ブランディング追加が成功するケース"""
    input_video = temp_workspace / "soul_narrative_FINAL_EDITED.mp4"
    input_video.write_text("dummy video content")
    
    output_video = temp_workspace / "soul_narrative_YOUTUBE_PREMIUM.mp4"
    real_font = load_japanese_font(20)
    
    def mock_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            output_video.write_text("dummy output video content")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        elif cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="125.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    with patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run, \
         patch("PIL.ImageFont.truetype", return_value=real_font):
        result = apb.add_premium_branding()
        
        assert result == str(output_video)
        assert output_video.exists()
        assert mock_subprocess_run.call_count == 2


def test_add_premium_branding_failure(temp_workspace):
    """ffmpeg が失敗し、None が返されるケース"""
    input_video = temp_workspace / "soul_narrative_FINAL_EDITED.mp4"
    input_video.write_text("dummy video content")
    
    real_font = load_japanese_font(20)
    
    with patch("subprocess.run") as mock_run, \
         patch("PIL.ImageFont.truetype", return_value=real_font):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffmpeg error details"
        )
        
        result = apb.add_premium_branding()
        
        assert result is None


def test_main_block(temp_workspace):
    """__main__ ブロックを実行してカバレッジを通す (成功ケース)"""
    input_video = temp_workspace / "soul_narrative_FINAL_EDITED.mp4"
    input_video.write_text("dummy video content")
    
    output_video = temp_workspace / "soul_narrative_YOUTUBE_PREMIUM.mp4"
    real_font = load_japanese_font(20)
    
    def mock_run(cmd, **kwargs):
        if cmd[0] == "ffmpeg":
            output_video.write_text("dummy output video content")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")
        elif cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="125.5\n", stderr="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    if "backend.add_premium_branding" in sys.modules:
        del sys.modules["backend.add_premium_branding"]
        
    with patch("subprocess.run", side_effect=mock_run) as mock_subprocess_run, \
         patch("PIL.ImageFont.truetype", return_value=real_font), \
         patch("sys.argv", ["add_premium_branding.py"]):
        
        runpy.run_module(
            "backend.add_premium_branding", 
            run_name="__main__"
        )
        
        assert mock_subprocess_run.call_count == 2


def test_main_block_failure(temp_workspace):
    """__main__ ブロックで追加が失敗したケースのカバレッジを通す (失敗ケース)"""
    input_video = temp_workspace / "soul_narrative_FINAL_EDITED.mp4"
    input_video.write_text("dummy video content")
    
    real_font = load_japanese_font(20)
    
    if "backend.add_premium_branding" in sys.modules:
        del sys.modules["backend.add_premium_branding"]
        
    with patch("subprocess.run") as mock_run, \
         patch("PIL.ImageFont.truetype", return_value=real_font), \
         patch("sys.argv", ["add_premium_branding.py"]):
        
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="ffmpeg error details"
        )
        
        runpy.run_module(
            "backend.add_premium_branding", 
            run_name="__main__"
        )
        
        assert mock_run.call_count == 1


# -------------------------------------------------------------
# サムネイル品質検証および StageBoundAgent 連携テスト
# -------------------------------------------------------------

def test_generate_premium_thumbnail_quality_and_load(tmp_path):
    """プレミアムサムネイル画像の解像度、アスペクト比、ファイルサイズ、Pillowロード確認"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumbnail = tmp_path / "premium_thumbnail.png"
    out_preview = tmp_path / "premium_preview.png"

    # ダミーロゴを作る
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    # BASE_DIRを一時ディレクトリに差し替え
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        # 生成
        apb.generate_premium_branding_thumbnail(
            out_thumbnail, 
            width=1280, 
            height=720, 
            text="Premium Video Title", 
            preview_path=out_preview
        )

        # 正常系検証
        info = apb.validate_thumbnail(out_thumbnail)
        assert info["width"] >= 1280, f"Resolution width must be >= 1280, got {info['width']}"
        assert info["height"] >= 720, f"Resolution height must be >= 720, got {info['height']}"
        assert abs(info["width"] / info["height"] - 16.0 / 9.0) < 0.01, f"Aspect ratio must be 16:9, got {info['width'] / info['height']:.3f}"
        assert info["size_bytes"] < 4 * 1024 * 1024, f"File size must be < 4MB, got {info['size_bytes']} bytes"

        # Pillowでの読み込みと破損がないことの確認
        with Image.open(out_thumbnail) as img:
            img.verify()
        with Image.open(out_thumbnail) as img:
            img.load()

        info_prev = apb.validate_thumbnail(out_preview, is_preview=True)
        assert info_prev["width"] >= 320, f"Preview width must be >= 320, got {info_prev['width']}"
        assert info_prev["height"] >= 180, f"Preview height must be >= 180, got {info_prev['height']}"
        assert abs(info_prev["width"] / info_prev["height"] - 16.0 / 9.0) < 0.01
        assert info_prev["size_bytes"] < 4 * 1024 * 1024

        # 異常解像度/アスペクト比の検証
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            apb.generate_premium_branding_thumbnail(out_thumbnail, width=1024, height=720)
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            apb.generate_premium_branding_thumbnail(out_thumbnail, width=1280, height=800)

        # 破損画像ファイルのロード失敗検知テスト
        corrupted_file = tmp_path / "corrupted_thumb.png"
        corrupted_file.write_text("invalid png header and corrupted content")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            apb.validate_thumbnail(corrupted_file)

        # 4MBサイズ制限の超過検知テスト
        oversized_file = tmp_path / "oversized_thumb.png"
        # 4MBを超えるダミーデータを作成して書き込む
        with open(oversized_file, "wb") as f:
            f.write(b"\x00" * (4 * 1024 * 1024 + 100))
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            apb.validate_thumbnail(oversized_file)
            
    finally:
        apb.BASE_DIR = original_base


@pytest.mark.anyio
async def test_premium_stage_bound_agent_integration(tmp_path):
    """プレミアムサムネイルタスクが StageBoundAgent と正常に連携すること"""
    import json
    import sqlite3
    import asyncio
    import backend.add_premium_branding as apb
    from PIL import Image
    from agents.stage_bound_agent import StageBoundAgent

    # ダミーロゴを作る
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        db_file = tmp_path / "premium_tasks.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        # タスクパラメータを設定
        agent.output_dir = str(tmp_path)
        agent.width = 1280
        agent.height = 720
        agent.text = "Test Premium Video"

        task_id = "test_premium_thumb_task_001"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        async def process_task(tid):
            return await apb.resolve_premium_branding_task(tid, agent=agent)

        await agent.start(process_task)

        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 結果の確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0

        await agent.stop()
    finally:
        apb.BASE_DIR = original_base


@pytest.mark.anyio
async def test_premium_stage_bound_agent_retry_on_failure(tmp_path):
    """プレミアムサムネイルタスクが失敗時に正しくリトライされ、FAILEDになること"""
    import sqlite3
    import asyncio
    import backend.add_premium_branding as apb
    from agents.stage_bound_agent import StageBoundAgent

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        db_file = tmp_path / "premium_tasks_retry.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_premium_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 既存のファイルを output_dir に指定することで、ディレクトリ作成やファイル書き込み時に確実にエラーを起こさせる
        dummy_file = tmp_path / "dummy_file.txt"
        dummy_file.write_text("not a directory")
        agent.output_dir = str(dummy_file)
        agent.width = 1280
        agent.height = 720
        agent.text = "Test Premium Video"

        async def process_task(tid):
            return await apb.resolve_premium_branding_task(tid, agent=agent)

        await agent.start(process_task)

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
        assert row[1] is not None

        await agent.stop()
    finally:
        apb.BASE_DIR = original_base


# =============================================================
# 追加の境界値・例外系・未カバー行カバレッジテストケース
# =============================================================

def test_generate_premium_thumbnail_edge_cases(tmp_path):
    """プレミアムサムネイル生成における各種入力引数のバリデーションと折り返し・縮小等の境界値テスト"""
    out_thumb = tmp_path / "edge_case_thumb.png"
    out_prev = tmp_path / "edge_case_prev.png"

    # 1. output_path が None または空
    with pytest.raises(ValueError, match="Output path cannot be empty"):
        apb.generate_premium_branding_thumbnail(None)
    with pytest.raises(ValueError, match="Output path cannot be empty"):
        apb.generate_premium_branding_thumbnail("")

    # 2. output_path に不正な文字がある場合 (Windows依存のエラー)
    with pytest.raises(OSError, match="Invalid characters in path"):
        apb.generate_premium_branding_thumbnail(str(tmp_path / "invalid_name_*.png"))

    # 3. width / height が非整数の場合
    with pytest.raises(ValueError, match="Width and height must be integers"):
        apb.generate_premium_branding_thumbnail(out_thumb, width="abc", height=720)

    # 4. width / height が 0 以下の場合
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        apb.generate_premium_branding_thumbnail(out_thumb, width=0, height=720)
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=-10)

    # 5. preview_path に不正な文字がある場合
    with pytest.raises(OSError, match="Invalid characters in preview path"):
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, preview_path=str(tmp_path / "invalid_prev_?.png"))

    # 6. text が None/空 の時のデフォルトテキスト処理
    # (BASE_DIRをtmp_pathにしてロゴなし状態)
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        # text=Noneで実行し、デフォルトテキスト生成ルートを通す
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text=None)
        assert out_thumb.exists()
        
        # 7. テキストが30文字を超える長文の場合の折り返し処理
        long_text = "これは非常に長いテキストです。" * 10
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text=long_text)
        assert out_thumb.exists()

        # 8. 枠内に収まりきらない巨大テキストによるフォントサイズ極小化 (フォントサイズ縮小ループの完遂)
        very_long_text = "極小" * 200
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text=very_long_text)
        assert out_thumb.exists()
    finally:
        apb.BASE_DIR = original_base


def test_generate_premium_thumbnail_io_errors(tmp_path):
    """パス作成エラーや、保存時の例外など、I/O例外発生時のハンドリングと一時ファイルクリーンアップ"""
    out_thumb = tmp_path / "io_error_thumb.png"

    # 1. output_path の親ディレクトリ作成失敗 (mkdirがTypeErrorを投げる場合を擬似再現)
    with patch("pathlib.Path.mkdir", side_effect=TypeError("mocked mkdir error")):
        with pytest.raises(OSError, match="Failed to create directory structure"):
            apb.generate_premium_branding_thumbnail(out_thumb)

    # 2. preview_path の親ディレクトリ作成失敗
    with patch("pathlib.Path.mkdir") as mock_mkdir:
        # 1回目のmkdir(output_path用)はパスし、2回目(preview_path用)でTypeErrorを投げるように設定
        mock_mkdir.side_effect = [None, TypeError("mocked preview mkdir error")]
        with pytest.raises(OSError, match="Failed to create preview directory structure"):
            apb.generate_premium_branding_thumbnail(out_thumb, preview_path=tmp_path / "prev_dir" / "prev.png")

    # 3. 画像保存時 (Image.save) またはファイル名変更 (rename) 時の例外発生と、一時ファイルの確実な削除
    # Image.saveがOSErrorを投げた時に、確実に一時ファイルをunlinkして例外を再送出するか
    with patch("PIL.Image.Image.save", side_effect=OSError("mocked save error")):
        # 一時ファイル作成用のUUIDを固定して存在確認できるようにする
        with patch("uuid.uuid4") as mock_uuid:
            dummy_uuid = MagicMock()
            dummy_uuid.hex = "testuuid123"
            mock_uuid.return_value = dummy_uuid
            
            expected_temp = out_thumb.with_suffix(".testuuid123.tmp")
            
            with pytest.raises(OSError, match="mocked save error"):
                apb.generate_premium_branding_thumbnail(out_thumb)
                
            # 一時ファイルが残っていないことを検証
            assert not expected_temp.exists()


def test_validate_thumbnail_failures(tmp_path):
    """validate_thumbnail における存在しないファイル、低解像度、アスペクト比エラー、破損等の検証"""
    # 1. 存在しないファイル
    non_existent = tmp_path / "does_not_exist.png"
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        apb.validate_thumbnail(non_existent)

    # 2. 低解像度 (1280x720 未満)
    low_res_file = tmp_path / "low_res.png"
    img_low = Image.new("RGB", (640, 360))
    img_low.save(low_res_file)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        apb.validate_thumbnail(low_res_file)

    # 3. 低解像度プレビュー (320x180 未満)
    low_prev_file = tmp_path / "low_prev.png"
    img_prev = Image.new("RGB", (160, 90))
    img_prev.save(low_prev_file)
    with pytest.raises(ValueError, match="Preview resolution must be at least 320x180"):
        apb.validate_thumbnail(low_prev_file, is_preview=True)

    # 4. アスペクト比が 16:9 ではない場合
    bad_aspect_file = tmp_path / "bad_aspect.png"
    img_aspect = Image.new("RGB", (1280, 1024)) # 5:4
    img_aspect.save(bad_aspect_file)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        apb.validate_thumbnail(bad_aspect_file)

    # 5. ピクセルデータが破損している場合 (Image.loadで例外が発生するケース)
    corrupted_load_file = tmp_path / "corrupted_load.png"
    img_ok = Image.new("RGB", (1280, 720))
    img_ok.save(corrupted_load_file)
    
    # Image.openで開いたオブジェクトの load() が OSError を投げるようにモックする
    original_open = Image.open
    def mock_open(*args, **kwargs):
        img_obj = original_open(*args, **kwargs)
        # loadメソッドをモック
        img_obj.load = MagicMock(side_effect=OSError("corrupted pixel data read error"))
        return img_obj

    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            apb.validate_thumbnail(corrupted_load_file)


@pytest.mark.anyio
async def test_resolve_premium_branding_task_failure(tmp_path):
    """resolve_premium_branding_task 内で例外が発生した際に、ログが出力されて再レイズされること"""
    import sys
    from io import StringIO
    
    # 標準エラーをモックする
    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf
    try:
        # 例外を発生させるため、不正な引数でタスクリゾルバを実行
        with pytest.raises(ValueError):
            # widthを不正な値にすることで generate_premium_branding_thumbnail で ValueError を発生させる
            agent = MagicMock()
            agent.output_dir = str(tmp_path)
            agent.width = "invalid_width"
            await apb.resolve_premium_branding_task("fail_task_001", agent=agent)
            
        log_content = stderr_buf.getvalue()
        assert "CRITICAL [StageBoundAgent:fail_task_001] Task processing failed" in log_content
    finally:
        sys.stderr = original_stderr


def test_font_loading_fallback(tmp_path):
    """フォント読み込み時に全てのフォントファイルが存在しない/読み込み失敗した際、デフォルトフォントにフォールバックすること"""
    out_thumb = tmp_path / "fallback_font_thumb.png"

    # 全てのフォントパスの存在チェックをFalseに、load_defaultが成功するようにモック
    original_exists = Path.exists
    def mock_exists(self):
        # フォント関連のパスだけ存在しないものとする
        if "Fonts" in str(self) or "fonts" in str(self) or "truetype" in str(self):
            return False
        return original_exists(self)

    with patch.object(Path, "exists", autospec=True, side_effect=mock_exists), \
         patch("PIL.ImageFont.load_default", return_value=ImageFont.load_default()) as mock_load_default:
        
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text="Fallback Test")
        assert out_thumb.exists()
        mock_load_default.assert_called()


def test_unused_resampling_fallbacks(tmp_path):
    """Image.Resampling などの属性が存在しない場合の古い Pillow バージョン向けフォールバック分岐のテスト"""
    out_thumb = tmp_path / "resample_fallback_thumb.png"
    out_prev = tmp_path / "resample_fallback_prev.png"

    original_hasattr = hasattr
    def mock_hasattr(obj, name):
        # Imageオブジェクトに対する特定の属性チェックでFalseを返し、LANCZOS=Noneへフォールバックさせる
        if obj is Image and name in ("Resampling", "LANCZOS", "ANTIALIAS", "BICUBIC"):
            return False
        return original_hasattr(obj, name)

    with patch("builtins.hasattr", side_effect=mock_hasattr):
        apb.generate_premium_branding_thumbnail(
            out_thumb, width=1280, height=720, text="Resample Fallback", preview_path=out_prev
        )
        assert out_thumb.exists()
        assert out_prev.exists()


def test_generate_premium_thumbnail_rigorous_verification(tmp_path):
    """生成されたサムネイル画像の解像度・アスペクト比・サイズ・破損・プレミアム視覚要素の有無を厳密に検証する"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumbnail = tmp_path / "rigorous_thumbnail.png"
    out_preview = tmp_path / "rigorous_preview.png"

    # ダミーロゴを作る
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        # 1. プレミアムブランディングサムネイルおよびプレビュー画像の生成
        apb.generate_premium_branding_thumbnail(
            out_thumbnail, 
            width=1920, 
            height=1080,  # 16:9 以上の解像度で生成
            text="Rigorous Premium Verification\nLine 2", 
            preview_path=out_preview
        )

        # 2. 生成ファイルの存在確認
        assert out_thumbnail.exists()
        assert out_preview.exists()

        # 3. 破損がなく、正常に Pillow でロードできることの検証
        with Image.open(out_thumbnail) as img:
            img.verify()
        with Image.open(out_thumbnail) as img:
            img.load()  # 完全なピクセルデータロード
            
            # 解像度が 1280x720 以上であること
            width, height = img.size
            assert width >= 1280
            assert height >= 720
            assert width == 1920
            assert height == 1080
            
            # アスペクト比が 16:9 であること
            aspect_ratio = width / height
            assert abs(aspect_ratio - 16.0 / 9.0) < 0.01

            # プレミアムグラデーション等の色要素の多様性検証 (単一色ではないこと)
            colors = img.getcolors(maxcolors=256)
            # 256色以上使われているはずなので、getcolors(maxcolors=256) は None (256色を超える) が返されるはず
            assert colors is None

        # 4. ファイルサイズが 4MB 未満であることの検証
        size_bytes = out_thumbnail.stat().st_size
        assert size_bytes < 4 * 1024 * 1024

        # 5. 品質検証ロジック (validate_thumbnail) 自体の正常動作
        info = apb.validate_thumbnail(out_thumbnail)
        assert info["width"] == 1920
        assert info["height"] == 1080
        assert info["size_bytes"] == size_bytes
        assert info["format"] == "PNG"

        # プレビュー画像に対する検証
        prev_info = apb.validate_thumbnail(out_preview, is_preview=True)
        assert prev_info["width"] == 640
        assert prev_info["height"] == 360
        assert prev_info["size_bytes"] < 4 * 1024 * 1024
        assert prev_info["format"] == "PNG"

    finally:
        apb.BASE_DIR = original_base


@pytest.mark.anyio
async def test_stage_bound_agent_task_db_structure_and_migration(tmp_path):
    """StageBoundAgent にタスクを登録し、DB構造がマイグレーション要件を満たしていること、自動リトライや結果保存の連携を検証する"""
    import json
    import sqlite3
    import asyncio
    import backend.add_premium_branding as apb
    from PIL import Image
    from agents.stage_bound_agent import StageBoundAgent

    # ダミーロゴを作る
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    try:
        db_file = tmp_path / "migration_tasks.db"
        agent = StageBoundAgent(
            stage_name="premium_migration_test",
            db_path=str(db_file),
            poll_interval=0.01
        )

        # 1. DBマイグレーション確認: テーブルが自動生成されているか
        # StageBoundAgent の初期化によってスキーマ作成が実行されるため、テーブル・カラム構成を直接検証する
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        conn.close()

        # スキーマ連携に必要な必須カラムの存在検証
        assert "id" in columns
        assert "stage" in columns
        assert "status" in columns
        assert "result" in columns
        assert "error" in columns
        assert "retry_count" in columns
        assert "max_retries" in columns

        # 2. 自動リトライおよび結果保存の連携動作検証
        agent.output_dir = str(tmp_path)
        agent.width = 1280
        agent.height = 720
        agent.text = "DB Migration and Retry Collaboration Test"

        task_id = "collaboration_task_001"
        # タスクを READY ステータスで登録
        await agent.register_task(task_id, initial_status="READY", max_retries=3)

        async def process_task(tid):
            return await apb.resolve_premium_branding_task(tid, agent=agent)

        # エージェント開始
        await agent.start(process_task)

        # タスク完了を待つ (非同期)
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # データベースからタスク結果およびリトライ回数が正常に保存されているか検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        # 自動検証項目との連携
        assert result_json["width"] == 1280
        assert result_json["height"] == 720
        assert "preview" in result_json
        assert row[1] is None  # エラーなし
        assert row[2] == 0  # リトライ0回で一発成功

        await agent.stop()
    finally:
        apb.BASE_DIR = original_base


@pytest.mark.anyio
async def test_mandatory_quality_criteria_verification(tmp_path):
    """【必須品質基準自動検証】
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    import json
    import sqlite3
    import asyncio
    import backend.add_premium_branding as apb
    from PIL import Image
    from agents.stage_bound_agent import StageBoundAgent

    # 一時環境構築
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    try:
        out_path = tmp_path / "quality_test_thumbnail.png"
        prev_path = tmp_path / "quality_test_preview.png"

        # 1. 画像生成の実行
        apb.generate_premium_branding_thumbnail(
            out_path,
            width=1280,
            height=720,
            text="Mandatory Quality Criteria Verification",
            preview_path=prev_path
        )

        # 2. 生成ファイルの存在と破損のないことの検証
        assert out_path.exists(), "出力ファイルが存在しません。"
        with Image.open(out_path) as img:
            img.verify()
        with Image.open(out_path) as img:
            img.load()  # 正常にロード可能
            width, height = img.size
            
            # 解像度が 1280x720 以上であること
            assert width >= 1280, f"解像度の幅が足りません: {width}"
            assert height >= 720, f"解像度の高さが足りません: {height}"
            
            # アスペクト比が 16:9 であること (1.7777...)
            aspect_ratio = width / height
            assert abs(aspect_ratio - 16.0 / 9.0) < 0.01, f"アスペクト比が16:9ではありません: {aspect_ratio}"

        # 3. ファイルサイズが 4MB 未満であること
        size_bytes = out_path.stat().st_size
        assert size_bytes < 4 * 1024 * 1024, f"ファイルサイズが4MBを超えています: {size_bytes} bytes"

        # 4. StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
        db_file = tmp_path / "quality_criteria_tasks.db"
        agent = StageBoundAgent(
            stage_name="quality_criteria_test",
            db_path=str(db_file),
            poll_interval=0.01
        )
        
        # ディレクトリ構造と設定
        agent.output_dir = str(tmp_path)
        agent.width = 1920
        agent.height = 1080
        agent.text = "Agent integration test"

        # マイグレーション確認: テーブルが自動生成されているか
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        for col in ["id", "stage", "status", "result", "error", "retry_count", "max_retries"]:
            assert col in columns, f"DBマイグレーションに必要なカラム {col} が存在しません。"

        task_id = "mandatory_task_001"
        # タスク登録
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        async def process_task(tid):
            return await apb.resolve_premium_branding_task(tid, agent=agent)

        # エージェント開始してタスクを実行
        await agent.start(process_task)

        # タスク完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED", "エージェント連携タスクが完了しませんでした。"

        # 結果保存の検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "DBにタスク結果が保存されていません。"
        result_json = json.loads(row[0])
        assert result_json["width"] == 1920
        assert result_json["height"] == 1080
        assert row[1] is None, "エラーが記録されています。"
        assert row[2] == 0, f"不要なリトライが行われました: {row[2]}"

        await agent.stop()
    finally:
        apb.BASE_DIR = original_base


def test_validate_thumbnail_aspect_ratio_precision(tmp_path):
    """アスペクト比の判定精度（16:9）を精密に検証する。許容誤差を超えるアスペクト比（例: 1280x721や1281x720など）の画像がValueErrorを投げること。"""
    import backend.add_premium_branding as apb
    from PIL import Image

    # 1. 許容される画像 (1280x720) -> 1.7777...
    ok_file = tmp_path / "aspect_ok.png"
    img_ok = Image.new("RGB", (1280, 720))
    img_ok.putpixel((0, 0), (255, 0, 0)) # 単一色回避
    img_ok.save(ok_file)
    info = apb.validate_thumbnail(ok_file)
    assert info["width"] == 1280
    assert info["height"] == 720

    # 2. 誤差を超える画像 (1280x721) -> 1.7753... 
    err_file1 = tmp_path / "aspect_err1.png"
    img_err1 = Image.new("RGB", (1280, 721))
    img_err1.save(err_file1)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        apb.validate_thumbnail(err_file1)

    # 3. 誤差を超える画像 (1281x720) -> 1.7791...
    err_file2 = tmp_path / "aspect_err2.png"
    img_err2 = Image.new("RGB", (1281, 720))
    img_err2.save(err_file2)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        apb.validate_thumbnail(err_file2)


def test_validate_thumbnail_file_size_boundary(tmp_path):
    """ファイルサイズ制限（4MB）の境界値を検証する。"""
    import backend.add_premium_branding as apb
    from PIL import Image

    # 4MB未満 (3.99MB) のファイル
    under_limit_file = tmp_path / "under_limit.png"
    with open(under_limit_file, "wb") as f:
        # 有効な画像ヘッダ情報とピクセルデータでダミー画像ファイルを作成
        img = Image.new("RGB", (1280, 720))
        img.putpixel((0, 0), (255, 0, 0)) # 単一色回避
        img.save(f, "PNG")
        # 残りをゼロパディングして、4MB未満 (4MB - 100バイト) に調整
        current_size = f.tell()
        target_size = 4 * 1024 * 1024 - 100
        if target_size > current_size:
            f.write(b"\x00" * (target_size - current_size))

    # 検証（サイズチェックは画像ロード前に行われる）
    info = apb.validate_thumbnail(under_limit_file)
    assert info["size_bytes"] < 4 * 1024 * 1024

    # 4MB以上 (4.00MB) のファイル
    over_limit_file = tmp_path / "over_limit.png"
    with open(over_limit_file, "wb") as f:
        img = Image.new("RGB", (1280, 720))
        img.save(f, "PNG")
        current_size = f.tell()
        target_size = 4 * 1024 * 1024 + 100
        if target_size > current_size:
            f.write(b"\x00" * (target_size - current_size))

    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        apb.validate_thumbnail(over_limit_file)


def test_validate_thumbnail_integrity_check(tmp_path):
    """Pillowのロードにおいて、画像ファイルの一部が欠損または破損している場合に正常にロード検知エラーを発生させる。"""
    import backend.add_premium_branding as apb

    corrupted_file = tmp_path / "corrupted_integrity.png"
    # 不正なバイト列（ヘッダー等はPNGに見えるが中身が壊れている）
    corrupted_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x05\x00\x00\x00\x02\xd0\x08\x02\x00\x00\x00" + b"\x00" * 100)

    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        apb.validate_thumbnail(corrupted_file)


def test_generate_premium_thumbnail_jpeg_format(tmp_path):
    """サムネイル画像をJPEG形式（.jpg/.jpeg）で保存した際、JPEGフォーマットで保存され、quality=95およびsubsampling=0のオプションが正しく適用されていることを検証する"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumbnail = tmp_path / "premium_thumbnail.jpg"
    out_preview = tmp_path / "premium_preview.jpeg"

    # ダミーロゴを作る
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    logo = Image.new('RGBA', (23, 45), (255, 0, 0, 255))
    logo.save(logo_dir / "brand_logo.png")

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    
    original_save = Image.Image.save
    saved_calls = []

    def spy_save(self_img, fp, format=None, **kwargs):
        saved_calls.append({
            "fp": fp,
            "format": format,
            "kwargs": kwargs
        })
        return original_save(self_img, fp, format, **kwargs)

    try:
        # クラスメソッドをモンキーパッチ
        Image.Image.save = spy_save
        
        apb.generate_premium_branding_thumbnail(
            out_thumbnail, 
            width=1280, 
            height=720, 
            text="Premium Video Title JPEG", 
            preview_path=out_preview
        )

        # 保存先の確認
        assert out_thumbnail.exists()
        assert out_preview.exists()

        # 画像フォーマットの検証
        info = apb.validate_thumbnail(out_thumbnail)
        assert info["format"] == "JPEG"

        info_prev = apb.validate_thumbnail(out_preview, is_preview=True)
        assert info_prev["format"] == "JPEG"

        # saveメソッド呼び出し時の引数の検証
        # 1つ目はサムネイル(JPEG)、2つ目はプレビュー(JPEG)
        assert len(saved_calls) >= 2
        
        # サムネイル保存時の検証
        thumb_call = saved_calls[0]
        assert thumb_call["format"] == "JPEG"
        assert thumb_call["kwargs"].get("quality") == 95
        assert thumb_call["kwargs"].get("subsampling") == 0

        # プレビュー保存時の検証
        prev_call = saved_calls[1]
        assert prev_call["format"] == "JPEG"
        assert prev_call["kwargs"].get("quality") == 95
        assert prev_call["kwargs"].get("subsampling") == 0

    finally:
        # モンキーパッチを戻す
        Image.Image.save = original_save
        apb.BASE_DIR = original_base


def test_additional_validation_types(tmp_path):
    """output_path や preview_path、file_path の各種不正な型や拡張子の検証"""
    import backend.add_premium_branding as apb

    # 1. output_path の不正な型 (TypeError)
    with pytest.raises(TypeError, match="Output path must be a string or Path object"):
        apb.generate_premium_branding_thumbnail(123)

    # 2. output_path の不正な拡張子 (ValueError)
    with pytest.raises(ValueError, match="Unsupported file format"):
        apb.generate_premium_branding_thumbnail(tmp_path / "test.gif")

    # 3. width / height が上限を超える (ValueError)
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        apb.generate_premium_branding_thumbnail(tmp_path / "test.png", width=4000, height=2160)

    # 4. preview_path の不正な型 (TypeError)
    with pytest.raises(TypeError, match="Preview path must be a string or Path object"):
        apb.generate_premium_branding_thumbnail(tmp_path / "test.png", preview_path=123)

    # 5. validate_thumbnail の空パス (ValueError)
    with pytest.raises(ValueError, match="File path cannot be empty"):
        apb.validate_thumbnail("")
    with pytest.raises(ValueError, match="File path cannot be empty"):
        apb.validate_thumbnail(None)

    # 6. validate_thumbnail の不正な型 (TypeError)
    with pytest.raises(TypeError, match="File path must be a string or Path object"):
        apb.validate_thumbnail(123)

    # 7. validate_thumbnail がファイルではなくディレクトリを指している (ValueError)
    with pytest.raises(ValueError, match="Target path is not a file"):
        apb.validate_thumbnail(tmp_path)


def test_validate_thumbnail_solid_color_isolated(tmp_path):
    """単一色の画像に対して validate_thumbnail が ValueError を投げることの独立検証"""
    import backend.add_premium_branding as apb
    from PIL import Image

    single_color_file = tmp_path / "single_color.png"
    img = Image.new("RGB", (1280, 720), (255, 255, 255))
    img.save(single_color_file)
    with pytest.raises(ValueError, match="Image is a single solid color"):
        apb.validate_thumbnail(single_color_file)


def test_shutil_disk_usage_variants(tmp_path):
    """shutil.disk_usage のフォールバックおよび容量不足エラーの検証"""
    import backend.add_premium_branding as apb
    import shutil

    out_thumb = tmp_path / "disk_test.png"

    # 1. 空き容量不足 (10MB未満)
    mock_usage_low = MagicMock()
    mock_usage_low.free = 5 * 1024 * 1024  # 5MB
    with patch("shutil.disk_usage", return_value=mock_usage_low):
        with pytest.raises(OSError, match="Insufficient disk space"):
            apb.generate_premium_branding_thumbnail(out_thumb)

    # 2. usage に free 属性がなく、かつインデックスアクセスも失敗するケース (例外発生)
    # これにより内側の except ブロックに入り、free_space = 100MB にフォールバックする
    class BadUsage:
        def __getitem__(self, item):
            raise KeyError("no index access")

    with patch("shutil.disk_usage", return_value=BadUsage()):
        # ロゴなし状態で生成が成功することを確認
        original_base = apb.BASE_DIR
        apb.BASE_DIR = tmp_path
        try:
            apb.generate_premium_branding_thumbnail(out_thumb)
            assert out_thumb.exists()
        finally:
            apb.BASE_DIR = original_base

    # 3. ディレクトリ作成時に TypeError 以外の例外が発生した場合 (軽微な例外として無視される)
    # ディレクトリ作成時 (mkdir) に KeyError を投げ、それが無視されて後続処理に進むことを確認
    with patch("pathlib.Path.mkdir", side_effect=KeyError("some minor error")):
        original_base = apb.BASE_DIR
        apb.BASE_DIR = tmp_path
        try:
            apb.generate_premium_branding_thumbnail(out_thumb)
            assert out_thumb.exists()
        finally:
            apb.BASE_DIR = original_base


def test_image_resampling_attribute_errors(tmp_path):
    """Image.Resampling 等の属性が欠けている場合 (古いPillow) のフォールバック"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumb = tmp_path / "resample_err.png"
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # Image.Resampling アクセス時に AttributeError を投げ、かつ Image.BICUBIC アクセス時も AttributeError
    # を投げて、最終的に 3 にフォールバックするルートを通す。
    original_getattr = Image.__getattribute__

    def mock_getattr(name):
        if name in ("Resampling", "BICUBIC"):
            raise AttributeError("mocked attribute error")
        return original_getattr(Image, name)

    try:
        with patch("PIL.Image.__getattribute__", side_effect=mock_getattr):
            apb.generate_premium_branding_thumbnail(out_thumb)
            assert out_thumb.exists()
    finally:
        apb.BASE_DIR = original_base


def test_logo_load_failure(tmp_path):
    """ロゴ画像は存在するが、Image.open が失敗して警告を出力するケース"""
    import backend.add_premium_branding as apb
    import sys
    from io import StringIO

    out_thumb = tmp_path / "logo_fail_thumb.png"
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    # 空ファイルを作成して存在させ、Image.openが失敗するようにする
    (logo_dir / "brand_logo.png").touch()

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf

    try:
        apb.generate_premium_branding_thumbnail(out_thumb)
        assert out_thumb.exists()
        
        log_content = stderr_buf.getvalue()
        assert "Warning: Failed to load brand logo for thumbnail" in log_content
    finally:
        sys.stderr = original_stderr
        apb.BASE_DIR = original_base


def test_font_size_reduction_exhausted(tmp_path):
    """テキストが大きすぎる、またはフォント取得失敗によりフォントサイズが極小以下になるケース"""
    import backend.add_premium_branding as apb
    from PIL import ImageFont


    out_thumb = tmp_path / "font_ex_thumb.png"
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # 1. font_paths のフォント読み込み時に OSError が発生し、load_default も OSError を投げるケース
    # これにより font = None になり、フォントサイズ削減ループを即座に break する。
    # 描画時のデフォルトフォントロードエラーを防ぐため、ImageDraw.Draw.text 自体をモックする。
    with patch("PIL.ImageFont.truetype", side_effect=OSError("font load failed")), \
         patch("PIL.ImageFont.load_default", side_effect=OSError("default font load failed")), \
         patch("PIL.ImageDraw.ImageDraw.text") as mock_text:
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test default fail")
        assert out_thumb.exists()
        mock_text.assert_called()

    # 2. ImageFont.truetype が ValueError を投げ、フォールバックの continue パスを通す
    # 最初のいくつかのフォントで ValueError を投げ、最終的に msgothic が成功するようにする
    real_font = ImageFont.load_default()
    def mock_truetype(fp, size):
        if "YuGothB" in str(fp):
            raise ValueError("mocked value error")
        return real_font

    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test continue path")
        assert out_thumb.exists()

    # 3. textbbox が OSError / ValueError を投げる場合
    # これにより max_line_w = len(line) * font_size にフォールバックする
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=OSError("bbox error")):
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test bbox error path")
        assert out_thumb.exists()


def test_io_unlinks_oserrors(tmp_path):
    """ファイルの存在チェックと削除時の例外 (OSError) が適切に無視されること"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumb = tmp_path / "unlink_test.png"
    out_prev = tmp_path / "unlink_test_prev.png"

    # ダミーファイルをあらかじめ作っておく
    out_thumb.touch()
    out_prev.touch()

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # Windows での FileExistsError (rename 失敗) を防ぐため、Path.rename もモックする。
    original_unlink = Path.unlink
    
    def mock_unlink(self_path):
        if self_path.name in (out_thumb.name, out_prev.name):
            raise OSError("mocked unlink error")
        if ".tmp" in self_path.name:
            raise OSError("mocked temp unlink error")
        original_unlink(self_path)

    # 一時ファイルの削除時エラーによる警告を確認するため、stderr をキャプチャ
    import sys
    from io import StringIO
    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf

    try:
        with patch.object(Path, "unlink", autospec=True, side_effect=mock_unlink):
            # Path.rename で意図的にエラーを起こさせて、一時ファイルのクリーンアップルートを通す
            with patch.object(Path, "rename", side_effect=OSError("save error for temp clean")):
                with pytest.raises(OSError, match="save error for temp clean"):
                    apb.generate_premium_branding_thumbnail(out_thumb, preview_path=out_prev)
            
            # 通常の unlink() エラー無視ルートを通す (Path.rename が動くようにモック)
            with patch.object(Path, "rename") as mock_rename:
                apb.generate_premium_branding_thumbnail(out_thumb, preview_path=out_prev)
                mock_rename.assert_called()

        log_content = stderr_buf.getvalue()
        assert "WARNING: Failed to cleanup temp file" in log_content

    finally:
        sys.stderr = original_stderr
        apb.BASE_DIR = original_base


@pytest.mark.anyio
async def test_resolve_task_resolution_parsing(tmp_path):
    """resolve_premium_branding_task における agent のパラメータパースと preview_path 不存在ケース"""
    import backend.add_premium_branding as apb
    import json

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # MagicMock は hasattr に対して意図しない True を返すため、プレーンなダミークラスを使用する
    class DummyAgent:
        def __init__(self, output_dir, resolution=None, width=None, height=None, text=None):
            self.output_dir = output_dir
            if resolution:
                self.resolution = resolution
            if width:
                self.width = width
            if height:
                self.height = height
            if text:
                self.text = text

    try:
        # 1. agent に resolution="1920x1080" が指定された場合
        agent1 = DummyAgent(str(tmp_path), resolution="1920x1080", text="Agent custom resolution")

        res1_str = await apb.resolve_premium_branding_task("task_res_1", agent=agent1)
        res1 = json.loads(res1_str)
        assert res1["width"] == 1920
        assert res1["height"] == 1080

        # 2. agent.resolution パース失敗ケース (デフォルトサイズに戻る)
        agent2 = DummyAgent(str(tmp_path), resolution="invalid_format")
        
        res2_str = await apb.resolve_premium_branding_task("task_res_2", agent=agent2)
        res2 = json.loads(res2_str)
        assert res2["width"] == 1280
        assert res2["height"] == 720

        # 3. preview_path が存在しないケース (preview_path が生成されない等)
        original_exists = Path.exists

        def mock_exists_path(self_path):
            if "_preview.png" in self_path.name:
                return False
            return original_exists(self_path)

        with patch.object(Path, "exists", autospec=True, side_effect=mock_exists_path):
            agent3 = DummyAgent(str(tmp_path))
            res3_str = await apb.resolve_premium_branding_task("task_res_3", agent=agent3)
            res3 = json.loads(res3_str)
            assert "preview" not in res3

    finally:
        apb.BASE_DIR = original_base



# =============================================================
# 追加のカバレッジ改善テストケース (修正版・カバレッジ極大化)
# =============================================================

@pytest.mark.anyio
async def test_resolve_premium_branding_task_agent_none_and_falsy(tmp_path):
    """resolve_premium_branding_task で agent が None または agent.output_dir が falsy なケース"""
    import backend.add_premium_branding as apb
    import json
    
    # 1. agent = None のケース
    # BASE_DIRをtmp_pathにして、かつデフォルトの出力先に書き込まれないよう Path.__truediv__ をモック
    with patch("pathlib.Path.__truediv__", return_value=tmp_path / "agent_none_task.png") as mock_div:
        with patch("backend.add_premium_branding.generate_premium_branding_thumbnail") as mock_gen, \
             patch("backend.add_premium_branding.validate_thumbnail", return_value={"width": 1280, "height": 720, "size_bytes": 100, "format": "PNG"}):
            
            result = await apb.resolve_premium_branding_task("agent_none_task", agent=None)
            result_json = json.loads(result)
            assert result_json["width"] == 1280
            
    # 2. agent は存在するが agent.output_dir が None (falsy) のケース
    class DummyAgentNoDir:
        def __init__(self):
            self.output_dir = None
            self.resolution = None
            self.width = None
            self.height = None
            self.text = None

    with patch("pathlib.Path.__truediv__", return_value=tmp_path / "agent_nodir_task.png") as mock_div:
        with patch("backend.add_premium_branding.generate_premium_branding_thumbnail") as mock_gen, \
             patch("backend.add_premium_branding.validate_thumbnail", return_value={"width": 1280, "height": 720, "size_bytes": 100, "format": "PNG"}):
            
            result = await apb.resolve_premium_branding_task("agent_nodir_task", agent=DummyAgentNoDir())
            result_json = json.loads(result)
            assert result_json["width"] == 1280


def test_image_resampling_deep_attribute_errors(tmp_path):
    """LANCZOS, Resampling, BICUBIC などの古いPillow of 非存在属性フォールバックの網羅"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumb = tmp_path / "resample_deep_err.png"
    out_prev = tmp_path / "resample_deep_err_prev.png"
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # Image wrapper proxy to mock lack of Resampling, LANCZOS, and BICUBIC
    class ImageWrapper:
        def __getattr__(self, name):
            if name in ("Resampling", "LANCZOS", "BICUBIC"):
                raise AttributeError(f"mocked {name} error")
            return getattr(Image, name)

    try:
        with patch("backend.add_premium_branding.Image", ImageWrapper()):
            apb.generate_premium_branding_thumbnail(
                out_thumb, width=1280, height=720, text="Deep Fallback 2", preview_path=out_prev
            )
            assert out_thumb.exists()
            assert out_prev.exists()
    finally:
        apb.BASE_DIR = original_base



def test_font_size_reduction_loop_exhausted(tmp_path):
    """フォントサイズ削減ループで while ループの条件 (font_size >= 12 * scale) を満たさなくなって抜けるケース"""
    import backend.add_premium_branding as apb
    
    out_thumb = tmp_path / "font_loop_exhaust_thumb.png"
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # textbbox が常に巨大な値を返すようにして、フォントサイズ削減ループが 12 * scale 未満に達するまで break しないようにする
    # width*scale は 1280 * 2 = 2560。マージン等考慮すると max_text_width は 2560 - 240 = 2320
    # textbbox が常に (0, 0, 9999, 9999) を返すようにモックする
    with patch("PIL.ImageDraw.ImageDraw.textbbox", return_value=(0, 0, 9999, 9999)):
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text="Force Loop Exhaust")
        assert out_thumb.exists()
        
    apb.BASE_DIR = original_base

# =============================================================
# 追加のカバレッジ改善テストケース (修正版・PASS保証)
# =============================================================

def test_generate_premium_thumbnail_more_edge_cases(tmp_path):
    """引数の型、非対応拡張子、最大解像度超過、およびロゴ読み込み失敗時の警告ログを検証"""
    import backend.add_premium_branding as apb
    import sys
    from io import StringIO

    # 1. output_path の型が不正
    with pytest.raises(TypeError, match="Output path must be a string or Path object"):
        apb.generate_premium_branding_thumbnail(12345)

    # 2. preview_path の型が不正
    out_thumb = tmp_path / "edge_type_thumb.png"
    with pytest.raises(TypeError, match="Preview path must be a string or Path object"):
        apb.generate_premium_branding_thumbnail(out_thumb, preview_path=9999)

    # 3. 拡張子が非対応
    with pytest.raises(ValueError, match="Unsupported file format"):
        apb.generate_premium_branding_thumbnail(tmp_path / "thumb.gif")

    # 4. 最大解像度の超過
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        apb.generate_premium_branding_thumbnail(out_thumb, width=4000, height=2250)

    # 5. ロゴ読み込み失敗時の stderr 警告 (ダミーロゴをtouchして存在させてエラーを起こす)
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path
    
    logo_dir = tmp_path / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    (logo_dir / "brand_logo.png").touch()  # 壊れたロゴファイルを存在させる

    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf
    try:
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text="No Logo Test")
        assert "Warning: Failed to load brand logo for thumbnail" in stderr_buf.getvalue()
    finally:
        sys.stderr = original_stderr
        apb.BASE_DIR = original_base


def test_generate_premium_thumbnail_disk_usage_exceptions(tmp_path):
    """shutil.disk_usage の例外ハンドリングを検証"""
    import backend.add_premium_branding as apb
    
    out_thumb = tmp_path / "disk_test.png"

    # 1. usageオブジェクトが free 属性を持たず、インデックス2アクセスも失敗する場合のフォールバック
    class DummyUsageNoFree:
        def __getattr__(self, name):
            raise AttributeError("no attribute")
        def __getitem__(self, item):
            raise IndexError("no index")

    with patch("shutil.disk_usage", return_value=DummyUsageNoFree()):
        apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text="Fallback Disk Test")
        assert out_thumb.exists()

    if out_thumb.exists():
        out_thumb.unlink()

    # 2. 空き容量が不足している場合 (10MB 未満)
    class DummyUsageLowSpace:
        free = 5 * 1024 * 1024  # 5MB

    with patch("shutil.disk_usage", return_value=DummyUsageLowSpace()):
        with pytest.raises(OSError, match="Insufficient disk space"):
            apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720)

    # 3. disk_usage 自体が例外を投げる場合 (TypeError は OSError に変換される)
    with patch("shutil.disk_usage", side_effect=TypeError("mocked disk_usage TypeError")):
        with pytest.raises(OSError, match="Failed to create directory structure: mocked disk_usage TypeError"):
            apb.generate_premium_branding_thumbnail(out_thumb, width=1280, height=720)


def test_validate_thumbnail_more_failures(tmp_path):
    """validate_thumbnail における各種バリデーションエラーのテスト"""
    import backend.add_premium_branding as apb
    from PIL import Image

    # 1. file_path が None
    with pytest.raises(ValueError, match="File path cannot be empty"):
        apb.validate_thumbnail(None)

    # 2. file_path が空文字列
    with pytest.raises(ValueError, match="File path cannot be empty"):
        apb.validate_thumbnail("")

    # 3. file_path の型が不正
    with pytest.raises(TypeError, match="File path must be a string or Path object"):
        apb.validate_thumbnail(12345)

    # 4. 対象がファイルではなくディレクトリ
    with pytest.raises(ValueError, match="Target path is not a file"):
        apb.validate_thumbnail(tmp_path)

    # 5. 単一色の画像
    solid_file = tmp_path / "solid_color.png"
    img_solid = Image.new("RGB", (1280, 720), (0, 0, 0))
    img_solid.save(solid_file)
    with pytest.raises(ValueError, match="Image is a single solid color"):
        apb.validate_thumbnail(solid_file)


@pytest.mark.anyio
async def test_resolve_premium_branding_task_agent_edge_cases(tmp_path):
    """resolve_premium_branding_task における agent 属性のパースエラーや preview が存在しない場合の挙動を検証"""
    import backend.add_premium_branding as apb
    import json

    # 1. agent.output_dir が空文字列
    agent_empty_dir = MagicMock()
    agent_empty_dir.output_dir = ""
    agent_empty_dir.resolution = "1280x720"
    agent_empty_dir.width = None
    agent_empty_dir.height = None
    agent_empty_dir.text = "Empty Dir Test"

    # __truediv__ のパッチで、どのパス結合も一時ディレクトリを指すようにする
    with patch("pathlib.Path.__truediv__", return_value=tmp_path / "empty_dir_task.png") as mock_div:
        with patch("backend.add_premium_branding.generate_premium_branding_thumbnail") as mock_gen, \
             patch("backend.add_premium_branding.validate_thumbnail", return_value={"width": 1280, "height": 720, "size_bytes": 100, "format": "PNG"}):
            
            result = await apb.resolve_premium_branding_task("empty_dir_task", agent=agent_empty_dir)
            result_json = json.loads(result)
            assert result_json["width"] == 1280

    # 2. agent.resolution の形式が不正でパースエラーになる場合
    agent_invalid_res = MagicMock()
    agent_invalid_res.output_dir = str(tmp_path)
    agent_invalid_res.resolution = "invalid_format"
    # MagicMockのwidth/height属性がTruthyになってバグるのを防ぐために明示的にNoneをセット
    agent_invalid_res.width = None
    agent_invalid_res.height = None
    agent_invalid_res.text = "Invalid Res Test"

    with patch("backend.add_premium_branding.generate_premium_branding_thumbnail") as mock_gen, \
             patch("backend.add_premium_branding.validate_thumbnail", return_value={"width": 1280, "height": 720, "size_bytes": 100, "format": "PNG"}):
        
        # パース失敗しても例外は無視され、デフォルト解像度(1280x720)で generate が呼ばれるはず
        await apb.resolve_premium_branding_task("invalid_res_task", agent=agent_invalid_res)
        mock_gen.assert_called_once_with(
            tmp_path / "invalid_res_task.png",
            width=1280,
            height=720,
            text="Invalid Res Test",
            preview_path=tmp_path / "invalid_res_task_preview.png"
        )

    # 3. preview_path が存在しない場合の挙動
    agent_no_preview = MagicMock()
    agent_no_preview.output_dir = str(tmp_path)
    agent_no_preview.resolution = "1280x720"
    agent_no_preview.width = 1280
    agent_no_preview.height = 720
    agent_no_preview.text = "No Preview Test"

    # preview_path.exists() が False を返すようにする
    with patch("backend.add_premium_branding.generate_premium_branding_thumbnail"), \
         patch("backend.add_premium_branding.validate_thumbnail", return_value={"width": 1280, "height": 720, "size_bytes": 100, "format": "PNG"}), \
         patch("pathlib.Path.exists", return_value=False):
        
        result = await apb.resolve_premium_branding_task("no_preview_task", agent=agent_no_preview)
        result_json = json.loads(result)
        # previewキーが含まれていないことを確認
        assert "preview" not in result_json


def test_cleanup_temp_files_os_errors(tmp_path):
    """一時ファイル削除時に OSError が発生した場合のハンドリングと警告ログ出力を検証"""
    import backend.add_premium_branding as apb
    import sys
    from io import StringIO
    from pathlib import Path

    out_thumb = tmp_path / "cleanup_err_thumb.png"

    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf
    try:
        # Path.unlink が OSError をスローするようにモックする
        original_unlink = Path.unlink
        def mock_unlink(self, *args, **kwargs):
            if "tmp" in self.name:
                raise OSError("mocked unlink error")
            return original_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", mock_unlink):
            # Path.renameがOSErrorを投げて、例外クリーンアップルートへ入るようにする
            with patch.object(Path, "rename", side_effect=OSError("mocked rename error")):
                with pytest.raises(OSError, match="mocked rename error"):
                    apb.generate_premium_branding_thumbnail(out_thumb)
                    
        log_output = stderr_buf.getvalue()
        assert "WARNING: Failed to cleanup temp file" in log_output
    finally:
        sys.stderr = original_stderr


def test_unused_resampling_fallbacks_deeper(tmp_path):
    """Pillowの各種リサイズフィルタが存在しないと仮定した場合のフォールバックを網羅"""
    import backend.add_premium_branding as apb
    from PIL import Image

    out_thumb = tmp_path / "res_fallback_deep.png"
    out_prev = tmp_path / "res_fallback_deep_prev.png"

    original_hasattr = hasattr
    def mock_hasattr(obj, name):
        if obj is Image and name == "Resampling":
            return False
        return original_hasattr(obj, name)

    # 属性アクセスでBICUBICやBILINEARなどが無い場合にフォールバックする挙動をエミュレートするため、
    # Image モジュールの一時的な書き換えをする
    original_bicubic = getattr(Image, "BICUBIC", None)
    original_bilinear = getattr(Image, "BILINEAR", None)
    if hasattr(Image, "BICUBIC"):
        delattr(Image, "BICUBIC")
    if hasattr(Image, "BILINEAR"):
        delattr(Image, "BILINEAR")

    try:
        with patch("builtins.hasattr", side_effect=mock_hasattr):
            apb.generate_premium_branding_thumbnail(
                out_thumb, width=1280, height=720, text="Deep Fallback", preview_path=out_prev
            )
            assert out_thumb.exists()
            assert out_prev.exists()
    finally:
        if original_bicubic is not None:
            setattr(Image, "BICUBIC", original_bicubic)
        if original_bilinear is not None:
            setattr(Image, "BILINEAR", original_bilinear)


def test_font_size_reduction_exhausted_robust(tmp_path):
    """テキストが大きすぎる、またはフォント取得失敗によりフォントサイズが極小以下になるケース"""
    import backend.add_premium_branding as apb
    from PIL import ImageFont

    out_thumb = tmp_path / "font_ex_thumb.png"
    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    # 1. font_paths のフォント読み込み時に OSError が発生し、load_default も OSError を投げるケース
    # これにより font = None になり、フォントサイズ削減ループを即座に break する。
    with patch("PIL.ImageFont.truetype", side_effect=OSError("font load failed")), \
         patch("PIL.ImageFont.load_default", side_effect=OSError("default font load failed")), \
         patch("PIL.ImageDraw.ImageDraw.text") as mock_text:
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test default fail")
        assert out_thumb.exists()
        mock_text.assert_called()

    # 2. ImageFont.truetype が ValueError を投げ、フォールバックの continue パスを通す
    real_font = ImageFont.load_default()
    def mock_truetype(fp, size):
        if "YuGothB" in str(fp):
            raise ValueError("mocked value error")
        return real_font

    with patch("PIL.ImageFont.truetype", side_effect=mock_truetype):
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test continue path")
        assert out_thumb.exists()

    # 3. textbbox が OSError / ValueError を投げる場合
    # これにより max_line_w = len(line) * font_size にフォールバックする
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=OSError("bbox error")):
        apb.generate_premium_branding_thumbnail(out_thumb, text="Test bbox error path")
        assert out_thumb.exists()


def test_io_unlinks_oserrors_robust(tmp_path):
    """ファイルの存在チェックと削除時の例外 (OSError) が適切に無視され、Windows環境でもFileExistsErrorを起こさない検証"""
    import backend.add_premium_branding as apb
    from PIL import Image
    from pathlib import Path

    out_thumb = tmp_path / "unlink_test.png"
    out_prev = tmp_path / "unlink_test_prev.png"

    original_base = apb.BASE_DIR
    apb.BASE_DIR = tmp_path

    original_unlink = Path.unlink
    
    # output_path や preview_path の存在確認と削除（unlink）は成功させ、一時ファイルの削除（unlink）だけ失敗させる
    # これにより、Windows環境で rename 移動先にファイルが残って FileExistsError になるのを防ぐ
    def mock_unlink(self_path):
        if ".tmp" in self_path.name:
            raise OSError("mocked temp unlink error")
        original_unlink(self_path)

    # 一時ファイルの削除時エラーによる警告を確認するため、stderr をキャプチャ
    import sys
    from io import StringIO
    stderr_buf = StringIO()
    original_stderr = sys.stderr
    sys.stderr = stderr_buf

    try:
        with patch.object(Path, "unlink", autospec=True, side_effect=mock_unlink):
            # Path.rename で意図的にエラーを起こさせて、一時ファイルのクリーンアップルートを通す
            with patch.object(Path, "rename", side_effect=OSError("save error for temp clean")):
                with pytest.raises(OSError, match="save error for temp clean"):
                    apb.generate_premium_branding_thumbnail(out_thumb, preview_path=out_prev)
            
            # 通常の unlink() エラー無視ルートを通す (Path.rename が動くようにモック)
            with patch.object(Path, "rename") as mock_rename:
                apb.generate_premium_branding_thumbnail(out_thumb, preview_path=out_prev)
                mock_rename.assert_called()

        log_content = stderr_buf.getvalue()
        assert "WARNING: Failed to cleanup temp file" in log_content

    finally:
        sys.stderr = original_stderr
        apb.BASE_DIR = original_base


# 追加の堅牢性検証テストケース
@pytest.mark.anyio
async def test_resolve_premium_branding_task_agent_resolution_invalid_format(tmp_path):
    """エージェントの resolution 属性が不正な形式の場合、デフォルト値にフォールバックされること"""
    import backend.add_premium_branding as apb
    import json
    
    # ダミーのエージェントオブジェクト
    class DummyAgent:
        def __init__(self):
            self.resolution = "invalid_resolution_format"
            self.output_dir = str(tmp_path)
            self.text = "Resolution Fallback Test"
            
    agent = DummyAgent()
    task_id = "test_res_fallback"
    
    # 実際には存在するフォントを読み込む
    real_font = load_japanese_font(20)
    
    with patch("PIL.ImageFont.truetype", return_value=real_font):
        result_json = await apb.resolve_premium_branding_task(task_id, agent=agent)
        result = json.loads(result_json)
        
        # デフォルトの1280x720で生成されること
        assert result["width"] == 1280
        assert result["height"] == 720
        assert Path(result["path"]).exists()


def test_generate_premium_thumbnail_logo_corrupted(tmp_path):
    """ロゴ画像が破損している場合（SyntaxError等を発生させる）、警告を出力しつつ処理を継続すること"""
    import backend.add_premium_branding as apb
    import io
    import sys
    
    out_thumbnail = tmp_path / "corrupted_logo_thumbnail.png"
    
    # 破損したロゴファイルを作成（空ファイルやテキストファイル）
    logo_dir = apb.BASE_DIR / "backend" / "branding" / "logos"
    logo_dir.mkdir(parents=True, exist_ok=True)
    corrupted_logo = logo_dir / "brand_logo.png"
    
    # 既存のロゴがあればバックアップ
    logo_backup = None
    if corrupted_logo.exists():
        logo_backup = corrupted_logo.read_bytes()
        
    try:
        corrupted_logo.write_text("this is not an image file")
        
        real_font = load_japanese_font(20)
        
        stderr_capture = io.StringIO()
        with patch("PIL.ImageFont.truetype", return_value=real_font),              patch("sys.stderr", stderr_capture):
            
            apb.generate_premium_branding_thumbnail(
                out_thumbnail,
                width=1280,
                height=720,
                text="Corrupted Logo Test"
            )
            
            # 標準エラー出力にWarningが記録されていること
            stderr_output = stderr_capture.getvalue()
            assert "Warning: Failed to load brand logo" in stderr_output
            
            # サムネイル自体は生成されていること
            assert out_thumbnail.exists()
            
    finally:
        # ロゴの復元
        if logo_backup is not None:
            corrupted_logo.write_bytes(logo_backup)
        else:
            try:
                corrupted_logo.unlink()
            except OSError:
                pass


def test_validate_thumbnail_invalid_type_dict():
    """validate_thumbnail に対し、引数として不正な型である dict を渡した場合に TypeError が発生すること"""
    import backend.add_premium_branding as apb
    with pytest.raises(TypeError, match="File path must be a string or Path object"):
        apb.validate_thumbnail({"path": "dummy_path.png"})


def test_generate_premium_thumbnail_null_path():
    """generate_premium_branding_thumbnail に対し、出力パスに None を渡した場合に ValueError が発生すること"""
    import backend.add_premium_branding as apb
    with pytest.raises(ValueError, match="Output path cannot be empty"):
        apb.generate_premium_branding_thumbnail(None)
