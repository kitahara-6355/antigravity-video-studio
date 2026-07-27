import pytest
import os
import sys
import shutil
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open, AsyncMock

# backend パスを通す
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import backend.auto_full_build as auto_full_build
from services.soul_feedback import SoulFeedbackParams

def test_parse_srt(tmp_path):
    srt_content = """1
00:00:01,000 --> 00:00:04,500
こんにちは、山田です。

2
00:00:05,200 --> 00:00:08,000
伝統の筆づくりについて。

3
不正なブロック（行数不足）

4
00:00:09,000 --> 00:00:10,000
有効なブロックだがテキストが不正

5
00:00:11,000 00:00:12,000
矢印フォーマット不正のブロック
"""
    srt_file = tmp_path / "test.srt"
    srt_file.write_text(srt_content, encoding="utf-8-sig")

    segments = auto_full_build.parse_srt(srt_file)
    assert len(segments) == 3
    
    assert segments[0]["id"] == 1
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 4.5
    assert segments[0]["text"] == "こんにちは、山田です。"
    
    assert segments[1]["id"] == 2
    assert segments[1]["start"] == 5.2
    assert segments[1]["end"] == 8.0
    assert segments[1]["text"] == "伝統の筆づくりについて。"
    
    assert segments[2]["id"] == 4
    assert segments[2]["start"] == 9.0
    assert segments[2]["end"] == 10.0
    assert segments[2]["text"] == "有効なブロックだがテキストが不正"

def test_write_srt(tmp_path):
    segments = [
        {"id": 1, "start": 1.5, "end": 4.75, "text": "テストテキスト1"},
        {"id": 2, "start": 10.0, "end": 12.125, "text": "テストテキスト2"}
    ]
    srt_file = tmp_path / "output.srt"
    auto_full_build.write_srt(segments, srt_file)
    
    content = srt_file.read_text(encoding="utf-8")
    expected = "1\n00:00:01,500 --> 00:00:04,750\nテストテキスト1\n\n2\n00:00:10,000 --> 00:00:12,125\nテストテキスト2\n\n"
    assert content.replace("\r\n", "\n") == expected

@patch("backend.auto_full_build.template_config")
@patch("backend.auto_full_build.format_segments")
@patch("backend.auto_full_build.parse_srt")
@patch("backend.auto_full_build.write_srt")
def test_get_formatted_srt(mock_write_srt, mock_parse_srt, mock_format_segments, mock_template_config, tmp_path):
    mock_template_config.get_max_chars_per_line.return_value = 20
    mock_parse_segs = [{"id": 1, "start": 0.0, "end": 1.0, "text": "test"}]
    mock_parse_srt.return_value = mock_parse_segs
    mock_format_segs = [{"id": 1, "start": 0.0, "end": 1.0, "text": "formatted"}]
    mock_format_segments.return_value = mock_format_segs
    
    original_temp_dir = auto_full_build.TEMP_DIR
    auto_full_build.TEMP_DIR = Path(tmp_path)
    
    try:
        res_path = auto_full_build.get_formatted_srt("scene01", "dummy_srt_path")
        
        mock_template_config.get_max_chars_per_line.assert_called_once()
        mock_parse_srt.assert_called_once_with("dummy_srt_path")
        mock_format_segments.assert_called_once_with(mock_parse_segs, max_chars=20)
        mock_write_srt.assert_called_once_with(mock_format_segs, res_path)
        assert res_path == Path(tmp_path) / "scene01_formatted.srt"
    finally:
        auto_full_build.TEMP_DIR = original_temp_dir

def test_cleanup_temp_files(tmp_path):
    original_temp_dir = auto_full_build.TEMP_DIR
    auto_full_build.TEMP_DIR = Path(tmp_path)
    try:
        file1 = tmp_path / "dummy1.png"
        file1.write_text("dummy")
        dir1 = tmp_path / "subdir"
        dir1.mkdir()
        
        auto_full_build.cleanup_temp_files()
        assert not file1.exists()
        assert dir1.exists()
        
        with patch.object(Path, "glob", side_effect=Exception("glob error")):
            auto_full_build.cleanup_temp_files()
            
    finally:
        auto_full_build.TEMP_DIR = original_temp_dir

