import sys
import os
import json
import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

# プロジェクトのパスを解決（親ディレクトリを追加して、backend パッケージとしてインポート可能にする）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend import disk_manager

def test_get_drive_root():
    # 正常系：デフォルトパス
    root = disk_manager.get_drive_root()
    assert isinstance(root, str)
    assert len(root) > 0

    # 正常系：任意のパス
    custom_path = Path("C:/Users/PC_User/Test") if sys.platform == "win32" else Path("/usr/local")
    root_custom = disk_manager.get_drive_root(custom_path)
    assert isinstance(root_custom, str)
    if sys.platform == "win32":
        assert root_custom.upper() == "C:\\"
    else:
        assert root_custom == "/"

def test_get_free_gb():
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = (100 * 1024**3, 50 * 1024**3, 20 * 1024**3)
        free = disk_manager.get_free_gb()
        assert free == 20.0

def test_calc_total_input_size_bytes():
    # 存在しないファイルは無視、存在するファイルはサイズ合算
    p1 = Path("temp_p1.mp4")
    p2 = Path("temp_p2.mp4")
    
    # OSに応じた具象クラスをパッチ
    path_class = "pathlib.WindowsPath" if sys.platform == "win32" else "pathlib.PosixPath"
    
    with patch(f"{path_class}.exists") as mock_exists, \
         patch(f"{path_class}.stat") as mock_stat:
        
        # 1回目のexists(p1)はTrue, 2回目のexists(p2)はFalse
        mock_exists.side_effect = [True, False]
        
        # statは1回だけ(p1に対して)呼ばれる
        mock_stat_val = MagicMock()
        mock_stat_val.st_size = 100
        mock_stat.return_value = mock_stat_val
        
        total_size = disk_manager._calc_total_input_size_bytes([p1, p2])
        assert total_size == 100

def test_estimate_needed_gb():
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=4 * 1024**3):
        needed = disk_manager.estimate_needed_gb(["dummy.mp4"], multiplier=2.5)
        # 4GB * 2.5 = 10GB
        assert needed == 10.0

def test_calc_timeout():
    # 1GB = 1024**3 bytes -> 300秒
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=1 * 1024**3):
        assert disk_manager.calc_timeout(["dummy.mp4"]) == 300
        
    # 0.5GB -> 最低値の300秒
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=0.5 * 1024**3):
        assert disk_manager.calc_timeout(["dummy.mp4"]) == 300
        
    # 30GB -> 9000秒だが、最大値の7200秒
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=30 * 1024**3):
        assert disk_manager.calc_timeout(["dummy.mp4"]) == 7200

