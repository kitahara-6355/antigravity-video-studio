import sys
from unittest.mock import MagicMock, patch
import pytest

def test_collaborative_evolution_success(capsys):
    """正常系: contextにCOLLABORATIVE PROFILEが含まれ、XPが正常にインクリメントされる場合の検証"""
    mock_bm = MagicMock()
    mock_bm.get_context_block.return_value = "## COLLABORATIVE PROFILE\nDummy profile content"
    
    user_model_before = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 100}}},
            "owner": {"ranks": {"biz_rank": {"xp": 50}}}
        }
    }
    user_model_after = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 120}}},
            "owner": {"ranks": {"biz_rank": {"xp": 80}}}
        }
    }
    
    mock_bm.user_model = user_model_before
    
    def mock_update_user_rank(rank_type, amount):
        if rank_type == "tech_rank":
            assert amount == 20
        elif rank_type == "biz_rank":
            assert amount == 30
        mock_bm.user_model = user_model_after

    mock_bm.update_user_rank.side_effect = mock_update_user_rank

    with patch('branding_manager.branding_manager', mock_bm):
        if 'verify_collaborative_model' in sys.modules:
            sys.modules.pop('verify_collaborative_model', None)
        import verify_collaborative_model
        
        result = verify_collaborative_model.verify_collaborative_evolution()

    assert result is True
    captured = capsys.readouterr()
    assert "Context includes Collaborative Profile header." in captured.out
    assert "Admin Tech XP: 120 (was 100)" in captured.out
    assert "Owner Biz XP: 80 (was 50)" in captured.out
    assert "SUCCESS: Collaborative XP Tracking is working flawlessly!" in captured.out


def test_collaborative_evolution_missing_profile_header(capsys):
    """正常系（準正常系）: contextにCOLLABORATIVE PROFILEが含まれないがXP更新は成功する場合の検証"""
    mock_bm = MagicMock()
    mock_bm.get_context_block.return_value = "## DUMMY BLOCK\nNo profile"
    
    user_model_before = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 100}}},
            "owner": {"ranks": {"biz_rank": {"xp": 50}}}
        }
    }
    user_model_after = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 120}}},
            "owner": {"ranks": {"biz_rank": {"xp": 80}}}
        }
    }
    mock_bm.user_model = user_model_before
    
    def mock_update_user_rank(rank_type, amount):
        mock_bm.user_model = user_model_after

    mock_bm.update_user_rank.side_effect = mock_update_user_rank

    with patch('branding_manager.branding_manager', mock_bm):
        if 'verify_collaborative_model' in sys.modules:
            sys.modules.pop('verify_collaborative_model', None)
        import verify_collaborative_model
        
        result = verify_collaborative_model.verify_collaborative_evolution()

    assert result is True
    captured = capsys.readouterr()
    assert "Context missing Collaborative Profile header." in captured.out
    assert "SUCCESS: Collaborative XP Tracking is working flawlessly!" in captured.out


def test_collaborative_evolution_xp_update_failure(capsys):
    """異常系: XPが正しくインクリメントされなかった（差分が期待値と異なる）場合の検証"""
    mock_bm = MagicMock()
    mock_bm.get_context_block.return_value = "## COLLABORATIVE PROFILE\nDummy profile content"
    
    user_model_before = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 100}}},
            "owner": {"ranks": {"biz_rank": {"xp": 50}}}
        }
    }
    user_model_after = {
        "profiles": {
            "admin": {"ranks": {"tech_rank": {"xp": 100}}},
            "owner": {"ranks": {"biz_rank": {"xp": 50}}}
        }
    }
    mock_bm.user_model = user_model_before
    
    mock_bm.update_user_rank.side_effect = lambda rank_type, amount: None

    with patch('branding_manager.branding_manager', mock_bm):
        if 'verify_collaborative_model' in sys.modules:
            sys.modules.pop('verify_collaborative_model', None)
        import verify_collaborative_model
        
        result = verify_collaborative_model.verify_collaborative_evolution()

    assert result is False
    captured = capsys.readouterr()
    assert "FAILURE: XP did not update correctly in nested profiles." in captured.out


def test_collaborative_thumbnail_generation_success(tmp_path):
    """Pillowで生成されたサムネイル画像が品質要件を満たしているかテスト"""
    import verify_collaborative_model
    from PIL import Image
    output_file = tmp_path / "collab_test.png"
    
    # 画像生成
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(output_file),
        width=1280,
        height=720,
        text="Test Success"
    )
    
    assert output_file.exists()
    
    # 品質検証
    result = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
    
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] < 4 * 1024 * 1024
    assert result["path"] == str(output_file)
    
    # Pillowで実際にロード可能か
    with Image.open(output_file) as img:
        img.verify()


