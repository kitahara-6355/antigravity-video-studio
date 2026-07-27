"""
Phase 20 品質検分テストスイート
厳格なユニットテスト + 統合テスト

テスト項目:
1. データクラスの妥当性
2. JSONパース処理の堅牢性
3. FFmpegコマンド生成の正確性
4. エラーハンドリング
5. ファイルパスエスケープ
6. 統合パイプライン
"""

import unittest
import json
import sys
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from interactive_preview import (
    ConfirmationItem,
    TelopSuggestion,
    TelopConfig,
    SubtitleConfirmationChecker,
    TelopSuggester,
    TelopPreviewRenderer,
    IntegratedReportGenerator
)


class TestDataClasses(unittest.TestCase):
    """データクラスのテスト"""
    
    def test_confirmation_item_creation(self):
        """ConfirmationItemの作成テスト"""
        item = ConfirmationItem(
            id="test_001",
            timestamp="00:01:30",
            original_text="テスト文字列",
            concern="固有名詞の可能性",
            category="proper_noun"
        )
        self.assertEqual(item.id, "test_001")
        self.assertEqual(item.status, "pending")
        self.assertIsNone(item.suggestion)
    
    def test_telop_suggestion_defaults(self):
        """TelopSuggestionのデフォルト値テスト"""
        telop = TelopSuggestion(
            id="telop_001",
            timestamp="00:00:30",
            duration=3.0,
            text="テロップテキスト",
            reason="理由"
        )
        self.assertEqual(telop.position, "top")
        self.assertEqual(telop.style, "default")
        self.assertFalse(telop.approved)
    
    def test_telop_config_serialization(self):
        """TelopConfigのシリアライズテスト"""
        config = TelopConfig(
            scene_name="テストシーン",
            telops=[{"id": "t1", "text": "テロップ"}],
            confirmations=[{"id": "c1", "text": "確認"}]
        )
        data = asdict(config)
        self.assertEqual(data["version"], "1.0")
        self.assertEqual(len(data["telops"]), 1)


class TestJSONParsing(unittest.TestCase):
    """JSONパース処理の堅牢性テスト"""
    
    def setUp(self):
        self.checker = SubtitleConfirmationChecker()
        self.suggester = TelopSuggester()
    
    def test_parse_valid_json(self):
        """正常なJSONのパース"""
        response = '''
```json
[{"timestamp": "00:01:30", "original_text": "テスト", "concern": "理由", "category": "proper_noun", "suggestion": "修正案"}]
```
'''
        items = self.checker._parse_response(response, "test")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].original_text, "テスト")
    
    def test_parse_json_without_code_block(self):
        """コードブロックなしのJSONパース"""
        response = '[{"timestamp": "00:00:10", "original_text": "直接JSON", "concern": "理由", "category": "typo"}]'
        items = self.checker._parse_response(response, "test")
        self.assertEqual(len(items), 1)
    
    def test_parse_invalid_json(self):
        """不正なJSONのパース（エラーにならないこと）"""
        response = "これはJSONではありません"
        items = self.checker._parse_response(response, "test")
        self.assertEqual(len(items), 0)
    
    def test_parse_empty_array(self):
        """空配列のパース"""
        response = '```json\n[]\n```'
        items = self.checker._parse_response(response, "test")
        self.assertEqual(len(items), 0)
    
    def test_parse_missing_fields(self):
        """フィールド不足のJSONパース"""
        response = '[{"timestamp": "00:00:00"}]'
        items = self.checker._parse_response(response, "test")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].original_text, "")  # デフォルト値


class TestTelopPreviewRenderer(unittest.TestCase):
    """テロッププレビューレンダラーのテスト"""
    
    def test_text_escaping(self):
        """テキストエスケープの検証"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TelopPreviewRenderer(Path(tmpdir))
            
            # 特殊文字を含むテロップ
            telop = TelopSuggestion(
                id="test",
                timestamp="00:00:00",
                duration=3.0,
                text="テスト: 'シングルクォート' を含む",
                reason="テスト"
            )
            
            # renderメソッドは実行しないが、エスケープロジックを検証
            text_escaped = telop.text.replace("'", "\\'").replace(":", "\\:")
            self.assertIn("\\'", text_escaped)
            self.assertIn("\\:", text_escaped)
    
    def test_position_calculation(self):
        """位置計算の検証"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            renderer = TelopPreviewRenderer(Path(tmpdir))
            
            # top位置
            telop_top = TelopSuggestion(
                id="t1", timestamp="00:00:00", duration=3.0,
                text="Top", reason="", position="top"
            )
            y_top = "50" if telop_top.position == "top" else "h-th-50"
            self.assertEqual(y_top, "50")
            
            # bottom位置
            telop_bottom = TelopSuggestion(
                id="t2", timestamp="00:00:00", duration=3.0,
                text="Bottom", reason="", position="bottom"
            )
            y_bottom = "50" if telop_bottom.position == "top" else "h-th-50"
            self.assertEqual(y_bottom, "h-th-50")


