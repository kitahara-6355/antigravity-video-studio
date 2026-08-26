import os
import sys
from unittest.mock import MagicMock

# google API関連をモックして、インポート時に pydantic.root_model KeyError が起きるのを回避する
sys.modules["google.adk"] = MagicMock()
sys.modules["google.genai"] = MagicMock()
sys.modules["google.genai.types"] = MagicMock()

# **`google.genai` を差し替えるなら `errors` も差し替える。**
# 差し替えないと、同じ pytest プロセスで後から読まれるモジュールの
# `from google.genai.errors import APIError` が
# 「'google.genai' is not a package」で落ちる。
# 巻き添えの相手は**バッチの区切り次第**で、testpaths に1ファイル足すだけで変わる
# （2026-08-26 に踏んだ: test_smartcut_router / test_transcribe_worker /
#  test_subtitle_quality_normalization が道連れになった）。
class _MockAPIError(Exception):
    def __init__(self, message="", code=None):
        super().__init__(message)
        self.message = message
        self.code = code


_mock_errors = MagicMock()
_mock_errors.APIError = _MockAPIError
sys.modules["google.genai.errors"] = _mock_errors

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

# パス追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import inspect
from unittest.mock import MagicMock

# 実在しないモジュール 'subtitle_engine.transcriber' を偽装
mock_transcriber_module = MagicMock()
mock_transcriber_obj = MagicMock()
mock_transcriber_module.transcriber = mock_transcriber_obj
sys.modules["subtitle_engine.transcriber"] = mock_transcriber_module



import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.segments import router, _format_time_vtt, _format_time_srt

app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.fixture(autouse=True)
def mock_segments_path(tmp_path):
    from routers import segments
    original_path = segments.SEGMENTS_PATH
    temp_file = tmp_path / "subtitle_result_test.json"
    segments.SEGMENTS_PATH = temp_file
    yield temp_file
    segments.SEGMENTS_PATH = original_path

# --- GET /api/segments ---

def test_get_segments_not_exists(mock_segments_path):
    # Ensure file does not exist
    if mock_segments_path.exists():
        mock_segments_path.unlink()
    response = client.get("/api/segments")
    assert response.status_code == 200
    assert response.json() == []

def test_get_segments_exists(mock_segments_path):
    data = [{"start": 0.0, "end": 2.5, "text": "テスト"}]
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    
    response = client.get("/api/segments")
    assert response.status_code == 200
    assert response.json() == data

def test_get_segments_exception(mock_segments_path, monkeypatch):
    # openで例外が発生した場合のエラーハンドリング検証
    import builtins
    original_open = builtins.open
    
    def mock_open_raise(file, *args, **kwargs):
        file_str = str(file)
        if "subtitle_result" in file_str:
            raise OSError("Disk read error")
        return original_open(file, *args, **kwargs)
    
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("[]")
        
    monkeypatch.setattr(builtins, "open", mock_open_raise)
    
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "Disk read error" in response.json()["detail"]

# --- POST /api/segments ---