def test_cleanup_helpers(tmp_path):
    # tmp_path配下にテスト用ディレクトリ構造を作成
    merged_dir = tmp_path / "merged"
    preview_dir = tmp_path / "preview"
    merged_dir.mkdir()
    preview_dir.mkdir()
    
    # 1. _cleanup_old_mp4s のテスト
    f1 = merged_dir / "old1.mp4"
    f2 = merged_dir / "old2.mp4"
    f1.write_text("dummy")
    f2.write_text("dummy")
    
    # mtime をずらす
    import time
    f1_mtime = time.time() - 100
    f2_mtime = time.time()
    os.utime(f1, (f1_mtime, f1_mtime))
    os.utime(f2, (f2_mtime, f2_mtime))
    
    # keep_latest=1, dry_run=True
    freed, deleted = disk_manager._cleanup_old_mp4s(tmp_path, keep_latest=1, dry_run=True)
    assert len(deleted) == 1
    assert "old1.mp4" in deleted
    assert f1.exists()  # dry_runなので削除されない
    
    # keep_latest=1, dry_run=False
    freed, deleted = disk_manager._cleanup_old_mp4s(tmp_path, keep_latest=1, dry_run=False)
    assert len(deleted) == 1
    assert "old1.mp4" in deleted
    assert not f1.exists()  # 削除された
    assert f2.exists()      # 最新なので保持される

    # 削除失敗の例外ハンドリング
    f3 = merged_dir / "old3.mp4"
    f3.write_text("dummy")
    with patch.object(Path, "unlink", side_effect=PermissionError("Permission denied")):
        freed_err, deleted_err = disk_manager._cleanup_old_mp4s(tmp_path, keep_latest=0, dry_run=False)
        assert len(deleted_err) == 0

    # 2. _cleanup_smartcut_parts のテスト
    sc_part = preview_dir / "_smartcut_part1.mp4"
    sc_part.write_text("dummy_part")
    
    # dry_run=True
    freed_sc, deleted_sc = disk_manager._cleanup_smartcut_parts(tmp_path, dry_run=True)
    assert "_smartcut_part1.mp4" in deleted_sc
    assert sc_part.exists()
    
    # dry_run=False
    freed_sc, deleted_sc = disk_manager._cleanup_smartcut_parts(tmp_path, dry_run=False)
    assert "_smartcut_part1.mp4" in deleted_sc
    assert not sc_part.exists()

    # 例外時
    sc_part_err = preview_dir / "_smartcut_part2.mp4"
    sc_part_err.write_text("dummy")
    with patch.object(Path, "unlink", side_effect=RuntimeError):
        freed_err, deleted_err = disk_manager._cleanup_smartcut_parts(tmp_path, dry_run=False)
        assert len(deleted_err) == 0

    # 3. _cleanup_tmp_mp4s のテスト
    tmp_mp4 = tmp_path / "temp.tmp.mp4"
    tmp_mp4.write_text("tmp")
    
    freed_tmp, deleted_tmp = disk_manager._cleanup_tmp_mp4s(tmp_path, dry_run=False)
    assert "temp.tmp.mp4" in deleted_tmp
    assert not tmp_mp4.exists()

    # 例外時
    tmp_mp4_err = tmp_path / "temp_err.tmp.mp4"
    tmp_mp4_err.write_text("tmp")
    with patch.object(Path, "unlink", side_effect=RuntimeError):
        freed_err, deleted_err = disk_manager._cleanup_tmp_mp4s(tmp_path, dry_run=False)
        assert len(deleted_err) == 0

    # 4. _cleanup_concat_txts のテスト
    concat_txt = merged_dir / "concat_1.txt"
    concat_txt.write_text("list")
    
    # dry_run=True
    disk_manager._cleanup_concat_txts(tmp_path, dry_run=True)
    assert concat_txt.exists()

    # dry_run=False
    disk_manager._cleanup_concat_txts(tmp_path, dry_run=False)
    assert not concat_txt.exists()

    # 例外時
    concat_txt_err = merged_dir / "concat_err.txt"
    concat_txt_err.write_text("list")
    with patch.object(Path, "unlink", side_effect=RuntimeError):
        disk_manager._cleanup_concat_txts(tmp_path, dry_run=False)
        assert concat_txt_err.exists()

def test_cleanup_helpers_missing_dir(tmp_path):
    # previewディレクトリが存在しない場合（L78の coverage 分岐をカバー）
    # preview_dir は作成せず merged_dir のみ作成
    merged_dir = tmp_path / "merged"
    merged_dir.mkdir()
    
    (merged_dir / "test.mp4").write_text("1")
    
    freed, deleted = disk_manager._cleanup_old_mp4s(tmp_path, keep_latest=0, dry_run=False)
    assert len(deleted) == 1
    assert "test.mp4" in deleted

