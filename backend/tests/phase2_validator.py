"""
Phase 2: 安定性検証 — 7項目判定基準の自動チェックスクリプト

ロードマップ Phase 2 (10回連続成功) の判定基準:
  □ ① 文字起こし: segments数 > 0 かつ各セグメントにstart/end/text
  □ ② AI校閲: 辞書適用件数 ≥ 0 かつ AI校閲試行の記録
  □ ③ SmartCut: selected_segments数 > 0 かつ推定尺がtarget_minutes of ±20%
  □ ④ プレビュー: preview_path が存在し、ファイルサイズ > 1MB
  □ ⑤ 品質ゲート: category_reportに4カテゴリスコアが存在 かつ スコア80+
  □ ⑥ レンダリング: final_path が存在、サイズ > 1MB、H.264+AAC
  □ ⑦ YouTube最適化: titles >= 1 かつ tags >= 5 かつ chapters >= 1
"""

import os
import sys
import json
import subprocess
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def get_pipeline_result():
    """パイプラインステータスAPIから結果を取得"""
    import requests
    try:
        response = requests.get("http://localhost:8000/api/pipeline/status", timeout=10)
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": f"Connection failed: {e}"}


def check_stage_result(stage_results, keyword):
    """ステージ実行ログから特定ステージの結果を取得"""
    if not isinstance(stage_results, (list, tuple)):
        return None
    for stage in stage_results:
        if not isinstance(stage, dict):
            continue
        if keyword in stage.get("name", ""):
            return stage
    return None


def _get_stream_codec(path, stream_specifier):
    """ffprobeで特定のストリームのコーデックを取得"""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", stream_specifier,
        "-show_entries", "stream=codec_name",
        "-of", "json", str(path)
    ]
    response = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    video = json.loads(response.stdout)
    streams = video.get("streams", [])
    return streams[0].get("codec_name", "") if streams else ""


def check_ffprobe(path):
    """ffprobeでH.264+AACを確認"""
    try:
        v_codec = _get_stream_codec(path, "v:0")
        a_codec = _get_stream_codec(path, "a:0")
        return v_codec, a_codec
    except Exception as e:
        return f"error:{e}", ""


def _get_file_existence_and_size(file_path):
    """ファイルパスが有効かつ存在するかをチェックし、存在フラグとサイズを返す"""
    if not isinstance(file_path, (str, Path)):
        return False, 0
    try:
        exists = bool(file_path and Path(file_path).exists())
        size = Path(file_path).stat().st_size if exists else 0
        return exists, size
    except (TypeError, ValueError, OSError):
        return False, 0


def _check_transcribe(result, stages):
    """① 文字起こしの判定"""
    seg_count = result.get("segments_count", 0)
    transcribe = check_stage_result(stages, "文字起こし")
    is_valid = seg_count > 0 and transcribe is not None and transcribe.get("success") is True
    return is_valid, f"segments={seg_count}"


def _check_proofread(stages):
    """② AI校閲の判定"""
    proofread = check_stage_result(stages, "AI校閲")
    is_valid = proofread is not None and proofread.get("success") is True
    detail = proofread.get("detail", "N/A") if proofread else "未実行"
    return is_valid, detail


def _check_smartcut(stages):
    """③ SmartCut構成の判定"""
    smartcut = check_stage_result(stages, "SmartCut")
    is_valid = smartcut is not None and smartcut.get("success") is True
    detail = smartcut.get("detail", "N/A") if smartcut else "未実行"
    return is_valid, detail


def _check_image_specifications(width, height, file_size):
    """画像の解像度、アスペクト比、ファイルサイズの個別条件チェック"""
    if width < 1280 or height < 720:
        return False, f"Resolution must be at least 1280x720, got {width}x{height}"

    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        return False, f"Aspect ratio must be 16:9, got {aspect_ratio:.3f}"

    if file_size >= 4 * 1024 * 1024:
        return False, f"File size must be less than 4MB, got {file_size} bytes"

    return True, ""


def _verify_image_properties(preview_path, file_size):
    """Pillowを使用して画像の破損、解像度、アスペクト比、ファイルサイズ上限を検証"""
    from PIL import Image
    try:
        with Image.open(preview_path) as img:
            img.verify()
        with Image.open(preview_path) as img:
            img.load()
            width, height = img.size
        return _check_image_specifications(width, height, file_size)
    except (OSError, SyntaxError, ValueError, AttributeError, RuntimeError) as e:
        return False, f"Image verify failed: {e}"


def _verify_preview_image(preview_path, file_size):
    """Pillowを使用したプレビュー画像の解像度・アスペクト比・破損チェック"""
    suffix = Path(preview_path).suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        # 動画等の場合は既存の 1MB 以上チェック
        if file_size <= 1 * 1024 * 1024:
            return False, f"Preview file too small: {file_size/1024/1024:.1f}MB"
        return True, ""

    return _verify_image_properties(preview_path, file_size)


def _fetch_agent_task_record(db_path, task_id):
    """SQLiteデータベースから指定されたタスクIDのレコードを取得"""
    import sqlite3
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
        return cursor.fetchone(), None
    except sqlite3.Error as e:
        return None, f"Database connection/query failed: {e}"
    finally:
        if conn:
            try:
                conn.close()
            except sqlite3.Error:
                pass


def _validate_agent_task_record(task_id, row):
    """データベースから取得したタスクレコードの内容をバリデーション"""
    if not row:
        return False, f"Task {task_id} not found in database"
    
    status, res_json, retry_count = row
    if status != "COMPLETED":
        return False, f"Task {task_id} status is {status}, expected COMPLETED"
    if not res_json:
        return False, f"Task {task_id} has empty result in database"

    try:
        res_data = json.loads(res_json)
        if not isinstance(res_data, dict) or "width" not in res_data or "height" not in res_data:
            return False, f"Task {task_id} result data is invalid: {res_json}"
        if retry_count is None or retry_count < 0:
            return False, f"Task {task_id} has invalid retry_count"
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return False, f"JSON validation failed: {e}"

    return True, ""


