import os
from moviepy import TextClip

os.environ["IMAGEMAGICK_BINARY"] = r"C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"

try:
    print("Creating TextClip...")
    t = TextClip(text="テスト表示", font_size=50, color='white', font=r'C:\Windows\Fonts\msgothic.ttc')
    print("Saving to file...")
    t.save_frame("test_clip.png")
    print("Success!")
except Exception as e:
    print(f"Failed: {e}")