def test_cleanup_intermediates(tmp_path):
    # 各ディレクトリを用意
    merged_dir = tmp_path / "merged"
    preview_dir = tmp_path / "preview"
    merged_dir.mkdir()
    preview_dir.mkdir()
    
    # mp4を作成
    (merged_dir / "test1.mp4").write_text("1")
    (merged_dir / "test2.mp4").write_text("2")
    (preview_dir / "_smartcut_part.mp4").write_text("part")
    (tmp_path / "test.tmp.mp4").write_text("tmp")
    (merged_dir / "concat_list.txt").write_text("list")
    
    # cleanup_intermediates を呼び出す
    freed_gb = disk_manager.cleanup_intermediates(outputs_dir=tmp_path, keep_latest=1, dry_run=False)
    assert freed_gb > 0

    # 何も削除しない場合
    freed_gb_empty = disk_manager.cleanup_intermediates(outputs_dir=tmp_path, keep_latest=5, dry_run=False)
    assert freed_gb_empty == 0.0

def test_ensure_disk_space():
    with patch("backend.disk_manager.get_free_gb") as mock_free, \
         patch("backend.disk_manager.estimate_needed_gb", return_value=15.0), \
         patch("backend.disk_manager.cleanup_intermediates", return_value=5.0) as mock_cleanup:
        
        # ケース1: 空き容量十分
        mock_free.side_effect = [20.0]
        res = disk_manager.ensure_disk_space(["dummy.mp4"], min_free_gb=10.0)
        assert res is True
        mock_cleanup.assert_not_called()
        
        # ケース2: 空き容量不足 -> クリーンアップで回復
        mock_cleanup.reset_mock()
        mock_free.side_effect = [5.0, 16.0]  # 1回目不足、2回目十分
        res = disk_manager.ensure_disk_space(["dummy.mp4"], min_free_gb=10.0)
        assert res is True
        mock_cleanup.assert_called_once()

        # ケース3: 空き容量不足 -> クリーンアップしても回復せず
        mock_cleanup.reset_mock()
        mock_free.side_effect = [5.0, 8.0]
        res = disk_manager.ensure_disk_space(["dummy.mp4"], min_free_gb=10.0)
        assert res is False

def create_dummy_image_bytes(size=(1280, 720), format="JPEG"):
    img = Image.new("RGB", size, color="blue")
    out = BytesIO()
    img.save(out, format=format)
    return out.getvalue()

def test_verify_thumbnail_quality(tmp_path):
    # 正常系 (bytes)
    valid_bytes = create_dummy_image_bytes(size=(1280, 720))
    assert disk_manager.verify_thumbnail_quality(valid_bytes) is True
    
    # 正常系 (base64)
    valid_b64 = base64.b64encode(valid_bytes).decode("utf-8")
    assert disk_manager.verify_thumbnail_quality(valid_b64) is True
    
    # 正常系 (Path)
    img_file = tmp_path / "thumb.jpg"
    img_file.write_bytes(valid_bytes)
    assert disk_manager.verify_thumbnail_quality(img_file) is True
    
    # 正常系 (strとしてのパス)
    assert disk_manager.verify_thumbnail_quality(str(img_file)) is True

    # 異常系: 不正な型
    assert disk_manager.verify_thumbnail_quality(12345) is False

    # 異常系: ファイルサイズ超過 (4MB以上)
    large_bytes = b"0" * (4 * 1024 * 1024 + 10)
    assert disk_manager.verify_thumbnail_quality(large_bytes) is False

    # 異常系: 解像度不足 (1280x720未満、例えば 640x360)
    low_res_bytes = create_dummy_image_bytes(size=(640, 360))
    assert disk_manager.verify_thumbnail_quality(low_res_bytes) is False

    # 異常系: アスペクト比異常 (16:9 ではない、例えば 1280x1280)
    square_bytes = create_dummy_image_bytes(size=(1280, 1280))
    assert disk_manager.verify_thumbnail_quality(square_bytes) is False

    # 異常系: 画像破損 / Pillowロード失敗
    corrupt_bytes = b"not an image file content"
    assert disk_manager.verify_thumbnail_quality(corrupt_bytes) is False

    # base64デコード例外や文字列パス存在しない場合
    assert disk_manager.verify_thumbnail_quality("invalid_string_not_path_nor_b64") is False

