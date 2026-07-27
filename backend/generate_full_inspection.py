"""
全カットポイント + 全字幕切り替えのスクリーンショットを生成する完全検品ツール

Q2: B対応 — 等間隔ではなく、実際のカット境界と字幕切り替えポイントでフレーム抽出
"""
import subprocess
import json
import os
import sys
import glob
import hashlib
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def calculate_sha256(filepath):
    sha256 = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            while True:
                data = f.read(65536)
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    except OSError as e:
        print(f"⚠️ ハッシュ計算エラー: {e}")
        return "error"


def get_git_commit():
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        pass
    return "unknown"


def update_previews_metadata(metadata_path, version, video_file, video_hash, git_commit, duration, segment_count, generated_frames):
    import datetime
    
    metadata = {"current_version": version, "history": []}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
            
    history_entry = {
        "version": version,
        "video_file": os.path.basename(video_file),
        "video_hash": video_hash,
        "timestamp": datetime.datetime.now().isoformat(),
        "git_commit": git_commit,
        "duration": duration,
        "segment_count": segment_count,
        "frames": [
            {
                "index": i,
                "timestamp": ts,
                "image_path": os.path.relpath(p, start=str(PROJECT_ROOT)).replace("\\", "/")
            }
            for i, (ts, p) in enumerate(generated_frames)
        ]
    }
    
    # 既存の同一バージョンがあれば上書き、なければ追記
    history = metadata.setdefault("history", [])
    for idx, entry in enumerate(history):
        if entry.get("version") == version:
            history[idx] = history_entry
            break
    else:
        history.append(history_entry)
        
    metadata["current_version"] = version
    
    try:
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"⚠️ プレビューメタデータ保存失敗: {e}", file=sys.stderr)


def get_video_duration(video_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        if isinstance(r.returncode, int) and r.returncode != 0:
            print(f"⚠️ ffprobeがエラーを返しました (code: {r.returncode})", file=sys.stderr)
            return 0.0
        if not r.stdout.strip():
            print("⚠️ ffprobeの出力が空です", file=sys.stderr)
            return 0.0
        data = json.loads(r.stdout)
        duration_str = data.get("format", {}).get("duration", "0")
        return float(duration_str)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"⚠️ ffprobe実行エラー: {e}", file=sys.stderr)
        return 0.0
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"⚠️ ffprobe出力解析エラー: {e}", file=sys.stderr)
        return 0.0


def extract_frame(video_path, timestamp, output_path):
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(timestamp), "-i", video_path,
             "-frames:v", "1", "-q:v", "2", output_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30
        )
        if isinstance(r.returncode, int) and r.returncode != 0:
            print(f"⚠️ ffmpegフレーム抽出失敗 (code: {r.returncode}, timestamp: {timestamp})", file=sys.stderr)
            return False
    except (subprocess.SubprocessError, OSError) as e:
        print(f"⚠️ ffmpeg実行エラー (timestamp: {timestamp}): {e}", file=sys.stderr)
        return False
    return Path(output_path).exists()


def load_segments_from_cache():
    """最新のWhisperキャッシュからセグメントを読む"""
    cache_dir = PROJECT_ROOT / "vault-outputs" / "merged"
    try:
        if not cache_dir.exists():
            print(f"⚠️ キャッシュディレクトリが存在しません: {cache_dir}", file=sys.stderr)
            return []
        candidates = sorted(cache_dir.glob("_whisper_*.jsonl"), key=lambda p: p.stat().st_mtime)
    except OSError as e:
        print(f"⚠️ キャッシュファイル検索エラー: {e}", file=sys.stderr)
        return []

    if not candidates:
        return []
    
    latest = candidates[-1]
    print(f"📄 セグメントソース: {latest.name}")
    segments = []
    try:
        with open(latest, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        segments.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"⚠️ キャッシュJSON解析エラー (行 {line_idx}): {e}", file=sys.stderr)
    except OSError as e:
        print(f"⚠️ キャッシュファイル読み込みエラー: {e}", file=sys.stderr)
        return []
    return segments
