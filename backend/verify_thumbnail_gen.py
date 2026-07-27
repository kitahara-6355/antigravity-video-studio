import requests
import json
import base64
import os
from pathlib import Path
from PIL import Image, UnidentifiedImageError
from combined_overlay import CombinedOverlay

def verify_image_quality(file_path: str) -> dict:
    """
    サムネイル画像の品質基準を厳密に検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillowでロード可能）こと
    - フォーマットがサポートされていること（PNG, JPEG, WEBP）
    - カラーモードが適切であること（RGB, RGBA）
    """
    if file_path is None:
        raise TypeError("file_path cannot be None")
    if not isinstance(file_path, str):
        raise TypeError("file_path must be a string")
    if not file_path.strip():
        raise ValueError("file_path cannot be empty")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"検証対象のサムネイルファイルが見つかりません: {file_path}")
        
    size_bytes = path.stat().st_size
    max_size = 4 * 1024 * 1024  # 4MB
    if size_bytes >= max_size:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
    if size_bytes == 0:
        raise ValueError("File size is 0 bytes, the thumbnail image is empty.")

    # 1. Pillowによるファイル検証 (verify)
    try:
        with Image.open(path) as img:
            img.verify()
    except (SyntaxError, OSError, ValueError, TypeError, AttributeError, UnidentifiedImageError) as e:
        raise ValueError(f"Image is corrupted or invalid format (verify failed): {e}")

    # 2. 完全なピクセルデータのロードによる破損検知とサイズ取得
    try:
        with Image.open(path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
            img_format = img.format
            img_mode = img.mode
            img.tobytes()  # データの整合性を最終チェック
    except (SyntaxError, OSError, ValueError, TypeError, AttributeError, UnidentifiedImageError) as e:
        raise ValueError(f"Image is corrupted or invalid format (load failed): {e}")

    # 3. フォーマットの検証 (PNG, JPEG, WEBPのみ許可)
    supported_formats = {"PNG", "JPEG", "WEBP"}
    if img_format not in supported_formats:
        raise ValueError(f"Unsupported image format: {img_format}. Supported: {supported_formats}")

    # 4. カラーモードの検証 (RGB, RGBAのみ許可)
    supported_modes = {"RGB", "RGBA"}
    if img_mode not in supported_modes:
        raise ValueError(f"Unsupported image mode: {img_mode}. Supported: {supported_modes}")

    # 5. 解像度の検証 (1280x720 以上)
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")

    # 6. アスペクト比の検証 (16:9)
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")

    return {
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "format": img_format,
        "mode": img_mode
    }

def test_thumbnail_generation():
    url = "http://localhost:8000/api/thumbnail/generate"
    payload = {
        "video_title": "書道家・北原美麗の挑戦：伝統と革新の融合",
        "video_description": "日本デザイン書道作家協会理事長の久喜田博信先生を迎え、書道を通じた人生観とデザイン書道の魅力を語り合います。",
        "num_variants": 2
    }
    
    print(f"🚀 テスト開始: {url}")
    print(f"📝 動画タイトル: {payload['video_title']}")
    
    overlay = CombinedOverlay()
    
    try:
        try:
            response = requests.post(url, json=payload, timeout=60)
            response.raise_for_status()
        except requests.exceptions.Timeout as te:
            print(f"❌ API接続タイムアウト: {te}")
            raise
        except requests.exceptions.ConnectionError as ce:
            print(f"❌ API接続エラー (サーバーが起動していない可能性があります): {ce}")
            raise
        except requests.exceptions.HTTPError as he:
            print(f"❌ HTTPエラーレスポンス受信: {he}")
            if he.response is not None:
                print(f"📄 エラー詳細: {he.response.text}")
            raise
            
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as je:
            print(f"❌ レスポンスのJSONパースに失敗しました: {je}")
            raise
            
        print(f"✅ ステータス: {data.get('status')}")
        print(f"🖼️ 生成数: {data.get('count')}")
        
        thumbnails = data.get('thumbnails', [])
        for i, thumb in enumerate(thumbnails):
            print(f"\\n--- 候補 {i+1} ---")
            print(f"📌 コンセプト: {thumb.get('concept_name')}")
            print(f"📝 説明: {thumb.get('description')}")
            print(f"📊 推定CTR: {thumb.get('ctr_score')}%")
            
            try:
                img_data = base64.b64decode(thumb['image_base64'])
            except (KeyError, ValueError, TypeError) as de:
                print(f"❌ Base64画像データのデコードに失敗しました: {de}")
                raise ValueError(f"Failed to decode base64 image data: {de}")
                
            filename = f"test_thumb_{i}.png"
            
            try:
                with open(filename, "wb") as f:
                    f.write(img_data)
                print(f"📁 保存完了: {os.path.abspath(filename)}")
                
                # 品質検証の実行
                try:
                    # ローカルでの二重検証
                    local_info = verify_image_quality(filename)
                    print(f"✅ ローカル品質検証パス: {local_info}")
                    
                    # 統合検証器による検証
                    result_info = overlay.validate_thumbnail(filename)
                    print(f"✅ 統合品質検証パス: {result_info}")
                except Exception as ve:
                    print(f"❌ 品質検証失敗: {ve}")
                    raise ValueError(f"Thumbnail validation failed: {ve}")
            finally:
                if os.path.exists(filename):
                    try:
                        os.remove(filename)
                        print(f"🧹 クリーンアップ: 一時ファイルを削除しました: {filename}")
                    except OSError as oe:
                        print(f"⚠️ 一時ファイル削除失敗: {oe}")
            
        print("\\n✨ 統合テスト完了: すべての項目で正常なレスポンスを確認しました。")
        
    except Exception as e:
        print(f"❌ テスト失敗: {e}")
        raise

if __name__ == '__main__':
    test_thumbnail_generation()
