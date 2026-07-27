import sys
import importlib
from unittest.mock import MagicMock, patch
import pytest

def test_verify_rank_success_status_change(capsys):
    """正常系: ランク更新が成功し、履歴がSTATUS_CHANGEの場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    # get_history(1)が期待するSTATUS_CHANGE形式のイベントを返すようにモック
    mock_hm.get_history.return_value = [{'type': 'STATUS_CHANGE', 'data': 'dummy'}]
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            # 既にインポートされている場合はキャッシュから削除して強制リロード
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    # メソッドが呼び出されたことを確認
    mock_bm.update_user_rank.assert_called_once_with("tech_rank", 5)
    mock_hm.get_history.assert_called_once_with(1)
    
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Rank updated successfully." in captured.out
    assert "History verification successful:" in captured.out

def test_verify_rank_success_empty_history(capsys):
    """正常系: ランク更新が成功し、履歴が空（またはSTATUS_CHANGE以外）の場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    # get_history(1)が空リストを返すようにモック
    mock_hm.get_history.return_value = []
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    mock_bm.update_user_rank.assert_called_once_with("tech_rank", 5)
    mock_hm.get_history.assert_called_once_with(1)
    
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Rank updated successfully." in captured.out
    assert "History verification FAILED/Empty." in captured.out

def test_verify_rank_failure(capsys):
    """異常系: ランク更新時に例外が発生した場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    # 例外を発生させる
    mock_bm.update_user_rank.side_effect = ValueError("Mocked rank update error")
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Error: Mocked rank update error" in captured.out

def test_verify_rank_success_other_history_type(capsys):
    """正常系: ランク更新が成功し、履歴のtypeがSTATUS_CHANGE以外の場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    mock_hm.get_history.return_value = [{'type': 'OTHER_TYPE', 'data': 'dummy'}]
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    mock_bm.update_user_rank.assert_called_once_with("tech_rank", 5)
    mock_hm.get_history.assert_called_once_with(1)
    
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Rank updated successfully." in captured.out
    assert "History verification FAILED/Empty." in captured.out

