"""リンク検証・イベント記録モジュール — DS-038 レポート分割 Phase 2

generate_subagent_reports.py から抽出された、ダッシュボードリンク検証
およびイベントログの記録・読み取りのためのユーティリティ関数群。
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import os
import json
import re
import sys
from datetime import datetime, timezone, timedelta

try:
    from backend.agents.orchestration.jst_time import now_jst, parse_jst
except ImportError:  # 単体モジュールとして読み込まれた場合
    from jst_time import now_jst, parse_jst

# パスの定義
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATION_DIR = os.path.dirname(__file__)
FLASH_SESSION_PATH = str(_writable_path("backend/agents/orchestration/flash_session.json"))
FLASH_REPORTS_PATH = os.path.join(ORCHESTRATION_DIR, "flash_reports.jsonl")


# リンクとして扱わない（実ファイルを指さない）スキーム
_NON_FILE_SCHEMES = ("http://", "https://", "mailto:", "#", "data:", "tel:")

# URL エンコードしない文字。'/' は区切りとして残す
_SAFE_CHARS = "/@!$&'()+,;=-._~"


def _encode_path(rel_posix: str) -> str:
    """パス区切りは残したまま、スペースと非ASCII文字を URL エンコードする。"""
    from urllib.parse import quote

    return quote(rel_posix, safe=_SAFE_CHARS)


def _as_file_url(abs_path: str) -> str:
    """リポジトリ外のファイル用。絶対パスを file:/// リンクにする。"""
    from urllib.parse import quote

    path_str = abs_path.replace(os.path.sep, "/")
    encoded = quote(path_str, safe="/:@!$&'()+,;=-._~")
    return ("file://" + encoded) if path_str.startswith("/") else ("file:///" + encoded)


def get_rel_link(abs_path: str) -> str:
    """ファイルパスを **リポジトリルート相対** のリンクに変換する。

    以前は生成した環境の絶対パス（`file:///C:/Users/.../video-automation/...`）を
    書き込んでいた。取り違えのない書き方として導入されたものだが、別のチェックアウトや
    CI(Linux)、配布先ではリンクが 1 本も解決できないという環境依存を持ち込んでいた。

    リポジトリ内のファイルはリポジトリ相対で正確に書けるため、相対リンクを返す。
    書き込み先の README に合わせた付け替えは `localize_links()` が行う。

    リポジトリ外のファイル（Antigravity の brain ディレクトリ等）は相対で書けないため、
    従来どおり file:/// にフォールバックする。

    Args:
        abs_path: システム上の絶対パス

    Returns:
        str: URLエンコードされたリポジトリ相対リンク（リポジトリ外なら file:/// リンク）
    """
    if not isinstance(abs_path, str) or not abs_path:
        return ""

    try:
        rel = os.path.relpath(os.path.abspath(abs_path), WORKSPACE_DIR)
    except (ValueError, OSError):
        # 別ドライブなど、相対パスを作れない場合
        return _as_file_url(abs_path)

    if rel.startswith(".."):
        return _as_file_url(abs_path)

    return _encode_path(rel.replace(os.path.sep, "/"))


def localize_links(markdown: str, target_dir: str) -> str:
    """リポジトリ相対のリンクを、書き込み先ファイルから見た相対リンクに付け替える。

    同じ本文を深さの違う 2 つの README（リポジトリルート / ダッシュボード）へ
    書き出すため、書き込み先ごとに前置きを調整する。

    Args:
        markdown: `get_rel_link()` 由来のリンクを含む Markdown
        target_dir: 書き込み先ファイルが置かれるディレクトリ

    Returns:
        str: 付け替え後の Markdown
    """
    if not isinstance(markdown, str) or not isinstance(target_dir, str):
        return markdown

    import posixpath

    # 書き込み先をリポジトリ相対（エンコード済み）で表す
    base = os.path.relpath(os.path.abspath(target_dir), WORKSPACE_DIR).replace(os.path.sep, "/")
    if base == ".":
        return markdown
    base = _encode_path(base)

    def _replace(m):
        link = m.group(1)
        if link.startswith(_NON_FILE_SCHEMES) or link.startswith("file:"):
            return m.group(0)
        # エンコード済みのまま計算できる（%XX に '/' は現れない）
        return "](" + posixpath.relpath(link, base) + ")"

    return re.sub(r"\]\(([^)\s]+)\)", _replace, markdown)


