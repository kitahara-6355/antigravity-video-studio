import os
from pathlib import Path

# パス定義
PROJECT_ROOT = Path("C:/Users/PC_User/Desktop/script/video-automation")
TRANSITION_FILE = PROJECT_ROOT / "Human01_Official Artifact" / "開発推移表_20260501.md"
UNTRACKED_DIR = PROJECT_ROOT / "Human01_Official Artifact" / "未転記"

categories = {
    "監査・レビュー": "監査",
    "ウォークスルー": "実装",
    "実装計画": "計画",
    "分析・提案": "分析",
    "設計・アーキテクチャ": "設計"
}

lines_to_append = []
lines_to_append.append("\n## 第34期: 30サブエージェント自律品質監査および是正ロードマップ (2026-05-20)\n")
lines_to_append.append("> **テーマ**: 30サブエージェントによる1,500項目の自律的な動画品質監査、およびGate D是正ロードマップの推進\n")
lines_to_append.append("| 日付 | 種別 | 内容概要 | 関連アーティファクト |\n")
lines_to_append.append("|:---|:---|:---|:---|\n")

# 重複を排除しつつ走査
added_files = set()

# ファイル走査
for cat_folder, cat_name in categories.items():
    folder_path = UNTRACKED_DIR / cat_folder
    if folder_path.exists():
        # mdとresolvedファイルを検索
        files = list(folder_path.glob("*.resolved*")) + list(folder_path.glob("*.md")) + list(folder_path.glob("*.json"))
        for file in sorted(files, key=lambda x: x.name):
            filename = file.name
            if filename in added_files:
                continue
            added_files.add(filename)
            
            # 簡易説明
            summary = f"自動品質監査および是正プロセスに関連するドキュメント ({filename})"
            if "report_W" in filename or "report_1" in filename or "report_2" in filename or "report_3" in filename or "report_4" in filename or "report_5" in filename or "report_6" in filename or "report_7" in filename or "report_8" in filename or "report_9" in filename or "report_10" in filename or "report_11" in filename:
                summary = f"弱点補強エージェントによる自動品質監査レポート ({filename})"
            elif "gate_d_remediation" in filename:
                summary = f"Gate D是正ロードマップ詳細設計書 ({filename})"
            elif "walkthrough" in filename:
                summary = f"実装ウォークスルー ({filename})"
            elif "session_report" in filename:
                summary = f"セッション完了報告書 ({filename})"
            elif "handoff" in filename:
                summary = f"次ステップへの引き継ぎハンドオフプロンプト ({filename})"
            
            lines_to_append.append(f"| 05-20 | {cat_name} | {summary} | `{filename}` |\n")

# 推移表ファイルに追記
with open(TRANSITION_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# 既存のコンテンツの末尾に追記
new_content = content.rstrip() + "\n" + "".join(lines_to_append)

with open(TRANSITION_FILE, "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"✅ 開発推移表に {len(added_files)} 件のエントリを正常に追記しました。")
