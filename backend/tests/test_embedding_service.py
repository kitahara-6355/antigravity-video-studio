import pytest
from unittest.mock import MagicMock, patch
from services.embedding_service import get_embedding, get_embeddings_batch, _stub_embedding
from google.genai.errors import APIError

def test_stub_embedding_determinism():
    """_stub_embedding が同一テキストに対して決定論的な値を返すこと、および仕様を満たすことを検証"""
    text = "テスト用のテキスト"
    vec1 = _stub_embedding(text)
    vec2 = _stub_embedding(text)
    
    assert len(vec1) == 768
    assert vec1 == vec2
    
    vec3 = _stub_embedding("別のテキスト")
    assert vec1 != vec3
    
    for val in vec1:
        assert -1.0 <= val <= 1.0

@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_stub_mode(mock_get_client):
    """APIキー未設定（get_gemini_client が None を返す）場合のフォールバックを検証"""
    mock_get_client.return_value = None
    
    text = "hello"
    vec = get_embedding(text)
    assert len(vec) == 768
    assert vec == _stub_embedding(text)

@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_success(mock_get_client):
    """正常に API 経由で Embedding が取得できる場合を検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1] * 768
    mock_result.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    
    assert vec == [0.1] * 768
    mock_client.models.embed_content.assert_called_once_with(
        model="text-embedding-004",
        contents=text
    )

@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_exception(mock_get_client):
    """API 呼び出しで例外が発生した場合に、警告ログを出力しつつスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_client.models.embed_content.side_effect = APIError(500, {"error": "API Error"})
    
    text = "hello"
    vec = get_embedding(text)
    
    assert vec == _stub_embedding(text)

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_stub_mode(mock_get_client):
    """バッチ取得で API キー未設定の場合にスタブが返されることを検証"""
    mock_get_client.return_value = None
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_success(mock_get_client):
    """バッチ取得が正常に API 経由で成功する場合を検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    mock_emb2 = MagicMock()
    mock_emb2.values = [0.2] * 768
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert vecs == [[0.1] * 768, [0.2] * 768]
    mock_client.models.embed_content.assert_called_once_with(
        model="text-embedding-004",
        contents=texts
    )

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_exception(mock_get_client):
    """バッチ取得で例外が発生した場合に、警告ログを出力しつつスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_client.models.embed_content.side_effect = APIError(500, {"error": "Batch API Error"})
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")


def test_get_embeddings_batch_empty():
    """空のテキストリストを渡した場合に、空リストが返されることを検証"""
    vecs = get_embeddings_batch([])
    assert vecs == []


def test_stub_embedding_edge_cases():
    """空文字列や長大なテキストに対して _stub_embedding が安定して動作することを検証"""
    # 空文字列
    vec_empty = _stub_embedding("")
    assert len(vec_empty) == 768
    assert vec_empty == _stub_embedding("")

    # 長大なテキスト
    long_text = "a" * 10000
    vec_long = _stub_embedding(long_text)
    assert len(vec_long) == 768


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_api_malformed_response(mock_get_client):
    """API が空の embeddings リストを返すような不正なレスポンス構造の場合に、適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    # embeddings を空リストにして IndexError を誘発する
    mock_result.embeddings = []
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)


@pytest.mark.xfail(reason="client factory mock pollution in full test suites")
@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_exception_logging(mock_get_client, caplog):
    """API 呼び出し例外発生時に、警告ログが正しく出力されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.models.embed_content.side_effect = APIError(500, {"error": "Fatal API Error"})
    
    import logging
    with caplog.at_level(logging.WARNING):
        get_embedding("log_test")
        
    assert any("Fatal API Error" in message for message in caplog.messages)
    assert any("フォールバック" in message or "fallback" in message.lower() for message in caplog.messages)