def _link_target_exists(local_path: str) -> bool:
    """リンク先が実在するかを、記録された絶対パスと現在のワークスペースの両方で判定する。

    ダッシュボードのリンクは生成した環境の絶対パス
    （例: `C:/Users/.../script/video-automation/...`）で記録される。
    別のチェックアウト（worktree、CI の Linux ランナー等）ではこの絶対パスは存在しないが、
    リンク切れではなく **パスの前置部分が違うだけ** なので、リポジトリ相対で解決し直す。

    判定順:
      1. 記録された絶対パスがそのまま存在すればOK（生成環境ではこれで一致する）
      2. パス末尾から順に、現在のワークスペース直下で最長一致する部分パスを探す

    2 の誤検出（たまたま同名ファイルがある）を避けるため、2セグメント以上の一致のみ認める。

    Args:
        local_path: file:/// を除去・デコード済みのローカルパス

    Returns:
        bool: リンク先が解決できれば True
    """
    if os.path.exists(local_path):
        return True

    # ドライブレター（"C:"）を落として、区切り文字を正規化する
    parts = [p for p in local_path.replace("\\", "/").split("/") if p and not p.endswith(":")]
    # 長い部分パスから順に試す = ワークスペース相対の本来の位置を優先する
    for i in range(len(parts) - 1):
        if os.path.exists(os.path.join(WORKSPACE_DIR, *parts[i:])):
            return True
    return False


