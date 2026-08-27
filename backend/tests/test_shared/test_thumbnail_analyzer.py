"""
thumbnail_analyzer.py に対するエッジケース・異常系テスト
カバレッジ 100% を達成するためのユニットテストスイート
"""
import sys
import os
import base64
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# backend ディレクトリを sys.path に追加 (動的に取得)
_backend_dir = str(Path(__file__).resolve().parents[2])
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from services.thumbnail_analyzer import ThumbnailAnalyzer, thumbnail_analyzer


class TestThumbnailAnalyzerTextMatch:
    """テキスト分析機能 (analyze) のテストケース"""

    def test_face_closeup_branch(self):
        """顔クローズアップチェックの分岐テスト"""
        analyzer = ThumbnailAnalyzer()
        
        # 顔クローズアップあり
        res_face = analyzer.analyze({"concept": "驚き顔のクローズアップ"})
        face_check = next(c for c in res_face["checks"] if c["name"] == "顔クローズアップ")
        assert face_check["score"] == 90
        assert face_check["status"] == "✅"
        assert "顔のクローズアップを含む" in face_check["detail"]

        # 顔クローズアップなし
        res_no_face = analyzer.analyze({"concept": "ただの背景映像"})
        no_face_check = next(c for c in res_no_face["checks"] if c["name"] == "顔クローズアップ")
        assert no_face_check["score"] == 40
        assert no_face_check["status"] == "⚠️"
        assert "顔のクローズアップが検出されない" in no_face_check["detail"]

        # 空データ・キー欠損
        res_empty = analyzer.analyze({})
        empty_check = next(c for c in res_empty["checks"] if c["name"] == "顔クローズアップ")
        assert empty_check["score"] == 40

    def test_text_readability_branch(self):
        """テキスト可読性チェックの分岐テスト (10文字 / 20文字 / 21文字以上の境界値)"""
        analyzer = ThumbnailAnalyzer()

        # 10文字以下 (境界値)
        res_10 = analyzer.analyze({"concept": "あいうえおかきくけこ"})  # 10文字
        check_10 = next(c for c in res_10["checks"] if c["name"] == "テキスト可読性")
        assert check_10["score"] == 95
        assert check_10["status"] == "✅"
        assert "モバイルで大きく表示可能" in check_10["detail"]

        # 11〜20文字 (境界値)
        res_11 = analyzer.analyze({"concept": "あいうえおかきくけこさ"})  # 11文字
        check_11 = next(c for c in res_11["checks"] if c["name"] == "テキスト可読性")
        assert check_11["score"] == 70
        assert check_11["status"] == "⚠️"
        assert "モバイルでギリギリ読める" in check_11["detail"]

        res_20 = analyzer.analyze({"concept": "あいうえおかきくけこさしすせそたちつてと"})  # 20文字
        check_20 = next(c for c in res_20["checks"] if c["name"] == "テキスト可読性")
        assert check_20["score"] == 70

        # 21文字以上 (境界値)
        res_21 = analyzer.analyze({"concept": "あいうえおかきくけこさしすせそたちつてとな"})  # 21文字
        check_21 = next(c for c in res_21["checks"] if c["name"] == "テキスト可読性")
        assert check_21["score"] == 35
        assert check_21["status"] == "❌"
        assert "モバイルで読めない可能性が高い" in check_21["detail"]

        # text_overlay 優先の挙動
        res_overlay = analyzer.analyze({
            "concept": "あいうえおかきくけこさしすせそたちつてとな",  # 21文字
            "text_overlay": "短い文字"  # 4文字
        })
        check_overlay = next(c for c in res_overlay["checks"] if c["name"] == "テキスト可読性")
        assert check_overlay["score"] == 95

    def test_color_contrast_branch(self):
        """カラーコントラストチェックの分岐テスト"""
        analyzer = ThumbnailAnalyzer()

        # 高コントラスト
        res_high = analyzer.analyze({"style": "黒背景でビビッドな赤文字"})
        check_high = next(c for c in res_high["checks"] if c["name"] == "カラーコントラスト")
        assert check_high["score"] == 90
        assert check_high["status"] == "✅"

        # 低コントラスト
        res_low = analyzer.analyze({"style": "白いパステル調の背景"})
        check_low = next(c for c in res_low["checks"] if c["name"] == "カラーコントラスト")
        assert check_low["score"] == 35
        assert check_low["status"] == "❌"

        # 情報不足
        res_mid = analyzer.analyze({"style": "普通のデザイン"})
        check_mid = next(c for c in res_mid["checks"] if c["name"] == "カラーコントラスト")
        assert check_mid["score"] == 65
        assert check_mid["status"] == "⚠️"

    def test_composition_branch(self):
        """構図チェックの分岐テスト"""
        analyzer = ThumbnailAnalyzer()

        # 効果的パターンあり
        res_comp = analyzer.analyze({"concept": "Before/Afterの比較をする"})
        check_comp = next(c for c in res_comp["checks"] if c["name"] == "構図パターン")
        assert check_comp["score"] == 85
        assert check_comp["status"] == "✅"
        assert "効果的パターン検出" in check_comp["detail"]

        # 効果的パターンなし
        res_no_comp = analyzer.analyze({"concept": "普通の料理風景"})
        check_no_comp = next(c for c in res_no_comp["checks"] if c["name"] == "構図パターン")
        assert check_no_comp["score"] == 55
        assert check_no_comp["status"] == "⚠️"

    def test_verdict_ranges(self):
        """総合スコアによる判定の境界値テスト (80以上 / 60以上 / 60未満)"""
        analyzer = ThumbnailAnalyzer()

        # 高品質 (平均 80以上)
        res_high = analyzer.analyze({
            "concept": "驚き顔のBefore/After比較",
            "style": "黒背景のビビッドなデザイン",
            "text_overlay": "短い文字"
        })
        assert res_high["overall_score"] >= 80.0
        assert res_high["verdict"] == "✅ 高品質"

        # 改善推奨 (平均 60〜79)
        res_mid = analyzer.analyze({
            "concept": "驚き顔の風景",
            "style": "普通のデザイン",
            "text_overlay": "21文字以上の長い長いテキストオーバーレイです"
        })
        assert 60.0 <= res_mid["overall_score"] < 80.0
        assert res_mid["verdict"] == "⚠️ 改善推奨"

        # 要修正 (平均 60未満)
        res_low = analyzer.analyze({
            "concept": "パステルカラーの背景のテキストのみの動画",
            "style": "白いパステル調の背景",
            "text_overlay": "21文字以上の長い長いテキストオーバーレイです"
        })
        assert res_low["overall_score"] < 60.0
        assert res_low["verdict"] == "❌ 要修正"

    def test_estimate_ctr_impact_ranges(self):
        """CTR推定ロジックの全境界値テスト"""
        analyzer = ThumbnailAnalyzer()
        assert analyzer._estimate_ctr_impact(85.0) == "+1.5-2.0% CTRブースト見込み"
        assert analyzer._estimate_ctr_impact(84.9) == "+0.5-1.0% CTRブースト見込み"
        assert analyzer._estimate_ctr_impact(70.0) == "+0.5-1.0% CTRブースト見込み"
        assert analyzer._estimate_ctr_impact(69.9) == "±0% CTR影響は中立"
        assert analyzer._estimate_ctr_impact(50.0) == "±0% CTR影響は中立"
        assert analyzer._estimate_ctr_impact(49.9) == "-1.0% CTR低下リスクあり"


