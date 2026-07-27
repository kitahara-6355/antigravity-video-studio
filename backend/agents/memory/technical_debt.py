"""
Technical Debt Store — VF同型のJSON+Markdown二重管理

VFの VerifiedFactsStore と完全対称の設計:
- JSON (technical_debt_index.json) ← API (register / resolve / accept)
  ↓ 自動同期
- Markdown (TECHNICAL_DEBT_REGISTRY.md) ← 人間可読ビュー

ライフサイクル: open → fixed / accepted / wontfix
ラチェット: CRITICAL件数(open)は前回スナップショット以下であること
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
DEBT_DIR = Path(__file__).parent
DEBT_INDEX_PATH = DEBT_DIR / "technical_debt_index.json"
DEBT_MD_PATH = DEBT_DIR / "../../TECHNICAL_DEBT_REGISTRY.md"
DEBT_SNAPSHOT_DIR = DEBT_DIR / "../../technical_debt_snapshots"

VALID_CATEGORIES = [
    "CRITICAL_ROUTER",
    "CRITICAL_PHASE4",
    "IMPORTANT_SERVICE",
    "MINOR_INFRA",
    "ACCEPTED_SAFETY",
]

VALID_STATUSES = ["open", "fixed", "accepted", "wontfix"]

CATEGORY_LABELS = {
    "CRITICAL_ROUTER": "Router層 HTTPException捕捉バグ",
    "CRITICAL_PHASE4": "Phase 4直接干渉",
    "IMPORTANT_SERVICE": "Service/Engine層",
    "MINOR_INFRA": "インフラ層（ログ出力あり）",
    "ACCEPTED_SAFETY": "正当な安全ネット（修正不要）",
}


# ============================================================
# データ構造
# ============================================================

@dataclass
class TechnicalDebtEntry:
    """個々の技術負債エントリ"""
    debt_id: str                    # "TD-001"
    category: str                   # CRITICAL_ROUTER / CRITICAL_PHASE4 / ...
    file_path: str                  # "routers/preview.py"
    line_number: int                # 87
    pattern: str                    # "except Exception as e:"
    cause_pattern: str              # "DP-02"
    fix_pattern: str                # "except HTTPException: raise を追加"
    status: str                     # "open" / "fixed" / "accepted" / "wontfix"
    # ライフサイクル追跡
    registered_at: str              # ISO8601
    registered_by: str              # "sprint_4125"
    fixed_at: Optional[str] = None  # ISO8601
    fixed_by: Optional[str] = None  # "sprint_4125"
    fix_evidence: Optional[str] = None  # "pytest 3043 passed"
    # 関連情報
    related_test: Optional[str] = None  # "test_sc_07..."
    notes: str = ""
    tags: List[str] = field(default_factory=list)
    # L5-1: 最終検証日 — VF last_verified_at 対称
    last_verified_at: Optional[str] = None  # ISO8601
    # L5-5: 確信度 — 自動スキャン(0.7) vs 手動確認(1.0)
    confidence: float = 1.0
    # L6-1: SQALE修正コスト定量化 — 修正にかかる推定時間(分)
    estimated_fix_minutes: Optional[int] = None


@dataclass
class CausePattern:
    """負債発生要因パターン"""
    pattern_id: str     # "DP-01"
    name: str           # "汎用catch伝播"
    cause: str          # "1箇所の except Exception がコピペされる"
    prevention: str     # "テンプレートに guard を必須化"
    scope: str          # "全Router"


@dataclass
class DebtChangeRecord:
    """変更履歴レコード（不変ログ）— L2-3 changelog"""
    timestamp: str      # ISO8601
    action: str         # "registered" / "resolved" / "accepted" / "reopened"
    debt_id: str
    actor: str          # Sprint名
    old_status: str     # 変更前ステータス
    new_status: str     # 変更後ステータス
    detail: str = ""    # 証拠や理由


# ============================================================
# メインクラス
# ============================================================

class TechnicalDebtStore:
    """
    技術負債の永続化ストア

    VerifiedFactsStore と同型のAPI設計:
    - JSON インデックスによるCRUD
    - Markdown自動生成（人間可読ビュー）
    - ラチェット機構によるリグレッション防止
    """

    def __init__(self, debt_dir: Optional[Path] = None):
        self.debt_dir = debt_dir or DEBT_DIR
        self.index_path = debt_dir / "technical_debt_index.json" if debt_dir else DEBT_INDEX_PATH
        self.md_path = debt_dir / "../../TECHNICAL_DEBT_REGISTRY.md" if debt_dir else DEBT_MD_PATH
        self.snapshot_dir = debt_dir / "../../technical_debt_snapshots" if debt_dir else DEBT_SNAPSHOT_DIR
        self.entries: List[TechnicalDebtEntry] = []
        self.cause_patterns: List[CausePattern] = []
        self.changelog: List[DebtChangeRecord] = []
        self._load()

    # --------------------------------------------------------
    # CRUD
    # --------------------------------------------------------

    def register_debt(
        self,
        category: str,
        file_path: str,
        line_number: int,
        pattern: str,
        cause_pattern: str = "",
        fix_pattern: str = "",
        registered_by: str = "manual",
        notes: str = "",
        tags: Optional[List[str]] = None,
    ) -> TechnicalDebtEntry:
        """
        新しい技術負債を登録。

        Args:
            category: CRITICAL_ROUTER / CRITICAL_PHASE4 / IMPORTANT_SERVICE / MINOR_INFRA / ACCEPTED_SAFETY
            file_path: 対象ファイルパス
            line_number: 行番号
            pattern: コードパターン（例: "except Exception as e:"）
            cause_pattern: 発生要因パターンID（例: "DP-02"）
            fix_pattern: 修正パターン（例: "except HTTPException: raise を追加"）
            registered_by: 登録Sprint名
            notes: 自由記述
            tags: 分類タグ

        Returns:
            登録された TechnicalDebtEntry
        """
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category: {category}. Valid: {VALID_CATEGORIES}")

        # 重複チェック（ファイル+行番号で一意）
        for existing in self.entries:
            if existing.file_path == file_path and existing.line_number == line_number:
                logger.info(f"重複負債をスキップ: {file_path}:L{line_number}")
                return existing

        # ID自動生成
        max_id = 0
        for e in self.entries:
            try:
                num = int(e.debt_id.split("-")[1])
                if num > max_id:
                    max_id = num
            except (IndexError, ValueError):
                pass
        debt_id = f"TD-{max_id + 1:03d}"

        now = datetime.now().isoformat()
        entry = TechnicalDebtEntry(
            debt_id=debt_id,
            category=category,
            file_path=file_path,
            line_number=line_number,
            pattern=pattern,
            cause_pattern=cause_pattern,
            fix_pattern=fix_pattern,
            status="open",
            registered_at=now,
            registered_by=registered_by,
            notes=notes,
            tags=tags or [],
        )

        self.entries.append(entry)
        self._enforce_limits()  # L5-2: 上限制御
        self._add_changelog("registered", debt_id, registered_by, "", "open", pattern)
        self._save()
        logger.info(f"📋 技術負債登録: {debt_id} [{category}] {file_path}:L{line_number}")
        return entry

    def resolve_debt(
        self,
        debt_id: str,
        fixed_by: str,
        fix_evidence: str,
    ) -> Optional[TechnicalDebtEntry]:
        """
        技術負債を解消済みにする。

        Args:
            debt_id: 対象のID（例: "TD-074"）
            fixed_by: 修正Sprint名
            fix_evidence: 解消の証拠（例: "pytest 3043 passed / grep guard確認"）

        Returns:
            更新された TechnicalDebtEntry、見つからなければ None
        """
        for entry in self.entries:
            if entry.debt_id == debt_id:
                if entry.status == "fixed":
                    logger.warning(f"⚠️ {debt_id} は既に解消済み")
                    return entry
                old_status = entry.status
                entry.status = "fixed"
                entry.fixed_at = datetime.now().isoformat()
                entry.fixed_by = fixed_by
                entry.fix_evidence = fix_evidence
                self._add_changelog("resolved", debt_id, fixed_by, old_status, "fixed", fix_evidence)
                self._save()
                logger.info(f"✅ 技術負債解消: {debt_id} by {fixed_by}")
                return entry
        logger.warning(f"⚠️ {debt_id} が見つかりません")
        return None

    def accept_debt(
        self,
        debt_id: str,
        reason: str,
    ) -> Optional[TechnicalDebtEntry]:
        """技術負債を許容済みにする（正当な安全ネット等）。"""
        for entry in self.entries:
            if entry.debt_id == debt_id:
                old_status = entry.status
                entry.status = "accepted"
                # P3: 既存notesを保全し、許容理由を追記
                now = datetime.now().isoformat()
                accept_record = f"[accepted {now[:10]}] {reason}"
                entry.notes = f"{entry.notes}\n{accept_record}".strip() if entry.notes else accept_record
                entry.fixed_at = now
                self._add_changelog("accepted", debt_id, "manual", old_status, "accepted", reason)
                self._save()
                logger.info(f"🔵 技術負債許容: {debt_id} - {reason}")
                return entry
        return None

    def reopen_debt(
        self,
        debt_id: str,
        reason: str,
    ) -> Optional[TechnicalDebtEntry]:
        """解消済み負債を再オープンする。旧修正情報はnotesに保全される。"""
        for entry in self.entries:
            if entry.debt_id == debt_id:
                # P5: 旧修正情報をnotesに保全してからリセット
                now = datetime.now().isoformat()
                history = (
                    f"[reopened {now[:10]}] {reason} "
                    f"(was fixed by {entry.fixed_by or '?'} at {(entry.fixed_at or '?')[:10]}, "
                    f"evidence: {entry.fix_evidence or 'none'})"
                )
                entry.notes = f"{entry.notes}\n{history}".strip() if entry.notes else history
                self._add_changelog("reopened", debt_id, "manual", entry.status, "open", reason)
                entry.status = "open"
                entry.fixed_at = None
                entry.fixed_by = None
                entry.fix_evidence = None
                self._save()
                logger.info(f"🔄 技術負債再オープン: {debt_id} - {reason}")
                return entry
        return None

    def get_entry(self, debt_id: str) -> Optional[TechnicalDebtEntry]:
        """IDで負債エントリを取得。"""
        for entry in self.entries:
            if entry.debt_id == debt_id:
                return entry
        return None

    def get_entries_by_file(self, file_path: str) -> List[TechnicalDebtEntry]:
        """ファイルパスに関連する負債を取得。"""
        return [e for e in self.entries if e.file_path == file_path]

    def get_entries_by_category(self, category: str) -> List[TechnicalDebtEntry]:
        """カテゴリ別に負債を取得。"""
        return [e for e in self.entries if e.category == category]

    def get_open_entries(self) -> List[TechnicalDebtEntry]:
        """未解消の負債を取得。"""
        return [e for e in self.entries if e.status == "open"]

    def get_critical_open_count(self) -> int:
        """未解消のCRITICAL件数を取得（ラチェット用）。"""
        return len([
            e for e in self.entries
            if e.status == "open" and e.category.startswith("CRITICAL")
        ])

    # --------------------------------------------------------
    # L5-1: verify_debt — 最終検証日の更新
    # --------------------------------------------------------

    def verify_debt(self, debt_id: str) -> Optional[TechnicalDebtEntry]:
        """負債エントリの存在を確認し、最終検証日を更新する。

        L3-1(滞留アラート)が「登録日からの経過」を測定するのに対し、
        本APIは「最後に人間がこの負債の存在を確認した日」を記録する。

        Args:
            debt_id: 対象のID

        Returns:
            更新された TechnicalDebtEntry、見つからなければ None
        """
        entry = self.get_entry(debt_id)
        if entry:
            entry.last_verified_at = datetime.now().isoformat()
            self._add_changelog("verified", debt_id, "manual", entry.status, entry.status, "manual verification")
            self._save()
            logger.info(f"🔍 技術負債検証: {debt_id} last_verified_at 更新")
        return entry

    # --------------------------------------------------------
    # L5-4: get_contradictions — 矛盾検出
    # --------------------------------------------------------

    def get_contradictions(self) -> List[Dict]:
        """同一(file_path, line_number)で異なるカテゴリまたはステータスのエントリを検出する。

        VFの get_contradictions() と対称の設計。

        Returns:
            矛盾のリスト。各要素は {"location", "entries", "reason"}
        """
        from collections import defaultdict
        location_map = defaultdict(list)
        for e in self.entries:
            key = (e.file_path, e.line_number)
            location_map[key].append(e)

        contradictions = []
        for (fp, ln), entries in location_map.items():
            if len(entries) <= 1:
                continue
            categories = set(e.category for e in entries)
            statuses = set(e.status for e in entries)
            reasons = []
            if len(categories) > 1:
                reasons.append(f"異なるカテゴリ: {categories}")
            if len(statuses) > 1:
                reasons.append(f"異なるステータス: {statuses}")
            if reasons:
                contradictions.append({
                    "location": f"{fp}:L{ln}",
                    "entries": [e.debt_id for e in entries],
                    "reason": "; ".join(reasons),
                })
        return contradictions

    # --------------------------------------------------------
    # L5-2: _enforce_limits — エントリ数上限制御
    # --------------------------------------------------------

    MAX_ENTRIES = 2000

    def _enforce_limits(self):
        """エントリ数が上限を超えた場合、最古のfixed/acceptedをアーカイブ削除する。

        VFの _enforce_limits() と対称の設計。
        """
        if len(self.entries) <= self.MAX_ENTRIES:
            return

        # fixed/accepted の古い順にソート
        archivable = [
            e for e in self.entries
            if e.status in ("fixed", "accepted", "wontfix")
        ]
        archivable.sort(key=lambda e: e.registered_at)

        remove_count = len(self.entries) - self.MAX_ENTRIES
        to_remove = set(e.debt_id for e in archivable[:remove_count])

        if to_remove:
            self.entries = [e for e in self.entries if e.debt_id not in to_remove]
            logger.info(f"📦 上限制御: {len(to_remove)}件のfixed/acceptedエントリをアーカイブ削除")

    # --------------------------------------------------------
    # L6-1: get_cost_summary — SQALE修正コスト定量化
    # --------------------------------------------------------

    def get_cost_summary(self) -> Dict:
        """カテゴリ別の修正コスト合計を算出する。

        SQALE (Software Quality Assessment based on Lifecycle Expectations) 準拠の
        定量的コスト分析。優先度判断の客観的根拠として使用。

        Returns:
            {"by_category": {...}, "total_minutes": int, "total_hours": float, "unestimated_count": int}
        """
        costs: Dict[str, int] = {}
        for e in self.entries:
            if e.status == "open" and e.estimated_fix_minutes:
                costs.setdefault(e.category, 0)
                costs[e.category] += e.estimated_fix_minutes
        return {
            "by_category": costs,
            "total_minutes": sum(costs.values()),
            "total_hours": round(sum(costs.values()) / 60, 1) if costs else 0.0,
            "unestimated_count": sum(
                1 for e in self.entries
                if e.status == "open" and not e.estimated_fix_minutes
            ),
        }

    # --------------------------------------------------------
    # L6-3: get_pattern_analysis — cause_pattern傾向分析
    # --------------------------------------------------------

    def get_pattern_analysis(self) -> Dict:
        """cause_pattern別の発生傾向分析。

        Fowler 4象限（意図的/無自覚×慎重/無謀）に相当する
        構造的パターンの繰り返し検出を行う。

        Returns:
            {"by_pattern": {...}, "recurring_patterns": {...}, "recommendation": str}
        """
        pattern_counts: Dict[str, Dict[str, int]] = {}
        for e in self.entries:
            if e.cause_pattern:
                pattern_counts.setdefault(e.cause_pattern, {"total": 0, "open": 0})
                pattern_counts[e.cause_pattern]["total"] += 1
                if e.status == "open":
                    pattern_counts[e.cause_pattern]["open"] += 1

        # 繰り返しパターンの検出（10回以上は構造的問題）
        recurring = {
            k: v for k, v in pattern_counts.items()
            if v["total"] >= 10
        }

        return {
            "by_pattern": pattern_counts,
            "recurring_patterns": recurring,
            "recommendation": (
                f"⚠️ {len(recurring)}個のパターンが繰り返し発生。根本原因の対処を推奨"
                if recurring else "✅ 繰り返しパターンなし"
            ),
        }

    # --------------------------------------------------------
    # サマリー（チャット開始時の軽量読み込み用）
    # --------------------------------------------------------

    def get_summary(self) -> Dict:
        """
        チャット開始時に読み込む軽量サマリー。

        VFのget_facts_for_context()に相当。
        """
        summary = {
            "total": len(self.entries),
            "by_status": {},
            "by_category": {},
            "critical_open": self.get_critical_open_count(),
            "last_updated": datetime.now().isoformat(),
        }

        for status in VALID_STATUSES:
            count = len([e for e in self.entries if e.status == status])
            if count > 0:
                summary["by_status"][status] = count

        for cat in VALID_CATEGORIES:
            entries = [e for e in self.entries if e.category == cat]
            if entries:
                open_count = len([e for e in entries if e.status == "open"])
                fixed_count = len([e for e in entries if e.status == "fixed"])
                summary["by_category"][cat] = {
                    "total": len(entries),
                    "open": open_count,
                    "fixed": fixed_count,
                }

        # L6-1: SQALE修正コストの概要
        cost = self.get_cost_summary()
        if cost["total_minutes"] > 0:
            summary["cost_hours"] = cost["total_hours"]
            summary["unestimated_count"] = cost["unestimated_count"]

        # L6-3: 繰り返しパターンの概要
        analysis = self.get_pattern_analysis()
        if analysis["recurring_patterns"]:
            summary["recurring_patterns"] = list(analysis["recurring_patterns"].keys())

        return summary

    # --------------------------------------------------------
    # L5-3: get_entries_for_context — トークン制限付き出力
    # --------------------------------------------------------

    def get_entries_for_context(self, max_entries: int = 20) -> List[TechnicalDebtEntry]:
        """コンテキスト注入用の軽量エントリリスト。

        VFの get_facts_for_context() と対称の設計。
        CRITICAL > IMPORTANT > MINORの優先度でフィルタリングし、
        max_entries件に制限する。

        Args:
            max_entries: 返却する最大エントリ数

        Returns:
            優先度順にソートされたopenエントリのリスト
        """
        priority_order = {
            "CRITICAL_ROUTER": 0,
            "CRITICAL_PHASE4": 1,
            "IMPORTANT_SERVICE": 2,
            "MINOR_INFRA": 3,
            "ACCEPTED_SAFETY": 4,
        }
        open_entries = [e for e in self.entries if e.status == "open"]
        open_entries.sort(key=lambda e: priority_order.get(e.category, 99))
        return open_entries[:max_entries]

    def get_context_for_file(self, file_path: str) -> str:
        """
        特定ファイルに関連する負債のコンテキスト文字列。
        エージェントのプロンプトに注入可能な形式。
        """
        entries = self.get_entries_by_file(file_path)
        if not entries:
            return ""

        lines = [f"## ⚠️ 技術負債: {file_path}", ""]
        for e in entries:
            status_icon = {"open": "🔴", "fixed": "✅", "accepted": "🔵", "wontfix": "⚪"}.get(e.status, "❓")
            lines.append(f"- {status_icon} {e.debt_id} L{e.line_number}: {e.pattern} [{e.status}]")
        return "\n".join(lines)

    # --------------------------------------------------------
    # スナップショット（ラチェット機構）
    # --------------------------------------------------------

    def create_snapshot(self, version: str) -> Path:
        """ラチェット用スナップショットを作成。"""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = self.snapshot_dir / f"tdr_v{version}.json"

        snapshot = {
            "version": version,
            "created_at": datetime.now().isoformat(),
            "summary": self.get_summary(),
            "critical_open": self.get_critical_open_count(),
        }

        with open(snapshot_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        logger.info(f"📸 TDRスナップショット作成: {snapshot_path.name}")
        return snapshot_path

    def get_latest_snapshot(self) -> Optional[Dict]:
        """最新のスナップショットを取得。"""
        if not self.snapshot_dir.exists():
            return None

        snapshots = sorted(self.snapshot_dir.glob("tdr_v*.json"))
        if not snapshots:
            return None

        with open(snapshots[-1], "r", encoding="utf-8") as f:
            return json.load(f)

    def check_ratchet(self) -> Dict:
        """
        ラチェットチェック: CRITICAL open件数が前回以下であること。

        Returns:
            {"passed": bool, "current": int, "previous": int, "delta": int}
        """
        current = self.get_critical_open_count()
        prev_snapshot = self.get_latest_snapshot()

        if prev_snapshot is None:
            return {"passed": True, "current": current, "previous": None, "delta": 0}

        previous = prev_snapshot.get("critical_open", 0)
        delta = current - previous
        passed = delta <= 0

        if not passed:
            logger.error(
                f"🚨 TDRラチェット違反: CRITICAL open {previous} → {current} (+{delta})"
            )

        return {"passed": passed, "current": current, "previous": previous, "delta": delta}

    # --------------------------------------------------------
    # 変更履歴 (L2-3 changelog)
    # --------------------------------------------------------

    def _add_changelog(
        self,
        action: str,
        debt_id: str,
        actor: str,
        old_status: str,
        new_status: str,
        detail: str = "",
    ):
        """変更履歴に不変レコードを追加。"""
        record = DebtChangeRecord(
            timestamp=datetime.now().isoformat(),
            action=action,
            debt_id=debt_id,
            actor=actor,
            old_status=old_status,
            new_status=new_status,
            detail=detail[:200],  # 長すぎる証拠を切り詰め
        )
        self.changelog.append(record)

    def get_changelog(self, debt_id: Optional[str] = None, limit: int = 50) -> List[DebtChangeRecord]:
        """変更履歴を取得。debt_id指定で特定エントリのみ。"""
        records = self.changelog
        if debt_id:
            records = [r for r in records if r.debt_id == debt_id]
        return records[-limit:]

    # --------------------------------------------------------
    # 永続化（VF同型）
    # --------------------------------------------------------

    def _load(self):
        """JSONインデックスからエントリを復元。スキーマ進化に安全対応(C1)。"""
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # C1: 新フィールド追加時の安全ガード — 未知フィールドは無視、欠損フィールドはdefaultで補完
                entry_fields = {f.name for f in TechnicalDebtEntry.__dataclass_fields__.values()}
                self.entries = []
                import dataclasses as _dc
                for entry_data in data.get("entries", []):
                    safe_data = {k: v for k, v in entry_data.items() if k in entry_fields}
                    # 欠損フィールドのdefault補完
                    for fname, fobj in TechnicalDebtEntry.__dataclass_fields__.items():
                        if fname not in safe_data:
                            if fobj.default is not _dc.MISSING:
                                safe_data[fname] = fobj.default
                            elif fobj.default_factory is not _dc.MISSING:
                                safe_data[fname] = fobj.default_factory()
                            # else: 必須フィールド欠損 → TechnicalDebtEntry()がTypeErrorで通知
                    self.entries.append(TechnicalDebtEntry(**safe_data))
                self.cause_patterns = [
                    CausePattern(**cp_data)
                    for cp_data in data.get("cause_patterns", [])
                ]
                # changelog復元
                self.changelog = [
                    DebtChangeRecord(**cr_data)
                    for cr_data in data.get("changelog", [])
                ]
                logger.info(f"📂 {len(self.entries)}件の技術負債を読み込み")
            except Exception as e:
                logger.error(f"技術負債JSON読み込みエラー: {e}")
                self.entries = []
        else:
            self.entries = []

    def _save(self):
        """JSON + Markdown の両方を保存。"""
        import os
        import sys
        if ("pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST")) and self.index_path == DEBT_INDEX_PATH:
            logger.info("🧪 Test environment detected. Skipping actual save in TechnicalDebtStore to prevent pollution.")
            return

        self.debt_dir.mkdir(parents=True, exist_ok=True)

        # L4-1: 原子的書き込み (tmp → rename)
        import os
        import tempfile

        # JSON インデックス
        try:
            payload = json.dumps(
                {
                    "version": "1.1",
                    "last_updated": datetime.now().isoformat(),
                    "entry_count": len(self.entries),
                    "entries": [asdict(e) for e in self.entries],
                    "cause_patterns": [asdict(cp) for cp in self.cause_patterns],
                    "changelog": [asdict(cr) for cr in self.changelog[-500:]],
                },
                ensure_ascii=False,
                indent=2,
            )
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(self.debt_dir), suffix=".tmp", prefix="tdr_"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_path, str(self.index_path))
            except Exception:
                # tmp残骸クリーンアップ
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise
        except Exception as e:
            logger.error(f"技術負債JSON保存エラー: {e}")

        # Markdown（人間可読ビュー）
        try:
            md_content = self._render_markdown()
            with open(self.md_path, "w", encoding="utf-8") as f:
                f.write(md_content)
        except Exception as e:
            logger.error(f"技術負債Markdown保存エラー: {e}")

    def _render_markdown(self) -> str:
        """Markdown形式でレンダリング（VFの_render_markdown同型）。"""
        now = datetime.now()
        summary = self.get_summary()
        open_count = summary["by_status"].get("open", 0)
        fixed_count = summary["by_status"].get("fixed", 0)

        lines = [
            "# Technical Debt Registry — Antigravity Pipeline",
            "",
            f"> **最終更新**: {now.strftime('%Y-%m-%d %H:%M')}",
            f"> **総エントリ数**: {len(self.entries)} (open: {open_count} / fixed: {fixed_count})",
            "> **管理方式**: JSON+Markdown二重管理（VF同型）。手動編集禁止。API経由で更新。",
            "> **更新ルール**: 新規 `except Exception` 追加時は `register_debt()` API経由で登録必須",
            "",
            "---",
            "",
        ]

        # カテゴリサマリーテーブル
        lines.extend([
            "## カテゴリ別サマリー",
            "",
            "| カテゴリ | 意味 | Total | Open | Fixed | Accepted |",
            "|:---|:---|:---:|:---:|:---:|:---:|",
        ])

        for cat in VALID_CATEGORIES:
            label = CATEGORY_LABELS.get(cat, cat)
            cat_entries = [e for e in self.entries if e.category == cat]
            total = len(cat_entries)
            open_c = len([e for e in cat_entries if e.status == "open"])
            fixed_c = len([e for e in cat_entries if e.status == "fixed"])
            accepted_c = len([e for e in cat_entries if e.status == "accepted"])
            if total > 0:
                lines.append(f"| {cat} | {label} | {total} | {open_c} | {fixed_c} | {accepted_c} |")

        lines.extend(["", "---", ""])

        # カテゴリ別詳細
        for cat in VALID_CATEGORIES:
            cat_entries = [e for e in self.entries if e.category == cat]
            if not cat_entries:
                continue

            label = CATEGORY_LABELS.get(cat, cat)
            open_c = len([e for e in cat_entries if e.status == "open"])
            fixed_c = len([e for e in cat_entries if e.status == "fixed"])

            lines.extend([
                f"## {cat}: {label} ({len(cat_entries)}件 / open:{open_c} fixed:{fixed_c})",
                "",
                "| ID | ファイル | 行 | ステータス | パターン | 修正パターン | 修正日 |",
                "|:--|:---|:---:|:---:|:---|:---|:---|",
            ])

            for e in sorted(cat_entries, key=lambda x: x.debt_id):
                status_icon = {"open": "🔴", "fixed": "✅", "accepted": "🔵", "wontfix": "⚪"}.get(e.status, "❓")
                fixed_date = e.fixed_at[:10] if e.fixed_at else "-"
                lines.append(
                    f"| {e.debt_id} | `{e.file_path}` | L{e.line_number} | {status_icon} {e.status} "
                    f"| `{e.pattern}` | {e.fix_pattern} | {fixed_date} |"
                )

            lines.extend(["", "---", ""])

        # 負債発生要因パターンカタログ
        if self.cause_patterns:
            lines.extend([
                "## 負債発生要因パターンカタログ",
                "",
                "| ID | パターン名 | 発生要因 | 防止策 | 影響範囲 |",
                "|:--|:---|:---|:---|:---|",
            ])
            for cp in self.cause_patterns:
                lines.append(f"| {cp.pattern_id} | **{cp.name}** | {cp.cause} | {cp.prevention} | {cp.scope} |")
            lines.extend(["", "---", ""])

        # 更新履歴（最新10件のchangelogをJSONから表示）
        lines.extend([
            "## 更新履歴",
            "",
            "> このファイルはJSON (`technical_debt_index.json`) から自動生成されています。",
            "> 手動編集禁止。`TechnicalDebtStore` API経由で更新してください。",
            "",
        ])

        return "\n".join(lines)

    # --------------------------------------------------------
    # 統計
    # --------------------------------------------------------

    def get_stats(self) -> Dict:
        """ストアの統計情報。"""
        return {
            "total_entries": len(self.entries),
            "by_status": {
                status: len([e for e in self.entries if e.status == status])
                for status in VALID_STATUSES
            },
            "by_category": {
                cat: len([e for e in self.entries if e.category == cat])
                for cat in VALID_CATEGORIES
            },
            "critical_open": self.get_critical_open_count(),
            "ratchet": self.check_ratchet(),
        }


# ============================================================
# シングルトンインスタンス
# ============================================================
technical_debt_store = TechnicalDebtStore()
