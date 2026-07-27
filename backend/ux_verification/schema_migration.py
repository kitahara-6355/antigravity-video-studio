"""
L2ゴール v1.0→v2.0 マイグレーションユーティリティ

設計参照: pcqa_v2_deep_design.md § F. JSONスキーマ進化戦略
"""
import json
import copy
from pathlib import Path


STORIES_DIR = Path(__file__).parent / "stories"
MIGRATION_DATE = "2026-04-30"


def migrate_story_v1_to_v2(story_v1: dict) -> dict:
    """
    v1.0のストーリーJSONをv2.0に変換する。
    
    追加フィールド:
    - $schema_version: "2.0"
    - lifecycle: ストーリー全体のライフサイクル
    - persona_context: ペルソナ紐付け
    - data_requirements: データ接続先の予約（M3.8で実装）
    - inheritance: Step遷移時のポリシー
    - verification_items[].edge_cases: origin付き構造化（存在する場合）
    
    既存フィールドは一切変更しない（後方互換性保証）。
    """
    if not isinstance(story_v1, dict):
        return {}
    story_v2 = copy.deepcopy(story_v1)
    
    # スキーマバージョン
    story_v2.setdefault("$schema_version", "2.0")
    
    # ライフサイクル
    story_v2.setdefault("lifecycle", {})
    if isinstance(story_v2["lifecycle"], dict):
        story_v2["lifecycle"].setdefault("status", "active")
        story_v2["lifecycle"].setdefault("created_at", MIGRATION_DATE)
        story_v2["lifecycle"].setdefault("created_by", "migration_v1_to_v2")
        story_v2["lifecycle"].setdefault("activated_at", MIGRATION_DATE)
        story_v2["lifecycle"].setdefault("last_extended_at", None)
        story_v2["lifecycle"].setdefault("superseded_at", None)
        story_v2["lifecycle"].setdefault("superseded_by", None)
    
    # ペルソナコンテキスト
    story_v2.setdefault("persona_context", {})
    if isinstance(story_v2["persona_context"], dict):
        story_v2["persona_context"].setdefault("origin_step", 1)
        story_v2["persona_context"].setdefault("origin_persona", "step_001_mirei")
        story_v2["persona_context"].setdefault("required_by_steps", [1])
        story_v2["persona_context"].setdefault("complexity_by_step", {"1": "basic"})
    
    # データ要件（M3.8で具体化）
    story_v2.setdefault("data_requirements", [])
    
    # 継承ポリシー
    story_v2.setdefault("inheritance", {})
    if isinstance(story_v2["inheritance"], dict):
        story_v2["inheritance"].setdefault("mode", "inherit")
        story_v2["inheritance"].setdefault("parent_step", None)
        story_v2["inheritance"].setdefault("override_policy", "extend_only")
    
    # 将来接続用の空配列
    story_v2.setdefault("philosophy_derived_edges", [])
    story_v2.setdefault("analytics_derived_edges", [])
    story_v2.setdefault("major_update_refs", [])
    
    return story_v2


def is_v2(story: dict) -> bool:
    """ストーリーがv2.0スキーマかどうかを判定する"""
    if not isinstance(story, dict):
        return False
    return story.get("$schema_version") == "2.0"


def validate_v2_schema(story: dict) -> list[str]:
    """
    v2.0スキーマのバリデーション。
    
    Returns:
        エラーメッセージのリスト（空ならバリデーション成功）
    """
    errors = []
    
    if not isinstance(story, dict):
        return ["ストーリーデータが辞書（オブジェクト）ではありません"]
    
    # 必須フィールド（v1.0由来）
    for field in ["ux_id", "name", "description", "scenes", "verification_items"]:
        if field not in story:
            errors.append(f"必須フィールド '{field}' が存在しません")
    
    # v2.0新規必須フィールド
    if story.get("$schema_version") != "2.0":
        errors.append(f"$schema_version が '2.0' ではありません: {story.get('$schema_version')}")
    
    if "lifecycle" not in story:
        errors.append("lifecycle フィールドが存在しません")
    else:
        lc = story["lifecycle"]
        if not isinstance(lc, dict):
            errors.append("lifecycle フィールドが辞書ではありません")
        else:
            if lc.get("status") not in ("draft", "active", "extended", "superseded", "archived"):
                errors.append(f"lifecycle.status が無効です: {lc.get('status')}")
            if not lc.get("created_at"):
                errors.append("lifecycle.created_at が空です")
    
    if "persona_context" not in story:
        errors.append("persona_context フィールドが存在しません")
    else:
        pc = story["persona_context"]
        if not isinstance(pc, dict):
            errors.append("persona_context フィールドが辞書ではありません")
        else:
            if not isinstance(pc.get("origin_step"), int):
                errors.append(f"persona_context.origin_step が整数ではありません: {pc.get('origin_step')}")
            if not pc.get("origin_persona"):
                errors.append("persona_context.origin_persona が空です")
    
    if "data_requirements" not in story:
        errors.append("data_requirements フィールドが存在しません")
    
    if "inheritance" not in story:
        errors.append("inheritance フィールドが存在しません")
    else:
        inh = story["inheritance"]
        if not isinstance(inh, dict):
            errors.append("inheritance フィールドが辞書ではありません")
        else:
            if inh.get("mode") not in ("inherit", "extend", "override"):
                errors.append(f"inheritance.mode が無効です: {inh.get('mode')}")
    
    # scenes構造
    if "scenes" in story:
        scenes = story["scenes"]
        if not isinstance(scenes, list):
            errors.append("scenes フィールドがリストではありません")
        else:
            for i, scene in enumerate(scenes):
                if not isinstance(scene, dict):
                    errors.append(f"scenes[{i}] が辞書ではありません")
                else:
                    if "id" not in scene:
                        errors.append(f"scenes[{i}] に id がありません")
                    if "text" not in scene:
                        errors.append(f"scenes[{i}] に text がありません")
                    if "linked_items" not in scene:
                        errors.append(f"scenes[{i}] に linked_items がありません")
    
    # verification_items構造
    if "verification_items" in story:
        v_items = story["verification_items"]
        if not isinstance(v_items, list):
            errors.append("verification_items フィールドがリストではありません")
        else:
            for i, item in enumerate(v_items):
                if not isinstance(item, dict):
                    errors.append(f"verification_items[{i}] が辞書ではありません")
                else:
                    for field in ["id", "layer", "story_scene", "description", "test_method"]:
                        if field not in item:
                            errors.append(f"verification_items[{i}] に {field} がありません")
                    if "layer" in item and item["layer"] not in (1, 2, 3, 4, 5):
                        errors.append(f"verification_items[{i}] の layer が 1-5 の範囲外です: {item['layer']}")
    
    return errors


