"""fact_parser.py — VERIFIED_FACTS.md 構造化パーサー

VERIFIED_FACTS.md を構造化データ（dict）としてパースし、
テキスト類似度検索・矛盾検出を提供するモジュール。

設計方針:
    - 2段階フォールバック: 厳格 Markdown パーサー → 正規表現フォールバック
    - TF-IDF ベースのコサイン類似度（外部ライブラリ不要）
    - verified_facts.py の VerifiedFact データ構造と互換性を持つ
    - カテゴリ分類: architecture / implementation / constraint / decision / observation

使用例:
    parser = FactParser()
    facts = parser.parse()
    related = parser.find_related_facts("FastAPIのルーティング構造を変更したい")
    contradictions = parser.check_contradiction("subprocess を直接使用する", facts)
"""

import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================

# VERIFIED_FACTS.md のデフォルトパス
DEFAULT_FACTS_PATH = Path(__file__).parent / "VERIFIED_FACTS.md"

# カテゴリ定義（日本語見出し → 英語ID マッピング）
CATEGORY_MAP_JP_TO_EN: Dict[str, str] = {
    "アーキテクチャ": "architecture",
    "確定仕様": "implementation",
    "学んだ教訓": "constraint",
    "ユーザーの好み・こだわり": "decision",
    "進捗": "observation",
}

# 英語カテゴリ名 → そのまま
VALID_CATEGORIES = {"architecture", "implementation", "constraint", "decision", "observation"}

# ストップワード（日本語テキストの類似度計算ノイズ低減用）
_STOPWORDS = frozenset({
    "の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ",
    "ある", "いる", "する", "も", "な", "から", "まで", "より", "こと",
    "これ", "それ", "あれ", "この", "その", "あの", "ため", "など",
    "です", "ます", "した", "され", "して", "おり", "及び", "または",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "in", "on", "at", "to", "for", "of", "and", "or", "not", "with",
})


# ============================================================
# データ構造
# ============================================================

def make_fact(
    fact_id: str,
    category: str,
    content: str,
    source: str = "",
    verified_at: str = "",
    confidence: float = 1.0,
    evidence: str = "",
) -> Dict:
    """ファクトの構造化 dict を生成する。

    Args:
        fact_id: ファクトの一意ID（例: "vf_0001"）
        category: カテゴリ（architecture / implementation / constraint / decision / observation）
        content: ファクトの内容テキスト
        source: ソース情報（例: "manual", "council", "pipeline"）
        verified_at: 検証日時（ISO8601）。省略時は現在日時
        confidence: 確信度（0.0〜1.0）
        evidence: 裏付け情報テキスト

    Returns:
        構造化されたファクト辞書
    """
    return {
        "id": fact_id,
        "category": category if category in VALID_CATEGORIES else "observation",
        "content": content,
        "source": source,
        "verified_at": verified_at or datetime.now().isoformat(),
        "confidence": confidence,
        "evidence": evidence,
    }


# ============================================================
# テキスト類似度エンジン（TF-IDF + コサイン類似度）
# ============================================================