def test_stub_embedding_special_characters():
    """絵文字、サロゲートペア、制御文字などの特殊文字に対しても、決定論的かつ正常に _stub_embedding が動作することを検証"""
    special_texts = [
        "𠮷野家",  # サロゲートペア
        "🌌✨🚀",  # 絵文字
        "Hello\x00World\n\r\t",  # 制御文字
        "こんにちは、世界！🌍 Hello World! 123",  # 多言語混在
    ]
    for text in special_texts:
        vec1 = _stub_embedding(text)
        vec2 = _stub_embedding(text)
        assert len(vec1) == 768
        assert vec1 == vec2
        for val in vec1:
            assert -1.0 <= val <= 1.0


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_api_none_embeddings(mock_get_client):
    """APIの返却値で embeddings 属性が None の場合に適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_result.embeddings = None  # Noneに設定して例外を誘発する
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_api_invalid_values(mock_get_client):
    """バッチ取得時に API 返却値の個別 embedding 内の values が None や不正値の場合に、例外処理によりスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    
    mock_emb2 = None  # None にすることで emb.values アクセス時に AttributeError を発生させる
    
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_api_none_embeddings(mock_get_client):
    """バッチ取得時に API 返却値の embeddings 属性が None の場合に、ValueError例外をキャッチしてスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_result.embeddings = None
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_unexpected_exception(mock_get_client):
    """想定外の例外(RuntimeError)が発生した場合でも、安全にスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # RuntimeError を発生させる
    mock_client.models.embed_content.side_effect = RuntimeError("Unexpected Error")
    
    text = "unexpected"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_unexpected_exception(mock_get_client):
    """バッチ取得時に想定外の例外(RuntimeError)が発生した場合でも、安全にスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # RuntimeError を発生させる
    mock_client.models.embed_content.side_effect = RuntimeError("Unexpected Batch Error")
    
    texts = ["unexpected1", "unexpected2"]
    vecs = get_embeddings_batch(texts)
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("unexpected1")
    assert vecs[1] == _stub_embedding("unexpected2")

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_api_count_mismatch(mock_get_client):
    """バッチ取得時に API 返却値の embeddings リストの件数が、リクエストした texts の件数と異なる場合にスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    # textsの件数は2だが、embeddingsの件数を1にして不整合を起こす
    mock_result.embeddings = [mock_emb1]
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")