def main():
    parser = argparse.ArgumentParser(description="全カットポイント + 全字幕切り替えのスクリーンショットを生成する完全検品ツール")
    parser.add_argument("--output-dir", type=str, default=None, help="出力先ディレクトリ")
    parser.add_argument("--video-path", type=str, default=None, help="対象動画ファイルのパス")
    parser.add_argument("--version", type=str, default="latest", help="管理用バージョン名 (例: v1.0.0)")
    args = parser.parse_args()

    # 対象動画の決定
    video_path = args.video_path
    if not video_path:
        preview_dir = PROJECT_ROOT / "vault-outputs" / "preview"
        previews = sorted(glob.glob(os.path.join(str(preview_dir), "preview_*.mp4")))
        if not previews:
            # ルートの soul_narrative_full_v1.mp4 も候補に入れる
            fallback = PROJECT_ROOT / "soul_narrative_full_v1.mp4"
            if os.path.exists(str(fallback)):
                video_path = str(fallback)
            else:
                print("❌ プレビュー動画が見つかりません")
                sys.exit(1)
        else:
            video_path = previews[-1]

    # 出力先の決定
    output_dir = args.output_dir
    if not output_dir:
        # デフォルトはプロジェクトルート配下の backend/graded_previews/latest
        output_dir = str(PROJECT_ROOT / "backend" / "graded_previews" / "latest")
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"📹 プレビュー動画: {os.path.basename(video_path)}")
    duration = get_video_duration(video_path)
    if duration <= 0:
        print("❌ 動画の長さが取得できないか、0秒以下です。処理を中断します。", file=sys.stderr)
        sys.exit(1)
    print(f"⏱️ 動画尺: {duration:.1f}s ({duration/60:.1f}min)")

    # セグメントからタイムスタンプを収集
    segments = load_segments_from_cache()
    
    timestamps = set()
    
    # 1. 字幕切り替えポイント（各セグメントのstart + 0.5s）でスマートサンプリング
    # API上限に収めるため、前回のサンプリングから最低 15秒の間隔を空ける
    last_added_t = -999.0
    MIN_SAMPLE_INTERVAL = 15.0  # 15秒間隔
    for seg in segments:
        t = seg.get("start", 0)
        end = seg.get("end", t + 1.0)
        if t - last_added_t >= MIN_SAMPLE_INTERVAL:
            # 短い字幕の場合に表示終了を超えないよう、中間のタイミングを計算する
            duration_seg = end - t
            delay = min(0.5, duration_seg / 2.0)
            check_t = t + delay
            if 0 <= check_t <= duration:
                timestamps.add(round(check_t, 1))
                last_added_t = check_t
    
    # 2. 等間隔補完（字幕がない時間帯のカバー用に 60秒ごと）
    t = 0
    while t < duration:
        # すでに近いタイムスタンプ（±5秒以内）がある場合はスキップして重複を避ける
        if not any(abs(existing - t) < 5.0 for existing in timestamps):
            timestamps.add(round(t, 1))
        t += 60
    
    # 3. ソート
    sorted_ts = sorted(timestamps)
    print(f"📸 合計 {len(sorted_ts)} フレームを抽出中（字幕切替{len(segments)}件 + 60秒間隔）...")

    generated = []
    for i, ts in enumerate(sorted_ts):
        fname = f"frame_{i:04d}_{ts:.1f}s.jpg"
        fpath = os.path.join(output_dir, fname)
        if extract_frame(video_path, ts, fpath):
            generated.append((ts, fpath))
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(sorted_ts)} 完了...")

    print(f"✅ {len(generated)}/{len(sorted_ts)} フレーム生成完了")
    print(f"📂 出力先: {output_dir}")

    # インデックスJSON
    index = {
        "video": os.path.basename(video_path),
        "duration": duration,
        "total_frames": len(generated),
        "segment_count": len(segments),
        "frames": [
            {"timestamp": ts, "path": os.path.basename(p)}
            for ts, p in generated
        ]
    }
    try:
        with open(os.path.join(output_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"⚠️ インデックスファイル保存失敗: {e}", file=sys.stderr)

    # 4. previews_metadata.json の更新
    metadata_path = PROJECT_ROOT / "backend" / "graded_previews" / "previews_metadata.json"
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    
    print("💾 プレビューメタデータを計算・更新中...")
    video_hash = calculate_sha256(video_path)
    git_commit = get_git_commit()
    
    update_previews_metadata(
        metadata_path=str(metadata_path),
        version=args.version,
        video_file=video_path,
        video_hash=video_hash,
        git_commit=git_commit,
        duration=duration,
        segment_count=len(segments),
        generated_frames=generated
    )
    print("✅ メタデータの更新に成功しました。")


if __name__ == "__main__":
    main()
