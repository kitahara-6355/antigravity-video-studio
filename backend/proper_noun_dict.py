"""
固有名詞辞書システム
Phase 1: Foundation

機能:
- 固有名詞辞書の読み込み・保存
- 自動学習（同じ修正が閾値回数以上で自動追加）
- 不確実語句のリストアップ
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

logger = logging.getLogger(__name__)

# 辞書ファイルパス
DICT_PATH = Path(__file__).parent / "branding" / "proper_nouns.json"


@dataclass
class DictionaryEntry:
    """辞書エントリ"""
    id: str
    incorrect: str
    correct: str
    type: str  # person_name, word, word_context, title
    context_hint: str = ""
    confirmed: bool = True
    usage_count: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PendingConfirmation:
    """確認待ちエントリ"""
    incorrect: str
    suggested_correct: str
    context: str
    confidence: float
    occurrences: int = 1


class ProperNounDictionary:
    """固有名詞辞書管理クラス"""
    
    def __init__(self, dict_path: Path = DICT_PATH):
        self.dict_path = dict_path
        self.entries: List[DictionaryEntry] = []
        self.pending: List[PendingConfirmation] = []
        self.auto_learn = True
        self.learning_threshold = 3
        self._load()
    
    def _load(self):
        """辞書を読み込み"""
        if self.dict_path.exists():
            try:
                with open(self.dict_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise TypeError("辞書データのルートはオブジェクトである必要があります。")
                self.auto_learn = data.get("auto_learn", True)
                self.learning_threshold = data.get("learning_threshold", 3)
                self.entries = [
                    DictionaryEntry(**e) for e in data.get("entries", [])
                ]
                self.pending = [
                    PendingConfirmation(**p) for p in data.get("pending_confirmations", [])
                ]
                logger.info(f"固有名詞辞書をロード: {len(self.entries)}エントリ")
            except json.JSONDecodeError as e:
                logger.error(f"辞書JSONパースエラー (破損したJSON): {e}")
                self.entries = []
            except (TypeError, KeyError, ValueError, AttributeError) as e:
                logger.error(f"辞書データ構造エラー (スキーマ不一致): {e}")
                self.entries = []
            except OSError as e:
                logger.error(f"辞書ファイルアクセスエラー: {e}")
                self.entries = []
        else:
            logger.info("固有名詞辞書が存在しません。新規作成します。")
            self._save()
    
    def _save(self):
        """辞書を保存"""
        data = {
            "version": "1.0",
            "description": "固有名詞辞書 - 音声認識の誤変換を自動修正",
            "auto_learn": self.auto_learn,
            "learning_threshold": self.learning_threshold,
            "entries": [asdict(e) for e in self.entries],
            "pending_confirmations": [asdict(pending_entry) for pending_entry in self.pending]
        }
        self.dict_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.dict_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"固有名詞辞書を保存: {len(self.entries)}エントリ")
    
    def _record_correction_usage(self, entry: DictionaryEntry):
        """修正の利用実績を記録"""
        entry.usage_count += 1

    def apply_corrections(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        テキストに辞書を適用
        
        Returns:
            (修正後テキスト, 適用した修正リスト)
        """
        corrections = []
        corrected_text = text
        
        for entry in self.entries:
            if entry.incorrect in corrected_text:
                corrected_text = corrected_text.replace(entry.incorrect, entry.correct)
                corrections.append({
                    "original": entry.incorrect,
                    "corrected": entry.correct,
                    "type": entry.type
                })
                self._record_correction_usage(entry)
        
        if corrections:
            self._save()
            logger.info(f"辞書適用: {len(corrections)}件の修正")
        
        return corrected_text, corrections
    
    def add_entry(self, incorrect: str, correct: str, entry_type: str = "word",
                  context_hint: str = "", confirmed: bool = True) -> DictionaryEntry:
        """新規エントリを追加"""
        max_num = 0
        for entry in self.entries:
            if entry.id.startswith("pn_"):
                try:
                    num = int(entry.id[3:])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
        entry_id = f"pn_{max_num + 1:03d}"
        entry = DictionaryEntry(
            id=entry_id,
            incorrect=incorrect,
            correct=correct,
            type=entry_type,
            context_hint=context_hint,
            confirmed=confirmed
        )
        self.entries.append(entry)
        self._save()
        logger.info(f"辞書に追加: {incorrect} → {correct}")
        return entry
    
    def remove_entry(self, entry_id: str) -> bool:
        """エントリを削除"""
        for i, entry in enumerate(self.entries):
            if entry.id == entry_id:
                removed = self.entries.pop(i)
                self._save()
                logger.info(f"辞書から削除: {removed.incorrect}")
                return True
        return False
    
    def _update_existing_pending(self, pending_entry: PendingConfirmation, context: str) -> bool:
        """既存の確認待ちエントリを更新し、自動学習の閾値に達した場合は登録する"""
        pending_entry.occurrences += 1
        if self.auto_learn and pending_entry.occurrences >= self.learning_threshold:
            self.add_entry(pending_entry.incorrect, pending_entry.suggested_correct, "auto_learned", context)
            self.pending.remove(pending_entry)
        self._save()
        return True

    def _add_new_pending(self, incorrect: str, suggested: str, context: str, confidence: float):
        """新規の確認待ちエントリを追加する"""
        self.pending.append(PendingConfirmation(
            incorrect=incorrect,
            suggested_correct=suggested,
            context=context,
            confidence=confidence
        ))
        self._save()

    def suggest_correction(self, incorrect: str, suggested: str, context: str, confidence: float):
        """修正候補を提案（確認待ちに追加）"""
        # 既存の確認待ちを探す
        for pending_entry in self.pending:
            if pending_entry.incorrect == incorrect and pending_entry.suggested_correct == suggested:
                self._update_existing_pending(pending_entry, context)
                return
        
        # 新規追加
        self._add_new_pending(incorrect, suggested, context, confidence)
    
    def confirm_pending(self, incorrect: str, approved: bool, final_correct: Optional[str] = None):
        """確認待ちを承認/却下"""
        for pending_entry in self.pending:
            if pending_entry.incorrect == incorrect:
                if approved:
                    correct = final_correct or pending_entry.suggested_correct
                    self.add_entry(incorrect, correct, "user_confirmed", pending_entry.context)
                self.pending.remove(pending_entry)
                self._save()
                return True
        return False
    
    def get_all_entries(self) -> List[Dict[str, Any]]:
        """全エントリを取得"""
        return [asdict(e) for e in self.entries]
    
    def get_pending(self) -> List[Dict[str, Any]]:
        """確認待ちを取得"""
        return [asdict(pending_entry) for pending_entry in self.pending]


# シングルトンインスタンス
proper_noun_dict = ProperNounDictionary()


def apply_dictionary(text: str) -> Tuple[str, List[Dict[str, Any]]]:
    """辞書を適用（簡易関数）"""
    return proper_noun_dict.apply_corrections(text)


def add_proper_noun(incorrect: str, correct: str, entry_type: str = "word") -> Dict[str, Any]:
    """固有名詞を追加（簡易関数）"""
    entry = proper_noun_dict.add_entry(incorrect, correct, entry_type)
    return asdict(entry)
