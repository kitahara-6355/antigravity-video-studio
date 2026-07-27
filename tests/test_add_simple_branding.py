# -*- coding: utf-8 -*-
# Phase 27: add_simple_branding.py のサムネイル品質向上と検証テスト
import sys
import os
import pytest
import json
import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.add_simple_branding import (
    generate_simple_branding_thumbnail,
    validate_thumbnail,
    resolve_branding_task
)
from backend.agents.stage_bound_agent import StageBoundAgent

def test_generate_and_validate_success(tmp_path):
    """正常系: 品質基準を満たした画像が生成され、検証が通ることを確認"""
    img_path = tmp_path / "valid_thumbnail.png"
    text = "Antigravity Premium Thumbnail"
    
    generate_simple_branding_thumbnail(img_path, width=1280, height=720, text=text)
    
    assert img_path.exists()
    
    result = validate_thumbnail(img_path)
    assert result["path"] == str(img_path)
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    
    # ピクセルデータのデコードチェック
    with Image.open(img_path) as img:
        img.load()
        assert img.size == (1280, 720)

def test_validation_file_not_found():
    """異常系: ファイルが存在しない場合に FileNotFoundError が発生することを確認"""
    with pytest.raises(FileNotFoundError):
        validate_thumbnail("non_existent_thumbnail_file.png")

