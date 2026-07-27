import sys
import os
import json
import base64
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

# backend ディレクトリを sys.path に追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend import disk_manager

def test_get_drive_root_edge_cases():
    # 相対パスでの動作確認
    root_rel = disk_manager.get_drive_root(Path("."))
    assert isinstance(root_rel, str)
    assert len(root_rel) > 0

    # 不正な型のパス（例外が発生することを確認）
    with pytest.raises(AttributeError):
        disk_manager.get_drive_root(12345)  # type: ignore

def test_calc_total_input_size_bytes_edge_cases():
    # 空リスト
    assert disk_manager._calc_total_input_size_bytes([]) == 0

    # 全て存在しないパス
    assert disk_manager._calc_total_input_size_bytes(["non_existent_file_123.mp4", Path("another_missing.mp4")]) == 0

    # 文字列パスとPathオブジェクトの混在
    p1 = Path("temp_p1_str.mp4")
    path_class = "pathlib.WindowsPath" if sys.platform == "win32" else "pathlib.PosixPath"
    with patch(f"{path_class}.exists", return_value=True), \
         patch(f"{path_class}.stat") as mock_stat:
        mock_stat_val = MagicMock()
        mock_stat_val.st_size = 500
        mock_stat.return_value = mock_stat_val
        
        # 文字列とPathの混在
        total = disk_manager._calc_total_input_size_bytes(["temp_p1_str.mp4", p1])
        assert total == 1000

def test_estimate_needed_gb_edge_cases():
    # 空リスト
    assert disk_manager.estimate_needed_gb([]) == 0.0

    # multiplier が 0 や負の数の場合
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=1024**3):
        assert disk_manager.estimate_needed_gb(["dummy.mp4"], multiplier=0.0) == 0.0
        assert disk_manager.estimate_needed_gb(["dummy.mp4"], multiplier=-1.0) == -1.0

def test_calc_timeout_edge_cases():
    # 空リスト
    assert disk_manager.calc_timeout([]) == 300  # 最低値の300

    # base_sec_per_gb が 0 や負の数の場合
    with patch("backend.disk_manager._calc_total_input_size_bytes", return_value=10 * 1024**3):
        # 0秒になるが最低値の300秒
        assert disk_manager.calc_timeout(["dummy.mp4"], base_sec_per_gb=0) == 300
        assert disk_manager.calc_timeout(["dummy.mp4"], base_sec_per_gb=-100) == 300

def test_ensure_disk_space_edge_cases():
    # min_free_gb が 0 または負の数の場合
    with patch("backend.disk_manager.get_free_gb", return_value=5.0), \
         patch("backend.disk_manager.estimate_needed_gb", return_value=1.0):
        # needed_gb = max(-5.0, 1.0) = 1.0GB. free_gb = 5.0GB. 5.0 >= 1.0 なので True
        assert disk_manager.ensure_disk_space(["dummy.mp4"], min_free_gb=-5.0) is True

def test_verify_thumbnail_quality_edge_cases():
    # None入力
    assert disk_manager.verify_thumbnail_quality(None) is False  # type: ignore

    # 空バイト
    assert disk_manager.verify_thumbnail_quality(b"") is False

    # 空文字列
    assert disk_manager.verify_thumbnail_quality("") is False

    # base64デコード可能だが画像ではない不正データ
    # 例えば、"YWJj" は "abc" にデコードされるが、画像ではない
    assert disk_manager.verify_thumbnail_quality("YWJj") is False

def create_dummy_image_bytes(size=(1280, 720), format="JPEG"):
    img = Image.new("RGB", size, color="blue")
    out = BytesIO()
    img.save(out, format=format)
    return out.getvalue()

@pytest.mark.asyncio
async def test_process_thumbnail_task_edge_cases():
    # task_id が空や None の場合でも正常に動作するか確認
    valid_bytes = create_dummy_image_bytes(size=(1280, 720))
    valid_b64 = base64.b64encode(valid_bytes).decode("utf-8")
    
    class MockGenerator:
        async def generate(self, prompt):
            return [{"id": "t1", "image_base64": valid_b64}]
            
    res_json = await disk_manager.process_thumbnail_task("", thumbnail_generator=MockGenerator())
    res = json.loads(res_json)
    assert res["status"] == "verified"