def validate_dashboard_links(readme_path: str) -> list[str]:
    """ダッシュボード内の全リンクが実在するファイルを指しているか検証する。

    相対リンクは **その Markdown ファイルの位置** を起点に解決する。
    外部 URL・アンカーは検証対象外。移行期間中の古い `file:///` 絶対リンクは
    `_link_target_exists()` で解決を試みる。

    Args:
        readme_path: 検証対象のMarkdownファイルの絶対パス

    Returns:
        list[str]: リンク切れのURLリスト（空なら全リンク正常）
    """
    if not isinstance(readme_path, str):
        return []

    from urllib.parse import unquote

    try:
        with open(readme_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return []

    base_dir = os.path.dirname(os.path.abspath(readme_path))
    links = re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", content)
    broken = []
    for link in links:
        if link.startswith(_NON_FILE_SCHEMES):
            continue
        if link.startswith("file:"):
            # 旧形式（生成環境の絶対パス）
            local_path = unquote(link.replace("file:///", "").replace("file://", ""))
            if not _link_target_exists(local_path.replace("/", os.sep)):
                broken.append(link)
            continue
        target = unquote(link.split("#", 1)[0])
        if not target:
            continue
        if not os.path.exists(os.path.join(base_dir, target.replace("/", os.sep))):
            broken.append(link)
    return broken


def _record_event_if_changed(event_log_path: str, lc_status: str, overall: str, now_jst: str) -> None:
    """状態変化があった場合のみイベントをログに永続記録する。

    Args:
        event_log_path: イベントログファイルのパス
        lc_status: ライフサイクルステータス
        overall: 全体ステータス
        now_jst: 現在のJST時刻文字列
    """
    # 前回のイベントを読み取り
    last_lc = ""
    last_overall = ""
    if os.path.exists(event_log_path):
        try:
            with open(event_log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    last = json.loads(lines[-1].strip())
                    if isinstance(last, dict):
                        last_lc = last.get("lifecycle", "")
                        last_overall = last.get("health", "")
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            pass

    # 変化があれば記録
    if lc_status != last_lc or overall != last_overall:
        event = {
            "timestamp": now_jst,
            "lifecycle": lc_status,
            "health": overall,
            "change": []
        }
        if lc_status != last_lc:
            event["change"].append(f"lifecycle: {last_lc or 'N/A'} → {lc_status}")
        if overall != last_overall:
            short_prev = "HEALTHY" if "HEALTHY" in last_overall else ("UNHEALTHY" if "UNHEALTHY" in last_overall else last_overall[:20] if last_overall else "N/A")
            short_new = "HEALTHY" if "HEALTHY" in overall else ("UNHEALTHY" if "UNHEALTHY" in overall else overall[:20])
            event["change"].append(f"health: {short_prev} → {short_new}")

        try:
            os.makedirs(os.path.dirname(event_log_path), exist_ok=True)
            with open(event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            import sys
            sys.stderr.write(f"[link_validator] Failed to write event to {event_log_path}: {e}\n")


def _record_topic_event(event_log_path: str, now_jst: str, category: str, topic: str, detail: str) -> None:
    """構造化トピックイベントを記録する。

    Args:
        event_log_path: イベントログファイルのパス
        now_jst: 現在のJST時刻文字列
        category: 'incident' | 'achievement' | 'system'
        topic: イベント種別 (THROUGHPUT_RECORD, SESSION_START など)
        detail: 人間が読める詳細説明
    """
    event = {
        "timestamp": now_jst,
        "lifecycle": "TOPIC",
        "health": "",
        "category": category,
        "topic": topic,
        "detail": detail,
        "change": [f"{category}: {topic}"]
    }
    try:
        os.makedirs(os.path.dirname(event_log_path), exist_ok=True)
        with open(event_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as e:
        import sys
        sys.stderr.write(f"[link_validator] Failed to write topic event to {event_log_path}: {e}\n")


def _read_recent_events(event_log_path: str, n: int = 10) -> str:
    """イベントログから直近24時間のイベントを読み取り、介入必要/解消のペアを可視化するタイムラインを返す。

    Args:
        event_log_path: イベントログファイルのパス
        n: 読み込み件数（後方互換性用、現在は主に24時間フィルタを使用）

    Returns:
        str: マークダウン形式のタイムライン
    """
    if not os.path.exists(event_log_path):
        return "- イベントログはまだありません。\n"

    try:
        with open(event_log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return "- 読み取り失敗\n"

    if not lines:
        return "- イベントログは空です。\n"

    def _translate_change(raw: str) -> str:
        """Raw event change string → Japanese topic description."""
        if "auto_stop:" in raw or "AUTO_STOPPED" in raw:
            import re
            min_match = re.search(r'(\d+)分前', raw)
            minutes = min_match.group(1) if min_match else '?'
            return f"⏸️ {minutes}分途絶 → 自動停止 (Flash側・pytestハング)"
        if "auto_recovery" in raw or "AUTO_RECOVERED" in raw:
            return "🟢 セッション自動復旧完了"
        if "lifecycle:" in raw:
            if "COMPLETE" in raw:
                return "🏁 セッション完遂 — 全タスク処理完了"
            if "FINISHING" in raw:
                if "FINISHING → ACTIVE" in raw or "FINISHING -> ACTIVE" in raw:
                    return "🔄 タスク消化再開"
                return "⏳ 残タスク消化完了間近"
            if "ACTIVE" in raw:
                return "🚀 セッション稼働開始"
            if "STOPPED" in raw:
                return "⏹️ セッション停止"
        if "health:" in raw:
            if "UNHEALTHY" in raw:
                return "🔴 異常検出（ヘルスチェック失敗）"
            if "DEGRADED" in raw:
                if "→ HEALTHY" in raw or "→ 🟢" in raw:
                    return "🟢 注意事項解消 → 正常復旧"
                return "🟡 注意事項を検出"
            if "HEALTHY → HEALTHY" in raw:
                return "🟢 正常状態を継続確認"
            if "HEALTHY" in raw:
                return "🟢 正常稼働"
        # Topic events
        if "achievement:" in raw:
            return "🏆 成果記録"
        if "incident:" in raw:
            return "🚨 インシデント"
        if "system:" in raw:
            return "📊 システム改善"
        return raw[:60]

    def _is_intervention_needed(ev: dict) -> bool:
        """ユーザー介入が必要な状態かを判定。"""
        health = ev.get("health", "")
        lc = ev.get("lifecycle", "")
        changes = ev.get("change", [])
        change_str = " ".join(changes)
        if "UNHEALTHY" in health:
            return True
        if lc in ("COMPLETE", "INFO"):
            return True
        if "auto_stop" in change_str or "AUTO_STOPPED" in change_str or "STOPPED" in change_str:
            return True
        return False

    def _is_intervention_resolved(ev: dict) -> bool:
        """介入が解消された（正常復帰した）状態かを判定。"""
        health = ev.get("health", "")
        lc = ev.get("lifecycle", "")
        if "HEALTHY" in health and lc == "ACTIVE":
            return True
        return False

    # ── 24時間フィルタリング ──
    # イベントログの時刻は JST 表記。ローカル時刻と突き合わせると
    # UTC 環境（CI・クラウド実行）で 9 時間ずれ、表示される 24 時間の範囲が変わる。
    now = now_jst()
    cutoff = now - timedelta(hours=24)
    events_24h = []
    for line in lines:
        try:
            ev = json.loads(line.strip())
            if isinstance(ev, dict):
                ts = parse_jst(ev.get("timestamp", ""))
                if ts and ts >= cutoff:
                    ev["_parsed_ts"] = ts
                    events_24h.append(ev)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            continue

    if not events_24h:
        return "- 直近24時間のイベントはありません。\n"

    # ── 介入タイムライン: 発生→解消ペアの抽出 ──
    incidents = []  # [(発生時刻, 解消時刻, 発生イベント, 解消イベント)]
    pending_incident_start = None
    pending_incident_event = None

    for ev in events_24h:
        if _is_intervention_needed(ev) and pending_incident_start is None:
            pending_incident_start = ev["_parsed_ts"]
            pending_incident_event = ev
        elif _is_intervention_resolved(ev) and pending_incident_start is not None:
            resolved_ts = ev["_parsed_ts"]
            delta = resolved_ts - pending_incident_start
            incidents.append({
                "start": pending_incident_start,
                "end": resolved_ts,
                "duration_min": int(delta.total_seconds() / 60),
                "start_event": pending_incident_event,
                "end_event": ev,
            })
            pending_incident_start = None
            pending_incident_event = None

    # 未解消のインシデント
    if pending_incident_start is not None:
        delta = now - pending_incident_start
        incidents.append({
            "start": pending_incident_start,
            "end": None,
            "duration_min": int(delta.total_seconds() / 60),
            "start_event": pending_incident_event,
            "end_event": None,
        })

    # ── 介入タイムロス・サマリー ──
    md = ""

    # ユーザーが見るべきインシデントに絞る:
    # - 未解消（現在対応が必要）
    # - タイムロス30分超（ユーザー介入なしでは解決しなかった長時間停止）
    # - セッション完遂（新規セッション開設が必要）
    user_relevant = []
    for inc in incidents:
        is_unresolved = inc["end"] is None
        is_long = inc["duration_min"] >= 30
        start_changes = " ".join(inc["start_event"].get("change", []))
        is_complete = "COMPLETE" in start_changes
        if is_unresolved or is_long or is_complete:
            user_relevant.append(inc)

    if user_relevant:
        total_loss_min = sum(i["duration_min"] for i in user_relevant)
        resolved_count = sum(1 for i in user_relevant if i["end"] is not None)
        unresolved_count = sum(1 for i in user_relevant if i["end"] is None)

        md += "### 🚨 介入タイムライン（24h）\n\n"

        # サマリーを表の上に配置
        if total_loss_min > 0:
            loss_pct = total_loss_min / (24 * 60) * 100
            md += f"> 📊 24h合計: **{len(user_relevant)}件** のインシデント"
            md += f" (解消: {resolved_count}, 未解消: {unresolved_count})"
            md += f" | 累計タイムロス: **{total_loss_min}分**"
            md += f" ({loss_pct:.1f}%/24h)\n\n"
        else:
            md += f"> 📊 24h合計: **{len(user_relevant)}件** のインシデント"
            md += f" (解消: {resolved_count}, 未解消: {unresolved_count})\n\n"

        md += "| 時刻 | 内容 | 解消 | ロス | 状態 |\n"
        md += "|:---:|:---|:---:|:---:|:---:|\n"

        for inc in user_relevant:
            start_str = inc["start"].strftime("%H:%M")
            start_changes = inc["start_event"].get("change", [])
            cause = " / ".join([_translate_change(c) for c in start_changes]) if start_changes else "—"
            if inc["end"] is not None:
                end_str = inc["end"].strftime("%H:%M")
                status = "✅"
            else:
                end_str = "—"
                status = "🔴"
            dur_str = f"{inc['duration_min']}分"
            md += f"| {start_str} | {cause} | {end_str} | {dur_str} | {status} |\n"

        md += "\n"

    # ── 24時間イベントログ ──
    # 概要テキストは常時表示、個別イベントは折りたたみ
    important_events = []
    if events_24h:
        for ev in events_24h:
            changes = ev.get("change", [])
            topics = []
            for c in changes:
                topic = _translate_change(c)
                # 頻発ノイズイベントを除外
                if any(nw in topic for nw in ["残タスク消化完了間近", "タスク消化再開", "正常状態を継続確認", "心拍"]):
                    continue
                if topic not in topics:
                    topics.append(topic)
            if topics:
                ev["_filtered_topics"] = topics
                important_events.append(ev)

        start_time = events_24h[0].get("timestamp", "?")
        end_time = events_24h[-1].get("timestamp", "?")
        md += f"**直近24時間の概要 ({start_time} 〜 {end_time})**:\n"

        has_auto_stop = any("auto_stop" in str(ev) or "AUTO_STOPPED" in str(ev) for ev in events_24h)
        has_unhealthy = any("UNHEALTHY" in ev.get("health", "") for ev in events_24h)
        has_complete = any("COMPLETE" in ev.get("lifecycle", "") for ev in events_24h)

        summary_parts = []
        if has_complete:
            summary_parts.append("セッションの完遂が確認されました。")
        if has_auto_stop or has_unhealthy:
            summary_parts.append("一部時間帯で自動停止や一時的な異常が発生しましたが、手動または自動で復旧されました。")
        else:
            summary_parts.append("致命的な停止や異常はなく、安定して稼働しました。")

        md += " " + "".join(summary_parts) + "\n\n"

    # 連続する同一イベントのマージ
    merged_events = []
    current_event = None
    for ev in important_events:
        ts = ev.get("timestamp", "?")
        topics = ev.get("_filtered_topics", [])
        topic_str = " / ".join(topics)

        # 日付と時刻 of 分離
        parts = ts.split(" ")
        date_part = parts[0] if len(parts) > 0 else ""
        time_part = parts[1] if len(parts) > 1 else ""

        if current_event and current_event["topic"] == topic_str:
            current_event["end_time"] = time_part
            current_event["count"] += 1
        else:
            if current_event:
                merged_events.append(current_event)
            current_event = {
                "topic": topic_str,
                "date": date_part,
                "start_time": time_part,
                "end_time": time_part,
                "count": 1,
                "raw_ts": ts
            }
    if current_event:
        merged_events.append(current_event)

    # 優先度フィルタリング
    def _get_priority(topic: str) -> int:
        if any(k in topic for k in ["自動停止", "完遂", "異常検出"]):
            return 3
        if any(k in topic for k in ["注意事項", "停止"]):
            return 2
        return 1

    rev_merged = list(reversed(merged_events))

    # 優先度2以上のイベントをまず抽出
    high_priority = [e for e in rev_merged if _get_priority(e["topic"]) >= 2]

    # 5件に満たない場合は、優先度1のイベントを最新順に補填
    selected_events = high_priority[:5]
    if len(selected_events) < 5:
        low_priority = [e for e in rev_merged if _get_priority(e["topic"]) < 2]
        needed = 5 - len(selected_events)
        selected_events.extend(low_priority[:needed])

    # 最終表示順として、元の時間逆順で並び替える（インデックスでソート）
    selected_events = sorted(selected_events, key=lambda e: rev_merged.index(e))

    # ── 3カテゴリ構造の主要トピック生成 ──
    # カテゴリ分類: incident / achievement / system
    categorized = {"incident": [], "achievement": [], "system": []}
    seen_details = {"incident": set(), "achievement": set(), "system": set()}

    for ev in reversed(events_24h):
        ts = ev.get("timestamp", "?")
        category = ev.get("category", "")
        topic_name = ev.get("topic", "")
        detail = ev.get("detail", "")
        changes = ev.get("change", [])
        lc = ev.get("lifecycle", "")

        # 明示的なcategoryフィールドがある場合（新形式）
        if category in categorized:
            if detail in seen_details[category]:
                continue
            seen_details[category].add(detail)
            categorized[category].append({
                "timestamp": ts,
                "topic": topic_name,
                "detail": detail,
            })
            continue

        # 旧形式イベントの自動分類
        change_str = " ".join(changes)
        if "auto_stop" in change_str or "AUTO_STOPPED" in change_str:
            import re
            min_match = re.search(r'(\d+)分前', change_str)
            minutes = min_match.group(1) if min_match else '?'
            det = f"心拍{minutes}分途絶"
            if det in seen_details["incident"]:
                continue
            seen_details["incident"].add(det)
            categorized["incident"].append({
                "timestamp": ts,
                "topic": "HEARTBEAT_STOP",
                "duration": f"{minutes}分",
                "stop_type": "自動停止",
                "root_cause": "pytestハング",
                "detail": det,
            })
        elif "AUTO_RECOVERED" in change_str or "auto_recovery" in change_str:
            det = "心拍更新により自動復旧完了"
            if det in seen_details["achievement"]:
                continue
            seen_details["achievement"].add(det)
            categorized["achievement"].append({
                "timestamp": ts,
                "topic": "AUTO_RECOVERED",
                "detail": det,
            })
        elif "COMPLETE" in change_str and lc == "COMPLETE":
            det = "Flashセッションが全タスクを処理し正常完遂"
            if det in seen_details["system"]:
                continue
            seen_details["system"].add(det)
            categorized["system"].append({
                "timestamp": ts,
                "topic": "SESSION_COMPLETE",
                "detail": det,
            })

    # ── Markdown生成 ──
    md += "#### 📰 主要トピック（直近24時間）\n\n"

    # インシデントは介入タイムラインに集約済みのため、ここでは省略

    # 成果・記録
    if categorized["achievement"]:
        md += "**🏆 成果・記録**\n\n"
        for ach in categorized["achievement"][:5]:
            md += f"- **{ach['timestamp']}**: {ach['detail']}\n"
        md += "\n"

    # システム改善
    if categorized["system"]:
        md += "**📊 システム・運用**\n\n"
        for sys_ev in categorized["system"][:5]:
            md += f"- **{sys_ev['timestamp']}**: {sys_ev['detail']}\n"
        md += "\n"

    # どのカテゴリも空の場合
    if not any(categorized.values()):
        md += "- 直近24時間に主要トピックはありませんでした。\n\n"

    # 全イベント一覧（折りたたみ。マージ済みイベントを全件表示）
    md += "<details>\n<summary>📋 24時間イベントログ詳細（マージ済み全" + str(len(merged_events)) + "件 — クリックで展開）</summary>\n\n"
    for ev in reversed(merged_events):
        if ev["count"] > 1 and ev["start_time"] != ev["end_time"]:
            time_range = f"{ev['start_time']}〜{ev['end_time']}"
        else:
            time_range = ev["start_time"]

        ts_display = f"{ev['date']} {time_range} JST" if ev["date"] else f"{time_range} JST"
        count_suffix = f" ({ev['count']}回発生)" if ev["count"] > 1 else ""
        md += f"- **{ts_display}**: {ev['topic']}{count_suffix}\n"

    if not merged_events:
        md += "- 期間中にイベントはありませんでした。\n"

    md += "\n</details>\n"

    return md


__all__ = [
    "get_rel_link",
    "localize_links",
    "_link_target_exists",
    "validate_dashboard_links",
    "_record_event_if_changed",
    "_record_topic_event",
    "_read_recent_events",
]
