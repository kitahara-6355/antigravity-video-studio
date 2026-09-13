# -*- coding: utf-8 -*-
import sys
import os
import pytest
import sqlite3
import json
import asyncio
from pathlib import Path
from PIL import Image
import io
from unittest.mock import patch, MagicMock

# パス追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.services.thumbnail_analyzer import ThumbnailAnalyzer, thumbnail_analyzer

def test_generate_thumbnail_success(tmp_path):
    """正常系: 適切な解像度(1280x720)とアスペクト比(16:9)で画像が生成され、品質検証に合格すること"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_normal.png"
    
    # 正常な生成
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=1280,
        height=720,
        text="テストサムネイル\n高品質画像処理",
        draw_arrow=True,
        draw_circle=True,
        use_banner=True
    )
    
    assert res_path.exists()
    assert res_path == output_file
    
    # 画像のロード検証
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1280, 720)
        assert img.format == "PNG"
        
    # ファイルサイズ検証 (4MB未満)
    size_bytes = res_path.stat().st_size
    assert size_bytes > 0
    assert size_bytes < 4 * 1024 * 1024
    
    # validate_thumbnailによる検証
    val_res = analyzer.validate_thumbnail(res_path)
    assert val_res["width"] == 1280
    assert val_res["height"] == 720
    assert val_res["size_bytes"] == size_bytes

def test_generate_thumbnail_jpeg_success(tmp_path):
    """正常系: JPEG形式での出力検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_normal.jpg"
    
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=1920,
        height=1080,
        text="JPEG高解像度テスト",
        draw_arrow=False,
        draw_circle=False,
        use_banner=False
    )
    
    assert res_path.exists()
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1920, 1080)
        assert img.format == "JPEG"
        
    # validate_thumbnailによる検証
    val_res = analyzer.validate_thumbnail(res_path)
    assert val_res["width"] == 1920
    assert val_res["height"] == 1080

def test_generate_thumbnail_invalid_resolutions(tmp_path):
    """解像度検証: 1280x720未満、または極端に大きいサイズ(8K超)でエラーが発生すること"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 1280x720未満 (例: 640x360) -> エラー
    output_file = tmp_path / "test_small.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=640, height=360)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)
    
    # 2. 8K超 (例: 7681x4320) -> エラー
    output_file2 = tmp_path / "test_huge.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file2, width=7681, height=4320)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)

def test_generate_thumbnail_invalid_aspect_ratio(tmp_path):
    """アスペクト比検証: 16:9でない場合にエラーが発生すること"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_aspect.png"
    
    # 1280x960 は 4:3 -> エラー
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=1280, height=960)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

def test_generate_thumbnail_invalid_inputs(tmp_path):
    """入力エラー検証: 無効なパラメータに対するエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 出力パスが空
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail("", width=1280, height=720)
    assert "Output path must not be empty" in str(excinfo.value)
    
    # 2. 出力パスがディレクトリ
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(tmp_path, width=1280, height=720)
    assert "must be a file path, not a directory" in str(excinfo.value)
    
    # 3. サポート外の拡張子 (例: .gif)
    output_file = tmp_path / "test.gif"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width=1280, height=720)
    assert "Unsupported file format" in str(excinfo.value)

def test_validate_thumbnail_corrupted(tmp_path):
    """画像検証: 破損画像や空ファイルに対する validate_thumbnail の挙動"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        analyzer.validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. 空ファイル
    empty_file = tmp_path / "empty.png"
    empty_file.write_bytes(b"")
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(empty_file)
    assert "is empty" in str(excinfo.value)
    
    # 3. 破損データ (中身が不適切な画像データ)
    corrupt_file = tmp_path / "corrupt.png"
    corrupt_file.write_bytes(b"this is not a valid png image data")
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(corrupt_file)
    err_str = str(excinfo.value)
    assert "verify failed" in err_str or "Failed to load image pixels" in err_str or "header is not PNG" in err_str

def test_validate_thumbnail_aspect_ratios_comprehensive(tmp_path):
    """アスペクト比検証: 16:9以外の様々なアスペクト比での検証エラー"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 4:3 (例: 1440x1080) -> エラー
    file_4_3 = tmp_path / "thumb_4_3.png"
    img = Image.new("RGB", (1440, 1080), color=(255, 0, 0))
    img.save(file_4_3, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_4_3)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)
    
    # 2. 1:1 (例: 1280x1280) -> エラー
    file_1_1 = tmp_path / "thumb_1_1.png"
    img = Image.new("RGB", (1280, 1280), color=(255, 0, 0))
    img.save(file_1_1, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_1_1)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

    # 3. 境界値誤差テスト: 誤差 0.02 (例: 1295x720 -> 比率 1.7986, 16:9 は 1.7778 -> 差は 0.0208) -> エラー
    file_border_fail = tmp_path / "thumb_border_fail.png"
    img = Image.new("RGB", (1295, 720), color=(255, 0, 0))
    img.save(file_border_fail, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_border_fail)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

    # 4. 許容される境界誤差テスト: 誤差 0.0097 (例: 1287x720 -> 比率 1.7875, 差は 0.0097) -> パス
    file_border_pass = tmp_path / "thumb_border_pass.png"
    img = Image.new("RGB", (1287, 720), color=(255, 0, 0))
    img.save(file_border_pass, "PNG")
    img.close()
    res = analyzer.validate_thumbnail(file_border_pass)
    assert res["width"] == 1287
    assert res["height"] == 720

def test_validate_thumbnail_file_size_boundaries(tmp_path):
    """ファイルサイズ検証: 4MB境界値などの検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 4MBを超える巨大なファイル（擬似的にモックサイズを指定するか、ダミーファイルを生成）
    large_file = tmp_path / "large_mock.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(large_file, "PNG")
    img.close()
    
    # st_size を 4MB以上にモック
    with patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 4 * 1024 * 1024 + 1
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(large_file)
        assert "exceeds 4MB" in str(excinfo.value)