@patch("backend.auto_full_build.ImageFont.truetype")
@patch("backend.auto_full_build.Image.new")
def test_generate_telops(mock_image_new, mock_truetype, tmp_path):
    original_temp_dir = auto_full_build.TEMP_DIR
    auto_full_build.TEMP_DIR = Path(tmp_path)
    try:
        mock_font = MagicMock()
        mock_truetype.return_value = mock_font
        mock_img = MagicMock()
        mock_image_new.return_value = mock_img
        
        auto_full_build.generate_telops(telop_color="#123456")
        
        mock_truetype.assert_called_once_with(auto_full_build.FONT_PATH, 18)
        assert mock_image_new.call_count == len(auto_full_build.THEMES)
        assert mock_img.save.call_count == len(auto_full_build.THEMES)
    finally:
        auto_full_build.TEMP_DIR = original_temp_dir

@patch("backend.auto_full_build.detect_silence")
@patch("backend.auto_full_build.trim_silence_and_srt")
@patch("backend.auto_full_build.get_formatted_srt")
@patch("backend.auto_full_build.subprocess.run")
def test_process_scene(mock_run, mock_get_formatted_srt, mock_trim, mock_detect, tmp_path):
    original_temp_dir = auto_full_build.TEMP_DIR
    original_base_dir = auto_full_build.BASE_DIR
    
    auto_full_build.BASE_DIR = Path(tmp_path)
    temp_dir = Path(tmp_path) / "backend" / "temp" / "final_build"
    temp_dir.mkdir(parents=True, exist_ok=True)
    auto_full_build.TEMP_DIR = temp_dir
    
    input_video = temp_dir / "input.mp4"
    input_video.write_text("video content")
    srt_file = temp_dir / "input.srt"
    srt_file.write_text("srt content")
    
    try:
        # 1. キャッシュが存在する場合の分岐
        cached_output = temp_dir / "scene01_processed.mp4"
        cached_output.write_bytes(b"A" * 1000001)
        
        res = auto_full_build.process_scene("scene01", input_video, "100:100:0:0")
        assert res == cached_output
        mock_run.assert_not_called()
        
        cached_output.unlink()
        
        # 2. 無音検出があり、無音区間が存在してトリミングされる場合
        mock_detect.return_value = [{"start": 0.0, "end": 2.0, "duration": 2.0}]
        mock_get_formatted_srt.return_value = temp_dir / "formatted.srt"
        
        def trim_side_effect(*args, **kwargs):
            Path(kwargs["output_video_path"]).write_text("trimmed video")
            Path(kwargs["output_srt_path"]).write_text("trimmed srt")
        mock_trim.side_effect = trim_side_effect
        
        (temp_dir / "formatted.srt").write_text("formatted srt")
        (temp_dir / "brand_telop_0.png").write_text("telop 0")
        (temp_dir / "brand_telop_1.png").write_text("telop 1")
        
        feedback_params = SoulFeedbackParams(tempo_multiplier=1.2, volume_multiplier=0.8, subtitle_font_size=20)
        
        res = auto_full_build.process_scene(
            scene_name="scene01",
            input_file=input_video,
            crop="100:100:0:0",
            srt_file=srt_file,
            telop_indices=[(0, 0.0, 5.0), (1, 5.0, 10.0)],
            feedback_params=feedback_params
        )
        
        assert res == cached_output
        mock_detect.assert_called_once()
        mock_trim.assert_called_once()
        mock_get_formatted_srt.assert_called_once()
        mock_run.assert_called_once()
        
        # 3. 無音検出したが、削るべき無音区間がない場合 (duration <= 1.5)
        mock_run.reset_mock()
        mock_detect.reset_mock()
        mock_trim.reset_mock()
        mock_get_formatted_srt.reset_mock()
        
        mock_detect.return_value = [{"start": 0.0, "end": 1.0, "duration": 1.0}]
        
        res = auto_full_build.process_scene(
            scene_name="scene01",
            input_file=input_video,
            crop="100:100:0:0",
            srt_file=srt_file,
            telop_indices=None,
            feedback_params=None
        )
        mock_detect.assert_called_once()
        mock_trim.assert_not_called()
        mock_run.assert_called_once()
        
        # 4. 無音検出中に例外が発生した場合
        mock_run.reset_mock()
        mock_detect.reset_mock()
        mock_trim.reset_mock()
        mock_get_formatted_srt.reset_mock()
        mock_detect.side_effect = ValueError("test value error")
        
        res = auto_full_build.process_scene(
            scene_name="scene01",
            input_file=input_video,
            crop="100:100:0:0",
            srt_file=srt_file,
            telop_indices=None,
            feedback_params=None
        )
        mock_detect.assert_called_once()
        mock_run.assert_called_once()
        
        # 5. srt整形中に例外が発生した場合
        mock_run.reset_mock()
        mock_detect.reset_mock()
        mock_trim.reset_mock()
        mock_get_formatted_srt.reset_mock()
        mock_detect.side_effect = None
        mock_detect.return_value = []
        mock_get_formatted_srt.side_effect = Exception("test format error")
        
        res = auto_full_build.process_scene(
            scene_name="scene01",
            input_file=input_video,
            crop="100:100:0:0",
            srt_file=srt_file,
            telop_indices=None,
            feedback_params=None
        )
        mock_get_formatted_srt.assert_called_once()
        mock_run.assert_called_once()

    finally:
        auto_full_build.TEMP_DIR = original_temp_dir
        auto_full_build.BASE_DIR = original_base_dir