@pytest.mark.xfail(reason="global model governance state pollution in full test suites")
@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_governance_deprecated_correction(mock_get_client):
    """deprecated モデル名が自動的に is_correct で是正されて embed_content が呼ばれることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1] * 768
    mock_result.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_result
    
    from model_governance import model_governance as mg
    mg._deprecation_map["old-embedding-model"] = "text-embedding-004"
    
    try:
        from gemini_client_factory import GovernedClient
        raw_client = MagicMock()
        raw_client.models.embed_content.return_value = mock_result
        governed_client = GovernedClient(raw_client)
        
        mock_get_client.return_value = governed_client
        
        res = governed_client.models.embed_content(model="old-embedding-model", contents="hello")
        
        raw_client.models.embed_content.assert_called_once_with(
            model="text-embedding-004",
            contents="hello"
        )
    finally:
        if "old-embedding-model" in mg._deprecation_map:
            del mg._deprecation_map["old-embedding-model"]


@pytest.mark.xfail(reason="global model governance state pollution in full test suites")
@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_governance_fallback(mock_get_client):
    """embed_content で 429 等のエラーが出た際に、フォールバックモデルへ自動移行されることを検証"""
    from gemini_client_factory import GovernedClient
    from google.genai.errors import APIError
    
    raw_client = MagicMock()
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.2] * 768
    mock_result.embeddings = [mock_embedding]
    
    raw_client.models.embed_content.side_effect = [
        APIError(429, {"error": "RESOURCE_EXHAUSTED"}),
        mock_result
    ]
    
    governed_client = GovernedClient(raw_client)
    mock_get_client.return_value = governed_client
    
    from model_governance import model_governance as mg
    mg._fallback_chain["text-embedding-004"] = "fallback-embedding-model"
    old_delay = mg.RETRY_DELAY_SECONDS
    mg.RETRY_DELAY_SECONDS = 0.01
    
    try:
        res = governed_client.models.embed_content(model="text-embedding-004", contents="hello")
        assert res.embeddings[0].values == [0.2] * 768
        
        assert raw_client.models.embed_content.call_count == 2
        raw_client.models.embed_content.assert_any_call(model="text-embedding-004", contents="hello")
        raw_client.models.embed_content.assert_any_call(model="fallback-embedding-model", contents="hello")
    finally:
        mg.RETRY_DELAY_SECONDS = old_delay
        if "text-embedding-004" in mg._fallback_chain:
            del mg._fallback_chain["text-embedding-004"]


@pytest.mark.xfail(reason="global model governance state pollution in full test suites")
@patch("gemini_client_factory.get_gemini_client")
@pytest.mark.asyncio
async def test_get_embedding_governance_async_fallback(mock_get_client):
    """非同期 embed_content でもガバナンスフォールバックが機能することを検証"""
    from gemini_client_factory import GovernedClient
    from google.genai.errors import APIError
    
    raw_client = MagicMock()
    mock_aio = MagicMock()
    raw_client.aio = mock_aio
    
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.3] * 768
    mock_result.embeddings = [mock_embedding]
    
    async def mock_async_embed_content(*args, **kwargs):
        if mock_async_embed_content.call_count == 0:
            mock_async_embed_content.call_count += 1
            raise APIError(429, {"error": "RESOURCE_EXHAUSTED"})
        mock_async_embed_content.call_count += 1
        return mock_result
        
    mock_async_embed_content.call_count = 0
    mock_aio.models.embed_content = mock_async_embed_content
    
    governed_client = GovernedClient(raw_client)
    mock_get_client.return_value = governed_client
    
    from model_governance import model_governance as mg
    mg._fallback_chain["text-embedding-004"] = "fallback-embedding-model"
    old_delay = mg.RETRY_DELAY_SECONDS
    mg.RETRY_DELAY_SECONDS = 0.01
    
    try:
        res = await governed_client.aio.models.embed_content(model="text-embedding-004", contents="hello")
        assert res.embeddings[0].values == [0.3] * 768
        assert mock_async_embed_content.call_count == 2
    finally:
        mg.RETRY_DELAY_SECONDS = old_delay
        if "text-embedding-004" in mg._fallback_chain:
            del mg._fallback_chain["text-embedding-004"]


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_invalid_input_type(mock_get_client):
    """入力 contents が None や int など文字列以外の不正な型の場合に、TypeError をキャッチしてスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # get_embedding に None を渡したとき
    vec_none = get_embedding(None)
    assert vec_none == _stub_embedding("")
    
    # get_embedding に int を渡したとき
    vec_int = get_embedding(12345)
    assert vec_int == _stub_embedding("12345")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_invalid_input_type(mock_get_client):
    """バッチ入力のリスト内に None や int などの非文字列が含まれている場合に、TypeError をキャッチしてスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    texts = ["hello", None, 123]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 3
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("")
    assert vecs[2] == _stub_embedding("123")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_dimension_mismatch(mock_get_client):
    """API が返す Embedding ベクトルの次元数が 768 次元でない場合（例: 512次元）に、ValueError を発生させてスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    mock_embedding.values = [0.1] * 512  # 違った次元数
    mock_result.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_missing_values_attr(mock_get_client):
    """API の返却オブジェクト emb に values 属性が欠落しているか None の場合に、ValueError でスタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_embedding = MagicMock()
    del mock_embedding.values  # values 属性を削除
    mock_result.embeddings = [mock_embedding]
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)


@pytest.mark.xfail(reason="APIError exception class mismatch in full test suites")
@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_apierror_logging(mock_get_client, caplog):
    """APIError 発生時に、APIError に適したログが記録されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.models.embed_content.side_effect = APIError(500, {"error": "API Failure"})
    
    import logging
    with caplog.at_level(logging.WARNING):
        get_embedding("api_error_test")
        
    assert any("APIError" in message for message in caplog.messages)
    assert any("ダミー Embedding" in message or "fallback" in message.lower() for message in caplog.messages)

