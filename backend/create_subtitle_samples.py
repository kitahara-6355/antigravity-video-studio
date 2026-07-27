"""
Create Subtitle Sample Image
字幕サンプル画像を生成 (soul_feedback.py への一元化と最適化ラッパー)
"""

from services.soul_feedback import (
    create_subtitle_sample,
    create_integrated_sample,
    SubtitleThumbnailVerifier,
    resolve_subtitle_thumbnail_task,
)

def generate_and_print_samples() -> None:
    """字幕サンプル画像と統合サンプル画像を生成し、結果を標準出力に表示する。"""
    subtitle_sample = create_subtitle_sample()
    integrated_sample = create_integrated_sample()
    
    print(f"\n✅ Subtitle sample: {subtitle_sample}")
    print(f"✅ Integrated sample: {integrated_sample}")


if __name__ == "__main__":
    generate_and_print_samples()