@patch("backend.auto_full_build.detect_silence")
@patch("backend.auto_full_build.subprocess.run")
def test_process_scene_no_srt(mock_run, mock_detect, tmp_path):
    original_temp_dir = auto_full_build.TEMP_DIR
    original_base_dir = auto_full_build.BASE_DIR
    
    auto_full_build.BASE_DIR = Path(tmp_path)
    temp_dir = Path(tmp_path) / "backend" / "temp" / "final_build"
    temp_dir.mkdir(parents=True, exist_ok=True)
    auto_full_build.TEMP_DIR = temp_dir
    
    input_video = temp_dir / "input.mp4"
    input_video.write_text("video content")
    
    try:
        res = auto_full_build.process_scene(
            scene_name="scene02",
            input_file=input_video,
            crop="1920:960:0:60",
            srt_file=None,
            telop_indices=None,
            feedback_params=None
        )
        mock_detect.assert_not_called()
        mock_run.assert_called_once()
        assert res == temp_dir / "scene02_processed.mp4"
    finally:
        auto_full_build.TEMP_DIR = original_temp_dir
        auto_full_build.BASE_DIR = original_base_dir

@patch("backend.auto_full_build.ProgressivePreview")
@patch("backend.auto_full_build.PreviewReportGenerator")
@patch("backend.auto_full_build.generate_telops")
@patch("backend.auto_full_build.process_scene")
@patch("backend.auto_full_build.parse_srt")
@patch("video_editor_engine.video_editor")
@patch("backend.auto_full_build.subprocess.run")
@patch("backend.auto_full_build.generate_metadata")
@patch("backend.auto_full_build.score_against_youtuber_standard")
@patch("backend.auto_full_build.cleanup_temp_files")
@patch("backend.auto_full_build.SoulFeedbackProcessor")
def test_main(
    mock_feedback_processor, mock_cleanup, mock_score, mock_metadata, mock_sub_run, 
    mock_video_editor, mock_parse_srt, mock_process_scene, mock_generate_telops, 
    mock_preview_gen, mock_prog_preview, tmp_path
):
    original_base = auto_full_build.BASE_DIR
    original_raw = auto_full_build.RAW_DIR
    original_srt = auto_full_build.SRT_DIR
    original_temp = auto_full_build.TEMP_DIR
    
    auto_full_build.BASE_DIR = Path(tmp_path)
    auto_full_build.RAW_DIR = Path(tmp_path) / "raw_videos"
    auto_full_build.SRT_DIR = Path(tmp_path) / "srt_videos"
    auto_full_build.TEMP_DIR = Path(tmp_path) / "temp"
    
    auto_full_build.RAW_DIR.mkdir(parents=True, exist_ok=True)
    auto_full_build.SRT_DIR.mkdir(parents=True, exist_ok=True)
    auto_full_build.TEMP_DIR.mkdir(parents=True, exist_ok=True)
    
    # スコア結果の保存先ディレクトリを作成
    (auto_full_build.BASE_DIR / "backend" / "graded_previews").mkdir(parents=True, exist_ok=True)
    
    (auto_full_build.RAW_DIR / "シーン01_前編.mp4").write_text("dummy")
    (auto_full_build.RAW_DIR / "シーン02_ゲスト書道.mp4").write_text("dummy")
    (auto_full_build.RAW_DIR / "シーン03_後編01.mp4").write_text("dummy")
    (auto_full_build.RAW_DIR / "シーン04_後編02.mp4").write_text("dummy")
    
    (auto_full_build.SRT_DIR / "シーン01_前編_regenerated.srt").write_text("dummy")
    (auto_full_build.SRT_DIR / "シーン03_後編01_regenerated.srt").write_text("dummy")
    (auto_full_build.SRT_DIR / "シーン04_後編02_regenerated.srt").write_text("dummy")
    
    # 累積処理用の一時SRTファイルを作成 (scene01〜scene04)
    for scene_name in ["scene01", "scene02", "scene03", "scene04"]:
        (auto_full_build.TEMP_DIR / f"{scene_name}_formatted.srt").write_text("1\n00:00:01,000 --> 00:00:04,500\ntest\n\n")
    
    try:
        mock_preview_inst = MagicMock()
        mock_prog_preview.return_value = mock_preview_inst
        
        mock_process_scene.side_effect = lambda name, *args, **kwargs: auto_full_build.TEMP_DIR / f"{name}_processed.mp4"
        mock_video_editor.ffmpeg.get_duration.return_value = 10.0
        mock_parse_srt.return_value = [{"id": 1, "start": 0.0, "end": 1.0, "text": "test"}]
        mock_metadata.return_value = {"title": "Test Title", "chapters": []}
        mock_score.return_value = {"total_score": 85, "grade": "A"}
        
        for scene_name in ["scene01", "scene02", "scene03", "scene04"]:
            (auto_full_build.TEMP_DIR / f"{scene_name}_processed.mp4").write_text("dummy video")
            
        with patch("sys.argv", ["auto_full_build.py"]):
            auto_full_build.main()
            
        mock_generate_telops.assert_called_once()
        assert mock_process_scene.call_count == 4
        
        # モックのコールを確認 (ffmpeg encoders の初期化確認があるので、最後のコールをアサート)
        mock_sub_run.assert_called()
        last_call_args = mock_sub_run.call_args_list[-1][0][0]
        assert "concat" in last_call_args
        
        mock_metadata.assert_called_once()
        mock_score.assert_called_once()
        mock_cleanup.assert_called_once()
        
        # 最終動画キャッシュの分岐
        final_output = auto_full_build.BASE_DIR / "soul_narrative_full_v1.mp4"
        final_output.write_bytes(b"A" * 10000001)
        
        mock_sub_run.reset_mock()
        with patch("sys.argv", ["auto_full_build.py"]):
            auto_full_build.main()
        mock_sub_run.assert_not_called()
        
        # --feedback 引数ありのテスト & 例外発生ルートのテスト
        mock_processor_inst = MagicMock()
        mock_feedback_processor.return_value = mock_processor_inst
        
        mock_processor_inst.parse_qualitative_feedback = AsyncMock(
            return_value=SoulFeedbackParams(telop_color="#112233")
        )
        
        # 例外を発生させて except 句のコードパスをカバーする
        mock_preview_inst.snapshot_step.side_effect = Exception("snapshot failed")
        mock_preview_gen.return_value.generate_from_session_dir.side_effect = Exception("gen failed")
        mock_metadata.side_effect = Exception("metadata failed")
        mock_score.side_effect = Exception("score failed")
        
        final_output.unlink()
        
        with patch("sys.argv", ["auto_full_build.py", "--feedback", "明るい雰囲気で"]):
            auto_full_build.main()
        
        mock_processor_inst.parse_qualitative_feedback.assert_called_once_with("明るい雰囲気で")
        
    finally:
        auto_full_build.BASE_DIR = original_base
        auto_full_build.RAW_DIR = original_raw
        auto_full_build.SRT_DIR = original_srt
        auto_full_build.TEMP_DIR = original_temp

