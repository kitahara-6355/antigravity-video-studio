"""backend/raw_source.py — raw 素材の読み口（M2・R2.5-C5）。

守りたい性質:

1. **読み取り専用以外のトークンでは API を呼ぶ前に止まる**
2. 共有ドライブの動画を、mp4 以外も含めてページングで取りこぼさず読む
3. 一覧にトークンの中身もフォルダ ID の全体も出さない

Google には接続しない（Drive クライアントは差し替える）。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend import raw_source
from backend.services import google_oauth

READONLY = "https://www.googleapis.com/auth/drive.readonly"
FULL = "https://www.googleapis.com/auth/drive"
FOLDER = "1AbCdEfGhIjKlMnOpQrStUv2h-z"


def _token(scopes) -> str:
    return json.dumps({"token": "at", "refresh_token": "SECRET-RT", "client_id": "cid",
                       "client_secret": "cs", "scopes": scopes})


def _drive(pages):
    """files().list(...).execute() がページを順に返す偽の Drive。"""
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = pages
    return service


# --- 1. 読み取り専用の確認 ------------------------------------------------------


def test_a_readonly_token_passes():
    raw_source.check_read_only({"scopes": [READONLY]})


@pytest.mark.parametrize("scopes", [
    [FULL],
    [READONLY, FULL],
    [READONLY, "https://www.googleapis.com/auth/spreadsheets"],
])
def test_a_token_that_can_write_is_refused(scopes):
    with pytest.raises(raw_source.TooBroadScopeError) as exc:
        raw_source.check_read_only({"scopes": scopes})
    assert "--readonly" in str(exc.value)


def test_a_token_without_recorded_scopes_is_refused():
    """何ができるか分からないトークンは raw に向けない。"""
    with pytest.raises(raw_source.TooBroadScopeError):
        raw_source.check_read_only({"token": "at"})


def test_a_broad_token_never_reaches_the_api(monkeypatch, capsys):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([FULL]))
    build = MagicMock()
    monkeypatch.setattr(raw_source, "_build_drive", build)

    code = raw_source.run_list({raw_source.FOLDER_ENV: FOLDER})

    assert code == 1
    build.assert_not_called()
    assert "読み取り専用以外" in capsys.readouterr().err


# --- 2. 一覧 --------------------------------------------------------------------


def test_list_videos_follows_pages_and_reads_shared_drives():
    service = _drive([
        {"files": [{"name": "a.mp4", "size": "10"}], "nextPageToken": "p2"},
        {"files": [{"name": "b.mov", "size": "20"}]},
    ])

    files = raw_source.list_videos(service, FOLDER)

    assert [f["name"] for f in files] == ["a.mp4", "b.mov"]
    calls = service.files.return_value.list.call_args_list
    assert len(calls) == 2
    assert calls[1].kwargs["pageToken"] == "p2"
    for c in calls:
        assert c.kwargs["supportsAllDrives"] is True
        assert c.kwargs["includeItemsFromAllDrives"] is True
        # mp4 に限らない・ゴミ箱は除く
        assert "mimeType contains 'video/'" in c.kwargs["q"]
        assert "trashed = false" in c.kwargs["q"]
        assert f"'{FOLDER}' in parents" in c.kwargs["q"]


def test_run_list_prints_names_sizes_and_total(monkeypatch, capsys):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([READONLY]))
    service = _drive([{"files": [
        {"name": "raw01.mp4", "size": str(300 * 1024 * 1024)},
        {"name": "raw02.mp4", "size": str(1024 * 1024 * 1024)},
    ]}])
    monkeypatch.setattr(raw_source, "_build_drive", lambda: service)

    code = raw_source.run_list({raw_source.FOLDER_ENV: FOLDER})

    out = capsys.readouterr().out
    assert code == 0
    assert "raw01.mp4" in out and "300.0 MB" in out
    assert "raw02.mp4" in out and "1.0 GB" in out
    assert "2 本" in out and "1.3 GB" in out


def test_run_list_never_prints_the_token_or_the_whole_folder_id(monkeypatch, capsys):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([READONLY]))
    monkeypatch.setattr(raw_source, "_build_drive",
                        lambda: _drive([{"files": [{"name": "a.mp4", "size": "1"}]}]))

    raw_source.run_list({raw_source.FOLDER_ENV: FOLDER})

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "SECRET-RT" not in text
    assert FOLDER not in text
    assert "2h-z" in text


def test_an_empty_folder_is_a_failure(monkeypatch):
    """0本は「準備できていない」。合格にしない。"""
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([READONLY]))
    monkeypatch.setattr(raw_source, "_build_drive", lambda: _drive([{"files": []}]))

    assert raw_source.run_list({raw_source.FOLDER_ENV: FOLDER}) == 1


def test_a_missing_folder_id_exits_two(capsys):
    assert raw_source.run_list({}) == 2
    assert raw_source.FOLDER_ENV in capsys.readouterr().err


def test_a_missing_token_is_reported_not_raised(monkeypatch, tmp_path):
    monkeypatch.delenv(google_oauth.TOKEN_JSON_ENV, raising=False)
    monkeypatch.setenv("ANTIGRAVITY_GOOGLE_TOKEN", str(tmp_path / "absent.json"))

    assert raw_source.run_list({raw_source.FOLDER_ENV: FOLDER}) == 1


def test_main_without_flags_shows_help():
    assert raw_source.main([]) == 2


def test_a_drive_error_is_reported_not_raised(monkeypatch, capsys):
    """フォルダが無い・権限が無いときも、トレースバックではなく理由を出して exit 1。"""
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([READONLY]))
    service = MagicMock()
    service.files.return_value.list.return_value.execute.side_effect = OSError("boom")
    monkeypatch.setattr(raw_source, "_build_drive", lambda: service)

    assert raw_source.run_list({raw_source.FOLDER_ENV: FOLDER}) == 1
    assert "Drive から読めません" in capsys.readouterr().err


# --- 3. 取得（--fetch）------------------------------------------------------------


def _fake_download(payloads):
    """`_download` の差し替え。名前ごとの中身を書き、呼ばれた ID を記録する。"""
    calls = []

    def download(service, file_id, dest):
        calls.append(file_id)
        dest.write_bytes(payloads[file_id])

    return download, calls


def test_fetch_writes_each_video_and_checks_its_size(tmp_path):
    files = [{"id": "i1", "name": "a.mp4", "size": "3"},
             {"id": "i2", "name": "b.mp4", "size": "2"}]
    download, calls = _fake_download({"i1": b"abc", "i2": b"de"})

    paths = raw_source.fetch_videos(MagicMock(), files, tmp_path, download=download)

    assert [p.name for p in paths] == ["a.mp4", "b.mp4"]
    assert (tmp_path / "a.mp4").read_bytes() == b"abc"
    assert calls == ["i1", "i2"]
    assert not list(tmp_path.glob("*.part"))


def test_fetch_skips_a_video_already_there_with_the_same_size(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"abc")
    download, calls = _fake_download({"i1": b"xyz"})

    raw_source.fetch_videos(MagicMock(), [{"id": "i1", "name": "a.mp4", "size": "3"}],
                            tmp_path, download=download)

    assert calls == []
    assert (tmp_path / "a.mp4").read_bytes() == b"abc"


def test_fetch_refuses_a_short_download_and_leaves_nothing(tmp_path):
    """途中で切れた取得を素材として残さない（大きさが Drive と違えば失敗）。"""
    download, _ = _fake_download({"i1": b"ab"})

    with pytest.raises(raw_source.FetchError):
        raw_source.fetch_videos(MagicMock(), [{"id": "i1", "name": "a.mp4", "size": "3"}],
                                tmp_path, download=download)

    assert list(tmp_path.iterdir()) == []


def test_fetch_never_writes_outside_the_destination(tmp_path):
    """Drive 上の名前にパスが混ざっていても、取得先の外には書かない。"""
    download, _ = _fake_download({"i1": b"abc"})

    paths = raw_source.fetch_videos(
        MagicMock(), [{"id": "i1", "name": "../../evil.mp4", "size": "3"}],
        tmp_path / "dest", download=download)

    assert paths[0].parent == tmp_path / "dest"
    assert not (tmp_path / "evil.mp4").exists()


def test_run_fetch_checks_the_scope_before_touching_the_api(monkeypatch, tmp_path):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([FULL]))
    build = MagicMock()
    monkeypatch.setattr(raw_source, "_build_drive", build)

    assert raw_source.run_fetch({raw_source.FOLDER_ENV: FOLDER}, tmp_path) == 1
    build.assert_not_called()


def test_run_fetch_downloads_the_listed_videos(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(google_oauth.TOKEN_JSON_ENV, _token([READONLY]))
    monkeypatch.setattr(raw_source, "_build_drive",
                        lambda: _drive([{"files": [{"id": "i1", "name": "a.mp4", "size": "3"}]}]))
    download, _ = _fake_download({"i1": b"abc"})
    monkeypatch.setattr(raw_source, "_download", download)

    assert raw_source.run_fetch({raw_source.FOLDER_ENV: FOLDER}, tmp_path) == 0
    assert (tmp_path / "a.mp4").exists()
    assert FOLDER not in capsys.readouterr().out
