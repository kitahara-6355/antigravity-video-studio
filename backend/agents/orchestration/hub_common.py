"""
Orchestration Hub — 共通ユーティリティ

全Mixinモジュール (hub_session, hub_status, hub_batch, hub_gate, hub_reports) が
共通で使用するユーティリティ関数・定数・パス定義を集約する。

orchestrator.py のトップレベル定義をそのまま移植。
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --- パス定義 ---
_BASE_DIR = Path(__file__).resolve().parent
_MEMORY_DIR = _BASE_DIR.parent / "memory"
_PROJECT_ROOT = _BASE_DIR.parent.parent.parent  # orchestration → agents → backend → project root
INBOX_DIR = _PROJECT_ROOT / "Human01_Official Artifact" / "受信トレイ"

TASK_QUEUE_PATH = _writable_path("backend/agents/orchestration/task_queue.json")
OPUS_DIRECTIVE_PATH = _BASE_DIR / "opus_directive.json"
FLASH_REPORTS_PATH = _BASE_DIR / "flash_reports.jsonl"
MESSAGE_BOX_PATH = _writable_path("backend/agents/orchestration/message_box.jsonl")
PHASE_STATE_PATH = _MEMORY_DIR / "phase_state.json"
PHASE_GATES_PATH = _MEMORY_DIR / "phase_gates.json"
FLASH_SESSION_PATH = _writable_path("backend/agents/orchestration/flash_session.json")
USER_SCHEDULE_PATH = _BASE_DIR / "user_schedule.json"
DESIGN_STOCK_PATH = _BASE_DIR / "design_stock.json"
ETA_STORE_PATH = _BASE_DIR / "eta_tracker.json"
MODULE_INDEX_PATH = _writable_path("backend/agents/orchestration/module_index.json")


class OpusQuotaExceededException(Exception):
    """週の累積利用時間リミットを超過した場合の例外"""
    pass


# --- デフォルトプロファイル（user_schedule.json 読み込み失敗時のフォールバック） ---
_DEFAULT_FLASH_PROFILES = {
    "standard": {
        "batch_size": 6, "archive_batches": 30,
        "archive_hours": 5, "context_pct_per_batch": 4,
        "context_target_pct": 70, "context_warn_pct": 60,
    },
    "weekend": {
        "batch_size": 8, "archive_batches": 35,
        "archive_hours": 6, "context_pct_per_batch": 4,
        "context_target_pct": 70, "context_warn_pct": 60,
    },
    "night": {
        "batch_size": 10, "archive_batches": 40,
        "archive_hours": 8, "context_pct_per_batch": 4,
        "context_target_pct": 70, "context_warn_pct": 60,
    },
}


def _get_flash_profile() -> dict:
    """現在時刻と曜日からFlash動作モードを自動選択し、パラメータを返します。

    `user_schedule.json` の `flash_profiles` および `mode_schedule` を参照します。
    ファイルの読み込みに失敗した場合は、デフォルトの標準（STANDARD）プロファイルにフォールバックします。

    Returns:
        dict: 選択されたプロファイルの設定パラメータを格納した辞書。
    """
    try:
        with open(USER_SCHEDULE_PATH, "r", encoding="utf-8") as f:
            schedule = json.load(f)
    except (OSError, json.JSONDecodeError):
        schedule = {}

    profiles = schedule.get("flash_profiles", _DEFAULT_FLASH_PROFILES)
    mode_schedule = schedule.get("mode_schedule", {"night_start": "22:00", "night_end": "06:30"})

    now_jst = datetime.now(timezone.utc) + timedelta(hours=9)
    now_hhmm = now_jst.strftime("%H:%M")
    day_of_week = now_jst.weekday()  # 0=Mon, 5=Sat, 6=Sun

    # 休日（土日）は23:00、平日は22:00（mode_scheduleの設定値）から夜間モード
    if day_of_week >= 5:
        night_start = "23:00"
    else:
        night_start = mode_schedule.get("night_start", "22:00")
    night_end = mode_schedule.get("night_end", "06:30")

    # 夜間判定（日をまたぐ場合を考慮）
    if night_start > night_end:
        is_night = now_hhmm >= night_start or now_hhmm < night_end
    else:
        is_night = night_start <= now_hhmm < night_end

    if is_night:
        mode = "night"
    elif day_of_week >= 5:  # 土日
        mode = "weekend"
    else:
        mode = "standard"

    profile = profiles.get(mode, _DEFAULT_FLASH_PROFILES.get(mode, _DEFAULT_FLASH_PROFILES["standard"]))
    profile["mode"] = mode
    return profile


def _now_iso() -> str:
    """現在時刻（UTC）をISO 8601形式の文字列で取得します。

    Returns:
        str: ISO 8601形式（秒精度）の日時文字列。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_parse_iso(iso_str: Optional[str]) -> Optional[datetime]:
    """ISO 8601 形式の文字列を安全に datetime オブジェクトに変換します。

    Args:
        iso_str: ISO 8601 形式の日時文字列。

    Returns:
        変換された datetime オブジェクト。パース失敗時は None。
    """
    if not iso_str:
        return None
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        return datetime.fromisoformat(clean_str)
    except (ValueError, TypeError, AttributeError):
        return None


