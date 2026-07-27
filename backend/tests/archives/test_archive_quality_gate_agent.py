import pytest
import sys
import os
from pathlib import Path
import importlib.util

# backend ディレクトリへのパスを通す
backend_dir = Path(__file__).resolve().parents[2]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

# テスト対象モジュールのインポート
module_path = backend_dir / "archives" / "archive_stable_v3.0_20260118_0953" / "quality_gate_agent.py"
# カバレッジ測定ツールが認識できるように、フルネームで登録する
module_name = "backend.archives.archive_stable_v3.0_20260118_0953.quality_gate_agent"
spec = importlib.util.spec_from_file_location(module_name, str(module_path))
qga_mod = importlib.util.module_from_spec(spec)
sys.modules[module_name] = qga_mod
spec.loader.exec_module(qga_mod)

QualityLevel = qga_mod.QualityLevel
QualityIssue = qga_mod.QualityIssue
QualityReport = qga_mod.QualityReport
QualityGateAgent = qga_mod.QualityGateAgent
quality_gate = qga_mod.quality_gate


def test_import_and_init():
    agent = QualityGateAgent()
    assert agent is not None
    assert len(agent.checks) == 4
    assert QualityGateAgent.THRESHOLD_PASS == 80
    assert QualityGateAgent.THRESHOLD_WARNING == 60


def test_quality_level_enum():
    assert QualityLevel.CRITICAL.value == "critical"
    assert QualityLevel.WARNING.value == "warning"
    assert QualityLevel.INFO.value == "info"


def test_quality_issue_dataclass():
    issue = QualityIssue(
        level=QualityLevel.WARNING,
        category="テスト",
        message="メッセージ",
        suggestion="提案",
        location="場所"
    )
    assert issue.level == QualityLevel.WARNING
    assert issue.category == "テスト"
    assert issue.message == "メッセージ"
    assert issue.suggestion == "提案"
    assert issue.location == "場所"

    issue_no_loc = QualityIssue(
        level=QualityLevel.INFO,
        category="テスト",
        message="メッセージ",
        suggestion="提案"
    )
    assert issue_no_loc.location is None


def test_quality_report_to_dict():
    issue = QualityIssue(
        level=QualityLevel.INFO,
        category="テスト",
        message="メッセージ",
        suggestion="提案",
        location="場所"
    )
    report = QualityReport(
        is_ready=True,
        score=90,
        issues=[issue],
        summary="サマリー"
    )
    d = report.to_dict()
    assert d["is_ready"] is True
    assert d["score"] == 90
    assert d["summary"] == "サマリー"
    assert len(d["issues"]) == 1
    assert d["issues"][0]["level"] == "info"
    assert d["issues"][0]["category"] == "テスト"
    assert d["issues"][0]["message"] == "メッセージ"
    assert d["issues"][0]["suggestion"] == "提案"
    assert d["issues"][0]["location"] == "場所"


