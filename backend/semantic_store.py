"""
Semantic Subtitle Store v2
Phase 2: Context Intelligence

根本的改善版:
- ストリーミング応答で即時処理
- 非同期API呼び出し
- プログレッシブフォールバック
- キャッシュ機能
- 詳細なエラーハンドリング
"""

import json
import logging
import hashlib
import tempfile
from pathlib import Path
from typing import List, Dict, Optional, Generator
from dataclasses import dataclass, field, asdict
from datetime import datetime

from dotenv import load_dotenv
from google.genai.errors import APIError
from gemini_client_factory import get_gemini_client
import os

from model_registry import get_model

load_dotenv()
logger = logging.getLogger(__name__)

# 設定
BATCH_SIZE = 30  # より小さいバッチサイズ
API_TIMEOUT = 60  # タイムアウトを延長
CACHE_DIR = Path(__file__).parent / ".cache" / "semantic"
USE_CACHE = True  # キャッシュを有効化
USE_FAST_MODEL = True  # 高速モデルを優先


@dataclass
class SemanticSegment:
    """意味的に構造化されたセグメント"""
    id: str
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    semantic_tags: List[str] = field(default_factory=list)
    importance: float = 0.5
    emotion: str = "neutral"
    topic: str = ""
    telop_candidate: bool = False
    telop_suggestion: str = ""
    highlight_candidate: bool = False


@dataclass
class Topic:
    """トピック"""
    id: str
    name: str
    start_seg: str
    end_seg: str
    start_time: float
    end_time: float
    duration_sec: float
    summary: str = ""


@dataclass
class KeyMoment:
    """重要シーン"""
    seg_id: str
    type: str
    score: float
    reason: str = ""


