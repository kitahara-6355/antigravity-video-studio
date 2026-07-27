import subprocess
import os

def test_filter_process():
    # パス設定
    input_video = r"C:\Users\PC_User\Desktop\script\video-automation\vault-assets\raw_videos\本番RAW01 対談_山田\シーン01_前編.mp4"
    output_video = r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\final_build\scene01_processed_filter_test.mp4"
    
    # フィルター設定
    # すでに生成されている一時ファイルを利用する
    srt_rel = "backend/temp/final_build/scene01_formatted.srt"
    
    base_vf = f"crop=1152:720:26:0,scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p,subtitles='{srt_rel}'"
    
    # テロップオーバーレイを追加
    vf = f"{base_vf}[v0]; "
    telops = [(0, 0, 600), (1, 600, 1200), (2, 1200, 1800)]
    for j, (idx, start, end) in enumerate(telops):
        movie_path = f"backend/temp/final_build/brand_telop_{idx}.png"
        movie_filter = f"movie='{movie_path}'[t{idx}]"
        is_last = (j == len(telops) - 1)
        out_label = "" if is_last else f"[v{j+1}]"
        overlay_filter = f"[v{j}][t{idx}]overlay=15:15:enable='between(t,{start},{end})'{out_label}"
        vf += f"{movie_filter}; {overlay_filter}"
        if not is_last:
            vf += "; "

    cmd = [
        "ffmpeg", "-y", "-i", input_video,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-b:v", "12M",
        "-c:a", "aac", "-b:a", "192k",
        output_video
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    
    # 標準エラー出力をリアルタイムで見るために subprocess.Popen を使用
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='ignore')
    
    # ログ出力しながら待機
    last_lines = []
    while True:
        line = process.stdout.readline()
        if not line and process.poll() is not None:
            break
        if line:
            # frame= などの進捗行は多すぎるので一部だけ表示
            if "frame=" in line:
                if "speed=" in line:
                    print(line.strip(), end="\r")
            else:
                print(line.strip())
                last_lines.append(line.strip())
                if len(last_lines) > 20:
                    last_lines.pop(0)
                    
    rc = process.poll()
    print(f"\nReturn code: {rc}")
    if rc != 0:
        print("Last lines of output:")
        for l in last_lines:
            print(l)

if __name__ == "__main__":
    test_filter_process()
