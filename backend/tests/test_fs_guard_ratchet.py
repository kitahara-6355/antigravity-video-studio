"""fs_guard ラチェットの鍵の作り方のテスト。

ラチェットが機能するかどうかは、ほぼ「鍵が実行のたびに変わらないか」で決まる。
変わる鍵を1つ混ぜるだけで毎回「新規パス」が出て恒常的に赤くなり、
そうなったラチェットは誰も見なくなる。逆に伏せすぎると別々の汚染先が
同じ鍵に畳まれ、増加が隠れる。この境目だけを直接叩く。

例に使っているパスとテスト名は 2026-08-01 の実測（fs-guard-records.jsonl）から
そのまま取った。作り話だと、実際に揺れているものを外す。

注意: このファイルは pytest.ini の testpaths に入っていない。
testpaths への投入はロードマップの最後にまとめて行う方針のため、
ここでは追加しない（backend/tests/test_fs_guard.py と同じ）。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_RATCHET = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "fs_guard_ratchet.py"
)


@pytest.fixture(scope="module")
def ratchet():
    """`.github/scripts/` はパッケージではないのでパスから直接読み込む。"""
    spec = importlib.util.spec_from_file_location("fs_guard_ratchet", _RATCHET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fs_guard_ratchet"] = module
    spec.loader.exec_module(module)
    return module


class TestNormalizeVolatile:
    """実行ごとに変わる部分が伏せ字になること"""

    @pytest.mark.parametrize("path", [
        "Human01_Official Artifact/受信トレイ/session_complete_report_20260801_021840_UTC.md",
        "backend/agents/logs/pipeline_knowledge/run_20260801_111033.json",
        "backend/migration_backups/backup_20260801_104305/settings.json",
    ])
    def test_timestamp(self, ratchet, path):
        assert "<TS>" in ratchet.normalize(path)

    def test_uuid(self, ratchet):
        assert ratchet.normalize(
            "backend/tests/performance/worker_perf_"
            "78838117-0f55-4312-be53-fb709bada460.json"
        ) == "backend/tests/performance/worker_perf_<UUID>.json"

    def test_hex_digest(self, ratchet):
        assert ratchet.normalize(
            "backend/temp_thumbnails/pipeline_status_thumb_task."
            "c16930fad4c842df98fee2cbdf7b8e2d.tmp"
        ) == "backend/temp_thumbnails/pipeline_status_thumb_task.<HEX>.tmp"

    def test_pid(self, ratchet):
        assert ratchet.normalize(".tmp_12676_output.jpg") == ".tmp_<N>_output.jpg"

    def test_same_shape_collapses_to_one_key(self, ratchet):
        # 同じ生成元が別の実行で作った2つは、同じ鍵に畳まれる必要がある。
        # ここが崩れると実行のたびに鍵が増える。
        a = "Human01_Official Artifact/受信トレイ/hourly_report_20260801_1046_jst.md"
        b = "Human01_Official Artifact/受信トレイ/hourly_report_20260802_0829_jst.md"
        assert ratchet.normalize(a) == ratchet.normalize(b)


class TestNormalizeKeepsStablePaths:
    """変わらないものまで伏せないこと"""

    @pytest.mark.parametrize("path", [
        "backend/branding/evolution_log.json",
        "backend/tests/e2e_results.json",
        "archives/analytics/history.jsonl",
        "README.md",
    ])
    def test_untouched(self, ratchet, path):
        assert ratchet.normalize(path) == path

    def test_short_serial_is_kept(self, ratchet):
        # 3桁の連番は固定。伏せると別々の汚染先が1つの鍵に畳まれ、増加が隠れる。
        assert ratchet.normalize("temp_thumbnails/task_001.png") == (
            "temp_thumbnails/task_001.png"
        )
        assert ratchet.normalize("temp_thumbnails/task_002.png") != (
            ratchet.normalize("temp_thumbnails/task_001.png")
        )


class TestTestKey:
    """nodeid の綴りがバッチ構成で変わっても同じテストとして数えること"""

    def test_rootdir_prefix_is_dropped(self, ratchet):
        assert ratchet.test_key("backend/tests/test_x.py::test_y") == (
            ratchet.test_key("test_x.py::test_y")
        )

    def test_class_and_method_are_kept(self, ratchet):
        assert ratchet.test_key(
            "backend/tests/test_shared/test_batch22_23_deep.py::TestDeep::test_ald_02"
        ) == "test_batch22_23_deep.py::TestDeep::test_ald_02"

    def test_windows_separator(self, ratchet):
        assert ratchet.test_key(r"backend\tests\test_x.py::test_y") == (
            "test_x.py::test_y"
        )


class TestReadRecords:
    """バッチをまたいだ追記の畳み方"""

    def test_folds_batches_and_normalizes(self, ratchet, tmp_path):
        records = tmp_path / "rec.jsonl"
        records.write_text(
            '{"path":"out/run_20260801_010101.json","tests":["a/test_x.py::t1"]}\n'
            '{"path":"out/run_20260801_020202.json","tests":["test_x.py::t1"]}\n'
            '{"path":"out/run_20260801_030303.json","tests":["test_x.py::t2"]}\n',
            encoding="utf-8",
        )
        # 3行・3パスだが、鍵は1つ。同じテストは綴りが違っても1つ。
        assert ratchet.read_records(records) == {"out/run_<TS>.json": 2}

    def test_blank_lines_are_skipped(self, ratchet, tmp_path):
        records = tmp_path / "rec.jsonl"
        records.write_text(
            '\n{"path":"README.md","tests":["test_x.py::t"]}\n\n', encoding="utf-8"
        )
        assert ratchet.read_records(records) == {"README.md": 1}
