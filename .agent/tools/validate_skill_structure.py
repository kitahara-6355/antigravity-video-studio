"""
validate_skill_structure.py - スキル構造検証ツール (Kitchen)

skill-linter スキルから呼び出され、対象スキルが Core Rules に準拠しているかを
7項目で自動検査し、結果をJSON形式で返す。

Usage:
    python tools/validate_skill_structure.py --target .agent/skills/<skill-name>

Output (JSON):
    {
        "status": "success",
        "skill_name": "example-skill",
        "checks": {
            "metadata_structure": {"pass": true, "detail": ""},
            "template_sections": {"pass": true, "detail": ""},
            "separation_check": {"pass": true, "detail": ""},
            "reference_check": {"pass": true, "detail": ""},
            "metrics_check": {"pass": true, "detail": ""},
            "persona_check": {"pass": true, "detail": ""},
            "tdd_check": {"pass": true, "detail": ""}
        },
        "all_passed": true
    }
"""
import argparse
import json
import os
import re
import sys


def check_metadata(skill_dir):
    """チェック1: metadata.yaml に name と description が存在するか"""
    meta_path = os.path.join(skill_dir, "metadata.yaml")
    if not os.path.exists(meta_path):
        return {"pass": False, "detail": "metadata.yaml が存在しません"}
    with open(meta_path, "r", encoding="utf-8") as f:
        content = f.read()
    has_name = bool(re.search(r"^name:", content, re.MULTILINE))
    has_desc = bool(re.search(r"^description:", content, re.MULTILINE))
    if has_name and has_desc:
        return {"pass": True, "detail": ""}
    missing = []
    if not has_name: missing.append("name")
    if not has_desc: missing.append("description")
    return {"pass": False, "detail": f"必須キーが不足: {', '.join(missing)}"}


def check_template_sections(skill_dir):
    """チェック2: SKILL.md に5つの必須セクションがあるか"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    required = ["Prerequisites", "Recipe", "Error Handling", "Persona", "References"]
    missing = [s for s in required if s not in content]
    if not missing:
        return {"pass": True, "detail": ""}
    return {"pass": False, "detail": f"不足セクション: {', '.join(missing)}"}


def check_separation(skill_dir):
    """チェック3: SKILL.md に絶対パスやOSコマンド直書きがないか"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    violations = []
    if re.search(r"[A-Z]:\\\\", content) or re.search(r"[A-Z]:\\[Uu]sers", content):
        violations.append("Windows絶対パスのハードコード検出")
    if re.search(r"^/usr/|^/home/", content, re.MULTILINE):
        violations.append("Unix絶対パスのハードコード検出")
    if not violations:
        return {"pass": True, "detail": ""}
    return {"pass": False, "detail": "; ".join(violations)}


def check_references(skill_dir):
    """チェック4: Markdownリンク参照を使用しているか"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    has_ref_section = "## References" in content
    has_links = bool(re.search(r"\[.*?\]\(file:///", content))
    if has_ref_section and has_links:
        return {"pass": True, "detail": ""}
    issues = []
    if not has_ref_section: issues.append("Referencesセクションなし")
    if not has_links: issues.append("file:///リンクなし")
    return {"pass": False, "detail": "; ".join(issues)}


def check_metrics(skill_dir):
    """チェック5: Recipe内に record_skill_metrics.py の呼び出しがあるか"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "record_skill_metrics.py" in content:
        return {"pass": True, "detail": ""}
    return {"pass": False, "detail": "メトリクス記録ステップ (record_skill_metrics.py) が見つかりません"}


def check_persona(skill_dir):
    """チェック6: Persona & Developer Rules セクションが存在するか"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    if "Persona" in content and "Developer Rules" in content:
        return {"pass": True, "detail": ""}
    return {"pass": False, "detail": "Persona & Developer Rules セクションが見つかりません"}


def check_tdd(skill_dir):
    """チェック7: TDD・検証要件（test, テスト, 検証のいずれかを含むか）"""
    skill_path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_path):
        return {"pass": False, "detail": "SKILL.md が存在しません"}
    with open(skill_path, "r", encoding="utf-8") as f:
        content = f.read()
    if re.search(r"(test|テスト|検証|確認|TDD|QA)", content, re.IGNORECASE):
        return {"pass": True, "detail": ""}
    return {"pass": False, "detail": "TDD・検証プロセスを示す記述 (test/検証 等) が見つかりません。テストファースト原則 (Rule 11) に違反しています。"}


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description="スキル構造検証ツール")
    parser.add_argument("--target", required=True, help="検証対象のスキルディレクトリパス")
    args = parser.parse_args()

    if not os.path.isdir(args.target):
        print(json.dumps({
            "status": "error",
            "message": f"ディレクトリが存在しません: {args.target}"
        }, ensure_ascii=False, indent=2))
        return 1

    skill_name = os.path.basename(args.target)
    checks = {
        "metadata_structure": check_metadata(args.target),
        "template_sections": check_template_sections(args.target),
        "separation_check": check_separation(args.target),
        "reference_check": check_references(args.target),
        "metrics_check": check_metrics(args.target),
        "persona_check": check_persona(args.target),
        "tdd_check": check_tdd(args.target),
    }

    all_passed = all(c["pass"] for c in checks.values())

    result = {
        "status": "success",
        "skill_name": skill_name,
        "checks": checks,
        "all_passed": all_passed
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