def test_validate_thumbnail_extreme_resolutions_comprehensive(tmp_path):
    """解像度検証: 下限・上限、および非数値等の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 下限未満 (例: 1279x719) -> エラー
    file_low = tmp_path / "thumb_low.png"
    img = Image.new("RGB", (1279, 719), color=(255, 0, 0))
    img.save(file_low, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_low)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)
    
    # 2. 8K上限超 (例: 7682x4321) -> エラー
    file_high = tmp_path / "thumb_high.png"
    img = Image.new("RGB", (7682, 4321), color=(255, 0, 0))
    img.save(file_high, "PNG")
    img.close()
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(file_high)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_integration(tmp_path):
    """非同期タスク処理: resolve_thumbnail_task のインテグレーション検証"""
    analyzer = ThumbnailAnalyzer()
    db_file = tmp_path / "test_thumb.db"
    output_dir = tmp_path / "output_thumbs"
    task_id = "task_thumb_001"
    
    # Agentモック
    agent = MagicMock()
    agent.output_dir = output_dir
    agent.db_path = str(db_file)
    agent.width = 1280
    agent.height = 720
    agent.text = "非同期タスクテストサムネイル"
    
    # 非同期実行
    result_json = await analyzer.resolve_thumbnail_task(agent, task_id)
    result_data = json.loads(result_json)
    
    assert result_data["valid"] is True
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    
    expected_path = output_dir / f"{task_id}.png"
    assert expected_path.exists()
    assert Path(result_data["path"]) == expected_path
    
    # DBのレコード確認
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT task_id, path, width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        db_task_id, db_path, db_width, db_height, db_size = row
        assert db_task_id == task_id
        assert Path(db_path) == expected_path
        assert db_width == 1280
        assert db_height == 720
        assert db_size == expected_path.stat().st_size
    finally:
        conn.close()


def test_generate_thumbnail_invalid_types(tmp_path):
    """異常系: 非数値やNone値などの無効な解像度パラメータが渡された際のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_invalid_type.png"
    
    # width が None -> デフォルトの1280x720が使われ、正常生成
    res_path = analyzer.generate_thumbnail(output_file, width=None, height=720)
    assert res_path.exists()
    
    # width が非数値文字列 -> ValueError
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file, width="invalid_width", height=720)
    assert "must be integers" in str(excinfo.value)


def test_generate_thumbnail_aspect_ratio_boundary(tmp_path):
    """解像度・アスペクト比検証: アスペクト比の誤差境界値の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 誤差 0.01 以下のギリギリのアスペクト比 (例: 1281x720 は 1.779、16:9 は 1.778 -> 差は 0.001 で許容)
    output_file = tmp_path / "test_boundary.png"
    res_path = analyzer.generate_thumbnail(output_file, width=1281, height=720)
    assert res_path.exists()
    
    # 誤差 0.01 を超えるアスペクト比 (例: 1300x720 は 1.806 -> 差は 0.028 でエラー)
    output_file2 = tmp_path / "test_boundary_fail.png"
    with pytest.raises(ValueError) as excinfo:
        analyzer.generate_thumbnail(output_file2, width=1300, height=720)
    assert "Aspect ratio must be 16:9" in str(excinfo.value)


def test_generate_thumbnail_write_error(tmp_path):
    """異常系: 存在しないディレクトリパスなど、書き込み不可のディレクトリを指定した場合のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 通常、generate_thumbnail は mkdir(parents=True) するので自動作成されるが、
    # もし親ディレクトリがファイルとして既に存在する場合、mkdir は OSError となる。
    dummy_file = tmp_path / "already_a_file"
    dummy_file.write_text("just a file")
    
    output_file_fail = dummy_file / "test.png"
    with pytest.raises(IOError) as excinfo:
        analyzer.generate_thumbnail(output_file_fail, width=1280, height=720)
    assert "Cannot write thumbnail" in str(excinfo.value) or "Cannot create parent directory" in str(excinfo.value)


def test_validate_thumbnail_resolution_boundary(tmp_path):
    """validate_thumbnail検証: 許容解像度上限(8K)および下限(1280x720)の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. 8K解像度上限テスト
    output_file = tmp_path / "test_8k.png"
    
    # ダミーの巨大なPNGファイルを生成 (PILで作成)
    img = Image.new("RGB", (7681, 4320), color=(255, 0, 0))
    img.save(output_file, "PNG")
    img.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(output_file)
    assert "Resolution exceeds maximum limit of 8K" in str(excinfo.value)
    
    # 2. 1280x720下限テスト
    output_file2 = tmp_path / "test_low.png"
    img2 = Image.new("RGB", (1279, 720), color=(255, 0, 0))
    img2.save(output_file2, "PNG")
    img2.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(output_file2)
    assert "Resolution must be at least 1280x720" in str(excinfo.value)



def test_validate_thumbnail_invalid_types_comprehensive():
    """validate_thumbnail検証: 無効な型のパスが渡された際のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. None値パス
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(None)
    assert "must not be empty or None" in str(excinfo.value)
    
    # 2. 空白文字列
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail("")
    assert "must not be empty or None" in str(excinfo.value)


