"""
M2.6 Batch 2: エンジン群テスト

対象: video_processor, video_editor_engine, template_recommender, tutorial_system
"""

import pytest
import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from video_processor import (
    VideoProcessor, ProcessingPhase, MoodSettings, MOOD_SETTINGS,
)

# video_editor_engine: シングルトン初期化時のFFmpeg検索を回避
with patch("shutil.which", return_value=None):
    from video_editor_engine import (
        FFmpegEditor, VideoEditorEngine, VideoClip, TransitionType,
    )

from template_recommender import TemplateRecommender
from tutorial_system import Tutorial, TutorialStep


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def vp(tmp_path):
    return VideoProcessor(output_dir=str(tmp_path))


@pytest.fixture
def ffmpeg_editor(tmp_path):
    with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
        with patch("video_editor_engine.subprocess.run") as m:
            m.return_value = MagicMock(stdout="h264_nvenc", returncode=0)
            editor = FFmpegEditor(output_dir=tmp_path)
    return editor


@pytest.fixture(autouse=True)
def mock_path_exists(request):
    """TestFFmpegEditorの実行時のみPath.existsをTrueにする"""
    if request.cls and request.cls.__name__ == "TestFFmpegEditor":
        with patch("video_editor_engine.Path.exists", return_value=True):
            yield
    else:
        yield


# ============================================================
# video_processor.py テスト
# ============================================================

class TestVideoProcessorProcessing:

    def test_process_video_task_not_found(self, vp):
        assert vp.process_video("nonexistent") is False

    @patch("video_processor.subprocess.Popen")
    def test_run_ffmpeg_success(self, mock_popen, vp):
        proc = MagicMock()
        # poll() は即座に0を返す → parse_progressスレッドが即終了
        proc.poll.return_value = 0
        proc.stderr.readline.return_value = ""
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc
        task = vp.create_task("t1", ["/v.mp4"], "elegant")
        assert vp._run_ffmpeg(["ffmpeg", "-y"], "test", timeout=10, task=task) is True

    @patch("video_processor.subprocess.Popen")
    def test_run_ffmpeg_failure(self, mock_popen, vp):
        proc = MagicMock()
        proc.poll.return_value = 1
        proc.stderr.readline.return_value = ""
        proc.stderr.read.return_value = "error"
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc
        assert vp._run_ffmpeg(["ffmpeg"], "test", timeout=10) is False

    @patch("video_processor.subprocess.Popen")
    def test_run_ffmpeg_timeout(self, mock_popen, vp):
        import subprocess as sp
        proc = MagicMock()
        proc.wait.side_effect = sp.TimeoutExpired(cmd="ffmpeg", timeout=1)
        proc.kill.return_value = None
        proc.poll.return_value = -9  # killed
        proc.stderr.readline.return_value = ""
        mock_popen.return_value = proc
        assert vp._run_ffmpeg(["ffmpeg"], "test", timeout=1) is False

    @patch("video_processor.subprocess.Popen")
    def test_run_ffmpeg_exception(self, mock_popen, vp):
        mock_popen.side_effect = OSError("no ffmpeg")
        assert vp._run_ffmpeg(["ffmpeg"], "test") is False

    def test_merge_scenes_no_valid(self, vp, tmp_path):
        out = str(tmp_path / "merged.mp4")
        vp._merge_scenes(["/nonexistent1.mp4", "/nonexistent2.mp4"], out)
        assert not Path(out).exists()

    def test_merge_scenes_single(self, vp, tmp_path):
        src = tmp_path / "scene1.mp4"
        src.write_bytes(b"fake video data")
        out = str(tmp_path / "merged.mp4")
        vp._merge_scenes([str(src)], out)
        assert Path(out).exists()

    @patch("video_processor.subprocess.Popen")
    def test_merge_scenes_multiple(self, mock_popen, vp, tmp_path):
        s1, s2 = tmp_path / "s1.mp4", tmp_path / "s2.mp4"
        s1.write_bytes(b"v1")
        s2.write_bytes(b"v2")
        proc = MagicMock()
        proc.poll.return_value = 0
        proc.stderr.readline.return_value = ""
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc
        vp._merge_scenes([str(s1), str(s2)], str(tmp_path / "m.mp4"))
        assert (vp.output_dir / "concat_list.txt").exists()

    def test_apply_branding_no_logo(self, vp, tmp_path):
        src = tmp_path / "input.mp4"
        src.write_bytes(b"fake video")
        out = str(tmp_path / "branded.mp4")
        vp._apply_branding(str(src), out, MOOD_SETTINGS["elegant"])
        assert Path(out).exists()

    def test_get_audio_normalize_args_error(self, vp):
        result = vp._get_audio_normalize_args("/dummy.mp4")
        assert isinstance(result, list)

    def test_process_scene_ffmpeg_fail_fallback(self, vp, tmp_path):
        src = tmp_path / "in.mp4"
        src.write_bytes(b"video data")
        out = str(tmp_path / "out.mp4")
        with patch.object(vp, "_run_ffmpeg", return_value=False):
            with patch.object(vp, "_get_audio_normalize_args", return_value=[]):
                vp._process_scene(str(src), out, MOOD_SETTINGS["dynamic"])
        assert Path(out).exists()

    def test_record_soul_narrative_error(self, vp):
        settings = MoodSettings(
            name="test", color_preset="warm", transition="fade",
            music_style="classical", telop_style="minimal"
        )
        vp._record_soul_narrative("tid", "out", settings, 3)  # no crash

    def test_get_color_filter_all_presets(self, vp):
        for p in ["cool", "energetic", "calm", "elegant", "warm", "vibrant", "cinematic"]:
            s = MoodSettings(name="t", color_preset=p, transition="", music_style="", telop_style="")
            assert len(vp._get_color_filter(s)) > 0

    def test_get_color_filter_unknown(self, vp):
        s = MoodSettings(name="t", color_preset="xxx", transition="", music_style="", telop_style="")
        assert vp._get_color_filter(s) == ""

    def test_process_scene_template_config_fallback(self, vp, tmp_path):
        src = tmp_path / "in.mp4"
        src.write_bytes(b"v")
        with patch.object(vp, "_run_ffmpeg", return_value=True):
            with patch.object(vp, "_get_audio_normalize_args", return_value=[]):
                vp._process_scene(str(src), str(tmp_path / "o.mp4"), MOOD_SETTINGS["elegant"])


