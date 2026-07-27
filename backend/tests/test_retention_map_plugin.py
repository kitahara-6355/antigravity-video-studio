# -*- coding: utf-8 -*-
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from plugins.retention_map_plugin import (
    RetentionMapPlugin,
    RetentionMapError,
    RetentionSegment,
    ReengagementSuggestion,
    RetentionMapReport,
    retention_map_plugin
)

def test_analyze_retention_risks_invalid_video_id():
    plugin = RetentionMapPlugin()
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("", 100)
    assert "video_id must be a non-empty string" in str(exc_info.value)

def test_analyze_retention_risks_invalid_duration():
    plugin = RetentionMapPlugin()
    # None
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", None)
    assert "duration_sec must be a positive integer" in str(exc_info.value)
    
    # Not int
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", "100")
    assert "duration_sec must be a positive integer" in str(exc_info.value)
    
    # <= 0
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", 0)
    assert "duration_sec must be a positive integer" in str(exc_info.value)
    
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", -10)
    assert "duration_sec must be a positive integer" in str(exc_info.value)

def test_analyze_retention_risks_normal_flow():
    plugin = RetentionMapPlugin()
    # 60秒の動画（6つのセグメント）
    report = plugin.analyze_retention_risks("v_normal", 60)
    assert report.video_id == "v_normal"
    assert report.total_duration_sec == 60
    assert len(report.segments) == 6
    # 最初のセグメントはフック（start==0）なので dopamine_hit が True になるはず
    assert report.segments[0].dopamine_hit is True

def test_analyze_retention_risks_mismatch_warning():
    plugin = RetentionMapPlugin()
    from plugins.retention_map_plugin import RetentionSegment
    
    original_init = RetentionSegment.__init__
    
    def mock_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        if self.start_time == 20:
            self.__dict__['end_time'] = 24
            
    with patch.object(RetentionSegment, '__init__', mock_init):
        report = plugin.analyze_retention_risks("v_mismatch", 25)
        assert report is not None
        assert report.segments[-1].end_time == 24

def test_generate_suggestions_consecutive_boring():
    plugin = RetentionMapPlugin()
    # 30秒以上ドーパミンヒットがない場合をシミュレート
    segments = [
        RetentionSegment(start_time=0, end_time=10, risk_score=50, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False),
        RetentionSegment(start_time=10, end_time=20, risk_score=50, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False),
        RetentionSegment(start_time=20, end_time=30, risk_score=50, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False),
    ]
    report = plugin._generate_suggestions("v_boring", 30, segments)
    # 10s + 10s + 10s = 30s で consecutive_boring_secs >= 30 になり、提案が追加されるはず
    assert len(report.suggestions) > 0
    assert report.suggestions[0].timestamp_sec == 20
    assert "ジャンプカットまたはB-roll挿入" in report.suggestions[0].suggestion_type

def test_generate_suggestions_three_min_point():
    plugin = RetentionMapPlugin()
    # 180秒（3分）の節目
    # 該当セグメントで dopamine_hit が False の場合
    segments = []
    for i in range(20): # 200秒分
        start = i * 10
        end = start + 10
        segments.append(RetentionSegment(
            start_time=start,
            end_time=end,
            risk_score=20,
            visual_change=True,
            audio_change=True,
            text_change=True,
            dopamine_hit=True # dopamine_hit=Trueにしておくことで30秒退屈アラートによる提案を防ぐ
        ))
    
    # 180秒(t_mark=180)のセグメント(180〜190秒、segments[18])の dopamine_hit を False にする
    segments[18] = RetentionSegment(
        start_time=180,
        end_time=190,
        risk_score=50,
        visual_change=False,
        audio_change=False,
        text_change=False,
        dopamine_hit=False
    )
    
    report = plugin._generate_suggestions("v_3min", 200, segments)
    # 180秒の節目で提案が追加されるはず
    suggestions = [s for s in report.suggestions if s.suggestion_type == "シーンの転換（BGM変更または大文字テロップ）"]
    assert len(suggestions) == 1
    assert suggestions[0].timestamp_sec == 180

def test_generate_suggestions_three_min_point_duplicate_avoided():
    plugin = RetentionMapPlugin()
    # 既に近い時間（前後15秒以内）に提案がある場合
    segments = []
    for i in range(20):
        start = i * 10
        end = start + 10
        segments.append(RetentionSegment(
            start_time=start, end_time=end, risk_score=20,
            visual_change=True, audio_change=True, text_change=True, dopamine_hit=True
        ))
    # 150-190秒を dopamine_hit=False にする
    for i in range(15, 19):
        segments[i] = RetentionSegment(
            start_time=i*10, end_time=(i+1)*10, risk_score=50,
            visual_change=False, audio_change=False, text_change=False, dopamine_hit=False
        )
        
    report = plugin._generate_suggestions("v_dup", 200, segments)
    # 3分節目の提案が追加されていないことを確認（重複回避）
    three_min_suggestions = [s for s in report.suggestions if "シーンの転換" in s.suggestion_type]
    assert len(three_min_suggestions) == 0

