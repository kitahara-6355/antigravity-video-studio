"""
SmartCut Engine — Phase D: FFmpeg + GPU 化

字幕セグメントの sourceStart/sourceEnd に基づき RAW動画をカット＆結合し、
字幕を焼き込んだ最終動画を生成する。

Phase D 変更:
  - MoviePy (CPU) → FFmpeg + NVENC (GPU) に完全移行
  - video_editor_engine.FFmpegEditor を利用
"""

import json
import os
import sys
import logging
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

# Ensure src is in path to import workflow_utils
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, "..", "src")
if src_dir not in sys.path:
    sys.path.append(src_dir)


def _get_logo_path() -> str | None:
    """ロゴファイルのパスを取得（FIX-6A: ロゴ重畳復元）"""
    # テンプレート設定からロゴパスを取得
    try:
        from template_config import template_config
        if template_config.is_active:
            logo = template_config.get_branding_config().get("logo_path")
            if logo and Path(logo).exists():
                return str(logo)
    except (ImportError, AttributeError, TypeError) as e:
        logger.debug(f"テンプレートロゴ取得スキップ: {e}")

    # デフォルトロゴパス
    default_logo = Path(__file__).parent / "branding" / "logos" / "brand_logo.png"
    if default_logo.exists():
        return str(default_logo)
    return None


