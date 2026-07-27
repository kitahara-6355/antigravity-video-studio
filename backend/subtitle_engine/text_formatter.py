"""
text_formatter.py — 字幕テキスト整形エンジン

旧 src/clean_linguistic.py から移植。
Whisper出力の長文セグメントを日本語の言語境界（助詞・句読点）で
15文字/行に分割し、字幕の画面はみ出しを防止する。

Phase C: word_timestamps対応 — 単語レベルタイミングで正確な発話同期を実現。
"""

import logging
import re

logger = logging.getLogger(__name__)

# ============================================================
# 設定
# ============================================================

MAX_CHARS_PER_LINE = 15  # A-2: NHK基準（13〜15文字/行）に変更
FILLERS = [
    "えーと", "えー", "あのー", "あのー、", "まぁ", "ちょっと",
    "そのー", "なんか", "そうそうそう", "あー", "うーん", "えっと",
]

# 日本語の助詞・句読点パターン（分割ポイント）
SPLIT_PATTERN = re.compile(r"(.+?[はがをにのでと、。？！]|.+?です|.+?ます)")



# ============================================================
# 安全なセグメントコピー
# ============================================================

def _safe_copy_segment(seg: dict) -> dict:
    """セグメント辞書を安全にコピーする。

    もしコピーに失敗した場合は例外を投げる。
    """
    if hasattr(seg, "copy"):
        return seg.copy()
    return dict(seg)


# ============================================================
# フィラー除去
# ============================================================

def remove_fillers(text: str) -> str:
    """フィラー（無意味なつなぎ言葉）を除去"""
    if not isinstance(text, str):
        logger.warning(f"Non-string input passed to remove_fillers: {type(text)}")
        return ""
    for filler in FILLERS:
        text = text.replace(filler, "")
    return text.strip()


# ============================================================
# 言語境界分割（メイン）
# ============================================================

