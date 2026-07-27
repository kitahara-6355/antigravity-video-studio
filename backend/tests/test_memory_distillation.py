import unittest
from unittest.mock import MagicMock, patch
import os
import json
import shutil
import tempfile
from agents.orchestration.memory_distiller import MemoryDistiller

class TestMemoryDistillation(unittest.TestCase):
    def setUp(self):
        # テスト用のテンポラリディレクトリを作成
        self.test_dir = tempfile.mkdtemp()
        
        # memory_distiller.py の MEMORY_DIR をテスト用のディレクトリにパッチ
        self.dir_patcher = patch("agents.orchestration.memory_distiller.MEMORY_DIR", self.test_dir)
        self.dir_patcher.start()
        
        # Gemini Clientのモック
        self.mock_client = MagicMock()
        self.client_patcher = patch("agents.orchestration.memory_distiller.get_gemini_client", return_value=self.mock_client)
        self.client_patcher.start()
        
        # テスト対象エージェントのダミーSoulデータを作成
        self.agent_name = "DistillTestAgent"
        self.soul_path = os.path.join(self.test_dir, f"{self.agent_name}.json")
        self.initial_soul = {
            "stats": {"debates": 10, "wins": 5, "losses": 5},
            "bias_weight": 0.9,
            "lessons": [
                {"text": "Avoid proposal that caused: excessive red telops", "created_at": 100},
                {"text": "Avoid proposal that caused: redundant explanation", "created_at": 200}
            ],
            "distilled_rules": ["Rule X: Be concise"]
        }
        with open(self.soul_path, "w", encoding="utf-8") as f:
            json.dump(self.initial_soul, f, indent=2, ensure_ascii=False)

    def tearDown(self):
        self.dir_patcher.stop()
        self.client_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_distill_skipped_when_under_threshold(self):
        distiller = MemoryDistiller()
        # 閾値が3（レッスン数は2）なので、force=False ならスキップされるべき
        success = distiller.distill_agent_memory(self.agent_name, force=False, max_lessons=3)
        self.assertFalse(success)
        
        # ファイル内容が変わっていないことを確認
        with open(self.soul_path, "r", encoding="utf-8") as f:
            soul = json.load(f)
        self.assertEqual(len(soul["lessons"]), 2)
        self.assertEqual(len(soul.get("archived_lessons", [])), 0)

    def test_distill_success_when_forced_or_over_threshold(self):
        # LLMレスポンスのモック設定
        mock_response = MagicMock()
        mock_response.text = '["Rule 1: Always limit red telops", "Rule 2: Avoid redundancy in script"]'
        self.mock_client.models.generate_content.return_value = mock_response

        distiller = MemoryDistiller()
        # force=True で強制実行
        success = distiller.distill_agent_memory(self.agent_name, force=True, max_lessons=5)
        self.assertTrue(success)

        # ファイル内容の検証
        with open(self.soul_path, "r", encoding="utf-8") as f:
            soul = json.load(f)

        # アクティブな個別教訓はクリーンアップされる
        self.assertEqual(len(soul["lessons"]), 0)
        
        # アーカイブに過去の教訓が退避されていること
        self.assertEqual(len(soul["archived_lessons"]), 2)
        self.assertEqual(soul["archived_lessons"][0]["text"], "Avoid proposal that caused: excessive red telops")
        
        # 新しいルールが蒸留ルールに追加されていること
        self.assertIn("Rule 1: Always limit red telops", soul["distilled_rules"])
        self.assertIn("Rule 2: Avoid redundancy in script", soul["distilled_rules"])
        self.assertIn("Rule X: Be concise", soul["distilled_rules"]) # 既存のルールもマージされて残る
        self.assertEqual(len(soul["distilled_rules"]), 3)

    def test_distill_success_case_insensitive(self):
        """エージェント名の大文字小文字表記揺れ（クロスプラットフォーム対策）の検証"""
        mock_response = MagicMock()
        mock_response.text = '["Rule 1: Limit red telops"]'
        self.mock_client.models.generate_content.return_value = mock_response

        distiller = MemoryDistiller()
        # 小文字でエージェント名を渡す
        lowercase_agent_name = self.agent_name.lower()
        success = distiller.distill_agent_memory(lowercase_agent_name, force=True, max_lessons=5)
        self.assertTrue(success)

        # 正規化されたファイル名（DistillTestAgent.json）が正しく更新されているか確認
        with open(self.soul_path, "r", encoding="utf-8") as f:
            soul = json.load(f)

        self.assertEqual(len(soul["lessons"]), 0)
        self.assertIn("Rule 1: Limit red telops", soul["distilled_rules"])

    def test_distill_skipped_when_client_is_none(self):
        """Geminiクライアントが None（Stubモード等）の場合にエラーを出さずに早期リターンすることの検証"""
        # get_gemini_client が None を返すようにパッチを一時的に変更
        with patch("agents.orchestration.memory_distiller.get_gemini_client", return_value=None):
            distiller = MemoryDistiller()
            self.assertIsNone(distiller.client)
            
            # 警告ログの補足
            with self.assertLogs("agents.orchestration.memory_distiller", level="WARNING") as log:
                success = distiller.distill_agent_memory(self.agent_name, force=True, max_lessons=5)
                self.assertFalse(success)
                self.assertTrue(any(
                    "Gemini client is not initialized" in message for message in log.output
                ))

    def test_distill_fails_on_api_error(self):
        """APIErrorまたはGoogleAPIErrorが発生した際に、正常にキャッチされてFalseが返されることの検証"""
        from google.api_core.exceptions import GoogleAPIError
        self.mock_client.models.generate_content.side_effect = GoogleAPIError("API limit exceeded")

        distiller = MemoryDistiller()
        with self.assertLogs("agents.orchestration.memory_distiller", level="ERROR") as log:
            success = distiller.distill_agent_memory(self.agent_name, force=True, max_lessons=5)
            self.assertFalse(success)
            self.assertTrue(any(
                "API or import error during distillation" in message for message in log.output
            ))

if __name__ == "__main__":
    unittest.main()