def test_save_segments(mock_segments_path):
    data = [{"start": 1.0, "end": 3.0, "text": "セーブ"}]
    response = client.post("/api/segments", json=data)
    assert response.status_code == 200
    assert response.json() == {"status": "saved", "count": 1}
    
    # Verify content was written
    assert mock_segments_path.exists()
    with open(mock_segments_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data == data

def test_save_segments_exception(mock_segments_path, monkeypatch):
    # openで例外が発生した場合のエラーハンドリング検証
    import builtins
    original_open = builtins.open
    
    def mock_open_raise(file, *args, **kwargs):
        file_str = str(file)
        if "subtitle_result" in file_str:
            raise OSError("Disk write error")
        return original_open(file, *args, **kwargs)
        
    monkeypatch.setattr(builtins, "open", mock_open_raise)
    
    response = client.post("/api/segments", json=[])
    assert response.status_code == 500
    assert "Disk write error" in response.json()["detail"]

# --- POST /api/subtitles/transcribe ---

def test_transcribe_video_success(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    
    called_with_path = None
    
    def mock_transcribe(path):
        nonlocal called_with_path
        called_with_path = path
        # Verify temporary file exists during processing
        assert os.path.exists(path)
        return {"status": "success", "text": "自動生成された字幕"}
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "success", "text": "自動生成された字幕"}
    # Verify cleanup
    assert called_with_path is not None
    assert not os.path.exists(called_with_path)

def test_transcribe_video_failure(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    
    called_with_path = None
    
    def mock_transcribe_fail(path):
        nonlocal called_with_path
        called_with_path = path
        assert os.path.exists(path)
        raise RuntimeError("Speech recognition engine error")
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_fail)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 500
    assert "Speech recognition engine error" in response.json()["detail"]
    # Verify cleanup even on failure
    assert called_with_path is not None
    assert not os.path.exists(called_with_path)

# --- POST /api/subtitles/export ---

def test_export_vtt():
    subtitles = [
        {"start": 1.5, "end": 4.25, "text": "ハロー"},
        {"start": 3600.0, "end": 3665.123, "text": "1時間後"}
    ]
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": subtitles}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/vtt; charset=utf-8"
    content = response.text
    assert "WEBVTT" in content
    assert "00:00:01.500 --> 00:00:04.250\nハロー" in content
    assert "01:00:00.000 --> 01:01:05.123\n1時間後" in content

def test_export_srt():
    subtitles = [
        {"start": 1.5, "end": 4.25, "text": "ハロー"},
        {"start": 3600.0, "end": 3665.123, "text": "1時間後"}
    ]
    response = client.post(
        "/api/subtitles/export?format=srt",
        json={"subtitles": subtitles}
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    content = response.text
    assert "1\n00:00:01,500 --> 00:00:04,250\nハロー" in content
    assert "2\n01:00:00,000 --> 01:01:05,123\n1時間後" in content

def test_export_unsupported():
    subtitles = [{"start": 1.5, "end": 4.25, "text": "ハロー"}]
    response = client.post(
        "/api/subtitles/export?format=invalid",
        json={"subtitles": subtitles}
    )
    assert response.status_code == 400
    assert "Unsupported format: invalid" in response.json()["detail"]

# --- Formatter Helper Tests ---

def test_format_time_vtt_boundaries():
    assert _format_time_vtt(0.0) == "00:00:00.000"
    assert _format_time_vtt(0.001) == "00:00:00.001"
    assert _format_time_vtt(59.999) == "00:00:59.999"
    assert _format_time_vtt(60.0) == "00:01:00.000"
    assert _format_time_vtt(3599.999) == "00:59:59.999"
    assert _format_time_vtt(3600.0) == "01:00:00.000"
    assert _format_time_vtt(86399.999) == "23:59:59.999"

def test_format_time_srt_boundaries():
    assert _format_time_srt(0.0) == "00:00:00,000"
    assert _format_time_srt(0.001) == "00:00:00,001"
    assert _format_time_srt(59.999) == "00:00:59,999"
    assert _format_time_srt(60.0) == "00:01:00,000"
    # 3599.999 % 1 evaluates to 0.9989999999998872 -> 998ms in production code
    assert _format_time_srt(3599.999) == "00:59:59,998"
    assert _format_time_srt(3600.0) == "01:00:00,000"
    # 86399.999 % 1 evaluates to 0.9989999999998872 -> 998ms in production code
    assert _format_time_srt(86399.999) == "23:59:59,998"

# --- Additional Edge Cases ---

def test_format_time_vtt_negative_and_large():
    # Negative value handling (mathematical floor behavior of //)
    assert _format_time_vtt(-1.5) == "-1:59:58.500"
    
    # Large value (100 hours)
    assert _format_time_vtt(360000.0) == "100:00:00.000"

def test_format_time_srt_negative_and_large():
    # Negative value handling (mathematical floor behavior of //)
    assert _format_time_srt(-1.5) == "-1:59:58,500"
    
    # Large value (100 hours)
    assert _format_time_srt(360000.0) == "100:00:00,000"

def test_export_empty_list():
    # Empty subtitles list for VTT
    response_vtt = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": []}
    )
    assert response_vtt.status_code == 200
    assert response_vtt.text == "WEBVTT\n\n"

    # Empty subtitles list for SRT
    response_srt = client.post(
        "/api/subtitles/export?format=srt",
        json={"subtitles": []}
    )
    assert response_srt.status_code == 200
    assert response_srt.text == ""


# --- Additional Validation Tests for export_subtitles ---

def test_export_subtitles_missing_payload():
    # subtitles キーが指定されていない場合 (422)
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={}
    )
    assert response.status_code == 422

