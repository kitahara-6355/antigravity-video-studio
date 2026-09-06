"""
AI Proofreader - Phase 18 Architecture
Gemini 3.0による字幕校閲（フィラー除去、文法修正）
"""

import os
import sys
import json
import traceback
import logging
from google import genai
from google.genai import types
from google.genai.errors import APIError

# Add parent directory for model_registry import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Model resolution: 各バッチで動的解決（枠チェック付き）
def _get_current_model() -> str:
    """現在の枠状況に応じた最適モデルを動的に取得。
    
    Premium → Standard → Batch の順で枠を確認し、
    利用可能な最上位モデルを返す。
    """
    try:
        from model_governance import model_governance
        return model_governance._resolve_model("proofreader")
    except (ImportError, ModuleNotFoundError):
        return "gemini-3.6-flash"
    except Exception as e:
        logger.warning(f"モデルの解決に失敗しました。デフォルトを使用します: {e}")
        return "gemini-3.6-flash"

logger = logging.getLogger(__name__)


def _build_proper_noun_context() -> str:
    """固有名詞辞書からプロンプト用コンテキストを生成（Phase E）"""
    try:
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.get_all_entries()
        if not entries:
            return "## 固有名詞辞書\n（辞書は空です。一般的な日本語校閲のみ実行してください）"
        
        lines = ["## 固有名詞辞書", "以下の固有名詞が出現する可能性があります。音声認識の誤変換を修正してください："]
        for entry in entries:
            incorrect = entry.get("incorrect", "")
            correct = entry.get("correct", "")
            context = entry.get("context_hint", "")
            hint = f"（{context}）" if context else ""
            lines.append(f"- 「{incorrect}」→「{correct}」{hint}")
        
        return "\n".join(lines)
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"固有名詞辞書モジュールが見つかりません。デフォルトの校閲のみ実行します: {e}")
        return "## 固有名詞辞書\n（辞書モジュールが利用できません。一般的な日本語校閲のみ実行してください）"
    except (AttributeError, KeyError, TypeError, ValueError) as e:
        logger.error(f"固有名詞辞書データの解析に失敗しました。詳細: {e}", exc_info=True)
        return "## 固有名詞辞書\n（辞書の解析に失敗しました。一般的な日本語校閲のみ実行してください）"
    except Exception as e:
        logger.error(f"固有名詞辞書の処理中に予期せぬエラーが発生しました: {e}", exc_info=True)
        return "## 固有名詞辞書\n（辞書の処理中に予期せぬエラーが発生しました。一般的な日本語校閲のみ実行してください）"



