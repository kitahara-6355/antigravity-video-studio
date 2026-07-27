import sys
import os
import importlib
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

# Add backend directory to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def test_disk_cleanup_success():
    # Mock size configuration
    mock_stat_obj = MagicMock()
    mock_stat_obj.st_size = 1024 * 1024  # 1MB

    # Mock Path objects for glob
    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.is_dir.return_value = False
    mock_file.name = "test_file.mp4"
    mock_file.stat.return_value = mock_stat_obj

    mock_dir = MagicMock(spec=Path)
    mock_dir.is_file.return_value = False
    mock_dir.is_dir.return_value = True
    mock_dir.name = "test_dir"

    mock_gitkeep = MagicMock(spec=Path)
    mock_gitkeep.is_file.return_value = True
    mock_gitkeep.is_dir.return_value = False
    mock_gitkeep.name = ".gitkeep"

    # Side effects configuration
    glob_side_effect = [
        [mock_file, mock_dir, mock_gitkeep],  # base_dir / "temp"
        [],                                  # base_dir / "graded_previews"
        [],                                  # base_dir / "graded_videos"
        [],                                  # base_dir / "output"
        [mock_dir]                           # worktrees_dir
    ]

    exists_side_effect = [
        True,  # large_files lf.exists() (debug_outputTEMP_MPY_wvf_snd.mp3)
        True,  # clean_dir temp exists
        True,  # clean_dir graded_previews exists
        True,  # clean_dir graded_videos exists
        True,  # clean_dir output exists
        True   # worktrees_dir exists
    ]

    with patch('pathlib.Path.exists', side_effect=exists_side_effect), \
         patch('pathlib.Path.glob', side_effect=glob_side_effect), \
         patch('pathlib.Path.stat', return_value=mock_stat_obj), \
         patch('pathlib.Path.unlink') as mock_unlink, \
         patch('shutil.rmtree') as mock_rmtree, \
         patch('builtins.print') as mock_print:

        import backend.scratch.disk_cleanup as disk_cleanup
        disk_cleanup.run_cleanup()

        # Assertions
        assert mock_unlink.call_count == 1  # only large_files lf.unlink() (since mock_file has its own mock)
        mock_file.unlink.assert_called_once()  # mock_file.unlink() in clean_dir
        assert mock_rmtree.call_count == 2  # clean_dir (mock_dir) + worktrees_dir (mock_dir)
        assert disk_cleanup.deleted_bytes == 2 * 1024 * 1024
        mock_print.assert_called_with("Total freed: 2.00 MB")


def test_disk_cleanup_not_exists():
    with patch('pathlib.Path.exists', return_value=False), \
         patch('pathlib.Path.glob', return_value=[]), \
         patch('pathlib.Path.unlink') as mock_unlink, \
         patch('shutil.rmtree') as mock_rmtree, \
         patch('builtins.print') as mock_print:

        import backend.scratch.disk_cleanup as disk_cleanup
        disk_cleanup.run_cleanup()

        assert mock_unlink.call_count == 0
        assert mock_rmtree.call_count == 0
        assert disk_cleanup.deleted_bytes == 0
        mock_print.assert_called_with("Total freed: 0.00 MB")


def test_disk_cleanup_exceptions():
    mock_stat_obj = MagicMock()
    mock_stat_obj.st_size = 1024 * 1024

    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.is_dir.return_value = False
    mock_file.name = "test_file.mp4"
    mock_file.stat.return_value = mock_stat_obj
    # Explicitly make mock_file.unlink throw an exception to cover line 18-19 in clean_dir
    mock_file.unlink.side_effect = Exception("mock_file unlink failure")

    mock_dir = MagicMock(spec=Path)
    mock_dir.is_file.return_value = False
    mock_dir.is_dir.return_value = True
    mock_dir.name = "test_dir"

    glob_side_effect = [
        [mock_file, mock_dir],  # temp
        [],                    # graded_previews
        [],                    # graded_videos
        [],                    # output
        [mock_dir]             # worktrees_dir
    ]

    exists_side_effect = [
        True,  # large_files lf.exists()
        True,  # temp exists
        True,  # graded_previews exists
        True,  # graded_videos exists
        True,  # output exists
        True   # worktrees_dir exists
    ]

    with patch('pathlib.Path.exists', side_effect=exists_side_effect), \
         patch('pathlib.Path.glob', side_effect=glob_side_effect), \
         patch('pathlib.Path.stat', return_value=mock_stat_obj), \
         patch('pathlib.Path.unlink', side_effect=Exception("unlink failure")), \
         patch('shutil.rmtree', side_effect=Exception("rmtree failure")), \
         patch('builtins.print') as mock_print:

        import backend.scratch.disk_cleanup as disk_cleanup
        disk_cleanup.run_cleanup()

        # Exceptions should be caught via 'except Exception: pass'
        assert disk_cleanup.deleted_bytes == 0
        mock_print.assert_called_with("Total freed: 0.00 MB")


