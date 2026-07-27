"""
DS-014: Design Stock タスク分解エンジン

DS項目からFlashタスクへの変換時に、1タスク=1ファイル変更(max)の
マイクロタスク粒度に自動分解する。

DS項目に `implementation_steps` フィールドがある場合はそれを使用し、
ない場合は description から自動推定する。
"""
import json
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent
_DESIGN_STOCK_PATH = _BASE_DIR / "design_stock.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def decompose_ds_item(ds_item: dict, batch_id: str, 
                       max_tasks: int = 3) -> list[dict]:
    """DS項目をマイクロタスクに分解する。

    DS-014の核心機能: 1つのDS項目から複数の具体的なタスクを生成。

    Args:
        ds_item: 設計ストック項目
        batch_id: バッチID
        max_tasks: 1 DS項目から生成するタスクの最大数

    Returns:
        タスク辞書のリスト
    """
    ds_id = ds_item.get("id", "DS-???")
    title = ds_item.get("title", "")
    description = ds_item.get("description", "")
    difficulty = ds_item.get("difficulty", "C")
    steps = ds_item.get("implementation_steps", [])

    # implementation_steps がある場合はそれを使用
    if steps:
        return _decompose_from_steps(ds_item, batch_id, steps, max_tasks)

    # ない場合は description から推定
    return _decompose_from_description(ds_item, batch_id, max_tasks)


def _decompose_from_steps(ds_item: dict, batch_id: str, 
                           steps: list, max_tasks: int) -> list[dict]:
    """implementation_steps から具体的なタスクを生成する。"""
    ds_id = ds_item.get("id", "DS-???")
    tasks = []

    for i, step in enumerate(steps[:max_tasks]):
        if isinstance(step, str):
            step_desc = step
            target = None
        elif isinstance(step, dict):
            step_desc = step.get("description", step.get("task", ""))
            target = step.get("target_file") or step.get("target_module")
        else:
            continue

        task_id = f"T-{batch_id}-ds-{ds_id.lower()}-s{i}"
        instruction = (
            f"設計ストック {ds_id} のステップ {i+1}/{len(steps)}\n\n"
            f"【全体目標】{ds_item.get('title', '')}\n"
            f"【このステップの作業】{step_desc}\n\n"
            f"【制約】\n"
            f"- 変更は最大3ファイルまで\n"
            f"- テストを1件以上追加すること\n"
            f"- このステップだけで独立してPASSすること"
        )

        tasks.append({
            "id": task_id,
            "group": "design_stock",
            "level": _difficulty_to_level(ds_item.get("difficulty", "C")),
            "target_module": target,
            "instruction": instruction,
            "status": "pending",
            "assigned_agent": None,
            "result": None,
            "design_stock_id": ds_id,
            "step_index": i,
        })

    return tasks


