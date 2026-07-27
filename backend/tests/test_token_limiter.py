# -*- coding: utf-8 -*-
import logging
import pytest
import importlib
from unittest.mock import MagicMock
from backend.agents.orchestration.token_limiter import TokenLimiter
import backend.agents.orchestration.token_limiter as token_limiter_mod

logger = logging.getLogger(__name__)

def test_token_limiter_init():
    """初期化のテスト"""
    limiter = TokenLimiter(max_tokens=500)
    assert limiter.max_tokens == 500

    # デフォルト値
    limiter_default = TokenLimiter()
    assert limiter_default.max_tokens == 120000

def test_count_tokens_empty():
    """空入力・None入力のテスト"""
    limiter = TokenLimiter()
    assert limiter.count_tokens("") == 0
    assert limiter.count_tokens(None) == 0

def test_count_tokens_with_tiktoken(monkeypatch):
    """tiktokenが有効な場合の正常系トークンカウント"""
    limiter = TokenLimiter()
    
    # tiktoken が確実に True である状態にする
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", True)
    
    # tiktoken の get_encoding をモック
    mock_encoding = MagicMock()
    mock_encoding.encode.return_value = [1, 2, 3, 4, 5]
    mock_get_encoding = MagicMock(return_value=mock_encoding)
    
    # モジュールの tiktoken をモック
    if hasattr(token_limiter_mod, "tiktoken") and token_limiter_mod.tiktoken:
        monkeypatch.setattr(token_limiter_mod.tiktoken, "get_encoding", mock_get_encoding)
    else:
        # tiktoken モジュール自体が存在しない環境用
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.return_value = mock_encoding
        monkeypatch.setattr(token_limiter_mod, "tiktoken", mock_tiktoken)
        
    text = "Hello world"
    tokens = limiter.count_tokens(text)
    
    assert tokens == 5
    mock_get_encoding.assert_called_once_with("cl100k_base")
    mock_encoding.encode.assert_called_once_with(text)

def test_count_tokens_fallback_no_tiktoken(monkeypatch):
    """tiktoken が利用不可の場合のフォールバックテスト"""
    limiter = TokenLimiter()
    
    # HAS_TIKTOKEN を False に設定
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    text = "This is a test sentence with several words."  # 43文字
    # len(text) // 4 = 10
    tokens = limiter.count_tokens(text)
    assert tokens == 10

    # 極小文字数の場合の最小値 1 を検証
    assert limiter.count_tokens("a") == 1
    assert limiter.count_tokens("abc") == 1
    assert limiter.count_tokens("abcd") == 1
    assert limiter.count_tokens("abcde") == 1  # 5 // 4 = 1

def test_count_tokens_fallback_on_exception(monkeypatch):
    """tiktoken が有効だが、実行時に例外が発生した場合のフォールバックテスト (TD-732)"""
    limiter = TokenLimiter()
    
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", True)
    
    # get_encoding が例外を発生させるようにモック
    def mock_get_encoding_fail(name):
        raise ValueError("Simulated encoding failure")
        
    if hasattr(token_limiter_mod, "tiktoken") and token_limiter_mod.tiktoken:
        monkeypatch.setattr(token_limiter_mod.tiktoken, "get_encoding", mock_get_encoding_fail)
    else:
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = ValueError("Simulated encoding failure")
        monkeypatch.setattr(token_limiter_mod, "tiktoken", mock_tiktoken)
        
    text = "Hello world!"  # 12文字
    # len(text) // 4 = 3
    tokens = limiter.count_tokens(text)
    assert tokens == 3

def test_trim_context_within_limit():
    """上限以内のテキストはトリミングされないこと"""
    limiter = TokenLimiter(max_tokens=100)
    text = "Hello world\nThis is within the limit."
    result = limiter.trim_context(text)
    assert result == text

def test_trim_context_default_limit(monkeypatch):
    """max_tokens が None の場合、デフォルト値 (self.max_tokens) が使用されること"""
    limiter = TokenLimiter(max_tokens=10)
    
    # 35文字 -> tiktokenなしで 8 トークン (上限10以内)
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    text = "Short text with very few characters."
    
    # max_tokens を明示的に指定しない場合
    result = limiter.trim_context(text, max_tokens=None)
    assert result == text
    
    # max_tokens=5 と指定して上限オーバーにする
    # リスト行がないため、通常行が削られていく
    # "Short text with very few characters." (8 tokens) -> max_tokens=5
    # splitlines() -> ['Short text with very few characters.']
    # 1行削ると temp_text = "" (0 tokens <= 5) -> "" が返る
    result_over = limiter.trim_context(text, max_tokens=5)
    assert result_over == ""

