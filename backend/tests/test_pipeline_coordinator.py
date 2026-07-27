import os
import sys
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# パスの追加
backend_path = Path(__file__).parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from video_pipeline.pipeline_coordinator import PipelineCoordinator, PipelineResult, STAGE_ORDER


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ダミー結果クラスの定義
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DummyIngestResult:
    def __init__(self, normalized_path, format_info, duration_seconds):
        self.normalized_path = normalized_path
        self.format_info = format_info
        self.duration_seconds = duration_seconds


class DummyAudioExtractResult:
    def __init__(self, audio_path):
        self.audio_path = audio_path


class DummySegment:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class DummyTranscriptionResult:
    def __init__(self, segments):
        self.segments = segments


class DummySubtitleGenResult:
    def __init__(self, output_path, entry_count):
        self.output_path = output_path
        self.entry_count = entry_count


class DummyRenderResult:
    def __init__(self, success, image_path):
        self.success = success
        self.image_path = image_path


class DummyComposeResult:
    def __init__(self, output_path):
        self.output_path = output_path


class DummyQualityGateResult:
    def __init__(self, overall_score, passed):
        self.overall_score = overall_score
        self.passed = passed


class DummyThumbnailResult:
    def __init__(self, image_path):
        self.image_path = image_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ヘルパー関数とフィクスチャ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def make_mock_method(stage_name, fail_config, success_return):
    """リトライ検証用に、指定回数失敗した後に成功するモックメソッドを作成する。"""
    if not fail_config:
        return MagicMock(return_value=success_return)
    
    fail_count = fail_config.get("fail_count", 0)
    error_type = fail_config.get("error_type", "Exception")
    
    if error_type == "FileNotFoundError":
        exc = FileNotFoundError(f"Dummy file not found for {stage_name}")
    else:
        exc = Exception(f"Dummy error for {stage_name}")
        
    calls = []
    for _ in range(fail_count):
        calls.append(exc)
    
    class SideEffect:
        def __init__(self, exceptions, success_val):
            self.exceptions = exceptions
            self.success_val = success_val
            self.index = 0
            
        def __call__(self, *args, **kwargs):
            if self.index < len(self.exceptions):
                self.index += 1
                raise self.exceptions[self.index - 1]
            return self.success_val
            
    return MagicMock(side_effect=SideEffect(calls, success_return))