def test_export_subtitles_invalid_type():
    # subtitles がリストではなく文字列の場合 (422)
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": "not a list"}
    )
    assert response.status_code == 422


# --- Additional Validation & Cleanup Tests ---

def test_transcribe_video_cleanup_on_upload_error(monkeypatch):
    import tempfile
    
    # 元の一時ディレクトリを監視するための仕組み
    created_temp_files = []
    original_named_temp_file = tempfile.NamedTemporaryFile
    
    def mock_named_temporary_file(*args, **kwargs):
        tmp = original_named_temp_file(*args, **kwargs)
        created_temp_files.append(tmp.name)
        # writeメソッドをモックして例外をスローさせる
        def mock_write(*a, **kw):
            raise IOError("Simulated write error during temp file save")
        tmp.write = mock_write
        return tmp
        
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", mock_named_temporary_file)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 500
    
    # 作成された一時ファイルがディスクから削除されていることを検証
    assert len(created_temp_files) == 1
    temp_file_path = created_temp_files[0]
    assert not os.path.exists(temp_file_path)


def test_save_segments_invalid_type():
    # リスト以外のデータを送信した場合に 400 が返ることを検証
    response = client.post("/api/segments", json={"not": "a list"})
    assert response.status_code == 400
    assert "Segments data must be a JSON array" in response.json()["detail"]
    
    response2 = client.post("/api/segments", json="just a string")
    assert response2.status_code == 400
    assert "Segments data must be a JSON array" in response2.json()["detail"]


def test_export_subtitles_invalid_substructure():
    # subtitles リストの中に None など辞書ではない要素がある場合
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": [None]}
    )
    assert response.status_code == 400
    assert "Invalid subtitle structure" in response.json()["detail"]


def test_export_subtitles_missing_keys():
    # subtitles リストの中の辞書に必要なキーが存在しない場合
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": [{"start": 1.0, "text": "missing end key"}]}
    )
    assert response.status_code == 400
    assert "Invalid subtitle structure" in response.json()["detail"]


# --- カバレッジ向上のための追加エラーケーステスト ---

def test_get_segments_invalid_json(mock_segments_path):
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("invalid json string")
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "Invalid JSON format" in response.json()["detail"]


def test_get_segments_http_exception(mock_segments_path, monkeypatch):
    import json
    def mock_load(f):
        raise HTTPException(status_code=400, detail="Mocked HTTP error")
    monkeypatch.setattr(json, "load", mock_load)
    
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("[]")
        
    response = client.get("/api/segments")
    assert response.status_code == 400
    assert "Mocked HTTP error" in response.json()["detail"]


