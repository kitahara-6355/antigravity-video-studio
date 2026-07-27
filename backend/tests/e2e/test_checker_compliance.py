"""
Q1-Q6 コンプライアンスチェッカー自体の品質保証テスト

チェッカー(conftest.py m36_q1_q6_compliance)が正しく違反を検出するか、
また正当なテストコードを誤検出しないかを検証する。

BP-1: チェッカーにバグが入った場合、不正なテストコードが通過してしまう。
このテストファイルはチェッカーの信頼性基盤を保証する。
"""
import re
import sys
import os
import pytest

# e2e/conftest.py から内部関数・定数をインポート
# pytestが上位conftest.pyを優先するため、importlibで直接ロード
import importlib.util
_e2e_conftest_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py")
_spec = importlib.util.spec_from_file_location("backend.tests.e2e.conftest", _e2e_conftest_path)
_e2e_conftest = importlib.util.module_from_spec(_spec)
# sys.modulesに登録することでpytest-cov (coverage.py) が認識可能にする
sys.modules["backend.tests.e2e.conftest"] = _e2e_conftest
_spec.loader.exec_module(_e2e_conftest)

_get_layer_section = _e2e_conftest._get_layer_section
_LAYER_MARKERS = _e2e_conftest._LAYER_MARKERS
_L3_OPS = _e2e_conftest._L3_OPS
_FAKE_PASS_PATTERNS = _e2e_conftest._FAKE_PASS_PATTERNS
_strip_comments = _e2e_conftest._strip_comments


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# テスト用サンプルソースコード
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALID_SOURCE = '''
def test_example(self, app_page):
    """AC-X01: テスト例
    逆引き: O1-L1-01, O1-L2-03
    """
    page = app_page

    # === L1: DOM存在 (2 assertions) ===
    el = page.locator("[data-testid='test']")
    assert el.count() == 1, "L1-1"
    assert el.first.is_visible(), "L1-2"

    # === L2: 視覚FBK (2 assertions) ===
    text = el.first.text_content()
    assert text is not None, "L2-1"
    assert len(text) > 0, "L2-2"

    # === L3: 操作 (3 assertions) ===
    el.first.click()
    page.wait_for_timeout(300)
    selected = page.locator(".selected")
    assert selected.count() >= 1, "L3-1"
    el.first.fill("test value")
    assert selected.first.is_visible(), "L3-2"
    assert el.first.text_content() is not None, "L3-3"

    # === L4: 状態遷移 (3 assertions) ===
    before_text = el.first.text_content()
    el.first.click()
    after_text = el.first.text_content()
    assert before_text is not None, "L4-1"
    assert after_text is not None, "L4-2"
    assert before_text != after_text, "L4-3"

    # === L5: E2E完走 (4 assertions) ===
    el.first.click()
    page.wait_for_timeout(300)
    el.first.fill("final")
    page.wait_for_timeout(300)
    assert el.first.is_visible(), "L5-1"
    assert page.locator(".result").count() > 0, "L5-2"
    assert page.locator(".result").first.text_content() is not None, "L5-3"
    assert page.locator(".status").first.is_visible(), "L5-4"
'''


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §1: _get_layer_section のセクション分割テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestLayerSectionExtraction:
    """_get_layer_section が === L*: 形式を正しく分割するか"""

    def test_extracts_l1_section(self):
        section = _get_layer_section(VALID_SOURCE, "L1:")
        assert "L1-1" in section
        assert "L1-2" in section
        # L2の内容が混入していないこと
        assert "L2-1" not in section

    def test_extracts_l3_section(self):
        section = _get_layer_section(VALID_SOURCE, "L3:")
        assert ".click(" in section
        assert ".fill(" in section
        # L2やL4の内容が混入していないこと
        assert "L2-1" not in section
        assert "L4-1" not in section

    def test_extracts_l5_section(self):
        section = _get_layer_section(VALID_SOURCE, "L5:")
        assert "L5-1" in section
        assert "L5-4" in section
        # L4の内容が混入していないこと
        assert "L4-3" not in section

    def test_l5_is_last_section(self):
        """L5は最後のセクション — 関数末尾まで含まれるべき"""
        section = _get_layer_section(VALID_SOURCE, "L5:")
        assert "L5-4" in section

    def test_empty_source_returns_empty(self):
        section = _get_layer_section("", "L1:")
        assert section == ""

    def test_missing_layer_returns_empty(self):
        source_no_l3 = """
    # === L1: test ===
    assert True
    # === L2: test ===
    assert True
    """
        section = _get_layer_section(source_no_l3, "L3:")
        assert section.strip() == ""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §2: 偽PASSパターン検出テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestFakePassDetection:
    """偽PASSパターンの正規表現が正しく動作するか"""

    def test_detects_assert_true(self):
        source = 'assert True'
        assert re.search(_FAKE_PASS_PATTERNS[0], source) is not None

    def test_detects_or_true(self):
        source = 'result or True'
        assert re.search(_FAKE_PASS_PATTERNS[1], source) is not None

    def test_detects_gte_zero(self):
        source = 'assert count >= 0, "always true"'
        assert re.search(_FAKE_PASS_PATTERNS[2], source) is not None

    def test_does_not_false_positive_on_gte_one(self):
        """assert count >= 1 は偽PASSではない — 検出しないこと"""
        source = 'assert count >= 1, "valid check"'
        for pattern in _FAKE_PASS_PATTERNS:
            match = re.search(pattern, source)
            assert match is None, f"False positive: {pattern} matched '{source}'"

    def test_valid_source_has_no_fake_pass(self):
        """正当なソースに偽PASSパターンがないこと"""
        for pattern in _FAKE_PASS_PATTERNS:
            match = re.search(pattern, VALID_SOURCE)
            assert match is None, \
                f"VALID_SOURCE contains fake pass: {pattern} → {match.group()}"

    def test_comment_fake_pass_is_not_detected(self):
        """コメント行の偽PASSパターンは誤検知しないこと (BP-4関連)"""
        source = '''# assert True は禁止パターンである
# >= 0 のようなチェックも禁止
assert count >= 1, "valid"
'''
        stripped = _strip_comments(source)
        for pattern in _FAKE_PASS_PATTERNS:
            match = re.search(pattern, stripped)
            assert match is None, \
                f"コメント行を除外後も誤検知: {pattern} → {match.group()}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §3: min_assertカウント検証テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestMinAssertCount:
    """各レイヤーのassert数が設計書の最小値を満たすか"""

    _MIN_ASSERTS = {"L1:": 2, "L2:": 2, "L3:": 3, "L4:": 3, "L5:": 4}

    def test_valid_source_meets_all_min_asserts(self):
        for layer, min_count in self._MIN_ASSERTS.items():
            section = _get_layer_section(VALID_SOURCE, layer)
            actual = sum(1 for line in section.split("\n")
                         if line.strip().startswith("assert "))
            assert actual >= min_count, \
                f"{layer}: assert数 {actual} < 最小 {min_count}"

    def test_insufficient_l1_is_detected(self):
        """L1にassertが1つしかないソースは不足と判定されるべき"""
        source = '''
    # === L1: test (1 assertion) ===
    assert True
    # === L2: test ===
    assert a
    assert b
    '''
        section = _get_layer_section(source, "L1:")
        actual = sum(1 for line in section.split("\n")
                     if line.strip().startswith("assert "))
        assert actual < 2, "L1に1 assertしかないのに2以上と判定された"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §4: L3 Browser操作キーワード検出テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestL3BrowserOps:
    """L3セクションにBrowser操作キーワードが含まれるか"""

    def test_valid_source_has_browser_ops_in_l3(self):
        l3_section = _get_layer_section(VALID_SOURCE, "L3:")
        has_op = any(op in l3_section for op in _L3_OPS)
        assert has_op, "VALID_SOURCE のL3にBrowser操作がない"

    def test_api_only_l3_is_detected(self):
        """L3にAPI呼出のみの場合、Browser操作なしと判定されるべき"""
        source = '''
    # === L3: 操作 ===
    res = page.request.get("/api/test")
    assert res.ok
    assert res.json()["key"] == "value"
    assert len(res.json()) > 0
    # === L4: test ===
    '''
        section = _get_layer_section(source, "L3:")
        has_op = any(op in section for op in _L3_OPS)
        assert not has_op, "API呼出のみのL3がBrowser操作ありと判定された"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §5: 逆引きID形式検出テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestReverseIdFormat:
    """O*-L*-** 形式の逆引きIDが正しく検出されるか"""

    def test_valid_ids_are_detected(self):
        text = "逆引き: O1-L1-01, O1-L2-03, O8-L5-12"
        ids = re.findall(r'O\d+-L\d+-\d+', text)
        assert len(ids) == 3

    def test_empty_reverse_mapping_detected(self):
        text = "逆引き:\n"
        ids = re.findall(r'O\d+-L\d+-\d+', text)
        assert len(ids) == 0, "空の逆引きセクションでIDが検出された"

    def test_invalid_format_not_detected(self):
        text = "O-1-L1 とか O1L101 は無効"
        ids = re.findall(r'O\d+-L\d+-\d+', text)
        assert len(ids) == 0


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §6: L4状態遷移パターン検出テスト (BP-4 v2.0対応)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestL4StateTransition:
    """L4セクションにbefore_/after_変数ペアがあるか (BP-4 v2.0)"""

    def test_before_after_variable_pattern(self):
        """VALID_SOURCEのL4にbefore_/after_変数が存在するか"""
        section = _get_layer_section(VALID_SOURCE, "L4:")
        l4_code_lines = [l for l in section.split("\n")
                         if l.strip() and not l.strip().startswith("#")]
        l4_code = "\n".join(l4_code_lines)
        has_before = bool(re.search(r'\bbefore_\w+', l4_code))
        has_after = bool(re.search(r'\bafter_\w+', l4_code))
        has_ne = "!=" in l4_code
        has_transition = (
            (has_before and has_after) or
            (has_ne and (has_before or has_after))
        )
        assert has_transition, "VALID_SOURCEのL4にbefore_/after_変数ペアがない"

    def test_api_only_l4_has_no_transition(self):
        """APIデータチェックのみのL4は構造的遷移なしと判定されるべき"""
        source = '''
    # === L4: 状態遷移 (3 assertions) ===
    assert isinstance(count_val, int), "L4-1"
    assert count_val == len(videos), "L4-2"
    assert "name" in video, "L4-3"
    # === L5: test ===
    '''
        section = _get_layer_section(source, "L4:")
        l4_code_lines = [l for l in section.split("\n")
                         if l.strip() and not l.strip().startswith("#")]
        l4_code = "\n".join(l4_code_lines)
        has_before = bool(re.search(r'\bbefore_\w+', l4_code))
        has_after = bool(re.search(r'\bafter_\w+', l4_code))
        has_ne = "!=" in l4_code
        has_transition = (
            (has_before and has_after) or
            (has_ne and (has_before or has_after))
        )
        assert not has_transition, "データチェックのみのL4が遷移ありと判定された"

    def test_comment_only_bypass_is_blocked(self):
        """コメントに# before/afterと書くだけでは通過しないこと (BP-4核心)"""
        source = '''
    # === L4: 状態遷移 (3 assertions) ===
    # before state と after state をチェック
    assert isinstance(count_val, int), "L4-1"
    assert count_val == len(videos), "L4-2"
    assert "name" in video, "L4-3"
    # === L5: test ===
    '''
        section = _get_layer_section(source, "L4:")
        l4_code_lines = [l for l in section.split("\n")
                         if l.strip() and not l.strip().startswith("#")]
        l4_code = "\n".join(l4_code_lines)
        has_before = bool(re.search(r'\bbefore_\w+', l4_code))
        has_after = bool(re.search(r'\bafter_\w+', l4_code))
        has_ne = "!=" in l4_code
        has_transition = (
            (has_before and has_after) or
            (has_ne and (has_before or has_after))
        )
        assert not has_transition, "コメントだけのbefore/afterが通過した(BP-4違反)"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §7: L5複数操作シーケンス検出テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestL5MultipleOps:
    """L5セクションに2種類以上のBrowser操作があるか"""

    def test_valid_source_has_multiple_ops_in_l5(self):
        l5_section = _get_layer_section(VALID_SOURCE, "L5:")
        op_count = sum(1 for op in _L3_OPS if op in l5_section)
        assert op_count >= 2, f"VALID_SOURCEのL5に操作が{op_count}種類しかない"

    def test_api_only_l5_has_zero_ops(self):
        """API呼出のみのL5はBrowser操作0と判定されるべき"""
        source = '''
    # === L5: E2E完走 (4 assertions) ===
    res = page.request.get("/api/test")
    assert res.ok, "L5-1"
    assert "data" in res.json(), "L5-2"
    res2 = page.request.get("/api/status")
    assert res2.ok, "L5-3"
    assert res2.json()["status"] == "ok", "L5-4"
    '''
        section = _get_layer_section(source, "L5:")
        op_count = sum(1 for op in _L3_OPS if op in section)
        assert op_count == 0, f"API呼出のみのL5で操作{op_count}種類検出"




# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# §8: conftest.py 内のユーティリティ・フィクスチャ検証テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _unwrap(func):
    if hasattr(func, "__wrapped__"):
        return func.__wrapped__
    return func

class TestConftestFixtures:
    """conftest.py 内のヘルパー関数およびフィクスチャの検証"""

    def test_is_port_in_use_true(self, monkeypatch):
        """ポートが使用中の場合、Trueを返すことを検証"""
        import socket
        # socket.connect が正常終了（ポート使用中）するようにモック
        def mock_connect(*args, **kwargs):
            return None
        monkeypatch.setattr(socket.socket, "connect", mock_connect)
        
        # 127.0.0.1 または ::1 で接続が試みられるので True になるはず
        res = _unwrap(_e2e_conftest._is_port_in_use)(9999)
        assert res is True

    def test_is_port_in_use_false(self, monkeypatch):
        """ポートが未使用の場合、Falseを返すことを検証"""
        import socket
        # socket.connect が ConnectionRefusedError を投げるようにモック
        def mock_connect(*args, **kwargs):
            raise ConnectionRefusedError()
        monkeypatch.setattr(socket.socket, "connect", mock_connect)
        
        res = _unwrap(_e2e_conftest._is_port_in_use)(9999)
        assert res is False

    def test_is_port_in_use_oserror(self, monkeypatch):
        """OSErrorが発生した場合の例外フォールバックでFalseを返すことを検証"""
        import socket
        def mock_connect(*args, **kwargs):
            raise OSError()
        monkeypatch.setattr(socket.socket, "connect", mock_connect)
        
        res = _unwrap(_e2e_conftest._is_port_in_use)(9999)
        assert res is False

    def test_wait_for_port_success(self, monkeypatch):
        """ポートが開いた場合に True を返すことを検証"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: True)
        res = _unwrap(_e2e_conftest._wait_for_port)(9999, timeout=1)
        assert res is True

    def test_wait_for_port_timeout(self, monkeypatch):
        """ポートが開かないままタイムアウトした場合に False を返すことを検証"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: False)
        # 待機時間を短縮するため、time.sleep をモック
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)
        
        res = _unwrap(_e2e_conftest._wait_for_port)(9999, timeout=1)
        assert res is False

    def test_start_backend_port_in_use(self, monkeypatch):
        """ポートが既に使用中の場合、Popenを呼ばずにNoneをyieldすることを検証"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: True)
        
        popen_called = False
        import subprocess
        def mock_popen(*args, **kwargs):
            nonlocal popen_called
            popen_called = True
            return None
        monkeypatch.setattr(subprocess, "Popen", mock_popen)
        
        generator = _unwrap(_e2e_conftest._start_backend)()
        res = next(generator)
        assert res is None
        # yieldの後、ジェネレータを最後まで進める
        try:
            next(generator)
        except StopIteration:
            pass
        assert not popen_called

    def test_start_backend_success(self, monkeypatch):
        """正常に起動し、クリーンアップで terminate / wait が呼ばれることを検証"""
        # 初回（起動前）は未使用、その後（起動後）は使用中になるようにする
        port_state = [False, True]
        def mock_port_check(port):
            if port_state:
                return port_state.pop(0)
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        class MockProcess:
            def __init__(self):
                self.terminated = False
                self.waited = False
            def terminate(self):
                self.terminated = True
            def wait(self, timeout=None):
                self.waited = True
                return 0
        
        mock_proc = MockProcess()
        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_backend)()
        res = next(generator)
        assert res is mock_proc
        
        # クリーンアップ（ジェネレータの終了）
        try:
            next(generator)
        except StopIteration:
            pass
        
        assert mock_proc.terminated is True
        assert mock_proc.waited is True

    def test_start_backend_timeout_expired(self, monkeypatch):
        """クリーンアップ時のwaitがTimeoutExpiredになった場合、killが呼ばれることを検証"""
        port_state = [False, True]
        def mock_port_check(port):
            if port_state:
                return port_state.pop(0)
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        import subprocess
        class MockProcess:
            def __init__(self):
                self.terminated = False
                self.killed = False
            def terminate(self):
                self.terminated = True
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cmd", timeout)
            def kill(self):
                self.killed = True
        
        mock_proc = MockProcess()
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_backend)()
        res = next(generator)
        assert res is mock_proc
        
        try:
            next(generator)
        except StopIteration:
            pass
        
        assert mock_proc.terminated is True
        assert mock_proc.killed is True

    def test_start_backend_port_wait_timeout(self, monkeypatch):
        """起動後のポート待機でタイムアウトした場合、procを終了してRuntimeErrorを投げることを検証"""
        # 起動前も起動後も未使用のままにする
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: False)
        
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)
        
        class MockProcess:
            def __init__(self):
                self.terminated = False
            def terminate(self):
                self.terminated = True
        
        mock_proc = MockProcess()
        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_backend)()
        with pytest.raises(RuntimeError) as exc_info:
            next(generator)
        
        assert "Backend failed to start" in str(exc_info.value)
        assert mock_proc.terminated is True

    def test_start_frontend_success(self, monkeypatch):
        """Frontend サーバーの正常起動とクリーンアップ"""
        port_state = [False, True]
        def mock_port_check(port):
            if port_state:
                return port_state.pop(0)
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        class MockProcess:
            def __init__(self):
                self.terminated = False
                self.waited = False
            def terminate(self):
                self.terminated = True
            def wait(self, timeout=None):
                self.waited = True
                return 0
        
        mock_proc = MockProcess()
        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_frontend)()
        res = next(generator)
        assert res is mock_proc
        
        try:
            next(generator)
        except StopIteration:
            pass
        
        assert mock_proc.terminated is True
        assert mock_proc.waited is True

    def test_start_frontend_port_in_use(self, monkeypatch):
        """Frontend ポートが既に使用中の場合、起動をスキップ"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: True)
        
        popen_called = False
        import subprocess
        def mock_popen(*args, **kwargs):
            nonlocal popen_called
            popen_called = True
            return None
        monkeypatch.setattr(subprocess, "Popen", mock_popen)
        
        generator = _unwrap(_e2e_conftest._start_frontend)()
        res = next(generator)
        assert res is None
        try:
            next(generator)
        except StopIteration:
            pass
        assert not popen_called

    def test_start_frontend_port_wait_timeout(self, monkeypatch):
        """Frontend 起動後のポート待機タイムアウト"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: False)
        
        import time
        monkeypatch.setattr(time, "sleep", lambda x: None)
        
        class MockProcess:
            def __init__(self):
                self.terminated = False
            def terminate(self):
                self.terminated = True
        
        mock_proc = MockProcess()
        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_frontend)()
        with pytest.raises(RuntimeError) as exc_info:
            next(generator)
        
        assert "Frontend failed to start" in str(exc_info.value)
        assert mock_proc.terminated is True

    def test_start_frontend_timeout_expired(self, monkeypatch):
        """Frontend クリーンアップ時のwaitがTimeoutExpiredになった場合"""
        port_state = [False, True]
        def mock_port_check(port):
            if port_state:
                return port_state.pop(0)
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        import subprocess
        class MockProcess:
            def __init__(self):
                self.terminated = False
                self.killed = False
            def terminate(self):
                self.terminated = True
            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired("cmd", timeout)
            def kill(self):
                self.killed = True
        
        mock_proc = MockProcess()
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: mock_proc)
        
        generator = _unwrap(_e2e_conftest._start_frontend)()
        res = next(generator)
        assert res is mock_proc
        
        try:
            next(generator)
        except StopIteration:
            pass
        
        assert mock_proc.terminated is True
        assert mock_proc.killed is True

    def test_servers_fixture_success(self, monkeypatch):
        """servers フィクスチャが正常に動作する場合"""
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", lambda p: True)
        
        generator = _unwrap(_e2e_conftest.servers)(None, None)
        res = next(generator)
        assert res["backend"] == _e2e_conftest.BACKEND_URL
        assert res["frontend"] == _e2e_conftest.FRONTEND_URL
        
        try:
            next(generator)
        except StopIteration:
            pass

    def test_servers_fixture_backend_not_running(self, monkeypatch):
        """servers フィクスチャで backend が動いていない場合、AssertionError"""
        def mock_port_check(port):
            if port == _e2e_conftest.BACKEND_PORT:
                return False
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        generator = _unwrap(_e2e_conftest.servers)(None, None)
        with pytest.raises(AssertionError) as exc_info:
            next(generator)
        assert "Backend not running" in str(exc_info.value)

    def test_servers_fixture_frontend_not_running(self, monkeypatch):
        """servers フィクスチャで frontend が動いていない場合、AssertionError"""
        def mock_port_check(port):
            if port == _e2e_conftest.FRONTEND_PORT:
                return False
            return True
        monkeypatch.setattr(_e2e_conftest, "_is_port_in_use", mock_port_check)
        
        generator = _unwrap(_e2e_conftest.servers)(None, None)
        with pytest.raises(AssertionError) as exc_info:
            next(generator)
        assert "Frontend not running" in str(exc_info.value)

    def test_browser_context_args(self):
        """browser_context_args フィクスチャが正しい設定を返すか"""
        res = _unwrap(_e2e_conftest.browser_context_args)()
        assert res["viewport"]["width"] == 1920
        assert res["viewport"]["height"] == 1080
        assert res["ignore_https_errors"] is True

    def test_app_page_fixture(self, monkeypatch):
        """app_page フィクスチャが frontend の URL を開き、page を yield すること"""
        class MockPage:
            def __init__(self):
                self.goto_url = None
                self.goto_kwargs = None
            def goto(self, url, **kwargs):
                self.goto_url = url
                self.goto_kwargs = kwargs
                
        mock_page = MockPage()
        servers = {"frontend": "http://mock-frontend"}
        
        generator = _unwrap(_e2e_conftest.app_page)(mock_page, servers)
        res = next(generator)
        assert res is mock_page
        assert mock_page.goto_url == "http://mock-frontend"
        assert mock_page.goto_kwargs["wait_until"] == "networkidle"
        
        try:
            next(generator)
        except StopIteration:
            pass

    def test_pipeline_result(self):
        """pipeline_result フィクスチャが正しいモックデータを返すか"""
        res = _unwrap(_e2e_conftest.pipeline_result)()
        assert res["status"] == "success"
        assert res["video_id"] == "test_13s.mp4"
        assert len(res["segments"]) == 2

    def test_m36_q1_q6_compliance_non_m36(self, monkeypatch):
        """m36 マーカーのないテストではコンプライアンス検証がスキップされることを確認"""
        class MockNode:
            def __init__(self):
                self.name = "test_non_m36"
                self.obj = lambda: None
            def iter_markers(self):
                return []
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        res = next(generator)
        assert res is None
        try:
            next(generator)
        except StopIteration:
            pass

    def test_m36_compliance_success_non_g4(self, monkeypatch):
        """全ての基準を満たす m36 マーカー付きテスト (G4未満) が正常にパスすること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_valid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        monkeypatch.setattr(inspect, "getsource", lambda x: VALID_SOURCE)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        res = next(generator)
        assert res is None
        try:
            next(generator)
        except StopIteration:
            pass

    def test_m36_compliance_success_g4(self, monkeypatch):
        """全ての基準を満たし、かつ G4 以降で pipeline_result を含むテストが正常にパスすること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_g4_valid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        g4_valid_source = VALID_SOURCE + "\n# pipeline_result を含む\n"
        monkeypatch.setattr(inspect, "getsource", lambda x: g4_valid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        res = next(generator)
        assert res is None
        try:
            next(generator)
        except StopIteration:
            pass

    def test_m36_compliance_violation_l1_missing(self, monkeypatch):
        """L1 が欠けている場合に Q2:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L1: が欠けているソース
        invalid_source = VALID_SOURCE.replace("L1:", "LX:")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L1:セクションが存在しない" in str(exc.value)

    def test_m36_compliance_violation_l3_no_browser_op(self, monkeypatch):
        """L3セクションに実ブラウザ操作がない場合に Q2:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L3 から .click( や .fill( を削除したソース
        invalid_source = VALID_SOURCE.replace("el.first.click()", "pass").replace("el.first.fill(\"test value\")", "pass")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L3セクションに実Browser操作がない" in str(exc.value)

    def test_m36_compliance_violation_no_reverse_mapping(self, monkeypatch):
        """逆引きマッピングの記述がない場合に Q3:B 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # "逆引き:" を削除
        invalid_source = VALID_SOURCE.replace("逆引き:", "XXX:")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "逆引きマッピング(UX検証項目ID)が未記載" in str(exc.value)

    def test_m36_compliance_violation_fake_pass(self, monkeypatch):
        """偽PASSパターンが含まれている場合に Q5:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # assert True を含むソース
        invalid_source = VALID_SOURCE + "\n    assert True\n"
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "偽PASSパターン検出" in str(exc.value)

    def test_m36_compliance_violation_duplicate_assert(self, monkeypatch):
        """L1とL5で同一のアサーションが重複している場合に Q5:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L1 のアサーションを L5 に重複して書き加える
        invalid_source = VALID_SOURCE + "\n    # === L5: ===\n    assert el.count() == 1, \"L1-1\"\n"
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L1とL5で同一assertが重複" in str(exc.value)

    def test_m36_compliance_violation_g4_no_pipeline_result(self, monkeypatch):
        """G4以降のテストで pipeline_result も test_13s もない場合に Q4:B 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_g4_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # pipeline_result や test_13s を含まないソース
        invalid_source = VALID_SOURCE.replace("pipeline_result", "xxx").replace("test_13s", "xxx")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "G4以降のテストにpipeline_result/test_13sが未使用" in str(exc.value)

    def test_m36_compliance_violation_invalid_reverse_id_format(self, monkeypatch):
        """逆引きIDが0件の場合に Q3:B 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # 逆引きIDの形式を崩す (O1-L1-01 -> OX-L1-01)
        invalid_source = VALID_SOURCE.replace("O1-L1-01", "OX-L1-01").replace("O1-L2-03", "OX-L2-03")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "逆引きID(O*-L*-**形式)が0件" in str(exc.value)

    def test_m36_compliance_violation_insufficient_assert_count(self, monkeypatch):
        """各層の assert 数が不足している場合に Q5:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L1 の assert 2個のうち 1個を削除する
        invalid_source = VALID_SOURCE.replace("assert el.first.is_visible(), \"L1-2\"", "# comment out")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L1:のassert数が不足" in str(exc.value)

    def test_m36_compliance_violation_l4_no_transition(self, monkeypatch):
        """L4に状態遷移パターンがない場合に Q2:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L4 から before_text や after_text や != を削除する
        invalid_source = VALID_SOURCE.replace("before_text", "some_val").replace("after_text", "other_val").replace("!=", "==")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L4セクションに構造的な状態遷移パターンがない" in str(exc.value)

    def test_m36_compliance_violation_l5_insufficient_ops(self, monkeypatch):
        """L5に Browser 操作が2つ未満の場合に Q2:C 違反を検出すること"""
        import inspect
        class MockNode:
            def __init__(self):
                self.name = "test_e2e_m36_o1_invalid"
                def dummy_func():
                    pass
                self.obj = dummy_func
            def iter_markers(self):
                class Marker:
                    name = "m36"
                return [Marker()]
                
        class MockRequest:
            def __init__(self):
                self.node = MockNode()
                
        # L5 から Browser 操作を 1つにする (clickとfillがあるので、両方 click だったのを 1個削除)
        invalid_source = VALID_SOURCE.replace("el.first.fill(\"final\")", "pass")
        monkeypatch.setattr(inspect, "getsource", lambda x: invalid_source)
        
        mock_request = MockRequest()
        generator = _unwrap(_e2e_conftest.m36_q1_q6_compliance)(mock_request)
        with pytest.raises(AssertionError) as exc:
            next(generator)
        assert "L5にBrowser操作が1個しかない" in str(exc.value)