def _decompose_from_description(ds_item: dict, batch_id: str, 
                                 max_tasks: int) -> list[dict]:
    """description を解析してマイクロタスクに分解する。

    分解戦略:
    1. 難易度 S/A → 3タスク（設計→実装→テスト）
    2. 難易度 B → 2タスク（実装→テスト）
    3. 難易度 C → 1タスク（そのまま）
    """
    ds_id = ds_item.get("id", "DS-???")
    title = ds_item.get("title", "")
    description = ds_item.get("description", "")
    difficulty = ds_item.get("difficulty", "C")

    tasks = []

    if difficulty in ("S", "A"):
        # 3段階分解: 設計 → 実装 → テスト
        phases = [
            ("設計", f"以下の設計をPythonコードで実装する準備を行え。"
                     f"型定義(TypedDict/dataclass)、インターフェース、"
                     f"モジュール構成を決定し、スタブ実装を作成すること。\n\n"
                     f"対象: {title}\n詳細: {description}"),
            ("実装", f"以下の機能を実装せよ。設計済みのスタブが存在する場合は"
                     f"それを埋めること。存在しない場合は新規作成すること。\n\n"
                     f"対象: {title}\n詳細: {description}"),
            ("テスト", f"以下の機能のユニットテストを作成せよ。"
                      f"正常系・異常系・境界値を各1件以上含むこと。\n\n"
                      f"対象: {title}\n詳細: {description}"),
        ]
    elif difficulty == "B":
        phases = [
            ("実装", f"以下の機能を実装せよ。\n\n"
                     f"対象: {title}\n詳細: {description}"),
            ("テスト", f"以下の機能のユニットテストを作成せよ。\n\n"
                      f"対象: {title}\n詳細: {description}"),
        ]
    else:
        phases = [
            ("実装+テスト", f"以下の機能を実装し、テストも追加せよ。\n\n"
                           f"対象: {title}\n詳細: {description}"),
        ]

    for i, (phase_name, phase_desc) in enumerate(phases[:max_tasks]):
        task_id = f"T-{batch_id}-ds-{ds_id.lower()}-{phase_name}"
        instruction = (
            f"設計ストック {ds_id} — {phase_name}フェーズ "
            f"({i+1}/{len(phases)})\n\n"
            f"【作業指示】{phase_desc}\n\n"
            f"【制約】\n"
            f"- 変更は最大3ファイルまで\n"
            f"- このフェーズだけで独立してテストPASSすること"
        )

        tasks.append({
            "id": task_id,
            "group": "design_stock",
            "level": _difficulty_to_level(difficulty),
            "target_module": None,
            "instruction": instruction,
            "status": "pending",
            "assigned_agent": None,
            "result": None,
            "design_stock_id": ds_id,
            "step_index": i,
        })

    return tasks


def _difficulty_to_level(difficulty: str) -> str:
    """DS難易度をタスクレベルに変換する。"""
    return {"S": "L4", "A": "L3", "B": "L2", "C": "L1"}.get(difficulty, "L2")


def add_implementation_steps(ds_id: str, steps: list[str]) -> bool:
    """DS項目にimplementation_stepsを追加する。

    Opus設計フェーズで使用。設計結果をDS項目に書き込み、
    Flashが分解して実行する。

    Args:
        ds_id: 設計ストックID (例: "DS-014")
        steps: 実装ステップのリスト

    Returns:
        成功したかどうか
    """
    try:
        data = _read_json(_DESIGN_STOCK_PATH)
        items = data.get("stock_items", [])
        for item in items:
            if item.get("id") == ds_id:
                item["implementation_steps"] = steps
                item["steps_added_at"] = _now_iso()
                break
        else:
            return False

        _DESIGN_STOCK_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        return True
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to add steps to {ds_id}: {e}")
        return False


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def get_decomposition_summary(ds_item: dict) -> str:
    """DS項目の分解プレビューを表示する。"""
    tasks = decompose_ds_item(ds_item, "preview")
    lines = [f"DS {ds_item.get('id')} → {len(tasks)}タスクに分解:"]
    for t in tasks:
        lines.append(f"  [{t['id']}] {t['instruction'][:80]}...")
    return "\n".join(lines)