def test_collaborative_thumbnail_quality_failures(tmp_path):
    """異常な画像に対して正しくエラーが返るかテスト"""
    import verify_collaborative_model
    from PIL import Image
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        verify_collaborative_model.validate_thumbnail_quality(tmp_path / "non_existent.png")
        
    # 2. 解像度不足
    low_res_file = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_file, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        verify_collaborative_model.validate_thumbnail_quality(low_res_file)
        
    # 3. アスペクト比不正
    bad_ratio_file = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_file, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        verify_collaborative_model.validate_thumbnail_quality(bad_ratio_file)
        
    # 4. ファイルサイズ制限
    valid_file = tmp_path / "valid.png"
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(valid_file), width=1280, height=720, text="Size test"
    )
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            verify_collaborative_model.validate_thumbnail_quality(valid_file)
            
    # 5. 画像破損（空ファイルなど）
    corrupted_file = tmp_path / "corrupted.png"
    with open(corrupted_file, "wb") as f:
        f.write(b"not an image file")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        verify_collaborative_model.validate_thumbnail_quality(corrupted_file)


def test_collaborative_thumbnail_stage_bound_agent_integration(tmp_path):
    """StageBoundAgentとの連携テスト（タスク登録、実行、結果DB保存、自動リトライ）"""
    import sqlite3
    import json
    import asyncio
    from pathlib import Path
    db_file = tmp_path / "collab_agent.db"
    
    from agents.stage_bound_agent import StageBoundAgent
    import verify_collaborative_model
    
    task_id = "collab_task_001"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    async def run_test():
        # タスク登録
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # エージェント開始
        await agent.start(verify_collaborative_model.resolve_collaborative_thumbnail_task)
        
        # 完了を待期
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # ファイルの存在と検証
        output_file = Path("backend/temp_thumbnails") / f"collaborative_model_{task_id}.png"
        assert output_file.exists()
        
        try:
            # 品質検証が通ることを確認
            result_info = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
            assert result_info["width"] == 1280
            assert result_info["height"] == 720
            
            # DBに結果が正しく書き込まれていることを確認
            conn = sqlite3.connect(str(db_file))
            try:
                cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                assert row is not None
                status, result_str, retry_count = row
                assert status == "COMPLETED"
                assert retry_count == 0
                
                db_result = json.loads(result_str)
                assert db_result["width"] == 1280
                assert db_result["height"] == 720
                assert "path" in db_result
            finally:
                conn.close()
        finally:
            if output_file.exists():
                output_file.unlink()
                
    asyncio.run(run_test())


def test_collaborative_thumbnail_retry_integration(tmp_path):
    """StageBoundAgentの自動リトライ連携テスト"""
    import sqlite3
    import asyncio
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "collab_retry.db"
    task_id = "collab_retry_task"
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 失敗を繰り返すダミータスク関数
    call_count = 0
    async def failing_task(tid):
        nonlocal call_count
        call_count += 1
        raise ValueError("Intentional Failure")
        
    async def run_test():
        # max_retries = 2 で登録 (計3回実行されるはず)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        await agent.start(failing_task)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "FAILED"
        assert call_count == 3  # 最初の1回 + リトライ2回 = 3回
        
        # DBにリトライ回数が保存されているか確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "FAILED"
            assert retry_count == 2
            assert "Intentional Failure" in error
        finally:
            conn.close()
            
    asyncio.run(run_test())

# ============================================================
# 新規追加された品質自動検証とStageBoundAgent/DBマイグレーション連携のテスト
# ============================================================

def test_collaborative_thumbnail_auto_resolution_and_aspect_ratio_correction(tmp_path):
    """品質基準自動検証: 解像度不足およびアスペクト比不整合の自動補正テスト"""
    import verify_collaborative_model
    from PIL import Image
    
    # 1. 1280x720未満、アスペクト比2:1 (非16:9) の場合
    output_file_1 = tmp_path / "correction_test_1.png"
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(output_file_1),
        width=1000,
        height=500,
        text="Auto Aspect Ratio Correction"
    )
    
    assert output_file_1.exists()
    result_1 = verify_collaborative_model.validate_thumbnail_quality(str(output_file_1))
    
    assert result_1["width"] >= 1280
    assert result_1["height"] >= 720
    assert abs(result_1["width"] / result_1["height"] - 16.0 / 9.0) <= 0.01
    
    # 2. 640x360 (1280x720未満、アスペクト比16:9) の場合
    output_file_2 = tmp_path / "correction_test_2.png"
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(output_file_2),
        width=640,
        height=360,
        text="Auto Resolution Scaling"
    )
    
    assert output_file_2.exists()
    result_2 = verify_collaborative_model.validate_thumbnail_quality(str(output_file_2))
    
    assert result_2["width"] == 1280
    assert result_2["height"] == 720