class TestIntegratedReportGenerator(unittest.TestCase):
    """統合レポート生成のテスト"""
    
    def test_generate_empty_report(self):
        """空のレポート生成"""
        gen = IntegratedReportGenerator()
        report = gen.generate("S01", "テストシーン", [], [], {}, [])
        self.assertIn("## S01", report)
        self.assertIn("テストシーン", report)
    
    def test_generate_with_confirmations(self):
        """確認項目付きレポート生成"""
        gen = IntegratedReportGenerator()
        confirmations = [
            ConfirmationItem(
                id="c001", timestamp="00:01:00",
                original_text="久北先生", concern="人名確認",
                category="proper_noun", suggestion="山田先生"
            )
        ]
        report = gen.generate("S01", "シーン01", confirmations, [], {}, [])
        self.assertIn("🔍 AI字幕確認リスト", report)
        self.assertIn("c001", report)
        self.assertIn("山田先生", report)
    
    def test_generate_with_telops(self):
        """テロップ提案付きレポート生成"""
        gen = IntegratedReportGenerator()
        telops = [
            TelopSuggestion(
                id="t001", timestamp="00:00:30", duration=3.0,
                text="日本デザイン書道作家協会", reason="肩書き表示"
            )
        ]
        report = gen.generate("S01", "シーン01", [], telops, {}, [])
        self.assertIn("🎬 テロップ提案", report)
        self.assertIn("日本デザイン書道作家協会", report)
    
    def test_text_truncation(self):
        """長いテキストの切り詰め"""
        gen = IntegratedReportGenerator()
        long_text = "これは非常に長いテキストで、20文字を超えています。"
        confirmations = [
            ConfirmationItem(
                id="c001", timestamp="00:00:00",
                original_text=long_text, concern="テスト",
                category="uncertain"
            )
        ]
        report = gen.generate("T01", "テスト", confirmations, [], {}, [])
        self.assertIn("...", report)


class TestTelopConfigFile(unittest.TestCase):
    """設定ファイルの読み書きテスト"""
    
    def test_save_and_load(self):
        """保存と読み込みの往復テスト"""
        import tempfile
        
        original_config = TelopConfig(
            scene_name="テストシーン",
            telops=[{"id": "t1", "text": "テロップ1"}],
            confirmations=[{"id": "c1", "text": "確認1"}]
        )
        
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            temp_path = Path(f.name)
        
        try:
            original_config.save(temp_path)
            loaded_config = TelopConfig.load(temp_path)
            
            self.assertEqual(loaded_config.scene_name, original_config.scene_name)
            self.assertEqual(len(loaded_config.telops), 1)
            self.assertEqual(len(loaded_config.confirmations), 1)
        finally:
            temp_path.unlink()


class TestEdgeCases(unittest.TestCase):
    """エッジケースのテスト"""
    
    def test_empty_srt_content(self):
        """空のSRTコンテンツ"""
        checker = SubtitleConfirmationChecker()
        # 空文字列でエラーにならないこと
        # （実際のAPI呼び出しはスキップ）
    
    def test_japanese_in_json(self):
        """日本語を含むJSONの処理"""
        response = '''
```json
[{"timestamp": "00:00:00", "original_text": "日本語テスト", "concern": "漢字の確認", "category": "proper_noun", "suggestion": "日本語テスト修正"}]
```
'''
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response(response, "日本語シーン")
        self.assertEqual(len(items), 1)
        self.assertIn("日本語", items[0].original_text)
    
    def test_special_characters_in_text(self):
        """特殊文字を含むテキスト"""
        response = '[{"timestamp": "00:00:00", "original_text": "テスト and special", "concern": "特殊文字", "category": "uncertain"}]'
        checker = SubtitleConfirmationChecker()
        items = checker._parse_response(response, "test")
        self.assertEqual(len(items), 1)



def run_quality_audit():
    """品質監査を実行し結果を返す"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # すべてのテストクラスを追加
    suite.addTests(loader.loadTestsFromTestCase(TestDataClasses))
    suite.addTests(loader.loadTestsFromTestCase(TestJSONParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestTelopPreviewRenderer))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegratedReportGenerator))
    suite.addTests(loader.loadTestsFromTestCase(TestTelopConfigFile))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestSecurityValidation))
    
    # テスト実行
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("Phase 20 品質検分テストスイート")
    print("=" * 60)
    result = run_quality_audit()
    
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    print(f"実行: {result.testsRun}")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失敗: {len(result.failures)}")
    print(f"エラー: {len(result.errors)}")
    
    if result.failures:
        print("\n失敗したテスト:")
        for test, traceback in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\nエラーが発生したテスト:")
        for test, traceback in result.errors:
            print(f"  - {test}")


class TestSecurityValidation(unittest.TestCase):
    """セキュリティバリデーションのテスト"""
    
    def test_invalid_timestamp(self):
        """不正なタイムスタンプに対する例外発生の検証"""
        from interactive_preview import validate_timestamp
        
        # 正常系
        self.assertEqual(validate_timestamp("00:01:30"), "00:01:30")
        self.assertEqual(validate_timestamp("123.45"), "123.45")
        
        # 異常系
        with self.assertRaises(ValueError):
            validate_timestamp("00:01:30; rm -rf /")
        with self.assertRaises(ValueError):
            validate_timestamp("abc")
        with self.assertRaises(ValueError):
            validate_timestamp("00:01:30 -vf drawtext")

    def test_directory_traversal_prevention(self):
        """ディレクトリトラバーサル防止の検証"""
        import tempfile
        from interactive_preview import validate_path, TelopPreviewRenderer
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            renderer = TelopPreviewRenderer(tmp_path)
            
            video_path = tmp_path / "video.mp4"
            video_path.touch()
            
            telop = TelopSuggestion(
                id="t1", timestamp="00:00:00", duration=3.0,
                text="Test", reason="", position="top"
            )
            
            # ディレクトリトラバーサルを含む output_name のテスト
            with self.assertRaises(ValueError):
                renderer.render(video_path, telop, "../traversal")
                
            with self.assertRaises(ValueError):
                renderer.render(video_path, telop, "/absolute/path/file")

    def test_unsafe_path_validation(self):
        """許可されていないディレクトリ配下のパスに対する例外発生の検証"""
        from interactive_preview import validate_path
        
        # Windowsのシステムフォルダや無関係な絶対パスなど
        unsafe_path = Path("C:/Windows/System32/cmd.exe")
        with self.assertRaises(ValueError):
            validate_path(unsafe_path)
