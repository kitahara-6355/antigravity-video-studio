"""

Whisper サブプロセスランナー — チャンク分割GPU戦略



CTranslate2 + CUDA が長尺音声(>5分)でデッドロックする問題に対し、

音声を5分チャンクに分割し各チャンクを独立GPU処理する。



戦略:

  1. FFmpegで16kHz mono WAV抽出

  2. WAVを5分チャンクに分割

  3. 各チャンクをGPU Whisperで処理（チャンク間タイムアウト付き）

  4. タイムスタンプをオフセット補正して統合

  5. デッドロック区間はスキップ（部分結果で続行）

"""



import sys

import json

import time

import logging

import os

import queue

import threading

from pathlib import Path



logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

logger = logging.getLogger("whisper_subprocess")



CHUNK_DURATION = 300  # 5分チャンク

CHUNK_TIMEOUT = 600   # チャンクあたり10分タイムアウト (CPUモードでのスキップ防止)





def get_video_hash(video_path: str) -> str:

    """動画のパスから一意なハッシュ値を計算"""

    import hashlib

    try:

        abs_path = os.path.abspath(video_path)

        return hashlib.md5(abs_path.encode('utf-8')).hexdigest()[:12]

    except (OSError, ValueError, AttributeError) as e:

        logger.warning(f"Failed to get absolute path for hash: {e}")

        return hashlib.md5(str(video_path).encode('utf-8')).hexdigest()[:12]





def extract_audio_wav(video_path: str, output_dir: str) -> str:

    """FFmpegで音声を16kHz mono WAVに変換"""

    import subprocess

    video_hash = get_video_hash(video_path)

    wav_path = str(Path(output_dir) / f"_whisper_audio_{video_hash}.wav")



    if Path(wav_path).exists():

        wav_mtime = Path(wav_path).stat().st_mtime

        vid_mtime = Path(video_path).stat().st_mtime

        if wav_mtime > vid_mtime:

            logger.info(f"♻️ 既存WAV再利用: {wav_path}")

            return wav_path



    logger.info(f"🔊 音声抽出中...")

    start = time.time()

    result = subprocess.run(

        ["ffmpeg", "-y", "-i", video_path,

         "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",

         wav_path],

        capture_output=True, text=True, timeout=120

    )

    if result.returncode != 0:

        raise RuntimeError(f"FFmpeg failed: {result.stderr[:300]}")



    size_mb = Path(wav_path).stat().st_size / (1024**2)

    logger.info(f"✅ WAV: {size_mb:.0f}MB ({time.time()-start:.1f}s)")

    return wav_path





def split_wav_chunks(wav_path: str, output_dir: str, chunk_sec: int, video_hash: str = "") -> list:

    """WAVをチャンク分割（FFmpegで高速分割）"""

    import subprocess

    

    # 総長取得

    r = subprocess.run(

        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", wav_path],

        capture_output=True, text=True

    )

    total = float(r.stdout.strip()) if r.stdout.strip() else 0

    

    if total <= chunk_sec:

        return [(wav_path, 0.0, total)]  # 短い音声はチャンク分割不要

    

    chunks = []

    offset = 0.0

    idx = 0

    while offset < total:

        end = min(offset + chunk_sec, total)

        chunk_name = f"_chunk_{video_hash}_{idx:03d}.wav" if video_hash else f"_chunk_{idx:03d}.wav"

        chunk_path = str(Path(output_dir) / chunk_name)

        

        subprocess.run(

            ["ffmpeg", "-y", "-i", wav_path,

             "-ss", str(offset), "-t", str(chunk_sec),

             "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",

             chunk_path],

            capture_output=True, text=True, timeout=30

        )

        

        if Path(chunk_path).exists() and Path(chunk_path).stat().st_size > 1000:

            chunks.append((chunk_path, offset, end))

        

        offset = end

        idx += 1

    

    logger.info(f"📦 {len(chunks)}チャンクに分割 (各{chunk_sec}秒)")

    return chunks