def test_verify_rank_success_history_none(capsys):
    """正常系: ランク更新が成功し、履歴がNoneの場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    mock_hm.get_history.return_value = None
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    mock_bm.update_user_rank.assert_called_once_with("tech_rank", 5)
    mock_hm.get_history.assert_called_once_with(1)
    
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Rank updated successfully." in captured.out
    assert "History verification FAILED/Empty." in captured.out

def test_verify_rank_history_exception(capsys):
    """異常系: 履歴取得時に例外が発生した場合の検証"""
    mock_bm = MagicMock()
    mock_hm = MagicMock()
    
    mock_hm.get_history.side_effect = ValueError("Mocked history error")
    
    with patch('branding_manager.branding_manager', mock_bm), \
         patch('branding.history_manager.history_manager', mock_hm):
        
        if 'verify_rank' in sys.modules:
            sys.modules.pop('verify_rank', None)
        
        import verify_rank
            
    captured = capsys.readouterr()
    assert "Testing BrandingManager..." in captured.out
    assert "Error: Mocked history error" in captured.out


# --- サムネイル画像処理・品質検証・StageBoundAgent連携テストの追加 ---
import shutil
import tempfile
import asyncio
from pathlib import Path
from PIL import Image
import json

# verify_rank をインポート
import verify_rank
from verify_rank import ThumbnailQualityVerifier, generate_thumbnail_file, resolve_thumbnail_task
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

def test_thumbnail_quality_verifier_valid(temp_dir):
    output_path = temp_dir / "valid.png"
    # 正常な1280x720 (16:9) の画像を生成
    generate_thumbnail_file(str(output_path), width=1280, height=720)
    
    # 検証
    result = ThumbnailQualityVerifier.validate(str(output_path))
    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["size_bytes"] > 0
    assert Path(result["path"]).exists()

def test_thumbnail_quality_verifier_invalid_resolution(temp_dir):
    output_path = temp_dir / "invalid_res.png"
    # 解像度不足 1000x500 (アスペクト比は2:1)
    generate_thumbnail_file(str(output_path), width=1000, height=500)
    
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        ThumbnailQualityVerifier.validate(str(output_path))

def test_thumbnail_quality_verifier_invalid_aspect(temp_dir):
    output_path = temp_dir / "invalid_aspect.png"
    # 1280x800 (アスペクト比 16:10 = 1.6)
    generate_thumbnail_file(str(output_path), width=1280, height=800)
    
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        ThumbnailQualityVerifier.validate(str(output_path))

def test_thumbnail_quality_verifier_file_size_exceeded(temp_dir):
    output_path = temp_dir / "large.png"
    # 4MB以上のダミーファイル（サイズチェックで落ちることを確認）
    with open(output_path, "wb") as f:
        f.seek(4 * 1024 * 1024 + 10)
        f.write(b"\0")
        
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        ThumbnailQualityVerifier.validate(str(output_path))

def test_thumbnail_quality_verifier_corrupted(temp_dir):
    output_path = temp_dir / "corrupted.png"
    # 破損画像（空ファイル）
    with open(output_path, "wb") as f:
        f.write(b"not an image data")
        
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        ThumbnailQualityVerifier.validate(str(output_path))

def test_thumbnail_quality_verifier_not_found():
    with pytest.raises(FileNotFoundError, match="Thumbnail file not found"):
        ThumbnailQualityVerifier.validate("non_existent_file.png")

@pytest.mark.asyncio
async def test_stage_bound_agent_integration(temp_dir):
    db_path = ":memory:" # メモリ上のDB
    agent = StageBoundAgent(
        stage_name="thumbnail_stage",
        db_path=db_path,
        poll_interval=0.01
    )
    
    # DBマイグレーション（テーブルは__init__の中で作成されている）
    # tasks テーブルが正しくマイグレーションされていることを確認
    conn = agent._get_conn()
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
    # キャッシュされたコネクションを直接クローズしない（agent._close_connを使うか何もしない）
    agent._close_conn(conn)

    task_id = "test_task_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=1)

    # Agent の処理関数として resolve_thumbnail_task をラップして登録
    async def process_func(tid):
        return await resolve_thumbnail_task(tid, db_path=db_path, output_dir=str(temp_dir))

    await agent.start(process_func)
    
    # 処理が完了するまで待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.02)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # DBから結果を確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    result_str = row[0]
    error_str = row[1]
    retry_count = row[2]
    agent._close_conn(conn)
    
    assert error_str is None
    assert retry_count == 0
    assert result_str is not None
    
    result_info = json.loads(result_str)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    
    await agent.stop()

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_on_failure(temp_dir):
    db_path = ":memory:"
    agent = StageBoundAgent(
        stage_name="thumbnail_stage",
        db_path=db_path,
        poll_interval=0.01
    )

    task_id = "test_task_fail_002"
    # max_retries = 2 とする（合計3回実行）
    await agent.register_task(task_id, initial_status="READY", max_retries=2)

    # 常に失敗する処理関数
    call_count = 0
    async def process_func(tid):
        nonlocal call_count
        call_count += 1
        raise ValueError("Simulated processing error")

    await agent.start(process_func)

    # 失敗してリトライが尽きるまで待つ
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.02)

    status = await agent.get_task_status(task_id)
    assert status == "FAILED"

    # DBからリトライ回数を確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    retry_count = row[0]
    error_str = row[1]
    agent._close_conn(conn)

    assert retry_count == 2
    assert "Simulated processing error" in error_str
    assert call_count == 3 # 初回1回 + リトライ2回

    await agent.stop()

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_value_error_handling(temp_dir):
    import sys
    import verify_rank
    # verify_rank モジュール内の ThumbnailQualityVerifier と emit_critical をパッチする
    with patch.object(verify_rank.ThumbnailQualityVerifier, 'validate') as mock_validate, \
         patch.object(verify_rank, 'emit_critical') as mock_emit:
        mock_validate.side_effect = ValueError("Mocked invalid quality")
        
        with pytest.raises(ValueError, match="Mocked invalid quality"):
            await verify_rank.resolve_thumbnail_task("test_task_error", output_dir=str(temp_dir))
            
        mock_emit.assert_called_once_with("thumbnail", "Thumbnail task failed for task test_task_error: Mocked invalid quality")

