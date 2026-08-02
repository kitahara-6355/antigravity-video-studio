"""fs_guard の判定ロジックのテスト。

fs_guard は「テストが本番ファイルを書き換えていないか」を測る道具なので、
除外の取りこぼしがそのまま計測値の狂いになる。判定部分だけを直接叩く。

注意: このファイルは pytest.ini の testpaths に入っていない。
testpaths への投入はロードマップの最後にまとめて行う方針のため、
ここでは追加しない。ローカルで明示的に指定して実行する。
"""

import json
import os

import fs_guard
import pytest


REPO_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)


def _in_repo(*parts):
    return os.path.join(REPO_ROOT, *parts)


class TestIsWatched:
    """_is_watched — 本番ファイルへの書き込みかどうか"""

    def test_repo_file_is_watched(self):
        assert fs_guard._is_watched(_in_repo("backend", "branding", "evolution_log.json"))

    def test_outside_repo_is_not_watched(self, tmp_path):
        # tmp_path はリポジトリの外。テストが自分の作業領域に書くのは正常。
        assert not fs_guard._is_watched(str(tmp_path / "anything.json"))

    def test_non_path_argument_is_not_watched(self):
        # ファイルディスクリプタなど、パスでないものが渡ることがある。
        assert not fs_guard._is_watched(3)
        assert not fs_guard._is_watched(None)

    def test_ignored_dir_component(self):
        assert not fs_guard._is_watched(_in_repo("backend", "__pycache__", "x.pyc"))

    def test_ignored_name(self):
        assert not fs_guard._is_watched(_in_repo("fs-guard-report.txt"))


class TestIgnoredPrefixes:
    """前方一致の除外 — 名前に実行ごとの識別子が入る生成物"""

    def test_pytest_cache_files_dir_itself(self):
        assert not fs_guard._is_watched(_in_repo("pytest-cache-files-abc123"))

    def test_file_inside_pytest_cache_files_dir(self):
        # ディレクトリ自身だけでなく、その中に作られるファイルも落とす。
        assert not fs_guard._is_watched(
            _in_repo("pytest-cache-files-abc123", "nested", "cache.bin")
        )

    def test_junit_batch_report(self):
        assert not fs_guard._is_watched(_in_repo(".junit_batch_07.xml"))

    def test_similar_name_is_still_watched(self):
        # 前方一致なので、紛らわしいだけの本番ファイルは落とさない。
        assert fs_guard._is_watched(_in_repo("pytest-cache-notes.md"))
        assert fs_guard._is_watched(_in_repo("junit_batch_07.xml"))


class TestResolvesAgainstFd:
    """dir_fd 付きの相対パスは記録しない

    `shutil.rmtree` は Linux で `os.unlink(entry.name, dir_fd=topfd)` と
    ファイル名だけを渡す。カレントディレクトリ基準で解決すると、
    リポジトリ外を rmtree しただけでリポジトリ直下のファイルを消したように
    見える（CI 実測で `.gitignore` / `README.md` / `implementation_plan.md`）。
    """

    def test_relative_path_with_dir_fd_is_skipped(self):
        assert fs_guard._resolves_against_fd(".gitignore", {"dir_fd": 7})

    def test_relative_path_without_dir_fd_is_recorded(self):
        # dir_fd が無ければカレントディレクトリ基準で正しく解決できる。
        assert not fs_guard._resolves_against_fd(".gitignore", {})
        assert not fs_guard._resolves_against_fd(".gitignore", {"dir_fd": None})

    def test_absolute_path_with_dir_fd_is_recorded(self):
        # 絶対パスなら dir_fd は OS 側で無視されるので、記録してよい。
        assert not fs_guard._resolves_against_fd(_in_repo("README.md"), {"dir_fd": 7})

    def test_rename_style_fd_kwargs(self):
        assert fs_guard._resolves_against_fd("a.json", {"src_dir_fd": 3})
        assert fs_guard._resolves_against_fd("a.json", {"dst_dir_fd": 3})

    def test_non_path_argument(self):
        # ファイルディスクリプタが直接渡ることがある。例外にしない。
        assert not fs_guard._resolves_against_fd(3, {"dir_fd": 7})

    def test_wrapper_skips_fd_relative_unlink(self, monkeypatch, clean_records):
        calls = []
        wrapped = fs_guard._wrap_path(lambda *a, **k: calls.append((a, k)), "os.unlink")

        # リポジトリ外の一時ディレクトリを rmtree したときの内部呼び出し。
        wrapped(".gitignore", dir_fd=7)
        assert clean_records == []
        # 本物には委譲する — 挙動は変えない。
        assert calls == [((".gitignore",), {"dir_fd": 7})]

        # dir_fd が無ければ従来どおり記録する。
        monkeypatch.chdir(REPO_ROOT)
        wrapped(".gitignore")
        assert [r["path"] for r in clean_records] == [".gitignore"]


@pytest.fixture
def clean_records(monkeypatch):
    """モジュール全体で共有している記録を、このテストの間だけ空にする。"""
    monkeypatch.setattr(fs_guard, "_records", [])
    return fs_guard._records


class TestRecordsJsonl:
    """records_jsonl — ラチェットが読む機械可読の出力

    人間向けの報告（report）を解析させると、書式を変えただけでラチェットが
    壊れる。判定に使うのはこちらなので、畳み方を固定しておく。
    """

    def test_empty_when_nothing_recorded(self, clean_records):
        assert fs_guard.records_jsonl() == []

    def test_folds_repeated_writes_into_one_line(self, clean_records):
        # 同じテストが同じファイルを何度書いても1行。件数が実装の都合で
        # 揺れると、ラチェットが実質的な変化なしに違反を出す。
        clean_records.extend([
            {"test": "t::a", "operation": "open(w)", "path": "README.md"},
            {"test": "t::a", "operation": "open(w)", "path": "README.md"},
        ])
        lines = fs_guard.records_jsonl()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {
            "path": "README.md",
            "tests": ["t::a"],
            "operations": ["open(w)"],
        }

    def test_collects_tests_and_operations_per_path(self, clean_records):
        clean_records.extend([
            {"test": "t::b", "operation": "os.replace", "path": "a.json"},
            {"test": "t::a", "operation": "open(w)", "path": "a.json"},
        ])
        item = json.loads(fs_guard.records_jsonl()[0])
        assert item["tests"] == ["t::a", "t::b"]
        assert item["operations"] == ["open(w)", "os.replace"]

    def test_paths_are_posix(self, clean_records):
        # 出力を Windows とランナー(Linux)で突き合わせるため区切りを揃える。
        clean_records.append(
            {"test": "t::a", "operation": "open(w)",
             "path": os.path.join("backend", "branding", "evolution_log.json")}
        )
        assert json.loads(fs_guard.records_jsonl()[0])["path"] == (
            "backend/branding/evolution_log.json"
        )
