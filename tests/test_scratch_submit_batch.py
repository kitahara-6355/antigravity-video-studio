import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def test_backend_scratch_submit_batch_success(capsys):
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    dummy_status = {"status": "running", "progress": 0.5}
    mock_hub.generate_flash_status.return_value = dummy_status

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            import backend.scratch.submit_batch
            backend.scratch.submit_batch.main()
    finally:
        sys.path = original_path

    mock_hub.flash_update_heartbeat.assert_called_once()
    mock_hub.submit_batch_report.assert_called_once_with(
        "batch_769699",
        {
            "passed": 18,
            "failed": 0,
            "skipped": 12,
            "total": 30
        }
    )
    mock_hub.generate_flash_status.assert_called_once()

    captured = capsys.readouterr()
    assert "STATUS_START" in captured.out
    assert "STATUS_END" in captured.out
    assert '"status": "running"' in captured.out
    assert '"progress": 0.5' in captured.out

def test_backend_scratch_submit_batch_exception():
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    mock_hub.flash_update_heartbeat.side_effect = Exception("Hub Connection Error")

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            with pytest.raises(Exception) as excinfo:
                import backend.scratch.submit_batch
                backend.scratch.submit_batch.main()
            assert "Hub Connection Error" in str(excinfo.value)
    finally:
        sys.path = original_path

def test_backend_scratch_submit_batch_sys_path():
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"status": "ok"}
    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            import backend.scratch.submit_batch
            # 2026-07-26: 以前は sys.path にディレクトリ名 "video-automation" が
            # 含まれることを前提にしていたが、これは開発機のフォルダ名に依存する。
            # CI のチェックアウト先は antigravity-video-studio なので一致せず失敗していた。
            # 検証したいのは「プロジェクトルートが追加され、古いハードコードパスが
            # 残っていないこと」なので、実際のリポジトリルートで判定する。
            repo_root = str(Path(backend.scratch.submit_batch.__file__).resolve().parents[2])
            normalized = {os.path.normcase(os.path.abspath(p)) for p in sys.path if p}
            assert os.path.normcase(repo_root) in normalized
            assert "C:/Users/PC_User/Desktop/script/video-automation" not in sys.path
    finally:
        sys.path = original_path

def test_backend_scratch_submit_batch_report_exception():
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    mock_hub.submit_batch_report.side_effect = Exception("Report Submission Failed")

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            with pytest.raises(Exception) as excinfo:
                import backend.scratch.submit_batch
                backend.scratch.submit_batch.main()
            assert "Report Submission Failed" in str(excinfo.value)
    finally:
        sys.path = original_path

def test_backend_scratch_submit_batch_status_exception():
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]

    mock_hub = MagicMock()
    mock_hub.generate_flash_status.side_effect = Exception("Status Generation Failed")

    original_path = sys.path.copy()

    try:
        with patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub):
            with pytest.raises(Exception) as excinfo:
                import backend.scratch.submit_batch
                backend.scratch.submit_batch.main()
            assert "Status Generation Failed" in str(excinfo.value)
    finally:
        sys.path = original_path


# --- 以下は 2026-07-25 に置き換え ---------------------------------------------
# 旧 test_scratch_submit_batch_* 4件は、sys.argv から batch_id を読み
# get_queue_status() で集計し "BATCH_SUBMITTED" を出力する実装を前提としていたが、
# その実装は backend/scratch/submit_batch.py の全バージョンに存在しない
# （BATCH_SUBMITTED は mark_and_submit_batch*.py 等の別モジュールの挙動）。
# 上の test_backend_scratch_submit_batch_* 5件が実装を正しく覆っているため、
# 重複を避け、既存テストが検証していない実挙動に置き換えた。


def _import_submit_batch_with(mock_hub):
    """OrchestrationHub を差し替えた状態で submit_batch を読み込むヘルパー。"""
    if "backend.scratch.submit_batch" in sys.modules:
        del sys.modules["backend.scratch.submit_batch"]
    return patch("backend.agents.orchestration.OrchestrationHub", return_value=mock_hub)


def test_backend_scratch_submit_batch_call_order():
    """heartbeat → submit_batch_report → generate_flash_status の順で呼ばれること。

    順序が入れ替わると、ハートビート未更新のままレポートが送られたり、
    レポート反映前の状態が出力されたりする。
    """
    calls = []
    mock_hub = MagicMock()
    mock_hub.flash_update_heartbeat.side_effect = lambda *a, **k: calls.append("heartbeat")
    mock_hub.submit_batch_report.side_effect = lambda *a, **k: calls.append("report")
    mock_hub.generate_flash_status.side_effect = lambda *a, **k: (calls.append("status"), {})[1]

    original_path = sys.path.copy()
    try:
        with _import_submit_batch_with(mock_hub):
            import backend.scratch.submit_batch
            backend.scratch.submit_batch.main()
    finally:
        sys.path = original_path

    assert calls == ["heartbeat", "report", "status"]


def test_backend_scratch_submit_batch_emits_parsable_json_between_markers(capsys):
    """STATUS_START と STATUS_END の間が、そのまま JSON として解析できること。

    このマーカーは呼び出し側が標準出力から状態を切り出すための境界なので、
    間に余計な出力が混ざると連携が壊れる。
    """
    import json

    mock_hub = MagicMock()
    payload = {"phase": 2, "milestone": "M2.1", "tasks": [1, 2, 3]}
    mock_hub.generate_flash_status.return_value = payload

    original_path = sys.path.copy()
    try:
        with _import_submit_batch_with(mock_hub):
            import backend.scratch.submit_batch
            backend.scratch.submit_batch.main()
    finally:
        sys.path = original_path

    out = capsys.readouterr().out
    body = out.split("STATUS_START", 1)[1].split("STATUS_END", 1)[0]
    assert json.loads(body) == payload


def test_backend_scratch_submit_batch_keeps_japanese_unescaped(capsys):
    """ensure_ascii=False により日本語がエスケープされずに出力されること。"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"note": "ハングタスク検知"}

    original_path = sys.path.copy()
    try:
        with _import_submit_batch_with(mock_hub):
            import backend.scratch.submit_batch
            backend.scratch.submit_batch.main()
    finally:
        sys.path = original_path

    out = capsys.readouterr().out
    assert "ハングタスク検知" in out
    # \uXXXX \u5f62\u5f0f\u306b\u30a8\u30b9\u30b1\u30fc\u30d7\u3055\u308c\u3066\u3044\u306a\u3044\u3053\u3068\uff08\u30d0\u30c3\u30af\u30b9\u30e9\u30c3\u30b7\u30e5\u3092\u66f8\u304b\u305a\u306b\u691c\u8a3c\uff09
    assert "u30cf" not in out.lower()


def test_backend_scratch_submit_batch_output_is_indented(capsys):
    """indent=2 で整形出力されること（1行に潰れていないこと）。"""
    mock_hub = MagicMock()
    mock_hub.generate_flash_status.return_value = {"a": 1, "b": 2}

    original_path = sys.path.copy()
    try:
        with _import_submit_batch_with(mock_hub):
            import backend.scratch.submit_batch
            backend.scratch.submit_batch.main()
    finally:
        sys.path = original_path

    body = capsys.readouterr().out.split("STATUS_START", 1)[1].split("STATUS_END", 1)[0]
    assert '\n  "a": 1' in body