def test_collaborative_thumbnail_auto_compression_limit(tmp_path):
    """品質基準自動検証: ファイルサイズが4MB未満に自動圧縮されるテスト"""
    import verify_collaborative_model
    from PIL import Image
    import os
    
    output_file = tmp_path / "compression_test.png"
    
    original_save = Image.Image.save
    save_calls = []
    
    def mock_save(self_img, fp, format=None, **kwargs):
        save_calls.append(format)
        return original_save(self_img, fp, format=format, **kwargs)
        
    Image.Image.save = mock_save
    try:
        original_stat = os.stat
        def mock_stat(path, *args, **kwargs):
            stat_result = original_stat(path, *args, **kwargs)
            path_str = str(path)
            if "tmp" in path_str and len(save_calls) == 1:
                class MockStat:
                    def __init__(self, orig):
                        self.orig = orig
                        self.st_size = 5 * 1024 * 1024
                    def __getattr__(self, name):
                        return getattr(self.orig, name)
                return MockStat(stat_result)
            return stat_result
            
        with patch("os.stat", side_effect=mock_stat):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file),
                width=1920,
                height=1080,
                text="Mock Limit"
            )
    finally:
        Image.Image.save = original_save
            
    assert output_file.exists()
    assert "PNG" in save_calls
    assert "JPEG" in save_calls
    
    result = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
    assert result["size_bytes"] < 4 * 1024 * 1024


