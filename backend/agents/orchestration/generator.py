"""
Task Generator (TaskGenerator)
設計ストックや優先度設定から自律的に実装タスクを生成・分解する。
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

class TaskGenerator:
    def __init__(self, queue_path: str = None):
        self.queue_path = queue_path or os.path.join(os.path.dirname(__file__), "task_queue.json")

    def create_batch_tasks(self, batch_id: str, stock_items: List[Dict[str, Any]], phase: int = None) -> List[Dict[str, Any]]:
        """設計ストックリストから、指定バッチIDに紐づくマイクロタスク群を生成する"""
        generated_tasks = []
        for item in stock_items:
            ds_id = item.get("id", "DS-???")
            title = item.get("title", "")
            description = item.get("description", "")
            difficulty = item.get("difficulty", "C")
            milestone = item.get("milestone", "")
            source = item.get("source_phase_task", "")
            
            # 難度に応じたタスクレベル
            level = "L2" if difficulty in ("A", "S", "B") else "L1"
            
            steps = item.get("implementation_steps", [])
            if not steps:
                # 単一タスク
                if phase is not None:
                    instruction = (
                        f"Phase {phase} / 設計ストック {ds_id}: {title}\n"
                        f"マイルストーン: {milestone}\n\n"
                        f"【設計ストック駆動タスク — 優先度: {difficulty}】\n"
                        f"概要: {description}\n"
                        f"出典: {source}\n\n"
                        f"【作業指示】\n"
                        f"1. 上記の設計仕様に基づき、必要なモジュールを特定し実装せよ。\n"
                        f"2. 実装対象 of モジュールが存在しない場合は新規作成すること。\n"
                        f"3. テスト追加必須（pytest --timeout=300 で全テストPASS確認）。\n"
                        f"4. プロダクションコードの変更は5ファイル以内。\n"
                        f"5. 実装完了後、changed_files に変更したファイルのパスを必ず記録すること。\n"
                    )
                    # three_point_check が未完了なら追加指示
                    tpc = item.get("three_point_check", {})
                    if tpc and not all(tpc.values()):
                        missing = [k for k, v in tpc.items() if not v]
                        instruction += (
                            f"\n【追加要件】three_point_check の未完了項目を解消すること:\n"
                            + "".join(f"  - {m}\n" for m in missing)
                        )
                else:
                    instruction = f"【設計ストックタスク: {title}】\n{description}"

                task = {
                    "id": f"T-{batch_id}-ds-{ds_id.lower()}",
                    "group": self._map_difficulty_to_group(difficulty),
                    "level": level,
                    "target_module": item.get("target_module", None),
                    "instruction": instruction,
                    "status": "pending",
                    "assigned_agent": None,
                    "result": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "started_at": None,
                    "completed_at": None,
                    "retry_count": 0,
                    "design_stock_id": ds_id
                }
                generated_tasks.append(task)
            else:
                # 分解ステップが存在する場合
                for idx, step in enumerate(steps):
                    if isinstance(step, str):
                        step_title = step
                        step_desc = ""
                        target_module = None
                    else:
                        step_title = step.get("title", f"Step {idx+1}")
                        step_desc = step.get("description", "")
                        target_module = step.get("target_module")

                    if phase is not None:
                        instruction = (
                            f"Phase {phase} / 設計ストック {ds_id} (ステップ {idx+1}/{len(steps)}): {title} - {step_title}\n"
                            f"【設計ストック駆動マイクロタスク — 優先度: {difficulty}】\n"
                            f"概要: {step_desc or step_title}\n"
                            f"変更対象ファイル(原則1ファイル): {target_module or '探索により特定'}\n\n"
                            f"【作業指示】\n"
                            f"1. 対象モジュール（{target_module or '関連モジュール'}）を修正・実装せよ。\n"
                            f"2. 変更範囲は原則1ファイル（max）に抑えること。\n"
                            f"3. テスト追加必須（pytest --timeout=300 で全テストPASS確認）。\n"
                            f"4. 実装完了後、changed_files に変更したファイルのパスを必ず記録すること。\n"
                        )
                        # three_point_check が未完了なら追加指示
                        tpc = item.get("three_point_check", {})
                        if tpc and not all(tpc.values()):
                            missing = [k for k, v in tpc.items() if not v]
                            instruction += (
                                f"\n【追加要件】three_point_check の未完了項目を解消すること:\n"
                                + "".join(f"  - {m}\n" for m in missing)
                            )
                    else:
                        instruction = f"【設計ストックタスク: {title} - ステップ {idx+1}】\n{step_desc or step_title}"

                    task = {
                        "id": f"T-{batch_id}-ds-{ds_id.lower()}-{idx:03d}",
                        "group": self._map_difficulty_to_group(difficulty),
                        "level": level,
                        "target_module": target_module,
                        "instruction": instruction,
                        "status": "pending",
                        "assigned_agent": None,
                        "result": None,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "started_at": None,
                        "completed_at": None,
                        "retry_count": 0,
                        "design_stock_id": ds_id,
                        "step_index": idx
                    }
                    generated_tasks.append(task)
        return generated_tasks

    def _map_difficulty_to_group(self, difficulty: str) -> str:
        # 設計ストック用のグループとして常に "design_stock" を返す
        return "design_stock"

