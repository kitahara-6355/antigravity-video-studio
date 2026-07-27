# -*- coding: utf-8 -*-
import pytest
import logging
from quality_gate_agent import QualityGateAgent, QualityLevel, QualityIssue, QualityReport, quality_gate

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
    content = {
        "full_text": "意外と難しいですが、とうりすがりのアドバイスに従います。",
        "segments": [
            {"text": "以外と難しい。", "start": 0.0, "end": 1.0},
            {"text": "とうりすがりの人。", "start": 1.0, "end": 2.0},
            {"text": "この字幕は文字数が非常に多くて表示時間が短い警告パターンです。", "start": 2.0, "end": 4.5}
        ],
        "scenes": [],
        "constitution": {
            "forbidden_words": []
        }
    }
    report = agent.run_gate(content)
    assert report.is_ready is False
    assert report.score == 70
    assert "品質基準未達" in report.summary

    # スコア80で合格するケース
    content_pass = {
        "full_text": "",
        "segments": [
            {"text": "以外と難しい。", "start": 0.0, "end": 5.0},
            {"text": "とうりすがりの人。", "start": 5.0, "end": 10.0}
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
    content = {
        "full_text": "この原稿には禁止ワードが含まれています。",
        "segments": [],
        "scenes": [],
        "constitution": {
            "forbidden_words": ["禁止ワード"]
        }
    }
    report = agent.run_gate(content)
    assert report.is_ready is False
    assert report.score == 70
    assert "品質基準未達" in report.summary
    assert len(report.issues) == 1
    assert report.issues[0].level == QualityLevel.CRITICAL

def test_subtitle_rhythm_short():
    agent = QualityGateAgent()
    content = {
        "full_text": "",
        "segments": [
            {"text": "あ", "start": 0.0, "end": 1.0}
        ],
        "scenes": []
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 98
    assert len(report.issues) == 1
    assert report.issues[0].level == QualityLevel.INFO
    assert report.issues[0].category == "リズム"

def test_scene_coherence_ai():
    agent = QualityGateAgent()
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
    issues_min = [
        QualityIssue(level=QualityLevel.CRITICAL, category="c", message="m", suggestion="s")
        for _ in range(5)
    ]
    score_min = agent._calculate_score(issues_min)
    assert score_min == 0

    issues_empty = []
    score_max = agent._calculate_score(issues_empty)
    assert score_max == 100

def test_run_gate_exception_handling(caplog):
    agent = QualityGateAgent()

    # KeyErrorを発生させる
    def check_key_error(content):
        raise KeyError("missing_key")

    # TypeErrorを発生させる
    def check_type_error(content):
        raise TypeError("invalid_type")

    # ValueErrorを発生させる
    def check_value_error(content):
        raise ValueError("invalid_value")

    # 一般例外を発生させる
    def check_general_exception(content):
        raise RuntimeError("unexpected_error")

    agent.checks = [
        check_key_error,
        check_type_error,
        check_value_error,
        check_general_exception
    ]

    content = {
        "full_text": "",
        "segments": [],
        "scenes": []
    }

    # 各例外が発生してもクラッシュせず、正常にレポートが返ることを検証
    with caplog.at_level(logging.WARNING):
        report = agent.run_gate(content)
        assert report.is_ready is True
        assert report.score == 100

        # 各例外に対するログ出力の検証
        log_messages = [record.message for record in caplog.records]
        assert any("Quality check missing required key: check_key_error - Missing key: 'missing_key'" in msg for msg in log_messages) or                any("Quality check missing required key: check_key_error - Missing key: missing_key" in msg for msg in log_messages)
        assert any("Quality check type mismatch: check_type_error - invalid_type" in msg for msg in log_messages)
        assert any("Quality check invalid value: check_value_error - invalid_value" in msg for msg in log_messages)
        
        # ERROR レベルのログを確認
        assert any("Unexpected quality check failure: check_general_exception - unexpected_error" in msg for msg in [record.message for record in caplog.records])

def test_singleton_instance():
    assert quality_gate is not None
    assert isinstance(quality_gate, QualityGateAgent)

def test_calculate_score_unknown_level():
    agent = QualityGateAgent()
    issue_unknown = QualityIssue(
        level=None,  # type: ignore
        category="テスト",
        message="未知のレベル",
        suggestion="提案"
    )
    score = agent._calculate_score([issue_unknown])
    assert score == 100

def test_scene_coherence_ai_no_katakana():
    agent = QualityGateAgent()
    content = {
        "full_text": "",
        "segments": [],
        "scenes": [
            {"name": "テスト", "source_type": "AI"},
            {"name": "ひらがなシーン", "source_type": "AI"},
            {"name": "AI映像", "source_type": "AI"}
        ]
    }
    report = agent.run_gate(content)
    assert report.is_ready is True
    assert report.score == 100
    assert len(report.issues) == 0

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

    # 「づつ」は誤判定パターン（警告が出る）
    content_wrong = {
        "full_text": "",
        "segments": [
            {"text": "少しづつ進めます。", "start": 0.0, "end": 2.0}
        ],
        "scenes": []
    }
    report_wrong = agent.run_gate(content_wrong)
    assert len(report_wrong.issues) == 1
    assert "づつ" in report_wrong.issues[0].message


def test_run_gate_robustness():
    agent = QualityGateAgent()
    
    # 1. content が辞書ではない場合
    report_invalid_content = agent.run_gate(None)  # type: ignore
    assert report_invalid_content.is_ready is True
    assert report_invalid_content.score == 100

    # 2. segments や scenes がリストではない場合、要素が辞書でない場合
    content_invalid_types = {
        "full_text": None,
        "segments": "not_a_list",
        "scenes": [{"name": 1234, "source_type": None}, "not_a_dict"],
        "constitution": "not_a_dict"
    }
    report_invalid_types = agent.run_gate(content_invalid_types)  # type: ignore
    assert report_invalid_types.is_ready is True
    assert report_invalid_types.score == 100

    # 3. start / end の型が不正な場合
    content_invalid_times = {
        "full_text": "",
        "segments": [
            {"text": "テスト", "start": "invalid_time", "end": None}
        ],
        "scenes": []
    }
    report_invalid_times = agent.run_gate(content_invalid_times)
    assert report_invalid_times.is_ready is True
    assert report_invalid_times.score == 100


def test_comprehensive_check_ready():
    agent = QualityGateAgent()
    res = agent.comprehensive_check(
        full_text="これは正常な原稿です。",
        scenes=[{"name": "正常なシーン", "source_type": "LIVE"}],
        segments=[{"text": "正常な字幕です。", "start": 0.0, "end": 2.0}]
    )
    assert res["is_ready"] is True
    assert res["status"] == "passed"
    assert res["score"] == 100
    assert len(res["details"]) == 0

def test_comprehensive_check_fail():
    agent = QualityGateAgent()
    # 警告を2つ、INFOを1つ発生させてスコアを78にし、is_readyをFalseにする
    res = agent.comprehensive_check(
        full_text="これは原稿です。",
        scenes=[{"name": "プロトタイプシーン", "source_type": "AI"}],  # info警告(スコア-2)
        segments=[
            {"text": "以外と難しい。", "start": 0.0, "end": 1.0},        # warning警告(スコア-10)
            {"text": "とうりすがりの人。", "start": 1.0, "end": 2.0},      # warning警告(スコア-10)
        ]
    )
    # スコア: 100 - 2(INFO) - 10(WARNING) - 10(WARNING) = 78
    assert res["is_ready"] is False
    assert res["status"] == "failed"
    assert res["score"] == 78
    assert len(res["details"]) >= 3
    details = res["details"]
    categories = [d["category"] for d in details]
    assert "誤字脱字" in categories
    assert "演出ロジック" in categories

def test_pre_render_check_ready():
    agent = QualityGateAgent()
    data = {
        "full_text": "正常なテキスト",
        "scenes": [],
        "segments": []
    }
    res = agent.pre_render_check(data)
    assert res["is_ready"] is True
    assert res["status"] == "ok"
    assert res["score"] == 100

def test_pre_render_check_fail():
    agent = QualityGateAgent()
    data = {
        "full_text": "正常なテキストですが禁止ワードがあります",
        "scenes": [],
        "segments": [],
        "constitution": {
            "forbidden_words": ["禁止ワード"]
        }
    }
    res = agent.pre_render_check(data)
    assert res["is_ready"] is False
    assert res["status"] == "failed"
    assert res["score"] < 80
