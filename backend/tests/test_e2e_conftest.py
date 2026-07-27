import sys
from pathlib import Path
import pytest
import subprocess
from unittest.mock import MagicMock, patch

# sys.path に project root を追加してパッケージとしてインポート可能にする
tests_dir = Path(__file__).resolve().parent
project_root = tests_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.tests.e2e import conftest as e2e_conftest


# ─── 1. ポート監視関数のテスト ───

def test_is_port_in_use():
    with patch("socket.socket") as mock_socket:
        mock_s = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_s
        
        # 接続拒否 (ポートは空いている)
        mock_s.connect.side_effect = ConnectionRefusedError()
        assert e2e_conftest._is_port_in_use(8000) is False
        
        # 接続成功 (ポートは使用中)
        mock_s.connect.side_effect = None
        assert e2e_conftest._is_port_in_use(8000) is True


def test_wait_for_port():
    # すぐにポートが開くケース
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=True):
        assert e2e_conftest._wait_for_port(8000, timeout=1) is True
        
    # タイムアウトするケース
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("time.sleep") as mock_sleep:
        assert e2e_conftest._wait_for_port(8000, timeout=1) is False


# ─── 2. サーバー起動フィクスチャのテスト (Popenモック安全規約準拠) ───

def test_start_backend_already_in_use():
    # すでに起動中の場合は何もしない
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=True):
        gen = e2e_conftest._start_backend.__wrapped__()
        proc = next(gen)
        assert proc is None
        with pytest.raises(StopIteration):
            next(gen)


def test_start_backend_success():
    # 正常起動ケース
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout.readline.return_value = b""
    mock_proc.stderr.readline.return_value = b""
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc) as mock_popen,          patch("backend.tests.e2e.conftest._wait_for_port", return_value=True):
         
        gen = e2e_conftest._start_backend.__wrapped__()
        proc = next(gen)
        assert proc == mock_proc
        mock_popen.assert_called_once()
        
        # クリーンアップ実行
        try:
            next(gen)
        except StopIteration:
            pass
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=10)


def test_start_backend_timeout():
    # 起動タイムアウトでエラーになるケース
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc),          patch("backend.tests.e2e.conftest._wait_for_port", return_value=False):
         
        gen = e2e_conftest._start_backend.__wrapped__()
        with pytest.raises(RuntimeError) as excinfo:
            next(gen)
        assert "Backend failed to start" in str(excinfo.value)
        mock_proc.terminate.assert_called_once()


def test_start_backend_timeout_expired():
    # wait()でタイムアウトし、kill()されるケース
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="uvicorn", timeout=10)
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc),          patch("backend.tests.e2e.conftest._wait_for_port", return_value=True):
         
        gen = e2e_conftest._start_backend.__wrapped__()
        proc = next(gen)
        assert proc == mock_proc
        
        try:
            next(gen)
        except StopIteration:
            pass
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=10)
        mock_proc.kill.assert_called_once()


def test_start_frontend_already_in_use():
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=True):
        gen = e2e_conftest._start_frontend.__wrapped__()
        proc = next(gen)
        assert proc is None
        with pytest.raises(StopIteration):
            next(gen)


def test_start_frontend_success():
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout.readline.return_value = b""
    mock_proc.stderr.readline.return_value = b""
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc) as mock_popen,          patch("backend.tests.e2e.conftest._wait_for_port", return_value=True):
         
        gen = e2e_conftest._start_frontend.__wrapped__()
        proc = next(gen)
        assert proc == mock_proc
        
        try:
            next(gen)
        except StopIteration:
            pass
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=10)


def test_start_frontend_timeout():
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc),          patch("backend.tests.e2e.conftest._wait_for_port", return_value=False):
         
        gen = e2e_conftest._start_frontend.__wrapped__()
        with pytest.raises(RuntimeError) as excinfo:
            next(gen)
        assert "Frontend failed to start" in str(excinfo.value)
        mock_proc.terminate.assert_called_once()