def test_verify_thumbnail_quality_outer_exception():
    # L285-287の outer try-except Exception block をカバーするために、
    # 処理中で予期せぬ例外をスローさせる
    with patch("backend.disk_manager.isinstance", side_effect=TypeError("Unexpected error")):
        assert disk_manager.verify_thumbnail_quality(b"dummy") is False

@pytest.mark.asyncio
async def test_process_thumbnail_task():
    # 正常系: ダミーのジェネレータを使用
    valid_bytes = create_dummy_image_bytes(size=(1280, 720))
    valid_b64 = base64.b64encode(valid_bytes).decode("utf-8")
    
    class MockGenerator:
        async def generate(self, prompt):
            return [{
                "id": "t1",
                "concept_name": "Concept 1",
                "description": "Desc 1",
                "image_base64": valid_b64,
                "ctr_score": 8.5
            }]
            
    res_json = await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=MockGenerator())
    res = json.loads(res_json)
    assert res["status"] == "verified"
    assert len(res["thumbnails"]) == 1
    assert res["thumbnails"][0]["id"] == "t1"

    # 異常系: ジェネレータが例外を発生
    class ErrorGenerator:
        async def generate(self, prompt):
            raise RuntimeError("Generator Error")
            
    with pytest.raises(ValueError) as exc:
        await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=ErrorGenerator())
    assert "Thumbnail generation failed" in str(exc.value)

    # 異常系: ジェネレータ結果が空
    class EmptyGenerator:
        async def generate(self, prompt):
            return []
            
    with pytest.raises(ValueError) as exc:
        await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=EmptyGenerator())
    assert "Thumbnail generator returned no results" in str(exc.value)

    # 異常系: 品質検証ですべて不合格（300x300未満の極小画像で最適化も失敗させる）
    low_res_bytes = create_dummy_image_bytes(size=(100, 100))
    low_res_b64 = base64.b64encode(low_res_bytes).decode("utf-8")
    class BadGenerator:
        async def generate(self, prompt):
            return [{
                "id": "t2",
                "concept_name": "Concept 2",
                "image_base64": low_res_b64,
                "ctr_score": 1.0
            }]
            
    with pytest.raises(ValueError) as exc:
        await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=BadGenerator())
    assert "Thumbnail verification failed" in str(exc.value)

    # 正常系: thumbnail_generator=None の場合 (DummyGeneratorのロード)
    # sys.modules をモックして強制的に ImportError を起こす（L297-308のカバー）
    with patch.dict(sys.modules, {"thumbnail_engine": None, "thumbnail_engine.generator": None}):
        res_json = await disk_manager.process_thumbnail_task("task_fallback", thumbnail_generator=None)
        res = json.loads(res_json)
        assert res["status"] == "verified"
        assert len(res["thumbnails"]) == 1
        assert res["thumbnails"][0]["concept_name"] == "Fallback Concept"

    # 正常系: thumbnail_generator=None の場合で、thumbnail_engine がインポート可能な場合（L299のカバー）
    class DummyThumbnailGeneratorClass:
        def __init__(self):
            pass
        async def generate(self, prompt):
            return [{
                "id": "t_ok",
                "concept_name": "Concept OK",
                "description": "Desc OK",
                "image_base64": valid_b64,
                "ctr_score": 9.0
            }]

    mock_generator_module = MagicMock()
    mock_generator_module.ThumbnailGenerator = DummyThumbnailGeneratorClass
    
    with patch.dict(sys.modules, {
        "thumbnail_engine": mock_generator_module,
        "thumbnail_engine.generator": mock_generator_module
    }):
        res_json = await disk_manager.process_thumbnail_task("task_import_ok", thumbnail_generator=None)
        res = json.loads(res_json)
        assert res["status"] == "verified"
        assert len(res["thumbnails"]) == 1
        assert res["thumbnails"][0]["concept_name"] == "Concept OK"