def decompose_large_change_task(task: dict, max_tasks: int = 3) -> list[dict]:
    """大規模変更が検出されたタスク（またはそのモジュールに対するタスク）を細分化する。

    元の1タスクを、設計、実装、テストの3つのマイクロタスクに分割する。
    """
    orig_id = task.get("id", "T-unknown")
    instruction = task.get("instruction", "")
    target = task.get("target_module")
    group = task.get("group", "unknown")
    level = task.get("level", "L1")

    # 3分割：設計 -> 実装 -> テスト
    sub_tasks = []
    phases = [
        ("設計", f"【大規模変更対策・ステップ1/3: 設計】\n"
                 f"モジュール `{target}` は過去に大規模な変更（3ファイル超）が記録されたか、または変更スコープが大きいため、細分化して対応します。\n"
                 f"まずは実装に先立ち、クラス/メソッド設計や型定義（TypedDict/dataclass）、モジュールインターフェースのみを定義し、スタブを作成してください。本体の実装は行わないでください。\n\n"
                 f"【元の指示】\n{instruction}"),
        ("実装", f"【大規模変更対策・ステップ2/3: 実装】\n"
                 f"モジュール `{target}` の機能実装を行います。設計ステップで定義されたスタブに具体的な処理を実装してください。変更ファイル数は最小限（原則1ファイル、最大3ファイル）に抑えてください。\n\n"
                 f"【元の指示】\n{instruction}"),
        ("テスト", f"【大規模変更対策・ステップ3/3: テスト】\n"
                   f"モジュール `{target}` に対する単体テストを追加してください。正常系、異常系、および極端な値（None, 空値など）に対する境界値テストを網羅してください。\n\n"
                   f"【元の指示】\n{instruction}")
    ]

    for idx, (phase_name, phase_desc) in enumerate(phases[:max_tasks]):
        sub_task_id = f"{orig_id}-split{idx}"
        sub_tasks.append({
            "id": sub_task_id,
            "group": group,
            "level": level,
            "target_module": target,
            "instruction": (
                f"{phase_desc}\n\n"
                f"【制約】\n"
                f"- プロダクションコードの変更は原則1ファイル、最大3ファイルまで。\n"
                f"- このステップだけで独立して pytest を PASS させること。\n"
                f"- 完了後、changed_files に変更したファイルを記録すること。"
            ),
            "status": "pending",
            "assigned_agent": None,
            "result": None,
            "created_at": _now_iso(),
            "split_from": orig_id,
            "step_index": idx,
        })
    return sub_tasks


def decompose_by_dependency(task: dict, workspace_path: str = None) -> list[dict]:
    """【実験的機能】依存度分析に基づく動的なタスク細分化。
    
    AST解析を行い、インポート依存度からタスクの順序制御と分割を決定する。
    """
    import ast
    import os
    target = task.get("target_module")
    if not target:
        return [task]

    # workspaceパス解決
    p = Path(workspace_path or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    target_path = p / "backend" / target
    if not target_path.exists():
        return [task]

    # 簡易AST解析によるインポート依存関係抽出
    dependencies = []
    try:
        content = target_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    dependencies.append(name.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    dependencies.append(node.module)
    except (SyntaxError, FileNotFoundError, PermissionError, UnicodeDecodeError, OSError) as e:
        logger.warning(f"AST parsing / dependency extraction failed for {target}: {e}")

    # 依存するモジュール数に基づいてタスクの分割度を決定 (実験的アプローチ)
    sub_tasks = []
    orig_id = task.get("id", "T-unknown")
    instruction = task.get("instruction", "")
    group = task.get("group", "unknown")
    level = task.get("level", "L1")

    if len(dependencies) >= 5:
        # 高依存タスク: 3分割（モック準備・インフラ調査 → 実装 → 統合テスト）
        phases = [
            ("依存解決", f"モジュール `{target}` は他モジュールへの依存が多いため（{len(dependencies)}件）、モック設定と依存インフラの調整から着手します。\n\n{instruction}"),
            ("本体実装", f"モジュール `{target}` のメインロジックを実装します。\n\n{instruction}"),
            ("統合検証", f"モジュール `{target}` と依存先との統合検証テストを実装し、全PASSを確認します。\n\n{instruction}")
        ]
    else:
        # 低依存タスク: 2分割（実装 → 単体テスト）
        phases = [
            ("実装", f"モジュール `{target}` の機能を実装します。\n\n{instruction}"),
            ("テスト", f"モジュール `{target}` の単体テストを実装します。\n\n{instruction}")
        ]

    for idx, (phase_name, phase_desc) in enumerate(phases):
        sub_task_id = f"{orig_id}-dep{idx}"
        sub_tasks.append({
            "id": sub_task_id,
            "group": group,
            "level": level,
            "target_module": target,
            "instruction": f"{phase_desc}\n\n【依存関係】: {', '.join(dependencies)}",
            "status": "pending",
            "assigned_agent": None,
            "result": None,
            "created_at": _now_iso(),
            "split_from": orig_id,
            "step_index": idx,
        })
    return sub_tasks

