import pytest
import sys
import os
import argparse
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from pydantic import ValidationError

# テスト対象モジュールのディレクトリをパスに追加
backend_dir = Path(__file__).parent.parent.parent
if str(backend_dir) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(backend_dir))  # pragma: no cover

import auto_full_build
from services.soul_feedback import SoulFeedbackParams, SoulFeedbackProcessor

@pytest.fixture
def mock_pipeline_dependencies(tmp_path):
    """
    auto_full_build.py の実行に必要なファイル・ディレクトリ依存関係をモック、
    または一時ディレクトリに置き換えるフィクスチャ。
    """
    base_dir = tmp_path / "video-automation"
    raw_dir = base_dir / "vault-assets" / "raw_videos" / "本番RAW01  対談_山田"
    raw_dir.mkdir(parents=True, exist_ok=True)
    srt_dir = base_dir / "vault-assets" / "raw_videos" / "AI Studio アップロード用動画"
    srt_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = base_dir / "backend" / "temp" / "final_build"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # 必要なダミービデオファイルの作成
    (raw_dir / "シーン01_前編.mp4").write_text("dummy video")
    (raw_dir / "シーン02_ゲスト書道.mp4").write_text("dummy video")
    (raw_dir / "シーン03_後編01.mp4").write_text("dummy video")
    (raw_dir / "シーン04_後編02.mp4").write_text("dummy video")
    
    # ダミーSRTファイル
    srt_content = "1\n00:00:01,000 --> 00:00:05,000\nこんにちは\n\n"
    (srt_dir / "シーン01_前編_regenerated.srt").write_text(srt_content, encoding="utf-8")
    (srt_dir / "シーン03_後編01_regenerated.srt").write_text(srt_content, encoding="utf-8")
    (srt_dir / "シーン04_後編02_regenerated.srt").write_text(srt_content, encoding="utf-8")
    
    # パス変数をパッチ
    with patch("auto_full_build.BASE_DIR", base_dir), \
         patch("auto_full_build.RAW_DIR", raw_dir), \
         patch("auto_full_build.SRT_DIR", srt_dir), \
         patch("auto_full_build.TEMP_DIR", temp_dir):
        yield base_dir

@pytest.fixture
def mock_ffmpeg():
    with patch("subprocess.run") as mock_run:
        yield mock_run

@pytest.fixture
def mock_other_services():
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    mock_preview = MagicMock()
    mock_report = MagicMock()
    mock_scorer = MagicMock()
    mock_scorer.return_value = {"total_score": 95, "grade": "S"}
    
    with patch("auto_full_build.ProgressivePreview", return_value=mock_preview), \
         patch("auto_full_build.PreviewReportGenerator", return_value=mock_report), \
         patch("auto_full_build.score_against_youtuber_standard", mock_scorer), \
         patch("video_editor_engine.video_editor", mock_editor), \
         patch("auto_full_build.detect_silence", return_value=[]), \
         patch("auto_full_build.trim_silence_and_srt", return_value=None), \
         patch("auto_full_build.generate_metadata", return_value={"title": "test", "chapters": []}):
        yield

def test_e2e_soul_feedback_flow_success(mock_pipeline_dependencies, mock_ffmpeg, mock_other_services):
    """
    正常な定性演出指示がLLMによって解釈され、auto_full_build.pyの動画ビルド、
    FFmpegコマンド、およびテロップ画像の描画色に正しく反映されるE2Eフローを検証する。
    """
    # LLMのモックレスポンスを設定
    mock_llm_response = MagicMock()
    mock_llm_response.text = '{"tempo_multiplier": 1.5, "telop_color": "#FF0000", "subtitle_font_size": 30, "volume_multiplier": 1.2}'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_llm_response

    # PIL.ImageDraw.Draw.text をモックしてテロップカラーの設定を検証する
    with patch("google.genai.Client", return_value=mock_client), \
         patch("services.soul_feedback.get_gemini_client", return_value=mock_client), \
         patch("PIL.ImageDraw.ImageDraw.text") as mock_draw_text, \
         patch("sys.argv", ["auto_full_build.py", "--feedback", "テンポ早く、赤色のテロップ"]):
        
        auto_full_build.main()
        
        # 1. テロップ画像の文字色が #FF0000 になっていることを検証
        assert mock_draw_text.called
        for call_args in mock_draw_text.call_args_list:
            # draw.text((x, y), text, font=font, fill=telop_color)
            kwargs = call_args[1]
            assert kwargs.get("fill") == "#FF0000"

        # 2. FFmpegコマンドに還流パラメータが適用されていることを検証
        assert mock_ffmpeg.called
        
        scene_processed_count = 0
        final_concat_called = False
        
        for call_args in mock_ffmpeg.call_args_list:
            cmd = call_args[0][0]
            cmd_str = " ".join(cmd)
            
            if "scene01_processed.mp4" in cmd_str:
                scene_processed_count += 1
                # テンポ倍率 (setpts) と字幕サイズ (force_style) の検証
                assert "setpts=PTS/1.5" in cmd_str
                assert "force_style='FontSize=30'" in cmd_str
                # 音声フィルタ (atempo, volume) の検証
                assert "-af atempo=1.5,volume=1.2" in cmd_str
            
            if "concat" in cmd_str:
                final_concat_called = True

        assert scene_processed_count > 0
        assert final_concat_called

