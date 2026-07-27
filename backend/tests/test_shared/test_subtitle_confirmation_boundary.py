# -*- coding: utf-8 -*-
import sys
from pathlib import Path
from PIL import Image
import pytest

# backend ディレクトリをパスに追加
backend_dir = Path("C:/Users/PC_User/.gemini/antigravity/brain/0c00ce38-f479-4e0c-853e-22aa566d725e/.system_generated/worktrees/subagent-test-weaver-Agent-self-a8bfca75/backend")
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import subtitle_confirmation

def test_validate_thumbnail_quality_aspect_ratio_boundary(tmp_path):
    """正常系/異常系: アスペクト比の許容差 0.01 の境界値検証"""
    # 1. 許容差内の境界値 (1290 x 725 -> 比率 1.7793, 誤差 0.0015 <= 0.01, 解像度 >= 1280x720)
    boundary_ok_file = tmp_path / "boundary_ok.png"
    img_ok = Image.new("RGB", (1290, 725), color="blue")
    img_ok.save(boundary_ok_file, format="PNG")
    res = subtitle_confirmation.validate_thumbnail_quality(boundary_ok_file)
    assert res["width"] == 1290
    
    # 2. 許容差外の境界値 (1300 x 720 -> 比率 1.8056, 誤差 0.0278 > 0.01, 解像度 >= 1280x720)
    boundary_ng_file = tmp_path / "boundary_ng.png"
    img_ng = Image.new("RGB", (1300, 720), color="blue")
    img_ng.save(boundary_ng_file, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        subtitle_confirmation.validate_thumbnail_quality(boundary_ng_file)

def test_thumbnail_generation_size_boundary(tmp_path):
    """異常系/正常系: 画像解像度の境界値検証"""
    # 1. width=0
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
            tmp_path / "size_zero_w.png", width=0, height=720
        )
    
    # 2. height=0
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
            tmp_path / "size_zero_h.png", width=1280, height=0
        )
        
    # 3. Noneなどの無効な引数型
    with pytest.raises(ValueError, match="Width and height must be integers"):
        subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
            tmp_path / "size_none.png", width=None, height=720
        )

    # 4. 浮動小数点数（int変換されて成功するケース）
    float_file = tmp_path / "size_float.png"
    res_path = subtitle_confirmation.generate_subtitle_confirmation_thumbnail(
        float_file, width=1280.0, height=720.0
    )
    assert res_path.exists()
    with Image.open(res_path) as img:
        assert img.size == (1280, 720)