def test_run_as_main():
    file_path = auto_full_build.__file__
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    target_code = ""
    start_line = 0
    for i, line in enumerate(lines):
        if 'if __name__ == "__main__":' in line or "if __name__ == '__main__':" in line:
            target_code = "".join(lines[i:])
            start_line = i + 1
            break
            
    assert target_code != ""
    
    code_obj = compile(
        "\n" * (start_line - 1) + target_code,
        file_path,
        "exec"
    )
    
    mock_main = MagicMock()
    global_ns = {
        "__name__": "__main__",
        "main": mock_main
    }
    
    exec(code_obj, global_ns)
    mock_main.assert_called_once()

def test_sys_path_insertion():
    import importlib
    backend_dir_str = str(Path(auto_full_build.__file__).parent)
    original_path = sys.path.copy()
    try:
        while backend_dir_str in sys.path:
            sys.path.remove(backend_dir_str)
        importlib.reload(auto_full_build)
        assert backend_dir_str in sys.path
        assert sys.path[0] == backend_dir_str
    finally:
        sys.path = original_path

def test_parse_srt_exceptions(tmp_path):
    # 1. 存在しないファイル (40-42)
    res = auto_full_build.parse_srt(tmp_path / "non_existent.srt")
    assert res == []

    # 2. 不正な時間フォーマット (52-54)
    srt_content = """1
00:00:01,000 --> 00:00:04,500
こんにちは
"""
    srt_file = tmp_path / "invalid_time.srt"
    srt_file.write_text(srt_content, encoding="utf-8-sig")
    
    with patch("backend.auto_full_build.re.match") as mock_match:
        mock_m = MagicMock()
        mock_m.group.side_effect = lambda idx: "abc" if idx in (1, 2) else None
        mock_match.return_value = mock_m
        
        segments = auto_full_build.parse_srt(srt_file)
        assert len(segments) == 1
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 0.0