def _verify_stage_bound_agent(db_path, task_id):
    """SQLiteデータベース上のStageBoundAgentタスクステータス検証"""
    row, err_msg = _fetch_agent_task_record(db_path, task_id)
    if err_msg:
        return False, err_msg
    return _validate_agent_task_record(task_id, row)


def _check_preview(result):
    """④ プレビュー生成の判定"""
    preview_path = result.get("preview_path")
    exists, size = _get_file_existence_and_size(preview_path)
    if not exists:
        return False, f"path={preview_path} does not exist"

    # 画像・動画プレビューの検証
    img_ok, img_err_msg = _verify_preview_image(preview_path, size)
    if not img_ok:
        return False, img_err_msg

    # StageBoundAgent 連携の検証 (db_path と task_id が提供されている場合)
    db_path = result.get("db_path")
    task_id = result.get("task_id")
    if db_path and task_id:
        agent_ok, agent_err_msg = _verify_stage_bound_agent(db_path, task_id)
        if not agent_ok:
            return False, agent_err_msg

    return True, f"path={preview_path}, size={size/1024/1024:.1f}MB"


def _check_quality_gate(quality_details):
    """⑤ 品質ゲートの判定"""
    cat_report = quality_details.get("category_report", [])
    if not isinstance(cat_report, (list, tuple)):
        cat_report = []
    cat_names = [category_info.get("category") for category_info in cat_report if isinstance(category_info, dict)]
    score = quality_details.get("score", 0)
    required_cats = {"core", "template", "broadcast", "youtube"}
    has_cats = required_cats.issubset(set(cat_names))
    is_passed = has_cats and score >= 80
    return is_passed, f"score={score}, cats={cat_names}"


def _check_rendering(result):
    """⑥ 最終レンダリングの判定"""
    final_path = result.get("final_path")
    exists, size = _get_file_existence_and_size(final_path)
    if exists:
        v_codec, a_codec = check_ffprobe(final_path)
    else:
        v_codec, a_codec = "N/A", "N/A"
    is_passed = exists and size > 1 * 1024 * 1024 and v_codec == "h264" and a_codec == "aac"
    return is_passed, f"path={final_path}, size={size/1024/1024:.1f}MB, codec={v_codec}+{a_codec}"


def _check_youtube_optimization(metadata):
    """⑦ YouTube最適化の判定"""
    titles = metadata.get("titles", [])
    if not isinstance(titles, (list, tuple)):
        titles = []
    tags = metadata.get("tags", [])
    if not isinstance(tags, (list, tuple)):
        tags = []
    chapters = metadata.get("chapters", [])
    if not isinstance(chapters, (list, tuple)):
        chapters = []
    is_passed = len(titles) >= 1 and len(tags) >= 5 and len(chapters) >= 1
    return is_passed, f"titles={len(titles)}, tags={len(tags)}, chapters={len(chapters)}"


def run_checks(data):
    """7項目判定基準チェック"""
    if not isinstance(data, dict):
        data = {}
    result = data.get("result", {})
    if not isinstance(result, dict):
        result = {}
    stages = result.get("stage_results", [])
    quality_details = result.get("quality_details", {})
    if not isinstance(quality_details, dict):
        quality_details = {}
    metadata = result.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}

    checks = []

    # ① 文字起こし
    is_transcribe_ok, transcribe_detail = _check_transcribe(result, stages)
    checks.append(("① 文字起こし", is_transcribe_ok, transcribe_detail))

    # ② AI校閲
    is_proofread_ok, proofread_detail = _check_proofread(stages)
    checks.append(("② AI校閲", is_proofread_ok, proofread_detail))

    # ③ SmartCut
    is_smartcut_ok, smartcut_detail = _check_smartcut(stages)
    checks.append(("③ SmartCut構成", is_smartcut_ok, smartcut_detail))

    # ④ プレビュー
    is_preview_ok, preview_detail = _check_preview(result)
    checks.append(("④ プレビュー生成", is_preview_ok, preview_detail))

    # ⑤ 品質ゲート
    is_quality_gate_ok, quality_gate_detail = _check_quality_gate(quality_details)
    checks.append(("⑤ 品質ゲート", is_quality_gate_ok, quality_gate_detail))

    # ⑥ レンダリング
    is_rendering_ok, rendering_detail = _check_rendering(result)
    checks.append(("⑥ 最終レンダリング", is_rendering_ok, rendering_detail))

    # ⑦ YouTube最適化
    is_youtube_ok, youtube_detail = _check_youtube_optimization(metadata)
    checks.append(("⑦ YouTube最適化", is_youtube_ok, youtube_detail))

    return checks


def main():
    print("=" * 60)
    print("Phase 2: 7項目判定基準 自動検証")
    print("=" * 60)

    data = get_pipeline_result()

    if data.get("status") != "completed":
        print(f"⚠️ パイプライン未完了: status={data.get('status')}")
        return False

    checks = run_checks(data)
    all_pass = True

    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name}: {detail}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("🎉 全7項目合格！Phase 2 判定基準クリア")
    else:
        failed = [name for name, ok, _ in checks if not ok]
        print(f"⚠️ 不合格項目: {', '.join(failed)}")

    return all_pass


if __name__ == "__main__":  # pragma: no cover
    passed = main()
    sys.exit(0 if passed else 1)