def _burn_subtitles_ffmpeg(video_path: str, segments: list, output_path: str, ffmpeg_editor) -> bool:
    """FFmpeg の subtitles + overlay フィルターで字幕とロゴを焼き込む

    フィルターチェーン:
      1. ロゴオーバーレイ（存在時のみ）
      2. 字幕焼き込み（SRT → subtitles フィルター）

    3段階フォールバック:
      1. GPU hwaccel + フィルターチェーン
      2. CPU入力 + GPU出力（hwaccel/subtitles衝突回避）
      3. 字幕・ロゴなしでコピー（最終手段）
    """
    import tempfile
    import subprocess as _sp
    
    # BUG-PV02: 入力動画のdurationを取得（SRTによる引き延ばし防止）
    video_duration = None
    try:
        import json as _json
        probe_r = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
            capture_output=True, text=True, encoding="utf-8", timeout=30
        )
        probe_data = _json.loads(probe_r.stdout)
        video_duration = float(probe_data.get("format", {}).get("duration", 0))
        logger.info(f"入力動画duration: {video_duration:.1f}s ({video_duration/60:.1f}min)")
    except (FileNotFoundError, _sp.SubprocessError, _json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"入力動画duration取得失敗: {e}")
    
    # SRT ファイルを一時生成
    # 相づちだけの字幕（「はい。」）は出さない。音声とカットはそのまま（2026-10-06 ユーザー指摘）
    try:
        from subtitle_engine.text_formatter import is_standalone_omittable, _omit_words
        standalone = _omit_words("omit_standalone_words")
    except ImportError:
        is_standalone_omittable, standalone = None, []
    srt_lines = []
    hidden = 0
    for i, s in enumerate(segments, 1):
        start = s.get("start", 0)
        end = s.get("end", 0)
        text = s.get("text", "").strip()
        if not text:
            continue
        if standalone and is_standalone_omittable(text, standalone):
            hidden += 1
            continue
        
        def _fmt_srt(sec):
            h = int(sec // 3600)
            m = int((sec % 3600) // 60)
            s_val = int(sec % 60)
            ms = int((sec % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s_val:02d},{ms:03d}"
        
        srt_lines.append(f"{i}")
        srt_lines.append(f"{_fmt_srt(start)} --> {_fmt_srt(end)}")
        srt_lines.append(text)
        srt_lines.append("")
    
    # BUG-PV02: SRT末尾のタイムスタンプをログ出力
    if srt_lines:
        max_end = max((s.get("end", 0) for s in segments), default=0)
        logger.info(f"SRT生成: {len([l for l in srt_lines if l.strip() and '-->' in l])}エントリ, max(end)={max_end:.1f}s, 相づちで非表示={hidden}件")
        if video_duration and max_end > video_duration + 5:
            logger.warning(f"⚠️ SRT max(end)={max_end:.1f}s > 動画尺{video_duration:.1f}s — 動画膨張リスク!")
    
    if not srt_lines:
        # 字幕なし: そのままコピー
        import shutil
        shutil.copy(video_path, output_path)
        return True
    
    srt_content = "\n".join(srt_lines)
    
    # 一時SRTファイル
    temp_srt = Path(output_path).parent / "_temp_subtitles.srt"
    try:
        temp_srt.write_text(srt_content, encoding="utf-8")
        
        # FFmpeg で字幕焼き込み（Windows パスのエスケープ対応）
        srt_path_escaped = str(temp_srt).replace("\\", "/").replace(":", "\\:")
        
        encode_args = ffmpeg_editor._get_encode_args("balanced")
        
        # テンプレート基準の字幕スタイルを適用（ハードコード廃止）
        try:
            from template_config import template_config
            subtitle_style = template_config.get_subtitle_style()
        except (ImportError, AttributeError):
            # A-1: NHK準拠字幕スタイル（フォールバック）
            # FontSize=16: 720pで適正サイズ（画面高の約2.2%）
            # MarginV=10: 画面最下部に配置
            # Alignment=2: 下部中央揃え
            # BorderStyle=4: 半透明背景帯（NHKテロップ風）
            # BackColour=&H80000000: 50%透明度の黒背景
            subtitle_style = "FontSize=16,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BackColour=&H80000000,Outline=1,BorderStyle=4,FontName=Yu Gothic UI,MarginV=10,Alignment=2"
        
        # ━━━ FIX-6A: ロゴオーバーレイ統合 ━━━
        logo_path = _get_logo_path()
        logo_input_args = []
        
        if logo_path:
            # ロゴ高さ（テンプレートから取得 or デフォルト45px）
            logo_height = 45
            try:
                from template_config import template_config as _tc
                if _tc.is_active:
                    logo_height = _tc.get_branding_config().get("logo_height", 45)
            except (ImportError, AttributeError, TypeError) as e:
                logger.debug(f"テンプレートロゴ高さ取得スキップ: {e}")

            logo_input_args = ["-i", logo_path]
            # フィルターチェーン: ロゴリサイズ → オーバーレイ → 字幕
            vf_arg = (
                f"[1:v]scale=-1:{logo_height}[logo];"
                f"[0:v][logo]overlay=10:10:format=auto[with_logo];"
                f"[with_logo]subtitles='{srt_path_escaped}':force_style='{subtitle_style}'"
            )
            filter_flag = "-filter_complex"
            logger.info(f"🏷️ ロゴ重畳有効: {Path(logo_path).name} (h={logo_height}px)")
        else:
            vf_arg = f"subtitles='{srt_path_escaped}':force_style='{subtitle_style}'"
            filter_flag = "-vf"
            logger.info("🏷️ ロゴなし — 字幕のみ焼き込み")
        
        # BUG-PV02: -t オプションで出力尺を入力動画尺に制限
        duration_limit = ["-t", str(video_duration)] if video_duration else []

        # --- フォールバック1: GPU hwaccel + フィルターチェーン ---
        # C-04修正: ロゴ付き(filter_complex)時はhwaccelスキップ
        if logo_path:
            cmd1 = [
                "-i", video_path,
            ] + logo_input_args + [
                filter_flag, vf_arg,
            ] + encode_args + duration_limit + [
                "-y", output_path
            ]
        else:
            hwaccel_args = ffmpeg_editor._get_hwaccel_input_args()
            cmd1 = hwaccel_args + [
                "-i", video_path,
            ] + [
                filter_flag, vf_arg,
            ] + encode_args + duration_limit + [
                "-y", output_path
            ]
        
        success, output = ffmpeg_editor.run_command(cmd1, timeout=1800)
        
        if success and Path(output_path).exists() and Path(output_path).stat().st_size > 1024:
            logger.info("✅ 字幕+ロゴ焼き込み成功 (GPU hwaccel)")
            return True
        
        # --- フォールバック2: CPU入力 + GPU出力 ---
        logger.warning("⚠️ GPU hwaccel + フィルター失敗。CPU入力 + GPU出力にフォールバック...")
        cmd2 = [
            "-i", video_path,
        ] + logo_input_args + [
            filter_flag, vf_arg,
        ] + encode_args + duration_limit + [
            "-y", output_path
        ]
        
        success, output = ffmpeg_editor.run_command(cmd2, timeout=1800)
        
        if success and Path(output_path).exists() and Path(output_path).stat().st_size > 1024:
            logger.info("✅ 字幕+ロゴ焼き込み成功 (CPU入力 + GPU出力)")
            return True
        
        # --- フォールバック3: 字幕・ロゴなしでコピー ---
        # C-07修正: 成功偽装防止 — 字幕なしであることを明示的に記録
        logger.warning("⚠️ 字幕焼き込み完全失敗。コピーフォールバック（字幕なし）")
        import shutil
        shutil.copy(video_path, output_path)
        
        # 品質ゲートが検出できるようフラグファイルを残す
        flag_path = Path(output_path).parent / "_subtitle_burn_failed.flag"
        try:
            flag_path.write_text("subtitle burn-in failed, fallback to copy", encoding="utf-8")
        except (PermissionError, OSError) as e:
            logger.debug(f"フラグファイル書込スキップ: {e}")
        
        # C-07修正: 字幕なしであることをフラグ+戻り値で明示
        return "fallback_no_subtitle"
    finally:
        if temp_srt.exists():
            temp_srt.unlink()



CUT_SUBTITLE_BUFFER = 0.5  # A-3: カット直後の字幕バッファ（秒）


def _display_span(seg: dict) -> tuple[float, float]:
    """字幕の行を**表示する**時刻（元の動画の時間軸）。

    校閲の整形は1つの発話を数行に分け、各行の start/end を発話の中で按分する。
    sourceStart/sourceEnd は発話全体の区間のまま（切る区間を決めるため）。
    以前は表示にも sourceStart/sourceEnd を使っていて、**同じ発話の全行が同時に
    出て下から逆順に積み上がっていた**（2026-10-05 raw 4本の実走）。
    行の start/end が発話の区間に収まっていればそれを使う。
    """
    src_start = float(seg.get("sourceStart", seg.get("start", 0)))
    src_end = float(seg.get("sourceEnd", seg.get("end", 0)))
    start = seg.get("start")
    end = seg.get("end")
    if start is not None and end is not None:
        start, end = float(start), float(end)
        if src_start - 0.01 <= start < end <= src_end + 0.5:
            return start, end
    return src_start, src_end


def _cut_kept_ranges_exact(ffmpeg, input_path, ranges, out_path) -> bool:
    """残す区間（素材の秒）だけを、1回のエンコードで時間ぴったりに抜き出す。

    select / aselect で区間内のフレームだけを通し、時刻を詰め直す。出力の長さは
    区間の合計とほぼ一致し（1区間あたり ±1 フレーム・±10ms・偏りなし）、字幕の時刻
    （`retime_segments`）とずれが積み上がらない。
    """
    if not ranges or not hasattr(ffmpeg, "run_command"):
        return False
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in ranges)
    graph = (f"[0:v]select='{expr}',setpts=N/FRAME_RATE/TB[v];"
             f"[0:a]asetnsamples=n=480:p=0,aselect='{expr}',asetpts=N/SR/TB[a]")
    script = Path(out_path).with_suffix(".filter.txt")
    try:
        script.write_text(graph, encoding="utf-8")
        try:
            enc = [a for a in ffmpeg._get_encode_args() if a not in ("-c:a", "aac")]
        except (AttributeError, TypeError):
            enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p"]
        args = ["-y", "-i", str(input_path), "-filter_complex_script", str(script),
                "-map", "[v]", "-map", "[a]", *enc, "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(out_path)]
        ok, _ = ffmpeg.run_command(args, timeout=7200)
        return bool(ok) and Path(out_path).exists() and Path(out_path).stat().st_size > 1024
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"区間の一括抽出に失敗: {e}")
        return False
    finally:
        try:
            script.unlink()
        except OSError:
            pass


def subtitle_sidecar_path(video_path) -> Path:
    """出力動画の時間軸の字幕（JSON）の置き場所。"""
    p = Path(video_path)
    return p.with_name(p.stem + ".subtitles.json")


def write_subtitle_sidecar(video_path, segments, ranges=None) -> None:
    """出力の時間軸の字幕と、素材のどの区間を残したか（`ranges`）を書く。"""
    try:
        rows = [{"start": round(float(s.get("start", 0)), 3), "end": round(float(s.get("end", 0)), 3),
                 "text": s.get("text", "")} for s in segments]
        data = {"segments": rows,
                "ranges": [[round(float(a), 3), round(float(b), 3)] for a, b in (ranges or [])]}
        subtitle_sidecar_path(video_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"字幕の横置き JSON を書けませんでした: {e}")


def retime_segments(segments, merged):
    """BUG-PV02/PV04: 字幕の時刻をカット後の時間軸に直す。

    merged は元の動画の時間軸で残す区間。merged[0]=(s0,e0) は出力の 0〜(e0-s0) 秒、
    merged[1]=(s1,e1) は (e0-s0)〜(e0-s0)+(e1-s1) 秒に並ぶ。
    どの区間に属するかは発話の区間（sourceStart/sourceEnd）で、表示の時刻は
    `_display_span` で決める。返り値は (直した字幕, 出力の尺, カット点)。
    """
    recalculated_segments = []
    output_offset = 0.0
    cut_points = []  # カットポイントの出力タイムライン位置を記録
    for ri, (range_start, range_end) in enumerate(merged):
        if ri > 0:
            cut_points.append(output_offset)
        for seg in segments:
            seg_start = seg.get("sourceStart", seg.get("start", 0))
            seg_end = seg.get("sourceEnd", seg.get("end", 0))
            # セグメントがこのrangeに含まれるか判定
            if seg_start >= range_start and seg_end <= range_end + 0.5:
                show_start, show_end = _display_span(seg)
                new_seg = dict(seg)
                new_start = output_offset + (show_start - range_start)
                new_end = output_offset + (min(show_end, range_end) - range_start)

                # A-3: カットポイント直後の字幕バッファ
                # カット直後0.5秒以内に始まる字幕は開始を遅らせる
                for cp in cut_points:
                    if cp <= new_start < cp + CUT_SUBTITLE_BUFFER:
                        new_start = cp + CUT_SUBTITLE_BUFFER
                        break

                if new_end > new_start:  # バッファ適用後も有効な場合のみ追加
                    new_seg["start"] = new_start
                    new_seg["end"] = new_end
                    recalculated_segments.append(new_seg)
        output_offset += (range_end - range_start)
    return recalculated_segments, output_offset, cut_points


def render_smart_cut(
    segments,
    original_video_path,
    output_path,
    generate_thumbnail: bool = False,
    thumbnail_path: str | None = None,
    thumbnail_time: float = 0.5
):
    """
    Cuts the original video based on 'sourceStart' and 'sourceEnd' of segments,
    concatenates the kept parts, and then overlays the subtitles.
    
    Phase D: MoviePy to FFmpeg + GPU (NVENC) migration complete.
    """
    from video_editor_engine import video_editor, VideoClip

    logger.info("--- Starting Smart Cut Render (FFmpeg + GPU) ---")
    
    # 1. Extract and Merge Source Ranges
    keep_ranges = []
    for s in segments:
        start = s.get("sourceStart", s["start"])
        end = s.get("sourceEnd", s["end"])
        keep_ranges.append((float(start), float(end)))
    
    keep_ranges.sort()
    
    merged = []
    if keep_ranges:
        curr_start, curr_end = keep_ranges[0]
        for start, end in keep_ranges[1:]:
            # Merge if adjacent (within 0.3s tolerance to catch floating point gaps)
            if start <= curr_end + 0.3:
                curr_end = max(curr_end, end)
            else:
                merged.append((curr_start, curr_end))
                curr_start, curr_end = start, end
        merged.append((curr_start, curr_end))
    
    logger.info(f"Merged Cut Ranges: {merged}")

    # 2. Process Video Slicing with FFmpeg (GPU accelerated)
    temp_parts = []
    temp_cut_path = None
    try:
        ffmpeg = video_editor.ffmpeg
        input_path = Path(original_video_path)
        temp_cut_path = Path(output_path).with_suffix('.tmp.mp4')
        # **1回のエンコードで残す区間だけを抜く**（2026-10-06）。パーツに -c copy で
        # 切って concat すると、キーフレーム・AAC の端数がパーツごとに積み上がり、
        # 178 パーツで**映像と音声が字幕より 22 秒遅れた**（素材 25 分地点で 15 秒）。
        exact = len(merged) > 1 and _cut_kept_ranges_exact(ffmpeg, input_path, merged, temp_cut_path)
        if not exact:
            if len(merged) > 1:
                logger.warning("区間の一括抽出に失敗 → パーツを切って結合する従来の方法に戻します（ずれが出ます）")
        
            # 動画の長さを取得（境界チェック用）
            total_duration = ffmpeg.get_duration(input_path)
            if total_duration is None:
                logger.warning("Could not determine video duration, proceeding anyway")
                total_duration = float('inf')
        
            for i, (start, end) in enumerate(merged):
                # 境界チェック
                s = max(0, min(start, total_duration))
                e = max(0, min(end, total_duration))
                if e <= s:
                    continue
            
                temp_path = Path(output_path).parent / f"_smartcut_part_{i:04d}.mp4"
                if ffmpeg.cut_video(input_path, temp_path, s, e):
                    temp_parts.append(temp_path)
                else:
                    logger.warning(f"Failed to cut segment {i} ({s:.2f}-{e:.2f})")
        
            if not temp_parts:
                logger.error("No valid ranges to keep.")
                return False

            logger.info(f"SmartCut: {len(temp_parts)} parts to merge")

            # 3. Merge all parts
            temp_cut_path = Path(output_path).with_suffix('.tmp.mp4')
            if len(temp_parts) == 1:
                # 単一セグメントの場合はコピー
                import shutil
                shutil.copy(temp_parts[0], temp_cut_path)
            else:
                clips = [VideoClip(path=p) for p in temp_parts]
                # 大容量テスト対応: 多数パートのconcatには長時間必要
                orig_timeout = 600
                try:
                    # merge_videosでrun_command内のtimeout=600が足りない場合に対応
                    # run_commandのデフォルトtimeoutを一時的に延長
                    ffmpeg._merge_timeout = 1800  # 30分
                except (AttributeError, TypeError) as e:
                    logger.debug(f"merge_timeout設定スキップ: {e}")
                if not ffmpeg.merge_videos(clips, temp_cut_path):
                    logger.error(f"Merge failed ({len(clips)} clips)")
                    return False
        
        # 4. ━━━ BUG-PV02/PV04修正: SRTタイムスタンプをカット後タイムラインに再計算 ━━━
        # merged rangesは元動画の時間軸。カット後の新タイムラインを構築する。
        # merged[0]=(s0,e0) → 出力0〜(e0-s0)秒
        # merged[1]=(s1,e1) → 出力(e0-s0)〜(e0-s0)+(e1-s1)秒
        recalculated_segments, output_offset, cut_points = retime_segments(segments, merged)

        logger.info(f"SRTタイムスタンプ再計算: {len(segments)}seg → {len(recalculated_segments)}seg, 出力尺={output_offset:.1f}s, カットポイント={len(cut_points)}箇所")

        # 出力の時間軸の字幕を横に置く。品質ゲートが「喋っているのに字幕が無い」を
        # 出力の音声と突き合わせて数える（2026-10-06 ユーザー指摘の欠落）
        write_subtitle_sidecar(output_path, recalculated_segments, merged)

        # 5. Overlay Subtitles via FFmpeg (Phase D: MoviePy 完全脱却)
        burn_result = _burn_subtitles_ffmpeg(str(temp_cut_path), recalculated_segments, output_path, ffmpeg)
        
        # C-07: フォールバック3（字幕なしコピー）検出
        if burn_result == "fallback_no_subtitle":
            logger.warning("⚠️ 字幕焼込み完全失敗 — 字幕なし動画として出力")
            
        logger.info(f"✅ Smart Cut complete: {output_path}")

        # --- サムネイル自動生成機能 ---
        if generate_thumbnail:
            try:
                if not thumbnail_path:
                    out_p = Path(output_path)
                    thumbnail_path = str(out_p.parent / f"{out_p.stem}_thumbnail.jpg")
                
                logger.info(f"Generating thumbnail at {thumbnail_time}s to: {thumbnail_path}")
                try:
                    from screenshot_generator import extract_screenshot
                    extract_screenshot(output_path, thumbnail_time, thumbnail_path)
                except (ImportError, OSError, ValueError, subprocess.SubprocessError, RuntimeError) as inner_e:
                    logger.warning(f"Failed to use screenshot_generator, fallback to direct FFmpeg: {inner_e}")
                    cmd = [
                        "ffmpeg",
                        "-ss", str(thumbnail_time),
                        "-i", output_path,
                        "-vframes", "1",
                        "-vf", "scale=1280:-1",
                        "-y",
                        thumbnail_path
                    ]
                    success, _ = ffmpeg.run_command(cmd, timeout=30)
                    if not success:
                        logger.error("Direct FFmpeg thumbnail extraction failed")
            except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as e:
                logger.error(f"Thumbnail generation failed: {e}", exc_info=True)

        return True

    except (FileNotFoundError, PermissionError, OSError, subprocess.SubprocessError) as e:
        logger.error(f"Smart Cut Error: {e}", exc_info=True)
        return False

    finally:
        # CR-4修正: 一時ファイルの確実なクリーンアップ（中断・例外時もリークしない）
        for p in temp_parts:
            try:
                if p.exists():
                    p.unlink()
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.debug(f"一時ファイル削除スキップ: {e}")
        if temp_cut_path:
            try:
                if temp_cut_path.exists():
                    temp_cut_path.unlink()
            except (FileNotFoundError, PermissionError, OSError) as e:
                logger.debug(f"一時ファイル削除スキップ: {e}")


