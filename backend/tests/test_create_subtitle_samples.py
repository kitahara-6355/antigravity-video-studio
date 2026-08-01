# 出力先は実装と同じ経路で解決する。直書きすると、実装を writable_path へ
# 寄せた後もテストだけがリポジトリ内を見に行き、本番ディレクトリを掴む。
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _wp
except ImportError:
    from path_resolver import writable_path as _wp

import os
import pytest
from pathlib import Path
from PIL import Image
from unittest import mock
from backend.create_subtitle_samples import create_subtitle_sample, create_integrated_sample

def test_create_subtitle_sample(tmp_path):
    # 出力ファイルパスを設定
    output_file = tmp_path / "subtitle_test.png"
    
    # 実行
    res_path = create_subtitle_sample(output_file)
    
    # 検証
    assert res_path == str(output_file)
    assert os.path.exists(res_path)
    
    # 画像を開いて検証
    with Image.open(res_path) as img:
        assert img.size == (1920, 1080)
        assert img.mode == "RGB"

def test_create_integrated_sample(tmp_path):
    # 出力ファイルパスを設定
    output_file = tmp_path / "integrated_test.png"
    
    # 実行
    res_path = create_integrated_sample(output_file)
    
    # 検証
    assert res_path == str(output_file)
    assert os.path.exists(res_path)
    
    # 画像を開いて検証
    with Image.open(res_path) as img:
        assert img.size == (1920, 1080)
        assert img.mode == "RGB"

def test_default_paths():
    # 実行環境に合わせて backend のベースパスを動的に決定
    base_dir = Path(__file__).parent.parent
    if not (base_dir / "create_subtitle_samples.py").exists():
        base_dir = Path("backend").resolve()
        
    sample_path = base_dir / "subtitle_sample.png"
    integrated_path = base_dir / "B_plan_with_subtitle.png"
    
    try:
        res1 = create_subtitle_sample()
        assert os.path.exists(res1)
        assert res1 == str(sample_path)
    finally:
        if sample_path.exists():
            sample_path.unlink()
            
    try:
        res2 = create_integrated_sample()
        assert os.path.exists(res2)
        assert res2 == str(integrated_path)
    finally:
        if integrated_path.exists():
            integrated_path.unlink()

def test_font_loading_success_mock(tmp_path):
    # ImageFont.truetype が成功するケースをシミュレート
    from PIL import ImageFont
    real_default_font = ImageFont.load_default()
    
    with mock.patch("PIL.ImageFont.truetype", return_value=real_default_font):
        output_file1 = tmp_path / "success_subtitle.png"
        output_file2 = tmp_path / "success_integrated.png"
        
        result1 = create_subtitle_sample(output_path=str(output_file1))
        assert result1 == str(output_file1)
        assert output_file1.exists()
        
        result2 = create_integrated_sample(output_path=str(output_file2))
        assert result2 == str(output_file2)
        assert output_file2.exists()

def test_font_loading_exception_fallback(tmp_path):
    # ImageFont.truetype が例外を投げたときのフォールバック検証
    from PIL import ImageFont
    output_file1 = tmp_path / "fallback_subtitle.png"
    output_file2 = tmp_path / "fallback_integrated.png"
    
    real_default_font = ImageFont.load_default()
    
    with mock.patch("PIL.ImageFont.truetype", side_effect=OSError("Font error")):
        with mock.patch("PIL.ImageFont.load_default", return_value=real_default_font):
            result1 = create_subtitle_sample(output_path=str(output_file1))
            assert result1 == str(output_file1)
            assert output_file1.exists()
            
            result2 = create_integrated_sample(output_path=str(output_file2))
            assert result2 == str(output_file2)
            assert output_file2.exists()

def test_main_block():
    # スクリプトのメインブロックの動作確認
    base_dir = Path(__file__).parent.parent
    if not (base_dir / "create_subtitle_samples.py").exists():
        base_dir = Path("backend").resolve()
        
    path1 = base_dir / "subtitle_sample.png"
    path2 = base_dir / "B_plan_with_subtitle.png"
    
    for path in [path1, path2]:
        if path.exists():
            path.unlink()
            
    script_path = (base_dir / "create_subtitle_samples.py").resolve()
    with open(script_path, "r", encoding="utf-8") as f:
        code_str = f.read()
        
    code_obj = compile(code_str, str(script_path), "exec")
    
    global_dict = {
        "__name__": "__main__",
        "__file__": str(script_path),
    }
    
    try:
        with mock.patch("builtins.print") as mock_print:
            exec(code_obj, global_dict)
            mock_print.assert_called()
    finally:
        for path in [path1, path2]:
            if path.exists():
                path.unlink()