# --- サムネイル画像生成・品質検証自動化テスト ---
import base64
import sqlite3
import pytest
import asyncio
from io import BytesIO
from PIL import Image
from unittest.mock import MagicMock, patch

from disk_manager import verify_thumbnail_quality, process_thumbnail_task
from agents.stage_bound_agent import StageBoundAgent

def create_dummy_image(width, height, fmt="JPEG", size_bytes=0):
    img = Image.new("RGB", (width, height), color="red")
    out = BytesIO()
    img.save(out, format=fmt)
    data = out.getvalue()
    if len(data) < size_bytes:
        data += b"\x00" * (size_bytes - len(data))
    return data

def test_verify_thumbnail_quality_valid_bytes():
    data = create_dummy_image(1280, 720, "JPEG")
    assert verify_thumbnail_quality(data) is True

def test_verify_thumbnail_quality_valid_path(tmp_path):
    data = create_dummy_image(1920, 1080, "JPEG")
    img_path = tmp_path / "valid_thumb.jpg"
    img_path.write_bytes(data)
    assert verify_thumbnail_quality(img_path) is True
    assert verify_thumbnail_quality(str(img_path)) is True

def test_verify_thumbnail_quality_valid_base64():
    data = create_dummy_image(1280, 720, "JPEG")
    b64_data = base64.b64encode(data).decode("utf-8")
    assert verify_thumbnail_quality(b64_data) is True

def test_verify_thumbnail_quality_invalid_resolution():
    data_width = create_dummy_image(1279, 720, "JPEG")
    assert verify_thumbnail_quality(data_width) is False
    data_height = create_dummy_image(1280, 719, "JPEG")
    assert verify_thumbnail_quality(data_height) is False

def test_verify_thumbnail_quality_invalid_aspect_ratio():
    data_aspect = create_dummy_image(1280, 1280, "JPEG")
    assert verify_thumbnail_quality(data_aspect) is False

def test_verify_thumbnail_quality_too_large():
    data_large = create_dummy_image(1280, 720, "JPEG", size_bytes=4 * 1024 * 1024 + 10)
    assert verify_thumbnail_quality(data_large) is False

def test_verify_thumbnail_quality_corrupted():
    assert verify_thumbnail_quality(b"invalid_corrupted_data") is False

@pytest.mark.asyncio
async def test_process_thumbnail_task_success(tmp_path):
    db_file = tmp_path / "thumbnail_task_success.db"
    mock_generator = MagicMock()
    valid_img = create_dummy_image(1280, 720, "JPEG")
    valid_img_b64 = base64.b64encode(valid_img).decode("utf-8")
    async def mock_generate(*args, **kwargs):
        return [{"id": "thumb_0", "concept_name": "Concept A", "description": "Desc A", "ctr_score": 7.8, "image_base64": valid_img_b64}]
    mock_generator.generate = mock_generate

    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_success_01", initial_status="READY")

    async def process_wrapper(task_id):
        return await process_thumbnail_task(task_id, db_path=str(db_file), thumbnail_generator=mock_generator)

    await agent.start(process_wrapper)
    await asyncio.sleep(0.3)

    final_status = await agent.get_task_status("t_success_01")
    assert final_status == "COMPLETED"

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result FROM tasks WHERE id = 't_success_01'")
        res_str = cursor.fetchone()[0]
        assert "Concept A" in res_str
        assert "verified" in res_str
    finally:
        conn.close()
    await agent.stop()

