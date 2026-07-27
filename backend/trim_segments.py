"""
trim_segments.py - 動画の指定セグメントのカット・結合編集モジュール

このモジュールは、指定された入力動画から複数のセグメントを切り出し、
それらを再結合して最終的な編集動画を作成します。
"""
import subprocess
from pathlib import Path

def cut_segments(base_dir=None):
    """指定されたディレクトリ内の動画ファイルをカットおよび結合します。

    Args:
        base_dir (str, optional): 動画ファイルが存在するベースディレクトリ。
                                  Noneの場合はデフォルトのデスクトップパスを使用します。

    Returns:
        str: 成功した場合は出力された動画ファイルの絶対パス。
        bool: 入力ファイルが存在しない場合などは False。
        None: 結合処理等でエラーが発生した場合は None。
    """
    try:
        if base_dir is None:
            base = Path(r"C:\Users\PC_User\Desktop\script\video-automation")
        else:
            base = Path(base_dir)
            
        input_video = base / "soul_narrative_FIXED.mp4"
        output_video = base / "soul_narrative_FINAL_EDITED.mp4"
        
        # 1. 入力ファイルの存在確認 (早期エラーリターン)
        if not input_video.exists():
            print(f"❌ Input video not found: {input_video}")
            return False
            
        print("="*70)
        print("Scene Trimming: Cutting 2 Segments")
        print("="*70)
        
        # concat demuxer用の一時ファイル作成
        temp_dir = base / "backend" / "temp" / "trimmed_segments"
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"❌ Failed to create temp directory {temp_dir}: {e}")
            return False
            
        segments = [
            {"start": 0, "end": 1848, "name": "segment1.mp4"},  # 0:00 - 30:48
            {"start": 1851, "end": 2258, "name": "segment2.mp4"},  # 30:51 - 37:38
            {"start": 2267, "end": None, "name": "segment3.mp4"}  # 37:47 - 終了
        ]
        
        segment_files = []
        
        for seg in segments:
            output_path = temp_dir / seg["name"]
            
            if seg["end"] is None:
                # 最後のセグメント（終了まで）
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(seg["start"]),
                    "-i", str(input_video),
                    "-c", "copy",
                    str(output_path)
                ]
            else:
                # 中間セグメント
                duration = seg["end"] - seg["start"]
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(seg["start"]),
                    "-t", str(duration),
                    "-i", str(input_video),
                    "-c", "copy",
                    str(output_path)
                ]
            
            print(f"\nExtracting {seg['name']}...")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore')
            except (subprocess.SubprocessError, OSError) as e:
                print(f"❌ Subprocess error while extracting {seg['name']}: {e}")
                return False
            
            if result.returncode == 0 and output_path.exists():
                size_mb = output_path.stat().st_size / 1024 / 1024
                print(f"✅ {seg['name']}: {size_mb:.1f} MB")
                segment_files.append(output_path)
            else:
                print(f"❌ Failed: {seg['name']}")
                print(result.stderr[-500:] if result.stderr else "")
                return False
        
        # セグメントを結合
        concat_list = temp_dir / "concat.txt"
        try:
            with open(concat_list, "w", encoding="utf-8") as f:
                for seg_file in segment_files:
                    path = str(seg_file.absolute()).replace("\\", "/")
                    f.write(f"file '{path}'\n")
        except OSError as e:
            print(f"❌ Failed to write concat list {concat_list}: {e}")
            return False
        
        print("\n" + "="*70)
        print("Concatenating trimmed segments...")
        print("="*70)
        
        cmd_concat = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_video)
        ]
        
        try:
            result = subprocess.run(cmd_concat, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        except (subprocess.SubprocessError, OSError) as e:
            print(f"❌ Subprocess error during concatenation: {e}")
            return None
        
        if result.returncode == 0 and output_video.exists():
            size_mb = output_video.stat().st_size / 1024 / 1024
            print(f"\n🎉 FINAL EDITED VIDEO COMPLETE!")
            print(f"   File: {output_video}")
            print(f"   Size: {size_mb:.1f} MB")
            
            # 長さ確認
            check_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output_video)
            ]
            try:
                duration_result = subprocess.run(check_cmd, capture_output=True, text=True)
                if duration_result.returncode == 0:
                    duration_sec = float(duration_result.stdout.strip())
                    duration_min = int(duration_sec // 60)
                    duration_sec_remaining = int(duration_sec % 60)
                    print(f"   Duration: {duration_min}:{duration_sec_remaining:02d}")
            except ValueError as e:
                print(f"⚠️ Failed to parse video duration as float: {e}")
            except (subprocess.SubprocessError, OSError) as e:
                print(f"⚠️ Failed to check video duration: {e}")
            
            return str(output_video)
        else:
            print("\n❌ Concatenation failed")
            print(result.stderr[-500:] if result.stderr else "")
            return None
            
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as e:
        print(f"🚨 Unexpected exception in cut_segments: {e}")
        try:
            import sys
            from agents.memory.technical_debt import TechnicalDebtStore
            store = TechnicalDebtStore()
            line_num = sys._getframe().f_lineno - 5  # Exception発生行付近
            store.register_debt(
                category="MINOR_INFRA",
                file_path="trim_segments.py",
                line_number=line_num,
                pattern="except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as e:",
                cause_pattern="DP-01",
                fix_pattern="具体的な例外ハンドリングへの分解",
                registered_by="bug_hunter_T-batch_377c87",
                notes=f"Unexpected exception caught: {str(e)}",
                tags=["batch_377c87_residual"]
            )
        except (IOError, ValueError, AttributeError, TypeError, KeyError) as tdr_err:
            print(f"⚠️ Failed to register technical debt: {tdr_err}")
        return None

if __name__ == "__main__":
    import time
    start = time.time()
    result = cut_segments()
    elapsed = time.time() - start
    
    print(f"\nTotal time: {elapsed:.1f} seconds")
    if result:
        print(f"✅ SUCCESS: {result}")
    else:
        print("❌ FAILED")
