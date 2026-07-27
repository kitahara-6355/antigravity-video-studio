"""

Verified Facts Store — Claude Code Tier 3 メモリに相当



Claude Code の MEMORY.md レイヤーを Antigravity に移植。

- 人間が読める Markdown 形式で永続化

- 全エージェント（Council / ProductionPipeline）に「最優先コンテキスト」として注入

- DreamEngine が定期的に更新（Orient→Gather→Consolidate→Prune）

- 200行 / 25KB の上限を Claude Code 準拠で厳守



設計根拠:

    Claude Code では MEMORY.md を 200行以内に保ち、

    全セッション開始時にコンテキストとして読み込んでいた。

    Antigravity でもプロジェクトの「確定仕様」を Markdown で永続化し、

    Council / ProductionPipeline の両系統にプロンプト注入する。

"""



import json

import logging

import os

import re

import time

from contextlib import contextmanager

from pathlib import Path

from datetime import datetime, timedelta

from typing import List, Dict, Optional, Tuple

from dataclasses import dataclass, field, asdict



logger = logging.getLogger(__name__)



# ============================================================

# 定数（Claude Code 準拠）

# ============================================================

MAX_LINES = 200

MAX_SIZE_KB = 25

DEFAULT_STALE_DAYS = 30



# 2026-07-26: 保存先を環境変数で差し替え可能にした。
#
# テストがこのストアに書き込むと本番の VERIFIED_FACTS.md が汚染される。
# 2026-07-25 の調査時点で、記録されていた9件のうち8件が session-123 /
# session-adk-empty-res といったユニットテスト由来のIDだった。
# GEMINI.md はこのファイルを「セッション開始時に突合して現在地を導出する」
# ソースに指定しているため、AI の現在地認識そのものが汚染されていた。
#
# ANTIGRAVITY_VERIFIED_FACTS_DIR を設定すると保存先がそちらへ向く。
# テスト実行時は conftest が一時ディレクトリを指すよう設定する。
# 未設定時の挙動は従来どおり（後方互換）。
_facts_dir_override = os.environ.get("ANTIGRAVITY_VERIFIED_FACTS_DIR")
FACTS_DIR = Path(_facts_dir_override) if _facts_dir_override else Path(__file__).parent

FACTS_PATH = FACTS_DIR / "VERIFIED_FACTS.md"

FACTS_INDEX_PATH = FACTS_DIR / "verified_facts_index.json"





# ============================================================

# データ構造

# ============================================================



@dataclass

class VerifiedFact:

    """個々の検証済みファクト"""

    fact_id: str

    category: str           # "architecture", "preference", "specification", "lesson", "progress"

    content: str            # ファクトの内容

    evidence: str           # 裏付けとなる根拠

    created_at: str         # ISO8601

    last_verified_at: str   # 最後に検証された日時

    confidence: float = 1.0 # 0.0-1.0 確信度

    source: str = ""        # "dream", "manual", "pipeline", "council"

    tags: List[str] = field(default_factory=list)





# ============================================================

# メインクラス

# ============================================================



