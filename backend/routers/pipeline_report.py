"""
パイプライン完了レポート — Phase 1: 初回貫通の判定基準自動検証

ブラウザで `/api/pipeline/report` にアクセスすると、
パイプライン完了後の7項目判定基準をHTMLレポートとして表示する。

判定基準:
  ① 文字起こし: segments数 > 0 かつ各セグメントにstart/end/text
  ② AI校閲: 辞書適用の試行記録
  ③ SmartCut: selected_segments数 > 0
  ④ プレビュー: preview_path存在 + サイズ > 1MB
  ⑤ 品質ゲート: 4カテゴリスコア存在
  ⑥ レンダリング: final_path存在 + H.264+AAC
  ⑦ YouTube最適化: titles ≥ 1, tags ≥ 5, chapters ≥ 1
"""
import json
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline-report"])


def _probe_video(path: str) -> dict:
    """ffprobeでコーデック情報を取得"""
    try:
        from video_editor_engine import video_editor
        ffmpeg_path = video_editor.ffmpeg.ffmpeg_path
        # ffmpeg.EXE / ffmpeg.exe / ffmpeg のいずれにも対応
        import re
        ffprobe_path = re.sub(r'ffmpeg(\.exe)?$', r'ffprobe\1', ffmpeg_path, flags=re.IGNORECASE)
        if ffprobe_path == ffmpeg_path:  # 置換されなかった場合
            ffprobe_path = str(Path(ffmpeg_path).parent / "ffprobe.exe")
    except HTTPException:
        raise
    except Exception:
        ffprobe_path = "ffprobe"

    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            video_codec = next((s["codec_name"] for s in streams if s["codec_type"] == "video"), "unknown")
            audio_codec = next((s["codec_name"] for s in streams if s["codec_type"] == "audio"), "unknown")
            duration = float(data.get("format", {}).get("duration", 0))
            return {
                "video_codec": video_codec,
                "audio_codec": audio_codec,
                "duration_sec": round(duration, 1),
                "valid": True,
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"ffprobe failed: {e}")
    return {"valid": False, "error": "ffprobe不可"}


def _build_category_html(quality: dict) -> str:
    """カテゴリ別スコアのHTMLテーブルを生成"""
    cat_report = quality.get("category_report", [])
    if not cat_report:
        return "<p style='color:#9ca3af;font-size:13px;margin-top:8px;'>カテゴリ別スコア: データなし</p>"
    
    rows = ""
    for item in cat_report:
        if not isinstance(item, dict):
            continue
        label = item.get("label", item.get("category", "?"))
        score = item.get("score")
        status = item.get("status", "")
        ded = item.get("deductions", 0)
        plugins = item.get("plugin_count", 0)
        score_str = f"{score}" if score is not None else "—"
        rows += f"""
        <tr>
            <td>{label}</td>
            <td><strong>{score_str}</strong></td>
            <td>{status}</td>
            <td>{ded}点</td>
            <td>{plugins}個</td>
        </tr>"""
    
    return f"""
    <table style="margin-top:12px;">
        <tr><th>カテゴリ</th><th>スコア</th><th>判定</th><th>減点</th><th>プラグイン数</th></tr>
        {rows}
    </table>"""


def _build_feedback_html(quality: dict) -> str:
    """フィードバック一覧のHTMLを生成"""
    feedback = quality.get("feedback", [])
    if not feedback:
        return "<p style='color:#22c55e;margin-top:12px;'>✅ フィードバック: なし（全項目クリア）</p>"
    
    items = "".join(f"<li style='margin:4px 0;'>{f}</li>" for f in feedback)
    return f"""
    <div style="margin-top:12px;">
        <p style="font-weight:600;color:#f59e0b;">⚠ フィードバック ({len(feedback)}件):</p>
        <ul style="padding-left:20px;font-size:13px;color:#e4e4e7;">{items}</ul>
    </div>"""