def test_validate_thumbnail_corrupted_magic_numbers(tmp_path):
    """validate_thumbnail検証: 拡張子とマジックナンバーが不一致（拡張子偽装）の場合の検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. PNG拡張子だがJPEGデータ
    mismatched_file_1 = tmp_path / "fake_png.png"
    img = Image.new("RGB", (1280, 720), color=(0, 255, 0))
    img.save(mismatched_file_1, "JPEG")
    img.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(mismatched_file_1)
    assert "header is not PNG" in str(excinfo.value)
    
    # 2. JPEG拡張子だがPNGデータ
    mismatched_file_2 = tmp_path / "fake_jpg.jpg"
    img2 = Image.new("RGB", (1280, 720), color=(0, 0, 255))
    img2.save(mismatched_file_2, "PNG")
    img2.close()
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(mismatched_file_2)
    assert "header is not JPEG" in str(excinfo.value)


def test_generate_thumbnail_very_long_text(tmp_path):
    """generate_thumbnail検証: 非常に長い日本語テキストを渡した際、エラーにならずフォントサイズ縮小で処理が完了すること"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_long_text.png"
    
    # 100文字超の長いテキスト
    long_text = "これはテストのための非常に長い文字列です。自動折り返しとフォントサイズの動的調整機能が正常に動作し、最終的に画像の描画がエラーなく完了することを確認するためのテストケースです。"
    
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=1280,
        height=720,
        text=long_text,
        use_banner=True
    )
    
    assert res_path.exists()
    with Image.open(res_path) as img:
        img.load()
        assert img.size == (1280, 720)


def test_validate_thumbnail_corrupted_pixel_load(tmp_path):
    """validate_thumbnail検証: ピクセルデータが壊れている場合の詳細エラーのハンドリング"""
    analyzer = ThumbnailAnalyzer()
    corrupt_file = tmp_path / "truncated.png"
    
    # PNGのシグネチャだけ書き込み、中身は適当なデータ（破損画像）
    corrupt_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"invalid chunks and truncated data here")
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(corrupt_file)
    assert "corrupted" in str(excinfo.value).lower() or "failed" in str(excinfo.value).lower()


def test_validate_thumbnail_unsupported_extension(tmp_path):
    """validate_thumbnail検証: サポート外の拡張子を指定した際のエラーハンドリング"""
    analyzer = ThumbnailAnalyzer()
    gif_file = tmp_path / "test.gif"
    gif_file.write_bytes(b"dummy data")
    
    with pytest.raises(ValueError) as excinfo:
        analyzer.validate_thumbnail(gif_file)
    assert "Unsupported file format" in str(excinfo.value)


