"""
E2E テスト — Playwright 基盤 conftest.py

Phase 3 M3.1: Playwright 完全自動化
- Backend (uvicorn) + Frontend (vite dev) をサブプロセスで起動
- session スコープで1回のみ起動、全E2Eテスト終了後にクリーンアップ
- headless=True, viewport=1920x1080

注意: Playwright は ProactorEventLoop を必要とするため、
親 conftest.py の WindowsSelectorEventLoopPolicy を E2E テストでは
上書きする。
"""

import os
import sys
import time
import signal
import socket
import asyncio
import subprocess
import pytest
from pathlib import Path


# ─── Windows asyncio: Playwright は ProactorEventLoop 必須 ───
# 親 conftest.py が SelectorEventLoop に切り替えているが、
# Playwright の subprocess 起動に ProactorEventLoop が必要。
# E2E テスト実行時のみデフォルトポリシーに戻す。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())


# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

BACKEND_PORT = 8000
FRONTEND_PORT = 5173
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"



def _is_port_in_use(port: int) -> bool:
    """ポートが使用中か確認（127.0.0.1 のみチェック）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            return False


def _wait_for_port(port: int, timeout: int = 60) -> bool:
    """ポートが開くまで待機"""
    start = time.time()
    while time.time() - start < timeout:
        if _is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def _start_backend():
    """Backend サーバーを起動（既に起動中ならスキップ）"""
    if _is_port_in_use(BACKEND_PORT):
        yield None  # 既に起動中 — 外部管理
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
        cwd=str(BACKEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    if not _wait_for_port(BACKEND_PORT, timeout=60):
        proc.terminate()
        raise RuntimeError(f"Backend failed to start on port {BACKEND_PORT}")

    yield proc

    # クリーンアップ
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def _start_frontend():
    """Frontend dev サーバーを起動（既に起動中ならスキップ）"""
    if _is_port_in_use(FRONTEND_PORT):
        yield None  # 既に起動中 — 外部管理
        return

    proc = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT), "--host", "127.0.0.1"],
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    if not _wait_for_port(FRONTEND_PORT, timeout=60):
        proc.terminate()
        raise RuntimeError(f"Frontend failed to start on port {FRONTEND_PORT}")

    yield proc

    # クリーンアップ
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def servers(_start_backend, _start_frontend):
    """Backend + Frontend が両方起動した状態を保証"""
    assert _is_port_in_use(BACKEND_PORT), f"Backend not running on port {BACKEND_PORT}"
    assert _is_port_in_use(FRONTEND_PORT), f"Frontend not running on port {FRONTEND_PORT}"
    yield {"backend": BACKEND_URL, "frontend": FRONTEND_URL}


@pytest.fixture(scope="session")
def browser_context_args():
    """pytest-playwright のブラウザコンテキスト設定"""
    return {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


@pytest.fixture
def app_page(page, servers):
    """
    アプリケーションのトップページを開いた状態の page fixture。
    servers fixture により Backend + Frontend の起動を保証。
    """
    page.goto(servers["frontend"], wait_until="networkidle")
    yield page


@pytest.fixture(scope="module")
def pipeline_result():
    """テスト用のパイプライン処理結果ダミーデータ"""
    return {
        "status": "success",
        "video_id": "test_13s.mp4",
        "segments": [
            {"id": 1, "start": 0.0, "end": 5.0, "text": "こんにちは", "keep": True},
            {"id": 2, "start": 5.0, "end": 10.0, "text": "テストです", "keep": True}
        ]
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Q1-Q6 コンプライアンス強制チェッカー  v2.0 (2026-05-05)
#
# ユーザー決定(設計チャット 04f613b9):
#   Q1:C 傾斜配分, Q2:C 5層分解, Q3:B 逆引き,
#   Q4:B 実走行, Q5:C 二重偽PASS防止, Q6:C 横断追加
#
# このチェッカーは @pytest.mark.m36 マーカー付きテストに対し、
# テスト関数のソースコードを静的解析してQ1-Q6準拠を強制する。
# 違反が検出された場合、テストは即座にFAILする。
#
# BP-2: レイヤーマーカー形式は以下に統一すること:
#   # === L*: [層名] ([N] assertions) ===
#   他の形式(「# L3:」等)は使用禁止。_get_layer_sectionの
#   パーサーがこの形式を前提としている。
#
# BP-5 変更履歴:
#   v1.0 (2026-05-03): 初版。6ルール。
#   v1.1 (2026-05-03): 10ルールに拡張(min_assert/逆引きID/L4遷移/L5操作)。
#   v2.0 (2026-05-05): BP-2/4/5対処。L4構造チェック強化、_L3_OPS拡張、
#                       偽PASSコメント除外、G4+正規表現簡潔化。
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import inspect
import re

# Q2:C — 5層マーカー (各層がコメントとして存在すること)
_LAYER_MARKERS = ["L1:", "L2:", "L3:", "L4:", "L5:"]

# Q2:C — L3必須: 実Browser操作キーワード
# BP-2準拠: レビュー指摘の5操作を追加 (.select_option/.check/.uncheck/.hover/.dblclick)
_L3_OPS = [
    ".click(", ".fill(", ".drag_to(", ".press(", "mouse.",
    ".select_option(", ".check(", ".uncheck(", ".hover(", ".dblclick(",
]

# Q5:C — 偽PASSパターン (テストソースに含まれていたらFAIL)
# コメント行(#で始まる行)は除外して検査する
_FAKE_PASS_PATTERNS = [
    r"\bassert\s+True\b",         # assert True (無条件PASS)
    r"\bor\s+True\b",             # or True (条件バイパス)
    r">=\s*0[,\s\)]",             # >= 0 (count等で常にTrue)
]


def _strip_comments(source: str) -> str:
    """ソースコードからコメント行を除外する(偽PASS誤検知防止)"""
    return "\n".join(
        line for line in source.split("\n")
        if not line.strip().startswith("#")
    )


def _get_layer_section(source: str, layer: str) -> str:
    """テストソースからL*:セクションの行を抽出"""
    lines = source.split("\n")
    in_section = False
    section = []
    for line in lines:
        if f"=== {layer}" in line or f"# {layer}" in line:
            in_section = True
            continue
        if in_section:
            if any(f"=== L" in line or f"# L" in line
                   for m in _LAYER_MARKERS if m != layer):
                # 次の層に到達
                if any(f"=== {m.replace(':', '')}" in line or f"# {m}" in line
                       for m in _LAYER_MARKERS if m != layer):
                    break
            section.append(line)
    return "\n".join(section)


@pytest.fixture(autouse=True)
def m36_q1_q6_compliance(request):
    """M3.6テストのQ1-Q6コンプライアンスを自動検証

    このフィクスチャは @pytest.mark.m36 マーカー付きテストにのみ適用。
    テスト関数のソースコードを静的解析し、以下を検証:
      Q2:C — L1-L5の5層全てがコメントとして存在すること
      Q2:C — L3セクションに実Browser操作(click/fill/drag/press)が含まれること
      Q3:B — docstringに逆引きマッピングが存在すること
      Q5:C — 偽PASSパターンが含まれていないこと
    """
    markers = [m.name for m in request.node.iter_markers()]
    if "m36" not in markers:
        yield
        return

    test_func = request.node.obj
    source = inspect.getsource(test_func)
    test_name = request.node.name
    docstring = test_func.__doc__ or ""

    # ── Q2:C 検証: 5層全てが存在するか ──
    for layer in _LAYER_MARKERS:
        assert layer in source, \
            f"【Q2:C違反】{test_name}: {layer}セクションが存在しない。" \
            f"設計書§3.1: '1 AC = 5検証項目 (L1〜L5各1項目)' — 全5層必須。"

    # ── Q2:C 検証: L3に実Browser操作が含まれるか ──
    l3_section = _get_layer_section(source, "L3:")
    has_browser_op = any(op in l3_section for op in _L3_OPS)
    assert has_browser_op, \
        f"【Q2:C違反】{test_name}: L3セクションに実Browser操作がない。" \
        f"設計書§3.2 L3定義: 'click() / fill() / drag_to()' — 実操作必須。"

    # ── Q3:B 検証: 逆引きマッピングが存在するか ──
    assert "逆引き:" in docstring or "逆引き:" in source, \
        f"【Q3:B違反】{test_name}: 逆引きマッピング(UX検証項目ID)が未記載。" \
        f"テンプレートルール1: 'UX検証項目マッピング (O*-L*-** 形式)' — 必須。"

    # ── Q5:C 検証: 偽PASSパターンがないか (コメント行除外) ──
    source_no_comments = _strip_comments(source)
    for pattern in _FAKE_PASS_PATTERNS:
        match = re.search(pattern, source_no_comments)
        assert match is None, \
            f"【Q5:C違反】{test_name}: 偽PASSパターン検出 '{match.group()}' (位置:{match.start()})。" \
            f"設計書§5.1: 'assert True / or True / ヘルスチェック代替' — 禁止。"

    # ── Q5:C 拡張: L1/L5間の重複アサーション検出 ──
    l1_section = _get_layer_section(source, "L1:")
    l5_section = _get_layer_section(source, "L5:")
    l1_asserts = set(
        line.strip() for line in l1_section.split("\n")
        if line.strip().startswith("assert ")
    )
    l5_asserts = set(
        line.strip() for line in l5_section.split("\n")
        if line.strip().startswith("assert ")
    )
    duplicates = l1_asserts & l5_asserts
    assert len(duplicates) == 0, \
        f"【Q5:C違反】{test_name}: L1とL5で同一assertが重複: {duplicates}。" \
        f"L5は新しい検証を含むべき(L1の再確認は水増し)。"

    # ── Q4:B 検証: G4以降のテストにはpipeline_result使用を強制 ──
    # G1-G3は Phase A 前のテストなのでスキップ
    # G4以降(WebSocket進捗等)はPhase Aの実走行データが必須
    # v2.0: 正規表現で G4+ を検出 (個別リスト不要)
    g_match = re.search(r'_g(\d+)_', test_name)
    if g_match and int(g_match.group(1)) >= 4:
        assert "pipeline_result" in source or "test_13s" in source, \
            f"【Q4:B違反】{test_name}: G4以降のテストにpipeline_result/test_13sが未使用。" \
            f"設計書§4.2: Phase Aの実走行データを使用すること。"

    # ── Q3:B 強化: 逆引きIDの形式・数量検証 (G2対策) ──
    # 「逆引き:」文字列だけでなく O*-L*-** または A*-L*-** 形式のIDが実在するか検証
    reverse_ids = re.findall(r'[OA]\d+-L\d+-\d+', docstring + source)
    assert len(reverse_ids) >= 1, \
        f"【Q3:B違反】{test_name}: 逆引きID(O*-L*-**形式)が0件。" \
        f"設計書テンプレートルール1: 'O1-L1-05'等のIDを1つ以上記載すること。"

    # ── Q5:C 強化: 各層min_assertカウント検証 (G4対策) ──
    # 設計書§5.1: L1:2, L2:2, L3:3, L4:3, L5:4 = 最低14アサーション
    _MIN_ASSERTS = {"L1:": 2, "L2:": 2, "L3:": 3, "L4:": 3, "L5:": 4}
    for layer, min_count in _MIN_ASSERTS.items():
        section = _get_layer_section(source, layer)
        actual = sum(1 for line in section.split("\n")
                     if line.strip().startswith("assert "))
        assert actual >= min_count, \
            f"【Q5:C違反】{test_name}: {layer}のassert数が不足 " \
            f"({actual} < {min_count})。設計書min_assert定義に違反。"

    # ── Q2:C 強化: L4に状態遷移パターンが含まれるか (G5対策) ──
    # BP-4 v2.0: キーワードマッチから構造チェックに強化。
    # L4は「操作前後のDOM変化」を検証する層。
    # 方式1: before_*/after_* 変数ペアの存在(最も確実)
    # 方式2: != 比較演算子の存在(before/afterの比較)
    # 方式3: before/after キーワードペアの存在(コメント含む)
    l4_section = _get_layer_section(source, "L4:")
    l4_code_lines = [l for l in l4_section.split("\n")
                     if l.strip() and not l.strip().startswith("#")]
    l4_code = "\n".join(l4_code_lines)
    # 方式1: before_/after_ 変数名の存在(最も厳格)
    has_before_var = bool(re.search(r'\bbefore_\w+', l4_code))
    has_after_var = bool(re.search(r'\bafter_\w+', l4_code))
    # 方式2: != 比較の存在
    has_ne_compare = "!=" in l4_code
    l4_has_transition = (
        (has_before_var and has_after_var) or  # before_x / after_x ペア
        (has_ne_compare and (has_before_var or has_after_var))  # != + 片方の変数
    )
    assert l4_has_transition, \
        f"【Q2:C違反】{test_name}: L4セクションに構造的な状態遷移パターンがない。" \
        f"L4には before_*/after_* 変数ペアまたは != 比較が必要。" \
        f"コメントだけのキーワードでは通過しない(BP-4 v2.0)。"

    # ── Q2:C 強化: L5に複数操作シーケンスが含まれるか (G6対策) ──
    # L5は「複数操作→最終状態」の一気通貫検証。Browser操作が2つ以上必要。
    l5_op_count = sum(1 for op in _L3_OPS if op in l5_section)
    assert l5_op_count >= 2, \
        f"【Q2:C違反】{test_name}: L5にBrowser操作が{l5_op_count}個しかない。" \
        f"L5は '複数操作シーケンス→最終状態' (最低2操作)を含むべき。"

    yield


# ─────────────────────────────────────────────────────────────────────────
# E2E 成果自動収集フック (Phase 42)
#
# pytestの各テスト終了時に呼び出され、逆引きIDとPASS/FAIL状態を
# `e2e_results.json` に動的に書き出す。
# ─────────────────────────────────────────────────────────────────────────

_E2E_ACCUMULATED_RESULTS = {
    "dom_checks": {},
    "visual_checks": {},
    "interaction_checks": {},
    "state_checks": {},
    "e2e_checks": {},
    "screenshots": {}
}

_LAYER_KEY_MAP = {
    1: "dom_checks",
    2: "visual_checks",
    3: "interaction_checks",
    4: "state_checks",
    5: "e2e_checks"
}

def pytest_runtest_makereport(item, call):
    """各テストステップの実行結果フック"""
    import inspect
    import json
    if call.when == "call":
        # テスト関数のソースとdocstringを取得
        try:
            source = inspect.getsource(item.obj)
            docstring = inspect.getdoc(item.obj) or ""
        except Exception:
            source = ""
            docstring = ""

        # 逆引きID（例: O1-L2-03）を抽出
        reverse_ids = re.findall(r'([OA]\d+)-L(\d+)-(\d+)', docstring + source)
        
        passed = not call.excinfo
        
        # 該当する層の結果にアサイン
        for story_id, layer_str, item_no in reverse_ids:
            layer = int(layer_str)
            item_id = f"{story_id}-L{layer_str}-{item_no}"
            key = _LAYER_KEY_MAP.get(layer)
            if key:
                _E2E_ACCUMULATED_RESULTS[key][item_id] = passed

        # 結果をファイルにフラッシュ（アトミック書き込み、既存結果があればマージ）
        results_path = Path(PROJECT_ROOT) / "backend" / "tests" / "e2e_results.json"
        
        current_data = {
            "dom_checks": {},
            "visual_checks": {},
            "interaction_checks": {},
            "state_checks": {},
            "e2e_checks": {},
            "screenshots": {}
        }
        if results_path.exists():
            try:
                loaded = json.loads(results_path.read_text(encoding="utf-8"))
                for k in current_data.keys():
                    if k in loaded:
                        current_data[k].update(loaded[k])
            except Exception:
                pass

        # 今回の結果をマージ
        for k, v in _E2E_ACCUMULATED_RESULTS.items():
            current_data[k].update(v)

        try:
            results_path.write_text(
                json.dumps(current_data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            print(f"Failed to write e2e_results.json: {e}", file=sys.stderr)