def test_safe_io_import_error():
    import importlib
    with patch.dict(sys.modules, {"safe_io": None}):
        disk_manager_cached = sys.modules.pop("backend.disk_manager", None)
        try:
            import backend.disk_manager as dm
            assert dm.VAULT_OUTPUTS_DIR.name == "vault-outputs"
        finally:
            if disk_manager_cached:
                sys.modules["backend.disk_manager"] = disk_manager_cached

@pytest.mark.asyncio
async def test_process_thumbnail_task_empty_image_b64():
    class EmptyImageGenerator:
        async def generate(self, prompt):
            return [
                {
                    "id": "t_empty_1",
                    "concept_name": "Empty 1",
                    "image_base64": ""
                },
                {
                    "id": "t_empty_2",
                    "concept_name": "Empty 2",
                }
            ]
    with pytest.raises(ValueError) as exc:
        await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=EmptyImageGenerator())
    assert "Thumbnail verification failed" in str(exc.value)

@pytest.mark.asyncio
async def test_process_thumbnail_task_invalid_b64():
    valid_bytes = create_dummy_image_bytes(size=(1280, 720))
    with patch("scratch.disk_cleanup.optimize_thumbnail", return_value=valid_bytes):
        class InvalidB64Generator:
            async def generate(self, prompt):
                return [
                    {
                        "id": "t_invalid",
                        "concept_name": "Invalid B64",
                        "image_base64": "A"
                    }
                ]
        res_json = await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=InvalidB64Generator())
        res = json.loads(res_json)
        assert res["status"] == "verified"
        assert len(res["thumbnails"]) == 1
        assert res["thumbnails"][0]["id"] == "t_invalid"

@pytest.mark.asyncio
async def test_process_thumbnail_task_import_error_disk_cleanup():
    with patch.dict(sys.modules, {"scratch.disk_cleanup": None}):
        class MockGenerator:
            async def generate(self, prompt):
                return [{
                    "id": "t1",
                    "concept_name": "Concept 1",
                    "image_base64": base64.b64encode(create_dummy_image_bytes()).decode("utf-8"),
                    "ctr_score": 8.5
                }]
        res_json = await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=MockGenerator())
        res = json.loads(res_json)
        assert res["status"] == "verified"


def test_cleanup_helpers_missing_all_dirs(tmp_path):
    # preview と merged ディレクトリが存在しない状態でヘルパーを呼び出す
    # 97->107, 129->exit のブランチをカバー
    freed_sc, deleted_sc = disk_manager._cleanup_smartcut_parts(tmp_path, dry_run=False)
    assert freed_sc == 0
    assert len(deleted_sc) == 0

    disk_manager._cleanup_concat_txts(tmp_path, dry_run=False)

def test_cleanup_tmp_mp4s_dry_run(tmp_path):
    # dry_run=True の場合のテスト。117->119 のブランチをカバー
    tmp_mp4 = tmp_path / "temp.tmp.mp4"
    tmp_mp4.write_text("tmp")
    freed_tmp, deleted_tmp = disk_manager._cleanup_tmp_mp4s(tmp_path, dry_run=True)
    assert "temp.tmp.mp4" in deleted_tmp
    assert tmp_mp4.exists()

@pytest.mark.asyncio
async def test_process_thumbnail_task_import_error_and_optimize_fallback():
    # scratch.disk_cleanup がインポートできず、かつ画像が検証不合格になるテスト
    # 325->exit, 351->327 のブランチをカバー
    low_res_bytes = create_dummy_image_bytes(size=(100, 100))
    low_res_b64 = base64.b64encode(low_res_bytes).decode("utf-8")
    
    with patch.dict(sys.modules, {"scratch.disk_cleanup": None}):
        class BadGenerator:
            async def generate(self, prompt):
                return [{
                    "id": "t_bad",
                    "concept_name": "Bad Concept",
                    "image_base64": low_res_b64,
                    "ctr_score": 2.0
                }]
        
        with pytest.raises(ValueError) as exc:
            await disk_manager.process_thumbnail_task("task_123", thumbnail_generator=BadGenerator())
        assert "Thumbnail verification failed" in str(exc.value)