def test_collaborative_thumbnail_db_migration_integration(tmp_path):
    """DBマイグレーション連携自動検証: 古いスキーマのDBから必要なカラムが自動マイグレーションされるテスト"""
    import sqlite3
    from pathlib import Path
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "migration_test.db"
    
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("""
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                stage TEXT,
                status TEXT,
                error TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.commit()
    finally:
        conn.close()
        
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    conn = sqlite3.connect(str(db_file))
    try:
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns = [row[1] for row in cursor.fetchall()]
        
        assert "result" in columns
        assert "retry_count" in columns
        assert "max_retries" in columns
    finally:
        conn.close()


def test_generate_thumbnail_invalid_dimensions():
    """正常系/異常系: width/heightの不正な入力に対するエラーハンドリング"""
    import verify_collaborative_model
    # None や文字などの無効な型 (L22-23)
    with pytest.raises(ValueError, match="Width and height must be integers"):
        verify_collaborative_model.generate_collaborative_thumbnail(
            "dummy.png", width="invalid", height=720
        )
    with pytest.raises(ValueError, match="Width and height must be integers"):
        verify_collaborative_model.generate_collaborative_thumbnail(
            "dummy.png", width=1280, height=None
        )
    
    # 0 以下の数値 (L26)
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        verify_collaborative_model.generate_collaborative_thumbnail(
            "dummy.png", width=0, height=720
        )
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        verify_collaborative_model.generate_collaborative_thumbnail(
            "dummy.png", width=1280, height=-10
        )


def test_generate_thumbnail_aspect_ratio_corrections(tmp_path):
    """正常系: 解像度およびアスペクト比補正のエッジケース検証 (L35-36, L45)"""
    import verify_collaborative_model
    output_file = tmp_path / "aspect_correction.png"
    
    # width=640, height=480 (アスペクト比 4:3 < 16:9)
    # L35-36 と L45 の両方の補正ルートを通す
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(output_file), width=640, height=480
    )
    assert output_file.exists()
    result = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
    assert result["width"] == 1706
    assert result["height"] == 960


def test_generate_thumbnail_overwrite_existing(tmp_path):
    """正常系: 出力先ファイルが既に存在する場合の自動削除・上書き検証 (L89)"""
    import verify_collaborative_model
    output_file = tmp_path / "overwrite.png"
    with open(output_file, "w") as f:
        f.write("existing content")
        
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(output_file), width=1280, height=720
    )
    assert output_file.exists()
    result = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
    assert result["width"] == 1280


def test_generate_thumbnail_compression_failures(tmp_path):
    """異常系: 4MB制限の自動圧縮・サイズ縮小の最終圧縮失敗時のエラーハンドリング (L75-78)"""
    import verify_collaborative_model
    import os
    
    output_file = tmp_path / "fail_compress.png"
    
    # 全てのファイル保存操作でファイルサイズが4MB以上であるようにスタット結果をモック
    original_stat = os.stat
    def mock_stat(path, *args, **kwargs):
        path_str = str(path)
        if "tmp" in path_str:
            class MockStat:
                def __init__(self, orig):
                    self.orig = orig
                    self.st_size = 5 * 1024 * 1024  # 5MB
                def __getattr__(self, name):
                    return getattr(self.orig, name)
            return MockStat(original_stat(path, *args, **kwargs))
        return original_stat(path, *args, **kwargs)
        
    with patch("os.stat", side_effect=mock_stat):
        with pytest.raises(ValueError, match="Failed to compress thumbnail under 4MB limit."):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file), width=1280, height=720
            )


def test_generate_thumbnail_verification_corrupted(tmp_path):
    """異常系: 生成されたサムネイル画像の破損検知時のエラーハンドリング (L84-85)"""
    import verify_collaborative_model
    from PIL import Image
    output_file = tmp_path / "corrupted_verify.png"
    
    original_open = Image.open
    def mock_open(fp, *args, **kwargs):
        img = original_open(fp, *args, **kwargs)
        if "tmp" in str(fp):
            img.load = MagicMock(side_effect=OSError("Load failed intentionally"))
        return img
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Generated thumbnail image is corrupted"):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file), width=1280, height=720
            )


def test_generate_thumbnail_runtime_error_and_unlink_failure(tmp_path):
    """異常系: 汎用例外ハンドリング、RuntimeErrorへのラップ、および一時ファイル削除失敗時の例外スルー検証 (L91-99)"""
    import verify_collaborative_model
    from pathlib import Path
    from PIL import Image
    output_file = tmp_path / "runtime_err.png"
    
    # 1. 汎用的なTypeErrorがRuntimeErrorにラップされるか
    with patch("PIL.Image.new", side_effect=TypeError("Image creation type error")):
        with pytest.raises(RuntimeError, match="Failed to generate collaborative thumbnail atomically: Image creation type error"):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file), width=1280, height=720
            )
            
    # 2. 一時ファイル削除 (unlink) がOSErrorで失敗しても正常に例外伝播されるか (L95-96)
    # 一時ファイルを残した状態で検証時にValueErrorを発生させる
    original_open = Image.open
    def mock_open(fp, *args, **kwargs):
        img = original_open(fp, *args, **kwargs)
        if "tmp" in str(fp):
            img.load = MagicMock(side_effect=ValueError("Corrupted image during verification"))
        return img
        
    original_unlink = Path.unlink
    def mock_unlink(self, *args, **kwargs):
        if ".tmp" in self.name:
            raise OSError("Permission denied to unlink tmp file")
        return original_unlink(self, *args, **kwargs)
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with patch.object(Path, "unlink", mock_unlink):
            with pytest.raises(ValueError, match="Generated thumbnail image is corrupted"):
                verify_collaborative_model.generate_collaborative_thumbnail(
                    str(output_file), width=1280, height=720
                )



def test_validate_thumbnail_quality_load_failure(tmp_path):
    """異常系: validate_thumbnail_quality における画像データロード例外のハンドリング (L125-126)"""
    import verify_collaborative_model
    from PIL import Image
    
    valid_file = tmp_path / "valid_for_load_test.png"
    verify_collaborative_model.generate_collaborative_thumbnail(
        str(valid_file), width=1280, height=720
    )
    
    original_open = Image.open
    open_count = 0
    def mock_open(fp, *args, **kwargs):
        nonlocal open_count
        img = original_open(fp, *args, **kwargs)
        if str(fp) == str(valid_file):
            open_count += 1
            if open_count == 2:  # 2回目の open 呼び出し (load用)
                img.load = MagicMock(side_effect=OSError("Load failure in quality validation"))
        return img
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format \\(load\\)"):
            verify_collaborative_model.validate_thumbnail_quality(str(valid_file))



def test_generate_thumbnail_compression_fallback_success(tmp_path):
    """正常系: 画質調整forループで4MB未満に収まらず、1280x720への縮小で4MB未満に収まる場合の圧縮フォールバック成功検証 (L77->81)"""
    import verify_collaborative_model
    from PIL import Image
    import os
    from unittest.mock import patch
    
    output_file = tmp_path / "compress_fallback_success.png"
    
    original_save = Image.Image.save
    save_calls = []
    
    def mock_save(self_img, fp, format=None, **kwargs):
        save_calls.append(format)
        return original_save(self_img, fp, format=format, **kwargs)
        
    Image.Image.save = mock_save
    try:
        original_stat = os.stat
        def mock_stat(path, *args, **kwargs):
            stat_result = original_stat(path, *args, **kwargs)
            path_str = str(path)
            if "tmp" in path_str:
                # save_callsの長さで保存回数を特定
                # 1回目(PNG): 5MB
                # 2〜6回目(JPEG 95, 85, 70, 50, 30): 5MB
                # 7回目(JPEG 30 縮小): 3MB (4MB未満)
                if len(save_calls) <= 6:
                    class MockStatBig:
                        def __init__(self, orig):
                            self.orig = orig
                            self.st_size = 5 * 1024 * 1024
                        def __getattr__(self, name):
                            return getattr(self.orig, name)
                    return MockStatBig(stat_result)
                else:
                    class MockStatSmall:
                        def __init__(self, orig):
                            self.orig = orig
                            self.st_size = 3 * 1024 * 1024
                        def __getattr__(self, name):
                            return getattr(self.orig, name)
                    return MockStatSmall(stat_result)
            return stat_result
            
        with patch("os.stat", side_effect=mock_stat):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file),
                width=1920,
                height=1080,
                text="Fallback Success"
            )
    finally:
        Image.Image.save = original_save
            
    assert output_file.exists()
    # PNG(1回) + for内のJPEG(5回) + else内のJPEG(1回) = 7回保存されていること
    assert len(save_calls) == 7
    assert save_calls[0] == "PNG"
    assert all(fmt == "JPEG" for fmt in save_calls[1:])
    
    result = verify_collaborative_model.validate_thumbnail_quality(str(output_file))
    assert result["size_bytes"] < 4 * 1024 * 1024


def test_generate_thumbnail_syntax_error_handling(tmp_path):
    """異常系: _verify_image_not_corrupted で SyntaxError が発生した場合の検証"""
    import verify_collaborative_model
    from PIL import Image
    output_file = tmp_path / "syntax_err.png"
    
    # Image.open が SyntaxError をスローするようにモックする
    original_open = Image.open
    def mock_open(fp, *args, **kwargs):
        if "tmp" in str(fp):
            raise SyntaxError("Mock SyntaxError during verification")
        return original_open(fp, *args, **kwargs)
        
    with patch("PIL.Image.open", side_effect=mock_open):
        with pytest.raises(ValueError, match="Generated thumbnail image is corrupted: Mock SyntaxError"):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file), width=1280, height=720
            )


def test_generate_thumbnail_type_error_handling(tmp_path):
    """異常系: generate_collaborative_thumbnail で TypeError が発生した場合に RuntimeError にラップされるかの検証"""
    import verify_collaborative_model
    output_file = tmp_path / "type_err.png"
    
    # Image.new が TypeError を発生させるようにする
    with patch("PIL.Image.new", side_effect=TypeError("Mock TypeError for generation")):
        with pytest.raises(RuntimeError, match="Failed to generate collaborative thumbnail atomically: Mock TypeError"):
            verify_collaborative_model.generate_collaborative_thumbnail(
                str(output_file), width=1280, height=720
            )


@pytest.mark.asyncio
async def test_resolve_collaborative_thumbnail_task_cleanup_on_failure():
    """異常系: resolve_collaborative_thumbnail_task で品質検証が例外を投げた場合に一時ファイルが削除されるか検証"""
    import verify_collaborative_model
    from unittest.mock import patch
    from pathlib import Path
    
    task_id = "test_cleanup_fail"
    expected_path = Path("backend/temp_thumbnails") / f"collaborative_model_{task_id}.png"
    
    # 既存のファイルがないことを保証
    if expected_path.exists():
        expected_path.unlink()
        
    # validate_thumbnail_quality が ValueError を投げるようにモック
    with patch("verify_collaborative_model.validate_thumbnail_quality", side_effect=ValueError("Quality validation failed intentionally")):
        with pytest.raises(ValueError, match="Quality validation failed intentionally"):
            await verify_collaborative_model.resolve_collaborative_thumbnail_task(task_id)
            
    # 例外発生後にファイルが削除されていることを検証
    assert not expected_path.exists()
