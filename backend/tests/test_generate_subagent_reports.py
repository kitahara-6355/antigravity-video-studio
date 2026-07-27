import os
import sys
import json
import glob
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# backend ディレクトリを sys.path に追加して、agents などのインポートを可能にする
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.agents.orchestration.generate_subagent_reports as gsr

# フィクスチャを用意して、グローバルパスを一時ディレクトリ配下に書き換える
@pytest.fixture
def mock_env(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # 必要なフォルダの作成
    orchestration_dir = workspace / "backend" / "agents" / "orchestration"
    orchestration_dir.mkdir(parents=True)
    
    official_dir = workspace / "Human01_Official Artifact"
    official_dir.mkdir()
    
    # 未転記と受信トレイ
    inbox_source_dir = official_dir / "未転記" / "分析・提案"
    inbox_source_dir.mkdir(parents=True)
    inbox_dir = official_dir / "受信トレイ"
    inbox_dir.mkdir()
    
    # グローバル変数のモック化
    monkeypatch.setattr(gsr, "WORKSPACE_DIR", str(workspace))
    monkeypatch.setattr(gsr, "ORCHESTRATION_DIR", str(orchestration_dir))
    monkeypatch.setattr(gsr, "TASK_QUEUE_PATH", str(orchestration_dir / "task_queue.json"))
    monkeypatch.setattr(gsr, "FLASH_SESSION_PATH", str(orchestration_dir / "flash_session.json"))
    monkeypatch.setattr(gsr, "FLASH_REPORTS_PATH", str(orchestration_dir / "flash_reports.jsonl"))
    
    monkeypatch.setattr(gsr, "OFFICIAL_ARTIFACT_DIR", str(official_dir))
    report_base = official_dir / "サブエージェント体制報告"
    monkeypatch.setattr(gsr, "REPORT_BASE_DIR", str(report_base))
    monkeypatch.setattr(gsr, "PERIODIC_REPORT_DIR", str(report_base / "定時レポート"))
    monkeypatch.setattr(gsr, "BULLETIN_REPORT_DIR", str(report_base / "速報"))
    monkeypatch.setattr(gsr, "RANKING_REPORT_DIR", str(report_base / "活動ランキング"))
    
    # phase_state.json の事前作成
    memory_dir = workspace / "backend" / "agents" / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    phase_state_path = memory_dir / "phase_state.json"
    phase_state_data = {
        "current_phase": 25,
        "current_milestone": "milestone",
        "roadmap_max_phase": 30,
        "next_milestones": [],
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
    with open(phase_state_path, "w", encoding="utf-8") as f:
        json.dump(phase_state_data, f)
        
    # event_log.jsonl の事前作成
    report_base.mkdir(parents=True, exist_ok=True)
    event_log_path = report_base / "event_log.jsonl"
    event_data = {
        "timestamp": "2026-05-24 10:00 JST",
        "topic": "PHASE_TRANSITION",
        "detail": "📦 Phase 24 で稼働中"
    }
    with open(event_log_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(event_data) + "\n")
        
    return {
        "workspace": workspace,
        "orchestration_dir": orchestration_dir,
        "official_dir": official_dir,
        "inbox_source_dir": inbox_source_dir,
        "inbox_dir": inbox_dir,
        "report_base": report_base,
    }

def test_find_latest_brain_report_success(mock_env, monkeypatch):
    # brain_base のモック化
    brain_dir = mock_env["workspace"] / "brain"
    brain_dir.mkdir()
    
    # テスト用フォルダ
    session_dir1 = brain_dir / "session1"
    session_dir1.mkdir()
    
    # 成果物フォルダ
    art_dir = session_dir1 / ".system_generated" / "artifacts"
    art_dir.mkdir(parents=True)
    
    report1 = session_dir1 / "some_other_file.md"
    report1.write_text("report1", encoding="utf-8")
    
    report2 = art_dir / "daily_report_20260523.md"
    report2.write_text("report2", encoding="utf-8")
    
    # mtime の操作 (更新日付)
    os.utime(str(report1), (1000, 1000))
    os.utime(str(report2), (2000, 2000)) # 最新にする
    
    # BRAIN_REPORT_PATH の書き換え (dirnameのdirnameがbrain_dirになるように2階層深くする)
    default_path = str(brain_dir / "dummy_session" / "default.md")
    monkeypatch.setattr(gsr, "BRAIN_REPORT_PATH", default_path)
    
    # 実行
    res = gsr.find_latest_brain_report()
    assert res == str(report2)

def test_find_latest_brain_report_not_found(mock_env, monkeypatch):
    # brain_base が存在しない場合
    monkeypatch.setattr(gsr, "BRAIN_REPORT_PATH", "non_existent_path/report.md")
    res = gsr.find_latest_brain_report()
    assert res == "non_existent_path/report.md"

def test_find_latest_brain_report_exception(mock_env, monkeypatch):
    # glob.glob で例外を発生させる
    monkeypatch.setattr(gsr, "BRAIN_REPORT_PATH", "dummy.md")
    with patch("glob.glob", side_effect=Exception("glob error")):
        res = gsr.find_latest_brain_report()
        assert res == "dummy.md"
        
    # os.path.dirname で例外を発生させるパターン
    with patch("os.path.dirname", side_effect=Exception("dirname error")):
        res = gsr.find_latest_brain_report()
        assert res == "dummy.md"

def test_get_week_range_str():
    # 正常系
    res = gsr.get_week_range_str("2026-05-24") # 日曜日
    assert "2026-05-18 〜 2026-05-24 (第21週)" in res
    
    # 異常系
    res_err = gsr.get_week_range_str("invalid-date")
    assert res_err == "その他の週"

def test_parse_iso_datetime():
    # Z付き
    dt1 = gsr.parse_iso_datetime("2026-05-24T12:00:00Z")
    assert dt1.year == 2026 and dt1.month == 5 and dt1.day == 24

    # Zなし
    dt2 = gsr.parse_iso_datetime("2026-05-24T12:00:00")
    assert dt2.year == 2026 and dt2.month == 5

    # オフセットの有無が混在しても引き算できること（常に aware で返す）
    # ログには両方の形式が混在しており、naive と aware を引くと TypeError になって
    # ダッシュボードのランキングが丸ごと欠落していた
    assert dt1.tzinfo is not None and dt2.tzinfo is not None
    assert (dt1 - dt2).total_seconds() == 0

    dt3 = gsr.parse_iso_datetime("2026-05-24T12:00:00+09:00")
    assert (dt1 - dt3).total_seconds() == 9 * 3600

    # None
    assert gsr.parse_iso_datetime(None) is None
    
    # 異常値
    assert gsr.parse_iso_datetime("invalid") is None

def test_format_duration():
    assert gsr.format_duration(3600) == "1h 0m"
    assert gsr.format_duration(3665) == "1h 1m"
    assert gsr.format_duration(125) == "2m 5s"
    assert gsr.format_duration(45) == "45s"
    assert gsr.format_duration(0) == "0s"

def test_extract_date(tmp_path):
    # ファイル名から日付抽出
    assert gsr.extract_date("/path/to/daily_report_20260522.md") == "2026-05-22"
    
    # ファイル名に日付がないが、実ファイルが存在して mtime が取得できる場合
    temp_file = tmp_path / "report.md"
    temp_file.write_text("content", encoding="utf-8")
    mtime = datetime(2026, 5, 20, 10, 0, 0).timestamp()
    os.utime(str(temp_file), (mtime, mtime))
    
    assert gsr.extract_date(str(temp_file)) == "2026-05-20"
    
    # 実ファイルが存在せず例外になる場合
    res = gsr.extract_date("non_existent_file.md")
    # 期待値も JST で作る。ローカル時刻だと UTC 環境（CI）の 00:00〜09:00 JST で 1 日ずれる
    from backend.agents.orchestration.jst_time import jst_date
    assert res == jst_date()

def test_get_rel_link():
    import os as _os
    repo_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))

    # リポジトリ内のファイルはリポジトリ相対（環境非依存）
    res1 = gsr.get_rel_link(_os.path.join(repo_root, "backend", "agents", "orchestration", "link_validator.py"))
    assert res1 == "backend/agents/orchestration/link_validator.py"
    assert not res1.startswith("file:")

    # リポジトリ外は相対で書けないので file:/// にフォールバックする
    outside = _os.path.abspath(_os.path.join(repo_root, "..", "..", "outside_repo_file.md"))
    res2 = gsr.get_rel_link(outside)
    assert res2.startswith("file://"), res2

    # 入力が壊れていても落ちない
    assert gsr.get_rel_link(None) == ""
    assert gsr.get_rel_link("") == ""