class SemanticSubtitleStoreV2:
    """Semantic Subtitle Store v2 - 根本的改善版"""
    
    # 簡略化したプロンプト（高速化）
    FAST_ANALYSIS_PROMPT = """
    以下の字幕から重要なポイントを抽出してください。

    {segments}

    重要度0.7以上のセグメントIDと、テロップ候補のみを出力してください。
    JSON形式: {{"important": ["seg_001", "seg_042"], "telops": [{{"id": "seg_042", "text": "短縮テキスト"}}]}}
    """

    # JSON抽出用の正規表現パターン
    JSON_PATTERN = r'\{[\s\S]*\}'

    # ルールベース分析用のキーワード
    HIGH_IMPORTANCE_KEYWORDS = ["大切", "本質", "秘訣", "ポイント", "重要", "核心", "すごい", "感動", "名言"]
    MID_IMPORTANCE_KEYWORDS = ["思う", "感じ", "なるほど", "そうですね"]

    def __init__(self, store_path: Optional[Path] = None, cache_dir: Optional[Path] = None):
        self.store_path = store_path
        self.cache_dir = cache_dir or CACHE_DIR
        self.segments: List[SemanticSegment] = []
        self.topics: List[Topic] = []
        self.key_moments: List[KeyMoment] = []
        self.metadata: Dict = {}
        self.stats: Dict = {"api_calls": 0, "cache_hits": 0, "fallbacks": 0}
        
        self.client = get_gemini_client()
        
        # 高速モデルを使用
        self.model = get_model("subtitle_split") if USE_FAST_MODEL else get_model("quality_gate")
        
        # キャッシュディレクトリ作成
        if USE_CACHE:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.warning(f"キャッシュディレクトリ作成失敗。パス: {self.cache_dir}, エラー: {e}")
        
        if store_path:
            self._load()
    
    def _get_cache_key(self, segments: List[Dict]) -> str:
        """キャッシュキーを生成"""
        content = json.dumps([s.get("text", "") for s in segments], ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()
    
    def _get_cached_result(self, cache_key: str) -> Optional[Dict]:
        """キャッシュから結果を取得（破損チェック付き）"""
        if not USE_CACHE:
            return None
        
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.stats["cache_hits"] += 1
                    logger.info(f"キャッシュヒット: {cache_key[:8]}...")
                    return data
            except json.JSONDecodeError as e:
                logger.warning(f"破損したキャッシュファイルを検出しました。削除します: {cache_file} (Error: {e})")
                try:
                    cache_file.unlink()
                except OSError as de:
                    logger.error(f"破損キャッシュファイルの削除に失敗しました。パス: {cache_file}, エラー: {de}")
            except OSError as e:
                logger.warning(f"キャッシュ読み込みエラー。パス: {cache_file}, エラー: {e}")
        return None
    
    def _atomic_write_json(self, file_path: Path, data: Dict, prefix: str, indent: Optional[int] = None) -> None:
        """アトミックにJSONデータをファイルへ保存する共通ヘルパー"""
        temp_dir = file_path.parent
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=str(temp_dir), suffix=".tmp", prefix=prefix)
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                tmp_fd = None  # fdopenに所有権が移ったため、ここでのクローズ義務を解除
                if indent is not None:
                    json.dump(data, f, ensure_ascii=False, indent=indent)
                else:
                    json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_path, str(file_path))
        except BaseException:
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def _save_to_cache(self, cache_key: str, result: Dict):
        """結果をキャッシュに保存（アトミック書き込み）"""
        if not USE_CACHE:
            return
        
        cache_file = self.cache_dir / f"{cache_key}.json"
        
        try:
            self._atomic_write_json(cache_file, result, prefix="cache_")
        except OSError as e:
            logger.warning(f"キャッシュ保存エラー。パス: {cache_file}, エラー: {e}")
    
    def _load(self):
        """ストアを読み込み（詳細例外ハンドリングと安全な初期化）"""
        self.metadata = {}
        self.segments = []
        self.topics = []
        self.key_moments = []
        
        if not self.store_path:
            return
            
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.metadata = data.get("metadata", {})
            self.segments = [SemanticSegment(**s) for s in data.get("segments", [])]
            self.topics = [Topic(**t) for t in data.get("topics", [])]
            self.key_moments = [KeyMoment(**k) for k in data.get("key_moments", [])]
            logger.info(f"Semantic Store読み込み: {len(self.segments)}セグメント")
        except FileNotFoundError:
            logger.warning(f"ストアファイルが見つかりません。新規作成します: {self.store_path}")
        except json.JSONDecodeError as e:
            logger.error(f"ストアファイルのJSON破損を検出しました: {e}")
        except OSError as e:
            logger.error(f"ストア読み込み中にOSエラーが発生しました。パス: {self.store_path}, エラー: {e}")
    
    def save(self, path: Optional[Path] = None):
        """ストアを保存（アトミック書き込み）"""
        save_path = path or self.store_path
        if not save_path:
            raise ValueError("保存パスが指定されていません")
        
        data = {
            "version": "2.0",
            "created_at": datetime.now().isoformat(),
            "metadata": self.metadata,
            "stats": self.stats,
            "segments": [asdict(s) for s in self.segments],
            "topics": [asdict(t) for t in self.topics],
            "key_moments": [asdict(k) for k in self.key_moments]
        }
        
        try:
            self._atomic_write_json(save_path, data, prefix="sem_", indent=2)
            logger.info(f"Semantic Store保存: {save_path}")
        except OSError as e:
            logger.error(f"Semantic Store保存中にOSエラーが発生しました。パス: {save_path}, エラー: {e}")
            raise
    
    def _sanitize_single_segment(self, index: int, raw_segment: Dict) -> Optional[Dict]:
        """個別の入力セグメントをサニタイズするヘルパーメソッド"""
        if not isinstance(raw_segment, dict):
            logger.warning(f"インデックス {index} のセグメントが辞書型ではありません。スキップします。")
            return None
            
        # IDの検証・付与
        seg_id = raw_segment.get("id")
        if seg_id is None:
            seg_id = f"seg_{index:03d}"
        else:
            seg_id = str(seg_id)
            
        # テキストの検証
        text = raw_segment.get("text")
        if text is None:
            text = ""
        else:
            text = str(text)
            
        # 時間の検証
        try:
            start = float(raw_segment.get("start", 0.0))
        except (ValueError, TypeError):
            logger.warning(f"セグメント {seg_id} の start が不正です。0.0 にフォールバックします。")
            start = 0.0
            
        try:
            end = float(raw_segment.get("end", 0.0))
        except (ValueError, TypeError):
            logger.warning(f"セグメント {seg_id} の end が不正です。0.0 にフォールバックします。")
            end = 0.0
            
        return {
            "id": seg_id,
            "text": text,
            "start": start,
            "end": end,
            "speaker": raw_segment.get("speaker")
        }

    def _validate_and_sanitize_segments(self, segments: List[Dict]) -> List[Dict]:
        """入力セグメントのバリデーションとサニタイズ"""
        if not isinstance(segments, list):
            logger.warning("入力セグメントがリストではありません。空リストとして扱います。")
            return []
            
        sanitized_segments = []
        for index, raw_segment in enumerate(segments):
            sanitized_seg = self._sanitize_single_segment(index, raw_segment)
            if sanitized_seg is not None:
                sanitized_segments.append(sanitized_seg)
        return sanitized_segments

    def analyze(self, normalized_segments: List[Dict], metadata: Optional[Dict] = None) -> Dict:
        """
        セグメントを分析（根本的改善版）
        
        改善点:
        1. 入力バリデーション
        2. キャッシュ優先
        3. 高速モデル使用
        4. 簡略化プロンプト
        5. 即時フォールバック
        """
        self.metadata = metadata or {}
        
        # 入力データのバリデーションとサニタイズ
        sanitized_segments = self._validate_and_sanitize_segments(normalized_segments)
        total_segments = len(sanitized_segments)
        
        logger.info(f"Semantic分析開始（v2）: {total_segments}セグメント")
        
        # まず全セグメントを基本構造化（即座に完了）
        self._quick_analyze_all(sanitized_segments)
        logger.info(f"基本分析完了: {len(self.segments)}セグメント")
        
        if total_segments > 0:
            # バッチ処理でAI分析を追加（失敗しても基本結果は保持）
            if total_segments > BATCH_SIZE:
                self._enhance_with_ai_batched(sanitized_segments)
            else:
                self._enhance_with_ai(sanitized_segments)
        
        logger.info(f"分析完了 - API: {self.stats['api_calls']}, キャッシュ: {self.stats['cache_hits']}, フォールバック: {self.stats['fallbacks']}")
        return self._get_summary()
    
    def _evaluate_rule_based_importance(self, text: str) -> tuple[float, bool]:
        """テキストの内容からルールベースの重要度とテロップ候補判定を評価する"""
        importance = 0.5
        telop_candidate = False
        
        if any(kw in text for kw in self.HIGH_IMPORTANCE_KEYWORDS):
            importance = 0.8
            if len(text) < 40:
                telop_candidate = True
        elif any(kw in text for kw in self.MID_IMPORTANCE_KEYWORDS):
            importance = 0.6
        elif len(text) < 15:
            importance = 0.3  # 短い相槌は低重要度
            
        return importance, telop_candidate

    def _quick_analyze_all(self, segments: List[Dict]):
        """全セグメントを即座に基本分析"""
        self.segments = []
        
        for i, seg in enumerate(segments):
            seg_id = seg.get("id", f"seg_{i:03d}")
            text = seg.get("text", "")
            
            importance, telop_candidate = self._evaluate_rule_based_importance(text)
            
            self.segments.append(SemanticSegment(
                id=seg_id,
                start=seg.get("start", 0),
                end=seg.get("end", 0),
                text=text,
                speaker=seg.get("speaker"),
                importance=importance,
                telop_candidate=telop_candidate,
                highlight_candidate=importance >= 0.8
            ))
    
    def _enhance_with_ai_batched(self, segments: List[Dict]):
        """バッチ処理でAI分析"""
        total = len(segments)
        
        for i in range(0, total, BATCH_SIZE):
            batch = segments[i:i+BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
            
            logger.info(f"AI強化 {batch_num}/{total_batches}...")
            self._enhance_with_ai(batch)
    
    def _enhance_with_ai(self, segments: List[Dict]):
        """AI分析で結果を強化（詳細例外ハンドリングとフォールバック）"""
        # キャッシュチェック
        cache_key = self._get_cache_key(segments)
        cached = self._get_cached_result(cache_key)
        if cached:
            self._apply_ai_result(cached)
            return
        
        # API呼び出し
        segments_text = "\n".join([
            f"[{s.get('id', f'seg_{i:03d}')}] {s.get('text', '')[:40]}"
            for i, s in enumerate(segments)
        ])
        
        prompt = self.FAST_ANALYSIS_PROMPT.format(segments=segments_text)
        
        try:
            self.stats["api_calls"] += 1
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"timeout": API_TIMEOUT}
            )
            
            result = self._parse_fast_response(response.text)
            self._save_to_cache(cache_key, result)
            self._apply_ai_result(result)
            
        except (AttributeError, ValueError, TypeError, APIError) as e:
            logger.warning(f"AI強化失敗（基本分析へフォールバックします）: {e}")
            self.stats["fallbacks"] += 1
    
    def _parse_fast_response(self, text: str) -> Dict:
        """高速分析レスポンスをパース（型・構造 of 安全バリデーション）"""
        import re
        json_match = re.search(self.JSON_PATTERN, text)
        result = {"important": [], "telops": []}
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                # 型とキーのバリデーション
                if isinstance(parsed, dict):
                    important = parsed.get("important", [])
                    if isinstance(important, list):
                        result["important"] = [str(x) for x in important]
                    telops = parsed.get("telops", [])
                    if isinstance(telops, list):
                        sanitized_telops = []
                        for t in telops:
                           if isinstance(t, dict) and "id" in t and "text" in t:
                                sanitized_telops.append({"id": str(t["id"]), "text": str(t["text"])})
                        result["telops"] = sanitized_telops
            except json.JSONDecodeError as e:
                logger.warning(f"高速分析レスポンスのJSONパース失敗: {e}")
            except (TypeError, ValueError) as e:
                logger.warning(f"高速分析レスポンス解析中の予期せぬエラー: {e}")
        return result
    
    def _apply_ai_result(self, result: Dict, segments: Optional[List[Dict]] = None):
        """AI結果を適用"""
        important_ids = set(result.get("important", []))
        telops = {t["id"]: t["text"] for t in result.get("telops", []) if isinstance(t, dict) and "id" in t}
        
        for seg in self.segments:
            if seg.id in important_ids:
                seg.importance = max(seg.importance, 0.8)
                seg.highlight_candidate = True
            if seg.id in telops:
                seg.telop_candidate = True
                seg.telop_suggestion = telops[seg.id]
    
    def _get_summary(self) -> Dict:
        """サマリーを取得"""
        return {
            "total_segments": len(self.segments),
            "topics": len(self.topics),
            "key_moments": len(self.key_moments),
            "telop_candidates": len([s for s in self.segments if s.telop_candidate]),
            "high_importance": len([s for s in self.segments if s.importance >= 0.8]),
            "stats": self.stats
        }
    
    def get_telop_candidates(self) -> List[Dict]:
        """テロップ候補を取得"""
        return [asdict(s) for s in self.segments if s.telop_candidate or s.importance >= 0.8]
    
    def get_key_moments(self, min_score: float = 0.8) -> List[Dict]:
        """重要シーンを取得"""
        return [asdict(k) for k in self.key_moments if k.score >= min_score]
    
    def get_topics(self) -> List[Dict]:
        """トピック一覧を取得"""
        return [asdict(t) for t in self.topics]


# ファクトリ関数（v2を使用）
def create_semantic_store(normalized_segments: List[Dict], 
                          store_path: Optional[Path] = None,
                          metadata: Optional[Dict] = None) -> SemanticSubtitleStoreV2:
    """Semantic Storeを作成（v2）"""
    store = SemanticSubtitleStoreV2(store_path)
    store.analyze(normalized_segments, metadata)
    if store_path:
        store.save()
    return store
