"""
Gemini Semantic Chunking - Fixed Version
Phase 30 - Week 2 Implementation

Whisperの出力を意味単位で区切り、読みやすい字幕に整形
バッファリング問題修正済み
"""

import sys
import io
import json
import os
from typing import List, Dict
from pathlib import Path



from google import genai

import logging

logger = logging.getLogger(__name__)

# Import Model Registry
try:
    try:
        from .model_registry import get_model
    except ImportError:
        from model_registry import get_model
    DEFAULT_MODEL = get_model("semantic_chunker")
except Exception:
    DEFAULT_MODEL = "gemini-2.5-flash"

client = None


def process_whisper_segments(
    whisper_json_path: str,
    video_theme: str = "",
    batch_size: int = 50
) -> List[Dict]:
    """
    Whisper JSONをGeminiで意味単位分割
    
    Args:
        whisper_json_path: Whisper出力JSONパス
        video_theme: 動画のテーマ
        batch_size: 一度に処理するセグメント数
    
    Returns:
        意味単位分割されたセグメント
    """
    print(f"\n{'='*60}", flush=True)
    print(f"🧠 Gemini 意味単位分割", flush=True)
    print(f"{'='*60}", flush=True)
    
    # Whisper JSON読み込み
    with open(whisper_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    segments = data.get("segments", [])
    print(f"📄 入力: {len(segments)} セグメント", flush=True)
    print(f"🎬 テーマ: {video_theme or '対談動画'}", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    # Use Model Registry
    model_name = DEFAULT_MODEL

    
    # バッチ処理
    all_results = []
    for i in range(0, len(segments), batch_size):
        batch = segments[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(segments) + batch_size - 1) // batch_size
        
        print(f"⏳ バッチ {batch_num}/{total_batches} 処理中...", flush=True)
        
        # APIクライアント取得 (遅延初期化 + テスト用モック考慮)
        global client
        if client is None:
            try:
                from .gemini_client_factory import get_gemini_client
            except ImportError:
                from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
        
        # テキスト化
        batch_text = "\n".join([
            f"[{s['start']:.1f}s-{s['end']:.1f}s] {s['text']}"
            for s in batch
        ])
        
        prompt = f"""
以下は動画の音声認識結果です。要件に従って整形してください。

【動画のテーマ】
{video_theme or "対談動画"}

【要件】
1. 文の途中で切れないように調整
2. 1セグメントは1-2文程度
3. 意味のまとまりで区切る
4. 「あの」「えっと」「まあ」などのフィラーは削除
5. 誤字は修正
6. タイムスタンプは元のものを維持

【音声認識結果】
{batch_text}

【出力形式】
JSONリストで返してください。```jsonで囲んでください。
[
  {{"start": 開始秒, "end": 終了秒, "text": "整形されたテキスト"}}
]
"""
        
        try:
            if client is None:
                logger.warning("   ⚠️ Gemini Client が None です (フォールバック使用)")
                all_results.extend(batch)
                continue
                
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            result_text = response.text
            
            # JSON抽出
            if "```json" in result_text:
                json_str = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                json_str = result_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = result_text.strip()
            
            batch_results = json.loads(json_str)
            all_results.extend(batch_results)
            print(f"   ✅ {len(batch_results)} セグメント生成", flush=True)
            
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
            logger.warning(f"   ⚠️ JSONパースエラーまたはセグメント構造不正 (元のセグメントをフォールバック使用): {e}")
            all_results.extend(batch)
        except Exception as e:
            logger.error(f"   ⚠️ 予期せぬエラー (元のセグメントをフォールバック使用): {e}", exc_info=True)
            all_results.extend(batch)
    
    print(f"\n{'='*60}", flush=True)
    print(f"✅ 完了: {len(all_results)} セグメント", flush=True)
    print(f"{'='*60}\n", flush=True)
    
    return all_results


def save_as_srt(segments: List[Dict], output_path: str):
    """SRT形式で保存"""
    with open(output_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start = seg['start']
            end = seg['end']
            text = seg['text']
            
            # タイムスタンプをミリ秒に変換して浮動小数点の丸め誤差を防ぐ
            start_ms = int(round(start * 1000))
            end_ms = int(round(end * 1000))
            
            start_ts = f"{start_ms//3600000:02d}:{(start_ms%3600000)//60000:02d}:{(start_ms%60000)//1000:02d},{start_ms%1000:03d}"
            end_ts = f"{end_ms//3600000:02d}:{(end_ms%3600000)//60000:02d}:{(end_ms%60000)//1000:02d},{end_ms%1000:03d}"
            
            f.write(f"{i}\n")
            f.write(f"{start_ts} --> {end_ts}\n")
            f.write(f"{text}\n\n")
    
    print(f"💾 SRT保存: {Path(output_path).name}", flush=True)


def main(whisper_json_path: str, video_theme: str = ""):
    """メイン処理"""
    whisper_json_path = Path(whisper_json_path)
    
    if not whisper_json_path.exists():
        print(f"❌ ファイルが見つかりません: {whisper_json_path}", flush=True)
        return None
    
    # Gemini処理
    processed_segments = process_whisper_segments(str(whisper_json_path), video_theme)
    
    # SRT保存
    output_srt = whisper_json_path.parent / f"{whisper_json_path.stem}_semantic.srt"
    save_as_srt(processed_segments, str(output_srt))
    
    # JSON保存（デバッグ用）
    output_json = whisper_json_path.parent / f"{whisper_json_path.stem}_semantic.json"
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump({"segments": processed_segments}, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON保存: {output_json.name}", flush=True)
    
    print(f"\n🎉 完了!", flush=True)
    return str(output_srt)


if __name__ == "__main__":
    # UTF-8出力を強制
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name)
        if hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        else:
            try:
                # フォールバック
                setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding='utf-8', errors='replace'))
            except Exception:
                pass
    
    if len(sys.argv) < 2:
        print("使用方法: python gemini_chunker_fixed.py <whisper_json_path> [video_theme]")
        sys.exit(1)
    
    whisper_json = sys.argv[1]
    theme = sys.argv[2] if len(sys.argv) > 2 else ""
    
    main(whisper_json, theme)