def transcribe_chunk(model, chunk_path: str, offset: float, language: str, chunk_idx: int, total_chunks: int) -> list:

    """1チャンクをGPUで文字起こし（タイムアウト付き）"""

    segments = []

    result_queue = queue.Queue()

    

    def _run():

        try:

            segs_iter, _ = model.transcribe(

                chunk_path,

                beam_size=1,

                language=language,

                condition_on_previous_text=False,  # チャンク独立処理

                word_timestamps=True,  # Phase C: 単語レベルタイムスタンプ

            )

            chunk_segs = []

            for seg in segs_iter:

                # Phase C: 単語タイミングを抽出

                words = []

                if getattr(seg, "words", None):

                    for w in seg.words:

                        w_text = (getattr(w, "word", "") or "").strip()

                        words.append({

                            "word": w_text,

                            "start": round(getattr(w, "start", 0.0) + offset, 2),

                            "end": round(getattr(w, "end", 0.0) + offset, 2),

                        })

                seg_text = (getattr(seg, "text", "") or "").strip()

                chunk_segs.append({

                    "start": round(getattr(seg, "start", 0.0) + offset, 2),

                    "end": round(getattr(seg, "end", 0.0) + offset, 2),

                    "text": seg_text,

                    "sourceStart": round(getattr(seg, "start", 0.0) + offset, 2),

                    "sourceEnd": round(getattr(seg, "end", 0.0) + offset, 2),

                    "words": words,  # Phase C: 単語レベルタイミング

                })

            result_queue.put(("ok", chunk_segs))

        except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as e:
            result_queue.put(("error", str(e)))

    

    t = threading.Thread(target=_run, daemon=True)

    t.start()

    

    try:

        status, data = result_queue.get(timeout=CHUNK_TIMEOUT)

        if status == "ok":

            return data

        else:

            logger.warning(f"⚠️ チャンク{chunk_idx+1}/{total_chunks} エラー: {data}")

            return []

    except queue.Empty:

        logger.warning(f"⏰ チャンク{chunk_idx+1}/{total_chunks} タイムアウト({CHUNK_TIMEOUT}s) — スキップ")

        return []