def test_start_frontend_timeout_expired():
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="npm", timeout=10)
    
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=False),          patch("subprocess.Popen", return_value=mock_proc),          patch("backend.tests.e2e.conftest._wait_for_port", return_value=True):
         
        gen = e2e_conftest._start_frontend.__wrapped__()
        proc = next(gen)
        assert proc == mock_proc
        
        try:
            next(gen)
        except StopIteration:
            pass
        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called_once_with(timeout=10)
        mock_proc.kill.assert_called_once()


# ─── 3. その他の基本的なフィクスチャのテスト ───

def test_servers_fixture():
    with patch("backend.tests.e2e.conftest._is_port_in_use", return_value=True):
        gen = e2e_conftest.servers.__wrapped__(None, None)
        res = next(gen)
        assert res["backend"] == "http://127.0.0.1:8000"
        assert res["frontend"] == "http://127.0.0.1:5173"
        try:
            next(gen)
        except StopIteration:
            pass


def test_browser_context_args():
    res = e2e_conftest.browser_context_args.__wrapped__()
    assert "viewport" in res
    assert res["viewport"]["width"] == 1920
    assert res["ignore_https_errors"] is True


def test_app_page():
    mock_page = MagicMock()
    servers = {"frontend": "http://127.0.0.1:5173"}
    gen = e2e_conftest.app_page.__wrapped__(mock_page, servers)
    res = next(gen)
    assert res == mock_page
    mock_page.goto.assert_called_once_with("http://127.0.0.1:5173", wait_until="networkidle")
    try:
        next(gen)
    except StopIteration:
        pass


def test_pipeline_result():
    res = e2e_conftest.pipeline_result.__wrapped__()
    assert res["status"] == "success"
    assert len(res["segments"]) == 2


# ─── 4. Q1-Q6 Compliance Checker フィクスチャのテスト ───

class DummyRequestNode:
    def __init__(self, test_func, markers):
        self.node = MagicMock()
        self.node.obj = test_func
        self.node.name = test_func.__name__
        
        mock_marker = MagicMock()
        mock_marker.name = "m36" if "m36" in markers else "other"
        self.node.iter_markers.return_value = [mock_marker]


def run_compliance_fixture(test_func, markers):
    req = DummyRequestNode(test_func, markers)
    gen = e2e_conftest.m36_q1_q6_compliance.__wrapped__(req)
    next(gen)
    try:
        next(gen)
    except StopIteration:
        pass


# 正常にクリアするダミーテスト定義
# O1-L1-05
def dummy_valid_test():
    """
    テスト説明
    逆引き: O1-L1-05
    """
    # === L1: L1セクション ===
    val1 = 1
    val2 = 2
    assert val1 == 1
    assert val2 == 2
    # === L2: L2セクション ===
    val3 = 3
    val4 = 4
    assert val3 == 3
    assert val4 == 4
    # === L3: L3セクション ===
    op1 = ".click("
    op2 = ".fill("
    op3 = ".press("
    assert op1 is not None
    assert op2 is not None
    assert op3 is not None
    # === L4: L4セクション ===
    before_val = 1
    after_val = 2
    assert before_val != after_val
    assert before_val == 1
    assert after_val == 2
    # === L5: L5セクション ===
    op1_l5 = ".click("
    op2_l5 = ".fill("
    assert op1_l5 is not None
    assert op2_l5 is not None
    val5 = 5
    val6 = 6
    assert val5 == 5
    assert val6 == 6


def test_compliance_no_m36_marker():
    def some_other_test():
        pass
    run_compliance_fixture(some_other_test, markers=[])


def test_compliance_valid_test():
    run_compliance_fixture(dummy_valid_test, markers=["m36"])


def test_compliance_missing_layers():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: L1セクション ===
        assert 1 == 1
        assert 2 == 2
        # === L2: L2セクション ===
        assert 3 == 3
        assert 4 == 4
        # === L3: L3セクション ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: L4セクション ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "L5:セクションが存在しない" in str(excinfo.value)


def test_compliance_missing_browser_ops_l3():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        assert 5 == 5
        assert 6 == 6
        assert 7 == 7
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1 = ".click("
        op2 = ".fill("
        assert op1 is not None
        assert op2 is not None
        assert 8 == 8
        assert 9 == 9

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "L3セクションに実Browser操作がない" in str(excinfo.value)