def test_generate_resolution_insufficient(tmp_path):
    """異常系: 解像度が足りない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "low_res.png"
    # 1280x720 未満
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_simple_branding_thumbnail(img_path, width=640, height=360)

def test_generate_aspect_ratio_invalid(tmp_path):
    """異常系: アスペクト比が 16:9 ではない場合に ValueError が発生することを確認"""
    img_path = tmp_path / "bad_ratio.png"
    # 1280x960 (4:3)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_simple_branding_thumbnail(img_path, width=1280, height=960)

def test_validation_file_size_exceeded(tmp_path):
    """異常系: ファイルサイズが 4MB を超える場合に ValueError が発生することを確認"""
    img_path = tmp_path / "oversized.png"
    generate_simple_branding_thumbnail(img_path)
    
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(img_path)

def test_validation_corrupted_image(tmp_path):
    """異常系: 画像データが破損している場合に ValueError が発生することを確認"""
    img_path = tmp_path / "corrupted.png"
    with open(img_path, "wb") as f:
        f.write(b"invalid image header and pixel payload")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(img_path)

def test_stage_bound_agent_branding_integration(tmp_path):
    """StageBoundAgent / DB結果保存 / 非同期リトライフローとの連携検証"""
    db_file = tmp_path / "test_stage_bound_branding.db"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    agent.output_dir = tmp_path
    agent.width = 1920
    agent.height = 1080
    agent.text = "High Quality 1080p Branding"
    
    task_id = "agent_branding_task_001"
    
    async def run_test():
        # タスクを READY 状態で登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # 非同期で解決処理を開始
        async def process_func(tid):
            return await resolve_branding_task(agent, tid)
            
        await agent.start(process_func)
        
        # 完了または失敗まで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 生成された画像ファイルを確認
        output_file = tmp_path / f"{task_id}.png"
        assert output_file.exists()
        
        # 画像品質の検証
        result_info = validate_thumbnail(output_file)
        assert result_info["width"] == 1920
        assert result_info["height"] == 1080
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBに書き込まれた結果を確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1920
            assert db_result["height"] == 1080
            assert "path" in db_result
        finally:
            conn.close()

    asyncio.run(run_test())

def test_stage_bound_agent_retry_on_failure(tmp_path):
    """異常系: 画像生成で一時エラーが発生した場合に自動リトライフローが動作することを検証"""
    db_file = tmp_path / "test_stage_bound_retry.db"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    task_id = "agent_branding_retry_task"
    call_count = 0
    
    async def process_func(tid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("Simulated temporary storage failure")
        
        # 2回目は正常終了
        agent.output_dir = tmp_path
        agent.width = 1280
        agent.height = 720
        agent.text = "Retry Success"
        return await resolve_branding_task(agent, tid)

    async def run_test():
        # 最大リトライ回数を 2 に設定して登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        await agent.start(process_func)
        
        # 完了するまで少し待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        assert call_count == 2
        
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "COMPLETED"
            assert retry_count == 1
        finally:
            conn.close()

    asyncio.run(run_test())

def test_thumbnail_resolution_variations(tmp_path):
    """追加検証: 各種解像度の境界値テスト"""
    # 正常系: 1920x1080 (16:9)
    img_path = tmp_path / "1080p.png"
    generate_simple_branding_thumbnail(img_path, width=1920, height=1080)
    res = validate_thumbnail(img_path)
    assert res["width"] == 1920
    assert res["height"] == 1080

    # 異常系: 1280x720 未満 (1279x720)
    bad_path1 = tmp_path / "low_w.png"
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_simple_branding_thumbnail(bad_path1, width=1279, height=720)

    # 正常系: 4K (3840x2160)
    img_path_4k = tmp_path / "4k.jpg"
    generate_simple_branding_thumbnail(img_path_4k, width=3840, height=2160)
    res_4k = validate_thumbnail(img_path_4k)
    assert res_4k["width"] == 3840
    assert res_4k["height"] == 2160

    # 異常系: 8K超過 (7681x4320)
    bad_path2 = tmp_path / "too_large.png"
    with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
        generate_simple_branding_thumbnail(bad_path2, width=7681, height=4320)

def test_thumbnail_aspect_ratio_boundary(tmp_path):
    """検証: アスペクト比 16:9 の境界値検証"""
    img_path = tmp_path / "aspect_boundary.png"
    # ほぼ 16:9 (許容誤差 0.01 内)
    # 1281 / 720 = 1.77916...
    generate_simple_branding_thumbnail(img_path, width=1281, height=720)
    assert validate_thumbnail(img_path)["width"] == 1281

    # 許容誤差を超えるアスペクト比
    # 1290 / 720 = 1.7916...
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_simple_branding_thumbnail(img_path, width=1290, height=720)

def test_thumbnail_empty_and_none_text(tmp_path):
    """検証: テキストが空またはNoneの場合に正常に生成されること"""
    img_path1 = tmp_path / "empty_text.png"
    generate_simple_branding_thumbnail(img_path1, width=1280, height=720, text="")
    res1 = validate_thumbnail(img_path1)
    assert res1["width"] == 1280

    img_path2 = tmp_path / "none_text.png"
    generate_simple_branding_thumbnail(img_path2, width=1280, height=720, text=None)
    res2 = validate_thumbnail(img_path2)
    assert res2["width"] == 1280

def test_thumbnail_long_text_wrapping(tmp_path):
    """検証: 非常に長いテキストが指定された場合でも、はみ出さずに安全に描画されること"""
    img_path = tmp_path / "long_text.png"
    long_text = "これは非常に長いテキストのテストケースです。このテキストは複数行に折り返される必要があります。バナー内にはみ出さず、画像が破損することなく、最後までクラッシュせずに生成されることをテストします。" * 3
    generate_simple_branding_thumbnail(img_path, width=1280, height=720, text=long_text)
    res = validate_thumbnail(img_path)
    assert res["width"] == 1280
    assert img_path.exists()

def test_thumbnail_invalid_resolution_types(tmp_path):
    """検証: 解像度に無効な型や無効な値を指定した場合のエラーハンドリング"""
    img_path = tmp_path / "invalid_type.png"
    generate_simple_branding_thumbnail(img_path, width="1280", height="720")
    assert validate_thumbnail(img_path)["width"] == 1280

    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_simple_branding_thumbnail(img_path, width="not_an_int", height=720)

    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_simple_branding_thumbnail(img_path, width=-1280, height=720)

    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_simple_branding_thumbnail(img_path, width=1280, height=0)

def test_thumbnail_unsupported_format(tmp_path):
    """検証: サポートされていない画像フォーマットが指定された場合のエラーハンドリング"""
    img_path = tmp_path / "invalid_format.gif"
    with pytest.raises(ValueError, match="Unsupported file format"):
        generate_simple_branding_thumbnail(img_path, width=1280, height=720)

def test_thumbnail_invalid_output_path_directory(tmp_path):
    """検証: 出力パスにファイル名ではなくディレクトリを指定した場合のエラーハンドリング"""
    with pytest.raises(ValueError, match="Output path must be a file path, not a directory"):
        generate_simple_branding_thumbnail(tmp_path, width=1280, height=720)

def test_get_lanczos_filter_fallback():
    """_get_lanczos_filter のフォールバックロジックを検証"""
    from backend.add_simple_branding import _get_lanczos_filter
    
    # LANCZOS がある場合
    mock_img = MagicMock()
    mock_img.Resampling.LANCZOS = 99
    assert _get_lanczos_filter(mock_img) == 99
    
    # Resampling がなく LANCZOS がある場合
    mock_img = MagicMock()
    del mock_img.Resampling
    mock_img.LANCZOS = 88
    assert _get_lanczos_filter(mock_img) == 88

    # 両方なく ANTIALIAS がある場合
    mock_img = MagicMock()
    del mock_img.Resampling
    del mock_img.LANCZOS
    mock_img.ANTIALIAS = 77
    assert _get_lanczos_filter(mock_img) == 77

    # 全てないが BICUBIC がある場合
    mock_img = MagicMock()
    del mock_img.Resampling
    del mock_img.LANCZOS
    del mock_img.ANTIALIAS
    mock_img.BICUBIC = 66
    assert _get_lanczos_filter(mock_img) == 66

    # 何もない場合
    mock_img = MagicMock()
    del mock_img.Resampling
    del mock_img.LANCZOS
    del mock_img.ANTIALIAS
    del mock_img.BICUBIC
    assert _get_lanczos_filter(mock_img) is None

def test_load_and_resize_logo_fallback(tmp_path):
    """_load_and_resize_logo のフォールバックロジックを検証"""
    from backend.add_simple_branding import _load_and_resize_logo
    
    # 存在しないロゴパスの場合、プレースホルダーが作成される
    non_existent = tmp_path / "non_existent_logo.png"
    fallback_logo = _load_and_resize_logo(non_existent, 100, 50)
    assert fallback_logo.size == (100, 50)

    # LANCZOS が None の場合のリサイズ処理をテスト
    # 画像ファイルを作成
    logo_file = tmp_path / "test_logo.png"
    Image.new('RGBA', (200, 200), (0, 255, 0, 255)).save(logo_file)
    
    with patch("backend.add_simple_branding.LANCZOS", None):
        logo_loaded = _load_and_resize_logo(logo_file, 50, 50)
        assert logo_loaded.size == (50, 50)

    # LANCZOS が None ではない通常のリサイズ処理をテスト
    logo_loaded_normal = _load_and_resize_logo(logo_file, 40, 40)
    assert logo_loaded_normal.size == (40, 40)


def test_select_branding_font_fallback():
    """_select_branding_font のフォールバックロジックを検証"""
    from backend.add_simple_branding import _select_branding_font
    
    # 全てのフォントパスが存在しないと仮定した場合のフォールバック
    with patch("pathlib.Path.exists", return_value=False):
        font = _select_branding_font(12)
        assert font is not None

    # ImageFont.truetype が例外を投げるケースをテスト (フォントパスが存在するが壊れている場合)
    # load_default は内部で例外を投げないように side_effect 関数を使用する
    def mock_truetype_side_effect(*args, **kwargs):
        font_path = args[0] if len(args) > 0 else None
        if font_path is None or "default" in str(font_path) or hasattr(font_path, "read"):
            return MagicMock()
        raise OSError("Font corrupted")

    with patch("pathlib.Path.exists", return_value=True), \
         patch("PIL.ImageFont.truetype", side_effect=mock_truetype_side_effect):
        font = _select_branding_font(12)
        assert font is not None




def test_resolve_branding_paths(tmp_path):
    """_resolve_branding_paths のパス解決および mkdir 例外ハンドリングを検証"""
    from backend.add_simple_branding import _resolve_branding_paths
    
    # base_path が None の場合
    logo_path, output_path = _resolve_branding_paths(None)
    assert logo_path.name == "brand_logo.png"
    assert output_path.name == "final_branding.png"
    
    # base_path が指定された場合
    logo_path, output_path = _resolve_branding_paths(tmp_path)
    assert logo_path == tmp_path / "backend" / "branding" / "logos" / "brand_logo.png"
    assert output_path == tmp_path / "backend" / "branding" / "final_branding.png"
    
    # mkdir で TypeError が発生した場合のハンドリング
    with patch("pathlib.Path.mkdir", side_effect=TypeError):
        logo_path, output_path = _resolve_branding_paths(tmp_path)
        assert output_path.exists() is False  # mkdirは失敗するが関数は正常終了

def test_create_combined_branding_success(tmp_path):
    """正常系: create_combined_branding が結合画像を正常に生成することを検証"""
    from backend.add_simple_branding import create_combined_branding
    
    # tmp_path をベースパスとして渡す。ロゴ画像は存在しないので fallback になる。
    output_path = create_combined_branding(target_height=45, base_path=tmp_path)
    assert output_path.exists()
    
    # 出力された画像のアスペクト比が 331:45 スケールであることを確認
    with Image.open(output_path) as img:
        assert img.size == (331, 45)

def test_create_combined_branding_oserror(tmp_path):
    """異常系: 保存時に OSError が発生した場合に適切に例外がレイズされることを検証"""
    from backend.add_simple_branding import create_combined_branding
    
    with patch("PIL.Image.Image.save", side_effect=OSError("Disk full")):
        with pytest.raises(OSError, match="Disk full"):
            create_combined_branding(target_height=45, base_path=tmp_path)

def test_add_branding_to_video_no_input():
    """異常系: 入力動画が存在しない場合に None が返ることを検証"""
    from backend.add_simple_branding import add_branding_to_video
    
    with patch("pathlib.Path.exists", return_value=False):
        result = add_branding_to_video()
        assert result is None

def test_add_branding_to_video_success(tmp_path):
    """正常系: add_branding_to_video が正常に動作し、動画パスを返すことを検証"""
    from backend.add_simple_branding import add_branding_to_video
    
    # input_video.exists() -> True
    # create_combined_branding -> ダミーパス
    # subprocess.run -> 2回呼ばれる (1回目: ffmpeg, 2回目: ffprobe)
    # output_video.exists() -> True
    # output_video.stat().st_size -> ダミーサイズ
    
    mock_input_exists = MagicMock(return_value=True)
    
    # 複数ファイルに対する Path.exists の挙動をモック
    # input_video と output_video は別オブジェクトなので、引数で判定するか、
    # 順番で side_effect を使う。
    # 1回目 (input_video.exists()): True
    # 2回目 (output_video.exists()): True
    # 他の exists() 呼び出しがあるかもしれないので、引数による side_effect が安全。
    def exists_side_effect(self_path):
        if "soul_narrative_FINAL_EDITED.mp4" in str(self_path):
            return True
        if "soul_narrative_YOUTUBE_READY.mp4" in str(self_path):
            return True
        return False
        
    mock_run = MagicMock()
    # 1回目のrun (ffmpeg): CompletedProcess(returncode=0)
    # 2回目のrun (ffprobe): CompletedProcess(returncode=0, stdout="125.0")
    run_ffmpeg = MagicMock(returncode=0, stdout="", stderr="")
    run_ffprobe = MagicMock(returncode=0, stdout="125.0\n", stderr="")
    mock_run.side_effect = [run_ffmpeg, run_ffprobe]
    
    # create_combined_branding が呼ばれると、C:\Users\PC_User\Desktop\script\video-automation\backend\branding\final_branding.png を指す。
    # テスト環境の保護のため、実際のファイル保存を防ぎたいが、create_combined_branding もモックする。
    with patch("pathlib.Path.exists", exists_side_effect), \
         patch("pathlib.Path.stat") as mock_stat, \
         patch("pathlib.Path.mkdir", side_effect=TypeError) as mock_mkdir, \
         patch("backend.add_simple_branding.create_combined_branding", return_value=tmp_path / "final_branding.png"), \
         patch("subprocess.run", mock_run):
         
        mock_stat.return_value.st_size = 1024 * 1024 * 10  # 10MB
        
        result = add_branding_to_video()
        assert result is not None
        assert "soul_narrative_YOUTUBE_READY.mp4" in result


def test_add_branding_to_video_failure():
    """異常系: ffmpeg 実行が失敗した場合に None が返ることを検証"""
    from backend.add_simple_branding import add_branding_to_video
    
    def exists_side_effect(self_path):
        if "soul_narrative_FINAL_EDITED.mp4" in str(self_path):
            return True
        return False
        
    mock_run = MagicMock()
    # ffmpeg がエラー (returncode != 0)
    run_ffmpeg = MagicMock(returncode=1, stdout="", stderr="ffmpeg error")
    mock_run.side_effect = [run_ffmpeg]
    
    with patch("pathlib.Path.exists", exists_side_effect), \
         patch("pathlib.Path.mkdir"), \
         patch("backend.add_simple_branding.create_combined_branding", return_value=Path("dummy_branding.png")), \
         patch("subprocess.run", mock_run):
         
        result = add_branding_to_video()
        assert result is None

def test_validate_thumbnail_corrupted_load(tmp_path):
    """異常系: 画像のロード (load()) に失敗した場合に ValueError が発生することを検証"""
    img_path = tmp_path / "corrupted_load.png"
    # 空の画像を作成
    Image.new("RGB", (1280, 720)).save(img_path)
    
    # img.load() で例外を発生させるモック
    mock_image_obj = MagicMock()
    mock_image_obj.verify = MagicMock()
    mock_image_obj.load.side_effect = OSError("Load failed")
    mock_image_obj.size = (1280, 720)
    
    with patch("PIL.Image.open", return_value=mock_image_obj):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(img_path)

def test_validate_thumbnail_preview_resolution_insufficient(tmp_path):
    """異常系: プレビュー検証時に解像度が 320x180 未満の場合に ValueError が発生することを検証"""
    img_path = tmp_path / "preview_low_res.png"
    Image.new("RGB", (300, 160)).save(img_path)
    
    with pytest.raises(ValueError, match="Preview resolution must be at least 320x180"):
        validate_thumbnail(img_path, is_preview=True)

def test_save_thumbnail_unsupported_or_fallback(tmp_path):
    """追加検証: LANCZOS is None の場合のリサイズ分岐と webp 保存の検証"""
    from backend.add_simple_branding import _save_thumbnail_to_path
    
    img = Image.new("RGBA", (2000, 1125))
    output_path = tmp_path / "test_fallback.webp"
    temp_path = tmp_path / "temp_fallback.webp"
    
    # 実際の画像オブジェクトを作成して、convert されたときにそれを返すようにする。
    real_rgb_img = Image.new("RGB", (1280, 720))
    mock_resized_img = MagicMock()
    mock_resized_img.convert.return_value = real_rgb_img
    
    with patch("backend.add_simple_branding.LANCZOS", None), \
         patch("PIL.Image.Image.resize", return_value=mock_resized_img) as mock_resize:
         
        # LANCZOS が None で Image.Resampling も AttributeError になる場合
        # _save_thumbnail_to_path は Image.Resampling.BILINEAR を呼ぼうとするが、
        # モックで Image.Resampling 自体を AttributeError にして、fallback (2) を呼ばせる
        with patch("PIL.Image.Resampling", spec=[]):  # hasattr(Image, "Resampling") -> False
            _save_thumbnail_to_path(img, 1280, 720, temp_path, output_path, ".webp")
            
            mock_resize.assert_called_with((1280, 720), 2)
            
    assert output_path.exists()


def test_resolve_branding_task_direct(tmp_path):
    """正常系: resolve_branding_task を直接呼び出し、text is None の場合のフォールバックを検証"""
    mock_agent = MagicMock()
    mock_agent.width = 1280
    mock_agent.height = 720
    mock_agent.text = None
    mock_agent.output_dir = tmp_path
    
    async def run_test():
        res_json = await resolve_branding_task(mock_agent, "direct_task")
        res = json.loads(res_json)
        assert res["width"] == 1280
        assert res["height"] == 720
        # プレビューも生成されていることを確認
        assert "preview" in res
        
    asyncio.run(run_test())

def test_validate_thumbnail_invalid_bounds(tmp_path):
    """異常系: validate_thumbnail の解像度不足、アスペクト比エラーの分岐を検証"""
    # 正常サイズだがプレビューではないサムネイルが 1280x720 未満 (例: 1000x562)
    img_path = tmp_path / "low_res_thumbnail.png"
    Image.new("RGB", (1000, 562)).save(img_path)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(img_path, is_preview=False)
        
    # アスペクト比が 16:9 ではない (例: 1280x800)
    img_path_ratio = tmp_path / "bad_ratio_thumbnail.png"
    Image.new("RGB", (1280, 800)).save(img_path_ratio)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(img_path_ratio, is_preview=False)

def test_mkdir_exception_handling(tmp_path):
    """異常系: 各種 mkdir での TypeError/OSError 例外ハンドリングを検証"""
    from backend.add_simple_branding import _validate_thumbnail_params, generate_simple_branding_thumbnail
    
    # _validate_thumbnail_params 内の mkdir 例外
    with patch("pathlib.Path.mkdir", side_effect=OSError("Perm denied")):
        # 例外が握り潰されて正常終了することを確認
        w, h, p, suff = _validate_thumbnail_params(tmp_path / "test.png", 1280, 720)
        assert w == 1280
        
    # generate_simple_branding_thumbnail 内の preview_path 親フォルダ mkdir 例外
    with patch("pathlib.Path.mkdir", side_effect=TypeError("Bad args")):
        # 例外が握り潰されて正常にサムネイルとプレビューが生成されることを確認
        generate_simple_branding_thumbnail(tmp_path / "thumb.png", preview_path=tmp_path / "prev.png")
        assert (tmp_path / "thumb.png").exists()
        assert (tmp_path / "prev.png").exists()

def test_unlink_exception_handling(tmp_path):
    """異常系: ファイル上書き時の unlink 例外ハンドリングを検証"""
    from backend.add_simple_branding import _save_thumbnail_to_path
    
    # すでにファイルが存在する状態を作る
    out_file = tmp_path / "existing.png"
    out_file.touch()
    
    img = Image.new("RGBA", (1280, 720))
    temp_file = tmp_path / "temp.png"
    
    # unlink が OSError を投げるようにモックし、かつ Windows での FileExistsError を防ぐために rename もモックする
    with patch("pathlib.Path.unlink", side_effect=OSError("File locked")), \
         patch("pathlib.Path.rename") as mock_rename:
        # 例外が握り潰されて rename が走り、正常に保存されることを確認
        _save_thumbnail_to_path(img, 1280, 720, temp_file, out_file, ".png")
        mock_rename.assert_called_once()


def test_generate_thumbnail_error_cleanup(tmp_path):
    """異常系: サムネイル生成中の例外発生時に一時ファイルが削除されること、またその unlink 自体が失敗してもクラッシュしないことを検証"""
    def exists_side_effect(self_path):
        if ".tmp" in str(self_path):
            return True
        return False

    with patch("backend.add_simple_branding._generate_gradient_background", side_effect=ValueError("Simulated error")), \
         patch("pathlib.Path.exists", exists_side_effect), \
         patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")) as mock_unlink:
         
        with pytest.raises(ValueError, match="Simulated error"):
            generate_simple_branding_thumbnail(tmp_path / "error_thumb.png")
            
        # unlink が呼ばれていることを確認
        assert mock_unlink.called


def test_textbbox_exception_handling(tmp_path):
    """異常系: textbbox で例外が発生した場合のフォールバックを検証"""
    from backend.add_simple_branding import generate_simple_branding_thumbnail
    
    with patch("PIL.ImageDraw.ImageDraw.textbbox", side_effect=OSError("Bbox failed")):
        # textbbox が失敗しても例外が握り潰され、デフォルトフォントや文字数ベースで正常に描画が行われることを確認
        out_file = tmp_path / "textbbox_err.png"
        generate_simple_branding_thumbnail(out_file, text="Hello World")
        assert out_file.exists()

def test_load_and_resize_logo_draw_text_exception(tmp_path):
    """異常系: プレースホルダー作成時に draw.text が失敗した場合の例外ハンドリングを検証"""
    from backend.add_simple_branding import _load_and_resize_logo
    
    non_existent = tmp_path / "non_existent_logo.png"
    # ImageDraw.Draw.text を例外発生モック
    with patch("PIL.ImageDraw.ImageDraw.text", side_effect=ValueError("Draw text failed")):
        # 例外が握り潰されて正常にプレースホルダーが返ることを確認
        logo = _load_and_resize_logo(non_existent, 100, 50)
        assert logo.size == (100, 50)

def test_generate_preview_unlink_exception(tmp_path):
    """異常系: プレビュー生成時の既存ファイル削除（unlink）での例外ハンドリングを検証"""
    from backend.add_simple_branding import generate_simple_branding_thumbnail
    
    # プレビューファイルをあらかじめ作成しておく
    prev_file = tmp_path / "prev_existing.png"
    prev_file.touch()
    
    # unlink を OSError を投げるようにモックし、rename もモックして WinError を防ぐ
    with patch("pathlib.Path.unlink", side_effect=OSError("Lock error")), \
         patch("pathlib.Path.rename") as mock_rename:
         
        generate_simple_branding_thumbnail(tmp_path / "thumb.png", preview_path=prev_file)
        # rename が呼ばれている＝処理が継続していることを確認
        assert mock_rename.called