def test_trim_context_remove_list_lines(monkeypatch):
    """リストアイテム行が優先的に削除され、上限以下に収まること"""
    # tiktoken なしでフォールバックカウントを使用
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    # 1行目: 18文字 -> 4 トークン
    # 2行目: 10文字 (リスト行) -> 2 トークン
    # 3行目: 10文字 (リスト行) -> 2 トークン
    # 4行目: 10文字 (リスト行) -> 2 トークン
    # 5行目: 18文字 -> 4 トークン
    # 合計: 66文字 (+改行4文字=70文字) -> 17 トークン
    text = (
        "Header information\n"
        "- List A\n"
        "* List B\n"
        "1. List C\n"
        "Footer information"
    )
    
    # max_tokens = 10 に設定
    limiter = TokenLimiter(max_tokens=10)
    
    # トリミングを実行
    # リスト行を順に削除していく
    # 削除後 temp_text は:
    # "Header information\nFooter information" -> 37文字 -> 9 トークン
    # 9 <= 10 なので、リスト行のみ削除された状態が返るはず
    result = limiter.trim_context(text)
    
    assert "Header information" in result
    assert "Footer information" in result
    assert "- List A" not in result
    assert "* List B" not in result
    assert "1. List C" not in result

def test_trim_context_remove_normal_lines(monkeypatch):
    """リストアイテム行をすべて削除しても上限を超える場合、通常行も順に削除されること"""
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    # 全て通常行で構成
    # 各行 20文字 -> 5 トークン
    # 合計 5行 -> 25 トークン
    text = (
        "Normal line number 1\n"
        "Normal line number 2\n"
        "Normal line number 3\n"
        "Normal line number 4\n"
        "Normal line number 5"
    )
    
    # max_tokens = 12
    limiter = TokenLimiter(max_tokens=12)
    
    # トリミング実行
    # 1行ずつ削られる (古いものから: 先頭から)
    # line 1 削除 -> 残り 4行 (20トークン) -> まだオーバー
    # line 2 削除 -> 残り 3行 (15トークン) -> まだオーバー
    # line 3 削除 -> 残り 2行 (10トークン) -> 10 <= 12 で成功
    # 結果として "Normal line number 4\nNormal line number 5" が返る
    result = limiter.trim_context(text)
    
    assert "Normal line number 1" not in result
    assert "Normal line number 2" not in result
    assert "Normal line number 3" not in result
    assert "Normal line number 4" in result
    assert "Normal line number 5" in result

def test_trim_context_mixed_lines_continue(monkeypatch):
    """混在テキストにおいて、リスト行削除後さらに通常行削除ループに入る際、リスト行インデックスが正しくスキップ(continue)されること"""
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    # 行構成:
    # 0: 通常行 (14文字) -> 3 トークン
    # 1: リスト行 (8文字) -> 2 トークン
    # 2: 通常行 (14文字) -> 3 トークン
    # 3: 通常行 (14文字) -> 3 トークン
    # 4: リスト行 (8文字) -> 2 トークン
    # 合計 13 トークン
    text = (
        "Normal Line 1\n"
        "- List 1\n"
        "Normal Line 2\n"
        "Normal Line 3\n"
        "- List 2"
    )
    
    # max_tokens = 3 と設定
    # リスト行 (1, 4) を全削除すると:
    # "Normal Line 1\nNormal Line 2\nNormal Line 3" (44文字) -> 11 トークン (まだ上限 3 を超える)
    # よって、通常行削除ループに入る。
    # 通常行削除ループ (i=0 to 4):
    # i=0 (通常行): 削除リストに加える -> 残り: "- List 1\nNormal Line 2\nNormal Line 3\n- List 2"
    #   実質残り: "Normal Line 2\nNormal Line 3" (29文字) -> 7 トークン > 3
    # i=1 (リスト行): すでに削除対象セットにあるため、continue でスキップされるはず (87行目をカバー)
    # i=2 (通常行): 削除リストに加える -> 実質残り: "Normal Line 3" (13文字) -> 3 トークン <= 3 -> トリミング成功！
    limiter = TokenLimiter(max_tokens=3)
    result = limiter.trim_context(text)
    
    assert "Normal Line 1" not in result
    assert "Normal Line 2" not in result
    assert "Normal Line 3" in result
    assert "- List 1" not in result
    assert "- List 2" not in result

def test_trim_context_extreme_fallback(monkeypatch):
    """極限フォールバックテスト (上限が極小で、すべて削除しても収まらない場合)"""
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    text = "Hello world"
    limiter = TokenLimiter(max_tokens=-1)  # 上限-1トークンとすることで 96行目の return "" に確実に到達させる
    
    result = limiter.trim_context(text)
    assert result == ""

