import unittest
from unittest.mock import MagicMock, patch
import os
import json
import shutil
import tempfile
from agents.agent_base import Agent
from agents.vector_utils import cosine_similarity, get_embedding

class DummyAgent(Agent):
    def process(self, input_data: dict, context: dict, council_context=None) -> dict:
        return {}

class TestAgentMemoryRAG(unittest.TestCase):
    def setUp(self):
        # テスト用のテンポラリディレクトリを作成
        self.test_dir = tempfile.mkdtemp()
        
        # Agentクラスのmemory_dirをテスト用に差し替えるパッチを適用
        self.dir_patcher = patch("agents.agent_base.os.path.dirname")
        mock_dirname = self.dir_patcher.start()
        # memory_dirが self.test_dir/memory になるようにモック
        mock_dirname.return_value = self.test_dir
        
        # Gemini Client of Mock
        self.mock_client = MagicMock()
        self.client_patcher = patch("agents.agent_base.get_gemini_client", return_value=self.mock_client)
        self.client_patcher.start()

    def tearDown(self):
        self.dir_patcher.stop()
        self.client_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_cosine_similarity(self):
        # 完全一致
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0)
        
        # 直交（類似度 0）
        v3 = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0)
        
        # 逆向き（類似度 -1）
        v4 = [-1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(v1, v4), -1.0)
        
        # 空ベクトルまたは次元不一致
        self.assertEqual(cosine_similarity([], v1), 0.0)
        self.assertEqual(cosine_similarity(v1, [1.0, 0.0]), 0.0)

    def test_agent_recall_with_rag(self):
        # Agentインスタンスの生成
        agent = DummyAgent("TestDistill", "Tester")
        
        # モックのEmbedding返却値の設定
        # embed_contentの戻り値を設定
        mock_resp_query = MagicMock()
        mock_resp_query.embedding.values = [1.0, 0.0, 0.0]  # クエリのベクトル
        
        mock_resp_l1 = MagicMock()
        mock_resp_l1.embedding.values = [0.9, 0.1, 0.0]  # 類似度の高いレッスン1
        
        mock_resp_l2 = MagicMock()
        mock_resp_l2.embedding.values = [0.1, 0.9, 0.0]  # 類似度の低いレッスン2
        
        # client.models.embed_contentの呼び出しごとに異なる値を返す
        self.mock_client.models.embed_content.side_effect = [
            mock_resp_query, # recallクエリ用
            mock_resp_l1,    # オンデマンド生成用 l1
            mock_resp_l2     # オンデマンド生成用 l2
        ]
        
        # テストデータの投入
        agent.soul["lessons"] = [
            {"text": "Avoid proposal that caused: high contrast style", "created_at": 1000, "weight": 1.0},
            {"text": "Avoid proposal that caused: excessive sound effects", "created_at": 2000, "weight": 1.0}
        ]
        agent.soul["distilled_rules"] = [
            "Rule A: Always verify contrast before applying"
        ]
        agent._save_soul()
        
        # recall実行
        # クエリに対して類似度が高いレッスンが優先して取得されるか検証
        results = agent.recall("contrast", top_k=1)
        
        # 結果には distilled_rules (Rule A) と、類似レッスン（l1: contrastの方）が含まれているはず
        self.assertIn("Rule A: Always verify contrast before applying", results)
        self.assertIn("Avoid proposal that caused: high contrast style", results)
        self.assertNotIn("Avoid proposal that caused: excessive sound effects", results)
        self.assertEqual(len(results), 2)  # Rule 1つ + Lesson 1つ

    def test_get_embedding_client_none(self):
        # clientがNoneの場合
        res = get_embedding(None, "hello")
        self.assertEqual(res, [])

    def test_get_embedding_api_error(self):
        from google.genai.errors import APIError
        # APIErrorをスローするモック
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = APIError(code=500, response_json={"error": "API Error occurred"})
        
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

    def test_get_embedding_attribute_error(self):
        # AttributeErrorが発生するような不正なclient
        mock_client = MagicMock()
        del mock_client.models
        
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

    def test_cosine_similarity_robustness(self):
        # リストでない入力
        self.assertEqual(cosine_similarity("not a list", [1.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0], "not a list"), 0.0)
        
        # 非数値要素（文字列など）
        self.assertEqual(cosine_similarity([1.0, "str"], [1.0, 1.0]), 0.0)
        
        # NaN や Inf が含まれる場合
        self.assertEqual(cosine_similarity([1.0, float('nan')], [1.0, 1.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0, 1.0], [1.0, float('inf')]), 0.0)
        
        # 極小値（アンダーフロー付近）の計算
        self.assertAlmostEqual(cosine_similarity([2.225e-162], [2.225e-162]), 1.0)

if __name__ == "__main__":
    unittest.main()