@pytest.mark.asyncio
async def test_process_thumbnail_task_retry_and_fail(tmp_path):
    db_file = tmp_path / "thumbnail_task_fail.db"
    mock_generator = MagicMock()
    invalid_img = create_dummy_image(100, 100, "JPEG")
    invalid_img_b64 = base64.b64encode(invalid_img).decode("utf-8")
    async def mock_generate(*args, **kwargs):
        return [{"id": "thumb_0", "concept_name": "Concept Invalid", "description": "Desc Invalid", "ctr_score": 2.1, "image_base64": invalid_img_b64}]
    mock_generator.generate = mock_generate

    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_fail_01", initial_status="READY", max_retries=2)

    async def process_wrapper(task_id):
        return await process_thumbnail_task(task_id, db_path=str(db_file), thumbnail_generator=mock_generator)

    await agent.start(process_wrapper)
    await asyncio.sleep(0.6)

    final_status = await agent.get_task_status("t_fail_01")
    assert final_status == "FAILED"

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = 't_fail_01'")
        row = cursor.fetchone()
        assert row[0] == 2
        assert "Thumbnail verification failed" in row[1]
    finally:
        conn.close()
    await agent.stop()


def test_disk_cleanup_gitkeep_skipped_explicit():
    # .gitkeep ファイルが無視されることを明示的にテストする
    mock_gitkeep = MagicMock(spec=Path)
    mock_gitkeep.is_file.return_value = True
    mock_gitkeep.is_dir.return_value = False
    mock_gitkeep.name = ".gitkeep"

    glob_side_effect = [
        [mock_gitkeep],  # base_dir / "temp"
        [],             # base_dir / "graded_previews"
        [],             # base_dir / "graded_videos"
        [],             # base_dir / "output"
        []              # worktrees_dir
    ]

    exists_side_effect = [
        False, # large_files lf.exists()
        True,  # temp exists
        True,  # graded_previews exists
        True,  # graded_videos exists
        True,  # output exists
        False  # worktrees_dir exists
    ]

    with patch('pathlib.Path.exists', side_effect=exists_side_effect),          patch('pathlib.Path.glob', side_effect=glob_side_effect),          patch('pathlib.Path.unlink') as mock_unlink,          patch('shutil.rmtree') as mock_rmtree,          patch('builtins.print'):

        import backend.scratch.disk_cleanup as disk_cleanup
        disk_cleanup.run_cleanup()

        # .gitkeep の unlink や rmtree が呼ばれていないことを確認
        assert mock_unlink.call_count == 0
        assert mock_rmtree.call_count == 0
        mock_gitkeep.unlink.assert_not_called()
        assert disk_cleanup.deleted_bytes == 0


def test_disk_cleanup_large_file_stat_exception():
    # 巨大ファイルの stat 取得時に例外が発生した場合のテスト
    glob_side_effect = [
        [], [], [], [], []
    ]

    exists_side_effect = [
        True,  # large_files lf.exists() (debug_outputTEMP_MPY_wvf_snd.mp3)
        False, # temp exists
        False, # graded_previews exists
        False, # graded_videos exists
        False, # output exists
        False  # worktrees_dir exists
    ]

    with patch('pathlib.Path.exists', side_effect=exists_side_effect),          patch('pathlib.Path.glob', side_effect=glob_side_effect),          patch('pathlib.Path.stat', side_effect=Exception("stat failure")),          patch('pathlib.Path.unlink') as mock_unlink,          patch('builtins.print') as mock_print:

        import backend.scratch.disk_cleanup as disk_cleanup
        disk_cleanup.run_cleanup()

        # 例外が発生しても deleted_bytes は 0 のまま、正常終了する
        assert disk_cleanup.deleted_bytes == 0
        mock_print.assert_called_with("Total freed: 0.00 MB")


def test_disk_cleanup_clean_dir_direct_call():
    # clean_dir 関数を直接呼び出して動作確認する
    with patch('pathlib.Path.exists', return_value=False),          patch('builtins.print'):
        import backend.scratch.disk_cleanup as disk_cleanup

    disk_cleanup.deleted_bytes = 0

    mock_file = MagicMock(spec=Path)
    mock_file.is_file.return_value = True
    mock_file.is_dir.return_value = False
    mock_file.name = "normal_file.txt"
    mock_stat = MagicMock()
    mock_stat.st_size = 500
    mock_file.stat.return_value = mock_stat

    mock_dir = MagicMock(spec=Path)
    mock_dir.is_file.return_value = False
    mock_dir.is_dir.return_value = True
    mock_dir.name = "sub_dir"

    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.glob.return_value = [mock_file, mock_dir]

    with patch('shutil.rmtree') as mock_rmtree:
        disk_cleanup.clean_dir(mock_path, "*")
        
        mock_file.unlink.assert_called_once()
        mock_rmtree.assert_called_once_with(mock_dir)
        assert disk_cleanup.deleted_bytes == 500


