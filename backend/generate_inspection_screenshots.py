"""
スクリーンショット検品ツール — 全カットポイント + 全字幕切り替えのスクリーンショットを生成

使用方法:
  python generate_inspection_screenshots.py <preview_video> <output_dir>
"""
import subprocess
import json
import os
import sys
import glob
import math
from pathlib import Path


def get_video_duration(video_path):
    """FFprobeで動画の尺を取得"""
    if not video_path:
        print("⚠️ 動画ファイルパスが空です。")
        return 0.0

    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
        )
    except FileNotFoundError:
        print("⚠️ ffprobe コマンドが見つかりません。FFmpeg/FFprobe がインストールされているか確認してください。")
        return 0.0
    except PermissionError:
        print("⚠️ ffprobe コマンドの実行権限がありません。")
        return 0.0
    except subprocess.TimeoutExpired:
        print("⚠️ ffprobe の実行がタイムアウト（30秒）しました。")
        return 0.0
    except (subprocess.SubprocessError, OSError, ValueError, TypeError) as e:
        print(f"⚠️ ffprobe 実行中にエラーが発生しました: {e}")
        return 0.0

    if r.returncode != 0:
        print(f"⚠️ ffprobe 失敗 (ステータスコード: {r.returncode}): {r.stderr}")
        return 0.0

    try:
        data = json.loads(r.stdout)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"⚠️ ffprobe の出力JSONパース失敗: {e}")
        return 0.0

    if not isinstance(data, dict) or "format" not in data or not isinstance(data["format"], dict):
        print("⚠️ ffprobe 出力のフォーマットが不正です")
        return 0.0

    duration_val = data["format"].get("duration")
    if duration_val is None:
        print("⚠️ duration 情報が見つかりません")
        return 0.0

    try:
        val = float(duration_val)
        if not math.isfinite(val):
            print(f"⚠️ duration が有限の数値ではありません ({val})")
            return 0.0
        if val < 0.0:
            print(f"⚠️ duration が負の値です ({val})")
            return 0.0
        return val
    except (ValueError, TypeError) as e:
        print(f"⚠️ duration の数値変換に失敗しました ({duration_val}): {e}")
        return 0.0


def extract_frame(video_path, timestamp, output_path):
    """指定タイムスタンプのフレームを抽出"""
    if not isinstance(video_path, (str, Path)) or not isinstance(output_path, (str, Path)):
        print("⚠️ 無効な動画ファイルパスまたは出力ファイルパスが指定されました。")
        return False

    try:
        ts_val = float(timestamp)
    except (ValueError, TypeError) as e:
        print(f"⚠️ 無効なタイムスタンプまたは引数が指定されました: {e}")
        return False

    if ts_val < 0.0:
        print(f"⚠️ 無効なタイムスタンプが指定されました: {timestamp}")
        return False

    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(ts_val), "-i", video_path,
             "-frames:v", "1", "-q:v", "2", output_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30
        )
        if r.returncode != 0:
            print(f"⚠️ ffmpeg 失敗 (ステータスコード: {r.returncode}): {r.stderr}")
            return False
    except FileNotFoundError:
        print("⚠️ ffmpeg コマンドが見つかりません。FFmpeg がインストールされているか確認してください。")
        return False
    except PermissionError:
        print("⚠️ ffmpeg コマンドの実行権限がありません。")
        return False
    except subprocess.TimeoutExpired:
        print("⚠️ ffmpeg の実行がタイムアウト（30秒）しました。")
        return False
    except (subprocess.SubprocessError, OSError, ValueError, TypeError) as e:
        print(f"⚠️ ffmpeg 実行中にエラーが発生しました: {e}")
        return False

    try:
        return Path(output_path).exists()
    except (OSError, TypeError, ValueError) as e:
        print(f"⚠️ 出力ファイルの存在確認に失敗しました ({output_path}): {e}")
        return False


def resolve_paths(args=None):
    """動画ファイルパスと出力ディレクトリパスを決定する"""
    if args is None:
        args = sys.argv
    elif not isinstance(args, (list, tuple)):
        raise TypeError("❌ args はリストまたはタプルである必要があります")
        
    if len(args) >= 2:
        video_path = args[1]
        if not isinstance(video_path, str):
            raise TypeError("❌ 動画ファイルパスは文字列である必要があります")
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"❌ 指定された動画ファイルが見つかりません: {video_path}")
        if os.path.isdir(video_path):
            raise ValueError(f"❌ 指定されたパスはファイルではなくディレクトリです: {video_path}")
            
        if len(args) >= 3:
            output_dir = args[2]
            if not isinstance(output_dir, str):
                raise TypeError("❌ 出力ディレクトリパスは文字列である必要があります")
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            output_dir = os.path.join(base_dir, "artifacts", "inspection_screenshots")
    else:
        # 最新のプレビュー動画を自動検出
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        preview_dir = os.path.join(base_dir, "vault-outputs", "preview")
        previews = sorted(glob.glob(os.path.join(preview_dir, "preview_*.mp4")))
        if not previews:
            raise FileNotFoundError("❌ プレビュー動画が見つかりません")

        video_path = previews[-1]
        output_dir = os.path.join(base_dir, "artifacts", "inspection_screenshots")
    return video_path, output_dir