def _split_at_boundary(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> list[str]:
    """
    日本語の助詞・句読点境界でテキストを分割する。

    旧 src/clean_linguistic.py split_linguistically() の移植版。
    fugashi (MeCab) 依存を排除し、正規表現ベースで動作。
    イテレーティブ実装により再帰深度制限の問題を回避。

    Args:
        text: 分割するテキスト
        max_chars: 1行の最大文字数

    Returns:
        分割された文字列 of リスト
    """
    if not isinstance(text, str):
        return []

    # max_charsの安全ガード
    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        return [text]

    if len(text) <= max_chars:
        return [text]

    # イテレーティブに max_chars 以下のチャンクに分割
    chunks = []
    remaining = text

    while len(remaining) > max_chars:
        # パフォーマンス向上のため、対象をスライスして検索範囲を制限
        search_range = remaining[:max_chars + 5]
        best_split = -1
        for m in SPLIT_PATTERN.finditer(search_range):
            end_pos = m.end()
            if end_pos <= max_chars:
                best_split = end_pos
            else:
                break  # max_chars を超えたら探索終了

        if best_split >= 2:
            # 助詞・句読点 of 境界で分割
            chunks.append(remaining[:best_split].strip())
            remaining = remaining[best_split:].strip()
        else:
            # 分割ポイントが見つからない場合: max_chars で強制分割
            chunks.append(remaining[:max_chars].strip())
            remaining = remaining[max_chars:].strip()

    if remaining:
        chunks.append(remaining.strip())

    return [c for c in chunks if c]


def enforce_line_length(text: str, max_chars: int = MAX_CHARS_PER_LINE) -> str:
    """
    指定されたテキストの各行が max_chars 以下になるよう、
    必要に応じて改行 (\n) を挿入する。
    """
    if not isinstance(text, str):
        return ""

    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        return text

    if len(text) <= max_chars:
        return text

    lines = text.split("\n")
    new_lines = []
    for line in lines:
        if len(line) <= max_chars:
            new_lines.append(line)
        else:
            temp_line = line
            while len(temp_line) > max_chars:
                split_idx = max_chars
                # 助詞・句読点パターンで最後のマッチを探す
                matches = list(SPLIT_PATTERN.finditer(temp_line[:max_chars + 1]))
                if matches:
                    best_match = matches[-1]
                    end_idx = best_match.end()
                    if 2 <= end_idx <= max_chars:
                        split_idx = end_idx
                
                new_lines.append(temp_line[:split_idx].strip())
                temp_line = temp_line[split_idx:].strip()
            if temp_line:
                new_lines.append(temp_line)
                
    return "\n".join(new_lines)



# ============================================================
# Phase C: 単語タイミングベース分割
# ============================================================

def _split_by_word_timing(words: list[dict], max_chars: int, parent_seg: dict) -> list[dict]:
    """Phase C: 単語タイミングに基づいて正確にチャンク分割

    wordsの実際のタイムスタンプを使い、max_chars以内で自然にグルーピング。
    按分計算と違い、字幕と発話が完全に同期する。
    """
    if not isinstance(words, list) or not isinstance(parent_seg, dict):
        return []

    if not words:
        return []

    # max_charsの安全ガード
    if not isinstance(max_chars, int):
        try:
            max_chars = int(max_chars)
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    if max_chars <= 0:
        max_chars = MAX_CHARS_PER_LINE

    chunks = []
    current_text = ""
    chunk_start = None
    chunk_end = None
    current_words = []

    for w in words:
        if not isinstance(w, dict):
            continue
        word_text = w.get("word", "")
        if not isinstance(word_text, str):
            continue
        word_text = word_text.strip()
        if not word_text:
            continue

        # フィラーチェック
        if word_text in FILLERS:
            continue

        w_start = w.get("start")
        if not isinstance(w_start, (int, float)):
            parent_start = parent_seg.get("start")
            w_start = parent_start if isinstance(parent_start, (int, float)) else 0.0

        w_end = w.get("end")
        if not isinstance(w_end, (int, float)):
            w_end = w_start

        # 安全ガード：単語レベルでのタイムスタンプ逆転防止
        w_end = max(w_end, w_start)

        if chunk_start is None:
            chunk_start = w_start
            chunk_end = w_end

        # この単語を追加するとmax_charsを超えるか？
        if current_text and len(current_text) + len(word_text) > max_chars:
            # 現在のチャンクを保存
            if current_text.strip():
                try:
                    new_seg = _safe_copy_segment(parent_seg)
                    new_seg["text"] = current_text.strip()
                    new_seg["start"] = chunk_start
                    new_seg["end"] = chunk_end
                    if "words" in new_seg:
                        new_seg["words"] = current_words.copy()
                    chunks.append(new_seg)
                except Exception as e:
                    logger.error(f"Error copying parent segment in word timing split: {e}")
            # 新しいチャンク開始
            current_text = word_text
            chunk_start = w_start
            chunk_end = w_end
            current_words = [w]
        else:
            current_text += word_text
            chunk_end = w_end
            current_words.append(w)

    # 最後のチャンク
    if current_text.strip():
        try:
            new_seg = _safe_copy_segment(parent_seg)
            new_seg["text"] = current_text.strip()
            new_seg["start"] = chunk_start if chunk_start is not None else parent_seg.get("start", 0)
            new_seg["end"] = chunk_end if chunk_end is not None else parent_seg.get("end", 0)
            # 安全ガード：逆転防止
            if new_seg["start"] is not None and new_seg["end"] is not None:
                new_seg["end"] = max(new_seg["end"], new_seg["start"])
            if "words" in new_seg:
                new_seg["words"] = current_words.copy()
            chunks.append(new_seg)
        except Exception as e:
            logger.error(f"Error copying parent segment for final chunk: {e}")

    return chunks if len(chunks) > 1 else []


# ============================================================
# メイン整形関数
# ============================================================

def format_segments(segments: list[dict], max_chars: int = MAX_CHARS_PER_LINE) -> list[dict]:
    """
    セグメントリストにテキスト整形を適用する。

    1. フィラー除去
    2. Phase C: wordsフィールドがある場合は単語タイミングベースで分割
    3. wordsがない場合は従来の言語境界分割 + タイミング按分

    Args:
        segments: セグメントリスト
        max_chars: 1行の最大文字数

    Returns:
        整形済みセグメントリスト
    """
    if not isinstance(segments, list):
        return []

    if not segments:
        return segments

    # max_charsの安全ガード
    if not isinstance(max_chars, int) or max_chars <= 0:
        try:
            max_chars = int(max_chars)
            if max_chars <= 0:
                max_chars = MAX_CHARS_PER_LINE
        except (ValueError, TypeError):
            max_chars = MAX_CHARS_PER_LINE

    formatted = []
    split_count = 0
    filler_count = 0
    word_split_count = 0

    for seg in segments:
        if not isinstance(seg, dict):
            continue

        try:
            text = seg.get("text", "")
            if not isinstance(text, str):
                continue
            text = text.strip()

            # Step 1: フィラー除去
            cleaned = remove_fillers(text)
            if cleaned != text:
                filler_count += 1

            if not cleaned:
                continue

            # Step 2: Phase C — word_timestampsベースの分割
            words = seg.get("words")
            if isinstance(words, list) and words and len(cleaned) > max_chars:
                chunks = _split_by_word_timing(words, max_chars, seg)
                if chunks and len(chunks) > 1:
                    formatted.extend(chunks)
                    word_split_count += 1
                    continue

            # Step 3: 短いテキストはそのまま
            if len(cleaned) <= max_chars:
                new_seg = _safe_copy_segment(seg)
                new_seg["text"] = cleaned
                formatted.append(new_seg)
                continue

            # Step 4: 従来の言語境界分割 + タイミング按分
            chunks = _split_at_boundary(cleaned, max_chars)

            if len(chunks) <= 1:
                new_seg = _safe_copy_segment(seg)
                new_seg["text"] = cleaned
                formatted.append(new_seg)
                continue

            total_chars = sum(len(c) for c in chunks)
            
            start = seg.get("start")
            end = seg.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                start = 0.0
                end = 0.0
            # タイムスタンプ逆転防止
            if end < start:
                end = start
            duration = end - start
            current_start = start

            for chunk in chunks:
                chunk_duration = (len(chunk) / total_chars) * duration if total_chars > 0 else duration / len(chunks)
                new_seg = _safe_copy_segment(seg)
                new_seg["text"] = chunk
                new_seg["start"] = current_start
                new_seg["end"] = current_start + chunk_duration
                # sourceStart/sourceEnd は元のまま維持（SmartCut用）
                formatted.append(new_seg)
                current_start += chunk_duration

            split_count += 1
        except Exception as e:
            logger.error(f"Unexpected error formatting segment: {e}", exc_info=True)
            # フォールバック: エラーが発生した場合は元のセグメントをそのまま追加して処理を継続
            try:
                formatted.append(_safe_copy_segment(seg))
            except Exception:
                formatted.append(seg)

    if split_count > 0 or filler_count > 0 or word_split_count > 0:
        logger.info(
            f"✂️ テキスト整形完了: フィラー除去 {filler_count}件, "
            f"word_timestamps分割 {word_split_count}件, "
            f"言語境界分割 {split_count}件 ({len(segments)} → {len(formatted)} セグメント)"
        )

    # 字幕速度の自動調整を適用
    formatted = adjust_segment_speeds(formatted)

    # 1行の強制改行制限を適用
    for seg in formatted:
        if isinstance(seg, dict) and "text" in seg:
            seg["text"] = enforce_line_length(seg["text"], max_chars)

    return formatted


# ============================================================
# 字幕表示速度の自動調整
# ============================================================

def adjust_segment_speeds(segments: list[dict], max_cps: float = None) -> list[dict]:
    """セグメントの表示速度（CPS）が目標閾値（max_cps * 2）を超えないよう調整する。

    1. 前後のセグメントと衝突しない範囲で、endを次のstartの手前まで延長する。
    2. それでもCPSが閾値を超える場合、テキストが長く、改行を含まない場合は適切な位置に改行を入れることで最長行文字数を減らす。
    """
    if not isinstance(segments, list):
        return []

    if not segments:
        return segments

    if max_cps is None:
        max_cps = get_chars_per_second_from_template()

    # max_cps のガード（None や 0 以下、NaN / INF の場合の安全フォールバック）
    import math
    if (not isinstance(max_cps, (int, float)) 
            or math.isnan(max_cps) 
            or math.isinf(max_cps) 
            or max_cps <= 0):
        max_cps = 4.0

    limit_cps = max_cps * 2  # NHK基準の2倍（デフォルト 8.0 文字/秒）を超えると検品違反になる
    
    adjusted = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            adjusted.append(_safe_copy_segment(seg))
        except Exception as e:
            logger.error(f"Error copying segment in adjust_segment_speeds: {e}")
            adjusted.append(seg)
        
    n = len(adjusted)

    for i in range(n):
        seg = adjusted[i]
        text = seg.get("text", "")
        # text が文字列でない場合はスキップ
        if not isinstance(text, str) or not text:
            continue

        # 表示字幕速度: 改行で分割された各行の最長行で判定
        lines = text.split("\n")
        max_line_len = max((len(line) for line in lines), default=0)

        # 短い字幕（8文字以下）は一目で読めるため、元々速度チェック対象外
        if max_line_len <= 8:
            continue

        start = seg.get("start")
        end = seg.get("end")

        # start, end が None または数値型でない場合はスキップ
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue

        dur = end - start

        if dur <= 0:
            continue

        current_cps = max_line_len / dur
        if current_cps <= limit_cps:
            continue

        # --- ステップ1: 表示時間の延長 ---
        # 次のセグメントの開始時間（なければ動画末尾や大きなマージン）
        next_start = None
        if i < n - 1:
            next_seg = adjusted[i+1]
            if isinstance(next_seg, dict):
                next_start = next_seg.get("start")
                
        if not isinstance(next_start, (int, float)):
            next_start = end + 5.0
        # 次のセグメントと 0.05秒 の安全マージンを空ける
        max_end = min(next_start - 0.05, end + 2.0)

        if max_end > end:
            # 必要な秒数を算出: max_line_len / limit_cps
            target_dur = max_line_len / limit_cps
            new_end = min(max_end, start + target_dur)
            seg["end"] = new_end
            dur = new_end - start
            current_cps = max_line_len / dur

        # --- ステップ2: 改行の挿入による最長行文字数の削減 ---
        if current_cps > limit_cps and "\n" not in text and len(text) > 8:
            # 助詞・句読点で自然に改行できるか調べる
            split_points = [m.end() - 1 for m in SPLIT_PATTERN.finditer(text)]
            if split_points:
                # 文字列の中央に最も近い分割ポイントを選択
                mid = len(text) // 2
                best_point = min(split_points, key=lambda x: abs(x - mid))
                # 端すぎるポイント（前後のマージン2文字）でなければ改行を挿入
                if 2 < best_point < len(text) - 2:
                    new_text = text[:best_point+1] + "\n" + text[best_point+1:]
                    seg["text"] = new_text

                    # 最長行とCPSを再計算
                    lines = new_text.split("\n")
                    max_line_len = max(len(line) for line in lines)
                    current_cps = max_line_len / dur

            # それでもダメなら中央で単純に改行を入れる
            if current_cps > limit_cps and "\n" not in seg["text"]:
                mid = len(text) // 2
                new_text = text[:mid] + "\n" + text[mid:]
                seg["text"] = new_text

                # 再計算
                lines = new_text.split("\n")
                max_line_len = max(len(line) for line in lines)
                current_cps = max_line_len / dur

    return adjusted


# ============================================================
# テンプレート連携
# ============================================================

def get_max_chars_from_template() -> int:
    """テンプレートから最大文字数を取得（未設定時はデフォルト15文字）"""
    try:
        from template_config import template_config
        rules = template_config.get_subtitle_rules()
        if not isinstance(rules, dict):
            return MAX_CHARS_PER_LINE
        val = rules.get("max_chars_per_line", MAX_CHARS_PER_LINE)
        if not isinstance(val, int):
            return MAX_CHARS_PER_LINE
        return val
    except Exception as e:
        logger.warning(f"Template config fallback due to template/system exception: {e}")
        return MAX_CHARS_PER_LINE


def get_chars_per_second_from_template() -> float:
    """テンプレートから秒間最大文字数（CPS）を取得（未設定時はデフォルト4.0文字）"""
    try:
        from template_config import template_config
        rules = template_config.get_subtitle_rules()
        if not isinstance(rules, dict):
            return 4.0
        val = rules.get("chars_per_second", 4.0)
        if not isinstance(val, (int, float)):
            return 4.0
        return float(val)
    except Exception as e:
        logger.warning(f"Template config CPS fallback due to template/system exception: {e}")
        return 4.0