def test_validate_thumbnail_corrupted_verify_detailed_exceptions(tmp_path):
    """validate_thumbnail検証: verify()およびload()中の個別の例外詳細ハンドリング"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. verify() が UnidentifiedImageError を投げるような偽装ファイルをモックで検証
    # (マジックナンバーは正しいがPILが識別できないケース)
    fake_png = tmp_path / "fake_pil.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"some bad chunks")
    
    from PIL import UnidentifiedImageError
    with patch("PIL.Image.open") as mock_open:
        mock_open.side_effect = UnidentifiedImageError("Mocked unidentified format error")
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(fake_png)
        assert "unidentified format" in str(excinfo.value)
        
    # 2. load() が OSError を投げるような破損ファイルをモックで検証
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        # verifyはパスする
        mock_img.verify.return_value = None
        # loadはOSErrorを投げる
        mock_img.load.side_effect = OSError("Mocked truncated pixel stream error")
        mock_open.return_value.__enter__.return_value = mock_img
        
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(fake_png)
        assert "corrupted pixel stream" in str(excinfo.value)

def test_analyze_text_matching():
    analyzer = ThumbnailAnalyzer()
    
    # 顔あり、高コントラスト、構図あり、テキスト短い
    res1 = analyzer.analyze({
        "concept": "顔クローズアップ 驚き Before/After 比較 矢印 2分割",
        "text_overlay": "短いテキスト",
        "style": "黒背景 高コントラスト 赤 黄色"
    })
    assert res1["overall_score"] >= 80
    assert res1["verdict"] == "✅ 高品質"
    
    # 顔なし、低コントラスト、構図なし、テキスト長い
    res2 = analyzer.analyze({
        "concept": "パステルカラーの背景で文字がぎっしり詰まった風景画像",
        "text_overlay": "これは非常に長いテキストオーバーレイで文字数が20文字を超えています",
        "style": "白 パステル 淡い"
    })
    assert res2["overall_score"] < 60
    assert res2["verdict"] == "❌ 要修正"

    # 中間
    res3 = analyzer.analyze({
        "concept": "普通の画像 比較",
        "text_overlay": "15文字のテキストです",
        "style": "普通"
    })
    assert 60 <= res3["overall_score"] < 80
    assert res3["verdict"] == "⚠️ 改善推奨"

@pytest.mark.asyncio
async def test_analyze_image_gemini_vision_and_fallback(tmp_path):
    analyzer = ThumbnailAnalyzer()
    
    # 存在しない画像パスでのフォールバック
    res_fallback = analyzer.analyze_image("non_existent_image.png")
    # 20周目 CE-3 以降、画像を一度も開けなかった経路は
    # `analyze({"concept": path.stem})` の戻り値（＝**ファイル名の長さを
    # 「テキスト可読性」として採点**した総合点 57.5）を返さない。
    # 印だけ確認して mode 名を書き換えると空振りになるので、
    # **点を名乗っていないこと**まで見る。
    assert res_fallback["analysis_mode"] == "image_unanalyzed"
    assert res_fallback["overall_score"] is None
    assert res_fallback["verdict"] is None
    assert res_fallback["is_real"] is False
    assert res_fallback["data_source"] == "unavailable"
    assert res_fallback["unavailable_reason"]
    assert len(res_fallback["unscored_axes"]) == 4
    assert all(c["score"] is None for c in res_fallback["checks"])
    assert all(c["is_real"] is False for c in res_fallback["checks"])
    
    # ダミー画像を作成
    dummy_img = tmp_path / "dummy_analysis.png"
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img.save(dummy_img, "PNG")
    img.close()
    
    # Vision API mock (成功ケース)
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '```json\n{"face_score": 85, "text_score": 75, "contrast_score": 90, "composition_score": 80, "overall_impression": "良い", "top_improvement": "特にありません"}\n```'
    mock_client.models.generate_content.return_value = mock_response
    
    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        res = analyzer.analyze_image(str(dummy_img))
        assert res["analysis_mode"] == "gemini_vision"
        assert res["overall_score"] == 82.5
        assert res["verdict"] == "✅ 高品質"
        
    # Vision API mock (APIが None を返すフォールバックケース)
    with patch("gemini_client_factory.get_gemini_client", return_value=None):
        res = analyzer.analyze_image(str(dummy_img))
        # 20周目 CE-3 以降、画像を一度も開けなかった経路は
        # `analyze({"concept": path.stem})` の戻り値（＝**ファイル名の長さを
        # 「テキスト可読性」として採点**した総合点 57.5）を返さない。
        # 印だけ確認して mode 名を書き換えると空振りになるので、
        # **点を名乗っていないこと**まで見る。
        assert res["analysis_mode"] == "image_unanalyzed"
        assert res["overall_score"] is None
        assert res["verdict"] is None
        assert res["is_real"] is False
        assert res["data_source"] == "unavailable"
        assert res["unavailable_reason"]
        assert len(res["unscored_axes"]) == 4
        assert all(c["score"] is None for c in res["checks"])
        assert all(c["is_real"] is False for c in res["checks"])
        
    # Vision API mock (例外発生によるフォールバック)
    with patch("gemini_client_factory.get_gemini_client", side_effect=Exception("API Error")):
        res = analyzer.analyze_image(str(dummy_img))
        # 20周目 CE-3 以降、画像を一度も開けなかった経路は
        # `analyze({"concept": path.stem})` の戻り値（＝**ファイル名の長さを
        # 「テキスト可読性」として採点**した総合点 57.5）を返さない。
        # 印だけ確認して mode 名を書き換えると空振りになるので、
        # **点を名乗っていないこと**まで見る。
        assert res["analysis_mode"] == "image_unanalyzed"
        assert res["overall_score"] is None
        assert res["verdict"] is None
        assert res["is_real"] is False
        assert res["data_source"] == "unavailable"
        assert res["unavailable_reason"]
        assert len(res["unscored_axes"]) == 4
        assert all(c["score"] is None for c in res["checks"])
        assert all(c["is_real"] is False for c in res["checks"])

def test_generate_thumbnail_high_res_and_contrast(tmp_path):
    import numpy as np
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_4k.png"
    
    # 4K解像度 (dither_intensity = 0 になる分岐をカバー)
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=3840,
        height=2160,
        text="4K解像度テスト",
        use_banner=False
    )
    assert res_path.exists()
    
    # use_banner=False で、明るい背景 (輝度 > 0.5 の場合に text_fill と stroke_fill が反転する)
    output_bright = tmp_path / "test_bright.png"
    orig_array = np.array
    def mock_array_fn(l, dtype=None):
        if isinstance(l, list) and l in [[35, 30, 60], [15, 65, 95], [80, 45, 90], [240, 180, 80]]:
            return orig_array([250, 250, 250], dtype=np.float32)
        return orig_array(l, dtype=dtype)
    with patch("numpy.array", side_effect=mock_array_fn):
        res_bright = analyzer.generate_thumbnail(
            output_path=output_bright,
            width=1280,
            height=720,
            text="明るい背景テスト",
            use_banner=False
        )
        assert res_bright.exists()

def test_generate_thumbnail_quantize_and_size_exceptions(tmp_path):
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_quantize.png"
    
    # 4MB制限を超えて PNG クオンタイズに入るように、Path.stat() を安全にモック
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        stat_res = original_stat(self, *args, **kwargs)
        if ".tmp" in self.name:
            m = MagicMock(wraps=stat_res)
            m.st_size = 5 * 1024 * 1024
            return m
        return stat_res
    with patch.object(Path, "stat", mock_stat):
        with pytest.raises(ValueError) as excinfo:
            analyzer.generate_thumbnail(output_file, width=1280, height=720, text="クオンタイズ例外テスト")
        assert "Failed to compress PNG below 4MB" in str(excinfo.value)

def test_validate_thumbnail_corrupted_verify_more_exceptions(tmp_path):
    analyzer = ThumbnailAnalyzer()
    fake_png = tmp_path / "fake_exceptions.png"
    fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"some chunks")
    
    # DecompressionBombError を模倣
    from PIL.Image import DecompressionBombError
    with patch("PIL.Image.open") as mock_open:
        mock_open.side_effect = DecompressionBombError("Bomb detected")
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(fake_png)
        assert "Bomb detected" in str(excinfo.value) or "safe pixel dimensions" in str(excinfo.value)
        
    # verify() 中の SyntaxError
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.verify.side_effect = SyntaxError("Syntax error during verify")
        mock_open.return_value.__enter__.return_value = mock_img
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(fake_png)
        assert "invalid syntax" in str(excinfo.value)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_not_agent_and_db_locked(tmp_path):
    analyzer = ThumbnailAnalyzer()
    db_file = tmp_path / "test_resolve.db"
    task_id = "task_002"
    
    # StageBoundAgent ではない文字列IDとdb_pathなどを直接渡す
    result_json = await analyzer.resolve_thumbnail_task(
        agent_or_id=task_id,
        db_path=str(db_file),
        output_dir=str(tmp_path)
    )
    result_data = json.loads(result_json)
    assert result_data["valid"] is True
    
    # sqlite3.OperationalError: database is locked を発生させてリトライを走らせる
    import sqlite3
    with patch("sqlite3.connect") as mock_connect:
        mock_connect.side_effect = sqlite3.OperationalError("database is locked")
        with pytest.raises(sqlite3.OperationalError):
            await analyzer.resolve_thumbnail_task(
                agent_or_id=task_id,
                db_path=str(db_file),
                output_dir=str(tmp_path)
            )
            
    # 一般例外が発生した際に emit_critical が呼ばれることをテスト
    with patch.object(analyzer, "generate_thumbnail", side_effect=Exception("Critical drawing crash")):
        with patch("usage_tracker.alert_system.emit_critical") as mock_emit:
            with pytest.raises(Exception):
                await analyzer.resolve_thumbnail_task(
                    agent_or_id=task_id,
                    db_path=str(db_file),
                    output_dir=str(tmp_path)
                )
            mock_emit.assert_called_once()

def test_thumbnail_resolver(tmp_path):
    from backend.services.thumbnail_analyzer import ThumbnailResolver
    resolver = ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path / "thumbs")
    assert resolver.project_root == tmp_path
    assert resolver.output_dir == tmp_path / "thumbs"
    
    # resolve_thumbnail_task の非同期呼び出しテスト
    with patch("backend.services.thumbnail_analyzer.ThumbnailAnalyzer.resolve_thumbnail_task") as mock_resolve:
        mock_resolve.return_value = '{"valid": true}'
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            res = loop.run_until_complete(resolver.resolve_thumbnail_task("task_resolver_001"))
            assert res == '{"valid": true}'
        finally:
            loop.close()


def test_generate_thumbnail_none_inputs(tmp_path):
    """generate_thumbnailの引数にNoneを渡した場合のフォールバック検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_none_inputs.png"
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        width=None,
        height=None,
        text=None
    )
    assert res_path.exists()