def generate_timestamps(duration, interval=10):
    """等間隔のタイムスタンプを作成する"""
    try:
        duration_val = float(duration)
    except (ValueError, TypeError) as e:
        raise TypeError(f"❌ duration は数値である必要があります: {e}")
        
    try:
        interval_val = float(interval)
    except (ValueError, TypeError) as e:
        raise TypeError(f"❌ interval は数値である必要があります: {e}")

    if not math.isfinite(duration_val) or not math.isfinite(interval_val):
        raise ValueError("❌ duration または interval が有限の数値ではありません")

    if duration_val <= 0:
        raise ValueError("❌ duration は 0 より大きい値である必要があります")

    if interval_val <= 0:
        raise ValueError("❌ interval は 0 より大きい値である必要があります")

    # 最大生成枚数制限
    try:
        estimated_frames = math.ceil(duration_val / interval_val)
    except OverflowError as e:
        raise ValueError(f"❌ 生成予定のスクリーンショット枚数の計算中にオーバーフローが発生しました: {e}")

    if estimated_frames > 1000:
        raise ValueError(f"❌ 生成予定のスクリーンショット枚数 ({estimated_frames}) が最大フレーム数制限 (1000) を超えています")

    timestamps = []
    current_time = 0.0
    while current_time < duration_val:
        timestamps.append(("interval", current_time))
        current_time += interval_val
    return timestamps


def save_index(output_dir, video_path, duration, generated_frames):
    """インデックスJSONファイルを保存する"""
    if generated_frames is None:
        print("⚠️ 生成されたフレームのリストが無効です。")
        return False

    if not isinstance(output_dir, (str, Path)) or not isinstance(video_path, (str, Path)):
        print("⚠️ 無効な出力ディレクトリまたは動画ファイルパスが指定されました。")
        return False

    try:
        index_path = os.path.join(output_dir, "index.json")
        index = {
            "video": os.path.basename(video_path) if video_path else "",
            "duration": duration,
            "total_frames": len(generated_frames),
            "frames": [
                {"timestamp": timestamp, "path": os.path.basename(file_path)}
                for timestamp, file_path in generated_frames
            ]
        }
        serialized_data = json.dumps(index, ensure_ascii=False, indent=2)
    except (TypeError, ValueError, AttributeError) as e:
        print(f"⚠️ インデックスデータのJSONシリアライズに失敗しました: {e}")
        return False

    try:
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(serialized_data)
    except (OSError, TypeError, ValueError) as e:
        print(f"⚠️ インデックスJSONの書き込みに失敗しました ({index_path}): {e}")
        return False
    return True


def main():
    try:
        video_path, output_dir = resolve_paths()
    except (FileNotFoundError, ValueError, TypeError) as e:
        print(e)
        sys.exit(1)
    except OSError as e:
        print(f"❌ パス解決中にエラーが発生しました: {e}")
        sys.exit(1)
    
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"❌ 出力ディレクトリの作成に失敗しました: {e}")
        sys.exit(1)

    print(f"📹 プレビュー動画: {os.path.basename(video_path)}")
    duration = get_video_duration(video_path)
    try:
        duration_val = float(duration)
        if duration_val <= 0.0:
            print("❌ 動画の尺が取得できないか、無効な動画ファイルです。")
            sys.exit(1)
    except (ValueError, TypeError) as e:
        print(f"❌ 動画の尺が不正な値です: {e}")
        sys.exit(1)
        
    print(f"⏱️ 動画尺: {duration_val:.1f}s ({duration_val/60:.1f}min)")

    try:
        timestamps = generate_timestamps(duration_val, interval=10)
    except (ValueError, TypeError) as e:
        print(e)
        sys.exit(1)
    print(f"📸 合計 {len(timestamps)} フレームを抽出中...")

    generated = []
    for i, (kind, timestamp) in enumerate(timestamps):
        file_name = f"frame_{i:04d}_{kind}_{timestamp:.1f}s.jpg"
        file_path = os.path.join(output_dir, file_name)
        if extract_frame(video_path, timestamp, file_path):
            generated.append((timestamp, file_path))
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(timestamps)} 完了...")

    if not generated:
        print("❌ スクリーンショットが1枚も生成されませんでした。")
        sys.exit(1)

    print(f"✅ {len(generated)}/{len(timestamps)} フレーム生成完了")
    print(f"📂 出力先: {output_dir}")

    if not save_index(output_dir, video_path, duration, generated):
        print("❌ インデックスJSONの保存に失敗しました。")
        sys.exit(1)

    return output_dir, generated


if __name__ == "__main__":
    main()
