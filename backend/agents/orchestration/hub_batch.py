"""BatchMixin – バッチ生成・タスク割当に関するメソッド群.

orchestrator.py から抽出された Mixin クラス。
HubOrchestrator が多重継承することで利用される。
"""

import json
import uuid
import random
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from .hub_common import (
    logger, _now_iso, _append_jsonl, _read_jsonl,
    TASK_QUEUE_PATH, OPUS_DIRECTIVE_PATH, FLASH_REPORTS_PATH,
    PHASE_STATE_PATH, PHASE_GATES_PATH, DESIGN_STOCK_PATH, MODULE_INDEX_PATH,
    _BASE_DIR, _MEMORY_DIR, _PROJECT_ROOT,
    PHASE_TASK_TEMPLATES, _safe_parse_iso, INBOX_DIR, FLASH_SESSION_PATH
)
from .convergence_loop import ConvergenceLoop
from .atomic_io import FileLock, safe_read_json, atomic_write_json


class BatchMixin:
    '''バッチ生成・タスク割当のMixin'''

    def _load_coverage_data(self) -> dict:
        """coverage.json からモジュールのカバレッジデータをロードする。"""
        cov_path = _PROJECT_ROOT / "coverage.json"
        if cov_path.exists():
            try:
                return safe_read_json(str(cov_path), {})
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load coverage.json: {e}")
        return {}

    def _is_module_eligible(self, group: str, module: str, 
                            coverage_data: dict, open_tdr_files: set) -> bool:
        """モジュールが指定グループのタスクアサインに適格であるかを静的に判定する。"""
        # test_weaver: カバレッジ100%のモジュールはアサインしない
        if group == "test_weaver":
            if coverage_data:
                key_with_backend = f"backend/{module}"
                files_data = coverage_data.get("files", {})
                
                mod_cov = None
                for k, v in files_data.items():
                    if k == key_with_backend or k == module or k.endswith(module):
                        mod_cov = v
                        break
                
                if mod_cov:
                    summary = mod_cov.get("summary", {})
                    percent = summary.get("percent_covered", 0.0)
                    missing = mod_cov.get("missing_lines", [])
                    if percent >= 100.0 or len(missing) == 0:
                        return False

        # tdr_cleanup: 未解消のTDRエントリが存在しないモジュールはアサインしない
        elif group == "tdr_cleanup":
            if open_tdr_files:
                is_tdr_file = any(
                    module in fp 
                    or fp in module 
                    or Path(fp).name == Path(module).name
                    for fp in open_tdr_files
                )
                if not is_tdr_file:
                    return False

        # bug_hunter: except Exceptionが0件かつ直近2回連続成功済みのモジュールはスキップ
        # (提案A-1: bug_hunter空振り46%の構造的削減)
        elif group == "bug_hunter":
            mod_path = _PROJECT_ROOT / "backend" / module
            if mod_path.exists():
                try:
                    source = mod_path.read_text(encoding="utf-8")
                    except_count = sum(1 for line in source.splitlines()
                                       if "except Exception" in line)
                    if except_count == 0:
                        # except Exceptionが0の場合、直近のmiss_countsも確認
                        # miss_countsが0 = 直近のアサインで空振りなし
                        # → そのモジュールはbug_hunterの改善余地が低い
                        miss_counts = getattr(self, '_current_miss_counts', {})
                        if miss_counts.get(module, 0) == 0:
                            return False
                except OSError:
                    pass  # ファイル読み取り失敗時はフォールバックで適格とみなす

        return True

    def _empty_queue(self) -> dict:
        return {
            "schema_version": "1.0",
            "current_batch_id": None,
            "generated_at": _now_iso(),
            "phase": 5,
            "milestone": "M5.1",
            "tasks": [],
            "blacklisted_modules": [],
            "batch_config": {
                "max_parallel": 30,
                "groups": {}
            }
        }

    def _empty_directive(self) -> dict:
        return {
            "directive_id": None,
            "issued_at": None,
            "issued_by": None,
            "priorities": {},
            "phase_advance": False,
            "focus_modules": [],
            "blacklist_override": [],
            "resume": True,
            "notes": ""
        }

    def _get_module_miss_counts(self) -> dict:
        """flash_reports.jsonl を読み、各モジュールの直近の連続空結果回数を返す。

        各モジュールの最新3件のアサインメントを調べ、result.changed_files が
        空（長さ0）または result が None/空のタスクを「ミス」としてカウントする。
        リカバリを可能にするため、直近3件のみを評価する。

        Returns:
            dict[str, int]: {module_path: consecutive_miss_count}
        """
        reports = _read_jsonl(FLASH_REPORTS_PATH)

        # Collect the last N assignments per module (most recent first)
        module_history: dict[str, list[bool]] = {}  # True = miss, False = hit
        for report in reports:
            for task in report.get("tasks", []):
                mod = task.get("target_module")
                if not mod:
                    continue
                result = task.get("result")
                # Determine if this assignment produced file changes
                if not result or not isinstance(result, dict):
                    is_miss = True
                else:
                    changed = result.get("changed_files", [])
                    is_miss = len(changed) == 0
                if mod not in module_history:
                    module_history[mod] = []
                module_history[mod].append(is_miss)

        # Count consecutive misses from the most recent assignment backwards
        miss_counts: dict[str, int] = {}
        for mod, history in module_history.items():
            # Only look at the last 3 assignments
            recent = history[-3:]
            consecutive = 0
            for is_miss in reversed(recent):
                if is_miss:
                    consecutive += 1
                else:
                    break
            if consecutive > 0:
                miss_counts[mod] = consecutive

        return miss_counts

    def auto_heal_stagnation(self, reason: str) -> None:
        """停滞検知時に自動でDirectiveを更新し、スタックしているモジュールを一時除外する（DS-037統合）"""
        if not PHASE_STATE_PATH.exists():
            return
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        blacklisted = state.get("blacklisted_modules", [])
        
        miss_counts = self._get_module_miss_counts()
        healed_count = 0
        auto_expiry = state.get("auto_blacklist_expiry", {})
        
        for mod, c in miss_counts.items():
            if c >= 2:
                if mod not in blacklisted:
                    blacklisted.append(mod)
                    auto_expiry[mod] = 5  # 5バッチ
                    healed_count += 1
                    
        if healed_count > 0:
            state["blacklisted_modules"] = blacklisted
            state["auto_blacklist_expiry"] = auto_expiry
            atomic_write_json(str(PHASE_STATE_PATH), state)
            logger.info(f"[LoopDetector] 自律修復: {healed_count}件の停滞モジュールを一時ブラックリストへ退避")

    def _create_random_tasks(self, batch_id: str, phase: int, remaining_slots: int,
                             priorities: dict, available_modules: list,
                             miss_counts: Optional[dict] = None,
                             skipped_modules: Optional[set] = None) -> tuple[list[dict], set[str]]:
        """残りスロット数と優先度、利用可能なモジュールに基づいてランダム割当タスクを生成する"""
        # 【S1-3】miss_countsは_generate_batchから引数で受け取る（二重スキャン防止）
        if miss_counts is None:
            miss_counts = self._get_module_miss_counts()
        
        # 事前アサイン前診断用データのロード
        coverage_data = self._load_coverage_data()
        open_tdr_files = set()
        try:
            tdr_data = safe_read_json(str(_MEMORY_DIR / "technical_debt_index.json"), {})
            for entry in tdr_data.get("entries", []):  # debts -> entries にバグ修正
                if entry.get("status") == "open":
                    fp = entry.get("file_path", "")
                    if fp:
                        open_tdr_files.add(fp)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load technical debt entries for assignment preflight: {e}")

        # 【S1-2】グループ別モジュールフィルタ拡充
        # 【施策1】タスク-モジュール適合性マトリクス: グループごとに適合するモジュールのみを割当
        GROUP_MODULE_FILTERS = {
            "thumbnail": [
                "thumbnail", "image", "preview", "hook_preview",
                "stage_bound_agent", "progressive_preview",
                "branding", "overlay", "compositor", "render",
                "visual", "canvas", "pillow", "photo",
            ],
            "tdr_cleanup": "__tdr_dynamic__",  # 動的フィルタ（TDR台帳連動）
            "coverage": "__coverage_dynamic__",  # カバレッジデータ連動
        }
        
        def _get_group_modules(group: str) -> list:
            """Group-specific module pool. Returns filtered list or full pool.
            
            【逓増型】coverage グループはカバレッジデータと連動し、
            未カバー行が実際に存在するモジュールのみを割当する。
            """
            filters = GROUP_MODULE_FILTERS.get(group)
            if not filters:
                return available_modules  # フィルタなし = 全モジュール
            # 【S1-2】tdr_cleanup: TDR台帳にエントリがあるモジュールのみ
            if filters == "__tdr_dynamic__":
                if open_tdr_files:
                    return [m for m in available_modules 
                            if any(t in m for t in open_tdr_files)]
                return available_modules
            # 【施策1】coverage: 未カバー行が存在するモジュールのみ
            if filters == "__coverage_dynamic__":
                if coverage_data:
                    uncovered = [m for m in available_modules
                                 if coverage_data.get(m, {}).get("missing_lines", 0) > 0]
                    return uncovered if uncovered else available_modules
                return available_modules
            return [
                m for m in available_modules
                if any(f in m.lower() for f in filters)
            ]
        
        # 【S1-1】グループ固有の具体的作業指示テンプレート（test_weaver抜本改善）
        GROUP_INSTRUCTIONS = {
            "thumbnail": (
                "対象モジュールのサムネイル生成/画像処理/プレビューロジックを改善せよ。"
                "具体的には: (1) 画像生成の品質向上、(2) エラーハンドリングの強化、"
                "(3) 解像度/アスペクト比/ファイルサイズの検証テスト追加。"
                "テスト追加必須。プロダクションコードの変更は3ファイル以内。"
            ),
            "test_weaver": (
                "【手順（必ず順番通りに実行）】\n"
                "1. まず `pytest --cov={target_module} --cov-report=term-missing --timeout=300 -q` を実行\n"
                "2. 出力の 'Missing' 列から未カバー行番号のリストを取得\n"
                "3. 対象モジュールの未カバー行をview_fileで実際に読み、ロジックを理解\n"
                "4. 未カバー行を通すユニットテストを設計（分岐条件・エラーパスに注目）\n"
                "5. テストファイルに実装し `pytest --timeout=300` で全PASS確認\n"
                "6. `pytest --cov={target_module}` で対象モジュールのカバレッジが向上したことを確認\n\n"
                "⚠️ プロダクションコードの変更禁止（L1）。テストコードのみ追加すること。\n"
                "⚠️ 未カバー行が0の場合: エッジケーステスト（境界値、None入力、空リスト、"
                "巨大入力、不正型）を追加し、changed_filesにテストファイルパスを記録すること。"
            ),
            "bug_hunter": (
                "【手順（必ず順番通りに実行）】\n"
                "1. 対象モジュール1ファイルのみに集中し、`pytest --timeout=300 -q` を実行\n"
                "2. FAIL/Warning があれば原因を特定し修正\n"
                "3. FAIL がなければ、以下の優先順で1つだけ改善:\n"
                "   (a) `except Exception` → 具体的な例外型に置換\n"
                "   (b) 入力値バリデーションの追加\n"
                "   (c) エラーメッセージの具体化\n"
                "4. 改善に対するテストを1ファイルに追加\n"
                "5. `pytest --timeout=300` で全PASS確認\n\n"
                "⚠️ 変更はプロダクションコード1ファイル＋テスト1ファイルの計2ファイル以内。\n"
                "⚠️ 改善対象が見つからない場合は空PASSで終了（無理に変更しない）。"
            ),
            "refactor": (
                "対象モジュールの dead code 除去、命名改善、関数分割を実施せよ。"
                "機能変更禁止。pytest --timeout=300 で全テストPASS確認。カバレッジ非退行確認。"
                "変更は3ファイル以内（L2）。"
            ),
            "tdr_cleanup": (
                "backend/agents/memory/technical_debt_index.json を読み、"
                "対象モジュールに関連する CRITICAL/IMPORTANT の未解消エントリを1件選択して修正せよ。"
                "修正後 resolve_debt() で証拠を記録。変更は3ファイル以内（L2）。"
            ),
        }
        
        tasks = []
        assigned_modules = set()  # バッチ内の重複防止
        total_pct = sum(priorities.values())
        if total_pct == 0:
            return tasks, assigned_modules

        # 【施策A】飽和チェック: test_weaverは空PASS履歴のあるモジュールを除外
        # 【S1-3】miss_countsは引数から取得（_generate_batchで計算済み）
        redistribution = {}  # グループ別の振替スロット
        
        # 飽和チェックで除外されたグループのスロットを再配分
        adjusted_group_slots = {}
        for group, pct in priorities.items():
            count = max(1, round(remaining_slots * pct / total_pct))
            if group == "test_weaver":
                # 空PASS 2回以上のモジュールを除外したプールサイズを確認
                group_pool = [m for m in available_modules 
                              if miss_counts.get(m, 0) < 2]
                if not group_pool:
                    # 全モジュール飽和 → スロットを refactor と bug_hunter に分散振替
                    refactor_share = count // 2
                    hunter_share = count - refactor_share
                    redistribution["refactor"] = redistribution.get("refactor", 0) + refactor_share
                    redistribution["bug_hunter"] = redistribution.get("bug_hunter", 0) + hunter_share
                    adjusted_group_slots[group] = 0
                    print(f"[SaturationCheck] test_weaver全モジュール飽和: refactor+{refactor_share}, bug_hunter+{hunter_share}に分散振替")
                    continue
            adjusted_group_slots[group] = count
        
        # 振替分を加算
        for rg, rc in redistribution.items():
            adjusted_group_slots[rg] = adjusted_group_slots.get(rg, 0) + rc

        for group, count in adjusted_group_slots.items():
            if count <= 0:
                continue
            group_instruction = GROUP_INSTRUCTIONS.get(
                group,
                f"{group} タスクを実行せよ。テスト追加必須。変更は3ファイル以内。"
            )
            for i in range(count):
                task_id = f"T-{batch_id}-{group}-{i:03d}"
                level = "L1" if group in ("test_weaver", "doc", "edge_case") else "L2"
                
                # グループ別モジュールプールからユニークなモジュールを割当
                target_module = None
                group_modules = _get_group_modules(group)
                # group_aware_cooldown: bug_hunter以外のグループではクールダウンを無視
                # bug_hunterで空PASSしたモジュールでも、test_weaver/refactorでは利用可能
                cooldown_exempt_groups = {"test_weaver", "refactor", "tdr_cleanup", "design_stock"}
                if skipped_modules and group not in cooldown_exempt_groups:
                    group_modules = [m for m in group_modules if m not in skipped_modules]
                # 【施策A】test_weaverは飽和モジュールを除外
                if group == "test_weaver":
                    group_modules = [m for m in group_modules 
                                    if miss_counts.get(m, 0) < 2]
                
                # 【学習エンジン連携】グループ別最適モジュール推薦
                try:
                    from backend.agents.orchestration.learning_integration import suggest_module_for_group
                    suggested = suggest_module_for_group(
                        group, group_modules, exclude=assigned_modules
                    )
                    if suggested and suggested not in assigned_modules:
                        if self._is_module_eligible(group, suggested, coverage_data, open_tdr_files):
                            target_module = suggested
                            assigned_modules.add(suggested)
                except Exception as e:
                    logger.warning(f"Learning integration failed: {e}")
                
                # フォールバック: 学習エンジンが推薦しなかった場合
                if target_module is None:
                    for mod in group_modules:
                        if mod not in assigned_modules:
                            if self._is_module_eligible(group, mod, coverage_data, open_tdr_files):
                                target_module = mod
                                assigned_modules.add(mod)
                                break
                
                # 【S4-3】モジュール固有情報を含む具体的な作業指示を構築
                instruction = (
                    f"Phase {phase} / {group} タスク #{i+1}"
                    + (f" — 対象: {target_module}" if target_module else "")
                    + f"\n\n【作業指示】{group_instruction}"
                )
                # モジュール固有情報を付加（指示の具体性向上）
                if target_module:
                    enrichment = self._enrich_instruction(group, target_module, miss_counts)
                    if enrichment:
                        instruction += f"\n\n【モジュール固有情報】\n{enrichment}"
                
                tasks.append({
                    "id": task_id,
                    "group": group,
                    "level": level,
                    "target_module": target_module,
                    "instruction": instruction,
                    "status": "pending",
                    "assigned_agent": None,
                    "result": None,
                    "created_at": _now_iso(),
                    "retry_count": 0,  # satisfies: REQ-CONV-02
                })
        return tasks, assigned_modules

    def _enrich_instruction(self, group: str, module: str, 
                            miss_counts: dict) -> Optional[str]:
        """【S4-3】モジュール固有の文脈情報を生成し、タスク指示を強化する。
        
        【C-1拡張】モジュールの現状分析結果を付加し、
        Flashが具体的な改善ポイントを把握できるようにする。
        """
        try:
            parts = []
            
            # === 全グループ共通: モジュール状態分析 ===
            mod_path = _PROJECT_ROOT / "backend" / module
            if mod_path.exists():
                try:
                    source = mod_path.read_text(encoding="utf-8")
                    lines = source.splitlines()
                    line_count = len(lines)
                    
                    # except Exception のカウント
                    except_count = sum(1 for l in lines if "except Exception" in l)
                    
                    # 関数定義数
                    func_count = sum(1 for l in lines if l.strip().startswith("def "))
                    
                    # docstring率（def行の次にdocstringがあるか）
                    doc_count = 0
                    for idx, l in enumerate(lines):
                        if l.strip().startswith("def ") and idx + 1 < len(lines):
                            next_stripped = lines[idx + 1].strip()
                            if next_stripped.startswith('"""') or next_stripped.startswith("'''"):
                                doc_count += 1
                    doc_rate = (doc_count / func_count * 100) if func_count > 0 else 0
                    
                    # 基本情報
                    parts.append(f"📊 モジュール分析: {line_count}行, {func_count}関数, "
                                f"except Exception: {except_count}箇所, docstring率: {doc_rate:.0f}%")
                    
                    # グループ別の具体的改善ポイント提案
                    if group == "bug_hunter" and except_count > 0:
                        parts.append(f"🎯 改善ポイント: except Exception が {except_count}箇所あります。"
                                    "具体的な例外型に置換してください。")
                    elif group == "test_weaver":
                        parts.append(f"🎯 改善ポイント: {func_count}関数のうち未テストの関数を特定し、"
                                    "ユニットテストを追加してください。")
                    elif group == "refactor":
                        if line_count > 300:
                            parts.append(f"🎯 改善ポイント: {line_count}行の大規模モジュールです。"
                                        "関数分割やdead code除去を検討してください。")
                        if doc_rate < 50:
                            parts.append(f"🎯 改善ポイント: docstring率が{doc_rate:.0f}%と低いです。"
                                        "主要関数にdocstringを追加してください。")
                    elif group == "tdr_cleanup" and except_count > 0:
                        parts.append(f"🎯 改善ポイント: except Exception {except_count}箇所は"
                                    "技術負債の典型パターンです。具体的な例外型に置換してください。")
                except (OSError, UnicodeDecodeError) as e:
                    logger.debug(f"Failed to analyze module: {e}")
            
            # === グループ固有の文脈情報 ===
            if group == "test_weaver":
                mc = miss_counts.get(module, 0)
                if mc > 0:
                    parts.append(f"⚠️ このモジュールは直近{mc}回連続で空PASSです。"
                                 "未カバー行が本当に存在するか慎重に確認してください。")
                    
            elif group == "tdr_cleanup":
                try:
                    tdr_data = safe_read_json(str(_MEMORY_DIR / "technical_debt_index.json"), {})
                    for entry in tdr_data.get("debts", []):
                        if entry.get("status") != "resolved" and module in entry.get("file_path", ""):
                            parts.append(f"TDRエントリ: [{entry.get('category', '?')}] "
                                        f"{entry.get('pattern', '不明')}")
                            break
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load technical debt entries for enrichment: {e}")
                    
            elif group == "bug_hunter":
                # 直近バッチでの同モジュール失敗情報
                try:
                    reports = _read_jsonl(FLASH_REPORTS_PATH)
                    for report in reports[-3:]:
                        for task in report.get("tasks", []):
                            if (task.get("target_module") == module and 
                                task.get("status") == "fail"):
                                err = ""
                                if isinstance(task.get("result"), dict):
                                    err = task["result"].get("error", "")[:150]
                                if err:
                                    parts.append(f"直近の失敗: {err}")
                                break
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to load flash reports for bug_hunter enrichment: {e}")
            
            return "\n".join(parts) if parts else None
        except Exception as e:
            logger.warning(f"Unexpected error in _enrich_instruction: {e}")
            return None

    def _adjust_priorities_by_hit_rate(self, priorities: dict) -> dict:
        """【施策C】直近3バッチのグループ別有効打率を算出し、低打率グループの配分を自動削減する。"""
        reports = _read_jsonl(FLASH_REPORTS_PATH)
        if len(reports) < 3:
            return priorities  # データ不足時はそのまま
        
        recent = reports[-3:]
        group_stats = {}  # {group: {hits: N, total: N}}
        for report in recent:
            for task in report.get("tasks", []):
                g = task.get("group", "unknown")
                if g not in group_stats:
                    group_stats[g] = {"hits": 0, "total": 0}
                group_stats[g]["total"] += 1
                result = task.get("result")
                status = task.get("status", "")
                # 有効判定: changed_files あり、または pass/fail（skipのみ無効）
                has_changes = result and isinstance(result, dict) and len(result.get("changed_files", [])) > 0
                is_effective = has_changes or status in ("pass", "fail")
                if is_effective:
                    group_stats[g]["hits"] += 1
        
        adjusted = dict(priorities)
        surplus = 0
        for group, pct in priorities.items():
            stats = group_stats.get(group)
            if stats and stats["total"] >= 3:
                hit_rate = stats["hits"] / stats["total"] * 100
                if hit_rate < 50:
                    new_pct = max(5, pct // 2)  # 最低5%は維持
                    surplus += pct - new_pct
                    adjusted[group] = new_pct
                    print(f"[HitRateFeedback] {group} 有効打率 {hit_rate:.0f}% → 配分 {pct}%→{new_pct}%")
        
        if surplus > 0:
            # 有効打率が最も高いグループに余剰を配分
            best_group = None
            best_rate = -1
            for g, s in group_stats.items():
                if g in adjusted and s["total"] >= 2:
                    rate = s["hits"] / s["total"]
                    if rate > best_rate:
                        best_rate = rate
                        best_group = g
            if best_group:
                adjusted[best_group] = adjusted.get(best_group, 0) + surplus
                print(f"[HitRateFeedback] 余剰 {surplus}% を {best_group} に再配分")
        
        return adjusted

    def _safe_instrument(self, name: str, func, *args, **kwargs) -> None:
        """【S2-3】自動計装を安全に実行し、連続失敗を検知・通知する。"""
        try:
            func(*args, **kwargs)
            self._instrument_fail_counts.pop(name, None)  # 成功時カウンタリセット
        except Exception as e:
            count = self._instrument_fail_counts.get(name, 0) + 1
            self._instrument_fail_counts[name] = count
            logger.warning(f"[Instrument] {name} failed ({count}回目): {e}")
            if count >= 3:
                logger.error(f"[Instrument] {name} が{count}回連続失敗: {e}")
                try:
                    self.send_message("flash", "opus",
                        f"⚠️ 自動計装 {name} が{count}回連続失敗: {str(e)[:100]}",
                        priority="urgent")
                except Exception as send_err:
                    logger.warning(f"Failed to send instrumentation failure message to Opus: {send_err}")

    def _infer_priorities_from_gate(self, phase: int) -> dict:
        """【S4-2】Phase Gate条件から必要なグループ配分を動的に逆算する。
        
        カバレッジが不足していればtest_weaverを増量、
        技術負債が多ければtdr_cleanupを増量する。
        Gate条件が全て達成されていればPhaseテンプレートにフォールバック。
        """
        gate = self.check_phase_gate(phase)
        conditions = gate.get("conditions", {})
        
        # Gate条件が全て達成されている → テンプレートで十分
        if gate.get("all_passed"):
            return PHASE_TASK_TEMPLATES.get(phase, PHASE_TASK_TEMPLATES[5])
        
        # 動的配分の基本構成
        priorities = {
            "bug_hunter": 20,
            "refactor": 15,
            "design_stock": 10,
        }
        remaining = 55  # 100 - 45(基本3グループ)
        
        # カバレッジ未達 → test_weaver を重点配分
        if not conditions.get("coverage_target", True):
            priorities["test_weaver"] = min(40, remaining)
            remaining -= priorities["test_weaver"]
            print(f"[DynamicGroup] カバレッジ未達: test_weaver={priorities['test_weaver']}%")
        else:
            priorities["test_weaver"] = 10
            remaining -= 10
        
        # 技術負債未解消 → tdr_cleanup を重点配分
        if not conditions.get("no_critical_debt", True):
            priorities["tdr_cleanup"] = min(25, remaining)
            remaining -= priorities["tdr_cleanup"]
            print(f"[DynamicGroup] 負債未解消: tdr_cleanup={priorities['tdr_cleanup']}%")
        else:
            priorities["tdr_cleanup"] = 5
            remaining -= 5
        
        # 残りがあればrefactorとbug_hunterに分散（一極集中防止）
        if remaining > 0:
            refactor_bonus = remaining // 2
            priorities["refactor"] += refactor_bonus
            priorities["bug_hunter"] += remaining - refactor_bonus
        
        return priorities

    def _auto_measure_coverage(self, state: dict) -> None:
        """【S2-1】カバレッジを自動測定し phase_state.metrics.coverage_pct を更新する。
        
        【D4追加】test_countも同時に計測（Phase 40のtest_count≥2500ゲート対応）。
        """
        import subprocess
        result = subprocess.run(
            ["python", "-m", "pytest", "--cov=backend", "--cov-report=json:coverage.json",
             "--timeout=120", "-q", "--no-header", "-x"],
            capture_output=True, text=True, timeout=240,
            cwd=str(_PROJECT_ROOT)
        )
        cov_file = _PROJECT_ROOT / "coverage.json"
        if cov_file.exists():
            cov_data = json.loads(cov_file.read_text(encoding="utf-8"))
            total_pct = cov_data.get("totals", {}).get("percent_covered", 0)
            state_fresh = safe_read_json(str(PHASE_STATE_PATH), {})
            if "metrics" not in state_fresh:
                state_fresh["metrics"] = {}
            state_fresh["metrics"]["coverage_pct"] = round(total_pct, 1)
            state_fresh["metrics"]["coverage_measured_at"] = _now_iso()
            
            # D4: test_count 自動計測（pytest --co -q で収集テスト数をカウント）
            try:
                tc_result = subprocess.run(
                    ["python", "-m", "pytest", "--co", "-q", "--no-header"],
                    capture_output=True, text=True, timeout=60,
                    cwd=str(_PROJECT_ROOT)
                )
                if tc_result.returncode == 0:
                    # "N tests collected" or "N items" パターンを検出
                    import re
                    lines = tc_result.stdout.strip().split("\n")
                    # 最後の行に "X tests/items" がある
                    for line in reversed(lines):
                        match = re.search(r"(\d+)\s+(?:test|item)", line)
                        if match:
                            state_fresh["metrics"]["test_count"] = int(match.group(1))
                            break
                    else:
                        # 行数カウント（各行が1テスト）
                        test_lines = [l for l in lines if "::" in l]
                        if test_lines:
                            state_fresh["metrics"]["test_count"] = len(test_lines)
            except (subprocess.SubprocessError, OSError, ValueError):
                pass  # test_count計測失敗は無視（coverage計測は成功している）
            
            atomic_write_json(str(PHASE_STATE_PATH), state_fresh)
            print(f"[CoverageAuto] カバレッジ自動測定: {total_pct:.1f}%, "
                  f"test_count: {state_fresh['metrics'].get('test_count', 'N/A')}")
            try:
                cov_file.unlink()  # 一時ファイル削除
            except OSError:
                pass

    def _auto_replenish_design_stock(self, phase: int) -> None:
        """【施策2】DS枯渇時の2段階補充: 設計書md → リトライ失敗 の優先順で補充する。
        
        従来はリトライ失敗のみから補充していたが、これでは「過去と同じ失敗を繰り返す」
        だけだった。設計書(ds_phase_N.md)のタスクグループ定義から新規タスクを生成する
        ことで、DS枯渇後もランダム割当への退行を防止する。
        """
        ds_data = safe_read_json(str(DESIGN_STOCK_PATH), {})
        items = ds_data.get("stock_items", [])
        pending = [i for i in items if i.get("status") == "pending"]
        target = ds_data.get("config", {}).get("target_stock_count", 14)

        if len(pending) >= target // 2:
            return  # 在庫十分

        # === Stage 1: 設計書mdからタスクを再生成（施策2の核心） ===
        new_items = self._replenish_from_design_stock_md(phase, items, target)
        
        # === Stage 1.5: カバレッジギャップ連動DS生成（弱点②修正） ===
        if len(new_items) < target // 2:
            gap_items = self._replenish_from_coverage_gaps(
                phase, items + new_items, target - len(new_items)
            )
            new_items.extend(gap_items)

        # === Stage 1.7: UXストーリーFAIL連動DS生成（新規） ===
        if len(new_items) < target // 2:
            ux_fail_items = self._replenish_from_ux_story_failures(
                phase, items + new_items, target - len(new_items)
            )
            new_items.extend(ux_fail_items)
        
        # === Stage 2: それでも不足する場合のみ、リトライ失敗から補充 ===
        if len(new_items) < target // 2:
            retry_items = self._replenish_from_failed_tasks(phase, items, target - len(new_items))
            new_items.extend(retry_items)

        if new_items:
            ds_data["stock_items"].extend(new_items)
            atomic_write_json(str(DESIGN_STOCK_PATH), ds_data)
            print(f"[DesignStock] {len(new_items)}件のDSを補充（設計書md + リトライ）")
        else:
            # DS枯渇フラグ: Opus介入トリガー（施策3）
            state = safe_read_json(str(PHASE_STATE_PATH), {})
            state["ds_exhausted"] = True
            state["ds_exhausted_at"] = _now_iso()
            atomic_write_json(str(PHASE_STATE_PATH), state)
            print(f"[DesignStock] ⚠️ DS完全枯渇 — Opus介入トリガー設定")

    def _replenish_from_design_stock_md(self, phase: int, existing_items: list,
                                         target_count: int) -> list:
        """設計書md (ds_phase_N.md) のタスクグループ定義から新規DSを生成する。
        
        設計書の「## 4. タスクグループ定義」セクションから
        「### group_name（配分: N%）」パターンを動的に抽出し、
        具体的指示テンプレートを含むDSを生成する。
        
        【脆弱性2修正】ハードコード5グループを廃止。Phase 35のconsensus_engine等も
        設計書に記載されていれば自動的にDS化される。
        """
        import re
        
        design_stock_dir = _PROJECT_ROOT / "backend" / "agents" / "orchestration" / "design_stock"
        md_file = design_stock_dir / f"ds_phase_{phase}.md"
        
        if not md_file.exists():
            return []
        
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            return []
        
        existing_ids = {i.get("id") for i in existing_items}
        existing_titles = {i.get("title", "").lower() for i in existing_items}
        new_items = []
        
        # 設計書mdからタスクグループを動的に抽出
        # 「## 4. タスクグループ定義」セクション以降のみを対象にする
        task_group_section_start = content.find("タスクグループ定義")
        if task_group_section_start >= 0:
            content = content[task_group_section_start:]
        
        # パターン: ### group_name（配分: N%） — 配分が必須のマッチ
        group_pattern = re.compile(
            r"^###\s+(\w+)（配分[:：]\s*(\d+)%）",
            re.MULTILINE
        )
        
        # グループごとのセクション内容を抽出
        matches = list(group_pattern.finditer(content))
        
        if not matches:
            # フォールバック: デフォルトグループ
            matches_fallback = ["test_weaver", "bug_hunter", "refactor", "coverage", "doc_gen"]
            for group in matches_fallback:
                ds_id = f"DS-MD-P{phase}-{group}-{uuid.uuid4().hex[:4]}"
                title = f"Phase {phase} / {group} — 設計書ベースタスク"
                if title.lower() in existing_titles:
                    continue
                new_items.append({
                    "id": ds_id,
                    "title": title,
                    "phase": phase,
                    "milestone": "",
                    "difficulty": "B",
                    "session_target": "flash",
                    "status": "pending",
                    "created_at": _now_iso(),
                    "last_activity": _now_iso(),
                    "description": (
                        f"ds_phase_{phase}.md の {group} セクションに記載された"
                        f"タスクグループ定義に基づくタスク。"
                        f"設計書を参照し、具体的な実装を行え。"
                    ),
                    "source_phase_task": f"design_stock_md_phase_{phase}",
                })
                if len(new_items) >= target_count:
                    break
        else:
            for i, match in enumerate(matches):
                group = match.group(1)
                
                # セクション内容を抽出（次のグループ見出しまで）
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
                section_content = content[start:end].strip()
                
                # 具体的指示テンプレートを抽出（``` ブロック内）
                template_match = re.search(r"```\n(.+?)```", section_content, re.DOTALL)
                template = template_match.group(1).strip() if template_match else ""
                
                # 対象モジュールを抽出（- **対象**: の後）
                target_match = re.search(r"\*\*対象\*\*[:：]\s*(.+)", section_content)
                target_modules = target_match.group(1).strip() if target_match else ""
                
                ds_id = f"DS-MD-P{phase}-{group}-{uuid.uuid4().hex[:4]}"
                title = f"Phase {phase} / {group} — 設計書ベースタスク"
                
                if title.lower() in existing_titles:
                    continue
                
                description = (
                    f"ds_phase_{phase}.md の {group} セクションに基づくタスク。\n"
                )
                if target_modules:
                    description += f"対象: {target_modules}\n"
                if template:
                    description += f"具体的指示:\n{template[:500]}"
                
                # C1/D2: Flash最適化テンプレートの自動付加
                optimization_hints = []
                if group in ("test_weaver", "coverage"):
                    optimization_hints.append(
                        "\n\n【parametrize活用】テスト関数には @pytest.mark.parametrize で"
                        "6-10ケース(正常系2+, 境界値2+, 異常系2+)を含めること。"
                    )
                if group in ("bug_hunter", "refactor"):
                    optimization_hints.append(
                        "\n\n【タイムアウト防止】1タスクで変更対象は3関数以内。"
                        "500行超モジュールは行範囲(L{start}-L{end})を明示すること。"
                    )
                optimization_hints.append(
                    "\n\n【TDR登録】新規except Exceptionを追加した場合は"
                    "register_debt()でACCEPTED_SAFETYとして登録すること。"
                )
                description += "".join(optimization_hints)
                
                new_items.append({
                    "id": ds_id,
                    "title": title,
                    "phase": phase,
                    "milestone": "",
                    "difficulty": "B",
                    "session_target": "flash",
                    "status": "pending",
                    "created_at": _now_iso(),
                    "last_activity": _now_iso(),
                    "description": description,
                    "source_phase_task": f"design_stock_md_phase_{phase}",
                })
                if len(new_items) >= target_count:
                    break
        
        if new_items:
            print(f"[DesignStock] 設計書mdから{len(new_items)}件の新規DSを生成（動的抽出）")
        return new_items

    def _replenish_from_coverage_gaps(self, phase: int, existing_items: list,
                                       target_count: int) -> list:
        """【弱点②修正】カバレッジギャップからデータ駆動でDSを自動生成する。
        
        coverage.jsonやmodule_indexから低カバレッジモジュールを特定し、
        具体的なテスト追加タスクを生成する。設計書mdの焼き直しではなく、
        実データに基づく「進化的DS」を投入する。
        
        段階的レベルアップ:
        - Level 1 (現在): 低カバレッジモジュールへのtest_weaverタスク生成
        - Level 2 (将来): 関数単位の未カバーブランチ特定
        - Level 3 (将来): ミューテーションテスト連動
        """
        new_items = []
        existing_titles = {i.get("title", "").lower() for i in existing_items}
        
        # module_indexから対象モジュールを取得
        module_index_path = _PROJECT_ROOT / "backend" / "agents" / "orchestration" / "module_index.json"
        module_index = safe_read_json(str(module_index_path), {})
        modules = module_index.get("modules", [])
        
        if not modules:
            return []
        
        # phase_stateからカバレッジ情報を取得
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        current_coverage = state.get("coverage_pct", 0)
        
        # ゲート目標カバレッジを取得
        gates_path = _PROJECT_ROOT / "backend" / "agents" / "memory" / "phase_gates.json"
        gates = safe_read_json(str(gates_path), {})
        phase_gate = gates.get(str(phase), gates.get(f"phase_{phase}", {}))
        target_coverage = phase_gate.get("min_coverage", current_coverage + 5)
        coverage_gap = target_coverage - current_coverage
        
        if coverage_gap <= 0:
            return []  # カバレッジ目標達成済み
        
        # BLモジュールを除外
        bl_modules = set(state.get("blacklisted_modules", []))
        
        # テスト対象として優先すべきモジュール: プロダクションコード（tests/を除外）
        candidate_modules = []
        for m in modules:
            mod_path = m if isinstance(m, str) else m.get("path", "")
            basename = mod_path.rsplit("/", 1)[-1] if "/" in mod_path else mod_path
            
            # テストファイル・設定ファイルを除外
            if any(x in mod_path for x in ["test_", "conftest", "__pycache__", "migration"]):
                continue
            if basename in bl_modules:
                continue
            
            candidate_modules.append(basename)
        
        if not candidate_modules:
            return []
        
        # カバレッジギャップに基づいてタスクを生成
        # test_weaverとcoverageの2グループで生成
        groups_for_gap = [
            ("test_weaver", "テストケースを追加してカバレッジを改善"),
            ("coverage", "未カバーブランチのテストを追加"),
        ]
        
        for mod in candidate_modules[:target_count * 2]:  # 候補を多めに
            for group, action in groups_for_gap:
                title = f"Phase {phase} / {group} — {mod} カバレッジ改善"
                if title.lower() in existing_titles:
                    continue
                
                ds_id = f"DS-COV-P{phase}-{group}-{uuid.uuid4().hex[:4]}"
                new_items.append({
                    "id": ds_id,
                    "title": title,
                    "phase": phase,
                    "milestone": "",
                    "difficulty": "B",
                    "session_target": "flash",
                    "status": "pending",
                    "created_at": _now_iso(),
                    "last_activity": _now_iso(),
                    "description": (
                        f"{mod} の{action}。\n"
                        f"現在のプロジェクトカバレッジ: {current_coverage:.1f}%\n"
                        f"Phase {phase} ゲート目標: {target_coverage:.1f}%\n"
                        f"ギャップ: {coverage_gap:.1f}ポイント\n"
                        f"具体的な指示: {mod} の未テスト関数・ブランチを特定し、"
                        f"テストを追加せよ。pytest全PASSを確認すること。"
                    ),
                    "source_phase_task": f"coverage_gap_phase_{phase}",
                })
                
                if len(new_items) >= target_count:
                    break
            if len(new_items) >= target_count:
                break
        
        if new_items:
            print(f"[DesignStock] カバレッジギャップから{len(new_items)}件 of 進化的DSを生成"
                  f"（目標: {current_coverage:.1f}% → {target_coverage:.1f}%）")
        return new_items

    def _replenish_from_ux_story_failures(self, phase: int, existing_items: list,
                                           target_count: int) -> list:
        """UXストーリーのFAIL項目（v5.0スナップショット等でpassed=False）からDSを生成。"""
        import os
        import glob
        existing_ids = {i.get("id") for i in existing_items}
        new_items = []
        
        # 最新のUXスナップショットファイルを検索
        snapshot_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "ux_verification", "snapshots")
        snapshot_files = sorted(glob.glob(os.path.join(snapshot_dir, "v*.json")))
        if not snapshot_files:
            return []
            
        latest_snapshot = snapshot_files[-1]
        try:
            with open(latest_snapshot, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
            
        stories = data.get("stories", {})
        for story_id, story in stories.items():
            story_title = story.get("title", story_id)
            for item in story.get("items", []):
                if item.get("passed") is False or item.get("passed") is None:
                    # IDの重複チェック
                    item_id = item.get("id")
                    ds_id = f"DS-UX-{story_id}-{item_id}"
                    if ds_id in existing_ids:
                        continue
                        
                    item_title = item.get("title", item_id)
                    desc = item.get("description", "")
                    
                    new_items.append({
                        "id": ds_id,
                        "scope": "test",
                        "title": f"UXストーリー検証: {story_title} - {item_title}",
                        "description": (
                            f"UX検証項目 '{story_title}' の '{item_title}' ({desc}) が現在不合格です。\n"
                            f"これをPASSさせるための機能実装および検証テスト（pytestによる検証など）を完了させてください。"
                        ),
                        "source_phase_task": f"ux_story_fail_phase_{phase}",
                    })
                    if len(new_items) >= target_count:
                        break
            if len(new_items) >= target_count:
                break
                
        if new_items:
            print(f"[DesignStock] UXストーリーFAILから{len(new_items)}件の進化的DSを生成")
        return new_items

    def _replenish_from_failed_tasks(self, phase: int, existing_items: list,
                                      target_count: int) -> list:
        """過去のバッチ失敗からリトライDSを生成する（従来のロジック）。"""
        reports = _read_jsonl(FLASH_REPORTS_PATH)
        existing_ids = {i.get("id") for i in existing_items}
        new_items = []

        for report in reports[-5:]:
            for task in report.get("tasks", []):
                if task.get("status") == "fail" and task.get("target_module"):
                    ds_id = f"DS-AUTO-{uuid.uuid4().hex[:6]}"
                    if ds_id in existing_ids:
                        continue
                    error_msg = ""
                    if isinstance(task.get("result"), dict):
                        error_msg = task["result"].get("error", "")[:200]
                    new_items.append({
                        "id": ds_id,
                        "title": f"リトライ: {task.get('group', '?')} - {task.get('target_module', '?')}",
                        "phase": phase,
                        "milestone": "",
                        "difficulty": "C",
                        "session_target": "flash",
                        "status": "pending",
                        "created_at": _now_iso(),
                        "last_activity": _now_iso(),
                        "description": (
                            f"バッチ {report.get('batch_id', '?')} で失敗した{task.get('group', '?')}"
                            f"タスクのリトライ。対象: {task.get('target_module', '?')}。"
                            f"エラー: {error_msg}"
                        ),
                        "source_phase_task": f"auto_replenish_{report.get('batch_id', '?')}",
                    })
                    existing_ids.add(ds_id)
                    if len(new_items) >= target_count:
                        break
            if len(new_items) >= target_count:
                break
        return new_items

    def _generate_batch(self, phase: int, milestone: str,
                        batch_size: int) -> dict:
        """
        Phaseテンプレート + 設計ストック駆動でタスクバッチを自動生成する。
        
        【設計ストック優先】design_stock.json の pending 項目を優先的にタスク化し、
        残りのスロットを従来のランダムモジュール割当で埋める。
        【衝突回避】各タスクにユニークな target_module を割り当て、
        同一バッチ内で複数エージェントが同じファイルを編集する競合を防止する。
        """
        batch_id = f"batch_{uuid.uuid4().hex[:6]}"
        
        # 【S2-2】設計ストック自動補充（在庫が閾値以下ならリトライDSを生成）
        try:
            self._auto_replenish_design_stock(phase)
        except Exception as e:
            logger.warning(f"DS auto-replenish failed: {e}")
        
        # === 設計ストック駆動タスク生成 ===
        ds_tasks = []
        ds_items = self._load_design_stock_items(phase)
        if ds_items:
            for ds_item in ds_items[:max(2, batch_size // 2)]:  # 【施策E】DS枠拡大
                generated = self._create_tasks_from_design_stock(ds_item, batch_id, phase)
                if generated:
                    ds_tasks.extend(generated)
                    # 設計ストックのステータスを dispatched に更新
                    self._update_design_stock_status(ds_item["id"], "dispatched")
            if ds_tasks:
                print(f"[DesignStock] {len(ds_tasks)}件の設計ストック駆動タスクを生成")
        
        # === 残りスロットは従来のランダム割当 ===
        remaining_slots = batch_size - len(ds_tasks)
        
        # Opusの指示があればそちらの配分を優先
        directive = self.get_current_directive()
        if directive and directive.get("priorities"):
            priorities = directive["priorities"]
        else:
            # 【S4-2】Phase Gate条件から動的にグループ配分を逆算
            priorities = self._infer_priorities_from_gate(phase)
        
        # 提案A-3: グループ多様性保証 — 1グループ独占を防止
        # Directiveが1グループのみ指定している場合、最低配分を保証
        MIN_DIVERSITY_GROUPS = {
            "bug_hunter": 10,
            "test_weaver": 10,
            "refactor": 10,
        }
        if len(priorities) <= 1:
            dominant_group = next(iter(priorities), "bug_hunter")
            dominant_pct = priorities.get(dominant_group, 50)
            for group, min_pct in MIN_DIVERSITY_GROUPS.items():
                if group not in priorities:
                    priorities[group] = min_pct
                    dominant_pct -= min_pct
            priorities[dominant_group] = max(10, dominant_pct)
            print(f"[提案A-3/GroupDiversity] 1グループ独占を検出、バランス配分に調整: {priorities}")
        
        # 【施策C】グループ別有効打率フィードバック
        priorities = self._adjust_priorities_by_hit_rate(priorities)
        
        # 【逓減リスク②修正】test_count不足時のtest_weaverブースト
        state_for_tc = safe_read_json(str(PHASE_STATE_PATH), {})
        current_test_count = state_for_tc.get("test_count", 0)
        # Phase 40ゲート: test_count >= 2500
        # 残りPhase数で必要なテスト増加ペースを算出
        remaining_phases = max(1, 40 - state_for_tc.get("current_phase", 34))
        needed_per_phase = max(0, (2500 - current_test_count) / remaining_phases)
        if needed_per_phase > 50 and "test_weaver" in priorities:
            # テスト生成が大幅に不足 → test_weaverを最低40%にブースト
            current_tw = priorities.get("test_weaver", 0)
            if current_tw < 40:
                boost = 40 - current_tw
                # 他グループから均等に差し引く
                other_groups = [g for g in priorities if g != "test_weaver" and priorities[g] > 5]
                per_group_deduct = boost // max(1, len(other_groups))
                for g in other_groups:
                    priorities[g] = max(5, priorities[g] - per_group_deduct)
                priorities["test_weaver"] = 40
                print(f"[TestCountBoost] test_count={current_test_count}, "
                      f"目標ペース={needed_per_phase:.0f}/phase → test_weaver 40%にブースト")
        
        # ブラックリストを取得
        state = safe_read_json(str(PHASE_STATE_PATH), {})
        blacklisted = set(state.get("blacklisted_modules", []))
        if directive and directive.get("blacklist_override"):
            for val in directive["blacklist_override"]:
                blacklisted.add(val)
        
        # --- モジュール自動割当: 利用可能モジュールのプール構築 ---
        available_modules = self._get_available_modules(blacklisted)
        
        # 【学習エンジン連携】収穫逓減モジュールを低優先化
        try:
            from backend.agents.orchestration.learning_integration import get_diminishing_modules
            diminishing = get_diminishing_modules()
            if diminishing:
                # 収穫逓減モジュールをリスト末尾に移動（除外はしない）
                prioritized = [m for m in available_modules if m not in diminishing]
                deprioritized = [m for m in available_modules if m in diminishing]
                available_modules = prioritized + deprioritized
                if deprioritized:
                    print(f"[LearningEngine] {len(deprioritized)}件の収穫逓減モジュールを低優先化")
        except Exception as e:
            logger.warning(f"[LearningEngine] diminishing modules check failed: {e}")
        
        # 【施策D】指数関数的クールダウン（固定3バッチ除外の代替）
        miss_counts = self._get_module_miss_counts()
        self._current_miss_counts = miss_counts  # 提案A-1: _is_module_eligible で参照
        module_cooldown = state.get("module_cooldown", {})
        current_batch_num = state.get("flash_batches_completed", 0)
        skipped_modules = set()
        
        for mod, consecutive_miss in miss_counts.items():
            if consecutive_miss >= 3:
                cd = module_cooldown.get(mod, {})
                bl_count = cd.get("consecutive_bl_count", 0) + 1
                cooldown_batches = 3 * (2 ** min(bl_count - 1, 5))  # 上限: 96バッチ
                cooldown_until = cd.get("cooldown_until_batch", 0)
                
                if current_batch_num < cooldown_until:
                    # まだクールダウン中
                    skipped_modules.add(mod)
                else:
                    # 新規クールダウン開始
                    module_cooldown[mod] = {
                        "consecutive_bl_count": bl_count,
                        "cooldown_until_batch": current_batch_num + cooldown_batches
                    }
                    skipped_modules.add(mod)
                    print(f"[ExpCooldown] {mod}: {cooldown_batches}バッチ除外（BL{bl_count}回目）")
        
        # passしたモジュールのクールダウンをリセット
        for mod in list(module_cooldown.keys()):
            if mod not in miss_counts or miss_counts[mod] == 0:
                del module_cooldown[mod]
        
        # --- D3: 長期cooldownの自動クリーンアップ ---
        # cooldown_until_batchが現在のバッチ+60を超えているエントリを刈り取り。
        # Phase進行時にblacklisted_modulesはリセットされるが、module_cooldownの
        # 古いエントリが残り続けてモジュールプール枯渇を引き起こす問題を防止。
        stale_threshold = current_batch_num + 60
        stale_mods = [
            mod for mod, cd in module_cooldown.items()
            if cd.get("cooldown_until_batch", 0) > stale_threshold
        ]
        for mod in stale_mods:
            old_until = module_cooldown[mod].get("cooldown_until_batch", 0)
            # cooldownを現在+6バッチに短縮（完全解除ではなく慎重に短縮）
            module_cooldown[mod]["cooldown_until_batch"] = current_batch_num + 6
            module_cooldown[mod]["consecutive_bl_count"] = min(
                module_cooldown[mod].get("consecutive_bl_count", 1), 2
            )
            print(f"[D3-Cleanup] {mod}: cooldown {old_until}→{current_batch_num + 6} に短縮")
        
        state["module_cooldown"] = module_cooldown
        atomic_write_json(str(PHASE_STATE_PATH), state)
        
        # グループ別にクールダウンを適用（group_aware_cooldown）
        # bug_hunterで空PASSしたモジュールでも、test_weaver/refactorでは利用可能
        if skipped_modules:
            available_modules = [m for m in available_modules if m not in skipped_modules]
            print(f"[ExpCooldown] {len(skipped_modules)}件のモジュールをbug_hunterクールダウン除外（他グループでは利用可）")
        
        # 欠陥A修正: focus_modulesをモジュール割当の優先キューとして使用
        import random
        focus_modules = []
        if directive and directive.get("focus_modules"):
            focus_modules = directive["focus_modules"]
        
        if focus_modules:
            # focus_modulesに含まれるモジュールを先頭に配置
            prioritized = [m for m in available_modules
                           if any(f in m for f in focus_modules)]
            others = [m for m in available_modules if m not in prioritized]
            random.shuffle(prioritized)
            random.shuffle(others)
            available_modules = prioritized + others
        else:
            random.shuffle(available_modules)
        
        module_pool = available_modules  # リストとして保持（グループ別フィルタ用）
        
        # ランダムタスクを生成（【S1-3】miss_countsを引数で渡し二重スキャン防止）
        tasks, assigned_modules = self._create_random_tasks(
            batch_id, phase, remaining_slots, priorities, available_modules,
            miss_counts=miss_counts,
            skipped_modules=skipped_modules if skipped_modules else set()
        )
        
        # 設計ストックタスクを先頭に配置し、ランダムタスクで残りを埋める
        all_tasks = ds_tasks + tasks
        
        # 大規模変更があったモジュールに対するタスクを自動細分化 (DS-016 / DS-026)
        decomposed_tasks = []
        try:
            lock_path = TASK_QUEUE_PATH.with_suffix(".json.lock")
            with FileLock(str(lock_path), timeout=60.0):
                queue_data = safe_read_json(str(TASK_QUEUE_PATH), {})
                large_change_modules = queue_data.get("large_change_modules", [])
                if large_change_modules:
                    from backend.agents.orchestration.ds_task_decomposer import decompose_large_change_task
                    for task in all_tasks:
                        target = task.get("target_module")
                        if target and target in large_change_modules:
                            print(f"[Orchestrator] Decomposing task {task.get('id')} for module {target} due to prior large change")
                            split_tasks = decompose_large_change_task(task)
                            decomposed_tasks.extend(split_tasks)
                            # 一度適用したらリストから削除
                            large_change_modules.remove(target)
                        else:
                            decomposed_tasks.append(task)
                    
                    queue_data["large_change_modules"] = large_change_modules
                    atomic_write_json(str(TASK_QUEUE_PATH), queue_data)
                    all_tasks = decomposed_tasks
                else:
                    decomposed_tasks = all_tasks
        except Exception as e:
            logger.warning(f"Failed to decompose large change tasks: {e}")
        
        # === test_weaver タスクのテスト雛形事前自動生成 ===
        for task in all_tasks[:batch_size]:
            if task.get("group") == "test_weaver" and task.get("target_module"):
                mod = task["target_module"]
                try:
                    from backend.agents.orchestration.ast_test_generator import ASTTestGenerator
                    generator = ASTTestGenerator()
                    generator.generate_and_save(mod)
                    print(f"[ASTTestGen] Pre-generated test skeleton for {mod}")
                except Exception as e:
                    logger.warning(f"[ASTTestGen] Failed to pre-generate test skeleton for {mod}: {e}")
        
        return {
            "schema_version": "1.1",
            "current_batch_id": batch_id,
            "generated_at": _now_iso(),
            "phase": phase,
            "milestone": milestone,
            "tasks": all_tasks[:batch_size],
            "blacklisted_modules": list(blacklisted),
            "assigned_modules": list(assigned_modules),
            "design_stock_tasks": len(ds_tasks),
            "random_tasks": len(tasks),
            "batch_config": {
                "max_parallel": 30,
                "groups": priorities,
            }
        }


    def _load_design_stock_items(self, phase: int) -> list:
        """design_stock.json から現Phaseの pending 項目を取得する。
        
        Returns:
            list: pending かつ現Phase以下の設計ストック項目のリスト
        """
        if not DESIGN_STOCK_PATH.exists():
            return []
        try:
            data = safe_read_json(str(DESIGN_STOCK_PATH), {})
            items = data.get("stock_items", [])
            # pending 項目のみ、かつ現Phase以下のもの（未来Phaseのは除外）
            return [
                item for item in items
                if item.get("status") == "pending" and item.get("phase", 999) <= phase
            ]
        except Exception as e:
            logger.warning("Design stock load failed: %s", e)
            return []

    def _create_tasks_from_design_stock(self, ds_item: dict, batch_id: str,
                                         phase: int) -> list:
        """設計ストック項目から、implementation_stepsがある場合は複数タスクに自動分解して返す。"""
        steps = ds_item.get("implementation_steps", [])
        if not steps:
            task = self._create_task_from_design_stock(ds_item, batch_id, phase)
            return [task] if task else []

        from .generator import TaskGenerator
        generator = TaskGenerator()
        return generator.create_batch_tasks(batch_id, [ds_item], phase)

    def _create_task_from_design_stock(self, ds_item: dict, batch_id: str,
                                        phase: int) -> Optional[dict]:
        """設計ストック項目から具体的な作業指示を含むタスクを生成する。
        
        DS項目の description, source_phase_task, difficulty から
        Flashサブエージェントが即座に実行可能な具体的指示を構築する。
        """
        from .generator import TaskGenerator
        generator = TaskGenerator()
        tasks = generator.create_batch_tasks(batch_id, [ds_item], phase)
        return tasks[0] if tasks else None

    def _update_design_stock_status(self, ds_id: str, new_status: str) -> None:
        """設計ストック項目のステータスを更新する。
        
        Args:
            ds_id: 設計ストックID (例: "DS-001")
            new_status: "dispatched", "completed", "failed"
        """
        try:
            from .design_stock import DesignStockStore
            store = DesignStockStore(str(DESIGN_STOCK_PATH))
            store.update_status(ds_id, new_status)
            logger.info("Design stock %s status updated to %s", ds_id, new_status)
        except Exception as e:
            logger.warning("Design stock status update failed: %s", e)

    def _get_available_modules(self, blacklisted: set) -> list[str]:
        """backend配下のPythonモジュール一覧を取得し、ブラックリストを除外して返す。
        
        【S3-2】module_index.json にキャッシュし、1時間以内の再呼び出しでは
        ファイルシステムスキャン(rglob)を省略してI/Oコストを削減する。
        """
        # キャッシュ読み込み
        index_path = MODULE_INDEX_PATH
        try:
            index = safe_read_json(str(index_path), {})
            updated_at = _safe_parse_iso(index.get("updated_at"))
            if updated_at:
                age = (datetime.now(timezone.utc) - updated_at).total_seconds()
                if age < 3600 and index.get("modules"):  # 1時間以内
                    all_modules = index["modules"]
                    return self._filter_blacklisted(all_modules, blacklisted)
        except Exception as e:
            logger.warning(f"Failed to read module index cache: {e}")

        # キャッシュが古い or 存在しない → rglob でフルスキャン
        all_modules = self._scan_backend_modules()
        
        # キャッシュに保存
        try:
            atomic_write_json(str(index_path), {
                "modules": all_modules,
                "updated_at": _now_iso(),
                "count": len(all_modules),
            })
        except Exception as e:
            logger.warning(f"Failed to write module index cache: {e}")

        return self._filter_blacklisted(all_modules, blacklisted)

    def _scan_backend_modules(self) -> list[str]:
        """backend配下のPythonモジュールをスキャンし、プロダクションコードのみ返す。
        
        【ホワイトリスト方式（逓増型）】
        2層防御でプロダクションモジュールを選別:
          Layer 1: 静的除外パターン（高速パス — AST解析を省略するための最適化）
          Layer 2: AST品質フィルタ（動的判定 — ファイル内容からプロダクション品質を評価）
        
        この方式により、新規ゴミファイルが生成されても自動的に除外される。
        パターンリストの手動メンテナンスが不要な「成長する仕組み」。
        """
        backend_dir = _PROJECT_ROOT / "backend"
        modules = []
        
        if not backend_dir.exists():
            return modules
        
        # === Layer 1: 静的除外パターン（高速パス） ===
        # AST解析を省略するための最適化。明らかな非プロダクションを即除外。
        EXCLUDE_DIR_PATTERNS = {
            "scratch/",           # 一時スクリプト
            "_deprecated/",       # 非推奨モジュール
            "archives/",          # アーカイブ済み
            "fixtures/",          # テストフィクスチャ
            "__pycache__",        # コンパイルキャッシュ
        }
        EXCLUDE_STEM_PREFIXES = (
            "mark_task",          # タスク管理用一時スクリプト
            "flash_assign_",      # Flash割当スクリプト
            "complete_batch_",    # バッチ完了スクリプト
            "apply_task_",        # タスク適用スクリプト
            "mark_and_",          # バッチ完了マーカー
            "flash_runner_",      # Flashランナーバージョン
        )
        EXCLUDE_STEMS = {
            "__init__",
            "conftest",           # テスト基盤
        }
        
        for py_file in backend_dir.rglob("*.py"):
            path_str = str(py_file).replace("\\", "/")
            
            # Layer 1: 静的除外（高速パス）
            if any(pattern in path_str for pattern in EXCLUDE_DIR_PATTERNS):
                continue
            if py_file.stem.startswith(EXCLUDE_STEM_PREFIXES):
                continue
            if py_file.stem in EXCLUDE_STEMS:
                continue
            if "test" in py_file.stem.lower() and py_file.stem.startswith("test_"):
                continue
            
            # === Layer 2: AST品質フィルタ（動的判定） ===
            if not self._is_production_module(py_file):
                continue
            
            try:
                rel = py_file.relative_to(backend_dir)
                module_path = str(rel).replace("\\", "/")
                modules.append(module_path)
            except ValueError:
                continue
        
        return modules

    @staticmethod
    def _is_production_module(py_file) -> bool:
        """AST解析でモジュールがプロダクションコードかを動的に判定する。
        
        【逓増型メカニズム】新規ゴミファイルは以下の条件を満たさないため自動除外:
        - ファイルサイズ 500B未満 → 除外（スクリプト片）
        - 関数/クラス定義が 2未満 → 除外（使い捨てスクリプト）
        - import文が 3未満 → 除外（単体で動く簡易スクリプト）
        
        プロダクションモジュールは通常:
        - 複数の関数/クラスを持つ（再利用可能な設計）
        - 複数のimportを持つ（他モジュールとの依存関係）
        - 一定のサイズを持つ（意味のあるロジック）
        """
        import ast as _ast
        
        try:
            stat = py_file.stat()
            if stat.st_size < 500:
                return False
            
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = _ast.parse(content)
            
            definitions = sum(
                1 for node in _ast.walk(tree)
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef))
            )
            imports = sum(
                1 for node in _ast.walk(tree)
                if isinstance(node, (_ast.Import, _ast.ImportFrom))
            )
            
            return definitions >= 2 and imports >= 3
            
        except Exception:
            return False

    @staticmethod
    def _filter_blacklisted(modules: list[str], blacklisted: set) -> list[str]:
        """モジュールリストからブラックリストを除外する。"""
        result = []
        for module_path in modules:
            is_blacklisted = False
            for b in blacklisted:
                if not b:
                    continue
                b_clean = b.rstrip("/")
                if (module_path == b or 
                    module_path == b_clean or 
                    module_path.startswith(b_clean + "/") or
                    module_path.rsplit("/", 1)[-1].replace(".py", "") == b):
                    is_blacklisted = True
                    break
            if not is_blacklisted:
                result.append(module_path)
        return result

    def trigger_quality_fix(self, score_report: dict):
        """NHKスコアレポートに基づき、閾値以下の軸に対して
        bug_hunterタスクを自動生成してキューに投入する。

        Args:
            score_report: NHKScoreReport.to_dict() の出力

        Returns:
            生成されたタスク数の報告文字列、閾値以上なら None
        """
        from backend.services.quality_feedback_trigger import QualityFeedbackTrigger
        trigger = QualityFeedbackTrigger()
        result = trigger.evaluate_and_trigger(score_report)

        if result["triggered"]:
            logger.info(
                "Quality fix triggered: %d axes below threshold, %d tasks created",
                len(result["low_axes"]), result["tasks_created"]
            )
            return result["details"]
        return None

    def _calculate_dynamic_limit(self, session: dict) -> int:
        """
        過去10分以内の429エラー数を評価し、並列上限数を動的に算出する。
        """
        recent_errors = session.get("recent_errors", [])
        if not recent_errors:
            return 15

        now = datetime.now(timezone.utc)
        has_recent_429 = False
        for err in recent_errors:
            try:
                ts_str = err.get("timestamp")
                err_time = _safe_parse_iso(ts_str)
                if err_time and (now - err_time) < timedelta(minutes=10):
                    err_msg = err.get("error", "")
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        has_recent_429 = True
                        break
            except KeyError:
                pass

        if has_recent_429:
            return 2
        return 15

    def _recover_timed_out_tasks(self, queue: dict, timeout_seconds: float = 900.0) -> bool:
        """
        実行中(running)のタスクで、開始から timeout_seconds 以上経過したものを
        自動的に pending に差し戻す（自己修復機能）。
        
        リトライ上限: MAX_TASK_RETRIES 回タイムアウトしたタスクは 'skip' にマークし、
        永久ループを防止する。
        
        変更があった場合は True を返す。
        """
        MAX_TASK_RETRIES = 2  # タイムアウト回復の最大回数。超過でスキップ
        changed = False
        now = datetime.now(timezone.utc)
        for task in queue.get("tasks", []):
            if task.get("status") == "running":
                started_at_str = task.get("started_at")
                if not started_at_str:
                    task["started_at"] = _now_iso()
                    changed = True
                    continue
                try:
                    started_time = _safe_parse_iso(started_at_str)
                    if started_time:
                        elapsed = (now - started_time).total_seconds()
                    else:
                        raise ValueError("Invalid format")
                    if elapsed >= timeout_seconds:
                        retry_count = task.get("retry_count", 0) + 1
                        task["retry_count"] = retry_count
                        
                        if retry_count > MAX_TASK_RETRIES:
                            # リトライ上限超過: スキップして先に進む
                            logger.warning(
                                f"Task {task['id']} exceeded max retries ({MAX_TASK_RETRIES}). "
                                f"Marking as 'skip' to prevent infinite loop."
                            )
                            task["status"] = "skip"
                            task["completed_at"] = _now_iso()
                            task["result"] = {
                                "error": f"MAX_RETRIES_EXCEEDED: {retry_count}回タイムアウト。自動スキップ。",
                                "retry_count": retry_count,
                                "total_elapsed": elapsed,
                            }
                            # Opusに通知
                            try:
                                self.send_message(
                                    "flash", "opus",
                                    f"⚠️ タスク {task['id']} ({task.get('target_module', '?')}) を自動スキップ。"
                                    f"リトライ{retry_count}回超過（各{timeout_seconds}秒タイムアウト）。"
                                    f"手動での対応が必要な場合があります。",
                                    priority="urgent"
                                )
                            except Exception as send_err:
                                logger.warning(f"Failed to send task skip notification to Opus: {send_err}")
                        else:
                            # 通常のリトライ: pending に戻す
                            logger.warning(
                                f"Task {task['id']} timed out after {elapsed:.1f}s "
                                f"(retry {retry_count}/{MAX_TASK_RETRIES}). Resetting to pending."
                            )
                            task["status"] = "pending"
                            task["started_at"] = None
                            if "assigned_agent" in task:
                                task["assigned_agent"] = None
                        
                        # エラー記録
                        session = safe_read_json(str(FLASH_SESSION_PATH), {})
                        if "recent_errors" not in session:
                            session["recent_errors"] = []
                        session["recent_errors"].append({
                            "timestamp": _now_iso(),
                            "error": f"TIMEOUT_RECOVERY: Task {task['id']} (retry {retry_count}/{MAX_TASK_RETRIES})",
                            "module": task.get("target_module", "unknown")
                        })
                        atomic_write_json(str(FLASH_SESSION_PATH), session)
                        changed = True
                except (ValueError, TypeError):
                    task["started_at"] = _now_iso()
                    changed = True
        return changed

    def _is_cooldown_active(self, session: dict, now: datetime) -> bool:
        """429エラーやRESOURCE_EXHAUSTEDによるクールダウン待機中（60秒以内）か判定する"""
        for err in session.get("recent_errors", []):
            try:
                ts_str = err.get("timestamp")
                err_time = _safe_parse_iso(ts_str)
                if err_time and (now - err_time) < timedelta(seconds=60):
                    err_msg = err.get("error", "")
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        return True
            except KeyError:
                pass
        return False

    def _reset_stale_running_tasks(self, queue: dict, now: datetime) -> int:
        """30分以上前に開始された stale running タスクを pending にリセットする"""
        stale_reset_count = 0
        for task in queue.get("tasks", []):
            if task.get("status") == "running":
                started_at = task.get("started_at", "")
                if started_at:
                    ts = _safe_parse_iso(started_at)
                    if ts and (now - ts) > timedelta(minutes=30):
                        task["status"] = "pending"
                        task.pop("started_at", None)
                        stale_reset_count += 1
        return stale_reset_count

    def _calculate_max_concurrent(self, phase: int, batch_size: int, session: dict) -> int:
        """クォータ制限回避のために動的な最大同時実行数を計算する"""
        # 1. 動的スロットリング上限 (429検出時=2, 通常=15)
        dynamic_limit = self._calculate_dynamic_limit(session)
        
        # 2. 予防的総量配分（model_config.json の RPM 制限に基づく上限）
        rpm_limit = 15
        model_config_path = _PROJECT_ROOT / "backend" / "model_config.json"
        if model_config_path.exists():
            try:
                config_data = safe_read_json(str(model_config_path), {})
                model_name = "gemini-2.5-flash-lite" if phase == 5 else "gemini-2.5-flash"
                limits = config_data.get("free_tier_limits", {}).get(model_name, {})
                rpm_limit = limits.get("rpm", 15)
            except (json.JSONDecodeError, KeyError, AttributeError):
                pass
        preventive_limit = int(rpm_limit * 0.8)  # 安全係数 0.8
        
        # 3. UsageTracker による今日の残リクエスト数上限
        remaining_requests = 9999
        try:
            from backend.usage_tracker.tracker import usage_tracker
            model_name = "gemini-2.5-flash-lite" if phase == 5 else "gemini-2.5-flash"
            remaining_requests = usage_tracker.get_remaining_requests(model_name)
        except Exception as e:
            logger.warning(f"Failed to get remaining requests from usage_tracker: {e}")
            remaining_requests = 9999
        
        # 最終上限の決定（最小値は2を保証）
        max_concurrent = min(batch_size, dynamic_limit, preventive_limit, remaining_requests)
        return max(2, max_concurrent)

    def get_next_batch(self, phase: int, milestone: str,
                        batch_size: int = 30, timeout_seconds: float = 900.0) -> list[dict]:
        """
        現在のPhase/Milestoneに基づいてタスクバッチを返す。
        
        【自動計装】この1メソッドを呼ぶだけで以下が自動実行される:
        - 初回呼び出し時: flash_session_start()
        - 毎回: flash_update_status(), Opus指示の読み込み, メッセージの自動処理
        """
        lock_path = TASK_QUEUE_PATH.with_suffix(".json.lock")
        with FileLock(str(lock_path), timeout=60.0):
            # --- 自動計装: タイムアウトしたタスクの自己修復 ---
            queue = safe_read_json(str(TASK_QUEUE_PATH), {})
            if self._recover_timed_out_tasks(queue, timeout_seconds):
                atomic_write_json(str(TASK_QUEUE_PATH), queue)

            # --- 自動計装: セッション自動開始 ---
            session = safe_read_json(str(FLASH_SESSION_PATH), {})
            if session.get("status") != "running":
                self.flash_session_start()
                session = safe_read_json(str(FLASH_SESSION_PATH), {})
            
            # --- 自動計装: Opus指示の自動読み込み ---
            directive = self.get_current_directive()
            if directive and directive.get("priorities"):
                # Opusの指示がある場合、タスク配分を自動反映
                pass  # _generate_batch() 内で自動参照される
            
            # --- 自動計装: 未読メッセージの自動処理 ---
            unread = self.read_messages("flash", unread_only=True)
            for msg in unread:
                self.acknowledge_message(msg["id"])
            
            # --- 自動計装: クールダウン判定 (60秒以内) ---
            now = datetime.now(timezone.utc)
            if self._is_cooldown_active(session, now):
                self.flash_update_status(
                    "waiting",
                    "429エラー発生によるクールダウン待機中（60秒間新規タスク休止）",
                    progress_pct=0
                )
                return []

            # --- 自動計装: ステータス更新 ---
            self.flash_update_status(
                "dispatching",
                f"バッチ取得中 (Phase {phase} / {milestone})",
                progress_pct=0
            )
            
            # --- コアロジック: バッチ取得 ---
            queue = safe_read_json(str(TASK_QUEUE_PATH), {})
            
            # --- R4: セッション引き継ぎ時の stale running タスク自動リセット ---
            stale_reset_count = self._reset_stale_running_tasks(queue, now)
            if stale_reset_count > 0:
                atomic_write_json(str(TASK_QUEUE_PATH), queue)

            # 再入ガード: running 状態のタスクがあれば、新バッチを生成せず返す（弱点4修正）
            running = [t for t in queue.get("tasks", []) if t["status"] == "running"]
            if running:
                batch_id = queue.get("current_batch_id", "unknown")
                self.flash_update_status(
                    "executing",
                    f"バッチ {batch_id}: {len(running)}タスクが実行中（再入検知・前バッチを継続）",
                    batch_id=batch_id,
                    progress_pct=5,
                    subagents_running=len(running)
                )
                return running
            
            pending = [t for t in queue.get("tasks", []) if t["status"] == "pending"]
            
            if not pending:
                queue = self._generate_batch(phase, milestone, batch_size)
                atomic_write_json(str(TASK_QUEUE_PATH), queue)
                pending = [t for t in queue["tasks"] if t["status"] == "pending"]
            
            # --- R-DAG: Filter pending tasks whose dependencies are fully resolved ---
            resolved_pending = []
            all_tasks_by_id = {t["id"]: t for t in queue.get("tasks", [])}
            for task in pending:
                deps = task.get("dependencies", [])
                deps_resolved = True
                for dep in deps:
                    dep_task = all_tasks_by_id.get(dep)
                    if dep_task and dep_task.get("status") not in ("pass", "completed"):
                        deps_resolved = False
                        break
                if deps_resolved:
                    resolved_pending.append(task)
            
            if not resolved_pending and pending:
                resolved_pending = pending
                
            # --- R-WAVE: WaveScheduler and ResourceGovernor integration ---
            from .wave_scheduler import WaveScheduler
            from .resource_governor import ResourceGovernor
            
            scheduler = WaveScheduler(default_wave_size=batch_size)
            governor = ResourceGovernor()
            
            max_concurrent = self._calculate_max_concurrent(phase, batch_size, session)
            
            # Enforce rate limits before dispatching wave
            governor.throttle_if_needed(expected_tokens=10000)
            
            waves = scheduler.schedule_waves(resolved_pending, wave_size=max_concurrent)
            batch = waves[0] if waves else []
            task_ids = {t["id"] for t in batch}
            for task in queue["tasks"]:
                if task["id"] in task_ids:
                    task["status"] = "running"
                    task["started_at"] = _now_iso()
            atomic_write_json(str(TASK_QUEUE_PATH), queue)
            
            batch_id = queue.get("current_batch_id", "unknown")
            self.flash_update_status(
                "executing",
                f"バッチ {batch_id}: {len(batch)}タスク実行開始",
                batch_id=batch_id,
                progress_pct=5,
                subagents_running=len(batch)
            )
            
            return batch

    def mark_task_done(self, task_id: str, result: str,
                       report: Optional[dict] = None) -> None:
        """
        タスクを完了としてマークする。
        
        【自動計装】以下が自動実行される:
        - ステータス更新（進捗率の自動計算）
        - FAIL時: 収束ループによるリトライ判定 + エラー報告
        - FAIL（リトライ不可）時: 連続3回で自動ブラックリスト化 + Opus通知
        - ハートビート更新

        # satisfies: REQ-CONV-03
        """
        lock_path = TASK_QUEUE_PATH.with_suffix(".json.lock")
        with FileLock(str(lock_path), timeout=60.0):
            queue = safe_read_json(str(TASK_QUEUE_PATH), {})
            target_module = None
            task_obj = None  # 収束ループ用にタスクオブジェクトを保持
            for task in queue.get("tasks", []):
                if task["id"] == task_id:
                    task["status"] = result
                    task["completed_at"] = _now_iso()
                    target_module = task.get("target_module")
                    if report:
                        task["result"] = report
                    task_obj = task.copy()  # 収束ループ判定用のスナップショット
                    break
            atomic_write_json(str(TASK_QUEUE_PATH), queue)
            
            # phase_state の統計を更新
            state_lock = PHASE_STATE_PATH.with_suffix(".json.lock")
            with FileLock(str(state_lock), timeout=60.0):
                state = safe_read_json(str(PHASE_STATE_PATH), {})
                state["flash_tasks_total"] = state.get("flash_tasks_total", 0) + 1
                if result == "pass":
                    state["flash_tasks_passed"] = state.get("flash_tasks_passed", 0) + 1
                    state["flash_consecutive_failures"] = 0
                    
                    # --- 収束ループ: リトライ成功の記録 ---
                    if task_obj and task_obj.get("retry_count", 0) > 0:
                        try:
                            conv_loop = ConvergenceLoop(
                                task_queue_path=TASK_QUEUE_PATH,
                                flash_reports_path=FLASH_REPORTS_PATH
                            )
                            conv_loop.record_retry_event(
                                task_id=task_id,
                                retry_count=task_obj["retry_count"],
                                result="retry_success",
                                target_module=target_module or "",
                            )
                        except Exception as e:
                            logger.warning(f"[ConvergenceLoop] Error recording retry success: {e}")
                elif result in ("fail", "failed"):
                    state["flash_tasks_failed"] = state.get("flash_tasks_failed", 0) + 1
                    state["flash_consecutive_failures"] = state.get("flash_consecutive_failures", 0) + 1
                atomic_write_json(str(PHASE_STATE_PATH), state)
            
            # --- 自動計装: FAIL時の詳細エラー報告 + 収束ループ + デバッグレポート生成 ---
            retried = False
            if result in ("fail", "failed"):
                error_msg = ""
                traceback_str = ""
                changed_files = []
                if report:
                    error_msg = report.get("error", report.get("message", str(report)[:200]))
                    traceback_str = report.get("traceback", "")
                    changed_files = report.get("changed_files", [])
                
                # flash_session.json にエラー記録（直近10件保持）
                self.flash_report_error(
                    f"タスク {task_id} FAIL: {error_msg}",
                    module=target_module
                )
                
                # --- 収束ループ: リトライ可否判定 (# satisfies: REQ-CONV-03) ---
                try:
                    conv_loop = ConvergenceLoop(
                        task_queue_path=TASK_QUEUE_PATH,
                        flash_reports_path=FLASH_REPORTS_PATH
                    )
                    if task_obj:
                        decision = conv_loop.should_retry(task_obj, report)
                        if decision["retry"]:
                            # リトライ可能: タスクを pending に戻す
                            conv_loop.prepare_retry(task_id, decision["feedback_prompt"])
                            conv_loop.record_retry_event(
                                task_id=task_id,
                                retry_count=decision["retry_count"] + 1,
                                result="retry_fail",
                                error_msg=error_msg,
                                target_module=target_module or "",
                            )
                            retried = True
                            logger.info(
                                f"[ConvergenceLoop] Task {task_id} queued for retry "
                                f"({decision['retry_count'] + 1}/{conv_loop.max_retries})"
                            )
                        else:
                            # リトライ不可: 最終失敗として記録
                            conv_loop.record_retry_event(
                                task_id=task_id,
                                retry_count=task_obj.get("retry_count", 0),
                                result="retry_exhausted",
                                error_msg=f"{decision['reason']}: {error_msg}",
                                target_module=target_module or "",
                            )
                except Exception as e:
                    logger.warning(f"[ConvergenceLoop] Error during retry evaluation: {e}")
                
                # 受信トレイにデバッグレポート自動生成（弱点3修正: 失敗してもメインは継続）
                if not retried:
                    try:
                        self._generate_error_debug_report(
                            task_id=task_id,
                            target_module=target_module,
                            error_msg=error_msg,
                            traceback_str=traceback_str,
                            changed_files=changed_files,
                            full_report=report,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to generate error debug report for {task_id}: {e}")
                
                # 連続3回FAILで自動ブラックリスト + Opus通知（リトライ中は除外）
                if not retried:
                    consec = state.get("flash_consecutive_failures", 0)
                    if consec >= 3 and target_module:
                        try:
                            self.blacklist_module(target_module,
                                f"連続{consec}回FAIL: {error_msg[:80]}")
                            self.send_message("flash", "opus",
                                f"⚠️ {target_module} を自動ブラックリスト化（連続{consec}回FAIL）",
                                priority="urgent")
                        except Exception as e:
                            logger.warning(f"Failed to blacklist module or notify Opus for {target_module}: {e}")
            
            # --- 自動計装: 進捗率の自動計算＆ステータス更新 ---
            tasks = queue.get("tasks", [])
            total = len(tasks)
            done = sum(1 for t in tasks if t.get("status") in ("pass", "fail", "skip"))
            pct = int(done / total * 100) if total else 0
            
            session_lock = FLASH_SESSION_PATH.with_suffix(".json.lock")
            with FileLock(str(session_lock), timeout=60.0):
                session = safe_read_json(str(FLASH_SESSION_PATH), {})
                session["last_heartbeat"] = _now_iso()
                session["tasks_completed_in_session"] = session.get("tasks_completed_in_session", 0) + 1
                session["progress_pct"] = pct
                session["current_step"] = f"タスク完了 {done}/{total} ({pct}%)"
                atomic_write_json(str(FLASH_SESSION_PATH), session)
            
            # design stock 状態更新
            ds_id = None
            if result == "pass":
                if task_obj:
                    ds_id = task_obj.get("design_stock_id")
                
                # フォールバック抽出
                if not ds_id and "-ds-" in task_id:
                    try:
                        import re
                        clean_match = re.sub(r"^T-batch_[a-f0-9]+-ds-", "", task_id)
                        if clean_match.count("-") >= 2 and re.search(r"-\d{3}$", clean_match):
                            ds_id_match = re.sub(r"-\d{3}$", "", clean_match)
                        else:
                            ds_id_match = clean_match
                        if ds_id_match:
                            ds_id_match_clean = re.sub(r"^ds-", "", ds_id_match.lower())
                            if ds_id_match_clean.startswith("auto-"):
                                ds_id = f"DS-AUTO-{ds_id_match_clean[5:].upper()}"
                            else:
                                ds_id = f"DS-{ds_id_match_clean.upper()}"
                    except Exception as e:
                        logger.warning("DS id fallback extraction failed for %s: %s", task_id, e)
                
                if ds_id:
                    try:
                        self._update_design_stock_status(ds_id, "completed")
                        print(f"[DesignStock] {ds_id} を completed に更新")
                    except Exception as e:
                        logger.warning("DS status update failed for %s: %s", task_id, e)
            
            # --- R-DAG: Cascade failure to dependent tasks ---
            is_final_failure = (result in ("fail", "failed") and not retried) or result == "skipped"
            if is_final_failure:
                try:
                    import collections
                    q_data = safe_read_json(str(TASK_QUEUE_PATH), {})
                    dependents = collections.defaultdict(list)
                    for t in q_data.get("tasks", []):
                        for dep in t.get("dependencies", []):
                            dependents[dep].append(t["id"])
                    
                    visited = set()
                    stack = dependents.get(task_id, [])
                    while stack:
                        curr_id = stack.pop()
                        if curr_id in visited:
                            continue
                        visited.add(curr_id)
                        
                        for t in q_data.get("tasks", []):
                            if t["id"] == curr_id:
                                t["status"] = "skipped"
                                t["result"] = f"skipped_dependency_failed: {task_id}"
                                t["completed_at"] = _now_iso()
                                break
                        stack.extend(dependents.get(curr_id, []))
                    atomic_write_json(str(TASK_QUEUE_PATH), q_data)
                except Exception as e:
                    logger.warning(f"[DAG] Error during cascade failure processing: {e}")

    def get_queue_status(self) -> dict:
        """タスクキューの現在のサマリーを返す"""
        lock_path = TASK_QUEUE_PATH.with_suffix(".json.lock")
        with FileLock(str(lock_path), timeout=60.0):
            queue = safe_read_json(str(TASK_QUEUE_PATH), {})
            # タイムアウトしたタスクの自己修復を自動実行
            if self._recover_timed_out_tasks(queue):
                atomic_write_json(str(TASK_QUEUE_PATH), queue)
            tasks = queue.get("tasks", [])
            status_counts = {}
            for t in tasks:
                s = t.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            return {
                "batch_id": queue.get("current_batch_id"),
                "phase": queue.get("phase"),
                "milestone": queue.get("milestone"),
                "total_tasks": len(tasks),
                "status_counts": status_counts,
                "blacklisted_modules": queue.get("blacklisted_modules", []),
            }

    def generate_tasks_for_batch(self, batch_id: str, stock_items: list) -> list:
        """Generator を使用してバッチ用のタスクを自動生成する"""
        from .generator import TaskGenerator
        generator = TaskGenerator()
        return generator.create_batch_tasks(batch_id, stock_items)