def test_write_srt_exceptions(tmp_path):
    # 1. 不正な秒数によるフォーマット生成エラー (81-83)
    segments = [{"id": 1, "start": "invalid_seconds", "end": 4.5, "text": "テスト"}]
    srt_file = tmp_path / "output_invalid.srt"
    auto_full_build.write_srt(segments, srt_file)
    assert srt_file.exists()
    content = srt_file.read_text(encoding="utf-8")
    assert "00:00:00,000" in content

    # 2. ディレクトリパス指定などによる書き込みエラー (91-92)
    invalid_path = tmp_path / "invalid_dir"
    invalid_path.mkdir()
    segments_ok = [{"id": 1, "start": 1.0, "end": 2.0, "text": "テスト"}]
    auto_full_build.write_srt(segments_ok, invalid_path)

@patch("backend.auto_full_build.template_config")
def test_get_formatted_srt_exceptions(mock_template_config):
    # 109-111 をカバー
    mock_template_config.get_max_chars_per_line.side_effect = AttributeError("test attribute error")
    res = auto_full_build.get_formatted_srt("scene01", "original.srt")
    assert res == Path("original.srt")

@patch("backend.auto_full_build.ImageFont.truetype")
@patch("backend.auto_full_build.Image.new")
def test_generate_telops_exceptions(mock_image_new, mock_truetype, tmp_path):
    original_temp_dir = auto_full_build.TEMP_DIR
    auto_full_build.TEMP_DIR = Path(tmp_path)
    try:
        # フォント読み込みエラーでデフォルトフォントにフォールバック (141-143)
        def truetype_side_effect(*args, **kwargs):
            if args and args[0] == auto_full_build.FONT_PATH:
                raise OSError("font not found")
            return MagicMock()
        mock_truetype.side_effect = truetype_side_effect
        
        mock_img = MagicMock()
        mock_image_new.return_value = mock_img
        auto_full_build.generate_telops()
        mock_truetype.assert_called()
        
        # 保存エラー (155-156)
        mock_truetype.side_effect = None
        mock_truetype.return_value = MagicMock()
        mock_img.save.side_effect = OSError("save failed")
        auto_full_build.generate_telops()
    finally:
        auto_full_build.TEMP_DIR = original_temp_dir

def test_process_scene_exceptions(tmp_path):
    # 1. 入力ファイルが存在しない場合の FileNotFoundError (167-168)
    with pytest.raises(FileNotFoundError):
        auto_full_build.process_scene("scene01", tmp_path / "non_existent.mp4", "100:100:0:0")

    # 2. ffmpegの実行失敗時の CalledProcessError (277-279)
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    with patch("backend.auto_full_build.subprocess.run") as mock_run:
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        with pytest.raises(subprocess.CalledProcessError):
            auto_full_build.process_scene("scene01", input_video, "100:100:0:0")


def test_auto_full_build_edge_cases():
    # Verify that parse_srt handles None or invalid path type by raising TypeError/AttributeError
    with pytest.raises(TypeError):
        auto_full_build.parse_srt(None)

