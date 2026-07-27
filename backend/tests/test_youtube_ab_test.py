import pytest
from unittest.mock import MagicMock, patch
import json
from pathlib import Path
from backend.services.youtube_ab_test import YouTubeABTestService

@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    mock_data_dir = tmp_path / "branding"
    mock_file = mock_data_dir / "ab_tests.json"
    monkeypatch.setattr("backend.services.youtube_ab_test.DATA_DIR", mock_data_dir)
    monkeypatch.setattr("backend.services.youtube_ab_test.AB_TESTS_FILE", mock_file)
    return mock_data_dir, mock_file

def test_init_creates_dir_and_file(mock_env):
    mock_data_dir, mock_file = mock_env
    assert not mock_data_dir.exists()
    assert not mock_file.exists()
    
    service = YouTubeABTestService()
    
    # 遅延初期化のため、プロパティアクセス前は存在しないことを確認
    assert not mock_data_dir.exists()
    assert not mock_file.exists()
    
    # プロパティアクセスにより作成されることを確認
    _ = service.active_tests
    
    assert mock_data_dir.exists()
    assert mock_file.exists()
    
    with open(mock_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data == {}

def test_init_loads_existing_data(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    existing_data = {"test_123": {"video_id": "v123", "status": "RUNNING"}}
    with open(mock_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f)
         
    service = YouTubeABTestService()
    assert service.active_tests == existing_data

def test_load_exception_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    mock_file.touch() # 遅延初期化による書き込み防止のためファイルを作成しておく
    
    service = YouTubeABTestService()
    
    with patch("builtins.open", side_effect=OSError("Read error")):
        data = service.active_tests
        assert data == {}

def test_load_json_decode_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    mock_file.touch() # 遅延初期化による書き込み防止のためファイルを作成しておく
    
    service = YouTubeABTestService()
    
    err = json.JSONDecodeError("Invalid JSON", "{}", 0)
    with patch("builtins.open", side_effect=err):
        data = service.active_tests
        assert data == {}

def test_save_exception_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    with patch("builtins.open", side_effect=OSError("Write error")):
        service._save()

def test_save_type_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    with patch("json.dump", side_effect=TypeError("Serialize error")):
        service._save()

@pytest.mark.asyncio
async def test_register_ab_test_truncation(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    titles = ["t1", "t2", "t3", "t4"]
    thumbnails = ["thumb1", "thumb2", "thumb3", "thumb4"]
    
    test_id = await service.register_ab_test("video_id_999", titles, thumbnails)
    
    assert test_id.startswith("ab_test_video_id_999_")
    
    saved_test = service.active_tests[test_id]
    assert len(saved_test["titles"]) == 3
    assert saved_test["titles"] == ["t1", "t2", "t3"]
    assert len(saved_test["thumbnails"]) == 3
    assert saved_test["thumbnails"] == ["thumb1", "thumb2", "thumb3"]
    assert saved_test["status"] == "RUNNING"

@pytest.mark.asyncio
async def test_get_test_results_not_found(mock_env):
    mock_env
    service = YouTubeABTestService()
    res = await service.get_test_results("non_existent_id")
    assert "error" in res
    assert res["error"] == "Test not found"

@pytest.mark.asyncio
async def test_get_test_results_multiple_variants(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1", "t2", "t3"], ["thumb1", "thumb2", "thumb3"])
    
    results = await service.get_test_results(test_id)
    assert results["test_id"] == test_id
    assert results["video_id"] == "v1"
    assert results["winner_index"] == 0
    assert len(results["variants"]) == 3
    
    assert results["variants"][0]["title"] == "t1"
    assert results["variants"][0]["watch_time_share"] == 40.0
    assert results["variants"][0]["ctr"] == 5.2
    
    assert results["variants"][1]["title"] == "t2"
    assert results["variants"][1]["watch_time_share"] == 30.0
    assert results["variants"][1]["ctr"] == 3.1
    
    assert results["variants"][2]["title"] == "t3"
    assert results["variants"][2]["watch_time_share"] == 30.0
    assert results["variants"][2]["ctr"] == 3.1

@pytest.mark.asyncio
async def test_get_test_results_single_variant(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    
    results = await service.get_test_results(test_id)
    assert test_id in service.active_tests
    assert results["test_id"] == test_id
    assert results["winner_index"] == 0
    assert len(results["variants"]) == 1
    assert results["variants"][0]["title"] == "t1"
    assert results["variants"][0]["watch_time_share"] == 40.0

@pytest.mark.asyncio
async def test_distill_results_to_knowledge_success(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1", "t2"], ["thumb1", "thumb2"])
    results = await service.get_test_results(test_id)
    
    wagamama_mock = MagicMock()
    
    res = await service.distill_results_to_knowledge(results, wagamama_mock)
    assert res is True
    
    wagamama_mock.add_distilled_knowledge.assert_called_once()
    args, kwargs = wagamama_mock.add_distilled_knowledge.call_args
    assert kwargs["topic"] == "A/B Test Winner"
    assert "t1" in kwargs["pattern"]
    assert kwargs["confidence"] == 0.9
    
    assert service.active_tests[test_id]["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_distill_results_to_knowledge_error(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    results = {"error": "some error"}
    res = await service.distill_results_to_knowledge(results)
    assert res is False

# ============================================================
# 新規追加テストケース
# ============================================================

@pytest.mark.asyncio
async def test_register_ab_test_validation_errors(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    with pytest.raises(ValueError, match="video_id cannot be empty"):
        await service.register_ab_test("", ["t1"], ["thumb1"])
        
    with pytest.raises(ValueError, match="title_candidates cannot be empty"):
        await service.register_ab_test("v1", [], ["thumb1"])
        
    with pytest.raises(ValueError, match="thumbnail_paths cannot be empty"):
        await service.register_ab_test("v1", ["t1"], [])

@pytest.mark.asyncio
async def test_register_ab_test_no_clash(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    test_id_1 = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    test_id_2 = await service.register_ab_test("v1", ["t2"], ["thumb2"])
    
    assert test_id_1 != test_id_2
    assert test_id_1 in service.active_tests
    assert test_id_2 in service.active_tests

@pytest.mark.asyncio
async def test_get_test_results_empty_variants_or_invalid_id(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    res = await service.get_test_results("")
    assert "error" in res
    assert res["error"] == "Invalid test_id"
    
    service.active_tests["bad_test"] = {
        "video_id": "v1",
        "titles": ["t1"],
        "thumbnails": []
    }
    
    res = await service.get_test_results("bad_test")
    assert "variants" in res
    assert len(res["variants"]) == 0

@pytest.mark.asyncio
async def test_distill_results_to_knowledge_robustness(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    assert await service.distill_results_to_knowledge(None) is False
    assert await service.distill_results_to_knowledge({"winner_index": 0}) is False
    
    bad_results = {
        "test_id": "test_1",
        "winner_index": 5,
        "variants": [{"title": "t1", "ctr": 5.0}]
    }
    assert await service.distill_results_to_knowledge(bad_results) is False


# ============================================================
# カバレッジ100%達成および堅牢性検証のための追加テストケース
# ============================================================

def test_active_tests_setter(mock_env):
    mock_env
    service = YouTubeABTestService()
    custom_data = {"test_custom": {"video_id": "v_custom", "status": "RUNNING"}}
    service.active_tests = custom_data
    assert service.active_tests == custom_data

@pytest.mark.asyncio
async def test_get_test_results_empty_titles_fallback(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    # titlesを空リストにして登録する
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    # 強制的に保存データを書き換えて titles を空にする
    data = service.active_tests
    data[test_id]["titles"] = []
    service.active_tests = data
    
    results = await service.get_test_results(test_id)
    assert len(results["variants"]) == 1
    assert results["variants"][0]["title"] == "Untitled Variant"

@pytest.mark.asyncio
async def test_save_skipped_on_load_error(mock_env):
    mock_data_dir, mock_file = mock_env
    # 既存データを作成しておく
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    existing_data = {"test_existing": {"video_id": "v_existing", "status": "RUNNING"}}
    with open(mock_file, "w", encoding="utf-8") as f:
        json.dump(existing_data, f)
        
    service = YouTubeABTestService()
    
    # ロード時にエラーを発生させる
    with patch("builtins.open", side_effect=OSError("Read error")):
        # プロパティにアクセスしてロード失敗状態にする
        _ = service.active_tests
        assert service._load_error_occurred is True
        
    # ロードエラー状態で save を試みても、ファイルが上書きされない（既存データが残る）ことを確認
    service._save()
    
    # モックなしでファイルを読み込み、元のデータが残っているか検証
    with open(mock_file, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert saved_data == existing_data


# ============================================================
# 堅牢性強化とエラーハンドリング検証のための追加テストケース (v4.0)
# ============================================================

def test_ensure_file_exists_os_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    # mkdir または open で OSError を投げさせる
    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        data = service.active_tests
        assert data == {}
        assert service._load_error_occurred is True

def test_save_value_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    service = YouTubeABTestService()
    
    # json.dump が ValueError (シリアライズエラー等) を投げた場合
    with patch("json.dump", side_effect=ValueError("Circular reference")):
        # 例外がキャッチされてエラーログが出力され、クラッシュしないことを確認
        service._save()

@pytest.mark.asyncio
async def test_register_ab_test_strict_type_validation(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    # video_id の型エラー
    with pytest.raises(TypeError, match="video_id must be a string"):
        await service.register_ab_test(123, ["t1"], ["thumb1"])
        
    # title_candidates の型エラー
    with pytest.raises(TypeError, match="title_candidates must be a list or tuple"):
        await service.register_ab_test("v1", "not a list", ["thumb1"])
        
    # thumbnail_paths の型エラー
    with pytest.raises(TypeError, match="thumbnail_paths must be a list or tuple"):
        await service.register_ab_test("v1", ["t1"], {"thumb1": "path"})

@pytest.mark.asyncio
async def test_register_ab_test_length_mismatch(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    # 個数の不一致
    with pytest.raises(ValueError, match="The number of title_candidates and thumbnail_paths must be equal"):
        await service.register_ab_test("v1", ["t1", "t2"], ["thumb1"])

@pytest.mark.asyncio
async def test_register_ab_test_invalid_elements(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    # title_candidates 内の型エラー
    with pytest.raises(TypeError, match=r"title_candidates\[1\] must be a string"):
        await service.register_ab_test("v1", ["t1", 123], ["thumb1", "thumb2"])
        
    # title_candidates 内の空文字エラー
    with pytest.raises(ValueError, match=r"title_candidates\[0\] cannot be empty"):
        await service.register_ab_test("v1", ["   "], ["thumb1"])
        
    # thumbnail_paths 内の型エラー
    with pytest.raises(TypeError, match=r"thumbnail_paths\[0\] must be a string"):
        await service.register_ab_test("v1", ["t1"], [None])
        
    # thumbnail_paths 内の空文字エラー
    with pytest.raises(ValueError, match=r"thumbnail_paths\[0\] cannot be empty"):
        await service.register_ab_test("v1", ["t1"], [""])

@pytest.mark.asyncio
async def test_distill_results_non_dict_and_invalid_manager(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    # test_results が dict ではない場合
    assert await service.distill_results_to_knowledge("not a dict") is False
    
    # wagamama_manager が add_distilled_knowledge メソッドを持っていない場合
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    results = await service.get_test_results(test_id)
    
    invalid_manager = object() # メソッドを持たないオブジェクト
    res = await service.distill_results_to_knowledge(results, invalid_manager)
    # クラッシュせずに True (処理成功) を返すことを確認
    assert res is True
    assert service.active_tests[test_id]["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_distill_results_winner_not_dict(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    # variants の要素（winner）が辞書ではない場合
    bad_results = {
        "test_id": "test_1",
        "winner_index": 0,
        "variants": ["not_a_dict"]
    }
    assert await service.distill_results_to_knowledge(bad_results) is False


# ============================================================
# 新規追加テストケース (v4.1 - エラーハンドリング強化検証)
# ============================================================

def test_active_tests_load_general_exception_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    mock_file.touch()
    
    service = YouTubeABTestService()
    
    # 汎用的な例外 (TypeError) を投げさせる
    with patch("builtins.open", side_effect=TypeError("Unexpected type error")):
        data = service.active_tests
        assert data == {}
        assert service._load_error_occurred is True

@pytest.mark.asyncio
async def test_distill_results_to_knowledge_wagamama_manager_exception(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    results = await service.get_test_results(test_id)
    
    # 例外を投げる wagamama_manager を作成
    wagamama_mock = MagicMock()
    wagamama_mock.add_distilled_knowledge.side_effect = RuntimeError("Database error")
    
    # 例外が内部でキャッチされ、クラッシュせずに True を返すことを検証
    res = await service.distill_results_to_knowledge(results, wagamama_mock)
    assert res is True
    assert service.active_tests[test_id]["status"] == "COMPLETED"


# ============================================================
# 新規追加テストケース (v4.2 - 例外型詳細検証)
# ============================================================

def test_active_tests_load_os_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    mock_file.touch()
    
    service = YouTubeABTestService()
    
    with patch("builtins.open", side_effect=OSError("Disk read failure")):
        data = service.active_tests
        assert data == {}
        assert service._load_error_occurred is True

def test_active_tests_load_value_error_handling(mock_env):
    mock_data_dir, mock_file = mock_env
    mock_data_dir.mkdir(parents=True, exist_ok=True)
    mock_file.touch()
    
    service = YouTubeABTestService()
    
    with patch("builtins.open", side_effect=ValueError("Invalid value")):
        data = service.active_tests
        assert data == {}
        assert service._load_error_occurred is True

@pytest.mark.asyncio
async def test_distill_results_wagamama_type_error(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    results = await service.get_test_results(test_id)
    
    wagamama_mock = MagicMock()
    wagamama_mock.add_distilled_knowledge.side_effect = TypeError("Invalid argument types")
    
    res = await service.distill_results_to_knowledge(results, wagamama_mock)
    assert res is True
    assert service.active_tests[test_id]["status"] == "COMPLETED"

@pytest.mark.asyncio
async def test_distill_results_wagamama_value_error(mock_env):
    mock_env
    service = YouTubeABTestService()
    
    test_id = await service.register_ab_test("v1", ["t1"], ["thumb1"])
    results = await service.get_test_results(test_id)
    
    wagamama_mock = MagicMock()
    wagamama_mock.add_distilled_knowledge.side_effect = ValueError("Invalid argument values")
    
    res = await service.distill_results_to_knowledge(results, wagamama_mock)
    assert res is True
    assert service.active_tests[test_id]["status"] == "COMPLETED"