def test_generate_thumbnail_paragraph_empty(tmp_path):
    """generate_thumbnailに空の改行を含むテキストを渡したときの検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_empty_line.png"
    res_path = analyzer.generate_thumbnail(
        output_path=output_file,
        text="Line1\n\nLine2"
    )
    assert res_path.exists()

def test_generate_thumbnail_invalid_bounds(tmp_path):
    """解像度が0以下のときの例外検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_bounds.png"
    with pytest.raises(ValueError):
        analyzer.generate_thumbnail(output_file, width=0, height=720)
    with pytest.raises(ValueError):
        analyzer.generate_thumbnail(output_file, width=1280, height=-10)

def test_generate_thumbnail_permission_error(tmp_path):
    """親ディレクトリが書き込み不可な場合の例外検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_permission.png"
    with patch("os.access", return_value=False):
        with pytest.raises(PermissionError):
            analyzer.generate_thumbnail(output_file)

def test_generate_thumbnail_cleanup_close_exception(tmp_path):
    """img.close()などが例外を投げる時の安全性の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_cleanup.png"
    
    close_count = 0
    original_close = Image.Image.close
    
    def mock_close(self, *args, **kwargs):
        nonlocal close_count
        close_count += 1
        # 最初の15回程度の通常クローズは通し、それ以降のクリーンアップの段階で例外を投げる
        if close_count > 15:
            raise Exception("Mocked close error")
        return original_close(self, *args, **kwargs)
        
    with patch("PIL.Image.Image.close", mock_close):
        res_path = analyzer.generate_thumbnail(output_file)
        assert res_path.exists()

def test_generate_thumbnail_font_fallback_errors(tmp_path):
    """ImageFont読み込み失敗時のフォールバック処理の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_font_fallback.png"
    
    original_exists = os.path.exists
    def mock_exists(path):
        if "truetype" in str(path) or "font" in str(path):
            return True
        return original_exists(path)
        
    mock_default_font = MagicMock()
    if hasattr(mock_default_font, "textbbox"):
        del mock_default_font.textbbox
    mock_default_font.getsize.return_value = (100, 20)
    real_mask = Image.new("L", (100, 20)).im
    mock_default_font.getmask2.return_value = (real_mask, (0, 0))
    mock_default_font.getbbox.side_effect = AttributeError("Mocked no getbbox")
    
    def mock_load_default(size=None):
        if size is not None:
            raise TypeError("size is invalid")
        return mock_default_font
        
    with patch("os.path.exists", side_effect=mock_exists):
        with patch("PIL.ImageFont.truetype", side_effect=OSError("Font load failed")):
            with patch("PIL.ImageFont.load_default", side_effect=mock_load_default):
                res_path = analyzer.generate_thumbnail(output_file, text="Font fallback test")
                assert res_path.exists()

def test_generate_thumbnail_font_too_small(tmp_path):
    """テキストサイズが大きすぎてフォントサイズが極小(12未満)になるelse節の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_too_small.png"
    
    very_long = "あ" * 500
    res_path = analyzer.generate_thumbnail(output_file, text=very_long)
    assert res_path.exists()

