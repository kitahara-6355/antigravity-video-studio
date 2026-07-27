"""
Phase 20 プレビューシステム デモ
字幕付きスクショ + AI確認リスト + テロップ提案
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\PC_User\Desktop\script\video-automation\backend")

from preview_system import SubtitlePreviewGenerator, TelopPreviewGenerator, PreviewReportGenerator, PreviewReport, ScenePreview
from subtitle_confirmation import SubtitleConfirmationChecker, ConfirmationReportGenerator

# パス設定
RAW_DIR = Path(r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画")
ARTIFACT_DIR = Path(r"C:\Users\PC_User\.gemini\antigravity\brain\0cc79527-362f-4816-aa0a-27c9f69dbaa5")
PREVIEWS_DIR = ARTIFACT_DIR / "previews"

# シーン定義
SCENES = [
    {
        "name": "シーン01_前編",
        "video": RAW_DIR / "シーン01_前編.mp4",
        "subtitle": RAW_DIR / "シーン01_前編_official.srt",
        "timestamps": ["00:00:05", "00:01:00", "00:05:00"]
    },
    {
        "name": "シーン02_ゲスト書道",
        "video": RAW_DIR / "シーン02_ゲスト書道.mp4",
        "subtitle": None,
        "timestamps": ["00:00:10", "00:00:30"]
    },
    {
        "name": "シーン03_後編01",
        "video": RAW_DIR / "シーン03_後編01.mp4",
        "subtitle": RAW_DIR / "シーン03_後編01_official.srt",
        "timestamps": ["00:00:05", "00:02:00"]
    },
    {
        "name": "シーン04_後編02",
        "video": RAW_DIR / "シーン04_後編02.mp4",
        "subtitle": RAW_DIR / "シーン04_後編02_official.srt",
        "timestamps": ["00:00:05", "00:02:00"]
    },
]


async def main():
    print("=" * 60)
    print("Phase 20: インタラクティブプレビューシステム デモ")
    print("=" * 60)
    
    # 初期化
    subtitle_gen = SubtitlePreviewGenerator(PREVIEWS_DIR)
    checker = SubtitleConfirmationChecker()
    confirm_report = ConfirmationReportGenerator()
    
    # レポート用データ
    scene_previews = []
    confirmation_scenes = []
    
    # 各シーンを処理
    for scene in SCENES:
        print(f"\n📷 {scene['name']}")
        
        # 1. 字幕付きスクショ生成
        print("  - 字幕付きスクショ生成中...")
        preview = subtitle_gen.generate_scene_previews(
            scene["name"],
            scene["video"],
            scene.get("subtitle"),
            scene["timestamps"]
        )
        scene_previews.append(preview)
        print(f"    ✅ {len(preview.screenshots)} 枚生成")
        
        # 2. AI字幕確認（字幕がある場合のみ）
        if scene.get("subtitle") and scene["subtitle"].exists():
            print("  - AI字幕確認実行中...")
            try:
                items = await checker.analyze_subtitle(scene["subtitle"])
                confirmation_scenes.append({
                    "name": scene["name"],
                    "items": items,
                    "screenshot": preview.screenshots[0]["path"] if preview.screenshots else None
                })
                print(f"    ✅ {len(items)} 件の確認項目を検出")
            except Exception as e:
                print(f"    ⚠️ AI確認スキップ: {e}")
    
    # 3. walkthrough形式レポート生成
    print("\n📝 レポート生成中...")
    
    # メインレポート
    md = "# 美麗書院 YouTube動画 プレビュー確認\n\n"
    md += "> **Phase 20: インタラクティブプレビューシステム**\n"
    md += "> 技術憲法9条（視覚確認プロトコル）準拠\n\n"
    md += "---\n\n"
    
    # シーン別字幕付きスクショ
    for preview in scene_previews:
        md += f"## {preview.scene_name}\n\n"
        
        if preview.screenshots:
            md += "````carousel\n"
            for i, ss in enumerate(preview.screenshots):
                if i > 0:
                    md += "<!-- slide -->\n"
                label = "字幕付き" if ss.get("with_subtitle") else "字幕なし"
                md += f"![{ss['timestamp']} {label}](file:///{ss['path'].replace(chr(92), '/')})\n"
            md += "````\n\n"
        
        md += "---\n\n"
    
    # AI確認リスト
    md += "## 🔍 AI字幕確認リスト\n\n"
    md += "> 固有名詞、不確かな表現、文脈的に不自然な箇所をAIが自動検出しました。\n\n"
    
    for scene in confirmation_scenes:
        md += confirm_report.generate(
            scene["name"],
            scene["items"]
        )
    
    # 操作説明
    md += "## 操作方法\n\n"
    md += "- **はい**: 現在のテキストを承認\n"
    md += "- **いいえ**: AIの提案を採用\n"
    md += "- **修正**: コメントで正しいテキストを入力\n\n"
    md += "---\n\n"
    md += "**確認後、ドラフト動画を生成しますか？**\n"
    
    # レポート保存
    output_path = ARTIFACT_DIR / "walkthrough.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)
    
    print(f"\n✅ レポート保存: {output_path}")
    print("\n" + "=" * 60)
    print("デモ完了！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