def test_overall_risk_assessment_levels():
    plugin = RetentionMapPlugin()
    
    # 危険 (avg_risk > 60)
    segments_danger = [
        RetentionSegment(start_time=0, end_time=10, risk_score=70, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False)
    ]
    report_danger = plugin._generate_suggestions("v_danger", 10, segments_danger)
    assert report_danger.overall_risk_assessment == "危険（要大幅な再編集）"
    
    # 要注意 (40 < avg_risk <= 60)
    segments_warning = [
        RetentionSegment(start_time=0, end_time=10, risk_score=50, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False)
    ]
    report_warning = plugin._generate_suggestions("v_warning", 10, segments_warning)
    assert report_warning.overall_risk_assessment == "要注意（一部シーンのテンポ改善が必要）"
    
    # 安全 (avg_risk <= 40)
    segments_safe = [
        RetentionSegment(start_time=0, end_time=10, risk_score=30, visual_change=False, audio_change=False, text_change=False, dopamine_hit=False)
    ]
    report_safe = plugin._generate_suggestions("v_safe", 10, segments_safe)
    assert report_safe.overall_risk_assessment == "安全"

def test_analyze_retention_risks_exceptions():
    plugin = RetentionMapPlugin()
    
    # _generate_suggestions で AttributeError
    with patch.object(plugin, "_generate_suggestions", side_effect=AttributeError("Mocked attribute error")):
        with pytest.raises(RetentionMapError) as exc_info:
            plugin.analyze_retention_risks("v_err", 10)
        assert "Failed to analyze retention risks" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, AttributeError)

    # _generate_suggestions で RetentionMapError
    with patch.object(plugin, "_generate_suggestions", side_effect=RetentionMapError("Direct retention error")):
        with pytest.raises(RetentionMapError) as exc_info:
            plugin.analyze_retention_risks("v_err", 10)
        assert "Direct retention error" in str(exc_info.value)

def test_generate_suggestions_exceptions():
    plugin = RetentionMapPlugin()
    
    # segments = None により TypeError
    with pytest.raises(RetentionMapError) as exc_info:
        plugin._generate_suggestions("v_err", 10, None)
    assert "Failed to generate suggestions" in str(exc_info.value)
    
    # segmentsのループ内で RetentionMapError
    mock_segment = MagicMock()
    type(mock_segment).dopamine_hit = PropertyMock(side_effect=RetentionMapError("Direct map error in loop"))
    
    with pytest.raises(RetentionMapError) as exc_info:
        plugin._generate_suggestions("v_err", 10, [mock_segment])
    assert "Direct map error in loop" in str(exc_info.value)

def test_singleton_export():
    assert retention_map_plugin is not None
    assert isinstance(retention_map_plugin, RetentionMapPlugin)

def test_analyze_retention_risks_invalid_video_id_type():
    plugin = RetentionMapPlugin()
    # 文字列以外の型
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks(123, 100)
    assert "video_id must be a non-empty string" in str(exc_info.value)

def test_analyze_retention_risks_duration_limit():
    plugin = RetentionMapPlugin()
    # 24時間（86400秒）を超える場合
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", 90000)
    assert "duration_sec cannot exceed 86400 seconds" in str(exc_info.value)

def test_analyze_retention_risks_invalid_video_path_type():
    plugin = RetentionMapPlugin()
    # 文字列以外の video_path
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", 100, video_path=123)
    assert "video_path must be a non-empty string" in str(exc_info.value)

    # 空文字列
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", 100, video_path="")
    assert "video_path must be a non-empty string" in str(exc_info.value)

def test_analyze_retention_risks_non_existent_video_path():
    plugin = RetentionMapPlugin()
    # 存在しないパス
    with pytest.raises(RetentionMapError) as exc_info:
        plugin.analyze_retention_risks("v_01", 100, video_path="non_existent_file.mp4")
    assert "video_path does not exist" in str(exc_info.value)

def test_analyze_retention_risks_valid_video_path(tmp_path):
    plugin = RetentionMapPlugin()
    # 実在するパス
    dummy_file = tmp_path / "dummy_video.mp4"
    dummy_file.write_text("dummy content")
    
    report = plugin.analyze_retention_risks("v_01", 60, video_path=str(dummy_file))
    assert report is not None
    assert report.video_id == "v_01"

def test_analyze_retention_risks_pydantic_validation_error():
    plugin = RetentionMapPlugin()
    from pydantic import BaseModel, ValidationError
    
    class DummyModel(BaseModel):
        x: int
        
    val_err = None
    try:
        DummyModel(x="invalid_type")
    except ValidationError as e:
        val_err = e
        
    with patch("plugins.retention_map_plugin.RetentionSegment", side_effect=val_err):
        with pytest.raises(RetentionMapError) as exc_info:
            plugin.analyze_retention_risks("v_err", 10)
        assert "Failed to analyze retention risks" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, ValidationError)

