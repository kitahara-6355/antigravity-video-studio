# -*- coding: utf-8 -*-
"""
debug_mapping.py — サムネイル画像生成および品質検証モジュール
StageBoundAgent や自動リトライ、結果保存、DBマイグレーションと連携して動作する。
"""
import os
import json
import logging
import uuid
from pathlib import Path
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

def generate_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail"
) -> Path:
    """
    Pillowを使用して、指定された解像度とテキストでサムネイル画像をアトミックに生成する。
    """
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # アトミック書き込み (Atomic Write)
    # 一時ファイルに保存後、完全に書き込めたらリネームする
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path, "PNG")
        
        # 正常に保存されたらアトミックにリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
        
    return output_path

def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること（許容誤差 0.01 以内）
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していないこと（verify, loadでチェック）
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # verify() による簡易構造チェック
    try:
        with Image.open(file_path) as img:
            img.verify()
    except Exception as e:
        raise ValueError(f"Image structural verification failed: {e}")
        
    # load() を強制してピクセルデータのロードおよび破損チェック
    try:
        with Image.open(file_path) as img:
            img.load()  # 完全なロード
            width, height = img.size
    except Exception as e:
        raise ValueError(f"Image pixel data load failed (possibly corrupted): {e}")
        
    # 解像度制限チェック
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    # アスペクト比チェック (16:9 = 1.777...)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_thumbnail_task(self, task_id: str) -> str:
    """
    StageBoundAgent などの process_func として登録して動作するタスクハンドラ。
    呼び出し元インスタンス (self) の属性から出力ディレクトリ、解像度、テキストを動的に取得する。
    """
    output_dir = Path(getattr(self, "output_dir", None) or "backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    width = getattr(self, "width", 1280)
    height = getattr(self, "height", 720)
    text = getattr(self, "text", "Thumbnail")
    
    # 画像の生成
    generate_thumbnail(output_path, width=width, height=height, text=text)
    
    # 品質の検証
    result_info = validate_thumbnail(output_path)
    
    # 検証結果をJSON形式で返却（StageBoundAgentの結果保存用）
    return json.dumps(result_info)