def test_token_limiter_import_error_coverage(monkeypatch):
    """tiktokenのインポートエラー発生時のHAS_TIKTOKENの初期設定を検証する"""
    import sys
    
    # sys.modulesからtiktokenを隠す
    monkeypatch.setitem(sys.modules, "tiktoken", None)
    
    # モジュールをリロードして ImportError を意図的に発生させる
    importlib.reload(token_limiter_mod)
    
    assert token_limiter_mod.HAS_TIKTOKEN is False
    
    # 他のテストへの影響を防ぐため、tiktoken を元に戻してリロードする
    monkeypatch.delitem(sys.modules, "tiktoken")
    importlib.reload(token_limiter_mod)


def test_trim_context_binary_search_efficiency(monkeypatch):
    """二分探索が効率的に動作し、count_tokensの呼び出し回数が劇的に少なくなっていることを検証する"""
    limiter = TokenLimiter(max_tokens=10)
    
    # 50行のリスト行を作成
    lines = [f"- Line {i}" for i in range(50)]
    text = "\n".join(lines)
    
    # count_tokens をスパイして呼び出し回数をカウントする
    call_count = 0
    original_count_tokens = limiter.count_tokens
    
    def spy_count_tokens(txt):
        nonlocal call_count
        call_count += 1
        return original_count_tokens(txt)
        
    monkeypatch.setattr(limiter, "count_tokens", spy_count_tokens)
    
    # トリミングを実行
    result = limiter.trim_context(text)
    
    # 線形探索の場合、最悪50回の count_tokens 呼び出しが発生しますが、
    # 二分探索であれば log2(50) = 6 回前後の呼び出しで収まるはずです
    # （最初の全体チェックやフォールバック等を考慮しても 15 回以内であるはず）
    assert call_count < 15
    assert limiter.count_tokens(result) <= 10


def test_count_tokens_fallback_logger_warning(monkeypatch):
    """tiktokenで例外が発生した際、警告ログが正しく出力されフォールバックされること"""
    limiter = TokenLimiter()
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", True)
    
    def mock_get_encoding_fail(name):
        raise RuntimeError("Encoding error")
        
    if hasattr(token_limiter_mod, "tiktoken") and token_limiter_mod.tiktoken:
        monkeypatch.setattr(token_limiter_mod.tiktoken, "get_encoding", mock_get_encoding_fail)
    else:
        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("Encoding error")
        monkeypatch.setattr(token_limiter_mod, "tiktoken", mock_tiktoken)
        
    mock_logger = MagicMock()
    monkeypatch.setattr(token_limiter_mod, "logger", mock_logger)
    
    text = "Hello world! This is a test."  # 28文字
    tokens = limiter.count_tokens(text)
    
    assert tokens == 7  # 28 // 4
    mock_logger.warning.assert_called_once()
    assert "tiktoken encoding failed" in mock_logger.warning.call_args[0][0]


def test_trim_context_various_list_formats(monkeypatch):
    """複数桁の数値を含む、さまざまな形式 of リスト行が正しく認識され優先削除されること"""
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    text = (
        "Header\n"
        "10. Item A\n"
        "12345. Item B\n"
        "0. Item C\n"
        "Footer"
    )
    
    # limit = 4 とすることで、リスト行がすべて削除されて Header\nFooter となることを期待
    # Header\nFooter (13文字) -> 3トークン なので max_tokens=4 なら収まる
    limiter = TokenLimiter(max_tokens=4)
    result = limiter.trim_context(text)
    
    assert "Header" in result
    assert "Footer" in result
    assert "10. Item A" not in result
    assert "12345. Item B" not in result
    assert "0. Item C" not in result


def test_trim_context_large_input_performance(monkeypatch):
    """極めて長大なテキスト（多数の行）を入力した際も、二分探索により高速かつ正常に制限内に収まること"""
    monkeypatch.setattr(token_limiter_mod, "HAS_TIKTOKEN", False)
    
    # 1000行のテキストを作成。各行20文字 (5トークン) -> 合計5000トークン
    lines = [f"Normal line number {i}" for i in range(1000)]
    text = "\n".join(lines)
    
    # 上限を100トークン (約20行) に設定
    limiter = TokenLimiter(max_tokens=100)
    result = limiter.trim_context(text)
    
    # トリミング後のトークン数が100以下であることを検証
    assert limiter.count_tokens(result) <= 100
    # 結果が空ではないことを検証
    assert result != ""