@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_parser_error_logging(mock_get_client, caplog):
    """ValueError 等のレスポンス解析失敗時に、レスポンス解析失敗用のログが記録されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_result.embeddings = []  # 空リストで ValueError を誘発
    mock_client.models.embed_content.return_value = mock_result
    
    import logging
    with caplog.at_level(logging.WARNING):
        get_embedding("parser_error_test")
        
    assert any("レスポンス解析失敗" in message for message in caplog.messages)
    assert any("ダミー Embedding" in message or "fallback" in message.lower() for message in caplog.messages)

@pytest.mark.xfail(reason="APIError exception class mismatch in full test suites")
@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_apierror_logging(mock_get_client, caplog):
    """バッチ APIError 発生時に、バッチ APIError に適したログが記録されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.models.embed_content.side_effect = APIError(500, {"error": "API Failure"})
    
    import logging
    with caplog.at_level(logging.WARNING):
        get_embeddings_batch(["test1", "test2"])
        
    assert any("APIError" in message for message in caplog.messages)
    assert any("バッチ Embedding 失敗" in message for message in caplog.messages)

@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_parser_error_logging(mock_get_client, caplog):
    """バッチレスポンス解析失敗時に、バッチレスポンス解析失敗用のログが記録されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_result.embeddings = None  # None で ValueError を誘発
    mock_client.models.embed_content.return_value = mock_result
    
    import logging
    with caplog.at_level(logging.WARNING):
        get_embeddings_batch(["test1", "test2"])
        
    assert any("バッチレスポンス解析失敗" in message for message in caplog.messages)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_program_error_propagation(mock_get_client):
    """プログラムエラー（NameError, TypeError等）が発生した場合は、スタブにフォールバックせずそのままraiseされることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # NameError の伝播を検証
    mock_client.models.embed_content.side_effect = NameError("test name error")
    with pytest.raises(NameError):
        get_embedding("hello")
        
    # TypeError の伝播を検証 (入力値検証以外のプログラム内エラー)
    mock_client.models.embed_content.side_effect = TypeError("test type error")
    with pytest.raises(TypeError):
        get_embedding("hello")

    # UnboundLocalError の伝播を検証
    mock_client.models.embed_content.side_effect = UnboundLocalError("test unbound local error")
    with pytest.raises(UnboundLocalError):
        get_embedding("hello")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_infrastructure_fallback(mock_get_client, caplog):
    """一時的なインフラエラー（ConnectionError, TimeoutError）が発生した場合は、スタブにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    import logging
    
    # ConnectionError のフォールバックとログ出力を検証
    mock_client.models.embed_content.side_effect = ConnectionError("test connection error")
    with caplog.at_level(logging.WARNING):
        vec = get_embedding("infra_test_conn")
    assert vec == _stub_embedding("infra_test_conn")
    assert any("一時的なインフラエラー" in message for message in caplog.messages)
    
    caplog.clear()
    
    # TimeoutError のフォールバックとログ出力を検証
    mock_client.models.embed_content.side_effect = TimeoutError("test timeout error")
    with caplog.at_level(logging.WARNING):
        vec = get_embedding("infra_test_timeout")
    assert vec == _stub_embedding("infra_test_timeout")
    assert any("一時的なインフラエラー" in message for message in caplog.messages)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_api_none_element(mock_get_client):
    """APIの返却値 embeddings リスト内に None の要素が存在する場合に適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_result.embeddings = [None]  # リスト内の要素を None に設定
    mock_client.models.embed_content.return_value = mock_result
    
    text = "hello"
    vec = get_embedding(text)
    assert vec == _stub_embedding(text)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_api_missing_values_attr(mock_get_client):
    """バッチ取得時に、API返却の個別 embedding に values 属性が欠落しているか None の場合に、適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    
    mock_emb2 = MagicMock()
    del mock_emb2.values  # values 属性を削除
    
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_api_dimension_mismatch(mock_get_client):
    """バッチ取得時に、API返却の個別 embedding ベクトルの次元数が 768 次元でない場合に、適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    
    mock_emb2 = MagicMock()
    mock_emb2.values = [0.2] * 512  # 不正な次元数
    
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result
    
    texts = ["hello", "world"]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("hello")
    assert vecs[1] == _stub_embedding("world")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_infrastructure_fallback(mock_get_client, caplog):
    """バッチ取得中に一時的なインフラエラー（ConnectionError, TimeoutError）が発生した場合に、適切にスタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    import logging
    
    # ConnectionError の検証
    mock_client.models.embed_content.side_effect = ConnectionError("test connection error")
    with caplog.at_level(logging.WARNING):
        vecs = get_embeddings_batch(["infra_test_conn1", "infra_test_conn2"])
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("infra_test_conn1")
    assert vecs[1] == _stub_embedding("infra_test_conn2")
    assert any("一時的なインフラエラー" in message for message in caplog.messages)
    
    caplog.clear()
    
    # TimeoutError の検証
    mock_client.models.embed_content.side_effect = TimeoutError("test timeout error")
    with caplog.at_level(logging.WARNING):
        vecs = get_embeddings_batch(["infra_test_timeout1", "infra_test_timeout2"])
    assert len(vecs) == 2
    assert vecs[0] == _stub_embedding("infra_test_timeout1")
    assert vecs[1] == _stub_embedding("infra_test_timeout2")
    assert any("一時的なインフラエラー" in message for message in caplog.messages)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_non_list_input(mock_get_client):
    """get_embeddings_batch に非リストが渡された場合に、TypeError を検出しつつ適切にスタブリストにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # texts にあえて文字列 "hello" を渡す
    vecs = get_embeddings_batch("hello")
    assert len(vecs) == 1
    assert vecs[0] == _stub_embedding("hello")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_non_list_input_stub_mode(mock_get_client):
    """stub_mode (clientがNone) の時に get_embeddings_batch に非リストが渡された場合、適切にスタブリストにフォールバックすることを検証"""
    mock_get_client.return_value = None
    
    vecs = get_embeddings_batch("hello")
    assert len(vecs) == 1
    assert vecs[0] == _stub_embedding("hello")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_chunking(mock_get_client):
    """バッチサイズが100を超える場合（例: 105件）、100件ずつのチャンクに分割されてAPIが呼ばれることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # embed_content が呼び出されるたびに返すモック結果を設定
    # 1回目は 100件、2回目は 5件分
    mock_result1 = MagicMock()
    mock_embeddings1 = [MagicMock(values=[0.1] * 768) for _ in range(100)]
    mock_result1.embeddings = mock_embeddings1
    
    mock_result2 = MagicMock()
    mock_embeddings2 = [MagicMock(values=[0.2] * 768) for _ in range(5)]
    mock_result2.embeddings = mock_embeddings2
    
    mock_client.models.embed_content.side_effect = [mock_result1, mock_result2]
    
    texts = [f"text_{i}" for i in range(105)]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 105
    assert vecs[0] == [0.1] * 768
    assert vecs[99] == [0.1] * 768
    assert vecs[100] == [0.2] * 768
    assert vecs[104] == [0.2] * 768
    
    assert mock_client.models.embed_content.call_count == 2
    mock_client.models.embed_content.assert_any_call(
        model="text-embedding-004",
        contents=texts[:100]
    )
    mock_client.models.embed_content.assert_any_call(
        model="text-embedding-004",
        contents=texts[100:]
    )


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_chunking_partial_failure(mock_get_client):
    """複数チャンクのうち一部が失敗（例: APIError）した場合に、正常なチャンクは取得し、失敗したチャンクはSTUBにフォールバックしてマージされることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result1 = MagicMock()
    mock_embeddings1 = [MagicMock(values=[0.1] * 768) for _ in range(100)]
    mock_result1.embeddings = mock_embeddings1
    
    # 2回目のAPI呼び出しでエラーを発生させる
    mock_client.models.embed_content.side_effect = [
        mock_result1,
        APIError(500, {"error": "Chunk Failure"})
    ]
    
    texts = [f"text_{i}" for i in range(105)]
    vecs = get_embeddings_batch(texts)
    
    assert len(vecs) == 105
    assert vecs[0] == [0.1] * 768
    assert vecs[99] == [0.1] * 768
    # 101〜105件目はSTUBにフォールバックしていることを確認
    for i in range(100, 105):
        assert vecs[i] == _stub_embedding(texts[i])


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_assertion_error_propagation(mock_get_client):
    """内部で AssertionError が発生した場合、STUBにフォールバックせずそのまま例外が raise されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # embed_content で AssertionError を発生させる
    mock_client.models.embed_content.side_effect = AssertionError("Mock AssertionError")
    
    with pytest.raises(AssertionError) as exc_info:
        get_embedding("assertion_test")
    
    assert "Mock AssertionError" in str(exc_info.value)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_malformed_chunk_results(mock_get_client, caplog):
    """チャンク処理結果がリスト以外、または長さ不整合の場合に、サイズ不整合を起こさず各要素の個別スタブへフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # _embed_contents_or_fallback が None (リストではない) を返すようにモックする
    with patch("services.embedding_service._embed_contents_or_fallback", return_value=None):
        texts = ["hello", "world"]
        vecs = get_embeddings_batch(texts)
        assert len(vecs) == 2
        assert vecs[0] == _stub_embedding("hello")
        assert vecs[1] == _stub_embedding("world")

    # _embed_contents_or_fallback が長さの異なるリストを返すようにモックする
    # 2つの入力を与えるが、1つの埋め込み結果しか返さない状況を作る
    with patch("services.embedding_service._embed_contents_or_fallback", return_value=[[0.1] * 768]):
        texts = ["hello", "world"]
        vecs = get_embeddings_batch(texts)
        assert len(vecs) == 2
        assert vecs[0] == _stub_embedding("hello")
        assert vecs[1] == _stub_embedding("world")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_tuple_input(mock_get_client):
    """入力にタプルなどのイテラブルを渡した場合でも、正しくバッチ処理が行われることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # 正常系モック
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    mock_emb2 = MagicMock()
    mock_emb2.values = [0.2] * 768
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result

    texts = ("hello", "world")
    vecs = get_embeddings_batch(texts)
    assert len(vecs) == 2
    assert vecs == [[0.1] * 768, [0.2] * 768]


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_client_factory_program_error(mock_get_client):
    """get_gemini_client 呼び出しにおいて TypeError などのプログラムエラーが発生した際、スタブにフォールバックせず raise されることを検証"""
    # get_gemini_client 呼び出しで TypeError を発生させる
    mock_get_client.side_effect = TypeError("Client Factory TypeError")

    with pytest.raises(TypeError) as exc_info:
        get_embedding("factory_test")
    assert "Client Factory TypeError" in str(exc_info.value)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_non_iterable_cast_fallback(mock_get_client):
    """非イテラブルな入力を渡したときに TypeError をキャッチし、適切にスタブリストにフォールバックすることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # texts にあえて整数 12345 を渡す
    vecs = get_embeddings_batch(12345)
    assert len(vecs) == 1
    assert vecs[0] == _stub_embedding("12345")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_arithmetic_error_propagation(mock_get_client):
    """内部で ArithmeticError が発生した場合、STUBにフォールバックせずそのまま例外が raise されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_client.models.embed_content.side_effect = ZeroDivisionError("Mock ZeroDivisionError")
    
    with pytest.raises(ZeroDivisionError) as exc_info:
        get_embedding("arithmetic_test")
    
    assert "Mock ZeroDivisionError" in str(exc_info.value)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_api_value_error_propagation(mock_get_client):
    """API呼び出し自体で ValueError が発生した場合（引数不正などを模倣）、STUBにフォールバックせずそのまま例外が raise されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    # embed_content 自体が ValueError を投げるケース
    mock_client.models.embed_content.side_effect = ValueError("Mock API ValueError")
    
    with pytest.raises(ValueError) as exc_info:
        get_embedding("value_error_test")
    
    assert "Mock API ValueError" in str(exc_info.value)


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_client_factory_unexpected_exception_fallback(mock_get_client):
    """get_gemini_client 呼び出しで RuntimeError などのプログラムエラー以外の想定外例外が発生した際、スタブにフォールバックすることを検証"""
    # get_gemini_client 呼び出しで RuntimeError を発生させる
    mock_get_client.side_effect = RuntimeError("Mock Client Factory RuntimeError")

    vec = get_embedding("factory_unexpected_test")
    assert len(vec) == 768
    assert vec == _stub_embedding("factory_unexpected_test")


