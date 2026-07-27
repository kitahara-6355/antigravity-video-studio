# -*- coding: utf-8 -*-
"""
Token Limiter — Opus への送信コンテキストの自動トリミング機能
"""
import logging
import re
from typing import Optional, List

logger = logging.getLogger(__name__)

try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False

MAX_OPUS_TOKENS_DEFAULT = 120000

class TokenLimiter:
    """
    Claude Opus への送信コンテキストサイズを制御するトークンカウンターおよびトリミングエンジン。
    """
    def __init__(self, max_tokens: int = MAX_OPUS_TOKENS_DEFAULT):
        self.max_tokens = max_tokens

    def count_tokens(self, text: Optional[str]) -> int:
        """
        テキストのトークン数を計算する。
        tiktoken が利用可能な場合は cl100k_base を使用し、
        利用不可能な場合は文字数ベースの安全係数を考慮したフォールバックカウンターを使用する。
        """
        if not text:
            return 0
        if HAS_TIKTOKEN:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                return len(encoding.encode(text))
            except (ValueError, RuntimeError) as e:
                logger.warning(f"tiktoken encoding failed: {e}. Falling back to character count.")
        
        # フォールバックカウンター: len(text) // 4 を基本とする。
        # 最小値は 1 を返す。
        return max(1, len(text) // 4)

    def trim_context(self, context_text: str, max_tokens: Optional[int] = None) -> str:
        """
        コンテキストテキストが指定の上限トークン数を超える場合、トリミングまたは要約を行う。
        
        アルゴリズム:
        1. コンテキストを行単位に分割。
        2. トークン数が上限を超える場合、特定の履歴ログや完了報告などのセクションを特定。
        3. それらのセクションから、古い行（最初の方の行）を優先的に削る。
        4. セクションを削ってもまだ上限を超える場合、あるいはセクションが特定できない場合は、
           テキスト全体の最初からトークン数が上限以下になるまで行単位で削除する。
        """
        limit = max_tokens if max_tokens is not None else self.max_tokens
        
        total_tokens = self.count_tokens(context_text)
        if total_tokens <= limit:
            return context_text
            
        logger.info(f"Context tokens ({total_tokens}) exceed limit ({limit}). Starting trimming...")
        
        # 行に分割
        lines = context_text.splitlines()
        
        # リストアイテム行（`-` または `*` または `数字.` で始まる行）を優先的に削除する
        list_line_indices = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("-") or stripped.startswith("*") or re.match(r"^\d+\.", stripped):
                list_line_indices.append(i)
                
        # 二分探索によるリスト行削除
        if list_line_indices:
            all_list_remove = set(list_line_indices)
            temp_lines_all = [line for i, line in enumerate(lines) if i not in all_list_remove]
            temp_text_all = "\n".join(temp_lines_all)
            
            if self.count_tokens(temp_text_all) <= limit:
                low = 1
                high = len(list_line_indices)
                best_k = high
                while low <= high:
                    mid = (low + high) // 2
                    to_remove = set(list_line_indices[:mid])
                    temp_lines = [line for i, line in enumerate(lines) if i not in to_remove]
                    temp_text = "\n".join(temp_lines)
                    if self.count_tokens(temp_text) <= limit:
                        best_k = mid
                        high = mid - 1
                    else:
                        low = mid + 1
                
                to_remove = set(list_line_indices[:best_k])
                temp_lines = [line for i, line in enumerate(lines) if i not in to_remove]
                logger.info(f"Trimming succeeded by removing {best_k} history list entries.")
                return "\n".join(temp_lines)
                
        # リスト行をすべて削除しても上限を超える場合は、最初から順番に行を削っていく（二分探索）
        low = 0
        high = len(lines) - 1
        best_i = high
        while low <= high:
            mid = (low + high) // 2
            to_remove = set(range(mid + 1)) | set(list_line_indices)
            temp_lines = [line for idx, line in enumerate(lines) if idx not in to_remove]
            temp_text = "\n".join(temp_lines)
            if self.count_tokens(temp_text) <= limit:
                best_i = mid
                high = mid - 1
            else:
                low = mid + 1
                
        to_remove = set(range(best_i + 1)) | set(list_line_indices)
        temp_lines = [line for idx, line in enumerate(lines) if idx not in to_remove]
        temp_text = "\n".join(temp_lines)
        if self.count_tokens(temp_text) <= limit:
            logger.info(f"Trimming succeeded by removing total {len(to_remove)} lines.")
            return temp_text
            
        # すべて削ってもダメな場合の極限フォールバック
        return ""
