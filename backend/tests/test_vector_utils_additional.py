import unittest
from unittest.mock import MagicMock, patch
from agents.vector_utils import get_embedding, cosine_similarity, _is_valid_numeric_list
from google.genai.errors import APIError

class TestVectorUtilsAdditional(unittest.TestCase):
    def test_get_embedding_client_none(self):
        res = get_embedding(None, "hello")
        self.assertEqual(res, [])

    def test_get_embedding_empty_text(self):
        res = get_embedding(MagicMock(), "")
        self.assertEqual(res, [])

    def test_get_embedding_api_error(self):
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = APIError(
            code=500, response_json={"error": "API Error occurred"}
        )
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

    def test_get_embedding_other_exceptions(self):
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = TypeError("invalid type")
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

        mock_client.models.embed_content.side_effect = AttributeError("no attribute")
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

        mock_client.models.embed_content.side_effect = ValueError("invalid value")
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [])

    def test_cosine_similarity_non_list(self):
        res = cosine_similarity("not a list", [1.0])
        self.assertEqual(res, 0.0)

        res = cosine_similarity([1.0], "not a list")
        self.assertEqual(res, 0.0)

    def test_cosine_similarity_dimension_mismatch(self):
        res = cosine_similarity([1.0], [1.0, 2.0])
        self.assertEqual(res, 0.0)

    def test_cosine_similarity_zero_norm(self):
        res = cosine_similarity([0.0, 0.0], [1.0, 1.0])
        self.assertEqual(res, 0.0)

    def test_cosine_similarity_exceptions(self):
        res = cosine_similarity([1.0, "invalid"], [1.0, 2.0])
        self.assertEqual(res, 0.0)

        # Lines 58-60: TypeError/ValueError exception handling
        class BadList(list):
            def __iter__(self):
                raise TypeError("Bad iterator")
        
        bad_v1 = BadList([1.0])
        res_exception = cosine_similarity(bad_v1, [1.0])
        self.assertEqual(res_exception, 0.0)

    @patch("agents.vector_utils.math.sqrt")
    def test_cosine_similarity_underflow(self, mock_sqrt):
        # Line 55: prod == 0.0 (underflow) by patching math.sqrt to return extremely small non-zero floats
        mock_sqrt.side_effect = [1e-200, 1e-200]
        res_underflow = cosine_similarity([1.0], [1.0])
        self.assertEqual(res_underflow, 0.0)

    def test_get_embedding_success(self):
        # Line 20-21: Success path returning embedding.values
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embedding.values = [0.1, 0.2, 0.3]
        mock_client.models.embed_content.return_value = mock_response
        
        res = get_embedding(mock_client, "hello")
        self.assertEqual(res, [0.1, 0.2, 0.3])

    def test_cosine_similarity_v2_invalid_values(self):
        # Line 43: Invalid/NaN/Inf values in v2
        import math
        res_str = cosine_similarity([1.0], ["invalid"])
        self.assertEqual(res_str, 0.0)

        res_nan = cosine_similarity([1.0], [float("nan")])
        self.assertEqual(res_nan, 0.0)

        res_inf = cosine_similarity([1.0], [float("inf")])
        self.assertEqual(res_inf, 0.0)

    def test_cosine_similarity_success(self):
        # Line 57: Success path of cosine similarity calculation
        # Identical vectors (similarity should be 1.0)
        res_ident = cosine_similarity([1.0, 2.0], [1.0, 2.0])
        self.assertAlmostEqual(res_ident, 1.0, places=6)

        # Orthogonal vectors (similarity should be 0.0)
        res_ortho = cosine_similarity([1.0, 0.0], [0.0, 1.0])
        self.assertAlmostEqual(res_ortho, 0.0, places=6)

        # Opposite vectors (similarity should be -1.0)
        res_opp = cosine_similarity([1.0, 0.0], [-1.0, 0.0])
        self.assertAlmostEqual(res_opp, -1.0, places=6)

    def test_cosine_similarity_empty_list(self):
        # カバー向上のための空リストテスト
        res = cosine_similarity([], [])
        self.assertEqual(res, 0.0)

    def test_is_valid_numeric_list_non_list_direct(self):
        # _is_valid_numeric_list に直接非リストを渡してカバー率を100%にする
        self.assertFalse(_is_valid_numeric_list("not a list"))
        self.assertFalse(_is_valid_numeric_list(None))

    def test_is_valid_numeric_list_with_bool(self):
        # boolが含まれる場合はFalseを返すこと
        self.assertFalse(_is_valid_numeric_list([1.0, True, 2.0]))
        self.assertFalse(_is_valid_numeric_list([False, 1.0]))

    def test_get_embedding_invalid_response_structure(self):
        mock_client = MagicMock()
        # response が None
        mock_client.models.embed_content.return_value = None
        self.assertEqual(get_embedding(mock_client, "hello"), [])

        # response.embedding が None
        mock_response = MagicMock()
        mock_response.embedding = None
        mock_client.models.embed_content.return_value = mock_response
        self.assertEqual(get_embedding(mock_client, "hello"), [])

        # response.embedding.values が None
        mock_response2 = MagicMock()
        mock_response2.embedding.values = None
        mock_client.models.embed_content.return_value = mock_response2
        self.assertEqual(get_embedding(mock_client, "hello"), [])

    def test_get_embedding_httpx_http_error(self):
        import httpx
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = httpx.HTTPError("Network timeout")
        self.assertEqual(get_embedding(mock_client, "hello"), [])

    def test_get_embedding_runtime_error(self):
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("SDK Error")
        self.assertEqual(get_embedding(mock_client, "hello"), [])

    def test_cosine_similarity_overflow_error(self):
        with patch("agents.vector_utils.math.sqrt", side_effect=OverflowError("overflow")):
            res = cosine_similarity([1.0, 2.0], [1.0, 2.0])
            self.assertEqual(res, 0.0)

    def test_cosine_similarity_zero_division_error(self):
        with patch("agents.vector_utils.sum", side_effect=ZeroDivisionError("zero division")):
            res = cosine_similarity([1.0, 2.0], [1.0, 2.0])
            self.assertEqual(res, 0.0)

    def test_cosine_similarity_overflow_large_values(self):
        # 極端に大きい値（1e200）を持つ同一ベクトルの類似度が 1.0 になることを検証
        v = [1e200, 1e200]
        res = cosine_similarity(v, v)
        self.assertAlmostEqual(res, 1.0, places=6)

    def test_cosine_similarity_underflow_small_values(self):
        # 極端に小さい値（1e-200）を持つ同一ベクトルの類似度が 1.0 になることを検証
        v = [1e-200, 1e-200]
        res = cosine_similarity(v, v)
        self.assertAlmostEqual(res, 1.0, places=6)

    def test_cosine_similarity_clipping_bounds(self):
        # 丸め誤差等で計算結果が1.0を超える場合に、1.0にクリップされることを検証
        with patch("agents.vector_utils.sum", side_effect=[1.0000000000000002, 1.0, 1.0]):
            res = cosine_similarity([1.0], [1.0])
            self.assertEqual(res, 1.0)

    @patch("agents.vector_utils.math.sqrt")
    def test_cosine_similarity_mock_zero_norm(self, mock_sqrt):
        # math.sqrtが0.0を返す場合のゼロノルムチェックを検証
        mock_sqrt.return_value = 0.0
        res = cosine_similarity([1.0], [1.0])
        self.assertEqual(res, 0.0)

    def test_is_valid_numeric_list_attribute_error(self):
        class AttributeErrorList(list):
            def __iter__(self):
                raise AttributeError("mock attribute error")
        self.assertFalse(_is_valid_numeric_list(AttributeErrorList([1.0])))

    def test_is_valid_numeric_list_value_error(self):
        class ValueErrorList(list):
            def __iter__(self):
                raise ValueError("mock value error")
        self.assertFalse(_is_valid_numeric_list(ValueErrorList([1.0])))

    def test_get_embedding_key_error(self):
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = KeyError("mock key error")
        self.assertEqual(get_embedding(mock_client, "hello"), [])

    def test_get_embedding_index_error(self):
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = IndexError("mock index error")
        self.assertEqual(get_embedding(mock_client, "hello"), [])

    def test_cosine_similarity_arithmetic_error(self):
        with patch("agents.vector_utils.math.sqrt", side_effect=ArithmeticError("mock arithmetic error")):
            res = cosine_similarity([1.0, 2.0], [1.0, 2.0])
            self.assertEqual(res, 0.0)

    def test_cosine_similarity_high_dimensional(self):
        v1 = [0.1] * 1536
        v2 = [0.1] * 1536
        res = cosine_similarity(v1, v2)
        self.assertAlmostEqual(res, 1.0, places=6)

        v3 = [-0.1] * 1536
        res_opp = cosine_similarity(v1, v3)
        self.assertAlmostEqual(res_opp, -1.0, places=6)

    def test_get_embedding_custom_model(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.embedding.values = [0.5, 0.6]
        mock_client.models.embed_content.return_value = mock_response

        res = get_embedding(mock_client, "hello", model="custom-model-123")
        self.assertEqual(res, [0.5, 0.6])
        mock_client.models.embed_content.assert_called_once_with(
            model="custom-model-123",
            contents="hello"
        )

    def test_cosine_similarity_clipping_bounds_lower(self):
        with patch("agents.vector_utils.sum", side_effect=[-1.0000000000000002, 1.0, 1.0]):
            res = cosine_similarity([1.0], [1.0])
            self.assertEqual(res, -1.0)

    def test_is_valid_numeric_list_empty_direct(self):
        self.assertFalse(_is_valid_numeric_list([]))

    def test_cosine_similarity_mixed_types(self):
        res = cosine_similarity([1, 2.0], [1.0, 2])
        self.assertAlmostEqual(res, 1.0, places=6)

    def test_is_valid_numeric_list_overflow_error(self):
        # 巨大な整数を渡した場合に math.isnan/isinf で発生する OverflowError のハンドリング検証
        large_int = 10**1000
        self.assertFalse(_is_valid_numeric_list([large_int]))

    def test_cosine_similarity_with_large_int_overflow(self):
        # 巨大な整数が含まれるベクトルに対してコサイン類似度がクラッシュせずに 0.0 を返すことを検証
        large_int = 10**1000
        res = cosine_similarity([large_int], [1.0])
        self.assertEqual(res, 0.0)