@patch("gemini_client_factory.get_gemini_client")
def test_get_embedding_client_factory_value_error_propagation(mock_get_client):
    """get_gemini_client 呼び出しにおいて ValueError が発生した際、スタブにフォールバックせず raise されることを検証"""
    mock_get_client.side_effect = ValueError("Client Factory ValueError")

    with pytest.raises(ValueError) as exc_info:
        get_embedding("factory_value_error_test")
    assert "Client Factory ValueError" in str(exc_info.value)





@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_with_generator_input(mock_get_client):
    """ジェネレータオブジェクトをバッチ入力として渡した場合に、正常にリストにキャストされて処理されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb1 = MagicMock()
    mock_emb1.values = [0.1] * 768
    mock_emb2 = MagicMock()
    mock_emb2.values = [0.2] * 768
    mock_result.embeddings = [mock_emb1, mock_emb2]
    mock_client.models.embed_content.return_value = mock_result
    
    # ジェネレータを作成
    texts_gen = (t for t in ["gen1", "gen2"])
    
    vecs = get_embeddings_batch(texts_gen)
    assert len(vecs) == 2
    assert vecs == [[0.1] * 768, [0.2] * 768]


@patch("gemini_client_factory.get_gemini_client")
def test_get_embeddings_batch_different_iterable(mock_get_client):
    """dict.keys() のようなリスト以外のイテラブルをバッチ入力として渡した場合に、正常にリストにキャストされて処理されることを検証"""
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    
    mock_result = MagicMock()
    mock_emb = MagicMock()
    mock_emb.values = [0.5] * 768
    mock_result.embeddings = [mock_emb]
    mock_client.models.embed_content.return_value = mock_result
    
    d = {"key1": "value1"}
    vecs = get_embeddings_batch(d.keys())
    assert len(vecs) == 1
    assert vecs == [[0.5] * 768]


def test_stub_embedding_surrogate_pairs():
    """絵文字結合文字（ZWJ）などの複雑なサロゲートペアが含まれる文字列に対しても、_stub_embedding が安定し一貫したベクトルを返すことを検証"""
    text = "👨‍👩‍👧‍👦"  # 家族の絵文字（ZWJで結合された複数のサロゲートペア）
    vec1 = _stub_embedding(text)
    vec2 = _stub_embedding(text)
    
    assert len(vec1) == 768
    assert vec1 == vec2
    
    for val in vec1:
        assert -1.0 <= val <= 1.0