class _SimilarityEngine:
    """外部ライブラリ不要の TF-IDF ベースコサイン類似度エンジン。

    日本語テキストは文字 N-gram（bigram + unigram）で分割し、
    英語テキストは空白分割でトークン化する。
    """

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """テキストをトークンに分割する。

        日本語はバイグラム + ユニグラム、ASCII部分は空白分割。
        ストップワードを除去する。

        Args:
            text: 入力テキスト

        Returns:
            トークンのリスト
        """
        text_lower = text.lower()
        tokens: List[str] = []

        # ASCII部分を空白分割
        ascii_parts = re.findall(r'[a-zA-Z0-9_]+', text_lower)
        for part in ascii_parts:
            if part not in _STOPWORDS and len(part) > 1:
                tokens.append(part)

        # 非ASCII部分（日本語等）をバイグラム化
        non_ascii = re.sub(r'[a-zA-Z0-9_\s\-\.\,\;\:\!\?\(\)\[\]\{\}\"\'`\*\#\%\/\\]', '', text_lower)
        non_ascii = re.sub(r'[\s]+', '', non_ascii)
        for i in range(len(non_ascii)):
            char = non_ascii[i]
            if char not in _STOPWORDS:
                tokens.append(char)
            if i + 1 < len(non_ascii):
                bigram = non_ascii[i:i+2]
                tokens.append(bigram)

        return tokens

    @staticmethod
    def compute_tf(tokens: List[str]) -> Dict[str, float]:
        """トークンの TF（出現頻度）を計算する。

        Args:
            tokens: トークンリスト

        Returns:
            トークン → TF値 の辞書
        """
        if not tokens:
            return {}
        tf: Dict[str, int] = {}
        for token in tokens:
            tf[token] = tf.get(token, 0) + 1
        total = len(tokens)
        return {k: v / total for k, v in tf.items()}

    @staticmethod
    def compute_idf(documents: List[List[str]]) -> Dict[str, float]:
        """文書コーパス全体の IDF を計算する。

        Args:
            documents: トークン化済み文書のリスト

        Returns:
            トークン → IDF値 の辞書
        """
        n_docs = len(documents)
        if n_docs == 0:
            return {}

        df: Dict[str, int] = {}
        for doc in documents:
            seen = set(doc)
            for token in seen:
                df[token] = df.get(token, 0) + 1

        return {k: math.log((n_docs + 1) / (v + 1)) + 1.0 for k, v in df.items()}

    @staticmethod
    def cosine_similarity(
        vec_a: Dict[str, float], vec_b: Dict[str, float]
    ) -> float:
        """2つのスパースベクトル間のコサイン類似度を計算する。

        Args:
            vec_a: ベクトルA（トークン → 重み）
            vec_b: ベクトルB（トークン → 重み）

        Returns:
            コサイン類似度（0.0〜1.0）
        """
        if not vec_a or not vec_b:
            return 0.0

        # 共通キーのみで内積計算
        common_keys = set(vec_a.keys()) & set(vec_b.keys())
        if not common_keys:
            return 0.0

        dot_product = sum(vec_a[k] * vec_b[k] for k in common_keys)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    @classmethod
    def tfidf_vector(
        cls, tokens: List[str], idf: Dict[str, float]
    ) -> Dict[str, float]:
        """TF-IDF ベクトルを生成する。

        Args:
            tokens: トークンリスト
            idf: IDF辞書

        Returns:
            トークン → TF-IDF値 のスパースベクトル
        """
        tf = cls.compute_tf(tokens)
        return {k: v * idf.get(k, 1.0) for k, v in tf.items()}


# ============================================================
# メインクラス: FactParser
# ============================================================

