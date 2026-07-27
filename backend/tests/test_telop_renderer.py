import os
import pytest
from unittest.mock import patch, MagicMock
from backend.video_pipeline.telop_renderer import TelopRenderer, TelopResult

@pytest.mark.parametrize(
    "text,style,expected_success",
    [
        # 1. 正常系: standard スタイル
        ("テストテロップ標準", "standard", True),
        # 2. 正常系: emphasis スタイル
        ("テストテロップ強調", "emphasis", True),
        # 3. 正常系: subtitle スタイル
        ("テストテロップ字幕", "subtitle", True),
        # 4. 正常系: 未知のスタイル（standardにフォールバック）
        ("未知のスタイルテスト", "unknown_style", True),
        # 5. 境界値: 最小文字数 (1文字)
        ("A", "standard", True),
        # 6. 境界値: 非常に長いテキスト (100文字)
        ("あ" * 100, "standard", True),
        # 7. 異常系: 空文字列
        ("", "standard", False),
        # 8. 異常系: 空白のみの文字列
        ("   ", "standard", False),
        # 9. 異常系: None
        (None, "standard", False),
        # 10. 異常系: 無効なカラーコード（ValueError 発生）
        ("無効なカラーテスト", "invalid_color", False),
        # 11. 異常系: 保存ディレクトリが無効（OSError 発生）
        ("ディレクトリ無効テスト", "standard", False),
    ]
)
def test_render_telop_scenarios(tmp_path, text, style, expected_success):
    # 無効なカラーコードを持つカスタムトークン
    design_tokens = {
        "standard": {
            "font_size": 48,
            "color": "#FFFFFF",
            "bg_color": "#000000CC",
        },
        "emphasis": {
            "font_size": 64,
            "color": "#FFD700",
            "bg_color": "#CC0000DD",
        },
        "subtitle": {
            "font_size": 36,
            "color": "#FFFFFF",
            "bg_color": "#00000099",
        },
        "invalid_color": {
            "font_size": 48,
            "color": "#GGGGGG",  # ValueError を発生させる
            "bg_color": "#000000CC",
        }
    }

    # ディレクトリ無効ケースでは OSError を発生させるモックを設定
    renderer = TelopRenderer(design_tokens=design_tokens, output_dir=str(tmp_path))
    if text == "ディレクトリ無効テスト":
        renderer._create_text_image = MagicMock(side_effect=OSError("Mocked write error"))

    result = renderer.render_telop(text, style=style)

    assert result.success == expected_success
    expected_text = text if text is not None else ""
    assert result.text == expected_text
    if expected_success:
        assert os.path.exists(result.image_path)
        assert result.image_path.endswith(".png")
        assert result.width > 0
        assert result.height > 0
    else:
        assert result.image_path == ""


def test_render_batch(tmp_path):
    renderer = TelopRenderer(output_dir=str(tmp_path))
    texts = ["こんにちは", "重要なポイント", "まとめ"]
    results = renderer.render_batch(texts, style="standard")

    assert len(results) == 3
    for r in results:
        assert r.success
        assert os.path.exists(r.image_path)


def test_pillow_not_available_fallback(tmp_path):
    # Pillowが利用不可の場合のフォールバックテスト
    renderer = TelopRenderer(output_dir=str(tmp_path))

    with patch.object(TelopRenderer, "_is_pillow_available", return_value=False):
        result = renderer.render_telop("フォールバックテスト", style="standard")

        assert result.success
        assert os.path.exists(result.image_path)
        # 1x1 の空 PNG が生成されているはず
        # ファイルサイズが非常に小さいことを確認
        assert os.path.getsize(result.image_path) > 0
        # PNGのシグネチャを確認
        with open(result.image_path, "rb") as f:
            sig = f.read(8)
            assert sig == b"\x89PNG\r\n\x1a\n"