def main():

    if len(sys.argv) < 3:

        print(json.dumps({"error": "Usage: whisper_subprocess.py <video_path> <output_jsonl_path> [model_size] [language]"}))

        sys.exit(1)



    video_path = sys.argv[1]

    output_path = sys.argv[2]

    model_size = sys.argv[3] if len(sys.argv) > 3 else "small"

    language = sys.argv[4] if len(sys.argv) > 4 else "ja"



    logger.info(f"=== Whisper チャンク分割GPU戦略 ===")

    logger.info(f"動画: {video_path}")

    logger.info(f"モデル: {model_size}, チャンク: {CHUNK_DURATION}秒")



    # CUDA DLLパス

    nvidia_paths = [

        Path(sys.executable).parent.parent / "Lib" / "site-packages" / "nvidia",

    ]

    for p in sys.path:

        if "site-packages" in p:

            nvidia_paths.append(Path(p) / "nvidia")



    for nvidia_path in nvidia_paths:

        if nvidia_path.exists():

            for sub in ["cublas/bin", "cudnn/bin", "cuda_nvrtc/bin"]:

                dll_path = str(nvidia_path / sub)

                if Path(dll_path).exists() and dll_path not in os.environ.get("PATH", ""):

                    os.environ["PATH"] = dll_path + os.pathsep + os.environ.get("PATH", "")



    try:

        from faster_whisper import WhisperModel

        import subprocess



        # ━━━ Step 1: 動画長取得 ━━━

        r = subprocess.run(

            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],

            capture_output=True, text=True

        )

        total_duration = float(r.stdout.strip()) if r.stdout.strip() else 1800.0

        logger.info(f"動画: {total_duration:.0f}秒 ({total_duration/60:.1f}分)")



        # ━━━ Step 2: WAV抽出 ━━━

        output_dir = str(Path(output_path).parent)

        video_hash = get_video_hash(video_path)

        wav_path = extract_audio_wav(video_path, output_dir)



        # ━━━ Step 3: チャンク分割 ━━━

        chunks = split_wav_chunks(wav_path, output_dir, CHUNK_DURATION, video_hash)

        logger.info(f"📦 {len(chunks)}チャンク生成完了")



        # ━━━ Step 4: GPUモデルロード ━━━

        device = "cpu"

        compute_type = "int8"

        try:
            import ctranslate2
            ctranslate2.get_supported_compute_types("cuda")
            
            # cuDNN DLL のロード可能性チェック (Windows)
            has_cudnn = True
            if sys.platform == "win32":
                import ctypes
                try:
                    ctypes.CDLL("cudnn_ops64_9.dll")
                except OSError:
                    try:
                        ctypes.CDLL("cudnn_ops_infer64_8.dll")
                    except OSError:
                        has_cudnn = False
                        logger.warning("⚠️ cuDNN DLL (cudnn_ops64_9.dll / cudnn_ops_infer64_8.dll) がロードできないため、CPU モードにフォールバックします")
            
            if has_cudnn:
                device = "cuda"
                compute_type = "float16"
                logger.info("🚀 CUDA GPU detected & cuDNN verified")
            else:
                device = "cpu"
                compute_type = "int8"
                logger.info("⚠️ cuDNN missing — Using CPU mode")
        except (ImportError, ValueError, RuntimeError) as e:
            logger.info(f"⚠️ CPU mode (CUDA not available or error: {e})")



        logger.info(f"Loading {model_size} on {device}...")

        loaded_model = None

        load_err = None



        def _load():

            nonlocal loaded_model, load_err

            try:

                loaded_model = WhisperModel(model_size, device=device, compute_type=compute_type)

            except (ImportError, ValueError, RuntimeError) as e:

                load_err = e



        lt = threading.Thread(target=_load)

        lt.start()

        lt.join(timeout=90)



        if lt.is_alive() or loaded_model is None:

            logger.warning("⏰ GPU load timeout — CPU fallback")

            device = "cpu"

            compute_type = "int8"

            model = WhisperModel(model_size, device="cpu", compute_type="int8")

        else:

            model = loaded_model



        logger.info(f"✅ Model on {device.upper()}")



        # ━━━ Step 5: チャンク毎にGPU処理 ━━━

        all_segments = []

        skipped = 0

        start_time = time.time()



        for i, (chunk_path, offset, end) in enumerate(chunks):

            logger.info(f"🎤 チャンク {i+1}/{len(chunks)}: {offset:.0f}s-{end:.0f}s")

            print(json.dumps({"progress": int((i / len(chunks)) * 100), "text": f"chunk {i+1}/{len(chunks)}"}), flush=True)



            segs = transcribe_chunk(model, chunk_path, offset, language, i, len(chunks))

            

            if segs:

                all_segments.extend(segs)

                logger.info(f"  ✅ {len(segs)}セグメント (計{len(all_segments)})")

            else:

                skipped += 1

                logger.warning(f"  ⚠️ チャンク{i+1}スキップ")



            # チャンクのWAVファイル削除

            if chunk_path != wav_path:

                try:

                    Path(chunk_path).unlink()

                except OSError as e:

                    logger.warning(f"Failed to delete chunk file {chunk_path}: {e}")



        elapsed = time.time() - start_time



        # ━━━ Step 6: 結果書き出し ━━━

        with open(output_path, "w", encoding="utf-8") as f:

            for seg in all_segments:

                f.write(json.dumps(seg, ensure_ascii=False) + "\n")



        logger.info(f"✅ 完了: {len(all_segments)}セグメント, {skipped}スキップ, {elapsed:.1f}秒 ({device.upper()})")



        print(json.dumps({

            "status": "completed",

            "segments": len(all_segments),

            "skipped_chunks": skipped,

            "output_path": output_path,

            "device": device,

            "model": model_size,

            "elapsed": round(elapsed, 1),

        }), flush=True)



        # WAV削除

        try:

            Path(wav_path).unlink()

        except OSError as e:

            logger.warning(f"Failed to delete extracted WAV file {wav_path}: {e}")



        os._exit(0)



    except (RuntimeError, ValueError, OSError, AttributeError, TypeError, KeyError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        logger.error(f"❌ Whisper error: {e}", exc_info=True)
        print(json.dumps({"status": "error", "error": str(e)}), flush=True)
        os._exit(1)





if __name__ == "__main__":

    main()