class FactParser:
    """VERIFIED_FACTS.md を構造化データとしてパースするクラス。

    2段階のパース戦略を採用:
    1. 厳格 Markdown パーサー: 見出し・箇条書きの構造を厳密に解析
    2. 正規表現フォールバック: 構造が壊れた場合でもファクトを抽出

    Attributes:
        facts_path: VERIFIED_FACTS.md のファイルパス
        _facts: パース済みファクトのキャッシュ
        _similarity_engine: 類似度計算エンジン
    """

    def __init__(self, facts_path: Optional[Path] = None):
        """FactParser を初期化する。

        Args:
            facts_path: VERIFIED_FACTS.md のパス。省略時はデフォルトパスを使用。
        """
        self.facts_path = facts_path or DEFAULT_FACTS_PATH
        self._facts: Optional[List[Dict]] = None
        self._similarity_engine = _SimilarityEngine()

    # --------------------------------------------------------
    # パブリック API
    # --------------------------------------------------------

    def parse(self, force_reload: bool = False) -> List[Dict]:
        """VERIFIED_FACTS.md をパースして構造化データのリストを返す。

        2段階フォールバック戦略:
        1. 厳格 Markdown パーサー（見出し + 箇条書き構造を厳密に解析）
        2. 正規表現フォールバック（構造が壊れている場合のフォールバック）

        Args:
            force_reload: True の場合、キャッシュを無視して再パースする

        Returns:
            ファクト辞書のリスト。各要素は make_fact() と同じ構造。
            ファイルが存在しない場合は空リスト。

        Raises:
            なし（エラー時は空リストを返しログに記録）
        """
        if self._facts is not None and not force_reload:
            return self._facts

        if not self.facts_path.exists():
            logger.warning(f"VERIFIED_FACTS.md が見つかりません: {self.facts_path}")
            self._facts = []
            return self._facts

        try:
            content = self.facts_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.error(f"VERIFIED_FACTS.md の読み込みに失敗: {e}", exc_info=True)
            self._facts = []
            return self._facts

        # 戦略1: 厳格 Markdown パーサー
        facts = self._parse_strict(content)

        if not facts:
            # 戦略2: 正規表現フォールバック
            logger.info("厳格パーサーでファクトが0件 → 正規表現フォールバックを実行")
            facts = self._parse_regex_fallback(content)

        self._facts = facts
        logger.info(f"✅ FactParser: {len(facts)}件のファクトをパース完了")
        return self._facts

    def find_related_facts(
        self,
        proposal_text: str,
        top_k: int = 5,
        min_similarity: float = 0.05,
    ) -> List[Dict]:
        """提案テキストに関連するファクトを TF-IDF コサイン類似度で検索する。

        Args:
            proposal_text: 検索クエリとなる提案テキスト
            top_k: 返すファクトの最大数（デフォルト: 5）
            min_similarity: 最低類似度閾値（これ未満のファクトは除外）

        Returns:
            類似度順にソートされたファクト辞書のリスト。
            各要素に "similarity_score" フィールドが追加される。
        """
        facts = self.parse()
        if not facts or not proposal_text.strip():
            return []

        # 全ファクトのトークン化
        fact_tokens_list = [
            self._similarity_engine.tokenize(f["content"]) for f in facts
        ]
        query_tokens = self._similarity_engine.tokenize(proposal_text)

        # IDF 計算（クエリも含めたコーパス）
        all_docs = fact_tokens_list + [query_tokens]
        idf = self._similarity_engine.compute_idf(all_docs)

        # クエリの TF-IDF ベクトル
        query_vec = self._similarity_engine.tfidf_vector(query_tokens, idf)

        # 各ファクトとの類似度を計算
        scored: List[Tuple[float, Dict]] = []
        for i, fact in enumerate(facts):
            fact_vec = self._similarity_engine.tfidf_vector(fact_tokens_list[i], idf)
            sim = self._similarity_engine.cosine_similarity(query_vec, fact_vec)
            if sim >= min_similarity:
                result = dict(fact)
                result["similarity_score"] = round(sim, 4)
                scored.append((sim, result))

        # 類似度降順でソート
        scored.sort(key=lambda x: x[0], reverse=True)

        return [item[1] for item in scored[:top_k]]

    def check_contradiction(
        self,
        proposal_text: str,
        facts: Optional[List[Dict]] = None,
        similarity_threshold: float = 0.15,
    ) -> List[Dict]:
        """提案テキストと既存ファクトの矛盾候補を検出する。

        矛盾検出ロジック:
        1. 提案テキストとファクトの類似度を計算
        2. 類似度が閾値以上（内容が関連している）のファクトに対して
        3. 否定語・対立語の存在を確認

        Args:
            proposal_text: 矛盾チェック対象の提案テキスト
            facts: チェック対象のファクトリスト。省略時は parse() 結果を使用。
            similarity_threshold: 関連性ありと判断する類似度閾値

        Returns:
            矛盾候補のファクト辞書リスト。
            各要素に "contradiction_reason" フィールドが追加される。
        """
        if facts is None:
            facts = self.parse()

        if not facts or not proposal_text.strip():
            return []

        # 否定語・対立語パターン
        negation_patterns = [
            r"禁止", r"不可", r"使用しない", r"してはいけない",
            r"避ける", r"deprecated", r"forbidden",
            r"not\s+use", r"do\s+not", r"must\s+not",
            r"never", r"直接.*禁止", r"使用禁止",
        ]

        # 提案テキストに否定語があるか
        proposal_has_negation = any(
            re.search(p, proposal_text, re.IGNORECASE) for p in negation_patterns
        )

        # 関連ファクトを検索
        related = self.find_related_facts(
            proposal_text,
            top_k=len(facts),  # 全件チェック
            min_similarity=similarity_threshold,
        )

        contradictions: List[Dict] = []
        for fact in related:
            fact_has_negation = any(
                re.search(p, fact["content"], re.IGNORECASE) for p in negation_patterns
            )

            # 矛盾パターン: 一方に否定語があり他方にない
            if proposal_has_negation != fact_has_negation:
                result = dict(fact)
                if proposal_has_negation:
                    result["contradiction_reason"] = (
                        f"提案テキストが既存ファクトと矛盾する可能性: "
                        f"提案に否定/禁止表現があるが、ファクト「{fact['content'][:60]}...」は肯定的"
                    )
                else:
                    result["contradiction_reason"] = (
                        f"既存ファクトの制約に違反する可能性: "
                        f"ファクト「{fact['content'][:60]}...」に否定/禁止表現が含まれる"
                    )
                contradictions.append(result)

            # キーワード一致 + 内容の相違チェック
            proposal_keywords = set(self._similarity_engine.tokenize(proposal_text))
            fact_keywords = set(self._similarity_engine.tokenize(fact["content"]))
            overlap = proposal_keywords & fact_keywords
            if len(overlap) >= 5 and fact.get("similarity_score", 0) < 0.8:
                # キーワードが多く共通しているが全体の類似度が低い → 内容相違の可能性
                if fact not in contradictions:
                    result = dict(fact)
                    result["contradiction_reason"] = (
                        f"同一トピックで内容が異なる可能性: "
                        f"共通キーワード{len(overlap)}個、類似度{fact.get('similarity_score', 0):.2f}"
                    )
                    contradictions.append(result)

        return contradictions

    def get_facts_by_category(self, category: str) -> List[Dict]:
        """指定カテゴリのファクトを取得する。

        Args:
            category: カテゴリ名（architecture / implementation / constraint / decision / observation）

        Returns:
            該当カテゴリのファクト辞書リスト
        """
        facts = self.parse()
        return [f for f in facts if f["category"] == category]

    def get_all_categories(self) -> List[str]:
        """パース済みファクトに含まれるカテゴリ一覧を返す。

        Returns:
            ユニークなカテゴリ名のリスト
        """
        facts = self.parse()
        return list(set(f["category"] for f in facts))

    def get_stats(self) -> Dict:
        """パーサーの統計情報を取得する。

        Returns:
            ファクト数、カテゴリ別件数、平均確信度などの統計辞書
        """
        facts = self.parse()
        if not facts:
            return {
                "total_facts": 0,
                "by_category": {},
                "avg_confidence": 0.0,
                "file_exists": self.facts_path.exists(),
            }

        by_category: Dict[str, int] = {}
        for f in facts:
            cat = f["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_facts": len(facts),
            "by_category": by_category,
            "avg_confidence": sum(f["confidence"] for f in facts) / len(facts),
            "file_exists": True,
        }

    # --------------------------------------------------------
    # プライベート: 厳格 Markdown パーサー
    # --------------------------------------------------------

    def _parse_strict(self, content: str) -> List[Dict]:
        """厳格な Markdown 構造パーサー。

        見出し（## / ###）でカテゴリを判別し、
        箇条書き（- **[N%]**）でファクトを抽出する。
        verified_facts.py の _restore_from_markdown() と互換性のあるフォーマット。

        Args:
            content: VERIFIED_FACTS.md の内容

        Returns:
            パース済みファクト辞書のリスト
        """
        facts: List[Dict] = []
        current_category: Optional[str] = None
        current_fact: Optional[Dict] = None
        fact_counter = 0

        # 見出しパターン: ## 🏗️ アーキテクチャ / ## 📈 進捗 etc.
        header_re = re.compile(r"^#{2,3}\s+(?:[^\w\s]*\s*)?(.+)$")
        # ファクト項目: - **[100%]** Content
        fact_re = re.compile(r"^-\s+\*\*\[(\d+)%\]\*\*\s+(.+)$")
        # 根拠行:   - 根拠: Evidence
        evidence_re = re.compile(r"^\s+-\s+根拠:\s*(.+)$")

        for line in content.splitlines():
            line_stripped = line.strip()

            # カテゴリ見出しの検出
            header_match = header_re.match(line_stripped)
            if header_match:
                raw_cat = header_match.group(1).strip()
                current_category = self._resolve_category(raw_cat)
                continue

            if current_category is None:
                continue

            # ファクト項目の検出
            fact_match = fact_re.match(line_stripped)
            if fact_match:
                confidence = float(fact_match.group(1)) / 100.0
                content_text = fact_match.group(2).strip()
                fact_counter += 1
                fact_id = f"fp_{fact_counter:04d}"

                current_fact = make_fact(
                    fact_id=fact_id,
                    category=current_category,
                    content=content_text,
                    source="verified_facts_md",
                    confidence=min(confidence, 1.0),
                )
                facts.append(current_fact)
                continue

            # 根拠行の検出
            evidence_match = evidence_re.match(line_stripped)
            if evidence_match and current_fact is not None:
                current_fact["evidence"] = evidence_match.group(1).strip()

        return facts

    def _resolve_category(self, raw_category: str) -> str:
        """見出しテキストからカテゴリ英語名を解決する。

        Args:
            raw_category: 見出しから抽出された生テキスト

        Returns:
            正規化されたカテゴリ名
        """
        # 日本語マッピングを試行
        for jp_name, en_name in CATEGORY_MAP_JP_TO_EN.items():
            if jp_name in raw_category:
                return en_name

        # 英語名が直接含まれているか
        raw_lower = raw_category.lower()
        for en_name in VALID_CATEGORIES:
            if en_name in raw_lower:
                return en_name

        # カテゴリ定義テーブルはスキップ
        if "カテゴリ定義" in raw_category or "category" in raw_lower:
            return ""

        # 不明なカテゴリは observation にフォールバック
        return "observation"

    # --------------------------------------------------------
    # プライベート: 正規表現フォールバックパーサー
    # --------------------------------------------------------

    def _parse_regex_fallback(self, content: str) -> List[Dict]:
        """正規表現ベースのフォールバックパーサー。

        Markdown 構造が壊れている場合でも、
        ファクトらしきテキストを正規表現で抽出する。

        Args:
            content: VERIFIED_FACTS.md の内容

        Returns:
            パース済みファクト辞書のリスト
        """
        facts: List[Dict] = []
        fact_counter = 0

        # パターン1: **[N%]** 形式（標準形式）
        pattern_standard = re.compile(
            r"\*\*\[(\d+)%\]\*\*\s+(.+?)(?:\n|$)"
        )
        for match in pattern_standard.finditer(content):
            confidence = float(match.group(1)) / 100.0
            content_text = match.group(2).strip()
            fact_counter += 1
            facts.append(make_fact(
                fact_id=f"fp_fb_{fact_counter:04d}",
                category="observation",  # フォールバック時はカテゴリ不明
                content=content_text,
                source="regex_fallback",
                confidence=min(confidence, 1.0),
            ))

        # パターン2: 箇条書き + 自然な文（構造化されていない場合）
        if not facts:
            pattern_bullet = re.compile(r"^[-*]\s+(.{20,})$", re.MULTILINE)
            for match in pattern_bullet.finditer(content):
                text = match.group(1).strip()
                # ヘッダーやメタ情報を除外
                if text.startswith("**") or "カテゴリ" in text or "最終更新" in text:
                    continue
                fact_counter += 1
                facts.append(make_fact(
                    fact_id=f"fp_fb_{fact_counter:04d}",
                    category="observation",
                    content=text,
                    source="regex_fallback",
                    confidence=0.5,
                ))

        return facts