@pytest.fixture
def mock_pipeline_services():
    """全ステージのクラスをモック化するフィクスチャ。"""
    with patch("backend.video_pipeline.ingest_service.IngestService") as mock_ingest_cls, \
         patch("backend.plugins.smart_cut_plugin.SmartCutPlugin") as mock_smartcut_cls, \
         patch("backend.video_pipeline.audio_extractor.AudioExtractor") as mock_extract_cls, \
         patch("backend.video_pipeline.transcription_service.TranscriptionService") as mock_transcribe_cls, \
         patch("backend.video_pipeline.subtitle_generator.SubtitleGenerator") as mock_subtitle_cls, \
         patch("backend.video_pipeline.soul_feedback_engine.SoulFeedbackEngine") as mock_soul_cls, \
         patch("backend.video_pipeline.telop_renderer.TelopRenderer") as mock_telop_cls, \
         patch("backend.video_pipeline.video_composer.VideoComposer") as mock_compose_cls, \
         patch("backend.video_pipeline.quality_gate.QualityGate") as mock_quality_cls, \
         patch("backend.video_pipeline.thumbnail_generator.ThumbnailGenerator") as mock_thumbnail_cls:
         
         yield {
             "ingest": mock_ingest_cls,
             "smart_cut": mock_smartcut_cls,
             "audio_extract": mock_extract_cls,
             "transcribe": mock_transcribe_cls,
             "subtitle_gen": mock_subtitle_cls,
             "soul_feedback": mock_soul_cls,
             "telop_render": mock_telop_cls,
             "compose": mock_compose_cls,
             "quality_gate": mock_quality_cls,
             "thumbnail": mock_thumbnail_cls,
         }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# パラメータ化テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest.mark.parametrize(
    "test_id, fail_stages, expected_success, expected_completed_stages, quality_score_value",
    [
        # 1. 正常系1: 全てストレートに成功
        (
            "normal_success",
            {},
            True,
            STAGE_ORDER,
            0.85,
        ),
        # 2. 正常系2: クオリティスコアが低い場合（品質チェックは通るがスコア低）
        (
            "normal_success_low_score",
            {},
            True,
            STAGE_ORDER,
            0.4,
        ),
        # 3. 境界値1: 1回失敗して2回目で成功 (リトライ1回)
        (
            "retry_once_success",
            {"transcribe": {"fail_count": 1, "error_type": "Exception"}},
            True,
            STAGE_ORDER,
            0.85,
        ),
        # 4. 境界値2: 2回失敗して3回目で成功 (リトライ2回 - リトライ上限ギリギリ)
        (
            "retry_twice_success",
            {"compose": {"fail_count": 2, "error_type": "Exception"}},
            True,
            STAGE_ORDER,
            0.85,
        ),
        # 5. 異常系1: transcribeが3回失敗して停止 (リトライ上限オーバーで失敗)
        (
            "retry_failed_stop_transcribe",
            {"transcribe": {"fail_count": 3, "error_type": "Exception"}},
            False,
            ["ingest", "smart_cut", "audio_extract"],
            0.0,
        ),
        # 6. 異常系2: ingestが即座に3回失敗して停止 (開始直後の失敗)
        (
            "ingest_failed_stop",
            {"ingest": {"fail_count": 3, "error_type": "Exception"}},
            False,
            [],
            0.0,
        ),
        # 7. 境界値3: FileNotFoundErrorによる失敗 (別の例外タイプ)
        (
            "filenotfound_retry_and_fail",
            {"audio_extract": {"fail_count": 3, "error_type": "FileNotFoundError"}},
            False,
            ["ingest", "smart_cut"],
            0.0,
        ),
    ]
)
def test_pipeline_coordinator_run(
    tmp_path,
    mock_pipeline_services,
    test_id,
    fail_stages,
    expected_success,
    expected_completed_stages,
    quality_score_value,
):
    # 各サービスのモックが返すダミー値を定義
    dummy_ingest = DummyIngestResult("norm.mp4", {"codec": "h264"}, 10.0)
    dummy_extract = DummyAudioExtractResult("audio.wav")
    dummy_transcribe = DummyTranscriptionResult([DummySegment(0.0, 2.0, "Hello")])
    dummy_subtitle = DummySubtitleGenResult("sub.srt", 1)
    dummy_render = [DummyRenderResult(True, "telop1.png")]
    dummy_compose = DummyComposeResult("composed.mp4")
    dummy_quality = DummyQualityGateResult(quality_score_value, quality_score_value >= 0.7)
    dummy_thumbnail = DummyThumbnailResult("thumb.png")
    
    # インスタンスをモック
    mock_ingest_inst = mock_pipeline_services["ingest"].return_value
    mock_smartcut_inst = mock_pipeline_services["smart_cut"].return_value
    mock_extract_inst = mock_pipeline_services["audio_extract"].return_value
    mock_transcribe_inst = mock_pipeline_services["transcribe"].return_value
    mock_subtitle_inst = mock_pipeline_services["subtitle_gen"].return_value
    mock_soul_inst = mock_pipeline_services["soul_feedback"].return_value
    mock_telop_inst = mock_pipeline_services["telop_render"].return_value
    mock_compose_inst = mock_pipeline_services["compose"].return_value
    mock_quality_inst = mock_pipeline_services["quality_gate"].return_value
    mock_thumbnail_inst = mock_pipeline_services["thumbnail"].return_value
    
    # side_effect/return_valueの設定
    mock_ingest_inst.ingest = make_mock_method("ingest", fail_stages.get("ingest"), dummy_ingest)
    mock_smartcut_inst.run_smart_cut = make_mock_method("smart_cut", fail_stages.get("smart_cut"), True)
    mock_extract_inst.extract = make_mock_method("audio_extract", fail_stages.get("audio_extract"), dummy_extract)
    mock_transcribe_inst.transcribe = make_mock_method("transcribe", fail_stages.get("transcribe"), dummy_transcribe)
    mock_subtitle_inst.generate_srt = make_mock_method("subtitle_gen", fail_stages.get("subtitle_gen"), dummy_subtitle)
    mock_telop_inst.render_batch = make_mock_method("telop_render", fail_stages.get("telop_render"), dummy_render)
    mock_compose_inst.compose = make_mock_method("compose", fail_stages.get("compose"), dummy_compose)
    mock_quality_inst.evaluate = make_mock_method("quality_gate", fail_stages.get("quality_gate"), dummy_quality)
    mock_thumbnail_inst.generate = make_mock_method("thumbnail", fail_stages.get("thumbnail"), dummy_thumbnail)
    
    # 実行
    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    result = coordinator.run_pipeline("input.mp4")
    
    # 結果の検証
    assert result.success == expected_success
    assert result.stages_completed == expected_completed_stages
    
    if expected_success:
        assert os.path.basename(result.output_path) == "composed_output.mp4"
        assert result.quality_score == quality_score_value
        
        # 中間成果物用ディレクトリの検証 (work_dir/{job_id}/)
        job_dir = Path(tmp_path) / result.job_id
        assert job_dir.exists()
        assert job_dir.is_dir()
        
    # get_statusの検証
    status = coordinator.get_status(result.job_id)
    assert status["status"] == ("completed" if expected_success else "failed")
    assert status["stages_completed"] == expected_completed_stages
    
    # event_log.jsonl の検証
    event_log_path = tmp_path / "event_log.jsonl"
    assert event_log_path.exists()
    
    events = []
    with open(event_log_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
                
    # 全てのイベントログに job_id が含まれていることを検証
    for ev in events:
        assert ev["job_id"] == result.job_id
        
    # pipeline_start と pipeline_end が含まれていることを検証
    assert any(ev["event_type"] == "pipeline_start" for ev in events)
    assert any(ev["event_type"] == "pipeline_end" for ev in events)
    
    # 各ステージの開始/完了のログが記録されていることを検証
    for stage in expected_completed_stages:
        assert any(ev["event_type"] == "stage_start" and ev.get("stage") == stage for ev in events)
        assert any(ev["event_type"] == "stage_complete" and ev.get("stage") == stage for ev in events)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 個別検証テスト
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_pipeline_coordinator_get_status_unknown(tmp_path):
    """未知のジョブIDが指定された場合の get_status の動作検証。"""
    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    status = coordinator.get_status("unknown_job_123")
    assert status["status"] == "unknown"
    assert "error" in status


def test_pipeline_coordinator_invalid_stage(tmp_path):
    """未知のステージ名が実行された場合に ValueError が送出されることの検証。"""
    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    with pytest.raises(ValueError, match="未知のステージ名"):
        coordinator._execute_stage("invalid_stage_name", {})


@patch("backend.plugins.smart_cut_plugin.SmartCutPlugin.run_smart_cut")
def test_pipeline_coordinator_smart_cut_fallback(mock_run_smart_cut, tmp_path, mock_pipeline_services):
    """smart_cut ステージが例外を投げた場合でも、フォールバックして処理が継続されることの検証。"""
    mock_run_smart_cut.side_effect = Exception("Auto-Editor binary missing")

    dummy_ingest = DummyIngestResult("norm.mp4", {"codec": "h264"}, 10.0)
    dummy_extract = DummyAudioExtractResult("audio.wav")
    dummy_transcribe = DummyTranscriptionResult([DummySegment(0.0, 2.0, "Hello")])
    dummy_subtitle = DummySubtitleGenResult("sub.srt", 1)
    dummy_render = [DummyRenderResult(True, "telop1.png")]
    dummy_compose = DummyComposeResult("composed.mp4")
    dummy_quality = DummyQualityGateResult(0.9, True)
    dummy_thumbnail = DummyThumbnailResult("thumb.png")

    mock_ingest_inst = mock_pipeline_services["ingest"].return_value
    mock_extract_inst = mock_pipeline_services["audio_extract"].return_value
    mock_transcribe_inst = mock_pipeline_services["transcribe"].return_value
    mock_subtitle_inst = mock_pipeline_services["subtitle_gen"].return_value
    mock_telop_inst = mock_pipeline_services["telop_render"].return_value
    mock_compose_inst = mock_pipeline_services["compose"].return_value
    mock_quality_inst = mock_pipeline_services["quality_gate"].return_value
    mock_thumbnail_inst = mock_pipeline_services["thumbnail"].return_value

    mock_ingest_inst.ingest.return_value = dummy_ingest
    mock_extract_inst.extract.return_value = dummy_extract
    mock_transcribe_inst.transcribe.return_value = dummy_transcribe
    mock_subtitle_inst.generate_srt.return_value = dummy_subtitle
    mock_telop_inst.render_batch.return_value = dummy_render
    mock_compose_inst.compose.return_value = dummy_compose
    mock_quality_inst.evaluate.return_value = dummy_quality
    mock_thumbnail_inst.generate.return_value = dummy_thumbnail

    coordinator = PipelineCoordinator(work_dir=str(tmp_path))
    result = coordinator.run_pipeline("input.mp4")

    assert result.success is True
    assert "smart_cut" in result.stages_completed
    assert "compose" in result.stages_completed