def test_compliance_missing_reverse_mapping():
    def dummy_invalid_test():
        """
        逆引きIDが欠損している
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 5 == 5
        assert 6 == 6

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "逆引きマッピング" in str(excinfo.value) or "逆引きID" in str(excinfo.value)


def test_compliance_fake_pass_pattern():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 5 == 5
        assert True

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "偽PASSパターン検出" in str(excinfo.value)


def test_compliance_duplicate_assertion():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 1 == 1
        assert 6 == 6

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "同一assertが重複" in str(excinfo.value)


def test_compliance_g4_no_pipeline_result():
    # O1-L1-05
    def test_g4_dummy():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 5 == 5
        assert 6 == 6

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(test_g4_dummy, markers=["m36"])
    assert "pipeline_result/test_13sが未使用" in str(excinfo.value)


def test_compliance_invalid_reverse_id():
    # O1-L1-X
    def dummy_invalid_test():
        """
        逆引き: IDが適切な形式ではない
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 5 == 5
        assert 6 == 6

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "逆引きID(O*-L*-**形式)が0件" in str(excinfo.value)


def test_compliance_insufficient_asserts():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "assert数が不足" in str(excinfo.value)


def test_compliance_missing_transition_l4():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        val_x = 1
        val_y = 2
        assert val_x == 1
        assert val_y == 2
        assert val_x < val_y
        # === L5: ===
        op1_l5 = ".click("
        op2_l5 = ".fill("
        assert op1_l5 is not None
        assert op2_l5 is not None
        assert 5 == 5
        assert 6 == 6

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "L4セクションに構造的な状態遷移パターンがない" in str(excinfo.value)


def test_compliance_insufficient_ops_l5():
    # O1-L1-05
    def dummy_invalid_test():
        """
        逆引き: O1-L1-05
        """
        # === L1: ===
        assert 1 == 1
        assert 2 == 2
        # === L2: ===
        assert 3 == 3
        assert 4 == 4
        # === L3: ===
        op1 = ".click("
        op2 = ".fill("
        op3 = ".press("
        assert op1 is not None
        assert op2 is not None
        assert op3 is not None
        # === L4: ===
        before_val = 1
        after_val = 2
        assert before_val != after_val
        assert before_val == 1
        assert after_val == 2
        # === L5: ===
        op1_l5 = ".click("
        assert op1_l5 is not None
        assert 5 == 5
        assert 6 == 6
        assert 7 == 7

    with pytest.raises(AssertionError) as excinfo:
        run_compliance_fixture(dummy_invalid_test, markers=["m36"])
    assert "L5にBrowser操作が" in str(excinfo.value)


# ─── 5. 追加カバレッジ改善用のテスト ───

def test_platform_not_win32():
    import importlib
    # sys.platform を 'linux' にモックし、asyncio.set_event_loop_policy が呼ばれないことを確認
    with patch("sys.platform", "linux"), \
         patch("asyncio.set_event_loop_policy") as mock_set_policy:
        importlib.reload(e2e_conftest)
        mock_set_policy.assert_not_called()

    # テスト後に元の状態（win32）でリロードして、元の状態に戻しておく
    importlib.reload(e2e_conftest)


def test_get_layer_section_partial_marker_match():
    # ターゲットレイヤーが L1: のとき、
    # # L2 という他のレイヤー名を含むが、正規の終了マーカー形式ではない行がある場合、
    # 232行目の any(...) は True になり、235行目の any(...) は False になる。
    # この場合、break せずにその行が section に追加される。
    source = (
        "# === L1: ===\n"
        "assert 1 == 1\n"
        "# L2 を含むが正規マーカーではないコメント\n"
        "assert 2 == 2\n"
        "# === L2: ===\n"
        "assert 3 == 3"
    )
    res = e2e_conftest._get_layer_section(source, "L1:")
    
    # 期待される結果: 
    # "# L2 を含むが正規マーカーではないコメント" が含まれ、
    # "# === L2: ===" に到達した時点で break すること。
    expected = (
        "assert 1 == 1\n"
        "# L2 を含むが正規マーカーではないコメント\n"
        "assert 2 == 2"
    )
    assert res == expected