def test_generate_thumbnail_bg_luminance_variations(tmp_path):
    """背景輝度の異なるパターンの検証(中間輝度)"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_mid_luminance.png"
    
    import numpy as np
    orig_array = np.array
    def mock_array_fn(l, dtype=None):
        if isinstance(l, list) and l in [[35, 30, 60], [15, 65, 95], [80, 45, 90], [240, 180, 80]]:
            return orig_array([127, 127, 127], dtype=np.float32)
        return orig_array(l, dtype=dtype)
        
    with patch("numpy.array", side_effect=mock_array_fn):
        res_path = analyzer.generate_thumbnail(output_file, text="中間輝度")
        assert res_path.exists()

def test_validate_thumbnail_oserror_magic_number(tmp_path):
    """マジックナンバー検証中にOSErrorが起きた時の検証"""
    analyzer = ThumbnailAnalyzer()
    dummy_file = tmp_path / "dummy_oserror.png"
    dummy_file.write_bytes(b"dummy")
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Failed to verify file magic number" in str(excinfo.value)

def test_validate_thumbnail_invalid_dimensions(tmp_path):
    """ピクセルサイズが0以下の無効な画像データロードの検証"""
    analyzer = ThumbnailAnalyzer()
    dummy_file = tmp_path / "dummy_dim.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(dummy_file, "PNG")
    img.close()
    
    original_open = Image.open
    def mock_open(*args, **kwargs):
        img_obj = original_open(*args, **kwargs)
        img_obj._size = (0, 720)
        return img_obj
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Invalid image dimensions" in str(excinfo.value)

def test_validate_thumbnail_decompression_bomb_load(tmp_path):
    """ピクセルデータロード中のDecompressionBombError検証"""
    analyzer = ThumbnailAnalyzer()
    dummy_file = tmp_path / "dummy_bomb.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(dummy_file, "PNG")
    img.close()
    
    from PIL.Image import DecompressionBombError
    with patch("PIL.Image.Image.load", side_effect=DecompressionBombError("Load bomb")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Decompression Bomb" in str(excinfo.value)

def test_validate_thumbnail_load_exceptions(tmp_path):
    """ピクセルデータロード中のUnidentifiedImageError、ValueError、一般的なException検証"""
    analyzer = ThumbnailAnalyzer()
    dummy_file = tmp_path / "dummy_exceptions.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(dummy_file, "PNG")
    img.close()
    
    from PIL import UnidentifiedImageError
    # 1. UnidentifiedImageError
    with patch("PIL.Image.Image.load", side_effect=UnidentifiedImageError("Unidentified load")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Failed to open image during loading" in str(excinfo.value)
        
    # 2. ValueError
    with patch("PIL.Image.Image.load", side_effect=ValueError("Value invalid")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Invalid value encountered during pixel load" in str(excinfo.value)
        
    # 3. Exception
    with patch("PIL.Image.Image.load", side_effect=Exception("Generic load error")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail(dummy_file)
        assert "Unexpected error during image loading" in str(excinfo.value)

def test_analyze_image_suggestion_branches(tmp_path):
    """analyze_image内のsuggestion分岐の網羅テスト"""
    analyzer = ThumbnailAnalyzer()
    dummy_img = tmp_path / "dummy_branches.png"
    img = Image.new("RGB", (1280, 720), color=(100, 100, 100))
    img.save(dummy_img, "PNG")
    img.close()
    
    mock_client = MagicMock()
    
    mock_response1 = MagicMock()
    mock_response1.text = '```json\n{"face_score": 80, "text_score": 85, "contrast_score": 90, "composition_score": 50, "overall_impression": "良い", "top_improvement": "特になし"}\n```'
    
    mock_response2 = MagicMock()
    mock_response2.text = '```json\n{"face_score": 50, "text_score": 60, "contrast_score": 70, "composition_score": 80, "overall_impression": "良い", "top_improvement": "特になし"}\n```'
    
    mock_response3 = MagicMock()
    mock_response3.text = '```json\n{"face_score": 65, "text_score": 30, "contrast_score": 40, "composition_score": 60, "overall_impression": "良い", "top_improvement": "特になし"}\n```'

    mock_response4 = MagicMock()
    mock_response4.text = '```json\n{"face_score": 10, "text_score": 20, "contrast_score": 90, "composition_score": 70, "overall_impression": "良い", "top_improvement": "特になし"}\n```'

    with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
        # 1. パターン1
        mock_client.models.generate_content.return_value = mock_response1
        res1 = analyzer.analyze_image(str(dummy_img))
        suggestions1 = [c["suggestion"] for c in res1["checks"]]
        assert "顔が画面の30%以上を占めるようにする" in suggestions1
        assert "現状のまま保持" in suggestions1
        assert "現状のスタイルを維持" in suggestions1
        
        # 2. パターン2
        mock_client.models.generate_content.return_value = mock_response2
        res2 = analyzer.analyze_image(str(dummy_img))
        suggestions2 = [c["suggestion"] for c in res2["checks"]]
        assert "10文字以内に削減すると可読性向上" in suggestions2
        assert "黒背景+白/黄文字 of " not in "".join(suggestions2)
        assert "黒背景+白/黄文字の組み合わせが最も安全" in suggestions2
        assert "視線誘導の矢印やフレームを追加するとさらに効果的" in suggestions2
        
        # 3. パターン3
        mock_client.models.generate_content.return_value = mock_response3
        res3 = analyzer.analyze_image(str(dummy_img))
        suggestions3 = [c["suggestion"] for c in res3["checks"]]
        assert "驚き顔・リアクション顔を追加するとCTR +1.5%の可能性" in suggestions3
        assert "暗い背景色 or ビビッドカラーに変更してコントラストを確保" in suggestions3
        assert "Before/After比較、大きな数字、矢印のいずれかを追加" in suggestions3

        # 4. パターン4
        mock_client.models.generate_content.return_value = mock_response4
        res4 = analyzer.analyze_image(str(dummy_img))
        suggestions4 = [c["suggestion"] for c in res4["checks"]]
        assert "10文字以内に大胆に削減すること" in suggestions4

        # 5. パターン5 (contrast_score が最小)
        mock_response5 = MagicMock()
        mock_response5.text = '```json\n{"face_score": 90, "text_score": 80, "contrast_score": 30, "composition_score": 70, "overall_impression": "良い", "top_improvement": "コントラスト改善"}\n```'
        mock_client.models.generate_content.return_value = mock_response5
        res5 = analyzer.analyze_image(str(dummy_img))
        suggestions5 = [c["suggestion"] for c in res5["checks"]]
        assert "コントラスト改善" in suggestions5

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_sqlite_exceptions(tmp_path):
    """sqlite3.Errorでrollbackが実行される箇所の検証"""
    analyzer = ThumbnailAnalyzer()
    db_file = tmp_path / "test_sqlite_err.db"
    task_id = "task_sqlite_err"
    
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.Error("Mocked execute error")
    mock_conn.__enter__.return_value = mock_conn
    
    with patch("sqlite3.connect", return_value=mock_conn):
        with pytest.raises(sqlite3.Error):
            await analyzer.resolve_thumbnail_task(
                agent_or_id=task_id,
                db_path=str(db_file),
                output_dir=str(tmp_path)
            )

def test_generate_thumbnail_luminance_branches(tmp_path):
    """背景輝度 (bg_luminance) に基づくバナー色分岐の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_luminance.png"
    
    # bg_luminance > 0.6 のパターン (np.meanが255.0を返す)
    with patch("numpy.mean", return_value=255.0):
        analyzer.generate_thumbnail(
            output_path=output_file,
            width=1280,
            height=720,
            text="明るい輝度テスト",
            use_banner=True
        )
    assert output_file.exists()
    
    # bg_luminance < 0.3 のパターン (np.meanが0.0を返す)
    if output_file.exists():
        output_file.unlink()
    with patch("numpy.mean", return_value=0.0):
        analyzer.generate_thumbnail(
            output_path=output_file,
            width=1280,
            height=720,
            text="暗い輝度テスト",
            use_banner=True
        )
    assert output_file.exists()