def test_e2e_soul_feedback_guardrails(mock_pipeline_dependencies, mock_ffmpeg, mock_other_services):
    """
    異常な演出指示（上限・下限を突破した値や不正な形式のカラーコード）が与えられた際、
    ガードレールによって安全な範囲にクリップされた上で、動画処理に反映されることを検証する。
    """
    # 範囲外の数値を返すモックLLMレスポンス
    mock_llm_response = MagicMock()
    mock_llm_response.text = '{"tempo_multiplier": 5.0, "telop_color": "blue", "subtitle_font_size": 200, "volume_multiplier": 3.0}'
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_llm_response

    with patch("google.genai.Client", return_value=mock_client), \
         patch("services.soul_feedback.get_gemini_client", return_value=mock_client), \
         patch("PIL.ImageDraw.ImageDraw.text") as mock_draw_text, \
         patch("sys.argv", ["auto_full_build.py", "--feedback", "超高速、青テロップ、特大フォント、大音量"]):
        
        auto_full_build.main()
        
        # 1. 無効なカラー名 'blue' はデフォルトの #FFFFFF にフォールバックされることを検証
        assert mock_draw_text.called
        for call_args in mock_draw_text.call_args_list:
            kwargs = call_args[1]
            assert kwargs.get("fill") == "#FFFFFF"

        # 2. パラメータがガードレールの上限値にクリップされて適用されていることを検証
        # tempo: 5.0 -> 2.0 (ge=0.5, le=2.0)
        # subtitle_font_size: 200 -> 100 (ge=10, le=100)
        # volume: 3.0 -> 2.0 (ge=0.0, le=2.0)
        assert mock_ffmpeg.called
        for call_args in mock_ffmpeg.call_args_list:
            cmd = call_args[0][0]
            cmd_str = " ".join(cmd)
            
            if "scene01_processed.mp4" in cmd_str:
                assert "setpts=PTS/2.0" in cmd_str
                assert "force_style='FontSize=100'" in cmd_str
                assert "-af atempo=2.0,volume=2.0" in cmd_str

def test_e2e_soul_feedback_fallback_on_llm_failure(mock_pipeline_dependencies, mock_ffmpeg, mock_other_services):
    """
    LLM APIのエラーやタイムアウト、JSON解析失敗の際に、システムが安全にデフォルト値
    （テンポ1.0倍、フォントサイズ24、音量1.0倍、カラー#FFFFFF）へフォールバックして実行されることを検証する。
    """
    # タイムアウトを引き起こすモッククライアント
    def mock_timeout_generate_content(*args, **kwargs):
        raise TimeoutError()

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = mock_timeout_generate_content

    with patch("google.genai.Client", return_value=mock_client), \
         patch("services.soul_feedback.get_gemini_client", return_value=mock_client), \
         patch("PIL.ImageDraw.ImageDraw.text") as mock_draw_text, \
         patch("sys.argv", ["auto_full_build.py", "--feedback", "エラーを発生させる指示"]):
        
        auto_full_build.main()
        
        # 1. カラーがデフォルトの #FFFFFF にフォールバックされることを検証
        assert mock_draw_text.called
        for call_args in mock_draw_text.call_args_list:
            kwargs = call_args[1]
            assert kwargs.get("fill") == "#FFFFFF"

        # 2. 各パラメータがデフォルト値になっており、動画と音声のテンポ・音量修飾子が追加されないこと、
        # 字幕サイズが 24 になっていることを検証
        assert mock_ffmpeg.called
        for call_args in mock_ffmpeg.call_args_list:
            cmd = call_args[0][0]
            cmd_str = " ".join(cmd)
            
            if "scene01_processed.mp4" in cmd_str:
                assert "setpts" not in cmd_str
                assert "force_style='FontSize=24'" in cmd_str
                assert "-af" not in cmd_str

def test_apply_guardrails_exceptions_and_types():
    """
    SoulFeedbackProcessor.apply_guardrails において、データ型が異なる場合の
    例外安全とデフォルト値フォールバック処理を徹底検証する。
    """
    processor = SoulFeedbackProcessor()
    
    # 1. 完全に型が壊れている場合 (辞書やリスト等)
    params = processor.apply_guardrails({
        "tempo_multiplier": [1.5],
        "telop_color": {"color": "#FF0000"},
        "subtitle_font_size": None,
        "volume_multiplier": "invalid_float"
    })
    
    assert params.tempo_multiplier == 1.0
    assert params.telop_color == "#FFFFFF"
    assert params.subtitle_font_size == 24
    assert params.volume_multiplier == 1.0

    # 2. PydanticのValidationErrorが発生した場合の安全フォールバック
    with patch("services.soul_feedback.SoulFeedbackParams") as mock_params_class:
        from pydantic import ValidationError
        validation_err = ValidationError.from_exception_data(
            title="SoulFeedbackParams", 
            line_errors=[]
        )
        original_class = SoulFeedbackParams
        def side_effect(*args, **kwargs):
            if args or kwargs:
                raise validation_err
            return original_class()
        mock_params_class.side_effect = side_effect
        params_fallback = processor.apply_guardrails({"tempo_multiplier": 1.0})
        # クラス呼び出し時の ValidationError がキャッチされ、デフォルトが返される
        assert params_fallback.tempo_multiplier == 1.0
        assert params_fallback.telop_color == "#FFFFFF"

@pytest.mark.asyncio
async def test_parse_qualitative_feedback_llm_json_decode_error():
    """
    JSONデコードエラー、および例外発生時にデフォルトへフォールバックされることを検証。
    """
    processor = SoulFeedbackProcessor()
    
    # 無効なJSON文字列を返すLLMモック
    with patch.object(processor, "_call_llm", return_value="invalid plain text response"):
        params = await processor.parse_qualitative_feedback("テンポ早く")
        assert params.tempo_multiplier == 1.0
        assert params.telop_color == "#FFFFFF"
        assert params.subtitle_font_size == 24
        assert params.volume_multiplier == 1.0