def migrate_all_stories(dry_run: bool = True) -> dict:
    """
    stories/ ディレクトリの全JSONファイルをv2.0にマイグレーションする。
    
    Args:
        dry_run: Trueの場合、ファイルを書き込まずに結果を返す
    
    Returns:
        マイグレーション結果のサマリー
    """
    results = {"migrated": [], "already_v2": [], "errors": []}
    
    for json_path in sorted(STORIES_DIR.glob("*.json")):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                story = json.load(f)
                if not isinstance(story, dict):
                    results["errors"].append({
                        "file": json_path.name,
                        "errors": ["ストーリーデータが辞書型ではありません"],
                    })
                    continue
        except (json.JSONDecodeError, OSError, TypeError, AttributeError) as e:
            results["errors"].append({
                "file": json_path.name,
                "errors": [f"ファイルの読み込みまたはJSONの解析に失敗しました: {str(e)}"],
            })
            continue
        
        if is_v2(story):
            results["already_v2"].append(json_path.name)
            continue
        
        story_v2 = migrate_story_v1_to_v2(story)
        
        # バリデーション
        validation_errors = validate_v2_schema(story_v2)
        if validation_errors:
            results["errors"].append({
                "file": json_path.name,
                "errors": validation_errors,
            })
            continue
        
        if not dry_run:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(story_v2, f, ensure_ascii=False, indent=2)
                f.write("\n")
        
        results["migrated"].append(json_path.name)
    
    return results


def validate_persona_json(persona_path: Path) -> list[str]:
    """ペルソナJSONのバリデーション"""
    errors = []
    
    if not persona_path.exists():
        return [f"ファイルが存在しません: {persona_path}"]
    
    try:
        with open(persona_path, "r", encoding="utf-8") as f:
            persona = json.load(f)
            if not isinstance(persona, dict):
                return ["ペルソナデータが辞書型ではありません"]
    except (json.JSONDecodeError, OSError, TypeError, AttributeError) as e:
        return [f"ファイルの読み込みまたはJSONの解析に失敗しました: {str(e)}"]
    
    for field in ["step", "persona_id", "name", "profile", "ux_principles",
                   "maturity_dimensions", "ux_stories"]:
        if field not in persona:
            errors.append(f"必須フィールド '{field}' が存在しません")
    
    if "step" in persona and not isinstance(persona["step"], int):
        errors.append(f"step が整数ではありません: {persona['step']}")
    
    if "maturity_dimensions" in persona:
        md = persona["maturity_dimensions"]
        if not isinstance(md, dict):
            errors.append("maturity_dimensions が辞書ではありません")
        else:
            expected = {"D1_activity", "D2_judgment", "D3_philosophy", "D4_youtube", "D5_proficiency"}
            actual = set(md.keys())
            missing = expected - actual
            if missing:
                errors.append(f"maturity_dimensions に不足: {missing}")
    
    if "ux_stories" in persona:
        if not isinstance(persona["ux_stories"], list) or len(persona["ux_stories"]) == 0:
            errors.append("ux_stories が空またはリストではありません")
    
    return errors


if __name__ == "__main__":
    import sys
    
    dry_run = "--apply" not in sys.argv
    
    print(f"=== L2ゴール v1.0→v2.0 マイグレーション {'(ドライラン)' if dry_run else '(実行)'}===")
    results = migrate_all_stories(dry_run=dry_run)
    
    print(f"\nマイグレーション対象: {len(results['migrated'])}件")
    for f in results["migrated"]:
        print(f"  ✅ {f}")
    
    print(f"\n既にv2.0: {len(results['already_v2'])}件")
    for f in results["already_v2"]:
        print(f"  ⏭️ {f}")
    
    if results["errors"]:
        print(f"\nエラー: {len(results['errors'])}件")
        for err in results["errors"]:
            print(f"  ❌ {err['file']}: {err['errors']}")