class VerifiedFactsStore:

    """

    検証済みファクトの永続化ストア



    Claude Code の Verified Facts レイヤーに相当。

    - Markdown + JSON インデックスの二重管理

    - Markdown: エージェントのコンテキスト注入用（人間可読）

    - JSON: プログラムからの CRUD 用

    - 自己修復・回復性（ファイルアトミック書き込み、Markdownからの復元、簡易排他ロック）を統合。

    """



    def __init__(self, facts_dir: Optional[Path] = None):

        self.facts_dir = facts_dir or FACTS_DIR

        self.facts_path = self.facts_dir / "VERIFIED_FACTS.md"

        self.index_path = self.facts_dir / "verified_facts_index.json"

        self.facts: List[VerifiedFact] = []

        with self._lock(timeout_secs=2.0):

            self._load_without_lock()



    # --------------------------------------------------------

    # 排他制御（ロック）

    # --------------------------------------------------------



    @contextmanager

    def _lock(self, timeout_secs: float = 5.0, check_interval: float = 0.05):

        """ディレクトリ作成のアトミック性を利用した簡易ファイルロック"""

        lock_dir = self.facts_dir / "verified_facts.lock"

        start_time = time.time()

        locked = False

        while time.time() - start_time < timeout_secs:

            try:

                lock_dir.mkdir(exist_ok=False)

                locked = True

                break

            except FileExistsError:

                time.sleep(check_interval)

            except OSError as e:

                logger.warning(f"ロックディレクトリ作成失敗: {e}", exc_info=True)

                time.sleep(check_interval)

        

        if not locked:

            logger.warning(f"ロックの取得にタイムアウトしました ({timeout_secs}秒)。ロックなしで処理を実行します。")

            

        try:

            yield

        finally:

            if locked:

                try:

                    lock_dir.rmdir()

                except OSError as e:

                    logger.error(f"ロックディレクトリの削除に失敗しました: {e}", exc_info=True)



    # --------------------------------------------------------

    # CRUD

    # --------------------------------------------------------



    def add_fact(

        self,

        category: str,

        content: str,

        evidence: str,

        source: str = "manual",

        confidence: float = 1.0,

        tags: Optional[List[str]] = None,

    ) -> VerifiedFact:

        """

        新しい検証済みファクトを追加。

        """

        # --- F-1: 空想リスク防止バリデーション ---
        if not evidence or len(evidence.strip()) < 10:
            raise ValueError(f"Evidence must be at least 10 characters (空エビデンス禁止): '{evidence}'")
        if confidence < 0.8:
            raise ValueError(f"Confidence {confidence} < 0.8 (低信頼度エントリ禁止)")
        
        dummy_patterns = ["No detailed", "Safety Fallback", "入力検証エラー", "ダミーエビデンス"]
        if any(p in evidence for p in dummy_patterns):
            raise ValueError(f"Dummy evidence pattern detected: '{evidence}' (ダミーデータ侵入禁止)")

        now = datetime.now().isoformat()

        fact_id = f"vf_{len(self.facts):04d}_{int(datetime.now().timestamp()) % 10000}"



        fact = VerifiedFact(

            fact_id=fact_id,

            category=category,

            content=content,

            evidence=evidence,

            created_at=now,

            last_verified_at=now,

            confidence=confidence,

            source=source,

            tags=tags or [],

        )



        with self._lock():

            self._load_without_lock()

            # 重複チェック（完全一致のみ）

            for existing in self.facts:

                if existing.content == content and existing.category == category:

                    logger.info(f"重複ファクトをスキップ: {content[:50]}...")

                    existing.last_verified_at = now

                    existing.confidence = max(existing.confidence, confidence)

                    self._save_without_lock()

                    return existing



            self.facts.append(fact)

            self._enforce_limits()

            self._save_without_lock()



        logger.info(f"✅ Verified Fact追加: [{category}] {content[:60]}...")

        return fact



    def get_facts_by_category(self, category: str) -> List[VerifiedFact]:

        """カテゴリ別にファクトを取得"""

        with self._lock():

            self._load_without_lock()

            return [f for f in self.facts if f.category == category]



    def get_facts_for_context(self, max_tokens: int = 2000) -> str:

        """

        エージェントのプロンプトに注入する Markdown 形式のコンテキスト。

        """

        with self._lock():

            self._load_without_lock()

            return self._get_facts_for_context_logic(max_tokens)



    def _get_facts_for_context_logic(self, max_tokens: int) -> str:

        if not self.facts:

            return ""



        lines = [

            "## 検証済みファクト（Verified Facts）",

            "",

            "> 以下は過去のセッションで確定した事実です。これらと矛盾する提案をしてはいけません。",

            "",

        ]



        # カテゴリ別にグループ化

        categories = {}

        for fact in sorted(self.facts, key=lambda f: f.confidence, reverse=True):

            cat = fact.category

            if cat not in categories:

                categories[cat] = []

            categories[cat].append(fact)



        category_labels = {

            "architecture": "### 🏗️ アーキテクチャ",

            "preference": "### 🎨 ユーザーの好み・こだわり",

            "specification": "### 📋 確定仕様",

            "lesson": "### 📝 学んだ教訓",

            "progress": "### 📈 進捗",

        }



        for cat, facts_list in categories.items():

            label = category_labels.get(cat, f"### {cat}")

            lines.append(label)

            for f in facts_list:

                confidence_marker = "✅" if f.confidence >= 0.8 else "⚠️"

                lines.append(f"- {confidence_marker} {f.content}")

            lines.append("")



        result = "\n".join(lines)



        # トークン上限の簡易チェック（4文字≒1トークン）

        estimated_tokens = len(result) // 4

        if estimated_tokens > max_tokens and self.facts:

            lowest = min(self.facts, key=lambda f: f.confidence)

            self.facts.remove(lowest)

            return self._get_facts_for_context_logic(max_tokens)



        return result



    def update_fact(self, fact_id: str, **kwargs) -> Optional[VerifiedFact]:

        """既存ファクトを更新"""

        with self._lock():

            self._load_without_lock()

            for fact in self.facts:

                if fact.fact_id == fact_id:

                    for key, value in kwargs.items():

                        if hasattr(fact, key):

                            setattr(fact, key, value)

                    fact.last_verified_at = datetime.now().isoformat()

                    self._save_without_lock()

                    return fact

            return None



    def remove_fact(self, fact_id: str) -> bool:

        """ファクトを削除"""

        with self._lock():

            self._load_without_lock()

            before = len(self.facts)

            self.facts = [f for f in self.facts if f.fact_id != fact_id]

            if len(self.facts) < before:

                self._save_without_lock()

                return True

            return False



    # --------------------------------------------------------

    # 矛盾検出（Claude Code の Consolidate フェーズ向け）

    # --------------------------------------------------------



    def _get_contradictions_without_lock(self) -> List[Tuple[VerifiedFact, VerifiedFact]]:

        contradictions = []

        for i, f1 in enumerate(self.facts):

            for f2 in self.facts[i + 1:]:

                if f1.category == f2.category:

                    # キーワード重複チェック

                    words1 = set(f1.content.lower().split())

                    words2 = set(f2.content.lower().split())

                    overlap = words1 & words2

                    # 共通キーワードが多いのに異なるファクト → 矛盾候補

                    if len(overlap) >= 3 and f1.content != f2.content:

                        contradictions.append((f1, f2))

        return contradictions



    def get_contradictions(self) -> List[Tuple[VerifiedFact, VerifiedFact]]:

        """

        矛盾する可能性のあるファクトペアを検出。

        """

        with self._lock():

            self._load_without_lock()

            return self._get_contradictions_without_lock()



    # --------------------------------------------------------

    # 古いファクトの整理

    # --------------------------------------------------------



    def prune_stale_facts(self, max_age_days: int = DEFAULT_STALE_DAYS) -> int:

        """

        指定日数以上検証されていないファクトを削除。

        """

        with self._lock():

            self._load_without_lock()

            cutoff = datetime.now() - timedelta(days=max_age_days)

            before = len(self.facts)



            self.facts = [

                f for f in self.facts

                if datetime.fromisoformat(f.last_verified_at) > cutoff

            ]



            removed = before - len(self.facts)

            if removed > 0:

                self._save_without_lock()

                logger.info(f"🧹 {removed}件の古いファクトをプルーニング")



            return removed



    # --------------------------------------------------------

    # 上限制御（Claude Code 準拠: 200行 / 25KB）

    # --------------------------------------------------------



    def _enforce_limits(self):

        """Claude Code 準拠の上限を強制"""

        # 行数上限チェック

        while len(self.facts) > 0:

            md_content = self._render_markdown()

            line_count = md_content.count("\n") + 1

            size_kb = len(md_content.encode("utf-8")) / 1024



            if line_count <= MAX_LINES and size_kb <= MAX_SIZE_KB:

                break



            # 最も古い & 低確信度のファクトを削除

            oldest = min(

                self.facts,

                key=lambda f: (f.confidence, f.last_verified_at),

            )

            self.facts.remove(oldest)

            logger.info(

                f"⚠️ 上限超過によりファクト削除: {oldest.content[:40]}... "

                f"(lines={line_count}, size={size_kb:.1f}KB)"

            )



    # --------------------------------------------------------

    # 永続化 & アトミック書き込み & 自己修復

    # --------------------------------------------------------



    def _save_atomic(self, file_path: Path, content: str):

        """一時ファイルに書き出してからアトミックに置換する"""

        file_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")

        try:

            with open(tmp_path, "w", encoding="utf-8") as f:

                f.write(content)

            # アトミック置換

            tmp_path.replace(file_path)

        except OSError as e:

            logger.error(f"ファイルアトミック書き込みに失敗しました ({file_path}): {e}", exc_info=True)

            if tmp_path.exists():

                try:

                    tmp_path.unlink()

                except OSError as unlink_err:

                    logger.warning(f"一時ファイルの削除に失敗しました ({tmp_path}): {unlink_err}", exc_info=True)

            raise e



    def _restore_from_markdown(self) -> bool:

        """

        Markdownファイル(facts_path)からデータをパースし、メモリ上のfactsを復元する。

        """

        if not self.facts_path.exists():

            return False



        try:

            with open(self.facts_path, "r", encoding="utf-8") as f:

                lines = f.readlines()

        except OSError as e:

            logger.error(f"Markdown読み込み失敗 ({self.facts_path}): {e}", exc_info=True)

            return False



        restored_facts = []

        current_category = None

        current_fact = None



        category_map = {

            "アーキテクチャ": "architecture",

            "ユーザーの好み・こだわり": "preference",

            "確定仕様": "specification",

            "学んだ教訓": "lesson",

            "進捗": "progress"

        }



        # 見出しパターン: ## 🏗️ アーキテクチャ or ## architecture など

        header_re = re.compile(r"^##\s+(?:[^\w\s]+\s*)?(.+)$")

        # ファクト項目: - **[100%]** Content

        fact_re = re.compile(r"^-\s+\*\*\[(\d+)%\]\*\*\s+(.+)$")

        # 根拠:   - 根拠: Evidence

        evidence_re = re.compile(r"^\s+-\s+根拠:\s*(.+)$")



        now = datetime.now().isoformat()



        for line in lines:

            line_str = line.strip("\r\n")

            # カテゴリの検出

            header_match = header_re.match(line_str)

            if header_match:

                raw_cat = header_match.group(1).strip()

                # 英語名やマッピングを適用

                mapped_cat = None

                for jp_name, en_name in category_map.items():

                    if jp_name in raw_cat:

                        mapped_cat = en_name

                        break

                if not mapped_cat:

                    # 英語のカテゴリ名が含まれているかチェック

                    for en_name in category_map.values():

                        if en_name in raw_cat.lower():

                            mapped_cat = en_name

                            break

                current_category = mapped_cat or raw_cat.lower()

                continue



            if not current_category:

                continue



            # ファクトの検出

            fact_match = fact_re.match(line_str)

            if fact_match:

                confidence = float(fact_match.group(1)) / 100.0

                content = fact_match.group(2).strip()

                fact_id = f"vf_{len(restored_facts):04d}_{int(datetime.now().timestamp()) % 10000}"

                current_fact = VerifiedFact(

                    fact_id=fact_id,

                    category=current_category,

                    content=content,

                    evidence="",

                    created_at=now,

                    last_verified_at=now,

                    confidence=confidence,

                    source="restored"

                )

                restored_facts.append(current_fact)

                continue



            # 根拠 of 検出

            evidence_match = evidence_re.match(line_str)

            if evidence_match and current_fact:

                current_fact.evidence = evidence_match.group(1).strip()



        if restored_facts:

            self.facts = restored_facts

            logger.info(f"Markdownから {len(self.facts)} 件のファクトを復元しました")

            return True

        return False



    def _load_without_lock(self):

        """ロックなしでの読み込み"""

        loaded = False

        if self.index_path.exists():

            try:

                with open(self.index_path, "r", encoding="utf-8") as f:

                    data = json.load(f)

                self.facts = [

                    VerifiedFact(**fact_data)

                    for fact_data in data.get("facts", [])

                ]

                logger.info(f"📂 {len(self.facts)}件のVerified Factsを読み込み")

                loaded = True

            except (OSError, json.JSONDecodeError) as e:

                logger.error(f"Verified Facts読み込みエラー: {e}。Markdownからの復元を試みます。", exc_info=True)

        

        if not loaded:

            if self._restore_from_markdown():

                try:

                    self._save_without_lock()

                except OSError as save_err:

                    logger.error(f"復元後の保存に失敗しました: {save_err}", exc_info=True)

            else:

                self.facts = []



    def _load(self):

        """JSON インデックスからファクトを復元"""

        with self._lock():

            self._load_without_lock()



    def _save_without_lock(self):

        """ロックなしでの保存 (アトミック書き込み)"""

        self.facts_dir.mkdir(parents=True, exist_ok=True)



        # JSON インデックス

        try:

            json_content = json.dumps(

                {

                    "version": "1.0",

                    "last_updated": datetime.now().isoformat(),

                    "fact_count": len(self.facts),

                    "facts": [asdict(f) for f in self.facts],

                },

                ensure_ascii=False,

                indent=2,

            )

            self._save_atomic(self.index_path, json_content)

        except OSError as e:

            logger.error(f"Verified Facts JSON保存エラー ({self.index_path}): {e}", exc_info=True)



        # Markdown（エージェント注入用）

        try:

            md_content = self._render_markdown()

            self._save_atomic(self.facts_path, md_content)

        except OSError as e:

            logger.error(f"Verified Facts Markdown保存エラー ({self.facts_path}): {e}", exc_info=True)



    def _save(self):

        """JSON インデックス + Markdown の両方を保存"""

        with self._lock():

            self._save_without_lock()



    # カテゴリの表示順序（VF.mdの表示順序を安定させる）

    CATEGORY_ORDER = [

        "architecture", "preference", "specification", "lesson", "progress",

    ]



    def _render_markdown(self) -> str:

        """Markdown 形式でレンダリング"""

        lines = [

            "# Verified Facts — Antigravity プロジェクト",

            "",

            f"> 最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",

            f"> ファクト数: {len(self.facts)}",

            "> カテゴリ: architecture / preference / specification / lesson / **progress**",

            "",

            "### カテゴリ定義",

            "",

            "| カテゴリ | 用途 | confidence |",

            "|:---|:---|:---:|",

            "| architecture | アーキテクチャの確定事実 | 0.8-1.0 |",

            "| preference | ユーザーの好み・こだわり | 0.9-1.0 |",

            "| specification | 確定した設計仕様 | 0.9-1.0 |",

            "| lesson | 開発で得た教訓 | 0.7-0.9 |",

            "| **progress** | **タスク完了の証拠付き記録** | **1.0** |",

            "",

            "> [!IMPORTANT]",

            "> **progressカテゴリ**: テスト結果やカバレッジ等の**検証可能な事実のみ**を記録する。",

            "> 計画・予定・状態は記録しない。チャット開始時にMASTER v3.6と突合して現在地を導出する。",

            "",

            "",

            "---",

            "",

        ]



        category_labels = {

            "architecture": "## 🏗️ アーキテクチャ",

            "preference": "## 🎨 ユーザーの好み・こだわり",

            "specification": "## 📋 確定仕様",

            "lesson": "## 📝 学んだ教訓",

            "progress": "## 📈 進捗",

        }



        # カテゴリ別にグループ化

        categories = {}

        for fact in self.facts:

            cat = fact.category

            if cat not in categories:

                categories[cat] = []

            categories[cat].append(fact)



        # CATEGORY_ORDERに従って表示（未知のカテゴリは末尾）

        ordered_cats = [c for c in self.CATEGORY_ORDER if c in categories]

        ordered_cats += [c for c in categories if c not in self.CATEGORY_ORDER]



        for cat in ordered_cats:

            facts_list = categories[cat]

            label = category_labels.get(cat, f"## {cat}")

            lines.append(label)

            lines.append("")

            for f in sorted(facts_list, key=lambda x: x.confidence, reverse=True):

                confidence_pct = int(f.confidence * 100)

                lines.append(f"- **[{confidence_pct}%]** {f.content}")

                if f.evidence:

                    # F-07: 複数行evidenceを1行に正規化（mdインデント崩れ防止）

                    normalized = f.evidence.replace("\r\n", " / ").replace("\n", " / ")

                    lines.append(f"  - 根拠: {normalized}")

            lines.append("")



        return "\n".join(lines)



    # --------------------------------------------------------

    # 統計

    # --------------------------------------------------------



    def get_stats(self) -> Dict:

        """ストアの統計情報"""

        with self._lock():

            self._load_without_lock()

            md_content = self._render_markdown()

            return {

                "total_facts": len(self.facts),

                "by_category": {

                    cat: len([f for f in self.facts if f.category == cat])

                    for cat in set(f.category for f in self.facts)

                },

                "avg_confidence": (

                    sum(f.confidence for f in self.facts) / len(self.facts)

                    if self.facts

                    else 0

                ),

                "markdown_lines": md_content.count("\n") + 1,

                "markdown_size_kb": round(len(md_content.encode("utf-8")) / 1024, 1),

                "contradictions": len(self._get_contradictions_without_lock()),

            }





# ============================================================

# シングルトンインスタンス

# ============================================================

verified_facts_store = VerifiedFactsStore()