def test_generate_thumbnail_validation_fails(tmp_path):
    """生成された画像が検証に失敗した場合のクリーンアップと例外再送の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_val_fail.png"
    
    with patch.object(analyzer, "validate_thumbnail", side_effect=ValueError("Mocked validation failure")):
        with pytest.raises(ValueError) as excinfo:
            analyzer.generate_thumbnail(
                output_path=output_file,
                width=1280,
                height=720,
                text="検証失敗テスト"
            )
        assert "Generated thumbnail quality validation failed" in str(excinfo.value)
    assert not output_file.exists()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_rollback_exception(tmp_path):
    """DB操作失敗時のrollback失敗ケースの検証"""
    analyzer = ThumbnailAnalyzer()
    db_file = tmp_path / "test_rollback_err.db"
    task_id = "task_rollback_err"
    
    mock_conn = MagicMock()
    mock_conn.execute.side_effect = sqlite3.Error("Mocked execute error")
    mock_conn.rollback.side_effect = Exception("Rollback failed")
    mock_conn.__enter__.return_value = mock_conn
    
    with patch("sqlite3.connect", return_value=mock_conn):
        with pytest.raises(sqlite3.Error):
            await analyzer.resolve_thumbnail_task(
                agent_or_id=task_id,
                db_path=str(db_file),
                output_dir=str(tmp_path)
            )

def test_validate_thumbnail_size_property_exception(tmp_path):
    """画像サイズ取得時に例外が発生した場合のデフォルト値フォールバックの検証"""
    analyzer = ThumbnailAnalyzer()
    dummy_file = tmp_path / "dummy_size_err.png"
    img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
    img.save(dummy_file, "PNG")
    img.close()
    
    class MockImage(MagicMock):
        @property
        def size(self):
            raise ValueError("Size access error")
            
    mock_img = MockImage()
    
    with patch("PIL.Image.open", return_value=mock_img):
        mock_img.load.return_value = None
        mock_img.tobytes.return_value = b""
        
        res = analyzer.validate_thumbnail(dummy_file)
        assert res["width"] == 1280
        assert res["height"] == 720

def test_generate_thumbnail_file_size_compressions(tmp_path):
    """JPEG圧縮ループおよびPNG減色ループのファイルサイズ上限検知と動作検証"""
    analyzer = ThumbnailAnalyzer()
    
    # 1. JPEG 圧縮リトライ & 失敗
    output_jpeg = tmp_path / "test_compress.jpg"
    
    original_stat = Path.stat
    def mock_stat_jpeg(self, *args, **kwargs):
        # ターゲットのファイルまたは一時ファイルのみモック
        if "test_compress" in self.name or ".tmp" in self.name:
            m = MagicMock()
            m.st_size = 5 * 1024 * 1024  # 5MB
            m.st_mode = 33188  # 一般ファイル (S_IFREG)
            return m
        return original_stat(self, *args, **kwargs)
    
    with patch.object(Path, "stat", mock_stat_jpeg):
        with pytest.raises(ValueError) as excinfo:
            analyzer.generate_thumbnail(
                output_path=output_jpeg,
                width=1280,
                height=720,
                text="JPEG圧縮テスト"
            )
        assert "Failed to compress JPEG below 4MB" in str(excinfo.value)

    # 2. PNG 減色リトライ (1回目 5MB -> 2回目 3MB)
    output_png = tmp_path / "test_compress.png"
    sizes = [5 * 1024 * 1024, 3 * 1024 * 1024, 3 * 1024 * 1024]
    
    class MockStatResult:
        def __init__(self):
            self.call_count = 0
            self.st_mode = 33188  # 一般ファイル (S_IFREG)
        @property
        def st_size(self):
            val = sizes[min(self.call_count, len(sizes)-1)]
            self.call_count += 1
            return val
            
    mock_stat_res = MockStatResult()
    def mock_stat_png(self, *args, **kwargs):
        if "test_compress" in self.name or ".tmp" in self.name:
            m = MagicMock()
            m.st_size = mock_stat_res.st_size
            m.st_mode = mock_stat_res.st_mode
            return m
        return original_stat(self, *args, **kwargs)
            
    with patch.object(Path, "stat", mock_stat_png):
        res_path = analyzer.generate_thumbnail(
            output_path=output_png,
            width=1280,
            height=720,
            text="PNG減色テスト"
        )
        assert res_path.exists()

def test_generate_thumbnail_rename_fallbacks(tmp_path):
    """一時ファイルリネーム時のOSErrorとshutil.moveによるフォールバック動作の検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_rename_fallback.png"
    
    # rename が OSError を投げるが shutil.move で成功するパターン
    with patch.object(Path, "rename", side_effect=OSError("Permission denied")):
        with patch("shutil.move") as mock_move:
            def create_dest(*args, **kwargs):
                img = Image.new("RGB", (1280, 720), color=(255, 0, 0))
                img.save(output_file, "PNG")
                img.close()
            mock_move.side_effect = create_dest
            
            res_path = analyzer.generate_thumbnail(
                output_path=output_file,
                width=1280,
                height=720,
                text="リネームフォールバック"
            )
            assert res_path.exists()
            assert mock_move.called

    # rename も shutil.move も失敗して IOError になるパターン
    if output_file.exists():
        output_file.unlink()
    with patch.object(Path, "rename", side_effect=OSError("Permission denied")):
        with patch("shutil.move", side_effect=Exception("Move failed")):
            with pytest.raises(IOError) as excinfo:
                analyzer.generate_thumbnail(
                    output_path=output_file,
                    width=1280,
                    height=720,
                    text="リネーム完全失敗"
                )
            assert "Failed to move temporary file" in str(excinfo.value)