def test_run_gate_excellent():
    agent = QualityGateAgent()
    # 完全に正常なコンテンツ
    content = {
        "full_text": "これは正常な原稿です。問題ありません。",
        "segments": [
            {"text": "これは正常な字幕です。", "start": 0.0, "end": 2.0}
        ],
        "scenes": [
            {"name": "正常なシーン", "source_type": "LIVE"}
        ],
        "constitution": {
            "forbidden_words": ["禁止語句"]
        }
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert "優秀" in report.summary
    assert len(report.issues) == 0


def test_run_gate_pass_with_warnings():
    agent = QualityGateAgent()
    # 警告を含むコンテンツ
    content = {
        "full_text": "意外と難しいですが、とうりすがりのアドバイスに従います。",
        "segments": [
            # 「以外と」（警告）、「とうり」（警告）
            {"text": "以外と難しい。", "start": 0.0, "end": 1.0},
            {"text": "とうりすがりの人。", "start": 1.0, "end": 2.0},
            # 20文字以上かつ3秒未満（警告）
            {"text": "この字幕は文字数が非常に多くて表示時間が短い警告パターンです。", "start": 2.0, "end": 4.5}
        ],
        "scenes": [],
        "constitution": {
            "forbidden_words": []
        }
    }
    report = agent.run_gate(content)
    # WARNING が3つあるので、スコアは 100 - 10*3 = 70。
    # 警告のみで CRITICAL はないので、THRESHOLD_PASS(80)未満なので is_ready=False になるはず。
    assert report.is_ready is False
    assert report.score == 70
    assert "品質基準未達" in report.summary

    # 警告を2つだけにしてスコア80（合格）にするケース
    content_pass = {
        "full_text": "",
        "segments": [
            {"text": "以外と難しい。", "start": 0.0, "end": 5.0},  # WARNING 1つ (-10)
            {"text": "とうりすがりの人。", "start": 5.0, "end": 10.0}  # WARNING 1つ (-10)
        ],
        "scenes": [],
        "constitution": {}
    }
    report_pass = agent.run_gate(content_pass)
    assert report_pass.is_ready is True
    assert report_pass.score == 80
    assert "合格基準を満たしています" in report_pass.summary


def test_run_gate_fail_with_critical():
    agent = QualityGateAgent()
    # 禁止ワード（CRITICAL）を含むコンテンツ
    content = {
        "full_text": "この原稿には禁止ワードが含まれています。",
        "segments": [],
        "scenes": [],
        "constitution": {
            "forbidden_words": ["禁止ワード"]
        }
    }
    report = agent.run_gate(content)
    # CRITICAL 1つ (-30) なので、スコアは70、かつ CRITICAL ありなので is_ready は False
    assert report.is_ready is False
    assert report.score == 70
    assert "品質基準未達" in report.summary
    assert len(report.issues) == 1
    assert report.issues[0].level == QualityLevel.CRITICAL


def test_subtitle_rhythm_short():
    agent = QualityGateAgent()
    # 2文字以下の短い字幕（INFO）
    content = {
        "full_text": "",
        "segments": [
            {"text": "あ", "start": 0.0, "end": 1.0}
        ],
        "scenes": []
    }
    report = agent.run_gate(content)
    # INFO 1つ (-2) なのでスコア98、is_readyはTrue
    assert report.is_ready is True
    assert report.score == 98
    assert len(report.issues) == 1
    assert report.issues[0].level == QualityLevel.INFO
    assert report.issues[0].category == "リズム"


def test_scene_coherence_ai():
    agent = QualityGateAgent()
    # AIシーンでカタカナ4文字以上（INFO）
    content = {
        "full_text": "",
        "segments": [],
        "scenes": [
            {"name": "プロトタイプシーン", "source_type": "AI"}
        ]
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 98
    assert len(report.issues) == 1
    assert report.issues[0].level == QualityLevel.INFO
    assert report.issues[0].category == "演出ロジック"


def test_calculate_score_boundary():
    agent = QualityGateAgent()
    # スコア計算のみのテスト
    issues_min = [
        QualityIssue(level=QualityLevel.CRITICAL, category="c", message="m", suggestion="s")
        for _ in range(5)
    ]
    # CRITICAL 5つ (-150) -> 下限 0 になることを確認
    score_min = agent._calculate_score(issues_min)
    assert score_min == 0

    issues_empty = []
    # 課題なし -> 100 になることを確認
    score_max = agent._calculate_score(issues_empty)
    assert score_max == 100


def test_check_func_error_handling(caplog):
    agent = QualityGateAgent()
    # 例外を投げるダミーのチェック関数を追加
    def bad_check(content):
        raise RuntimeError("ダミーエラー")

    agent.checks.append(bad_check)
    
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    # 例外が発生しても run_gate はクラッシュせず、正常にレポートを返すこと
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    
    # ログ出力に警告が含まれていることを確認
    assert any("Unexpected quality check failure: bad_check - ダミーエラー" in record.message for record in caplog.records)


def test_check_func_attribute_error_handling(caplog):
    agent = QualityGateAgent()
    def bad_check_attr(content):
        raise AttributeError("属性エラー")
    
    agent.checks.append(bad_check_attr)
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert any("Unexpected quality check failure: bad_check_attr - 属性エラー" in record.message for record in caplog.records)


def test_check_func_index_error_handling(caplog):
    agent = QualityGateAgent()
    def bad_check_index(content):
        raise IndexError("インデックスエラー")
    
    agent.checks.append(bad_check_index)
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert any("Unexpected quality check failure: bad_check_index - インデックスエラー" in record.message for record in caplog.records)


def test_check_funcs_with_none_values():
    agent = QualityGateAgent()
    # segments や scenes に None や無効な型のデータが含まれているケース
    content = {
        "full_text": None,
        "segments": [
            None,
            {"text": None, "start": None, "end": 2.0},
            {"text": "有効な字幕", "start": "無効な時間", "end": "無効な時間"},
        ],
        "scenes": [
            None,
            {"name": None, "source_type": None},
        ],
        "constitution": {
            "forbidden_words": [None]
        }
    }
    # クラッシュせずに処理されることを確認
    report = agent.run_gate(content)
    assert report is not None
    assert report.is_ready is True
    assert report.score == 100


def test_check_func_re_error_handling(caplog):
    agent = QualityGateAgent()
    import re
    def bad_check_re(content):
        raise re.error("正規表現エラー")
    
    agent.checks.append(bad_check_re)
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert any("Unexpected quality check failure: bad_check_re - 正規表現エラー" in record.message for record in caplog.records)


def test_check_func_key_error_handling(caplog):
    agent = QualityGateAgent()
    def bad_check_key(content):
        raise KeyError("キーエラー")
    
    agent.checks.append(bad_check_key)
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert any("Quality check missing required key: bad_check_key - Missing key: 'キーエラー'" in record.message for record in caplog.records)


def test_check_func_value_error_handling(caplog):
    agent = QualityGateAgent()
    def bad_check_value(content):
        raise ValueError("値エラー")
    
    agent.checks.append(bad_check_value)
    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert any("Quality check invalid value: bad_check_value - 値エラー" in record.message for record in caplog.records)


def test_check_typos_zutsu():
    agent = QualityGateAgent()
    
    # 「ずつ」は正しいので警告が出ない
    content_correct = {
        "full_text": "",
        "segments": [
            {"text": "少しずつ進めます。", "start": 0.0, "end": 2.0}
        ],
        "scenes": []
    }
    report_correct = agent.run_gate(content_correct)
    assert len(report_correct.issues) == 0

    # 「づつ」は誤字（警告が出る）
    content_wrong = {
        "full_text": "",
        "segments": [
            {"text": "少しづつ進めます。", "start": 0.0, "end": 2.0}
        ],
        "scenes": []
    }
    report_wrong = agent.run_gate(content_wrong)
    assert len(report_wrong.issues) == 1
    assert report_wrong.issues[0].category == "誤字脱字"
    assert "「づつ」は「ずつ」" in report_wrong.issues[0].message