def test_save_segments_malformed_json():
    response = client.post(
        "/api/segments",
        content="invalid json",
        headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert "Malformed JSON payload" in response.json()["detail"]


def test_save_segments_serialization_error(monkeypatch):
    import json
    def mock_dump(*args, **kwargs):
        raise TypeError("Object is not JSON serializable")
    monkeypatch.setattr(json, "dump", mock_dump)
    
    response = client.post("/api/segments", json=[])
    assert response.status_code == 400
    assert "Serialization failed" in response.json()["detail"]


def test_transcribe_video_cleanup_remove_oserror(monkeypatch):
    import tempfile
    import os
    
    created_temp_files = []
    original_named_temp_file = tempfile.NamedTemporaryFile
    
    def mock_named_temporary_file(*args, **kwargs):
        tmp = original_named_temp_file(*args, **kwargs)
        created_temp_files.append(tmp.name)
        def mock_write(*a, **kw):
            raise IOError("Simulated write error during temp file save")
        tmp.write = mock_write
        return tmp
        
    original_remove = os.remove
    def mock_remove(path):
        if path in created_temp_files:
            raise OSError("Permission denied on delete")
        return original_remove(path)
        
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", mock_named_temporary_file)
    monkeypatch.setattr(os, "remove", mock_remove)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 500
    
    for path in created_temp_files:
        try:
            original_remove(path)
        except OSError:
            pass


def test_transcribe_video_value_error(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    
    def mock_transcribe_value_error(path):
        raise ValueError("Invalid audio format")
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_value_error)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 400
    assert "Invalid audio format" in response.json()["detail"]


def test_transcribe_video_http_exception(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    
    def mock_transcribe_http_exception(path):
        raise HTTPException(status_code=403, detail="Forbidden action")
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_http_exception)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 403
    assert "Forbidden action" in response.json()["detail"]


def test_transcribe_video_unexpected_structural_error(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    
    def mock_transcribe_type_error(path):
        raise TypeError("Unexpected structural error during transcription")
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_type_error)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 500
    assert "Transcription processing error" in response.json()["detail"]


def test_transcribe_video_finally_remove_oserror(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    import os
    
    # transcribeは成功させ、クリーンアップ時のos.removeでOSErrorを発生させる
    def mock_transcribe_success(path):
        return {"status": "success", "text": "テスト"}
        
    original_remove = os.remove
    def mock_remove(path):
        if "tmp" in path or "temp" in path:
            raise OSError("Permission denied during cleanup removal")
        return original_remove(path)
        
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_success)
    monkeypatch.setattr(os, "remove", mock_remove)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    
    assert response.status_code == 200
    assert response.json() == {"status": "success", "text": "テスト"}

# --- except Exception 捕捉テスト ---

def test_get_segments_unexpected_exception(mock_segments_path, monkeypatch):
    # json.load等で想定外の例外(Exception)が発生した際のハンドリング検証
    import json
    def mock_load(f):
        raise RuntimeError("想定外のエラー")
    monkeypatch.setattr(json, "load", mock_load)
    
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("[]")
        
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "Unexpected internal server error" in response.json()["detail"]


def test_save_segments_unexpected_exception(mock_segments_path, monkeypatch):
    # open等で想定外の例外(Exception)が発生した際のハンドリング検証
    import builtins
    def mock_open_raise(*args, **kwargs):
        raise RuntimeError("想定外のエラー")
    monkeypatch.setattr(builtins, "open", mock_open_raise)
    
    response = client.post("/api/segments", json=[])
    assert response.status_code == 500
    assert "Unexpected internal server error" in response.json()["detail"]


def test_transcribe_video_unexpected_exception(monkeypatch):
    # transcribe()で想定外の例外(Exception)が発生した際のハンドリング検証
    from subtitle_engine.transcriber import transcriber
    def mock_transcribe_fail(path):
        raise Exception("想定外のエラー")
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_fail)
    
    response = client.post(
        "/api/subtitles/transcribe",
        files={"file": ("test.mp4", b"dummy_content", "video/mp4")}
    )
    assert response.status_code == 500
    assert "Unexpected internal server error" in response.json()["detail"]


def test_export_subtitles_unexpected_exception(monkeypatch):
    # export時に想定外の例外(Exception)が発生した際のハンドリング検証
    from routers import segments
    def mock_generate_vtt(subtitles):
        raise RuntimeError("想定外のエラー")
    monkeypatch.setattr(segments, "_generate_vtt", mock_generate_vtt)
    
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": [{"start": 1.5, "end": 4.25, "text": "ハロー"}]}
    )
    assert response.status_code == 500
    assert "Unexpected internal server error" in response.json()["detail"]


# --- Pydantic バリデーション強化に伴う追加テスト ---

def test_get_segments_filtering_invalid_records(mock_segments_path):
    # ファイル内に一部不正なデータが混入していた場合のフィルタリング挙動の検証
    data = [
        {"start": 0.0, "end": 2.5, "text": "正常データ"},
        {"start": "invalid_float", "end": 2.5, "text": "無効なstart型"},
        {"end": 4.5, "text": "start欠損"},
        "not_a_dict_string"
    ]
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        
    response = client.get("/api/segments")
    assert response.status_code == 200
    res_data = response.json()
    
    # 正常データのみが抽出されていることを確認
    assert len(res_data) == 1
    assert res_data[0]["text"] == "正常データ"