def test_subtitle_thumbnail_verifier_success(tmp_path):
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier, create_subtitle_sample
    img_path = tmp_path / "valid.png"
    create_subtitle_sample(img_path)
    
    result = SubtitleThumbnailVerifier.validate(img_path)
    assert result["path"] == str(img_path)
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["size_bytes"] > 0

def test_subtitle_thumbnail_verifier_file_not_found():
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier
    with pytest.raises(FileNotFoundError):
        SubtitleThumbnailVerifier.validate("non_existent_file.png")

def test_subtitle_thumbnail_verifier_resolution_too_low(tmp_path):
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier
    img_path = tmp_path / "low_res.png"
    # 100x100 の小さい画像を作成
    img = Image.new("RGB", (100, 100))
    img.save(img_path)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        SubtitleThumbnailVerifier.validate(img_path)

def test_subtitle_thumbnail_verifier_invalid_aspect_ratio(tmp_path):
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier
    img_path = tmp_path / "bad_aspect.png"
    # 1280x1280 の画像 (1:1)
    img = Image.new("RGB", (1280, 1280))
    img.save(img_path)
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        SubtitleThumbnailVerifier.validate(img_path)

def test_subtitle_thumbnail_verifier_file_too_large(tmp_path):
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier, create_subtitle_sample
    img_path = tmp_path / "large.png"
    create_subtitle_sample(img_path)
    
    # ファイルサイズ取得をモックして4MB以上にする
    with mock.patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            SubtitleThumbnailVerifier.validate(img_path)

def test_subtitle_thumbnail_verifier_corrupted_image(tmp_path):
    from backend.create_subtitle_samples import SubtitleThumbnailVerifier
    img_path = tmp_path / "corrupted.png"
    # 壊れた画像（空のファイル）を作成
    with open(img_path, "w") as f:
        f.write("not an image")
        
    with pytest.raises(ValueError, match="Image verify failed|Image load failed"):
        SubtitleThumbnailVerifier.validate(img_path)

@pytest.mark.anyio
async def test_resolve_subtitle_thumbnail_task_success(tmp_path):
    from backend.create_subtitle_samples import resolve_subtitle_thumbnail_task
    import json
    
    class DummyAgent:
        def __init__(self, out_dir):
            self.output_dir = out_dir
            
    agent = DummyAgent(str(tmp_path))
    task_id = "task_success_001"
    
    result_str = await resolve_subtitle_thumbnail_task(agent, task_id)
    result = json.loads(result_str)
    
    assert result["width"] == 1920
    assert result["height"] == 1080
    assert (tmp_path / f"{task_id}.png").exists()

@pytest.mark.anyio
async def test_resolve_subtitle_thumbnail_task_failure():
    import uuid
    from backend.create_subtitle_samples import resolve_subtitle_thumbnail_task
    
    class DummyAgent:
        def __init__(self, out_dir):
            self.output_dir = out_dir
            
    # 書き込み不可能なパスを指定して失敗させる
    invalid_path = f"/non_existent_directory_{uuid.uuid4().hex}/writing"
    agent = DummyAgent(invalid_path)
    
    with pytest.raises(Exception):
        await resolve_subtitle_thumbnail_task(agent, "task_fail_001")


def test_generate_and_print_samples():
    from backend.create_subtitle_samples import generate_and_print_samples
    
    # 実行環境に合わせて backend のベースパスを動的に決定
    base_dir = Path(__file__).parent.parent
    if not (base_dir / "create_subtitle_samples.py").exists():
        base_dir = Path("backend").resolve()
        
    sample_path = base_dir / "subtitle_sample.png"
    integrated_path = base_dir / "B_plan_with_subtitle.png"
    
    # 既存のファイルを退避/削除
    for path in [sample_path, integrated_path]:
        if path.exists():
            path.unlink()
            
    try:
        with mock.patch("builtins.print") as mock_print:
            generate_and_print_samples()
            mock_print.assert_called()
        assert sample_path.exists()
        assert integrated_path.exists()
    finally:
        for path in [sample_path, integrated_path]:
            if path.exists():
                path.unlink()


@pytest.mark.anyio
async def test_resolve_subtitle_thumbnail_task_default_dir():
    from backend.create_subtitle_samples import resolve_subtitle_thumbnail_task
    import json
    
    class DummyAgentWithoutOutputDir:
        pass
        
    agent = DummyAgentWithoutOutputDir()
    task_id = "task_default_dir_001"
    
    default_dir = _wp("backend/temp_thumbnails")
    default_dir.mkdir(parents=True, exist_ok=True)
    expected_file = default_dir / f"{task_id}.png"
    
    if expected_file.exists():
        expected_file.unlink()
        
    try:
        result_str = await resolve_subtitle_thumbnail_task(agent, task_id)
        result = json.loads(result_str)
        
        assert result["width"] == 1920
        assert result["height"] == 1080
        assert expected_file.exists()
    finally:
        if expected_file.exists():
            expected_file.unlink()