def proofread_segments(segments, update_callback=None, return_stats=False):
    """
    Gemini APIを使用して字幕セグメントを校閲

    Args:
        segments (list): セグメントリスト（text, start, end等）
        update_callback (callable, optional): 進捗コールバック(status, message, progress)
        return_stats (bool): Trueの場合、(segments, stats_dict) のタプルを返す

    Returns:
        list: 校閲済みセグメント（return_stats=Falseの場合）
        tuple: (segments, stats) のタプル（return_stats=Trueの場合）
            stats = {
                "proofread_count": int,    # 修正されたセグメント数
                "total_retries": int,      # 全バッチのリトライ合計回数
                "failed_batches": int,     # リトライ尽きた失敗バッチ数
                "total_batches": int,      # 全バッチ数
                "skipped": bool,           # APIキーなし等でスキップされたか
            }
    """
    # P-02: リトライ統計の初期化
    stats = {
        "proofread_count": 0,
        "total_retries": 0,
        "failed_batches": 0,
        "total_batches": 0,
        "skipped": False,
    }

    def _return(segs):
        if return_stats:
            return segs, stats
        return segs

    # 入力バリデーション
    if not isinstance(segments, list):
        logger.error("AI Proofreader: segments must be a list")
        stats["skipped"] = True
        return _return(segments)

    for idx, s in enumerate(segments):
        if not isinstance(s, dict):
            logger.error(f"AI Proofreader: segment at index {idx} must be a dict")
            stats["skipped"] = True
            return _return(segments)
        if "text" not in s:
            logger.error(f"AI Proofreader: segment at index {idx} must contain 'text' key")
            stats["skipped"] = True
            return _return(segments)
        if not isinstance(s.get("text"), str):
            logger.error(f"AI Proofreader: segment at index {idx} text must be a string")
            stats["skipped"] = True
            return _return(segments)

        # start, end のタイムスタンプ・バリデーション
        if "start" in s:
            start_val = s.get("start")
            if not isinstance(start_val, (int, float)):
                logger.error(f"AI Proofreader: segment at index {idx} 'start' must be int or float")
                stats["skipped"] = True
                return _return(segments)
            if start_val < 0:
                logger.error(f"AI Proofreader: segment at index {idx} 'start' must be non-negative")
                stats["skipped"] = True
                return _return(segments)

        if "end" in s:
            end_val = s.get("end")
            if not isinstance(end_val, (int, float)):
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be int or float")
                stats["skipped"] = True
                return _return(segments)
            if end_val < 0:
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be non-negative")
                stats["skipped"] = True
                return _return(segments)

        if "start" in s and "end" in s:
            if s.get("end") < s.get("start"):
                logger.error(f"AI Proofreader: segment at index {idx} 'end' must be greater than or equal to 'start'")
                stats["skipped"] = True
                return _return(segments)

    # API キーを環境変数から取得
    api_key = os.getenv("GOOGLE_GENERATIVE_AI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("AI Proofreader: No API Key found. Skipping proofreading.")
        stats["skipped"] = True
        return _return(segments)

    try:
        # D-04修正: GovernedModelsProxy経由でフォールバックチェーンを有効化
        try:
            from model_governance import get_governed_client
            client = get_governed_client("ai_proofreader")
        except ImportError:
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
        CHUNK_SIZE = 100  # サイクル3ループ2: 200→品質低下(-12%)→100に調整(APIコール18→9)
        total_segments = len(segments)
        proofread_count = 0

        total_batches = (total_segments + CHUNK_SIZE - 1) // CHUNK_SIZE
        stats["total_batches"] = total_batches

        logger.info(f"AI Proofreader: Processing {total_segments} segments in batches of {CHUNK_SIZE}...")

        for i in range(0, total_segments, CHUNK_SIZE):
            batch = segments[i:i + CHUNK_SIZE]
            batch_text = ""

            # バッチテキスト作成（絶対インデックス使用）
            for idx, s in enumerate(batch):
                abs_index = i + idx
                batch_text += f"[{abs_index}] {s['text']}\n"

            # 固有名詞辞書をプロンプトに注入（Phase E: 汎用化）
            proper_noun_context = _build_proper_noun_context()

            # Gemini校閲プロンプト（Phase E: 汎用化済み）
            prompt = f"""あなたはプロの動画字幕編集者です。以下の日本語字幕テキストを校閲および修正してください。

文脈を維持しつつ、以下の点を重点的に改善してください：
1. **固有名詞の修正**: 下記の固有名詞辞書を参考に、音声認識の誤変換を正しく修正してください。
2. **フィラーの削除**: 「えー」「あの」「えっと」「あー」などの不要な言葉を削除してください。
3. **自然な日本語**: 文末が不自然な助詞で終わっている場合、自然な言い切りや継続する形に修正してください。
4. **読みやすさ**: 意味を変えずに、字幕として読みやすい長さに調整してください。

{proper_noun_context}

**出力形式**:
必ず以下のJSON形式**のみ**を出力してください。Markdownのコードブロックは不要です。
[
  {{"index": 0, "text": "修正後のテキスト"}},
  {{"index": 1, "text": "修正後のテキスト"}}
]

**入力データ**:
""" + batch_text

            # 進捗表示
            current_batch_num = i // CHUNK_SIZE + 1
            msg = f"AI校閲を実行中 ({current_batch_num}/{total_batches} バッチ)..."

            # 各バッチでモデルを動的解決（枠枯渇時に自動降格）
            model_name = _get_current_model()

            logger.info(f"AI Proofreader: Sending batch {current_batch_num} (model={model_name})...")
            if update_callback:
                update_callback("processing", msg, 99)

            # ━━━ FIX-2A: リトライ付きGemini API呼び出し ━━━
            MAX_RETRIES = 3
            BACKOFF_BASE = 2  # 指数バックオフ: 2s → 4s → 8s
            batch_succeeded = False
            response = None

            for retry in range(MAX_RETRIES + 1):
                try:
                    # Gemini API呼び出し（動的解決モデル使用）
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                        )
                    )
                    batch_succeeded = True
                    break  # 成功 → リトライループ脱出

                except APIError as e:
                    error_str = str(e).lower()
                    is_api_retryable = (
                        e.code in (429, 503)
                        or any(x in error_str for x in ["429", "503", "resource_exhausted", "resourceexhausted", "quota"])
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"API一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue
                    
                    logger.error(f"AI Proofreader: Batch {current_batch_num} APIエラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except (ConnectionError, TimeoutError, OSError) as e:
                    if retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"接続一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    logger.error(f"AI Proofreader: Batch {current_batch_num} 接続エラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except (ValueError, TypeError, RuntimeError) as e:
                    # SDKの他の例外など、未知の例外に対するフォールバック
                    error_str = str(e).lower()
                    is_api_retryable = any(
                        x in error_str
                        for x in ["429", "503", "resource_exhausted", "resourceexhausted", "service_unavailable", "serviceunavailable", "quota"]
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"一時エラーによるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    logger.error(f"AI Proofreader: Batch {current_batch_num} 予期せぬエラーが継続し失敗: {e}")
                    traceback.print_exc()
                    break

                except Exception as e:
                    # 一般的な例外だが、メッセージから再試行可能と判定される場合（429や503など）はリトライに回す
                    error_str = str(e).lower()
                    is_api_retryable = any(
                        x in error_str
                        for x in ["429", "503", "resource_exhausted", "resourceexhausted", "service_unavailable", "serviceunavailable", "quota"]
                    )
                    if is_api_retryable and retry < MAX_RETRIES:
                        wait_sec = BACKOFF_BASE ** (retry + 1)
                        stats["total_retries"] += 1
                        logger.warning(
                            f"🔄 AI Proofreader: Batch {current_batch_num} "
                            f"一時的例外によるリトライ {retry + 1}/{MAX_RETRIES} "
                            f"({wait_sec}秒待機): {e}"
                        )
                        import time as _time
                        _time.sleep(wait_sec)
                        continue

                    # API呼び出し時の想定外の例外に対する安全網
                    logger.error(f"AI Proofreader: Batch {current_batch_num} 予期せぬ重大なエラー: {e}", exc_info=True)
                    break

            if batch_succeeded and response is not None:
                # API使用量を記録
                try:
                    from usage_tracker.api_usage_tracker import record_api_call
                    record_api_call(1, "ai_proofreader")
                except (ImportError, ModuleNotFoundError) as e:
                    logger.debug(f"API使用量トラッカーが見つかりません。スキップします: {e}")
                except OSError as e:
                    logger.warning(f"API使用量の書き込みに失敗しました（I/Oエラー）: {e}")
                except (TypeError, ValueError) as e:
                    logger.warning(f"API使用量記録 of argument or value error: {e}")

                # レスポンスをパース（セキュアなバリデーション付き）
                try:
                    corrected_data = json.loads(response.text)
                except json.JSONDecodeError as jde:
                    logger.error(f"AI Proofreader: Failed to decode JSON response: {jde}")
                    # JSONパース失敗はバッチ失敗とする
                    stats["failed_batches"] += 1
                    continue

                batch_correction_map = {}
                if isinstance(corrected_data, list):
                    for item in corrected_data:
                        if not isinstance(item, dict):
                            logger.warning(f"AI Proofreader: Ignored invalid item format (not dict): {item}")
                            continue
                        if "index" not in item or "text" not in item:
                            logger.warning(f"AI Proofreader: Ignored item missing index or text: {item}")
                            continue

                        try:
                            item_idx = int(item["index"])
                        except (TypeError, ValueError):
                            logger.warning(f"AI Proofreader: Ignored item with invalid index type: {item}")
                            continue

                        # 境界値チェック: 現在のバッチ範囲内に収まっていること
                        if not (i <= item_idx < i + len(batch)):
                            logger.warning(
                                f"AI Proofreader: Ignored out-of-range index {item_idx} "
                                f"(batch range: {i} to {i + len(batch) - 1})"
                            )
                            continue

                        if not isinstance(item["text"], str):
                            logger.warning(f"AI Proofreader: Ignored item with non-string text: {item}")
                            continue

                        batch_correction_map[item_idx] = item["text"]
                else:
                    logger.warning("AI Proofreader: LLM response corrected_data is not a list")

                # セグメントを更新
                for idx, s in enumerate(batch):
                    abs_index = i + idx
                    if abs_index in batch_correction_map:
                        original = s['text']
                        corrected = batch_correction_map[abs_index]
                        if original != corrected:
                            segments[abs_index]['text'] = corrected
                            proofread_count += 1
                            logger.debug(f"Corrected [{abs_index}]: '{original}' -> '{corrected}'")
            else:
                stats["failed_batches"] += 1

        stats["proofread_count"] = proofread_count
        logger.info(f"AI Proofreader: Successfully corrected {proofread_count} segments total."
                     f" (retries={stats['total_retries']}, failed_batches={stats['failed_batches']}/{total_batches})")
        return _return(segments)

    except Exception as e:
        logger.error(f"AI Proofreader Fatal Error: {e}", exc_info=True)
        stats["skipped"] = True
        return _return(segments)


if __name__ == "__main__":
    # 実際の誤変換ケースでテスト
    logging.basicConfig(level=logging.INFO)
    test_segments = [
        {"text": "こんにちは、初夏の北原美玲です。", "start": 0, "end": 5},
        {"text": "えー、あの、本日は久北博之先生にお越しいただいています。", "start": 5, "end": 10}
    ]
    print("--- Before Proofreading ---")
    for s in test_segments:
        print(s['text'])
    
    result = proofread_segments(test_segments)
    
    print("\n--- After Proofreading ---")
    for r in result:
        print(r['text'])
