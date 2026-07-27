"""
演出哲学還流エンジン (Soul Feedback Engine) 用のユニットテスト。

タスクID: T-batch_a41cc2-ds-ds-raw-s5-efc3
"""

import sys
import os
import json
from pathlib import Path
import pytest

# backend をインポートパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from video_pipeline.soul_feedback_engine import (
    SoulFeedbackEngine,
    Suggestion,
    ProductionContext,
    FeedbackOutput,
    AnalysisResult,
    ComplianceResult
)


@pytest.mark.parametrize(
    "case_name, context, custom_data, limit, expected_sug_min, expected_sug_max, expected_score_min, expected_score_max, expected_pat_min, expected_pat_max",
    [
        # 1. 正常系1: デフォルトコンテキスト, サンプルデータフォールバック (ログファイル未存在)
        ("normal_default_sample_fallback", None, None, 10, 1, 20, 0.0, 100.0, 1, 50),
        # 2. 正常系2: 長尺動画コンテキスト (duration_seconds=600)
        ("normal_long_duration", ProductionContext(duration_seconds=600), None, 10, 1, 20, 0.0, 100.0, 1, 50),
        # 3. 正常系3: カスタムの健全なデータ
        (
            "normal_custom_data",
            None,
            {
                "post_publish_feedbacks": [
                    {
                        "timestamp": "2026-06-27T10:00:00",
                        "video_id": "vid_custom_01",
                        "actual_ctr": 9.5,
                        "actual_retention": 80.0,
                        "significant_deviation": True,
                        "lessons_learned": [
                            "テンポが良くテロップの色彩コントラストも高い",
                            "SE効果的",
                            "タイトルに数字を含めるとCTR向上"
                        ]
                    }
                ]
            },
            5,
            1, 20, 50.0, 100.0, 1, 50
        ),
        # 4. 境界値1: limit = 0 (analyze_past_videos 自体の limit=0 をテスト。generate_suggestions はデフォルト limit=10 を呼ぶため提案あり)
        ("boundary_limit_zero", None, None, 0, 1, 20, 0.0, 100.0, 0, 0),
        # 5. 境界値2: limit = 100 (データ件数を超える極端に大きい limit)
        ("boundary_limit_large", None, None, 100, 1, 20, 0.0, 100.0, 1, 50),
        # 6. 境界値3: duration_seconds = -10 (負数)
        ("boundary_negative_duration", ProductionContext(duration_seconds=-10), None, 10, 1, 20, 0.0, 100.0, 1, 50),
        # 7. 異常系1: 壊れた JSON 形式の evolution_log.json (安全にフォールバック)
        ("error_corrupted_json", None, "corrupted_json_string_not_dict", 10, 1, 20, 0.0, 100.0, 1, 50),
        # 8. 異常系2: 存在しないディレクトリを指定した初期化
        ("error_nonexistent_dir", None, "nonexistent_dir_setup", 10, 1, 20, 0.0, 100.0, 1, 50),
    ]
)
def test_soul_feedback_engine_parametrize(
    tmp_path,
    case_name,
    context,
    custom_data,
    limit,
    expected_sug_min,
    expected_sug_max,
    expected_score_min,
    expected_score_max,
    expected_pat_min,
    expected_pat_max
):
    # 一時ディレクトリに設定を準備
    analytics_dir = tmp_path / "branding"
    analytics_dir.mkdir(exist_ok=True)
    constitution_path = tmp_path / "PROJECT_CONSTITUTION.md"
    
    # 憲法ファイルのモック作成
    constitution_content = """# PROJECT CONSTITUTION
    * 攻撃的表現は禁止。
    * 扇情的表現も避けること。
    """
    constitution_path.write_text(constitution_content, encoding="utf-8")

    # custom_dataのセットアップ
    if case_name == "error_nonexistent_dir":
        engine = SoulFeedbackEngine(
            analytics_dir=str(tmp_path / "nonexistent_dir_path_12345"),
            constitution_path=str(constitution_path)
        )
    else:
        log_path = analytics_dir / "evolution_log.json"
        if isinstance(custom_data, dict):
            log_path.write_text(json.dumps(custom_data, ensure_ascii=False), encoding="utf-8")
        elif isinstance(custom_data, str) and custom_data == "corrupted_json_string_not_dict":
            log_path.write_text("{invalid_json_data", encoding="utf-8")
        # None の場合はファイルを配置しない (データなし)

        engine = SoulFeedbackEngine(
            analytics_dir=str(analytics_dir),
            constitution_path=str(constitution_path)
        )

    # 1. analyze_past_videos のテスト
    analysis = engine.analyze_past_videos(limit=limit)
    assert isinstance(analysis, AnalysisResult)
    
    # パターン数の検証
    total_patterns = sum(len(v) for v in analysis.patterns.values())
    assert expected_pat_min <= total_patterns <= expected_pat_max

    # 2. generate_suggestions のテスト
    output = engine.generate_suggestions(context=context)
    assert isinstance(output, FeedbackOutput)
    
    # 提案数の検証
    assert expected_sug_min <= len(output.suggestions) <= expected_sug_max
    
    # スコアの検証
    assert expected_score_min <= output.overall_score <= expected_score_max


def test_constitution_compliance_logic(tmp_path):
    # 憲法整合チェックロジックの個別テスト
    constitution_path = tmp_path / "PROJECT_CONSTITUTION.md"
    constitution_content = """# PROJECT CONSTITUTION
    * 攻撃的表現は禁止。
    * 扇情的表現も避けること。
    """
    constitution_path.write_text(constitution_content, encoding="utf-8")

    engine = SoulFeedbackEngine(
        analytics_dir=str(tmp_path),
        constitution_path=str(constitution_path)
    )

    # 準拠する提案
    compliant_sug = Suggestion(
        category="テンポ",
        suggestion="カット数を増やす",
        evidence="CTR向上",
        priority="medium",
        confidence=0.8
    )

    # 憲法の禁止パターン（フラッシュ点滅、過度な画面振動など）に抵触する提案
    non_compliant_sug1 = Suggestion(
        category="ビジュアル",
        suggestion="フラッシュ点滅を使用して注意を引く",
        evidence="離脱防止",
        priority="high",
        confidence=0.9
    )

    # 憲法テキストに抵触する提案（「攻撃的」「扇情的」「過激」など）
    # suggestion 内に "攻撃的" というキーワードを含めることで、モック憲法にヒットさせます
    non_compliant_sug2 = Suggestion(
        category="テキスト",
        suggestion="攻撃的な言葉遣いでサムネイルを作成する",
        evidence="CTR劇的向上",
        priority="high",
        confidence=0.9
    )

    results = engine.check_constitution_compliance([compliant_sug, non_compliant_sug1, non_compliant_sug2])
    
    assert len(results) == 3
    
    # compliant_sug の検証
    assert results[0].compliant is True
    assert results[0].reason == ""
    
    # non_compliant_sug1 の検証（禁止パターン照合）
    assert results[1].compliant is False
    assert "禁止パターン検出" in results[1].reason

    # non_compliant_sug2 の検証（憲法テキスト照合）
    assert results[2].compliant is False
    assert "憲法の禁止事項に抵触" in results[2].reason