# ============================================================
# video_editor_engine.py テスト
# ============================================================

class TestFFmpegEditor:

    def test_find_ffmpeg_in_path(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.ffmpeg_path == "/usr/bin/ffmpeg"

    def test_find_ffmpeg_not_found(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", return_value=False):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.ffmpeg_path is None

    def test_detect_gpu_nvenc(self, ffmpeg_editor):
        assert ffmpeg_editor.use_gpu is True

    def test_detect_gpu_no_nvenc(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="libx264", returncode=0)):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.use_gpu is False

    def test_detect_gpu_exception(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", side_effect=Exception("fail")):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.use_gpu is False

    def test_is_available_true(self, ffmpeg_editor):
        assert ffmpeg_editor.is_available() is True

    def test_is_available_false(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", return_value=False):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.is_available() is False

    def test_get_encode_args_gpu(self, ffmpeg_editor):
        assert "h264_nvenc" in ffmpeg_editor._get_encode_args("balanced")

    def test_get_encode_args_cpu(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                e = FFmpegEditor(output_dir=tmp_path)
        assert "libx264" in e._get_encode_args("balanced")

    def test_get_encode_args_all_presets(self, ffmpeg_editor):
        for q in ["fast", "balanced", "quality"]:
            assert len(ffmpeg_editor._get_encode_args(q)) >= 4

    def test_get_encode_args_unknown(self, ffmpeg_editor):
        assert len(ffmpeg_editor._get_encode_args("xxx")) >= 4

    def test_hwaccel_gpu(self, ffmpeg_editor):
        assert "-hwaccel" in ffmpeg_editor._get_hwaccel_input_args()

    def test_hwaccel_cpu(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e._get_hwaccel_input_args() == []

    def test_run_command_not_available(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", return_value=False):
                e = FFmpegEditor(output_dir=tmp_path)
        ok, msg = e.run_command(["-version"])
        assert ok is False

    def test_run_command_success(self, ffmpeg_editor):
        with patch("video_editor_engine.subprocess.run") as m:
            m.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            ok, _ = ffmpeg_editor.run_command(["-version"])
        assert ok is True

    def test_run_command_failure(self, ffmpeg_editor):
        with patch("video_editor_engine.subprocess.run") as m:
            m.return_value = MagicMock(returncode=1, stderr="err")
            ok, _ = ffmpeg_editor.run_command(["-bad"])
        assert ok is False

    def test_run_command_timeout(self, ffmpeg_editor):
        import subprocess as sp
        with patch("video_editor_engine.subprocess.run", side_effect=sp.TimeoutExpired("x", 1)):
            ok, msg = ffmpeg_editor.run_command(["-x"], timeout=1)
        assert ok is False

    def test_run_command_exception(self, ffmpeg_editor):
        with patch("video_editor_engine.subprocess.run", side_effect=OSError("oops")):
            ok, _ = ffmpeg_editor.run_command(["-x"])
        assert ok is False

    def test_cut_video_copy(self, ffmpeg_editor):
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.cut_video(Path("/i.mp4"), Path("/o.mp4"), 10, 20) is True

    def test_cut_video_reencode(self, ffmpeg_editor):
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.cut_video(Path("/i.mp4"), Path("/o.mp4"), 10, 20, reencode=True) is True

    def test_merge_videos_empty(self, ffmpeg_editor):
        assert ffmpeg_editor.merge_videos([], Path("/o.mp4")) is False

    def test_merge_videos_cut(self, ffmpeg_editor, tmp_path):
        clips = [VideoClip(path=Path("/v1.mp4")), VideoClip(path=Path("/v2.mp4"))]
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.merge_videos(clips, tmp_path / "o.mp4") is True

    def test_merge_videos_fade(self, ffmpeg_editor, tmp_path):
        clips = [VideoClip(path=Path("/v1.mp4"))]
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.merge_videos(clips, tmp_path / "o.mp4", TransitionType.FADE) is True

    def test_merge_videos_fail(self, ffmpeg_editor, tmp_path):
        clips = [VideoClip(path=Path("/v1.mp4"))]
        with patch.object(ffmpeg_editor, "run_command", return_value=(False, "err")):
            assert ffmpeg_editor.merge_videos(clips, tmp_path / "o.mp4") is False

    def test_add_telop(self, ffmpeg_editor, tmp_path):
        for pos in ["top", "center", "bottom"]:
            with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
                assert ffmpeg_editor.add_telop(Path("/i.mp4"), tmp_path / "o.mp4", "テスト", position=pos) is True

    def test_batch_telops_empty(self, ffmpeg_editor, tmp_path):
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        assert ffmpeg_editor.apply_batch_telops(src, tmp_path / "o.mp4", []) is True

    def test_batch_telops_data(self, ffmpeg_editor, tmp_path):
        telops = [{"text": "hi", "start": 0, "end": 5}]
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.apply_batch_telops(Path("/i.mp4"), tmp_path / "o.mp4", telops) is True

    def test_extract_audio(self, ffmpeg_editor, tmp_path):
        with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")):
            assert ffmpeg_editor.extract_audio(Path("/i.mp4"), tmp_path / "o.mp3") is True

    def test_get_duration_no_ffprobe(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", return_value=False):
                e = FFmpegEditor(output_dir=tmp_path)
        assert e.get_duration(Path("/i.mp4")) is None

    def test_add_opening(self, ffmpeg_editor, tmp_path):
        with patch.object(ffmpeg_editor, "merge_videos", return_value=True):
            assert ffmpeg_editor.add_opening(Path("/m.mp4"), Path("/op.mp4"), tmp_path / "o.mp4") is True

    def test_add_ending(self, ffmpeg_editor, tmp_path):
        with patch.object(ffmpeg_editor, "merge_videos", return_value=True):
            assert ffmpeg_editor.add_ending(Path("/m.mp4"), Path("/ed.mp4"), tmp_path / "o.mp4") is True

    def test_safe_io_import_error_fallback(self):
        """safe_ioインポート失敗時のフォールバック処理を検証"""
        import sys
        from unittest.mock import patch
        from pathlib import Path
        with patch.dict(sys.modules, {"safe_io": None}):
            import importlib
            import video_editor_engine
            importlib.reload(video_editor_engine)
            assert video_editor_engine.DEFAULT_OUTPUT_DIR == Path("output/edited")
        
        # クリーンアップ（元の状態にリロード）
        import importlib
        import video_editor_engine
        importlib.reload(video_editor_engine)

    def test_find_ffmpeg_in_common_paths(self, tmp_path):
        """PATH上にないが共通パスに存在するFFmpeg検出を検証"""
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", side_effect=[False, False, True, False]):
                e = FFmpegEditor(output_dir=tmp_path)
                assert e.ffmpeg_path == "/usr/bin/ffmpeg"

    def test_apply_batch_telops_template_config_exception(self, ffmpeg_editor, tmp_path):
        """template_configインポート例外時のフォールバックフォントサイズ適用を検証"""
        telops = [{"text": "hi", "start": 0, "end": 5}]
        with patch.dict(sys.modules, {"template_config": None}):
            with patch.object(ffmpeg_editor, "run_command", return_value=(True, "")) as mock_run:
                assert ffmpeg_editor.apply_batch_telops(Path("/i.mp4"), tmp_path / "o.mp4", telops) is True
                called_args = mock_run.call_args[0][0]
                assert "fontsize=40" in "".join(called_args)

    def test_get_duration_ffprobe_uppercase_replace(self, tmp_path):
        """ffmpeg.EXE などの大文字パスが ffprobe.EXE に置換されることを検証"""
        with patch("video_editor_engine.shutil.which", return_value="C:/ffmpeg/bin/ffmpeg.EXE"):
            with patch("video_editor_engine.Path.exists", return_value=True):
                e = FFmpegEditor(output_dir=tmp_path)
                with patch("video_editor_engine.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(stdout="10.5\n", returncode=0)
                    duration = e.get_duration(Path("/i.mp4"))
                    called_cmd = mock_run.call_args[0][0][0]
                    assert called_cmd == "C:/ffmpeg/bin/ffprobe.EXE"
                    assert duration == 10.5

    def test_get_duration_subprocess_exception(self, ffmpeg_editor):
        """ffprobe実行時例外によるNone返却を検証"""
        with patch("video_editor_engine.Path.exists", return_value=True):
            with patch("video_editor_engine.subprocess.run", side_effect=Exception("ffprobe error")):
                assert ffmpeg_editor.get_duration(Path("/i.mp4")) is None


class TestVideoEditorEngine:

    def test_create_final_no_ffmpeg(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", return_value=False):
                eng = VideoEditorEngine(output_dir=tmp_path)
        assert eng.create_final_video(Path("/m.mp4"))["success"] is False

    def test_create_final_simple(self, tmp_path):
        main = tmp_path / "m.mp4"
        main.write_bytes(b"main")
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                eng = VideoEditorEngine(output_dir=tmp_path)
        assert eng.create_final_video(main, output_name="f.mp4")["success"] is True

    def test_create_final_video_with_all_elements_fail_branches(self, tmp_path):
        """create_final_video の各編集ステップ失敗ルートとコピー処理を検証"""
        main = tmp_path / "m.mp4"
        main.write_bytes(b"main")
        
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
            # 1. テロップ適用失敗
            with patch.object(eng.ffmpeg, "apply_batch_telops", return_value=False):
                res = eng.create_final_video(main, telops=[{"text": "hi"}])
                assert "telops failed" in res["steps"]
                
            # 2. オープニング追加失敗
            opening = tmp_path / "op.mp4"
            opening.write_bytes(b"op")
            with patch.object(eng.ffmpeg, "add_opening", return_value=False):
                res = eng.create_final_video(main, opening=opening)
                assert "opening failed" in res["steps"]

            # 3. エンディング追加失敗
            ending = tmp_path / "ed.mp4"
            ending.write_bytes(b"ed")
            with patch.object(eng.ffmpeg, "add_ending", return_value=False):
                res = eng.create_final_video(main, ending=ending)
                assert "ending failed" in res["steps"]

    def test_create_final_video_with_all_elements_success_branches(self, tmp_path):
        """create_final_video の全編集ステップ成功ルートとコピー処理を検証"""
        main = tmp_path / "m.mp4"
        main.write_bytes(b"main")
        
        opening = tmp_path / "op.mp4"
        opening.write_bytes(b"op")
        
        ending = tmp_path / "ed.mp4"
        ending.write_bytes(b"ed")
        
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
            with patch.object(eng.ffmpeg, "apply_batch_telops", return_value=True):
                with patch.object(eng.ffmpeg, "add_opening", return_value=True):
                    with patch.object(eng.ffmpeg, "add_ending", return_value=True):
                        with patch("video_editor_engine.shutil.copy") as mock_copy:
                            res = eng.create_final_video(main, opening=opening, ending=ending, telops=[{"text": "hi"}])
                            assert res["success"] is True
                            assert "telops applied" in res["steps"]
                            assert "opening added" in res["steps"]
                            assert "ending added" in res["steps"]
                            assert mock_copy.call_count > 0

    def test_auto_cut_no_silence(self, tmp_path):
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                eng = VideoEditorEngine(output_dir=tmp_path)
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        with patch.object(eng.ffmpeg, "run_command", return_value=(True, "no silence")):
            assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is True

    def test_auto_cut_silence_failure_cases(self, tmp_path):
        """auto_cut_silence の異常系（無音検出失敗、動画長さ取得失敗）を検証"""
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        
        # 1. コマンド失敗
        with patch.object(eng.ffmpeg, "run_command", return_value=(False, "error")):
            assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is False

        # 2. 動画の長さ取得失敗
        dummy_silence = "[silencedetect @ 0x...] silence_start: 1.0\n[silencedetect @ 0x...] silence_end: 2.0"
        with patch.object(eng.ffmpeg, "run_command", return_value=(True, dummy_silence)):
            with patch.object(eng.ffmpeg, "get_duration", return_value=None):
                assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is False

    def test_auto_cut_silence_success_complex(self, tmp_path):
        """auto_cut_silence の正常系（無音検出、カット、結合、一時ファイル削除）を検証"""
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        
        dummy_silence = (
            "[silencedetect @ 0x...] silence_start: 2.0\n"
            "[silencedetect @ 0x...] silence_end: 3.5\n"
            "[silencedetect @ 0x...] silence_start: 6.0\n"
            "[silencedetect @ 0x...] silence_end: 7.0\n"
        )
        
        with patch.object(eng.ffmpeg, "run_command", return_value=(True, dummy_silence)):
            with patch.object(eng.ffmpeg, "get_duration", return_value=10.0):
                with patch.object(eng.ffmpeg, "cut_video", return_value=True) as mock_cut:
                    with patch.object(eng.ffmpeg, "merge_videos", return_value=True) as mock_merge:
                        with patch("video_editor_engine.Path.exists", return_value=True):
                            with patch("video_editor_engine.Path.unlink") as mock_unlink:
                                assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is True
                                assert mock_cut.call_count == 3
                                # 各区間確認
                                assert mock_cut.call_args_list[0][0][2] == 0.0
                                assert mock_cut.call_args_list[0][0][3] == 2.0
                                assert mock_cut.call_args_list[1][0][2] == 3.5
                                assert mock_cut.call_args_list[1][0][3] == 6.0
                                assert mock_cut.call_args_list[2][0][2] == 7.0
                                assert mock_cut.call_args_list[2][0][3] == 10.0
                                assert mock_merge.call_count == 1
                                assert mock_unlink.call_count == 3

    def test_auto_cut_silence_no_keep_ranges(self, tmp_path):
        """全体が無音で保持区間がないケースを検証"""
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        
        dummy_silence = (
            "[silencedetect @ 0x...] silence_start: 0.0\n"
            "[silencedetect @ 0x...] silence_end: 10.0\n"
        )
        with patch.object(eng.ffmpeg, "run_command", return_value=(True, dummy_silence)):
            with patch.object(eng.ffmpeg, "get_duration", return_value=10.0):
                assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is False

    def test_auto_cut_silence_cut_video_fails(self, tmp_path):
        """カット処理(cut_video)失敗による全体のFalse返却を検証"""
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            eng = VideoEditorEngine(output_dir=tmp_path)
            
        src = tmp_path / "i.mp4"
        src.write_bytes(b"v")
        
        dummy_silence = (
            "[silencedetect @ 0x...] silence_start: 2.0\n"
            "[silencedetect @ 0x...] silence_end: 3.0\n"
        )
        with patch.object(eng.ffmpeg, "run_command", return_value=(True, dummy_silence)):
            with patch.object(eng.ffmpeg, "get_duration", return_value=5.0):
                with patch.object(eng.ffmpeg, "cut_video", return_value=False):
                    assert eng.auto_cut_silence(src, tmp_path / "o.mp4") is False

    def test_helper_functions(self, tmp_path):
        """モジュール直下の簡易関数呼び出しを検証"""
        import video_editor_engine
        main = tmp_path / "m.mp4"
        main.write_bytes(b"main")
        with patch("video_editor_engine.shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("video_editor_engine.subprocess.run", return_value=MagicMock(stdout="", returncode=0)):
                import importlib
                importlib.reload(video_editor_engine)
                assert video_editor_engine.check_ffmpeg() is True
                assert video_editor_engine.create_final_video(main)["success"] is True


# ============================================================
# template_recommender.py テスト
# ============================================================

class TestTemplateRecommender:

    def test_analyze_empty(self):
        assert TemplateRecommender().analyze_segments([])["speech_density"] == 0

    def test_analyze_normal(self):
        segs = [{"text": "t", "start": i * 3.0, "end": i * 3.0 + 2.5} for i in range(20)]
        assert TemplateRecommender().analyze_segments(segs, 60)["speech_density"] == 20.0

    def test_analyze_auto_duration(self):
        segs = [{"text": "a", "start": 0, "end": 30}, {"text": "b", "start": 30, "end": 60}]
        assert TemplateRecommender().analyze_segments(segs)["speech_density"] > 0

    def test_analyze_silence_gaps(self):
        segs = [{"text": "a", "start": 0, "end": 5}, {"text": "b", "start": 10, "end": 15}]
        assert TemplateRecommender().analyze_segments(segs, 20)["avg_silence"] == 5.0

    def test_analyze_tempo(self):
        segs = [{"text": "x", "start": i * 2, "end": i * 2 + 1.5} for i in range(10)]
        assert TemplateRecommender().analyze_segments(segs, 30)["tempo_fast_ratio"] == 1.0

    def test_recommend_valid(self):
        segs = [{"text": "テスト" * 5, "start": i * 2.0, "end": i * 2.0 + 1.5} for i in range(30)]
        tid, info = TemplateRecommender().recommend(segs, 120)
        assert tid in TemplateRecommender.TEMPLATE_PROFILES and "score" in info

    def test_recommend_alternatives(self):
        segs = [{"text": "x", "start": i, "end": i + 0.5} for i in range(50)]
        alts = TemplateRecommender().recommend_with_alternatives(segs, 120)
        assert len(alts) == 4 and alts[0]["is_recommended"] is True

    def test_learning_bias_no_history(self):
        scores = {"nhk_documentary": {"score": 50, "reasons": []}}
        assert TemplateRecommender()._apply_learning_bias("nhk_documentary", scores) == "nhk_documentary"

    def test_learning_bias_with_history(self):
        history = json.dumps({"template_selections": [
            {"template_id": "mrbeast_entertainment", "satisfaction": 5},
            {"template_id": "mrbeast_entertainment", "satisfaction": 4},
        ]})
        scores = {
            "nhk_documentary": {"score": 50, "reasons": []},
            "mrbeast_entertainment": {"score": 48, "reasons": []},
            "hikakin_vlog": {"score": 45, "reasons": []},
            "asmr_relaxation": {"score": 30, "reasons": []},
        }
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "read_text", return_value=history):
                result = TemplateRecommender()._apply_learning_bias("nhk_documentary", scores)
        assert isinstance(result, str)


# ============================================================
# tutorial_system.py テスト（0%→100%）
# ============================================================

class TestTutorialSystem:

    def test_init_steps(self):
        assert len(Tutorial().steps) == 4

    def test_steps_type(self):
        for step in Tutorial().steps:
            assert isinstance(step, TutorialStep)

    def test_current_step_first(self):
        assert Tutorial().get_current_step().id == "step1"

    def test_mark_completed(self):
        t = Tutorial()
        t.mark_completed("step1")
        assert t.steps[0].completed is True
        assert t.get_current_step().id == "step2"

    def test_all_completed(self):
        t = Tutorial()
        for s in t.steps:
            t.mark_completed(s.id)
        assert t.get_current_step().id == "step4"

    def test_progress_initial(self):
        p = Tutorial().get_progress()
        assert p == {"total": 4, "completed": 0, "percentage": 0}

    def test_progress_partial(self):
        t = Tutorial()
        t.mark_completed("step1")
        t.mark_completed("step2")
        assert t.get_progress()["completed"] == 2 and t.get_progress()["percentage"] == 50

    def test_mark_nonexistent(self):
        t = Tutorial()
        t.mark_completed("xxx")
        assert t.get_progress()["completed"] == 0
