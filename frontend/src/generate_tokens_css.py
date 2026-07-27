#!/usr/bin/env python3
"""
Antigravity Design System — デザイントークンCSS変数生成スクリプト

design_tokens.json から tokens.css を自動生成する。
JSONキーとCSS変数名の1:1対応を保証する。

使用方法:
    python generate_tokens_css.py

出力:
    tokens.css（同ディレクトリに生成）
"""
import json
import sys
from pathlib import Path
from datetime import datetime


def flatten_tokens(obj: dict, prefix: str = "") -> list[tuple[str, str]]:
    """JSONオブジェクトをフラットなCSS変数リストに変換する"""
    variables = []
    for key, value in obj.items():
        var_name = f"{prefix}-{key}" if prefix else f"--{key}"
        if isinstance(value, dict):
            variables.extend(flatten_tokens(value, var_name))
        else:
            variables.append((var_name, str(value)))
    return variables


def generate_css(tokens_path: Path) -> str:
    """design_tokens.jsonからtokens.cssを生成する"""
    with open(tokens_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    themes = data.get("themes", {})
    light = themes.get("light", {})
    dark = themes.get("dark", {})

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    version = data.get("$version", "1.0.0")
    description = data.get("$description", "Antigravity Design System")

    lines = [
        f"/* ━━━ {description} ━━━ */",
        f"/* Auto-generated from design_tokens.json v{version} */",
        f"/* Generated at: {timestamp} */",
        f"/* ⚠️ DO NOT EDIT MANUALLY — 変更は design_tokens.json で行うこと */",
        "",
        "/* ━━━ Light Theme (Default) ━━━ */",
        ":root {",
    ]

    # Light theme variables
    light_vars = flatten_tokens(light)
    for var_name, value in light_vars:
        lines.append(f"  {var_name}: {value};")

    lines.append("}")
    lines.append("")

    # Dark theme variables
    lines.append("/* ━━━ Dark Theme ━━━ */")
    lines.append("@media (prefers-color-scheme: dark) {")
    lines.append("  :root:not(.theme-light) {")

    dark_vars = flatten_tokens(dark)
    for var_name, value in dark_vars:
        lines.append(f"    {var_name}: {value};")

    lines.append("  }")
    lines.append("}")
    lines.append("")

    # Manual dark theme class
    lines.append("/* ━━━ Manual Dark Theme Override ━━━ */")
    lines.append(":root.theme-dark {")
    for var_name, value in dark_vars:
        lines.append(f"  {var_name}: {value};")
    lines.append("}")
    lines.append("")

    return "\n".join(lines)


def main():
    script_dir = Path(__file__).parent
    tokens_path = script_dir / "design_tokens.json"
    output_path = script_dir / "tokens.css"

    if not tokens_path.exists():
        print(f"❌ Error: {tokens_path} not found", file=sys.stderr)
        sys.exit(1)

    # Validate JSON structure
    with open(tokens_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    themes = data.get("themes", {})
    required_categories = ["color", "typography", "shadow", "radius", "motion"]

    for theme_name in ["light", "dark"]:
        theme = themes.get(theme_name)
        if not theme:
            print(f"❌ Error: theme '{theme_name}' not found", file=sys.stderr)
            sys.exit(1)

        for cat in required_categories:
            if cat not in theme:
                print(
                    f"❌ Error: category '{cat}' not found in theme '{theme_name}'",
                    file=sys.stderr,
                )
                sys.exit(1)

    # Generate CSS
    css_content = generate_css(tokens_path)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(css_content)

    # Count variables
    light_vars = flatten_tokens(themes["light"])
    dark_vars = flatten_tokens(themes["dark"])
    print(f"✅ Generated {output_path.name}")
    print(f"   Light theme: {len(light_vars)} variables")
    print(f"   Dark theme:  {len(dark_vars)} variables")
    print(f"   Categories:  {', '.join(required_categories)}")


if __name__ == "__main__":
    main()