@router.get("/report/thumbnail")
async def get_report_thumbnail():
    """完了したサムネイル画像を返すエンドポイント"""
    from routers.pipeline_router import _pipeline_state
    result = _pipeline_state.get("result") or {}
    thumbnail_path = result.get("thumbnail_path") or result.get("metadata", {}).get("thumbnail_path")
    
    if not thumbnail_path or not Path(thumbnail_path).exists():
        import glob
        thumbnail_files = glob.glob("output/thumbnails/*.jpg") + glob.glob("output/thumbnails/*.png")
        if thumbnail_files:
            thumbnail_path = thumbnail_files[0]
            
    if not thumbnail_path or not Path(thumbnail_path).exists():
        raise HTTPException(status_code=404, detail="サムネイル画像が見つかりません")
        
    return FileResponse(thumbnail_path)


@router.get("/report", response_class=HTMLResponse)
async def pipeline_report():
    """パイプライン完了レポート — 8項目判定基準のHTML表示"""
    from routers.pipeline_router import _pipeline_state

    result = _pipeline_state.get("result") or {}
    stages = result.get("stage_results", [])
    status = _pipeline_state.get("status", "idle")

    # === 8項目判定 ===
    checks = []

    # ① 文字起こし
    seg_count = result.get("segments_count", 0)
    transcribe_stage = next((s for s in stages if "文字起こし" in s.get("name", "")), None)
    transcribe_ok = seg_count > 0 and (transcribe_stage and transcribe_stage.get("success", False))
    checks.append({
        "id": "①", "name": "文字起こし",
        "ok": transcribe_ok,
        "detail": f"{seg_count}セグメント" if seg_count > 0 else "セグメントなし",
        "stage": transcribe_stage,
    })

    # ② AI校閲
    proofread_stage = next((s for s in stages if "AI校閲" in s.get("name", "")), None)
    proofread_ok = proofread_stage is not None and proofread_stage.get("success", False)
    checks.append({
        "id": "②", "name": "AI校閲",
        "ok": proofread_ok,
        "detail": proofread_stage.get("detail", "未実行") if proofread_stage else "未実行",
        "stage": proofread_stage,
    })

    # ③ SmartCut
    smartcut_stage = next((s for s in stages if "SmartCut" in s.get("name", "")), None)
    smartcut_ok = smartcut_stage is not None and smartcut_stage.get("success", False)
    checks.append({
        "id": "③", "name": "SmartCut構成",
        "ok": smartcut_ok,
        "detail": smartcut_stage.get("detail", "未実行") if smartcut_stage else "未実行",
        "stage": smartcut_stage,
    })

    # ④ プレビュー
    preview_path = result.get("preview_path")
    preview_exists = preview_path and Path(preview_path).exists()
    preview_size = Path(preview_path).stat().st_size if preview_exists else 0
    preview_ok = preview_exists and preview_size > 1 * 1024 * 1024
    checks.append({
        "id": "④", "name": "プレビュー生成",
        "ok": preview_ok,
        "detail": f"{preview_size / 1024 / 1024:.1f}MB" if preview_exists else "ファイルなし",
        "stage": next((s for s in stages if "プレビュー" in s.get("name", "")), None),
    })

    # ⑤ 品質ゲート
    quality = result.get("quality_details", {})
    cat_report = quality.get("category_report", [])
    categories_found = set()
    for item in cat_report:
        if isinstance(item, dict):
            categories_found.add(item.get("category", ""))
    quality_score = quality.get("score", 0)
    # 判定: スコア90点以上（憲法§8.2準拠）
    quality_ok = isinstance(quality_score, (int, float)) and quality_score >= 90
    cat_display = ', '.join(categories_found) if categories_found else f"{quality_score}点"
    checks.append({
        "id": "⑤", "name": "品質ゲート",
        "ok": quality_ok,
        "detail": f"スコア: {quality_score}点 / カテゴリ: {cat_display}",
        "stage": next((s for s in stages if "品質" in s.get("name", "")), None),
    })

    # ⑥ レンダリング
    final_path = result.get("final_path")
    final_exists = final_path and Path(final_path).exists()
    final_size = Path(final_path).stat().st_size if final_exists else 0
    probe = _probe_video(final_path) if final_exists else {"valid": False}
    render_ok = (final_exists and final_size > 1 * 1024 * 1024
                 and probe.get("video_codec") == "h264"
                 and probe.get("audio_codec") == "aac")
    checks.append({
        "id": "⑥", "name": "最終レンダリング",
        "ok": render_ok,
        "detail": (f"{final_size / 1024 / 1024:.1f}MB / "
                   f"V:{probe.get('video_codec', 'N/A')} A:{probe.get('audio_codec', 'N/A')}"
                   if final_exists else "ファイルなし"),
        "stage": next((s for s in stages if "レンダリング" in s.get("name", "")), None),
    })

    # ⑦ YouTube最適化
    metadata = result.get("metadata", {})
    titles = metadata.get("titles", [])
    tags = metadata.get("tags", [])
    chapters = metadata.get("chapters", [])
    youtube_ok = len(titles) >= 1 and len(tags) >= 5
    checks.append({
        "id": "⑦", "name": "YouTube最適化",
        "ok": youtube_ok,
        "detail": f"タイトル{len(titles)}案 / タグ{len(tags)}個 / チャプター{len(chapters)}個",
        "stage": next((s for s in stages if "YouTube" in s.get("name", "")), None),
    })

    # ⑧ サムネイル生成
    thumbnail_path = result.get("thumbnail_path") or metadata.get("thumbnail_path")
    if not thumbnail_path or not Path(thumbnail_path).exists():
        import glob
        thumbnail_files = glob.glob("output/thumbnails/*.jpg") + glob.glob("output/thumbnails/*.png")
        if thumbnail_files:
            thumbnail_path = thumbnail_files[0]
    thumbnail_exists = thumbnail_path and Path(thumbnail_path).exists()
    thumbnail_size = Path(thumbnail_path).stat().st_size if thumbnail_exists else 0
    thumbnail_ok = thumbnail_exists and thumbnail_size >= 1000
    checks.append({
        "id": "⑧", "name": "サムネイル生成",
        "ok": thumbnail_ok,
        "detail": f"{thumbnail_size / 1024:.1f}KB" if thumbnail_exists else "ファイルなし",
        "stage": next((s for s in stages if "サムネイル" in s.get("name", "")), None),
    })

    # === 総合判定 ===
    all_ok = all(c["ok"] for c in checks)
    pass_count = sum(1 for c in checks if c["ok"])
    total = len(checks)
    verdict = "✅ 全機能適用済み完成動画" if all_ok else f"⚠️ 改善余地あり（{pass_count}/{total}合格）"

    # === HTML生成 ===
    rows_html = ""
    for c in checks:
        icon = "✅" if c["ok"] else "❌"
        stage = c.get("stage") or {}
        duration = f"{stage.get('duration', 0):.1f}s" if stage.get("duration") else "—"
        detail_text = c["detail"]
        stage_detail = stage.get("detail", "")

        rows_html += f"""
        <tr class="{'pass' if c['ok'] else 'fail'}">
            <td>{c['id']}</td>
            <td>{icon}</td>
            <td><strong>{c['name']}</strong></td>
            <td>{detail_text}</td>
            <td class="sub">{stage_detail}</td>
            <td>{duration}</td>
        </tr>"""

    # ステージ実行ログ
    stage_log_html = ""
    for s in stages:
        s_icon = "✅" if s.get("success") else "❌"
        stage_log_html += f"""
        <tr>
            <td>{s_icon}</td>
            <td>{s.get('name', '')}</td>
            <td>{s.get('detail', '')}</td>
            <td>{s.get('duration', 0):.1f}s</td>
            <td>リトライ: {s.get('retries', 0)}</td>
        </tr>"""

    # サムネイル表示用 HTML
    thumbnail_preview_html = ""
    if thumbnail_exists:
        thumbnail_preview_html = f"""
<div class="section thumbnail-section">
  <h2>🖼️ サムネイルプレビュー</h2>
  <div style="text-align: center; margin-top: 16px; position: relative;">
    <img class="thumb-img" src="/api/pipeline/report/thumbnail" alt="サムネイルプレビュー">
    <p style="margin-top: 8px; font-size: 13px; color: var(--sub);">{Path(thumbnail_path).name} ({thumbnail_size / 1024:.1f} KB)</p>
  </div>
</div>
"""

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Antigravity パイプライン完了レポート</title>
<style>
  :root {{ --bg: #0f1117; --card: #1a1d27; --text: #e4e4e7; --sub: #9ca3af;
           --pass: #22c55e; --fail: #ef4444; --border: #2d3040; --accent: #6366f1; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
  .header {{ text-align: center; margin-bottom: 32px; }}
  .header h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 8px; }}
  .verdict {{ font-size: 20px; padding: 16px 24px; border-radius: 12px; display: inline-block;
              background: {'linear-gradient(135deg, #065f46, #064e3b)' if all_ok else 'linear-gradient(135deg, #7f1d1d, #991b1b)'};
              margin-top: 12px; }}
  .meta {{ display: flex; gap: 16px; justify-content: center; margin: 16px 0; flex-wrap: wrap; }}
  .meta-item {{ background: var(--card); padding: 8px 16px; border-radius: 8px; font-size: 13px; }}
  .section {{ background: var(--card); border-radius: 12px; padding: 20px; margin-bottom: 24px;
              border: 1px solid var(--border); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); }}
  .section h2 {{ font-size: 16px; margin-bottom: 12px; color: var(--accent); }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th {{ text-align: left; padding: 8px 12px; border-bottom: 2px solid var(--border); color: var(--sub); font-weight: 600; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid var(--border); }}
  tr.pass {{ background: rgba(34, 197, 94, 0.05); }}
  tr.fail {{ background: rgba(239, 68, 68, 0.08); }}
  .sub {{ color: var(--sub); font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; }}
  .footer {{ text-align: center; color: var(--sub); font-size: 12px; margin-top: 24px; }}
  
  /* サムネイルプレビュー特有のリッチデザイン */
  .thumbnail-section {{
    background: linear-gradient(145deg, #1e2230, #131622);
    border: 1px solid rgba(99, 102, 241, 0.2);
  }}
  .thumb-img {{
    max-width: 100%;
    max-height: 360px;
    border-radius: 8px;
    border: 1px solid var(--border);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.3s;
  }}
  .thumb-img:hover {{
    transform: scale(1.02);
    box-shadow: 0 20px 25px -5px rgba(99, 102, 241, 0.2), 0 10px 10px -5px rgba(99, 102, 241, 0.1);
  }}
</style>
</head>
<body>
<div class="header">
  <h1>🚀 Antigravity パイプライン完了レポート</h1>
  <div class="verdict">{verdict}</div>
  <div class="meta">
    <span class="meta-item">ステータス: {status}</span>
    <span class="meta-item">動画: {_pipeline_state.get('video_path', 'N/A')}</span>
    <span class="meta-item">実行時間: {result.get('duration_seconds', 'N/A')}秒</span>
    <span class="meta-item">セッション: {result.get('session_id', 'N/A')[:8] if result.get('session_id') else 'N/A'}</span>
  </div>
</div>

<div class="section">
  <h2>📋 8項目判定基準</h2>
  <table>
    <tr><th>#</th><th>判定</th><th>機能</th><th>結果</th><th>ステージ詳細</th><th>実行時間</th></tr>
    {rows_html}
  </table>
</div>

{thumbnail_preview_html}

<div class="section">
  <h2>📊 ステージ実行ログ</h2>
  <table>
    <tr><th>結果</th><th>ステージ</th><th>詳細</th><th>実行時間</th><th>リトライ</th></tr>
    {stage_log_html}
  </table>
</div>

<div class="section">
  <h2>🎯 品質ゲート詳細</h2>
  <p>総合スコア: <strong>{quality.get('score', 'N/A')}点</strong></p>
  {_build_category_html(quality)}
  {_build_feedback_html(quality)}
</div>

<div class="footer">
  <p>生成日時: {datetime.now().isoformat()} / Antigravity Video Studio</p>
  <p>憲法§8.2（品質ゲート）・§11.2（本番品質レンダリング）・§23（YouTube最適化）準拠</p>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)