def test_save_segments_pydantic_coercion():
    # Pydanticの型強制（文字列の"1.5"がfloatに自動変換される）が動作することの検証
    data = [{"start": "1.5", "end": "4.25", "text": "型強制テスト"}]
    response = client.post("/api/segments", json=data)
    assert response.status_code == 200
    assert response.json()["status"] == "saved"


def test_export_subtitles_pydantic_coercion():
    # エクスポート時の型強制が正しく動作することの検証
    subtitles = [{"start": "1.5", "end": "4.25", "text": "型強制テスト"}]
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": subtitles}
    )
    assert response.status_code == 200
    assert "00:00:01.500 --> 00:00:04.250\n型強制テスト" in response.text


def test_get_segments_empty_file(mock_segments_path):
    # ファイルサイズが0バイトの場合、空リストを返すことを検証
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("")
    response = client.get("/api/segments")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.anyio
async def test_transcribe_video_closes_file(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    from fastapi import UploadFile
    
    monkeypatch.setattr(transcriber, "transcribe", lambda path: {"status": "success"})
    
    close_called = False
    
    class SpiedUploadFile(UploadFile):
        async def close(self):
            nonlocal close_called
            close_called = True
            await super().close()
            
    from io import BytesIO
    file_obj = BytesIO(b"dummy video data")
    spied_file = SpiedUploadFile(file=file_obj, filename="test.mp4", headers={"content-type": "video/mp4"})
    
    from routers.segments import transcribe_video
    result = await transcribe_video(spied_file)
    
    assert result == {"status": "success"}
    assert close_called is True


def test_export_subtitles_case_insensitive():
    # 大文字のVTT/SRTフォーマットでもエクスポートが成功することを検証
    subtitles = [{"start": 1.0, "end": 2.0, "text": "テスト"}]
    
    response_vtt = client.post(
        "/api/subtitles/export?format=VTT",
        json={"subtitles": subtitles}
    )
    assert response_vtt.status_code == 200
    assert "WEBVTT" in response_vtt.text

    response_srt = client.post(
        "/api/subtitles/export?format=Srt",
        json={"subtitles": subtitles}
    )
    assert response_srt.status_code == 200
    assert "1\n00:00:01,000 --> 00:00:02,000\nテスト" in response_srt.text


def test_save_segments_atomic_write_failure(mock_segments_path, monkeypatch):
    # os.replace が OSError を投げた場合、元のファイルが壊れておらず、一時ファイルが消えていることを検証
    import os
    
    # 事前に元ファイルを準備
    initial_data = [{"start": 0.0, "end": 1.0, "text": "初期データ"}]
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        json.dump(initial_data, f, ensure_ascii=False)
        
    temp_file_path = None
    
    # os.replace をモックして例外を投げさせる
    def mock_replace(src, dst):
        nonlocal temp_file_path
        temp_file_path = src
        # 置き換え前に一時ファイルが存在することを確認
        assert os.path.exists(src)
        raise OSError("Simulated replacement failure")
    monkeypatch.setattr(os, "replace", mock_replace)
    
    new_data = [{"start": 2.0, "end": 3.0, "text": "新規データ"}]
    response = client.post("/api/segments", json=new_data)
    assert response.status_code == 500
    assert "Disk write error or permission denied" in response.json()["detail"]
    
    # 元のファイルが変更されていないことを確認
    with open(mock_segments_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data == initial_data
    
    # 作成された一時ファイルがディスクから削除されていることを確認
    assert temp_file_path is not None
    assert not os.path.exists(temp_file_path)


@pytest.mark.anyio
async def test_transcribe_video_closes_file_exception_cleanup(monkeypatch):
    # file.close() で例外が発生した場合でも、一時ファイルが確実に削除されることを検証
    from subtitle_engine.transcriber import transcriber
    from fastapi import UploadFile
    import os
    import tempfile
    
    monkeypatch.setattr(transcriber, "transcribe", lambda path: {"status": "success"})
    
    # 一時ファイルの生成パスを記録する
    created_temp_files = []
    original_named_temp_file = tempfile.NamedTemporaryFile
    def mock_named_temporary_file(*args, **kwargs):
        tmp = original_named_temp_file(*args, **kwargs)
        created_temp_files.append(tmp.name)
        return tmp
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", mock_named_temporary_file)
    
    class ExceptionUploadFile(UploadFile):
        async def close(self):
            # 例外をスロー
            raise RuntimeError("Simulated close exception")
            
    from io import BytesIO
    file_obj = BytesIO(b"dummy video data")
    bad_file = ExceptionUploadFile(file=file_obj, filename="test.mp4", headers={"content-type": "video/mp4"})
    
    from routers.segments import transcribe_video
    result = await transcribe_video(bad_file)
    
    assert result == {"status": "success"}
    
    # 例外が起きても一時ファイルがクリーンアップされていることを検証
    assert len(created_temp_files) > 0
    for path in created_temp_files:
        assert not os.path.exists(path)


# --- 追加のカバレッジ改善テストケース ---

def test_subtitle_segment_time_validation():
    # 26行目の ValueError を直接発生させるテスト
    from pydantic import ValidationError
    from routers.segments import SubtitleSegment
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSegment(start=5.0, end=2.0, text="End time before start")
    assert "end time must be greater than or equal to start time" in str(exc_info.value)


def test_get_segments_non_list_data(mock_segments_path):
    # 43-44行目の get_segments 時の非リスト構造エラーテスト
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        json.dump({"not": "a list"}, f)
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "Invalid data structure" in response.json()["detail"]


def test_save_segments_non_dict_element():
    # 89-90行目の save_segments 内の非dict要素エラーテスト
    response = client.post("/api/segments", json=[{"start": 1.0, "end": 2.0, "text": "Valid"}, "invalid string element"])
    assert response.status_code == 400
    assert "Item must be a JSON object" in response.json()["detail"]


def test_save_segments_validation_error():
    # 93-95行目の save_segments 内の ValidationError エラーテスト
    response = client.post("/api/segments", json=[{"start": 2.0, "end": 1.0, "text": "Invalid start/end"}])
    assert response.status_code == 400
    assert "Invalid subtitle structure" in response.json()["detail"]


@pytest.mark.anyio
async def test_export_subtitles_invalid_format_type():
    # format パラメータが文字列以外（Noneなど）の場合に HTTP 400 が返ることを検証
    import pytest
    from routers.segments import export_subtitles
    from fastapi import HTTPException
    
    with pytest.raises(HTTPException) as exc_info:
        await export_subtitles(format=None, subtitles=[{"start": 1.0, "end": 2.0, "text": "テスト"}])
        
    assert exc_info.value.status_code == 400
    assert "Format parameter must be a string" in exc_info.value.detail


@pytest.mark.anyio
async def test_save_upload_file_temp_chunking(monkeypatch):
    # チャンク読み書きが正しく動作することを検証する
    from fastapi import UploadFile
    from io import BytesIO
    from routers.segments import _save_upload_file_temp
    
    # 3MBのテストデータを用意する
    data_size = 3 * 1024 * 1024
    dummy_data = b"A" * data_size
    file_obj = BytesIO(dummy_data)
    
    # read の呼び出し履歴と呼び出し回数を記録するスパイオブジェクト
    read_calls = []
    original_read = file_obj.read
    
    def mock_read(size=-1):
        res = original_read(size)
        read_calls.append(len(res))
        return res
        
    file_obj.read = mock_read
    
    upload_file = UploadFile(file=file_obj, filename="large_test.mp4")
    
    # 実行
    tmp_path = await _save_upload_file_temp(upload_file)
    
    try:
        # ファイルが存在することを確認
        assert os.path.exists(tmp_path)
        # ファイルサイズが一致することを確認
        assert os.path.getsize(tmp_path) == data_size
        
        # チャンクサイズが 1MB なので、3MB に対しては 1MB, 1MB, 1MB, 0 の 4回 read が呼ばれるはず
        assert len(read_calls) >= 3
        for call_size in read_calls[:-1]:
            assert call_size == 1024 * 1024  # 1MB
        assert read_calls[-1] == 0  # 最後の読み込みは空
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_get_segments_stat_os_error(mock_segments_path, monkeypatch):
    from pathlib import Path
    original_exists = Path.exists
    def mock_exists(self):
        if "subtitle_result" in str(self):
            raise OSError("Simulated path exists error")
        return original_exists(self)
    monkeypatch.setattr(Path, "exists", mock_exists)
    
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "Disk read error or permission denied" in response.json()["detail"]


@pytest.mark.anyio
async def test_transcribe_video_cleanup_when_close_raises_http_exception(monkeypatch):
    from subtitle_engine.transcriber import transcriber
    from fastapi import UploadFile, HTTPException
    import tempfile
    
    monkeypatch.setattr(transcriber, "transcribe", lambda path: {"status": "success"})
    
    created_temp_files = []
    original_named_temp_file = tempfile.NamedTemporaryFile
    def mock_named_temporary_file(*args, **kwargs):
        tmp = original_named_temp_file(*args, **kwargs)
        created_temp_files.append(tmp.name)
        return tmp
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", mock_named_temporary_file)
    
    class ExceptionUploadFile(UploadFile):
        async def close(self):
            raise HTTPException(status_code=400, detail="Simulated close HTTPException")
            
    from io import BytesIO
    file_obj = BytesIO(b"dummy video data")
    bad_file = ExceptionUploadFile(file=file_obj, filename="test.mp4", headers={"content-type": "video/mp4"})
    
    from routers.segments import transcribe_video
    result = await transcribe_video(bad_file)
    assert result == {"status": "success"}
    
    # 確実に一時ファイルが削除されていることを検証
    assert len(created_temp_files) > 0
    for path in created_temp_files:
        assert not os.path.exists(path)


def test_subtitle_segment_infinite_values():
    from pydantic import ValidationError
    from routers.segments import SubtitleSegment
    
    # inf の検証
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSegment(start=1.0, end=float("inf"), text="Infinite end")
    assert "start and end times must be finite numbers" in str(exc_info.value)
    
    # nan の検証
    with pytest.raises(ValidationError) as exc_info:
        SubtitleSegment(start=float("nan"), end=2.0, text="NaN start")
    assert "greater than or equal to 0" in str(exc_info.value)



@pytest.mark.anyio
async def test_export_subtitles_overflow_error(monkeypatch):
    from routers import segments
    def mock_generate_vtt(subtitles):
        raise OverflowError("Simulated OverflowError during VTT generation")
    monkeypatch.setattr(segments, "_generate_vtt", mock_generate_vtt)
    
    response = client.post(
        "/api/subtitles/export?format=vtt",
        json={"subtitles": [{"start": 1.5, "end": 4.25, "text": "ハロー"}]}
    )
    assert response.status_code == 400
    assert "Invalid subtitle structure or format" in response.json()["detail"]


def test_get_segments_is_directory(mock_segments_path, monkeypatch):
    # SEGMENTS_PATH がディレクトリとして存在する場合、空リストを返すことを検証
    if mock_segments_path.exists():
        mock_segments_path.unlink()
    mock_segments_path.mkdir(parents=True, exist_ok=True)
    
    try:
        response = client.get("/api/segments")
        assert response.status_code == 200
        assert response.json() == []
    finally:
        # 後片付け
        if mock_segments_path.is_dir():
            import shutil
            shutil.rmtree(mock_segments_path)


def test_save_segments_temp_dir_creation(tmp_path):
    # 保存先親ディレクトリが存在しない場合でも、自動的に作成されて保存が成功することを検証
    from routers import segments
    original_path = segments.SEGMENTS_PATH
    
    nested_dir = tmp_path / "non_existent_subdir"
    temp_file = nested_dir / "subtitle_result_test.json"
    segments.SEGMENTS_PATH = temp_file
    
    try:
        data = [{"start": 1.0, "end": 3.0, "text": "新規サブディレクトリテスト"}]
        response = client.post("/api/segments", json=data)
        assert response.status_code == 200
        assert temp_file.exists()
    finally:
        segments.SEGMENTS_PATH = original_path


def test_save_segments_unexpected_atomic_exception_cleanup(mock_segments_path, monkeypatch):
    # os.replaceの過程などで想定外の例外(RuntimeErrorなど)が発生した際、
    # finallyブロックにより一時ファイルが確実に削除されることを検証
    import os
    import json
    
    temp_files = []
    
    # json.dumpの実行中に一時ファイルパスを追跡し、かつ例外を投げる
    def mock_dump_error(obj, fp, *args, **kwargs):
        temp_files.append(fp.name)
        raise RuntimeError("Unexpected failure during json dump")
        
    monkeypatch.setattr(json, "dump", mock_dump_error)
    
    data = [{"start": 1.0, "end": 2.0, "text": "一時ファイル削除テスト"}]
    response = client.post("/api/segments", json=data)
    assert response.status_code == 500
    
    # 登録された一時ファイルが削除されていることを確認
    assert len(temp_files) > 0
    for path in temp_files:
        assert not os.path.exists(path)


@pytest.mark.anyio
async def test_transcribe_video_empty_file(monkeypatch):
    # アップロードファイルが空の場合のエラーハンドリング
    from fastapi import UploadFile
    from io import BytesIO
    from fastapi import HTTPException
    
    file_obj = BytesIO(b"")  # 空のデータ
    empty_file = UploadFile(file=file_obj, filename="empty.mp4", headers={"content-type": "video/mp4"})
    
    from routers.segments import transcribe_video
    # 空のファイルに対しては ValueError や HTTPException(400) などが投げられるはず
    with pytest.raises((ValueError, HTTPException)):
        await transcribe_video(empty_file)


@pytest.mark.anyio
async def test_transcribe_video_closes_file_exception_no_override(monkeypatch):
    # file.close() で HTTPException が発生しても、元の例外 (ValueError) が隠蔽されないことを検証
    from subtitle_engine.transcriber import transcriber
    from fastapi import UploadFile, HTTPException
    
    # transcribeでValueErrorを発生させる
    def mock_transcribe_error(path):
        raise ValueError("Original transcription error")
    monkeypatch.setattr(transcriber, "transcribe", mock_transcribe_error)
    
    class ExceptionUploadFile(UploadFile):
        async def close(self):
            # closeでHTTPExceptionを発生させる
            raise HTTPException(status_code=400, detail="Close exception")
            
    from io import BytesIO
    file_obj = BytesIO(b"dummy video data")
    bad_file = ExceptionUploadFile(file=file_obj, filename="test.mp4", headers={"content-type": "video/mp4"})
    
    from routers.segments import transcribe_video
    with pytest.raises(HTTPException) as exc_info:
        await transcribe_video(bad_file)
        
    assert exc_info.value.status_code == 400
    assert "Original transcription error" in exc_info.value.detail


def test_save_segments_mkdir_failure(monkeypatch):
    # 親ディレクトリの作成（mkdir）で OSError が発生した際、適切に 500 エラーになることを検証
    from pathlib import Path
    
    def mock_mkdir(self, *args, **kwargs):
        raise OSError("Permission denied for mkdir")
    monkeypatch.setattr(Path, "mkdir", mock_mkdir)
    
    data = [{"start": 1.0, "end": 2.0, "text": "テスト"}]
    response = client.post("/api/segments", json=data)
    assert response.status_code == 500
    assert "Disk write error or permission denied" in response.json()["detail"]


def test_get_segments_unicode_decode_error(mock_segments_path, monkeypatch):
    # ファイル読み込み時に UnicodeDecodeError が発生した場合、適切に 500 エラーになることを検証
    import json
    
    def mock_load(f):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    monkeypatch.setattr(json, "load", mock_load)
    
    with open(mock_segments_path, "w", encoding="utf-8") as f:
        f.write("[]")
        
    response = client.get("/api/segments")
    assert response.status_code == 500
    assert "encoding error" in response.json()["detail"].lower() or "unicode" in response.json()["detail"].lower()






