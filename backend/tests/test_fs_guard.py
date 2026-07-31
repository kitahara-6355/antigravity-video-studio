"""fs_guard の判定ロジックのテスト。

fs_guard は「テストが本番ファイルを書き換えていないか」を測る道具なので、
除外の取りこぼしがそのまま計測値の狂いになる。判定部分だけを直接叩く。

注意: このファイルは pytest.ini の testpaths に入っていない。
testpaths への投入はロードマップの最後にまとめて行う方針のため、
ここでは追加しない。ローカルで明示的に指定して実行する。
"""

import os

import fs_guard


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
