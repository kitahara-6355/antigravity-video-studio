"""
テスト動画切り出しスクリプト — E2Eテスト基盤（Q3回答: 既存RAWから切り出し）

既存のRAW動画から5種類のテスト用短尺動画を自動生成する:
  1. test_30sec.mp4    — 最小ケース（30秒）
  2. test_5min.mp4     — 標準ケース（5分）
  3. test_silence.mp4  — 無音区間含有（30秒静音+30秒音声）
  4. test_mono.mp4      — モノラル音声（互換性テスト）
  5. test_lowres.mp4   — 低解像度（480p — 境界値テスト）

要件:
  - FFmpeg が PATH に存在すること
  - vault-assets/raw/ に任意のRAW動画が1本以上存在すること

出力先: vault-assets/test_videos/
"""

import sys
import subprocess
import shutil
from pathlib import Path

# パス設定
BACKEND_DIR = Path(__file__).parent
VAULT_RAW = BACKEND_DIR / "vault-assets" / "raw"
TEST_VIDEOS_DIR = BACKEND_DIR / "vault-assets" / "test_videos"


def find_source_video() -> Path:
    """RAW動画を1本見つける"""
    try:
        if VAULT_RAW.exists() and VAULT_RAW.is_dir():
            for ext in ["*.mp4", "*.mkv", "*.avi", "*.mov", "*.webm"]:
                files = list(VAULT_RAW.glob(ext))
                for f in files:
                    try:
                        if f.is_file() and f.stat().st_size > 0:
                            return f
                    except OSError:
                        continue

        # RAWフォルダに動画がなければ、backendディレクトリ以下を検索
        if BACKEND_DIR.exists() and BACKEND_DIR.is_dir():
            for ext in ["*.mp4", "*.mkv"]:
                files = list(BACKEND_DIR.glob(f"**/{ext}"))
                for f in files:
                    if "test_videos" not in str(f) and "node_modules" not in str(f):
                        try:
                            if f.is_file() and f.stat().st_size > 0:
                                return f
                        except OSError:
                            continue
    except OSError as e:
        print(f"  ⚠ ディレクトリ探索中にI/Oエラーが発生しました: {e}")

    return None


def run_ffmpeg(args: list, desc: str):
    """FFmpegコマンドを実行"""
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning"] + args
    print(f"  🔧 {desc}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ❌ Error: {result.stderr[:200]}")
            return False
        return True
    except FileNotFoundError:
        print("  ❌ Error: FFmpeg が PATH に見つかりません。FFmpeg をインストールしてください。")
        return False
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  ❌ Error: FFmpegコマンドの実行中にエラーが発生しました: {e}")
        return False


def generate_synthetic_source():
    """テスト用の合成動画を生成（RAW動画が無い場合のフォールバック）"""
    try:
        TEST_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"  ❌ Error: 出力ディレクトリの作成に失敗しました: {e}")
        return None

    source = TEST_VIDEOS_DIR / "_synthetic_source.mp4"

    # 10分のカラーバー + テスト音声を生成
    args = [
        "-f", "lavfi", "-i",
        "color=c=blue:size=1920x1080:rate=30:duration=600",
        "-f", "lavfi", "-i",
        "sine=frequency=440:duration=600",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(source),
    ]

    if run_ffmpeg(args, "合成テスト動画を生成"):
        return source
    return None


def create_test_videos(source: Path):
    """5種類のテスト動画を生成"""
    if not source or not source.exists():
        print(f"  ❌ Error: ソースファイルが存在しません: {source}")
        return {}

    try:
        TEST_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"  ❌ Error: 出力ディレクトリの作成に失敗しました: {e}")
        return {}

    results = {}

    # 1. 30秒テスト
    out = TEST_VIDEOS_DIR / "test_30sec.mp4"
    ok = run_ffmpeg([
        "-ss", "0", "-i", str(source), "-t", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ], "test_30sec.mp4 (最小ケース)")
    results["test_30sec"] = ok

    # 2. 5分テスト
    out = TEST_VIDEOS_DIR / "test_5min.mp4"
    ok = run_ffmpeg([
        "-ss", "0", "-i", str(source), "-t", "300",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ], "test_5min.mp4 (標準ケース)")
    results["test_5min"] = ok

    # 3. 無音区間含有（60秒: 前半30秒無音 + 後半30秒音声）
    out = TEST_VIDEOS_DIR / "test_silence.mp4"
    ok = run_ffmpeg([
        "-ss", "0", "-i", str(source), "-t", "60",
        "-af", "volume=enable='lt(t,30)':volume=0",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ], "test_silence.mp4 (無音区間含有)")
    results["test_silence"] = ok

    # 4. モノラル音声
    out = TEST_VIDEOS_DIR / "test_mono.mp4"
    ok = run_ffmpeg([
        "-ss", "0", "-i", str(source), "-t", "30",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-ac", "1", "-c:a", "aac", "-b:a", "64k",
        str(out),
    ], "test_mono.mp4 (モノラル)")
    results["test_mono"] = ok

    # 5. 低解像度（480p）
    out = TEST_VIDEOS_DIR / "test_lowres.mp4"
    ok = run_ffmpeg([
        "-ss", "0", "-i", str(source), "-t", "30",
        "-vf", "scale=854:480",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ], "test_lowres.mp4 (480p)")
    results["test_lowres"] = ok

    return results


def main():
    print("=" * 60)
    print("📹 E2Eテスト動画切り出しスクリプト")
    print("=" * 60)

    # ソース動画を探す
    source = find_source_video()
    if source:
        try:
            print(f"\n✅ ソース動画: {source}")
            print(f"   サイズ: {source.stat().st_size / 1024 / 1024:.1f} MB")
        except OSError as e:
            print(f"  ⚠ ソース動画のサイズ取得に失敗しました: {e}")
    else:
        print("\n⚠ RAW動画が見つかりません。合成テスト動画を生成します...")
        source = generate_synthetic_source()
        if not source:
            print("❌ 合成動画の生成に失敗しました。FFmpegを確認してください。")
            sys.exit(1)

    print(f"\n📁 出力先: {TEST_VIDEOS_DIR}")
    print("-" * 60)

    results = create_test_videos(source)

    print("-" * 60)
    print("\n📊 結果サマリー:")
    for name, ok in results.items():
        status = "✅" if ok else "❌"
        path = TEST_VIDEOS_DIR / f"{name}.mp4"
        size = "N/A"
        try:
            if path.exists():
                size = f"{path.stat().st_size / 1024 / 1024:.1f} MB"
        except OSError:
            pass
        print(f"  {status} {name:20s} — {size}")

    success = sum(1 for ok in results.values() if ok)
    total = len(results)
    print(f"\n{'🎉' if success == total else '⚠'} {success}/{total} テスト動画を生成しました")

    # 合成ソースの一時ファイルを削除
    synthetic = TEST_VIDEOS_DIR / "_synthetic_source.mp4"
    try:
        if synthetic.exists() and source == synthetic:
            pass  # テスト動画としても使用中なので残す
    except OSError:
        pass

    return 0 if (total > 0 and success == total) else 1


if __name__ == "__main__":
    sys.exit(main())