# --- 新規追加: サムネイル自動補正・最適化ロジックの検証テスト ---
def test_optimize_thumbnail_direct():
    from scratch.disk_cleanup import optimize_thumbnail
    
    # 1. アスペクト比 1:1, 低解像度 (500x500) の画像を補正
    bad_img_bytes = create_dummy_image(500, 500, "JPEG")
    optimized = optimize_thumbnail(bad_img_bytes)
    
    # 補正結果の検証
    assert verify_thumbnail_quality(optimized) is True
    
    with Image.open(BytesIO(optimized)) as img:
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w/h) - (16/9)) < 0.05

    # 2. 超巨大ファイルサイズ画像の補正
    # ダミーバイトを詰めて 4.5MB の画像を作成
    large_img_bytes = create_dummy_image(1920, 1080, "JPEG", size_bytes=4 * 1024 * 1024 + 500 * 1024)
    assert len(large_img_bytes) > 4 * 1024 * 1024
    
    optimized_large = optimize_thumbnail(large_img_bytes)
    assert len(optimized_large) < 4 * 1024 * 1024
    assert verify_thumbnail_quality(optimized_large) is True


@pytest.mark.asyncio
async def test_process_thumbnail_task_auto_correct_aspect_and_resolution(tmp_path):
    db_file = tmp_path / "thumbnail_task_autocorrect.db"
    mock_generator = MagicMock()
    
    # 1:1 アスペクト比の 500x500 画像を返す mock (そのままでは verify に落ちるはず)
    invalid_img = create_dummy_image(500, 500, "JPEG")
    invalid_img_b64 = base64.b64encode(invalid_img).decode("utf-8")
    
    async def mock_generate(*args, **kwargs):
        return [{"id": "thumb_autocorrect", "concept_name": "Concept Auto", "description": "Desc Auto", "ctr_score": 8.0, "image_base64": invalid_img_b64}]
    mock_generator.generate = mock_generate

    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    await agent.register_task(task_id="t_autocorrect_01", initial_status="READY")

    async def process_wrapper(task_id):
        return await process_thumbnail_task(task_id, db_path=str(db_file), thumbnail_generator=mock_generator)

    await agent.start(process_wrapper)
    await asyncio.sleep(0.5)

    final_status = await agent.get_task_status("t_autocorrect_01")
    # 自動補正されるため COMPLETED になるはず
    assert final_status == "COMPLETED"

    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("SELECT result FROM tasks WHERE id = 't_autocorrect_01'")
        res_str = cursor.fetchone()[0]
        assert "Concept Auto" in res_str
        assert "verified" in res_str
    finally:
        conn.close()
    await agent.stop()

def test_optimize_thumbnail_corrupted_verify_exception():
    from scratch.disk_cleanup import optimize_thumbnail
    # 画像オープン/verifyで例外が発生する無効なデータ
    with pytest.raises(ValueError, match="Image is corrupted or invalid"):
        optimize_thumbnail(b"completely_invalid_and_corrupted_image_data")


def test_optimize_thumbnail_wide_aspect_ratio_cropping():
    from scratch.disk_cleanup import optimize_thumbnail
    # 2000x500 (アスペクト比 4:1) の横長画像を作成して渡す
    # トリミングとリサイズにより、アスペクト比 16:9 で 1280x720 以上のサイズに調整されるはず
    wide_img_bytes = create_dummy_image(2000, 500, "JPEG")
    optimized = optimize_thumbnail(wide_img_bytes)
    
    assert verify_thumbnail_quality(optimized) is True
    with Image.open(BytesIO(optimized)) as img:
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w/h) - (16/9)) < 0.05