# ============================================================
# モジュールレベルのシングルトン
# ============================================================

_default_parser: Optional[FactParser] = None


def get_default_parser() -> FactParser:
    """デフォルトの FactParser インスタンスを取得する。

    Returns:
        シングルトンの FactParser インスタンス
    """
    global _default_parser
    if _default_parser is None:
        _default_parser = FactParser()
    return _default_parser


# ============================================================
# テスト・デバッグ用エントリポイント
# ============================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("FactParser — VERIFIED_FACTS.md 構造化パーサー テスト")
    print("=" * 60)

    parser = FactParser()
    facts = parser.parse()

    print(f"\n📊 パース結果: {len(facts)} 件のファクト")

    stats = parser.get_stats()
    print(f"\n📈 統計情報:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print(f"\n📂 カテゴリ一覧: {parser.get_all_categories()}")

    if facts:
        print(f"\n📋 先頭3件:")
        for fact in facts[:3]:
            print(f"  [{fact['id']}] ({fact['category']}) {fact['content'][:80]}...")

        # 類似度検索テスト
        test_query = "テストカバレッジの改善"
        print(f"\n🔍 類似度検索テスト: \"{test_query}\"")
        related = parser.find_related_facts(test_query, top_k=3)
        for i, r in enumerate(related, 1):
            print(f"  {i}. [sim={r['similarity_score']:.4f}] {r['content'][:80]}...")

        # 矛盾チェックテスト
        test_proposal = "subprocess を直接使用してファイルを操作する"
        print(f"\n⚠️ 矛盾チェックテスト: \"{test_proposal}\"")
        contradictions = parser.check_contradiction(test_proposal)
        if contradictions:
            for c in contradictions:
                print(f"  ❌ {c['contradiction_reason']}")
        else:
            print("  ✅ 矛盾は検出されませんでした")

    print(f"\n{'=' * 60}")
    print("テスト完了")
    sys.exit(0)
