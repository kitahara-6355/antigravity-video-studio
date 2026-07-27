"""
run_self_improvement_loop.py — 新自己改善サイクル（自律検品＆改善）実行スクリプト v2.0

動画生成パイプラインの実行、フレーム画像抽出、22種品質ゲートプラグインによる弱点分析、
およびパラメータ自動改善を合格基準（総合90点 + 全カテゴリ80点）に達するまで自動でループ実行する。

改善完了後にGit自動保存を行い、改善ループの証拠をバージョン管理する。
"""
import os
import sys
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("self_improvement_loop")

# パス設定
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
GRADED_PREVIEWS_DIR = BACKEND_DIR / "graded_previews"
sys.path.insert(0, str(BASE_DIR))

from backend.self_improvement_engine import SelfImprovementEngine


def run_pipeline() -> bool:
    """ステップ1: パイプラインによる動画生成を実行"""
    logger.info("🎬 動画生成パイプライン (auto_full_build) を実行中...")
    try:
        r = subprocess.run(
            [sys.executable, "backend/auto_full_build.py"],
            cwd=str(BASE_DIR),
            timeout=1200  # 最大20分
        )
        if r.returncode == 0:
            logger.info("✅ 動画生成パイプライン実行成功")
            # 生成された動画を vault-outputs/preview/ にコピー
            import shutil
            final_src = BASE_DIR / "soul_narrative_full_v1.mp4"
            if final_src.exists():
                dest_dir = BASE_DIR / "vault-outputs" / "preview"
                dest_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                dest_file = dest_dir / f"preview_{timestamp}.mp4"
                shutil.copy(final_src, dest_file)
                logger.info(f"💾 プレビューコピー作成成功: {dest_file.name}")
            else:
                logger.warning("⚠️ soul_narrative_full_v1.mp4 が見つかりませんでした。")
            return True
        else:
            logger.error(f"❌ 動画生成パイプライン実行失敗 (code={r.returncode})")
            return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.error(f"❌ 動画生成パイプライン実行エラー: {e}")
        return False


def run_frame_extraction() -> bool:
    """ステップ2: 検品用フレーム画像と index.json の抽出を実行

    出力先を backend/graded_previews/latest に変更。
    """
    logger.info("📸 検品用フレーム画像を抽出中...")
    output_dir = str(GRADED_PREVIEWS_DIR / "latest")
    try:
        r = subprocess.run(
            [sys.executable, "backend/generate_full_inspection.py",
             "--output-dir", output_dir,
             "--version", "latest"],
            cwd=str(BASE_DIR),
            timeout=300
        )
        if r.returncode == 0:
            logger.info(f"✅ フレーム画像抽出成功 → {output_dir}")
            return True
        else:
            logger.error(f"❌ フレーム画像抽出失敗 (code={r.returncode})")
            return False
    except (subprocess.SubprocessError, OSError) as e:
        logger.error(f"❌ フレーム画像抽出エラー: {e}")
        return False


def pipeline_callback() -> bool:
    """自己改善サイクルエンジンに渡す統合コールバック"""
    # 1. 動画生成
    if not run_pipeline():
        return False
    # 2. フレーム抽出
    if not run_frame_extraction():
        return False
    return True


def git_save_results(iteration: int, passed: bool):
    """改善結果をGitにコミットする"""
    logger.info("📦 改善結果を Git に保存中...")
    try:
        # graded_previews のメタデータと履歴のみコミット（画像は .gitignore）
        subprocess.run(
            ["git", "add",
             "backend/graded_previews/previews_metadata.json",
             "backend/graded_previews/weakness_analysis_report.md",
             "backend/graded_previews/weakness_analysis_history.json"],
            cwd=str(BASE_DIR),
            timeout=30
        )

        status = "PASS" if passed else "FAIL"
        commit_msg = (
            f"[self-improvement] iteration {iteration}: {status} — "
            f"自己改善ループ結果を保存"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg, "--allow-empty"],
            cwd=str(BASE_DIR),
            timeout=30
        )
        logger.info(f"✅ Git コミット完了: {commit_msg}")
    except (subprocess.SubprocessError, OSError) as e:
        logger.error(f"⚠️ Git 保存に失敗: {e}")


def main():
    logger.info("=" * 70)
    logger.info("🚀 新自己改善サイクル v2.0 (22種品質ゲート統合) を開始します")
    logger.info("   合格基準: 総合90点 + 全カテゴリ80点 (憲法§8.2準拠)")
    logger.info("=" * 70)

    # 改善エンジンのインスタンス化（出力先は graded_previews）
    engine = SelfImprovementEngine(
        artifacts_dir=str(GRADED_PREVIEWS_DIR)
    )

    # 改善ループの実行 (最大5回)
    success = engine.run_loop(pipeline_callback=pipeline_callback, max_iterations=5)

    # 履歴から最終イテレーション数を取得
    history_path = GRADED_PREVIEWS_DIR / "weakness_analysis_history.json"
    iteration_count = 0
    if history_path.exists():
        try:
            import json
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
                iteration_count = len(history)
        except Exception:
            pass

    # Git保存
    git_save_results(iteration_count, success)

    if success:
        logger.info("\n" + "=" * 70)
        logger.info("🎉 自己改善サイクルが合格基準に達し、正常に完了しました！")
        logger.info("   最終動画および品質レポートを確認してください。")
        logger.info(f"   レポートパス: {GRADED_PREVIEWS_DIR / 'weakness_analysis_report.md'}")
        logger.info("=" * 70)
    else:
        logger.warning("\n" + "=" * 70)
        logger.warning("⚠️ 改善ループが最大数に達したか、途中でエラーが発生しました。")
        logger.warning("   レポートの品質スコアおよび違反項目を確認してください。")
        logger.warning("=" * 70)


if __name__ == "__main__":
    main()