def test_optimize_thumbnail_compression_loop():
    from scratch.disk_cleanup import optimize_thumbnail
    
    # 正常な 1280x720 JPEG 画像データを用意
    img_data = create_dummy_image(1280, 720, "JPEG")
    
    # Image.save メソッドをモックして、1回目の save 時には 4MB 以上の大きなバイト列を返し、
    # 2回目（quality が 95 から 90 に低下）の save 時には 100KB の小さいバイト列を返すようにする。
    original_save = Image.Image.save
    
    call_count = 0
    def mock_save(self, fp, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # 1回目は 4MB 以上のサイズを書き込む
            fp.write(bytes([0] * (4 * 1024 * 1024 + 100)))
        else:
            # 2回目以降は通常通り保存
            original_save(self, fp, *args, **kwargs)
            
    with patch.object(Image.Image, 'save', mock_save):
        optimized = optimize_thumbnail(img_data)
        assert len(optimized) < 4 * 1024 * 1024
        assert call_count == 2  # 圧縮ループが1回回ったことを確認


def test_optimize_thumbnail_compression_failure():
    from scratch.disk_cleanup import optimize_thumbnail
    
    img_data = create_dummy_image(1280, 720, "JPEG")
    
    # Image.save が常に 4MB 以上のバイト列を書き込むようにモックする
    def mock_save_always_large(self, fp, *args, **kwargs):
        fp.write(bytes([0] * (4 * 1024 * 1024 + 100)))
        
    with patch.object(Image.Image, 'save', mock_save_always_large):
        with pytest.raises(ValueError, match="Failed to compress image to less than 4MB"):
            optimize_thumbnail(img_data)


# --- agents/orchestration/cleanup_disk.py 用のユニットテスト ---
import tempfile
import time
from agents.orchestration.cleanup_disk import main as cleanup_main

def test_cleanup_disk_agent_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        # ディレクトリ構造を作成
        # 1. アクティブフォルダ
        active_dir = os.path.join(tmpdir, "active_session")
        os.makedirs(active_dir)
        # 2. 直近更新フォルダ
        recent_dir = os.path.join(tmpdir, "recent_session")
        os.makedirs(recent_dir)
        # 3. 古いフォルダ
        old_dir = os.path.join(tmpdir, "old_session")
        os.makedirs(old_dir)
        
        # ダミーファイルを古いフォルダ内に作成してサイズを持たせる
        dummy_file = os.path.join(old_dir, "dummy.txt")
        with open(dummy_file, "w") as f:
            f.write("hello" * 200) # 1000 bytes
            
        # mtime を操作する
        now = time.time()
        # recent_session: 最終更新を現在時刻にする
        os.utime(recent_dir, (now, now))
        # old_session: 最終更新を3日前にする
        three_days_ago = now - (3 * 24 * 60 * 60)
        os.utime(old_dir, (three_days_ago, three_days_ago))
        
        # クリーンアップ実行
        # keep_days = 1 (1日より古いものを削除)
        cleanup_main(brain_dir=tmpdir, active_ids={"active_session"}, keep_days=1)
        
        # 検証
        assert os.path.exists(active_dir)
        assert os.path.exists(recent_dir)
        assert not os.path.exists(old_dir)


def test_cleanup_disk_agent_mtime_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = os.path.join(tmpdir, "old_session")
        os.makedirs(old_dir)
        
        # os.path.getmtime が OSError を投げるようにモックする
        with patch("os.path.getmtime", side_effect=OSError("Access denied")):
            cleanup_main(brain_dir=tmpdir, active_ids=set(), keep_days=1)
            
        # getmtime でエラーが出たディレクトリは安全のため残る
        assert os.path.exists(old_dir)


def test_cleanup_disk_agent_delete_permission_error():
    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = os.path.join(tmpdir, "old_session")
        os.makedirs(old_dir)
        
        # 3日前に設定
        three_days_ago = time.time() - (3 * 24 * 60 * 60)
        os.utime(old_dir, (three_days_ago, three_days_ago))
        
        # 削除時に PermissionError が発生して削除されなかったケースを模擬
        with patch("shutil.rmtree") as mock_rmtree:
            cleanup_main(brain_dir=tmpdir, active_ids=set(), keep_days=1)
            mock_rmtree.assert_called_once()
            
        # 削除されずフォルダは残る
        assert os.path.exists(old_dir)


def test_cleanup_disk_agent_readonly_removal():
    import stat
    with tempfile.TemporaryDirectory() as tmpdir:
        old_dir = os.path.join(tmpdir, "old_session")
        os.makedirs(old_dir)
        
        # 読み取り専用のファイルを作成
        readonly_file = os.path.join(old_dir, "readonly.txt")
        with open(readonly_file, "w") as f:
            f.write("readonly content")
        
        # 読み取り専用属性を付与
        os.chmod(readonly_file, stat.S_IREAD)
        
        # 3日前に設定
        three_days_ago = time.time() - (3 * 24 * 60 * 60)
        os.utime(old_dir, (three_days_ago, three_days_ago))
        os.utime(readonly_file, (three_days_ago, three_days_ago))
        
        # クリーンアップ実行
        cleanup_main(brain_dir=tmpdir, active_ids=set(), keep_days=1)
        
        # 読み取り専用ファイルごと、フォルダが正常に削除されていることを検証
        assert not os.path.exists(old_dir)



def test_cleanup_disk_agent_readonly_removal_typeerror():
    # os.chmod などの複数引数を要する関数が func として渡された場合、
    # TypeError でクラッシュしないことを検証する
    from agents.orchestration.cleanup_disk import _handle_remove_readonly
    
    # 2引数取る os.chmod を func に見立てて渡す。
    # 第3引数は例外オブジェクト (Python 3.12 以降の挙動)
    try:
        _handle_remove_readonly(os.chmod, "dummy_path", Exception("Mock failure"))
    except TypeError as e:
        pytest.fail(f"_handle_remove_readonly raised TypeError: {e}")


def test_cleanup_disk_agent_parent_protection(tmp_path):
    # パスから親の会話ID (UUID形式) を動的に抽出して active_ids に追加されるか検証する。
    # agents/orchestration/cleanup_disk.py を mock_file として実行する形を模擬する。
    import tempfile
    
    # brain/<parent_uuid>/.system_generated/worktrees/<sub_dir>/cleanup_disk.py という構造をシミュレート
    parent_uuid = "11111111-2222-3333-4444-555555555555"
    
    # 構造： mock_brain_dir/11111111-2222-3333-4444-555555555555/dummy_worktree
    mock_brain_dir = tmp_path / "brain"
    mock_parent_dir = mock_brain_dir / parent_uuid
    mock_worktree = mock_parent_dir / "dummy_worktree"
    mock_worktree.mkdir(parents=True)
    
    # 古い削除対象のフォルダも作成
    old_session_dir = mock_brain_dir / "99999999-9999-9999-9999-999999999999"
    old_session_dir.mkdir()
    
    # 最終更新を3日前にする
    now = time.time()
    three_days_ago = now - (3 * 24 * 60 * 60)
    os.utime(str(old_session_dir), (three_days_ago, three_days_ago))
    
    # cleanup_disk.py 自体の __file__ を mock する
    mock_file_path = str(mock_worktree / "cleanup_disk.py")
    
    # os.path.abspath(__file__) が mock_file_path を返すように mock する
    with patch("os.path.abspath", return_value=mock_file_path):
        # 実際に main を実行
        # old_session_dir は削除されるが、parent_uuid のフォルダは動的に保護されて残るはず
        cleanup_main(brain_dir=str(mock_brain_dir), active_ids=set(), keep_days=1)
        
    # 検証： 動的に保護された parent_uuid は存在する
    assert mock_parent_dir.exists()
    # old_session_dir は削除されている
    assert not old_session_dir.exists()

def test_disk_cleanup_no_side_effect_on_import():
    # インポートされただけでは実際のクリーンアップ処理（ファイルの exists, glob, rmtree など）が呼ばれないことを検証
    # （run_cleanup を明示的に呼んだときのみ実行される）
    with patch('pathlib.Path.exists') as mock_exists, \
         patch('pathlib.Path.glob') as mock_glob, \
         patch('shutil.rmtree') as mock_rmtree, \
         patch('builtins.print') as mock_print:
         
        sys.modules.pop('backend.scratch.disk_cleanup', None)
        sys.modules.pop('scratch.disk_cleanup', None)
        
        import backend.scratch.disk_cleanup
        
        mock_exists.assert_not_called()
        mock_glob.assert_not_called()
        mock_rmtree.assert_not_called()
        mock_print.assert_not_called()