def _read_json(path: Path) -> dict:
    """JSONファイルを安全に読み込みます。

    Args:
        path (Path): 読み込み対象のファイルパス。

    Returns:
        dict: パースされたJSONデータ。ファイルが存在しないか、
              パースや読み込みに失敗した場合は空の辞書。
    """
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to read json from {path}: {e}")
        return {}


def _write_json(path: Path, data: dict) -> None:
    """JSONファイルをUTF-8でアトミックかつ安全に書き込みます（CP932汚染防止）。

    一時ファイルへ書き込んでから対象パスへアトミックにリプレースします。

    Args:
        path (Path): 書き込み対象のファイルパス。
        data (dict): 書き込むデータ。

    Raises:
        OSError: ファイルの書き込みやリプレースに失敗した場合。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp-{uuid.uuid4().hex}")
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)
    except OSError as e:
        logger.error(f"Failed to write json to {path} atomically: {e}")
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e


def _append_jsonl(path: Path, record: dict) -> None:
    """JSONLファイルにレコードを1行追記します（UTF-8安全、自動ローテーション対応）。

    Args:
        path (Path): 追記対象のファイルパス。
        record (dict): 追記するレコードの辞書。
    """
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    # 自動ローテーション: 1000行超で古い行をアーカイブ
    _rotate_jsonl_if_needed(path, max_lines=1000)


def _rotate_jsonl_if_needed(path: Path, max_lines: int = 1000) -> None:
    """JSONLファイルの行数が閾値を超えた場合に、古い行をアーカイブファイルへ退避します。

    退避された行は `*.archive.YYYYMMDD.jsonl` に保存され、元のファイルは直近の `max_lines` 行に切り詰められます。

    Args:
        path (Path): 対象のJSONLファイルパス。
        max_lines (int): 保持する最大行数。デフォルトは 1000。
    """
    try:
        records = _read_jsonl(path)
        if len(records) <= max_lines:
            return
        archive_path = path.with_suffix(f".archive.{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl")
        with open(archive_path, "a", encoding="utf-8", newline="\n") as f:
            for r in records[:-max_lines]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in records[-max_lines:]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"JSONL rotation failed: {e}")


def _read_jsonl(path: Path) -> list[dict]:
    """JSONLファイルを読み込み、パースされたレコードのリストを返します。

    空行は無視され、パースに失敗した不正な行はスキップされます。

    Args:
        path (Path): 読み込み対象のJSONLファイルパス。

    Returns:
        list[dict]: パースされたレコード辞書のリスト。ファイルが存在しない場合は空リスト。
    """
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


# --- Phase別タスク配分テンプレート ---
PHASE_TASK_TEMPLATES = {
    5: {"bug_hunter": 20, "test_weaver": 40, "refactor": 25, "edge_case": 10, "tdr_cleanup": 5},
    6: {"bug_hunter": 20, "test_weaver": 35, "edge_case": 30, "performance": 15},
    7: {"chaos": 30, "security": 25, "load_test": 25, "recovery": 20},
    8: {"docker": 25, "ci_cd": 25, "monitoring": 25, "data_infra": 25},
    9: {"docker": 25, "ci_cd": 25, "monitoring": 25, "data_infra": 25},
    10: {"docker": 25, "ci_cd": 25, "monitoring": 25, "data_infra": 25},
    11: {"agent": 40, "predictive_ai": 30, "learning_loop": 30},
    12: {"agent": 40, "predictive_ai": 30, "learning_loop": 30},
    13: {"agent": 40, "predictive_ai": 30, "learning_loop": 30},
    14: {"auth": 25, "api": 25, "plugin": 25, "marketplace": 25},
    15: {"auth": 25, "api": 25, "plugin": 25, "marketplace": 25},
    16: {"auth": 25, "api": 25, "plugin": 25, "marketplace": 25},
    17: {"self_improve": 30, "quality_ascend": 25, "design_auto": 25, "ecosystem": 20},
    18: {"self_improve": 30, "quality_ascend": 25, "design_auto": 25, "ecosystem": 20},
    19: {"self_improve": 30, "quality_ascend": 25, "design_auto": 25, "ecosystem": 20},
    20: {"self_improve": 30, "quality_ascend": 25, "design_auto": 25, "ecosystem": 20},
    # Phase 21-25: リソース耐久性・負債クリーンアップ・カバレッジ改善
    21: {"bug_hunter": 25, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 20},
    22: {"bug_hunter": 25, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 20},
    23: {"bug_hunter": 25, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 20},
    24: {"bug_hunter": 25, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 20},
    25: {"bug_hunter": 25, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 20},
    # Phase 26-30: 共通処理機構・God Class分割
    26: {"bug_hunter": 25, "test_weaver": 25, "refactor": 30, "tdr_cleanup": 10, "design_stock": 10},
    27: {"bug_hunter": 25, "test_weaver": 25, "refactor": 30, "tdr_cleanup": 10, "design_stock": 10},
    28: {"bug_hunter": 25, "test_weaver": 25, "refactor": 30, "tdr_cleanup": 10, "design_stock": 10},
    29: {"bug_hunter": 25, "test_weaver": 25, "refactor": 30, "tdr_cleanup": 10, "design_stock": 10},
    30: {"bug_hunter": 25, "test_weaver": 25, "refactor": 30, "tdr_cleanup": 10, "design_stock": 10},
    # Phase 31-35: カバレッジ改善・自己修復エンジン
    31: {"bug_hunter": 20, "test_weaver": 35, "refactor": 25, "tdr_cleanup": 10, "design_stock": 10},
    32: {"bug_hunter": 20, "test_weaver": 35, "refactor": 25, "tdr_cleanup": 10, "design_stock": 10},
    33: {"bug_hunter": 20, "test_weaver": 35, "refactor": 25, "tdr_cleanup": 10, "design_stock": 10},
    34: {"bug_hunter": 20, "test_weaver": 35, "refactor": 25, "tdr_cleanup": 10, "design_stock": 10},
    35: {"bug_hunter": 20, "test_weaver": 35, "refactor": 25, "tdr_cleanup": 10, "design_stock": 10},
    # Phase 36-40: 完全自律運用
    36: {"bug_hunter": 15, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 15, "design_stock": 15},
    37: {"bug_hunter": 15, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 15, "design_stock": 15},
    38: {"bug_hunter": 15, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 15, "design_stock": 15},
    39: {"bug_hunter": 15, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 15, "design_stock": 15},
    40: {"bug_hunter": 15, "test_weaver": 30, "refactor": 25, "tdr_cleanup": 15, "design_stock": 15},
}


# --- Phaseロードマップ定義 ---
PHASE_ROADMAP = {
    1: {"name": "基盤修復", "detail": "テスト基盤の確立、インフラの修復、および基本的な自動テストの導入。"},
    2: {"name": "コアパイプライン完成", "detail": "動画生成コア、字幕生成、音声マスタリング、YouTube投稿等のコア機能の統合。"},
    3: {"name": "UX実証", "detail": "プレビュー生成、ブラウザE2Eテスト、およびユーザーインタラクションの実証。"},
    4: {"name": "高度自律", "detail": "Orchestratorによるタスクの自動差し戻し、リトライ、および自動リカバリの構築。"},
    5: {"name": "卓越", "detail": "テストカバレッジ95%超の達成、レガシーコード清掃、およびエッジケース網羅。"},
    6: {"name": "高並列自律実行", "detail": "Gemini 3.5 Flash 30並列基盤を構築し、1500タスクを自動実行・検証する並列実行基盤の確立。"},
    7: {"name": "戦略的ガバナンス", "detail": "Claude Opus 4.6 による軌道修正ループの追加、および検証結果の自動フィードバック。"},
    8: {"name": "24時間ノンストップ保護壁", "detail": "Self-Healing 3.0による自動障害検知・プロセスのストール自動修復機構。"},
    9: {"name": "品質監査自動化", "detail": "NHK・YouTuber品質基準に基づく自動測定スコアラーおよび品質レビューサイクルの導入。"},
    10: {"name": "ユーザーシナリオE2E自動テスト", "detail": "180ゴールのUXストーリーE2E自動テストの完全実行とテストカバレッジ98%+の達成。"},
    11: {"name": "セマンティックデータベース & 憲法・マニュアル自動更新", "detail": "セマンティックストアによる憲法・マニュアル・ドキュメントの自動更新とAI適合チェック。"},
    12: {"name": "セキュリティ脆弱性・エッジケース自動修正ループ", "detail": "パスバリデーション（トラバーサル対策）やアトミック書込みなどのセキュリティ脆弱性・バグ自動修正。"},
    13: {"name": "パフォーマンス・リソース・クラウドコスト自動最適化", "detail": "NumPy等によるボトルネック自動解消、メモリ効率化、およびクラウドコスト自動最適化。"},
    14: {"name": "フィードバックループの動的パーソナライズ", "detail": "Soul Narrative 3.0によるパーソナライズされた動画・フィードバック生成。"},
    15: {"name": "障害自己復旧・システムダウンタイムゼロ化", "detail": "Self-Healing 3.0の拡張によるシステム停止時間の実質ゼロ化。"},
    16: {"name": "進化型テストハーネス", "detail": "テストコードの自律的生成、モックの自動追従、および回帰検証の完全自動化。"},
    17: {"name": "完全自律評議会", "detail": "Nexus-Council 3.0による複数AIエージェントの動的対話・方針決定。"},
    18: {"name": "クロスプラットフォーム展開 & 最新モデル", "detail": "最新LLMの動的統合とマルチプラットフォーム向け動画最適化。"},
    19: {"name": "本番環境安定稼働耐久試験", "detail": "本番環境での24H×7日間連続自律稼働と安定稼働率99.9%の実証。"},
    20: {"name": "究極の自律エコシステム", "detail": "Antigravity 2.0の正式リリースと自己修復・自己進化ループの完全統合。"},
    21: {"name": "リソース耐久性 & パッケージング", "detail": "長期リソース耐久性テスト（メモリ・クリーンアップ）および Buildozer/PyInstaller によるクライアント側パッケージングPoC。"},
    22: {"name": "ADK刷新自走ループ & 負債クリーンアップ", "detail": "ADK Bridge適用による自走エージェントの刷新、および技術負債（TDR）の完全クリーンアップ。"},
}