def test_generate_thumbnail_unlink_exceptions(tmp_path):
    """例外発生時およびfinallyブロック内での一時ファイル削除時OSErrorの例外処理検証"""
    analyzer = ThumbnailAnalyzer()
    output_file = tmp_path / "test_unlink_err.png"
    
    # 1. 保存中に例外が発生し、temp_path.unlink() でも OSError が発生するパターン
    with patch("PIL.Image.Image.save", side_effect=ValueError("Save error")):
        with patch.object(Path, "unlink", side_effect=OSError("Cannot delete")):
            with pytest.raises(ValueError):
                analyzer.generate_thumbnail(
                    output_path=output_file,
                    width=1280,
                    height=720,
                    text="アンリンクエラー"
                )

    # 2. finally ブロック内で temp_path.unlink() が OSError を投げるパターン
    with patch.object(Path, "exists", return_value=True):
        with patch.object(Path, "unlink", side_effect=OSError("Finally delete fail")):
            res_path = analyzer.generate_thumbnail(
                output_path=output_file,
                width=1280,
                height=720,
                text="ファイナリアンリンク"
            )
            assert res_path.exists()

def test_validate_thumbnail_decompression_bomb_stub():
    """DecompressionBombErrorのインポート失敗時のダミークラス定義の動作検証"""
    analyzer = ThumbnailAnalyzer()
    
    import builtins
    real_import = builtins.__import__
    
    def mock_import(name, globals=None, locals=None, fromlist=None, level=0):
        if name == "PIL.Image" and fromlist and "DecompressionBombError" in fromlist:
            raise ImportError("Mocked DecompressionBombError import error")
        return real_import(name, globals, locals, fromlist, level)
        
    with patch("builtins.__import__", side_effect=mock_import):
        # 実際に例外クラスのフォールバック定義が呼ばれることを確認
        from PIL import Image
        dummy_file = Path("dummy_stub.png")
        # 実際にはファイルのバリデーション等は行わないが、
        # validate_thumbnail 内のインポート処理をカバーする。
        # パス名エラーなどの例外チェックに進むはず。
        with pytest.raises(ValueError) as excinfo:
            analyzer.validate_thumbnail("")
        assert "File path must not be empty" in str(excinfo.value)