def test_get_tdr_stats(mock_env):
    # ファイルが存在しない場合
    stats = gsr.get_tdr_stats()
    assert stats == {"CRITICAL": 0, "IMPORTANT": 0, "MINOR": 0, "total": 0}
    
    # 正常なJSON
    tdr_file = mock_env["workspace"] / "backend" / "agents" / "memory" / "technical_debt_index.json"
    tdr_file.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "entries": [
            {"status": "open", "category": "CRITICAL_DEBT"},
            {"status": "open", "category": "IMPORTANT_DEBT"},
            {"status": "open", "category": "MINOR_INFRA"},
            {"status": "closed", "category": "CRITICAL_DEBT"} # 集計対象外
        ]
    }
    tdr_file.write_text(json.dumps(data), encoding="utf-8")
    
    stats = gsr.get_tdr_stats()
    assert stats == {"CRITICAL": 1, "IMPORTANT": 1, "MINOR": 1, "total": 3}
    
    # 破損したJSONによる例外フォールバック
    tdr_file.write_text("invalid json", encoding="utf-8")
    stats_err = gsr.get_tdr_stats()
    assert stats_err == {"CRITICAL": 0, "IMPORTANT": 0, "MINOR": 0, "total": 0}

def test_get_flash_status_md(mock_env):
    # ファイルなし
    assert gsr.get_flash_status_md() == ""
    
    # 正常系 (status = running)
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    hb_time = (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    
    session_data = {
        "status": "running",
        "last_heartbeat": hb_time,
        "current_activity": "thinking",
        "current_step": "step 1",
        "current_batch_id": "batch_123",
        "subagents_running": 2,
        "tasks_completed_in_session": 10
    }
    
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
        
    md = gsr.get_flash_status_md()
    assert "🟢 RUNNING" in md
    assert "5分前" in md
    
    # 正常系 (status = stopped, heartbeat = 0分前)
    hb_time_now = now_utc.isoformat().replace("+00:00", "Z")
    session_data["status"] = "stopped"
    session_data["last_heartbeat"] = hb_time_now
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
    md = gsr.get_flash_status_md()
    assert "🔴 STOPPED" in md
    assert "今さっき心拍を確認" in md
    
    # status = unknown
    session_data["status"] = "idle"
    session_data["last_heartbeat"] = None
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
    md = gsr.get_flash_status_md()
    assert "⚪ UNKNOWN" in md
    assert "不明" in md
    
    # 例外系
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        f.write("invalid json")
    assert gsr.get_flash_status_md() == ""

def test_get_directive_md(mock_env):
    directive_path = os.path.join(gsr.ORCHESTRATION_DIR, "opus_directive.json")
    # ファイルなし
    assert gsr.get_directive_md() == ""
    
    # 正常系
    data = {
        "directive_id": "dir_001",
        "notes": "focus on quality",
        "priorities": {"quality": 80, "speed": 20},
        "focus_modules": ["/path/to/module1.py", "/path/to/module2.py"]
    }
    with open(directive_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    md = gsr.get_directive_md()
    assert "dir_001" in md
    assert "`quality`: 80%" in md
    assert "`module1.py`" in md
    
    # focus_modules が空の場合
    data["focus_modules"] = []
    with open(directive_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    md = gsr.get_directive_md()
    assert "なし" in md
    
    # 例外系
    with open(directive_path, "w", encoding="utf-8") as f:
        f.write("invalid json")
    assert gsr.get_directive_md() == ""

def test_extract_metrics_from_report(tmp_path):
    report_file = tmp_path / "report.md"
    
    # 正常系 (様々なパターンで抽出されるか検証)
    content = """
| **テスト数** | 1,521件 |
| **タスク成功率** | 100% |
| **Flash累計完了タスク** | **94件** |
"""
    report_file.write_text(content, encoding="utf-8")
    metrics = gsr.extract_metrics_from_report(str(report_file))
    assert metrics["test_count"] == 1521
    assert metrics["quality_score"] == 100.0
    assert metrics["resource_usage"] == 94
    
    # 正常系パターン2
    content2 = """
| **テスト総数** | 0 | 500 |
| **成功率** | 95.5% |
| 完了タスク | 120 |
"""
    report_file.write_text(content2, encoding="utf-8")
    metrics = gsr.extract_metrics_from_report(str(report_file))
    assert metrics["test_count"] == 500
    assert metrics["quality_score"] == 95.5
    assert metrics["resource_usage"] == 120
    
    # 正常系パターン3 (passed表記, PASS率, 括弧表記から完了タスク数抽出)
    content3 = """
55 passed, 2 failed
PASS率 | 90.0%
成功率 | 90.0% (82/82)
"""
    report_file.write_text(content3, encoding="utf-8")
    metrics = gsr.extract_metrics_from_report(str(report_file))
    assert metrics["test_count"] == 55
    assert metrics["quality_score"] == 90.0
    assert metrics["resource_usage"] == 82
    
    # 例外系 (ファイルが存在しない)
    metrics_err = gsr.extract_metrics_from_report("non_existent_report.md")
    assert metrics_err == {"quality_score": None, "test_count": None, "resource_usage": None}
    
    # 破損ファイル (読み込み失敗)
    with patch("builtins.open", side_effect=Exception("Read error")):
        metrics_err = gsr.extract_metrics_from_report(str(report_file))
        assert metrics_err == {"quality_score": None, "test_count": None, "resource_usage": None}

def test_register_tdr_debts_success():
    alerts = [
        {
            "type": "quality_drop",
            "file_path": "/path/to/workspace/file.py",
            "value": 85.0,
            "threshold": 90.0,
            "msg": "quality dropped to 85%"
        }
    ]
    
    # TechnicalDebtStore のモック化
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        gsr.register_tdr_debts(alerts)
        
        mock_store_inst.register_debt.assert_called_once()
        args, kwargs = mock_store_inst.register_debt.call_args
        assert kwargs["category"] == "MINOR_INFRA"
        assert "quality_drop" in kwargs["tags"]
        
    # alerts が空の場合
    mock_store_inst.reset_mock()
    gsr.register_tdr_debts([])
    mock_store_inst.register_debt.assert_not_called()

def test_register_tdr_debts_exception():
    alerts = [{"type": "quality_drop", "file_path": "file.py", "msg": "error"}]
    # 例外が発生した場合にクラッシュしないこと
    with patch("agents.memory.technical_debt.TechnicalDebtStore", side_effect=Exception("Import failed")):
        gsr.register_tdr_debts(alerts)

def test_register_tdr_debts_sys_path_append():
    alerts = [{"type": "quality_drop", "file_path": "file.py", "msg": "error"}]
    
    # sys.path.append(backend_dir) の分岐を実行させるため、sys.path から backend_dir を一時的に削除
    removed = False
    # backend_dir の絶対パス表現を考慮して一致するものすべて削除
    path_targets = [backend_dir, os.path.abspath(backend_dir), os.path.normpath(backend_dir)]
    for target in path_targets:
        while target in sys.path:
            sys.path.remove(target)
            removed = True
            
    # TechnicalDebtStore 自体をダミーモックで差し替えてインポートを成功させる
    sys.modules["agents"] = MagicMock()
    sys.modules["agents.memory"] = MagicMock()
    sys.modules["agents.memory.technical_debt"] = MagicMock()
    
    try:
        gsr.register_tdr_debts(alerts)
    finally:
        # sys.modules を元に戻す
        sys.modules.pop("agents", None)
        sys.modules.pop("agents.memory", None)
        sys.modules.pop("agents.memory.technical_debt", None)
        if removed:
            sys.path.insert(0, backend_dir)

def test_generate_trend_table(tmp_path):
    # レポートがない場合
    assert gsr.generate_trend_table(str(tmp_path)) == ""
    
    # レポートが存在する場合
    report1 = tmp_path / "daily_report_20260522.md"
    report1.write_text("| **テスト数** | 100 |\n| **成功率** | 95.0% |\n| 完了タスク | 10 |", encoding="utf-8")
    
    report2 = tmp_path / "periodic_report_20260523.md"
    report2.write_text("| **テスト数** | 200 |\n| **成功率** | 85.0% |\n| 完了タスク | 350 |", encoding="utf-8")
    
    os.utime(str(report1), (1000, 1000))
    os.utime(str(report2), (2000, 2000))
    
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        md = gsr.generate_trend_table(str(tmp_path))
        
        assert "## 📈 長期メトリクストレンド" in md
        assert "daily_report_20260522.md" in md
        assert "periodic_report_20260523.md" in md
        
        assert mock_store_inst.register_debt.call_count == 2

def test_main(mock_env, monkeypatch):
    inbox_src = mock_env["inbox_source_dir"]
    inbox = mock_env["inbox_dir"]
    
    # テスト用のインプットファイルを配置する
    hourly_file = inbox_src / "hourly_report_20260524_1000.md"
    hourly_file.write_text("hourly content", encoding="utf-8")
    
    phase_file = inbox_src / "phase_25_completion_20260524.md"
    phase_file.write_text("phase content", encoding="utf-8")
    
    # inbox (受信トレイ) 配下にもファイルを配置
    inbox_hourly = inbox / "hourly_report_20260524_1100.md"
    inbox_hourly.write_text("inbox hourly content", encoding="utf-8")
    
    inbox_phase = inbox / "phase_25_completion_20260524_v2.md"
    inbox_phase.write_text("inbox phase content", encoding="utf-8")
    
    inbox_periodic = inbox / "periodic_report_20260524.md"
    inbox_periodic.write_text("inbox periodic content", encoding="utf-8")
    
    inbox_durability = inbox / "raw_video_durability_report.md"
    inbox_durability.write_text("durability content", encoding="utf-8")
    
    # Brainレポート (dirnameのdirnameがbrain_dirになるように2階層深くする)
    brain_dir = mock_env["workspace"] / "brain"
    brain_report = brain_dir / "some_session" / "daily_report_20260524.md"
    brain_report.parent.mkdir(parents=True, exist_ok=True)
    brain_report.write_text("brain report content", encoding="utf-8")
    
    # task_queue.json
    task_queue_data = {
        "tasks": [
            {
                "id": "task_1",
                "status": "pass",
                "group": "Director",
                "started_at": "2026-05-24T10:00:00Z",
                "completed_at": "2026-05-24T10:01:00Z"
            },
            {
                "id": "task_2",
                "status": "fail",
                "group": "Analyst",
                "started_at": "2026-05-24T10:05:00Z",
                "completed_at": "2026-05-24T10:05:10Z"
            },
            {
                "id": "task_3",
                "status": "running"
            }
        ]
    }
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(task_queue_data, f)
        
    # flash_reports.jsonl
    flash_reports_data = [
        {
            "batch_id": "batch_001",
            "tasks": [
                {
                    "id": "task_4",
                    "status": "pass",
                    "group": "Director",
                    "started_at": "2026-05-24T09:00:00Z",
                    "completed_at": "2026-05-24T09:00:05Z"
                }
            ]
        }
    ]
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        for entry in flash_reports_data:
            f.write(json.dumps(entry) + "\n")
        f.write("\n\n") # 空行チェックのカバー
            
    # flash_session.json
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    hb_time = (now_utc - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    session_data = {
        "status": "running",
        "last_heartbeat": hb_time,
        "current_activity": "idle",
        "recent_errors": [
            {"module": "module_a", "error": "429 RESOURCE_EXHAUSTED"},
            {"module": "module_b", "error": "TIMEOUT"}, # TIMEOUT カバー
            {"module": "module_c", "error": "unknown database error"}
        ]
    }
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
        
    # TechnicalDebtStore のモック
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        gsr.main(brain_report_path=str(brain_report))
        
    readme_path = os.path.join(gsr.REPORT_BASE_DIR, "README.md")
    assert os.path.exists(readme_path)
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    
    assert "# 🎛️ ダッシュボード" in readme_content
    assert "24時間イベントログ" in readme_content
    
    ranking_dir = gsr.RANKING_REPORT_DIR
    ranking_files = os.listdir(ranking_dir)
    assert len(ranking_files) == 1
    ranking_file = os.path.join(ranking_dir, ranking_files[0])
    with open(ranking_file, "r", encoding="utf-8") as f:
        ranking_content = f.read()
    
    assert "稼働時間ランキング" in ranking_content
    assert "全体統計" in ranking_content
    assert "エラー多発モジュール" in ranking_content
    assert "Director Agent" in ranking_content or "Analyst Agent" in ranking_content
    
    assert os.path.exists(os.path.join(gsr.PERIODIC_REPORT_DIR, "phase_25_completion_20260524.md"))
    assert os.path.exists(os.path.join(gsr.PERIODIC_REPORT_DIR, "periodic_report_20260524.md"))
    assert os.path.exists(os.path.join(gsr.PERIODIC_REPORT_DIR, "raw_video_durability_report.md"))
    assert os.path.exists(os.path.join(gsr.BULLETIN_REPORT_DIR, "hourly_report_20260524_1100.md"))

def test_main_task_queue_not_found(mock_env):
    if os.path.exists(gsr.TASK_QUEUE_PATH):
        os.remove(gsr.TASK_QUEUE_PATH)
    res = gsr.main(brain_report_path="dummy.md")
    assert res is None

def test_main_corrupted_files(mock_env, monkeypatch):
    # BRAIN_REPORT_PATH を存在しないファイルに設定し、find_latest_brain_report での検出をバイパスして else (digest_filesのコピー) を通す
    monkeypatch.setattr(gsr, "BRAIN_REPORT_PATH", "non_existent_file.md")

    # sorted_periodic の中で get_week_sort_key が例外を投げるように、get_week_range_str をモック
    monkeypatch.setattr(gsr, "get_week_range_str", lambda x: None)

    # glob.glob のモック。BULLETIN_REPORT_DIR に対する glob の場合のみ、実在しないファイルを混ぜて mtime 例外を発生させる
    original_glob = glob.glob
    def mock_glob(pattern):
        if "サブエージェント体制報告" in pattern and "速報" in pattern:
            return ["non_existent_bulletin.md"]
        return original_glob(pattern)
    monkeypatch.setattr(glob, "glob", mock_glob)

    # 破損したJSONファイルを用意して例外ブロックをカバー
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        f.write("invalid json")
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        f.write("invalid json")
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        f.write("invalid json\n")
        
    digest_file = mock_env["inbox_source_dir"] / "daily_digest_20260524.md"
    digest_file.write_text("digest content", encoding="utf-8")
    
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        gsr.main(brain_report_path=None)
        
    readme_path = os.path.join(gsr.REPORT_BASE_DIR, "README.md")
    assert os.path.exists(readme_path)

def test_main_empty_resources(mock_env, monkeypatch):
    # ファイルを一切配置しない
    # さらに、main 処理中に生成されるランキングファイルも glob で空リストを返すようにモックする
    original_glob = glob.glob
    def mock_glob(pattern):
        if "サブエージェント体制報告" in pattern:
            return []
        return original_glob(pattern)
    monkeypatch.setattr(glob, "glob", mock_glob)
    
    # 正常な task_queue.json は用意しておく（mainの早期リターンを防ぐため）
    task_queue_data = {"tasks": []}
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(task_queue_data, f)
        
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        gsr.main(brain_report_path="non_existent_file.md")
        
    # README.md が生成され、空のメッセージが含まれていることを検証
    readme_path = os.path.join(gsr.REPORT_BASE_DIR, "README.md")
    assert os.path.exists(readme_path)
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "ランキングはまだ生成されていません。" in content
    assert "完了報告はありません。" in content
    assert "定時レポートはありません。" in content
    assert "速報レポートはありません。" in content

def test_main_execution(mock_env, monkeypatch):
    import runpy
    # 正常な task_queue.json は用意しておく（mainの早期リターンを防ぐため）
    task_queue_data = {"tasks": []}
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(task_queue_data, f)
        
    with patch("sys.argv", ["generate_subagent_reports.py", "--brain-report", "dummy.md"]):
        runpy.run_path(gsr.__file__, run_name="__main__")


def test_get_flash_status_md_stale_unreachable(mock_env):
    # 30分前の心拍 -> STALE
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    hb_time = (now_utc - timedelta(minutes=20)).isoformat().replace("+00:00", "Z")
    session_data = {
        "status": "running",
        "last_heartbeat": hb_time,
        "current_activity": "thinking",
        "current_step": "step 1",
        "current_batch_id": "batch_123",
        "subagents_running": 2,
        "tasks_completed_in_session": 10
    }
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
    md = gsr.get_flash_status_md()
    assert "🟡 STALE" in md

    # 45分前の心拍 -> UNREACHABLE
    hb_time = (now_utc - timedelta(minutes=45)).isoformat().replace("+00:00", "Z")
    session_data["last_heartbeat"] = hb_time
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
    md = gsr.get_flash_status_md()
    assert "🔴 UNREACHABLE" in md
    assert "45分前" in md

    # 125分前 (2時間5分前) -> UNREACHABLE
    hb_time = (now_utc - timedelta(minutes=125)).isoformat().replace("+00:00", "Z")
    session_data["last_heartbeat"] = hb_time
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)
    md = gsr.get_flash_status_md()
    assert "🔴 UNREACHABLE" in md
    assert "2時間5分前" in md

def test_infer_group_from_module():
    assert gsr._infer_group_from_module(None) == "misc"
    assert gsr._infer_group_from_module("") == "misc"
    assert gsr._infer_group_from_module("some_unknown_module.py") == "misc"
    assert gsr._infer_group_from_module("thumbnail_generator.py") == "thumbnail"
    assert gsr._infer_group_from_module("test_weaver.py") == "test_weaver"
    assert gsr._infer_group_from_module("bug_hunter.py") == "bug_hunter"
    assert gsr._infer_group_from_module("tdr_cleanup_script.py") == "tdr_cleanup"
    assert gsr._infer_group_from_module("tdr_resolver.py") == "tdr_resolver"
    assert gsr._infer_group_from_module("refactor_utils.py") == "refactor"
    assert gsr._infer_group_from_module("edge_case_tester.py") == "edge_case"
    assert gsr._infer_group_from_module("design_auto.py") == "design_auto"
    assert gsr._infer_group_from_module("self_improve.py") == "self_improve"
    assert gsr._infer_group_from_module("quality_ascend.py") == "quality_ascend"
    assert gsr._infer_group_from_module("subtitle_parser.py") == "subtitle"
    assert gsr._infer_group_from_module("branding_manager.py") == "branding"
    assert gsr._infer_group_from_module("integrated_preview.py") == "preview"
    assert gsr._infer_group_from_module("pipeline_runner.py") == "pipeline"
    assert gsr._infer_group_from_module("admin_channel_router.py") == "router"
    assert gsr._infer_group_from_module("orchestration_hub.py") == "orchestration"
    assert gsr._infer_group_from_module("quota_manager.py") == "quota"
    assert gsr._infer_group_from_module("cache_store.py") == "cache"
    assert gsr._infer_group_from_module("archive_helper.py") == "archive"

def test_exceptions_handling(mock_env, monkeypatch):
    # generate_batch_timeline での json.JSONDecodeError 例外ルート
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        f.write("invalid json\n")
    timeline = gsr.generate_batch_timeline()
    assert timeline == ""

    # generate_task_detail_summary での json.JSONDecodeError 例外ルート
    monkeypatch.setattr(gsr, "FLASH_REPORTS_PATH", "non_existent_reports.jsonl")
    detail = gsr.generate_task_detail_summary()
    assert detail == ""

    # generate_session_cumulative_stats での例外ルート
    monkeypatch.setattr(gsr, "FLASH_SESSION_PATH", "non_existent_session.json")
    stats = gsr.generate_session_cumulative_stats()
    assert stats == ""
    
    # get_recent_git_commits での例外ルート (git コマンドがエラー)
    with patch("subprocess.run", side_effect=Exception("Git error")):
        commits = gsr.get_recent_git_commits()
        assert commits == ""

    # subprocess.run が 0 以外の returncode を返す
    mock_run = MagicMock()
    mock_run.returncode = 1
    with patch("subprocess.run", return_value=mock_run):
        commits = gsr.get_recent_git_commits()
        assert commits == ""

    # git_commits が空の場合
    mock_run_success = MagicMock()
    mock_run_success.returncode = 0
    mock_run_success.stdout = "no flash commits here"
    with patch("subprocess.run", return_value=mock_run_success):
        commits = gsr.get_recent_git_commits()
        assert commits == ""

    # git_commits で [Flash/ を含むがフォーマットが異常な場合
    mock_run_success.stdout = "abc 2026-05-26 12:00:00 [Flash/ msg\n"
    with patch("subprocess.run", return_value=mock_run_success):
        commits = gsr.get_recent_git_commits()
        assert "abc" in commits

    # extract_metrics_from_report で regex マッチしない場合の PASS率 などの分岐
    report_file = mock_env["workspace"] / "dummy_report.md"
    report_file.write_text("PASS率 | 90.0%\n", encoding="utf-8")
    metrics = gsr.extract_metrics_from_report(str(report_file))
    assert metrics["quality_score"] == 90.0

def test_roadmap_progress(mock_env, monkeypatch):
    phase_state_path = mock_env["workspace"] / "backend" / "agents" / "memory" / "phase_state.json"
    phase_state_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. 正常系 & max_phase 拡張 & milestone なし & next_milestones なし & 更新遅延
    last_updated_time = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat().replace("+00:00", "Z")
    state_data = {
        "current_phase": 30,
        "current_milestone": "?",
        "roadmap_max_phase": 25,
        "next_milestones": [],
        "last_updated": last_updated_time
    }
    with open(str(phase_state_path), "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    roadmap_md = gsr.generate_roadmap_progress()
    assert "ロードマップ拡張が必要" in roadmap_md
    assert "マイルストーン未定義" in roadmap_md
    assert "次期マイルストーン未計画" in roadmap_md
    assert "ロードマップ未更新" in roadmap_md

    # 2. json デコードエラー時の early return
    phase_state_path.write_text("invalid json", encoding="utf-8")
    assert gsr.generate_roadmap_progress() == ""

def test_event_log_translations(mock_env):
    os.makedirs(gsr.REPORT_BASE_DIR, exist_ok=True)
    event_log_path = os.path.join(gsr.REPORT_BASE_DIR, "event_log.jsonl")

    # 1. _read_recent_events でのイベント変換
    # イベントログの時刻は JST 表記。ローカル時刻で作ると UTC 環境で 9 時間ずれる
    from backend.agents.orchestration.jst_time import jst_stamp
    ts_str = jst_stamp()
    events = [
        {"timestamp": ts_str, "health": "UNHEALTHY", "change": ["auto_stop: error", "lifecycle: COMPLETE", "lifecycle: FINISHING", "lifecycle: ACTIVE", "lifecycle: STOPPED", "health: UNHEALTHY", "health: DEGRADED", "health: DEGRADED → HEALTHY", "health: HEALTHY -> HEALTHY", "health: HEALTHY", "other change message"]},
    ]
    with open(event_log_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    events_md = gsr._read_recent_events(event_log_path)
    assert "自動停止" in events_md
    assert "完遂" in events_md
    assert "正常復旧" in events_md

    # 2. _read_recent_events でファイルなし
    os.remove(event_log_path)
    assert "イベントログはまだありません" in gsr._read_recent_events(event_log_path)

    # 3. _read_recent_events で空
    with open(event_log_path, "w", encoding="utf-8") as f:
        pass
    assert "イベントログは空です" in gsr._read_recent_events(event_log_path)

    # 4. _read_recent_events でパースエラー行を含む場合
    with open(event_log_path, "w", encoding="utf-8") as f:
        f.write("invalid json\n")
    assert "直近24時間のイベントはありません" in gsr._read_recent_events(event_log_path)

    # 5. stability metrics のダウンタイム計算
    now_utc = datetime.now(timezone.utc)
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    
    ts1 = (now_jst - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M JST")
    ts2 = (now_jst - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M JST")
    
    events_stability = [
        {"timestamp": ts1, "health": "UNHEALTHY", "change": ["health: HEALTHY -> UNHEALTHY"]},
        {"timestamp": ts2, "health": "HEALTHY", "change": ["health: UNHEALTHY -> HEALTHY"]},
    ]
    with open(event_log_path, "w", encoding="utf-8") as f:
        for ev in events_stability:
            f.write(json.dumps(ev) + "\n")

    session_data = {
        "status": "running",
        "last_heartbeat": (now_utc - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    }
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    stability_md = gsr.generate_stability_metrics()
    assert "稼働率" in stability_md
    assert "ダウンタイム" in stability_md

def test_main_actions_and_concentration(mock_env, monkeypatch):
    # TDR で CRITICAL を 1 にする
    tdr_file = mock_env["workspace"] / "backend" / "agents" / "memory" / "technical_debt_index.json"
    tdr_file.parent.mkdir(parents=True, exist_ok=True)
    tdr_data = {
        "entries": [
            {"status": "open", "category": "CRITICAL_DEBT"}
        ]
    }
    tdr_file.write_text(json.dumps(tdr_data), encoding="utf-8")

    # flash_session で auto_stop_reason ありにする
    session_data = {
        "status": "running",
        "last_heartbeat": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "auto_stop_reason": "token_limit_reached"
    }
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(session_data, f)

    # 偏り用のレポートデータを配置
    flash_reports_data = []
    now_utc = datetime.now(timezone.utc)
    for i in range(11):
        flash_reports_data.append({
            "timestamp": now_utc.isoformat().replace("+00:00", "Z"),
            "batch_id": f"batch_{i}",
            "tasks": [
                {
                    "id": f"task_{i}",
                    "status": "pass",
                    "group": "bug_hunter" if i < 10 else "refactor",
                    "target_module": "bug_hunter.py"
                }
            ]
        })
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        for entry in flash_reports_data:
            f.write(json.dumps(entry) + "\n")

    mock_hc = {
        "overall": "UNHEALTHY",
        "report": "dummy report",
        "flash_lifecycle": {"status": "COMPLETE"}
    }
    
    with patch("backend.agents.orchestration.health_check.run_health_check", return_value=mock_hc):
        gsr.generate_dashboard_quick()

    readme_path = os.path.join(gsr.REPORT_BASE_DIR, "README.md")
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "新規Flashセッションを開設" in content
    assert "CRITICAL負債" in content
    assert "自動停止されました" in content
    assert "エージェント偏り" in content

    # 2. リンク切れ検出の警告ルート
    with open(readme_path, "a", encoding="utf-8") as f:
        f.write("\n[リンク切れテスト](file:///C:/non_existent_file_xyz.md)\n")
    
    broken = gsr.validate_dashboard_links(readme_path)
    assert len(broken) > 0

    # 3. _record_event_if_changed で json_decode エラーなどの例外ハンドリング
    event_log_path = os.path.join(gsr.REPORT_BASE_DIR, "event_log.jsonl")
    with open(event_log_path, "w", encoding="utf-8") as f:
        f.write("invalid json\n")
    gsr._record_event_if_changed(event_log_path, "COMPLETE", "UNHEALTHY", "now")

def test_main_quick_execution(mock_env, monkeypatch):
    monkeypatch.setattr(gsr, "WORKSPACE_DIR", "C:\\some\\safe\\path")
    
    task_queue_data = {"tasks": []}
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(task_queue_data, f)
        
    with patch("sys.argv", ["generate_subagent_reports.py", "--quick"]):
        import runpy
        runpy.run_path(gsr.__file__, run_name="__main__")


def test_main_group_fallback(mock_env, monkeypatch):
    # 改善D: group が None や "unknown" の場合のフォールバックテスト
    brain_dir = mock_env["workspace"] / "brain"
    brain_report = brain_dir / "some_session" / "daily_report_20260524.md"
    brain_report.parent.mkdir(parents=True, exist_ok=True)
    brain_report.write_text("brain report content", encoding="utf-8")
    
    task_queue_data = {
        "tasks": [
            {
                "id": "task_unknown_group",
                "status": "pass",
                "group": "unknown",
                "target_module": "thumbnail_generator.py",
                "started_at": "2026-05-24T10:00:00Z",
                "completed_at": "2026-05-24T10:01:00Z"
            },
            {
                "id": "task_none_group",
                "status": "fail",
                "group": None,
                "target_module": "bug_hunter.py",
                "started_at": "2026-05-24T10:05:00Z",
                "completed_at": "2026-05-24T10:05:10Z"
            }
        ]
    }
    with open(gsr.TASK_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(task_queue_data, f)
        
    mock_store_inst = MagicMock()
    with patch("agents.memory.technical_debt.TechnicalDebtStore", return_value=mock_store_inst):
        gsr.main(brain_report_path=str(brain_report))
        
    ranking_dir = gsr.RANKING_REPORT_DIR
    ranking_files = os.listdir(ranking_dir)
    assert len(ranking_files) == 1
    ranking_file = os.path.join(ranking_dir, ranking_files[0])
    with open(ranking_file, "r", encoding="utf-8") as f:
        ranking_content = f.read()
    
    assert "thumbnail Agent" in ranking_content
    assert "bug_hunter Agent" in ranking_content


def test_generate_batch_timeline_exception(mock_env):
    # generate_batch_timeline の 607-609行目 例外ケース
    import builtins
    with patch("builtins.open", side_effect=IOError("Mock read error")):
        timeline = gsr.generate_batch_timeline()
        assert timeline == ""


def test_generate_task_detail_summary_edge_cases(mock_env):
    # 637行目の tasks 空ケース
    flash_reports_data = [
        {
            "batch_id": "batch_empty",
            "tasks": []
        }
    ]
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        for entry in flash_reports_data:
            f.write(json.dumps(entry) + "\n")
            
    assert gsr.generate_task_detail_summary() == ""

    # 671-673行目 例外ケース
    import builtins
    with patch("builtins.open", side_effect=IOError("Mock read error")):
        assert gsr.generate_task_detail_summary() == ""


def test_generate_session_cumulative_stats_exceptions(mock_env, monkeypatch):
    import builtins
    # 準備
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": "2026-05-24T10:00:00Z", "results": {"passed": 1, "failed": 0}}) + "\n")
    with open(gsr.FLASH_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump({"status": "running", "session_started_at": "2026-05-24T09:00:00Z"}, f)

    # 725-726行目: session json 読み込み例外
    original_open = builtins.open
    def mock_open_session(file, *args, **kwargs):
        if "flash_session.json" in str(file):
            raise IOError("Session load error")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open_session):
        stats = gsr.generate_session_cumulative_stats()
        # 例外をキャッチしつつ、他は処理されるので stats は空ではない
        assert stats != ""

    # 739-740行目: timestamp パース例外
    original_parse = gsr.parse_iso_datetime
    def mock_parse_error(ts):
        if ts == "2026-05-24T10:00:00Z":
            raise ValueError("Mock parse error")
        return original_parse(ts)
    monkeypatch.setattr(gsr, "parse_iso_datetime", mock_parse_error)
    stats2 = gsr.generate_session_cumulative_stats()
    assert stats2 != ""
    monkeypatch.setattr(gsr, "parse_iso_datetime", original_parse)

    # 758-761行目: json.JSONDecodeError と Exception のカバー
    # reportのパース時に例外
    def mock_open_reports(file, *args, **kwargs):
        if "flash_reports.jsonl" in str(file):
            raise IOError("Reports read error")
        return original_open(file, *args, **kwargs)
    with patch("builtins.open", side_effect=mock_open_reports):
        stats3 = gsr.generate_session_cumulative_stats()
        assert stats3 == ""  # reports が開けないと total_batches == 0 で early return "" になる

    # 796-797行目: design_stock.json 読込例外
    # 820-821行目: harness_audit_status.json 読込例外
    # これらは os.path.exists で True にさせつつ open で例外をスローさせる
    original_exists = os.path.exists
    def mock_exists(path):
        if "design_stock.json" in path or "harness_audit_status.json" in path:
            return True
        return original_exists(path)
        
    def mock_open_jsons(file, *args, **kwargs):
        if "design_stock.json" in str(file) or "harness_audit_status.json" in str(file):
            raise IOError("JSON open error")
        return original_open(file, *args, **kwargs)

    with patch("os.path.exists", side_effect=mock_exists), patch("builtins.open", side_effect=mock_open_jsons):
        stats4 = gsr.generate_session_cumulative_stats()
        assert stats4 != ""

    # 832-834行目: 全体の例外
    # json.loads が AttributeError をスローするように、flash_reports.jsonl に [] (リスト型) を書き込む
    with open(gsr.FLASH_REPORTS_PATH, "w", encoding="utf-8") as f:
        f.write("[]\n")
    assert gsr.generate_session_cumulative_stats() == ""
    if os.path.exists(gsr.FLASH_REPORTS_PATH):
        try:
            os.remove(gsr.FLASH_REPORTS_PATH)
        except OSError:
            pass


def test_get_recent_git_commits_fallback(mock_env):
    # 872行目: parts が 4 未満のフォールバック
    mock_run_success = MagicMock()
    mock_run_success.returncode = 0
    # スペースが2つしかない（parts の長さが 3 になる）[Flash/ コミットログ
    mock_run_success.stdout = "abc 2026-05-26 [Flash/msg_with_no_time\n"
    with patch("subprocess.run", return_value=mock_run_success):
        commits = gsr.get_recent_git_commits()
        # フォールバック処理で commits テーブルに反映されているか
        assert "abc" in commits
        assert "[Flash/" in commits


def test_sys_path_contains_backend():
    # WORKSPACE_DIR/backend が sys.path に存在することを確認する
    import os
    import sys
    import backend.agents.orchestration.generate_subagent_reports as gsr
    
    expected_backend_path = os.path.normpath(os.path.join(gsr.WORKSPACE_DIR, "backend"))
    sys_paths_normalized = [os.path.normpath(p) for p in sys.path]
    assert expected_backend_path in sys_paths_normalized


def test_get_flash_profile_import():
    # _get_flash_profile が正しくインポートできて dict を返すことを確認するテスト
    from backend.agents.orchestration.hub_common import _get_flash_profile
    assert _get_flash_profile is not None
    profile = _get_flash_profile()
    assert isinstance(profile, dict)


def test_sys_path_no_duplicate_insertions_on_reload():
    import sys
    import importlib
    import backend.agents.orchestration.generate_subagent_reports as gsr
    
    workspace_dir = gsr.WORKSPACE_DIR
    backend_path = os.path.join(workspace_dir, "backend")
    
    # Ensure they are in sys.path initially
    assert workspace_dir in sys.path
    assert backend_path in sys.path
    
    count_ws_before = sys.path.count(workspace_dir)
    count_backend_before = sys.path.count(backend_path)
    
    # Reload module to trigger top-level code execution
    importlib.reload(gsr)
    
    count_ws_after = sys.path.count(workspace_dir)
    count_backend_after = sys.path.count(backend_path)
    
    assert count_ws_after == count_ws_before, "WORKSPACE_DIR was duplicate inserted into sys.path upon module reload"
    assert count_backend_after == count_backend_before, "backend_path was duplicate inserted into sys.path upon module reload"