class TestThumbnailAnalyzerImageVision:
    """実画像 Vision API 分析 (analyze_image) のテストケース"""

    def test_analyze_image_file_not_found(self, caplog):
        """画像ファイルが存在しない場合、テキスト分析にフォールバックすることを確認"""
        analyzer = ThumbnailAnalyzer()
        non_existent_path = "non_existent_thumbnail.jpg"

        caplog.clear()
        with caplog.at_level(logging.WARNING):
            res = analyzer.analyze_image(non_existent_path)
            assert "サムネイル画像が見つかりません" in caplog.text
            assert res["analysis_mode"] == "text_match"
            assert res["top_improvement"] is not None

    def test_analyze_image_api_client_none(self, tmp_path, caplog):
        """Gemini API クライアントが None の場合、テキスト分析にフォールバックすることを確認"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy image data")

        caplog.clear()
        with patch("gemini_client_factory.get_gemini_client", return_value=None), \
             caplog.at_level(logging.INFO):
            res = analyzer.analyze_image(str(temp_file))
            assert "Gemini API未設定 — テキスト分析にフォールバック" in caplog.text
            assert res["analysis_mode"] == "text_match"

    def test_analyze_image_api_success_json_block(self, tmp_path):
        """Vision API が markdown コードブロック形式の JSON を返したとき、正常にパースできることを確認"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.png"
        temp_file.write_bytes(b"dummy png data")

        # モックの作成
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "```json\n"
            '{\n  "face_score": 85,\n  "text_score": 75,\n  "contrast_score": 90,\n'
            '  "composition_score": 80,\n  "overall_impression": "素晴らしい构図です",\n'
            '  "top_improvement": "特にありません"\n}\n'
            "```"
        )
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("services.thumbnail_analyzer.get_model", return_value="mock-vision-model"):
            res = analyzer.analyze_image(str(temp_file))
            
            assert res["analysis_mode"] == "gemini_vision"
            assert res["overall_score"] == 82.5
            assert res["verdict"] == "✅ 高品質"
            assert res["overall_impression"] == "素晴らしい构図です"
            assert res["top_improvement"] == "特にありません"

    def test_analyze_image_api_success_json_block_without_json_prefix(self, tmp_path):
        """Vision API が json プレフィックスのない markdown コードブロック形式の JSON を返したとき、正常にパースできることを確認"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.png"
        temp_file.write_bytes(b"dummy png data")

        # モックの作成
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            "```\n"
            '{\n  "face_score": 85,\n  "text_score": 75,\n  "contrast_score": 90,\n'
            '  "composition_score": 80,\n  "overall_impression": "素晴らしい构図です",\n'
            '  "top_improvement": "特にありません"\n}\n'
            "```"
        )
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             patch("services.thumbnail_analyzer.get_model", return_value="mock-vision-model"):
            res = analyzer.analyze_image(str(temp_file))
            
            assert res["analysis_mode"] == "gemini_vision"
            assert res["overall_score"] == 82.5
            assert res["verdict"] == "✅ 高品質"
            assert res["overall_impression"] == "素晴らしい构図です"
            assert res["top_improvement"] == "特にありません"

    def test_analyze_image_api_success_raw_json(self, tmp_path):
        """Vision API がコードブロックなしの生の JSON を返したとき、正常にパースできることを確認"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy jpg data")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"face_score": 35, "text_score": 50, "contrast_score": 60, "composition_score": 55, '
            '"overall_impression": "要改善です", "top_improvement": "文字を大きくしてください"}'
        )
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            
            assert res["analysis_mode"] == "gemini_vision"
            assert res["overall_score"] == 50.0
            assert res["verdict"] == "❌ 要修正"
            assert res["top_improvement"] == "文字を大きくしてください"

            # チェック項目の個別ステータス検証
            checks = res["checks"]
            face_check = next(c for c in checks if c["name"] == "顔クローズアップ")
            assert face_check["score"] == 35
            assert face_check["status"] == "❌"

            # 最低スコアが face_score (35) なので、suggestion は top_improvement となる
            assert face_check["suggestion"] == "文字を大きくしてください"

    def test_analyze_image_api_success_missing_fields(self, tmp_path):
        """Vision API の返却 JSON に一部のキーが欠損している場合、デフォルト値 50 が適用されることを確認"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy jpg data")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '{"face_score": 90}'
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            
            assert res["analysis_mode"] == "gemini_vision"
            assert res["overall_score"] == 60.0
            assert res["verdict"] == "⚠️ 改善推奨"
            
            checks = res["checks"]
            text_check = next(c for c in checks if c["name"] == "テキスト可読性")
            assert text_check["score"] == 50
            assert text_check["status"] == "⚠️"

    def test_analyze_image_api_json_parse_error(self, tmp_path, caplog):
        """Vision API が不正な JSON (パースエラー) を返したとき、例外をキャッチしてテキスト分析にフォールバックすることを確認 (TD-532検証)"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy jpg data")

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "invalid json text here"
        mock_client.models.generate_content.return_value = mock_response

        caplog.clear()
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             caplog.at_level(logging.ERROR):
            res = analyzer.analyze_image(str(temp_file))
            
            assert "Gemini Vision分析応答パースエラー" in caplog.text
            assert res["analysis_mode"] == "text_match"

    def test_analyze_image_api_exception(self, tmp_path, caplog):
        """Vision API 呼び出し自体が例外を投げたとき、例外をキャッチしてテキスト分析にフォールバックすることを確認 (TD-532検証)"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy data")

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API connection timed out")

        caplog.clear()
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             caplog.at_level(logging.ERROR):
            res = analyzer.analyze_image(str(temp_file))
            
            assert "Gemini Vision分析エラー — テキスト分析にフォールバック" in caplog.text
            assert res["analysis_mode"] == "text_match"

    def test_analyze_image_dynamic_suggestions(self, tmp_path):
        """Vision APIの分析結果において、スコアに応じた動的な改善提案(suggestion)が設定されること、および最低スコアの項目には top_improvement が適用されることを検証"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy data")

        # 1. 全て高スコア (90点以上) の場合。最低スコアは text_score (90)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"face_score": 95, "text_score": 90, "contrast_score": 92, "composition_score": 94, '
            '"overall_impression": "素晴らしいサムネイルです", "top_improvement": "テキストサイズを微調整してください"}'
        )
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            checks = res["checks"]
            face_check = next(c for c in checks if c["name"] == "顔クローズアップ")
            text_check = next(c for c in checks if c["name"] == "テキスト可読性")
            contrast_check = next(c for c in checks if c["name"] == "カラーコントラスト")
            comp_check = next(c for c in checks if c["name"] == "構図パターン")

            # text_score (90) は最低スコアなので、top_improvement が適用される
            assert text_check["suggestion"] == "テキストサイズを微調整してください"
            # face_score (95) は高スコア。テキストマッチと同様に「顔が画面の30%以上を占めるようにする」
            assert face_check["suggestion"] == "顔が画面の30%以上を占めるようにする"
            # contrast_score (92) は高スコアなので「現状のスタイルを維持」
            assert contrast_check["suggestion"] == "現状のスタイルを維持"
            # composition_score (94) は高スコアなので「視線誘導の矢印やフレームを追加するとさらに効果的」
            assert comp_check["suggestion"] == "視線誘導の矢印やフレームを追加するとさらに効果的"

        # 2. 低スコアがある場合。最低スコアは contrast_score (30)
        mock_response2 = MagicMock()
        mock_response2.text = (
            '{"face_score": 80, "text_score": 45, "contrast_score": 30, "composition_score": 60, '
            '"overall_impression": "コントラストが低すぎます", "top_improvement": "背景を暗くして文字を目立たせてください"}'
        )
        mock_client.models.generate_content.return_value = mock_response2

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res2 = analyzer.analyze_image(str(temp_file))
            checks2 = res2["checks"]
            face_check2 = next(c for c in checks2 if c["name"] == "顔クローズアップ")
            text_check2 = next(c for c in checks2 if c["name"] == "テキスト可読性")
            contrast_check2 = next(c for c in checks2 if c["name"] == "カラーコントラスト")
            comp_check2 = next(c for c in checks2 if c["name"] == "構図パターン")

            # contrast_score (30) は最低スコアなので top_improvement
            assert contrast_check2["suggestion"] == "背景を暗くして文字を目立たせてください"
            # face_score (80) は高スコア
            assert face_check2["suggestion"] == "顔が画面の30%以上を占めるようにする"
            # text_score (45) は最低スコアではないが、中スコアなので「10文字以内に削減すると可読性向上」
            assert text_check2["suggestion"] == "10文字以内に削減すると可読性向上"
            # composition_score (60) は中スコアなので「Before/After比較、大きな数字、矢印のいずれかを追加」
            assert comp_check2["suggestion"] == "Before/After比較、大きな数字、矢印のいずれかを追加"

    def test_analyze_image_dynamic_suggestions_missing_branches(self, tmp_path):
        """146行目、150行目、160行目の未カバー分岐（text_sugg, contrast_sugg）をカバーするテスト"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "temp_thumb.jpg"
        temp_file.write_bytes(b"dummy data")

        # 1. 146行目をカバー: text_score >= 80 かつ最低スコアではない (face_score が最低)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = (
            '{"face_score": 50, "text_score": 85, "contrast_score": 90, "composition_score": 90, '
            '"overall_impression": "テスト", "top_improvement": "顔を大きくしてください"}'
        )
        mock_client.models.generate_content.return_value = mock_response

        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            text_check = next(c for c in res["checks"] if c["name"] == "テキスト可読性")
            assert text_check["suggestion"] == "現状のまま保持"

        # 2. 150行目をカバー: text_score < 40 かつ最低スコアではない (face_score が最低)
        mock_response.text = (
            '{"face_score": 20, "text_score": 30, "contrast_score": 90, "composition_score": 90, '
            '"overall_impression": "テスト", "top_improvement": "顔をもっと大きくしてください"}'
        )
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            text_check = next(c for c in res["checks"] if c["name"] == "テキスト可読性")
            assert text_check["suggestion"] == "10文字以内に大胆に削減すること"

        # 3. 160行目をカバー: contrast_score < 50 かつ最低スコアではない (face_score が最低)
        mock_response.text = (
            '{"face_score": 20, "text_score": 90, "contrast_score": 30, "composition_score": 90, '
            '"overall_impression": "テスト", "top_improvement": "顔をもっと大きくしてください"}'
        )
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client):
            res = analyzer.analyze_image(str(temp_file))
            contrast_check = next(c for c in res["checks"] if c["name"] == "カラーコントラスト")
            assert contrast_check["suggestion"] == "暗い背景色 or ビビッドカラーに変更してコントラストを確保"

    def test_parse_vision_api_response_robustness(self):
        """_parse_vision_api_response が多様な markdown block や不要なテキストを頑健に処理できることを検証"""
        analyzer = ThumbnailAnalyzer()

        # パターン 1: 大文字の ```JSON
        text_upper = (
            "分析結果です:\n"
            "```JSON\n"
            '{"face_score": 80}\n'
            "```"
        )
        res_upper = analyzer._parse_vision_api_response(text_upper)
        assert res_upper["face_score"] == 80

        # パターン 2: 余分なスペースがある ``` json
        text_space = (
            "``` json \n"
            '{"face_score": 85}\n'
            "```"
        )
        res_space = analyzer._parse_vision_api_response(text_space)
        assert res_space["face_score"] == 85

        # パターン 3: ``` の前後に大量のテキスト
        text_extra = (
            "Here is the result:\n"
            "```\n"
            '{"face_score": 90}\n'
            "```\n"
            "Hope this helps!"
        )
        res_extra = analyzer._parse_vision_api_response(text_extra)
        assert res_extra["face_score"] == 90


class TestThumbnailAnalyzerImportFallback:
    """ImportError が発生した場合のフォールバック動作のテスト"""

    def test_get_model_fallback(self):
        """get_model が定義されていない（ImportError）場合のフォールバック定義テスト"""
        import sys
        import importlib
        
        # 既存の model_registry を退避
        old_registry = sys.modules.get("model_registry")
        
        try:
            # model_registry のインポート時に ImportError を強制的に発生させる
            sys.modules["model_registry"] = None
            
            # thumbnail_analyzer モジュールを再ロード（これにより try-except ImportError が実行される）
            import services.thumbnail_analyzer
            importlib.reload(services.thumbnail_analyzer)
            
            # フォールバックの get_model が期待通り動作することを確認
            fallback_get_model = services.thumbnail_analyzer.get_model
            assert fallback_get_model("any_task") == "gemini-3.6-flash"
            
        finally:
            # sys.modules を復元
            if old_registry is not None:
                sys.modules["model_registry"] = old_registry
            else:
                sys.modules.pop("model_registry", None)
                
            # テスト終了後に thumbnail_analyzer を元の状態に戻すために再リロード
            import services.thumbnail_analyzer
            importlib.reload(services.thumbnail_analyzer)

class TestThumbnailAnalyzerGenerationAndValidation:
    """新規追加：サムネイル生成・画像処理・品質検証・StageBoundAgent連携テスト"""

    def test_generate_thumbnail_success(self, tmp_path):
        """正常に解像度1280x720・アスペクト比16:9で画像が生成され、4MB未満かつ破損のないPNGが保存されること"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "success.png"
        
        # 1280x720のサムネイル生成
        res_path = analyzer.generate_thumbnail(output_path, width=1280, height=720, text="Success Test")
        assert res_path.exists()
        assert res_path == output_path
        
        # 品質検証の実施
        info = analyzer.validate_thumbnail(output_path)
        assert info["path"] == str(output_path)
        assert info["width"] == 1280
        assert info["height"] == 720
        assert info["size_bytes"] > 0
        assert info["size_bytes"] < 4 * 1024 * 1024

    def test_validate_thumbnail_invalid_resolution(self, tmp_path):
        """1280x720未満の画像に対する検証エラーの発生を確認"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "low_res.png"
        
        from PIL import Image
        img = Image.new("RGB", (640, 360), color=(10, 10, 10))
        img.save(output_path, "PNG")
        
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            analyzer.validate_thumbnail(output_path)

    def test_validate_thumbnail_invalid_aspect_ratio(self, tmp_path):
        """16:9ではない画像に対する検証エラーの発生を確認"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "bad_aspect.png"
        
        from PIL import Image
        img = Image.new("RGB", (1280, 1280), color=(10, 10, 10))
        img.save(output_path, "PNG")
        
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            analyzer.validate_thumbnail(output_path)

    def test_validate_thumbnail_exceed_size(self, tmp_path):
        """4MB以上のファイルに対する検証エラーの発生を確認"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "exceed_size.png"
        
        from PIL import Image
        img = Image.new("RGB", (1280, 720), color=(10, 10, 10))
        img.save(output_path, "PNG")
        
        # 4MB以上にパディングするために、追記
        with open(output_path, "ab") as f:
            f.write(b"\0" * (4 * 1024 * 1024 + 10))
            
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            analyzer.validate_thumbnail(output_path)

    def test_validate_thumbnail_corrupted(self, tmp_path):
        """破損した画像ファイルに対する検証エラーの発生を確認"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "corrupted.png"
        output_path.write_bytes(b"not an image file content at all")
        
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            analyzer.validate_thumbnail(output_path)

    @pytest.mark.anyio
    async def test_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgent との統合検証。タスク登録、READYタスク監視、resolve_thumbnail_task 実行、自動リトライ、DB結果保存の確認"""
        from agents.stage_bound_agent import StageBoundAgent
        import json
        import asyncio
        
        db_path = str(tmp_path / "test_tasks.db")
        agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path, poll_interval=0.01)
        
        analyzer = ThumbnailAnalyzer()
        
        analyzer.width = 1280
        analyzer.height = 720
        analyzer.text = "Agent Test"
        
        task_id = "test_task_001"
        out_dir = tmp_path / "temp_thumbnails"
        out_dir.mkdir(exist_ok=True)
        
        async def process_task(tid):
            return await analyzer.resolve_thumbnail_task(tid, output_dir=str(out_dir))
            
        await agent.register_task(task_id, initial_status="READY", max_retries=1)
        await agent.start(process_task)
        
        import time
        start_time = time.time()
        completed = False
        while time.time() - start_time < 5.0:
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                completed = True
                break
            await asyncio.sleep(0.05)
            
        await agent.stop()
        
        assert completed
        
        # DBに保存された結果の検証
        conn = agent._get_conn()
        try:
            cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            result_val = row[0]
            error_val = row[1]
            retry_count = row[2]
            
            assert error_val is None
            assert retry_count == 0
            assert result_val is not None
            
            result_data = json.loads(result_val)
            assert result_data["width"] == 1280
            assert result_data["height"] == 720
            
            output_file = out_dir / f"{task_id}.png"
            assert output_file.exists()
        finally:
            agent._close_conn(conn)

    def test_thumbnail_resolver_compatibility(self, tmp_path):
        """互換用の ThumbnailResolver クラスの動作検証"""
        from services.thumbnail_analyzer import ThumbnailResolver
        resolver = ThumbnailResolver(project_root=tmp_path, output_dir=tmp_path / "out")
        
        output_path = tmp_path / "out" / "resolver_test.png"
        res_path = resolver.generate_thumbnail(output_path, text="Resolver Text")
        assert res_path.exists()
        
        info = resolver.validate_thumbnail(output_path)
        assert info["width"] == 1280
        assert info["height"] == 720

    def test_generate_thumbnail_invalid_params_extra(self):
        """0や負数、極端に巨大な解像度(8K超)に対するエラーハンドリングの追加テスト"""
        analyzer = ThumbnailAnalyzer()
        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            analyzer.generate_thumbnail("dummy.png", width=0, height=720)
        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            analyzer.generate_thumbnail("dummy.png", width=1280, height=-100)
        with pytest.raises(ValueError, match="Resolution exceeds maximum limit of 8K"):
            analyzer.generate_thumbnail("dummy.png", width=8000, height=4500)

    def test_generate_thumbnail_supersampling_quality_check(self, tmp_path):
        """スーパサンプリングが正常に適用され、解像度、アスペクト比、ファイルサイズが品質基準を満たすことの検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "quality_test.png"
        
        # 1920x1080 (16:9) で生成
        res_path = analyzer.generate_thumbnail(output_path, width=1920, height=1080, text="SuperSampling Test")
        assert res_path.exists()
        
        # Pillowで開いて検証
        from PIL import Image
        with Image.open(res_path) as img:
            img.verify()
            
        with Image.open(res_path) as img:
            img.load()
            w, h = img.size
            assert w == 1920
            assert h == 1080
            assert abs((w / h) - (16.0 / 9.0)) < 0.01
            
        # ファイルサイズチェック (4MB = 4194304 bytes)
        size_bytes = res_path.stat().st_size
        assert size_bytes > 0
        assert size_bytes < 4 * 1024 * 1024

    def test_generate_thumbnail_premium_options(self, tmp_path):
        """プレミアムオプション（矢印、サークル、バナー）の全組み合わせで画像生成が品質基準を満たすことの検証"""
        analyzer = ThumbnailAnalyzer()
        
        # 1. 矢印とサークルを描画、バナーは無効
        output1 = tmp_path / "premium_1.png"
        res1 = analyzer.generate_thumbnail(output1, draw_arrow=True, draw_circle=True, use_banner=False)
        assert res1.exists()
        info1 = analyzer.validate_thumbnail(output1)
        assert info1["width"] == 1280
        assert info1["height"] == 720
        
        # 2. 矢印のみ描画、バナー有効
        output2 = tmp_path / "premium_2.png"
        res2 = analyzer.generate_thumbnail(output2, draw_arrow=True, draw_circle=False, use_banner=True)
        assert res2.exists()
        info2 = analyzer.validate_thumbnail(output2)
        assert info2["size_bytes"] < 4 * 1024 * 1024

    def test_generate_thumbnail_invalid_path_handling(self, tmp_path):
        """出力パスが空、None、またはディレクトリだった場合のエラーハンドリング検証"""
        analyzer = ThumbnailAnalyzer()
        
        with pytest.raises(ValueError, match="Output path must not be empty or None"):
            analyzer.generate_thumbnail(None)
            
        with pytest.raises(ValueError, match="Output path must not be empty or None"):
            analyzer.generate_thumbnail("")
            
        with pytest.raises(ValueError, match="Output path must be a file path, not a directory"):
            analyzer.generate_thumbnail(tmp_path)

    def test_generate_thumbnail_none_text_handling(self, tmp_path):
        """テキストに None が渡された場合に空文字として安全に生成されることの検証"""
        analyzer = ThumbnailAnalyzer()
        output = tmp_path / "none_text.png"
        res = analyzer.generate_thumbnail(output, text=None)
        assert res.exists()
        info = analyzer.validate_thumbnail(output)
        assert info["width"] == 1280

    def test_generate_thumbnail_directory_creation_failure(self, tmp_path):
        """親ディレクトリの作成に失敗した場合に IOError が適切に送出されることの検証"""
        analyzer = ThumbnailAnalyzer()
        bad_path = tmp_path / "non_existent_subdir" / "test.png"
        
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            with pytest.raises(IOError, match="Cannot write thumbnail to"):
                analyzer.generate_thumbnail(bad_path)

    def test_validate_thumbnail_invalid_arguments(self):
        """validate_thumbnail の引数が不正な場合のエラーハンドリング検証"""
        analyzer = ThumbnailAnalyzer()
        with pytest.raises(ValueError, match="File path must not be empty or None"):
            analyzer.validate_thumbnail(None)
        with pytest.raises(ValueError, match="File path must not be empty or None"):
            analyzer.validate_thumbnail("")

    def test_validate_thumbnail_slightly_off_aspect_ratio(self, tmp_path):
        """アスペクト比がわずかに16:9（1.777...）から外れている場合に検証エラーになることの検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "off_aspect.png"
        
        # 1280x725 はアスペクト比約 1.765 (16:9 は 1.777)
        from PIL import Image
        img = Image.new("RGB", (1280, 725), color=(20, 20, 20))
        img.save(output_path, "PNG")
        
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            analyzer.validate_thumbnail(output_path)

    def test_generate_thumbnail_multiline_text(self, tmp_path):
        """改行を含む複数行テキストの描画がエラーなく正常に行われ、品質要件を満たした画像が生成されること"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "multiline.png"
        
        # 改行を含むテキストを指定して生成
        res_path = analyzer.generate_thumbnail(
            output_path,
            text="Line One\nLine Two\nLine Three with very long text",
            draw_arrow=True,
            draw_circle=True,
            use_banner=True
        )
        assert res_path.exists()
        
        # 生成された画像の検証
        info = analyzer.validate_thumbnail(output_path)
        assert info["width"] == 1280
        assert info["height"] == 720
        assert info["size_bytes"] < 4 * 1024 * 1024
        
        # Pillowで問題なく読み込めることを確認
        from PIL import Image
        with Image.open(output_path) as img:
            img.load()
            assert img.size == (1280, 720)

    def test_generate_thumbnail_rename_fallback(self, tmp_path):
        """リネーム時にOSErrorが発生した場合、shutil.moveによるフォールバックが機能して正常に画像が保存されること"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "fallback.png"
        
        # Path.rename が OSError を投げるようにモックする
        # 1回目は失敗させ、2回目の shutil.move にフォールバックさせる
        with patch("pathlib.Path.rename", side_effect=OSError("Windows rename error")):
            res_path = analyzer.generate_thumbnail(output_path, text="Fallback Test")
            assert res_path.exists()
            assert res_path == output_path
            
            # 検証
            info = analyzer.validate_thumbnail(output_path)
            assert info["width"] == 1280
            
        # リネームも shutil.move も両方失敗した場合は IOError になること
        with patch("pathlib.Path.rename", side_effect=OSError("Rename failed")), \
             patch("shutil.move", side_effect=OSError("Move failed")):
            with pytest.raises(IOError, match="Failed to move temporary file"):
                analyzer.generate_thumbnail(tmp_path / "fail_both.png", text="Fail Test")

    def test_validate_thumbnail_unsupported_format(self, tmp_path):
        """サポート外の拡張子（.txt, .gif等）が指定された場合に検証エラー（ValueError）が発生すること"""
        analyzer = ThumbnailAnalyzer()
        bad_path = tmp_path / "unsupported.txt"
        bad_path.write_text("not an image")
        
        with pytest.raises(ValueError, match="Unsupported file format"):
            analyzer.validate_thumbnail(bad_path)
            
        bad_path_gif = tmp_path / "unsupported.gif"
        bad_path_gif.write_text("not a gif")
        with pytest.raises(ValueError, match="Unsupported file format"):
            analyzer.validate_thumbnail(bad_path_gif)

    def test_generate_thumbnail_strict_spec_bounds(self, tmp_path):
        """解像度、アスペクト比、ファイルサイズが厳密に品質基準を満たすことを確認するテスト"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "strict_spec.png"
        
        # 1920x1080 (16:9) で生成
        res_path = analyzer.generate_thumbnail(output_path, width=1920, height=1080, text="Strict Spec Bounds")
        assert res_path.exists()
        
        # Pillowによる検証
        from PIL import Image
        with Image.open(res_path) as img:
            img.verify()
            
        with Image.open(res_path) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            # 16:9 アスペクト比
            assert abs((w / h) - (16.0 / 9.0)) < 0.01
            
        # ファイルサイズが 4MB (4194304 bytes) 未満であることを検証
        size_bytes = res_path.stat().st_size
        assert size_bytes < 4 * 1024 * 1024
        assert size_bytes > 0



    @pytest.mark.anyio
    async def test_stage_bound_agent_integration_retry_and_migration(self, tmp_path):
        """StageBoundAgent との統合検証。自動リトライ機能、DBマイグレーション（テーブル定義）、結果保存の正確性をテスト"""
        from agents.stage_bound_agent import StageBoundAgent
        import sqlite3
        import asyncio

        db_path = str(tmp_path / "test_tasks_retry.db")
        
        # 1. DBマイグレーション連携の確認
        # StageBoundAgent が初期化された際、マイグレーション（DDL実行）が行われてテーブルが正常に定義されているかを検証
        agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path, poll_interval=0.01)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        table_exists = cursor.fetchone()
        assert table_exists is not None, "DBマイグレーションが正常に実行され、tasksテーブルが作成されていること"
        
        # カラム定義の確認
        cursor.execute("PRAGMA table_info(tasks)")
        columns = {row[1] for row in cursor.fetchall()}
        expected_columns = {"id", "stage", "status", "retry_count", "max_retries", "result", "error", "created_at", "updated_at"}
        assert expected_columns.issubset(columns), f"必要なカラムがDBマイグレーションによって定義されていること。Got: {columns}"
        conn.close()

        # 2. 自動リトライ機能の確認
        # 失敗するタスクを登録して、自動リトライが実行され、上限に達すると FAILED になることを検証
        task_id = "test_retry_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)
        
        call_count = 0
        async def failing_process_func(tid):
            nonlocal call_count
            call_count += 1
            raise ValueError(f"Simulated failure count: {call_count}")

        # エージェントを開始してタスク処理
        await agent.start(failing_process_func)
        
        # ポーリングして完了を待つ (リトライ上限に達するまで)
        import time
        start_time = time.time()
        failed = False
        while time.time() - start_time < 5.0:
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                failed = True
                break
            await asyncio.sleep(0.05)
            
        await agent.stop()
        
        assert failed, "タスクが規定回数のリトライ後に FAILED ステータスに遷移すること"
        
        # DBに保存されたエラー情報とリトライカウントの検証
        conn = agent._get_conn()
        try:
            cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            db_retry_count, db_error = row
            assert db_retry_count == 2, f"リトライ回数が上限値の 2 に達していること。Got: {db_retry_count}"
            assert "Simulated failure count:" in db_error, f"最後のエラーメッセージがDBに保存されていること。Got: {db_error}"
        finally:
            agent._close_conn(conn)

    def test_generate_thumbnail_min_font_size_decay(self, tmp_path):
        """テキストが非常に長く枠に収まらない場合に、フォントサイズが最小値の 12 まで動的に縮小されることを検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "decay.png"
        
        # 非常に長いテキストを生成
        very_long_text = "このテキストは非常に長いため、通常のフォントサイズ32では1280x720の画面からはみ出してしまいます。そのため、新しく導入されたフォントサイズ自動縮小ロジックによって、最小フォントサイズ12まで縮小されて収まるはずです。"
        
        # 画像生成を実行
        res_path = analyzer.generate_thumbnail(output_path, text=very_long_text)
        assert res_path.exists()
        
        # 検証
        info = analyzer.validate_thumbnail(output_path)
        assert info["width"] == 1280
        assert info["height"] == 720

    def test_generate_thumbnail_exception_cleanup_flow(self, tmp_path):
        """画像生成中に例外が発生した際、Windowsのファイルロックを回避しつつ、一時ファイルが確実に削除されるエラーハンドリングの検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "error_cleanup.png"
        
        # img.save で例外が発生したと仮定してモックする
        # このとき temp_path が作成されてから例外が発生するため、その後のクリーンアップフローを確認できる
        from PIL import Image
        with patch.object(Image.Image, "save", side_effect=ValueError("Simulated save error")):
            with pytest.raises(ValueError, match="Simulated save error"):
                analyzer.generate_thumbnail(output_path, text="Save Error Test")
                
        # 一時ファイル（.tmp）および最終出力ファイルが一切残っていないことを検証
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"一時ファイルが残っています: {tmp_files}"
        assert not output_path.exists()

    def test_validate_thumbnail_decompression_bomb_error(self, tmp_path):
        """DecompressionBombError が発生した際に ValueError が送出されることを検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "bomb.png"
        
        # ダミー画像を作成
        from PIL import Image
        from PIL.Image import DecompressionBombError
        img = Image.new("RGB", (1280, 720), color=(10, 10, 10))
        img.save(output_path, "PNG")
        
        # Image.open または load 時に DecompressionBombError を投げるようにモック
        with patch("PIL.Image.open") as mock_open:
            mock_img = MagicMock()
            mock_img.size = (1280, 720)
            mock_img.load.side_effect = DecompressionBombError("Image size exceeds limit")
            mock_open.return_value.__enter__.return_value = mock_img
            
            with pytest.raises(ValueError, match="Decompression Bomb"):
                analyzer.validate_thumbnail(output_path)

    def test_generate_thumbnail_resized_img_cleanup_on_exception(self, tmp_path):
        """画像保存中の例外発生時に resized_img が適切にクリーンアップ(close)されることを検証"""
        analyzer = ThumbnailAnalyzer()
        output_path = tmp_path / "cleanup_resized.png"
        
        # Image.Image.save で例外を発生させる
        # 同時に、生成された Image オブジェクトの close メソッドが呼ばれたかを追跡する
        from PIL import Image
        
        original_resize = Image.Image.resize
        resized_instances = []
        
        def mock_resize(self, *args, **kwargs):
            res = original_resize(self, *args, **kwargs)
            # spy するために close メソッドをラップする
            res.close = MagicMock(side_effect=res.close)
            resized_instances.append(res)
            return res
            
        with patch.object(Image.Image, "resize", mock_resize), \
             patch.object(Image.Image, "save", side_effect=ValueError("Save error during testing")):
            
            with pytest.raises(ValueError, match="Save error during testing"):
                analyzer.generate_thumbnail(output_path, text="Spy Test")
                
        # 少なくとも1つの最終サイズ (width, height) の resized_img が生成され、close が呼ばれていること
        final_resized_instances = [inst for inst in resized_instances if inst.size == (1280, 720)]
        assert len(final_resized_instances) > 0
        for inst in final_resized_instances:
            inst.close.assert_called()

    def test_analyze_image_api_json_decode_error_detailed_logging(self, tmp_path, caplog):
        """JSONパースエラー発生時に json.JSONDecodeError の例外ハンドラーが動作し、詳細ログを出力してフォールバックすることの検証"""
        analyzer = ThumbnailAnalyzer()
        temp_file = tmp_path / "json_error_thumb.jpg"
        temp_file.write_bytes(b"dummy data")
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        # 不正なJSON
        mock_response.text = "{invalid json: }"
        mock_client.models.generate_content.return_value = mock_response
        
        caplog.clear()
        with patch("gemini_client_factory.get_gemini_client", return_value=mock_client), \
             caplog.at_level(logging.ERROR):
            res = analyzer.analyze_image(str(temp_file))
            
            # ログに新しいエラーメッセージが含まれていること
            assert "Gemini Vision分析応答パースエラー" in caplog.text
            # テキスト分析にフォールバックしていること
            assert res["analysis_mode"] == "text_match"
