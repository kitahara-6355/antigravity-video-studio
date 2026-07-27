# -*- coding: utf-8 -*-
"""
Tests for video_editor_engine.py
"""

import pytest
import shutil
import sys
import re
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import subprocess

import video_editor_engine

# グローバル変数を定義（リロード時に更新されるため）
TransitionType = video_editor_engine.TransitionType
VideoClip = video_editor_engine.VideoClip
FFmpegEditor = video_editor_engine.FFmpegEditor
VideoEditorEngine = video_editor_engine.VideoEditorEngine
video_editor = video_editor_engine.video_editor
check_ffmpeg = video_editor_engine.check_ffmpeg
create_final_video = video_editor_engine.create_final_video

@pytest.fixture(autouse=True)
def mock_path_exists():
    """既存テストで使われるダミーパスの存在チェックをTrueにするモックフィクスチャ"""
    original_exists = Path.exists

    def side_effect(self, *args, **kwargs):
        name = self.name
        # 既存のテストで使われるダミーファイル名
        if name in ("in.mp4", "out.mp4", "p1.mp4", "p2.mp4", "part1.mp4", "part2.mp4", "main.mp4", "open.mp4", "end.mp4", "out.mp3", "dummy.mp4"):
            return True
        if "does_not_exist" in name:
            return False
        return original_exists(self, *args, **kwargs)

    with patch("video_editor_engine.Path.exists", side_effect):
        yield



def test_default_output_dir_fallback():
    """safe_ioインポート失敗時のデフォルト出力ディレクトリ設定を検証"""
    global TransitionType, VideoClip, FFmpegEditor, VideoEditorEngine, video_editor, check_ffmpeg, create_final_video
    
    # 一時的にsys.modulesからsafe_ioを排除
    with patch.dict(sys.modules, {"safe_io": None}):
        # video_editor_engineをリロード
        importlib.reload(video_editor_engine)
        # フォールバックされたパスになっていることを検証
        assert video_editor_engine.DEFAULT_OUTPUT_DIR == Path("output/edited")
    
    # テスト後に元に戻しておく
    importlib.reload(video_editor_engine)
    
    # グローバル変数の参照を最新のものに更新
    TransitionType = video_editor_engine.TransitionType
    VideoClip = video_editor_engine.VideoClip
    FFmpegEditor = video_editor_engine.FFmpegEditor
    VideoEditorEngine = video_editor_engine.VideoEditorEngine
    video_editor = video_editor_engine.video_editor
    check_ffmpeg = video_editor_engine.check_ffmpeg
    create_final_video = video_editor_engine.create_final_video

@pytest.fixture(autouse=True)
def mock_path_exists():
    """既存テストで使われるダミーパスの存在チェックをTrueにするモックフィクスチャ"""
    original_exists = Path.exists

    def side_effect(self, *args, **kwargs):
        name = self.name
        # 既存のテストで使われるダミーファイル名
        if name in ("in.mp4", "out.mp4", "p1.mp4", "p2.mp4", "part1.mp4", "part2.mp4", "main.mp4", "open.mp4", "end.mp4", "out.mp3", "dummy.mp4"):
            return True
        if "does_not_exist" in name:
            return False
        return original_exists(self, *args, **kwargs)

    with patch("video_editor_engine.Path.exists", side_effect):
        yield



def test_transition_type_enum():
    """TransitionTypeのメンバー検証"""
    assert TransitionType.CUT.value == "cut"
    assert TransitionType.FADE.value == "fade"
    assert TransitionType.DISSOLVE.value == "dissolve"
    assert TransitionType.WIPE.value == "wipe"


def test_video_clip_dataclass():
    """VideoClipの初期化検証"""
    clip = VideoClip(path=Path("test.mp4"), start_sec=1.5, end_sec=5.0, label="main")
    assert clip.path == Path("test.mp4")
    assert clip.start_sec == 1.5
    assert clip.end_sec == 5.0
    assert clip.label == "main"

    # デフォルト値
    clip_default = VideoClip(path=Path("test2.mp4"))
    assert clip_default.start_sec == 0
    assert clip_default.end_sec is None
    assert clip_default.label == ""





class TestFFmpegEditor:
    """FFmpegEditorのテスト"""

    def test_init_and_find_ffmpeg(self, tmp_path):
        """初期化とFFmpeg探索ロジックの検証"""
        # 1. shutil.whichがFFmpegを見つける場合
        with patch("shutil.which", return_value="/mock/bin/ffmpeg"):
            editor = FFmpegEditor(output_dir=tmp_path)
            assert editor.ffmpeg_path == "/mock/bin/ffmpeg"
            assert editor.output_dir == tmp_path
            assert (tmp_path / ".temp").exists()

        # 2. shutil.whichが失敗し、common_pathsのどれかが存在する場合
        with patch("shutil.which", return_value=None):
            # 3番目の /usr/bin/ffmpeg が存在する想定で side_effect に順番にTrue/Falseを指定
            with patch("video_editor_engine.Path.exists", side_effect=[False, False, True]):
                editor = FFmpegEditor(output_dir=tmp_path)
                assert editor.ffmpeg_path is not None
                assert "usr/bin/ffmpeg" in editor.ffmpeg_path.replace("\\", "/")

        # 3. いずれも見つからない場合
        with patch("shutil.which", return_value=None):
            with patch("video_editor_engine.Path.exists", side_effect=[False, False, False, False]):
                editor = FFmpegEditor(output_dir=tmp_path)
                assert editor.ffmpeg_path is None

    def test_detect_gpu(self, tmp_path):
        """GPU検出ロジックの検証"""
        # ffmpeg_pathがNoneの場合
        with patch("shutil.which", return_value=None), \
             patch("video_editor_engine.Path.exists", return_value=False):
            editor = FFmpegEditor(output_dir=tmp_path)
            assert editor.use_gpu is False

        # ffmpeg_pathが存在する場合
        with patch("shutil.which", return_value="/mock/ffmpeg"):
            # 1. GPU対応 (h264_nvencあり)
            mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="h264_nvenc enabled"))
            with patch("subprocess.run", mock_run):
                editor = FFmpegEditor(output_dir=tmp_path)
                assert editor.use_gpu is True

            # 2. GPU非対応 (h264_nvencなし)
            mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="other encoders"))
            with patch("subprocess.run", mock_run):
                editor = FFmpegEditor(output_dir=tmp_path)
                assert editor.use_gpu is False

            # 3. 例外発生時 (CPUフォールバック)
            mock_run = MagicMock(side_effect=OSError("Subprocess failed"))
            with patch("subprocess.run", mock_run):
                editor = FFmpegEditor(output_dir=tmp_path)
                assert editor.use_gpu is False

    def test_get_encode_args(self, tmp_path):
        """GPU/CPUに応じたエンコード引数の取得検証"""
        with patch("shutil.which", return_value="/mock/ffmpeg"):
            # GPUが有効な場合
            editor_gpu = FFmpegEditor(output_dir=tmp_path)
            editor_gpu.use_gpu = True

            args_fast = editor_gpu._get_encode_args("fast")
            assert "h264_nvenc" in args_fast
            assert "p1" in args_fast

            args_balanced = editor_gpu._get_encode_args("balanced")
            assert "p4" in args_balanced

            args_quality = editor_gpu._get_encode_args("quality")
            assert "p7" in args_quality

            args_default = editor_gpu._get_encode_args("invalid_quality")
            assert "p4" in args_default  # balancedにフォールバック

            # CPUが有効な場合
            editor_cpu = FFmpegEditor(output_dir=tmp_path)
            editor_cpu.use_gpu = False

            args_cpu_fast = editor_cpu._get_encode_args("fast")
            assert "libx264" in args_cpu_fast
            assert "ultrafast" in args_cpu_fast

            args_cpu_quality = editor_cpu._get_encode_args("quality")
            assert "slow" in args_cpu_quality

    def test_get_hwaccel_input_args(self, tmp_path):
        """GPUデコードの入力引数の検証"""
        with patch("shutil.which", return_value="/mock/ffmpeg"):
            editor = FFmpegEditor(output_dir=tmp_path)
            
            editor.use_gpu = True
            assert editor._get_hwaccel_input_args() == ["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"]

            editor.use_gpu = False
            assert editor._get_hwaccel_input_args() == []

    def test_is_available(self, tmp_path):
        """FFmpeg利用可能判定の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"
        assert editor.is_available() is True

        editor.ffmpeg_path = None
        assert editor.is_available() is False

    def test_run_command(self, tmp_path):
        """FFmpegコマンド実行の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        
        # 1. FFmpegが利用不可の場合
        editor.ffmpeg_path = None
        success, msg = editor.run_command(["-version"])
        assert success is False
        assert msg == "FFmpeg not available"

        editor.ffmpeg_path = "/mock/ffmpeg"

        # 2. コマンド成功 (returncode = 0)
        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="success output"))
        with patch("subprocess.run", mock_run):
            success, msg = editor.run_command(["-i", "input.mp4"])
            assert success is True
            assert msg == "success output"

        # 3. コマンド失敗 (returncode != 0)
        mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=1, stderr="error output"))
        with patch("subprocess.run", mock_run):
            success, msg = editor.run_command(["-i", "input.mp4"])
            assert success is False
            assert msg == "error output"

        # 4. タイムアウト発生
        mock_run = MagicMock(side_effect=subprocess.TimeoutExpired(cmd=[], timeout=60))
        with patch("subprocess.run", mock_run):
            success, msg = editor.run_command(["-i", "input.mp4"])
            assert success is False
            assert msg == "Timeout"

        # 5. 一般例外発生
        mock_run = MagicMock(side_effect=ValueError("General error"))
        with patch("subprocess.run", mock_run):
            success, msg = editor.run_command(["-i", "input.mp4"])
            assert success is False
            assert msg == "General error"

    def test_cut_video(self, tmp_path):
        """動画カットの検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"
        editor.use_gpu = False

        # 1. ストリームコピー (reencode=False)
        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.cut_video(Path("in.mp4"), Path("out.mp4"), 1.0, 5.0, reencode=False)
            assert success is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "-c" in args
            assert "copy" in args

        # 2. 再エンコード (reencode=True)
        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.cut_video(Path("in.mp4"), Path("out.mp4"), 1.0, 5.0, reencode=True)
            assert success is True
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "libx264" in args

    def test_merge_videos(self, tmp_path):
        """複数動画結合の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"
        editor.use_gpu = False

        # 1. クリップが空の場合
        success = editor.merge_videos([], Path("out.mp4"))
        assert success is False

        clips = [
            VideoClip(path=Path("part1.mp4")),
            VideoClip(path=Path("part2.mp4"))
        ]

        # 2. 通常カット (CUT)
        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.merge_videos(clips, Path("out.mp4"), transition=TransitionType.CUT)
            assert success is True
            args = mock_run.call_args[0][0]
            idx = args.index("-i")
            list_file_path = Path(args[idx + 1])
            assert "concat_list_" in list_file_path.name
            assert not list_file_path.exists()
            assert "concat" in args
            assert "copy" in args

        # 3. トランジション付き (FADEなど、再エンコード)
        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.merge_videos(clips, Path("out.mp4"), transition=TransitionType.FADE)
            assert success is True
            args = mock_run.call_args[0][0]
            assert "libx264" in args

        # 4. 結合コマンド失敗時
        with patch.object(editor, "run_command", return_value=(False, "Failed to merge")) as mock_run:
            success = editor.merge_videos(clips, Path("out.mp4"), transition=TransitionType.CUT)
            assert success is False

    def test_add_opening_and_ending(self, tmp_path):
        """オープニング・エンディング追加の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"

        with patch.object(editor, "merge_videos", return_value=True) as mock_merge:
            success = editor.add_opening(Path("main.mp4"), Path("open.mp4"), Path("out.mp4"))
            assert success is True
            mock_merge.assert_called_once()
            clips = mock_merge.call_args[0][0]
            assert clips[0].path == Path("open.mp4")
            assert clips[1].path == Path("main.mp4")

        with patch.object(editor, "merge_videos", return_value=True) as mock_merge:
            success = editor.add_ending(Path("main.mp4"), Path("end.mp4"), Path("out.mp4"))
            assert success is True
            mock_merge.assert_called_once()
            clips = mock_merge.call_args[0][0]
            assert clips[0].path == Path("main.mp4")
            assert clips[1].path == Path("end.mp4")

    def test_add_telop(self, tmp_path):
        """テロップ焼き込みの検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"

        positions_to_test = ["top", "center", "bottom", "invalid_pos"]
        for pos in positions_to_test:
            with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
                success = editor.add_telop(
                    input_path=Path("in.mp4"),
                    output_path=Path("out.mp4"),
                    text="Hello World",
                    position=pos,
                    start_sec=1.0,
                    duration_sec=3.0
                )
                assert success is True
                args = mock_run.call_args[0][0]
                assert "-vf" in args
                # フィルター文字列の確認
                vf_arg = args[args.index("-vf") + 1]
                assert "drawtext" in vf_arg
                assert "Hello World" in vf_arg
                assert "between(t,1.0,4.0)" in vf_arg

    def test_apply_batch_telops(self, tmp_path):
        """一括テロップ適用の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"

        # 1. テロップが空の場合 (コピーして終了)
        with patch("shutil.copy") as mock_copy:
            success = editor.apply_batch_telops(Path("in.mp4"), Path("out.mp4"), [])
            assert success is True
            mock_copy.assert_called_once_with(Path("in.mp4"), Path("out.mp4"))

        telops = [
            {"text": "Text1", "start": 1.0, "end": 4.0, "position": "top"},
            {"text": "Text2", "start": 5.0, "end": 8.0, "position": "bottom"}
        ]

        # 2. 通常適用
        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.apply_batch_telops(Path("in.mp4"), Path("out.mp4"), telops)
            assert success is True
            args = mock_run.call_args[0][0]
            vf_arg = args[args.index("-vf") + 1]
            assert "Text1" in vf_arg
            assert "Text2" in vf_arg

        # 3. テンプレート設定モジュールインポート失敗時のフォールバック検証
        with patch.dict(sys.modules, {"template_config": None}):
            # sys.modulesから削除された状態でインポートエラーをシミュレート
            with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
                success = editor.apply_batch_telops(Path("in.mp4"), Path("out.mp4"), telops)
                assert success is True

    def test_extract_audio(self, tmp_path):
        """音声抽出の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)
        editor.ffmpeg_path = "/mock/ffmpeg"

        with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
            success = editor.extract_audio(Path("in.mp4"), Path("out.mp3"))
            assert success is True
            args = mock_run.call_args[0][0]
            assert "-vn" in args
            assert "libmp3lame" in args

    def test_get_duration(self, tmp_path):
        """動画の長さ取得の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)

        # 1. ffmpeg_pathがNoneの場合
        editor.ffmpeg_path = None
        assert editor.get_duration(Path("in.mp4")) is None

        # 2. ffmpeg.EXE (Windows大文字) が含まれ、ffprobe.EXEに置換される場合
        editor.ffmpeg_path = "/mock/bin/ffmpeg.EXE"
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="12.34\n")):
            duration = editor.get_duration(Path("in.mp4"))
            assert duration == 12.34

        # 3. 通常のffmpegがffprobeに置換される場合
        editor.ffmpeg_path = "/mock/bin/ffmpeg"
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="45.67\n")):
            duration = editor.get_duration(Path("in.mp4"))
            assert duration == 45.67

        # 4. ffprobeが存在しない場合
        editor.ffmpeg_path = "/mock/bin/ffmpeg"
        def mock_exists_duration(self, *args, **kwargs):
            if "ffprobe" in self.name.lower() or "ffmpeg" in self.name.lower():
                return False
            return True
        with patch("video_editor_engine.Path.exists", mock_exists_duration):
            assert editor.get_duration(Path("in.mp4")) is None

        # 5. 例外発生時のフォールバック
        editor.ffmpeg_path = "/mock/bin/ffmpeg"
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.SubprocessError("ffprobe crash")):
            assert editor.get_duration(Path("in.mp4")) is None

    def test_get_video_info(self, tmp_path):
        """動画情報取得の検証"""
        editor = FFmpegEditor(output_dir=tmp_path)

        # 1. ffmpeg_pathがNoneで、かつffprobeがパス上にない場合
        editor.ffmpeg_path = None
        def mock_exists_info(self, *args, **kwargs):
            if "ffprobe" in self.name.lower() or "ffmpeg" in self.name.lower():
                return False
            return True
        with patch("video_editor_engine.Path.exists", mock_exists_info):
            info = editor.get_video_info(Path("in.mp4"))
            assert info["width"] == 0
            assert info["duration"] == 0.0

        # 2. 通常取得成功ケース
        editor.ffmpeg_path = "/mock/bin/ffmpeg"
        json_output = """{
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1920,
                    "height": 1080,
                    "codec_name": "h264"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "120.5"
            }
        }"""
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json_output)):
            info = editor.get_video_info(Path("in.mp4"))
            assert info["width"] == 1920
            assert info["height"] == 1080
            assert info["video_codec"] == "h264"
            assert info["audio_codec"] == "aac"
            assert info["duration"] == 120.5

        # 3. 大文字ffmpeg.EXEでの置換
        editor.ffmpeg_path = "/mock/bin/ffmpeg.EXE"
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json_output)):
            info = editor.get_video_info(Path("in.mp4"))
            assert info["width"] == 1920

        # 4. 例外発生時のフォールバック
        editor.ffmpeg_path = "/mock/bin/ffmpeg"
        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("subprocess.run", side_effect=ValueError("JSON decode failed")):
            info = editor.get_video_info(Path("in.mp4"))
            assert info["width"] == 0
            assert info["video_codec"] == ""


class TestVideoEditorEngine:
    """VideoEditorEngine of video_editor_engine.py"""

    def test_engine_availability(self, tmp_path):
        """利用可能フラグの伝播検証"""
        engine = VideoEditorEngine(output_dir=tmp_path)
        with patch.object(engine.ffmpeg, "is_available", return_value=True):
            assert engine.is_available() is True
        with patch.object(engine.ffmpeg, "is_available", return_value=False):
            assert engine.is_available() is False

    def test_create_final_video(self, tmp_path):
        """最終動画生成パイプラインの検証"""
        engine = VideoEditorEngine(output_dir=tmp_path)

        # 1. FFmpegが利用不可の場合
        with patch.object(engine, "is_available", return_value=False):
            res = engine.create_final_video(Path("main.mp4"))
            assert res["success"] is False
            assert res["error"] == "FFmpeg not available"

        # FFmpegを利用可能にする
        with patch.object(engine, "is_available", return_value=True):
            # モックヘルパー
            engine.ffmpeg.apply_batch_telops = MagicMock(return_value=True)
            engine.ffmpeg.add_opening = MagicMock(return_value=True)
            engine.ffmpeg.add_ending = MagicMock(return_value=True)

            # オープニング・エンディングファイルのダミー存在設定
            with patch("video_editor_engine.Path.exists", return_value=True), \
                 patch("shutil.copy") as mock_copy:
                
                # 全て正常系
                telops = [{"text": "Hello", "start": 0, "end": 5}]
                res = engine.create_final_video(
                    main_video=Path("main.mp4"),
                    opening=Path("open.mp4"),
                    ending=Path("end.mp4"),
                    telops=telops,
                    output_name="output.mp4"
                )
                assert res["success"] is True
                assert "telops applied" in res["steps"]
                assert "opening added" in res["steps"]
                assert "ending added" in res["steps"]
                mock_copy.assert_called_once()

            # 一部フェーズの失敗系検証
            engine.ffmpeg.apply_batch_telops = MagicMock(return_value=False)
            engine.ffmpeg.add_opening = MagicMock(return_value=False)
            engine.ffmpeg.add_ending = MagicMock(return_value=False)

            with patch("video_editor_engine.Path.exists", return_value=True), \
                 patch("shutil.copy"):
                res = engine.create_final_video(
                    main_video=Path("main.mp4"),
                    opening=Path("open.mp4"),
                    ending=Path("end.mp4"),
                    telops=telops,
                    output_name="output.mp4"
                )
                assert res["success"] is True  # 処理全体としてはフォールバックして進行
                assert "telops failed" in res["steps"]
                assert "opening failed" in res["steps"]
                assert "ending failed" in res["steps"]

            # テロップや追加動画なしの場合 (そのままコピー)
            with patch("shutil.copy") as mock_copy:
                res = engine.create_final_video(
                    main_video=Path("main.mp4"),
                    output_name="output.mp4"
                )
                assert res["success"] is True
                assert len(res["steps"]) == 0
                mock_copy.assert_called_once_with(Path("main.mp4"), tmp_path / "output.mp4")

    def test_auto_cut_silence(self, tmp_path):
        """無音自動カット処理の検証"""
        engine = VideoEditorEngine(output_dir=tmp_path)

        # 1. 無音検出コマンドが失敗する場合
        engine.ffmpeg.run_command = MagicMock(return_value=(False, "detect failed"))
        success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
        assert success is False

        # 2. 無音が全く検出されなかった場合 (オリジナルをコピー)
        engine.ffmpeg.run_command = MagicMock(return_value=(True, "no silence markers"))
        with patch("shutil.copy") as mock_copy:
            success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
            assert success is True
            mock_copy.assert_called_once_with(Path("in.mp4"), Path("out.mp4"))

        # 3. 無音が検出されるが、動画の長さが取得できない場合
        detect_output = "[silencedetect @ 0x...] silence_start: 1.5\n[silencedetect @ 0x...] silence_end: 2.5"
        engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
        engine.ffmpeg.get_duration = MagicMock(return_value=None)
        success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
        assert success is False

        # 4. 無音区間が検出され、保持区間の切り出し・結合が正常に行われる場合
        engine.ffmpeg.get_duration = MagicMock(return_value=10.0)
        # 無音区間: 1.5 ~ 2.5, 4.0 ~ 5.0
        detect_output = (
            "silence_start: 1.5\n"
            "silence_end: 2.5\n"
            "silence_start: 4.0\n"
            "silence_end: 5.0\n"
        )
        engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
        engine.ffmpeg.cut_video = MagicMock(return_value=True)
        engine.ffmpeg.merge_videos = MagicMock(return_value=True)

        with patch("video_editor_engine.Path.exists", return_value=True), \
             patch("video_editor_engine.Path.unlink") as mock_unlink:
            success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
            assert success is True
            # 有音区間が3つ作成される (0.0~1.5, 2.5~4.0, 5.0~10.0)
            assert engine.ffmpeg.cut_video.call_count == 3
            engine.ffmpeg.merge_videos.assert_called_once()
            # 一時ファイルのクリーンアップ unlink 呼び出し確認
            assert mock_unlink.call_count == 3

        # 5. 切り出しが一部失敗した場合
        engine.ffmpeg.cut_video = MagicMock(return_value=False)
        success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
        assert success is False

        # 6. 保持区間が極めて短い等で、保持対象が空になった場合
        # 全体が無音のケース
        detect_output = "silence_start: 0.0\nsilence_end: 10.0"
        engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
        success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
        assert success is False


def test_helper_functions():
    """モジュール補助関数の検証"""
    with patch("video_editor_engine.video_editor.is_available", return_value=True):
        assert check_ffmpeg() is True

    with patch("video_editor_engine.video_editor.create_final_video", return_value={"success": True}) as mock_create:
        res = create_final_video(Path("main.mp4"), opening=Path("open.mp4"))
        assert res["success"] is True
        mock_create.assert_called_once_with(Path("main.mp4"), opening=Path("open.mp4"))


def test_ffprobe_path_resolution_with_parent_ffmpeg_dir(tmp_path):
    """親ディレクトリ名に 'ffmpeg' が含まれていても ffprobe パスが正しく解決されるか検証"""
    # 1. get_duration でのパス解決
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "C:/my-ffmpeg-setup/ffmpeg.exe"
    
    with patch("video_editor_engine.Path.exists", return_value=True), \
         patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="10.0\n")):
        dur = editor.get_duration(Path("in.mp4"))
        assert dur == 10.0
        
    # 2. get_video_info でのパス解決
    editor.ffmpeg_path = "/usr/local/ffmpeg-distribution/bin/ffmpeg"
    json_output = '{"streams": [{"codec_type": "video", "width": 1280, "height": 720}], "format": {"duration": "10.0"}}'
    with patch("video_editor_engine.Path.exists", return_value=True), \
         patch("subprocess.run", return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json_output)):
        info = editor.get_video_info(Path("in.mp4"))
        assert info["width"] == 1280


def test_merge_videos_cleanup(tmp_path):
    """merge_videosの実行完了後に一時ファイルが確実に削除されるか検証"""
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "/mock/ffmpeg"
    
    clips = [VideoClip(path=Path("p1.mp4")), VideoClip(path=Path("p2.mp4"))]
    
    # 成功ケース
    with patch.object(editor, "run_command", return_value=(True, "")) as mock_run:
        success = editor.merge_videos(clips, Path("out.mp4"))
        assert success is True
        # 一時ディレクトリに concat_list_*.txt が残っていないことを検証
        temp_files = list(editor.temp_dir.glob("concat_list_*.txt"))
        assert len(temp_files) == 0

    # 失敗ケース
    with patch.object(editor, "run_command", return_value=(False, "error")) as mock_run:
        success = editor.merge_videos(clips, Path("out.mp4"))
        assert success is False
        temp_files = list(editor.temp_dir.glob("concat_list_*.txt"))
        assert len(temp_files) == 0


def test_auto_cut_silence_cleanup_on_failure(tmp_path):
    """auto_cut_silenceが失敗または例外発生した場合でも一時ファイルが確実に削除されるか検証"""
    engine = VideoEditorEngine(output_dir=tmp_path)
    engine.ffmpeg.ffmpeg_path = "/mock/ffmpeg"
    
    # 無音区間が検出される想定
    detect_output = "silence_start: 1.0\nsilence_end: 2.0\n"
    engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
    engine.ffmpeg.get_duration = MagicMock(return_value=5.0)
    
    # cut_video が呼ばれたときに一時ファイルを作成するようモック
    created_temp_files = []
    
    def mock_cut(input_path, output_path, start, end, reencode=False):
        # 実際に一時ファイルを生成して、後でクリーンアップされたか確かめる
        output_path.write_text("dummy video content")
        created_temp_files.append(output_path)
        return True
        
    engine.ffmpeg.cut_video = MagicMock(side_effect=mock_cut)
    
    # 結合処理で例外が発生した場合
    engine.ffmpeg.merge_videos = MagicMock(side_effect=RuntimeError("Merge crashed"))
    
    with pytest.raises(RuntimeError):
        engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
            
    # 例外発生後、作成された一時ファイルがすべて削除されていることを検証
    for p in created_temp_files:
        assert not p.exists()


def test_detect_silence_segments(tmp_path):
    """_detect_silence_segments の動作検証"""
    engine = VideoEditorEngine(output_dir=tmp_path)
    
    # 正常系 (無音検出)
    detect_output = "silence_start: 1.5\nsilence_end: 2.5\n"
    engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
    res = engine._detect_silence_segments(Path("in.mp4"), -40, 1.0)
    assert res is not None
    starts, ends = res
    assert starts == [1.5]
    assert ends == [2.5]

    # 失敗系
    engine.ffmpeg.run_command = MagicMock(return_value=(False, "error"))
    res = engine._detect_silence_segments(Path("in.mp4"), -40, 1.0)
    assert res is None


def test_calculate_keep_ranges():
    """_calculate_keep_ranges の動作検証"""
    engine = VideoEditorEngine()
    
    # 通常ケース: 1.5 ~ 2.5 が無音、全長 10 秒
    # 保持すべきは 0.0 ~ 1.5, 2.5 ~ 10.0
    ranges = engine._calculate_keep_ranges([1.5], [2.5], 10.0)
    assert ranges == [(0.0, 1.5), (2.5, 10.0)]
    
    # 連続する有音が短すぎる場合 (prev_end + 0.1 以下)
    # 例: 0.0 ~ 0.05 は保持しない
    ranges = engine._calculate_keep_ranges([0.05], [1.0], 10.0)
    assert ranges == [(1.0, 10.0)]


def test_resolve_ffprobe_path_large_ffmpeg(tmp_path):
    """ffmpeg_path の名前が大文字の FFMPEG である場合のパス解決の検証 (79行目のカバー)"""
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "C:/my-ffmpeg-setup/FFMPEG"
    
    with patch("video_editor_engine.Path.exists", return_value=True):
        ffprobe_path = editor._resolve_ffprobe_path()
        assert ffprobe_path == "C:/my-ffmpeg-setup/FFPROBE"


def test_merge_videos_unlink_exception(tmp_path, caplog):
    """merge_videos内の一時リストファイル削除時に例外が発生した際の挙動の検証 (299-300行目のカバー)"""
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "/mock/ffmpeg"
    
    clips = [VideoClip(path=Path("p1.mp4")), VideoClip(path=Path("p2.mp4"))]
    
    # Path.unlinkをモックして、一時ファイル削除時に例外を発生させる
    original_unlink = Path.unlink
    
    def mock_unlink(self, *args, **kwargs):
        if "concat_list_" in self.name:
            raise OSError("Unlink failed mock exception")
        return original_unlink(self, *args, **kwargs)
        
    with patch("video_editor_engine.Path.unlink", mock_unlink),          patch.object(editor, "run_command", return_value=(True, "")) as mock_run,          caplog.at_level("WARNING"):
         
        success = editor.merge_videos(clips, Path("out.mp4"))
        assert success is True
        
        # ログメッセージが含まれているか確認
        assert any("Failed to delete concat list file" in record.message for record in caplog.records)


def test_cut_and_merge_segments_unlink_exception(tmp_path, caplog):
    """_cut_and_merge_segments内の一時部分ファイル削除時に例外が発生した際の挙動の検証 (664-665行目のカバー)"""
    engine = VideoEditorEngine(output_dir=tmp_path)
    engine.ffmpeg.ffmpeg_path = "/mock/ffmpeg"
    
    # 無音区間が検出される想定
    detect_output = "silence_start: 1.0\nsilence_end: 2.0\n"
    engine.ffmpeg.run_command = MagicMock(return_value=(True, detect_output))
    engine.ffmpeg.get_duration = MagicMock(return_value=5.0)
    
    # cut_videoとmerge_videosをモック
    engine.ffmpeg.cut_video = MagicMock(return_value=True)
    engine.ffmpeg.merge_videos = MagicMock(return_value=True)
    
    original_unlink = Path.unlink
    
    def mock_unlink(self, *args, **kwargs):
        if "silence_cut_" in self.name:
            raise OSError("Unlink failed mock exception")
        return original_unlink(self, *args, **kwargs)
        
    with patch("video_editor_engine.Path.unlink", mock_unlink),          patch("video_editor_engine.Path.exists", return_value=True),          caplog.at_level("WARNING"):
         
        success = engine.auto_cut_silence(Path("in.mp4"), Path("out.mp4"))
        assert success is True
        
        # ログメッセージが含まれているか確認
        assert any("Failed to delete temp file" in record.message for record in caplog.records)


def test_missing_video_files_raise_file_not_found(tmp_path):
    """動画ファイルが存在しない場合にFileNotFoundErrorがスローされるか検証"""
    editor = FFmpegEditor(output_dir=tmp_path)
    engine = VideoEditorEngine(output_dir=tmp_path)
    missing_path = Path("this_file_does_not_exist_at_all.mp4")

    # 1. FFmpegEditor methods
    with pytest.raises(FileNotFoundError):
        editor.cut_video(missing_path, Path("out.mp4"), 0.0, 1.0)

    with pytest.raises(FileNotFoundError):
        editor.merge_videos([VideoClip(path=missing_path)], Path("out.mp4"))

    with pytest.raises(FileNotFoundError):
        editor.add_telop(missing_path, Path("out.mp4"), "text")

    with pytest.raises(FileNotFoundError):
        editor.apply_batch_telops(missing_path, Path("out.mp4"), [{"text": "text", "start": 0, "end": 1}])

    with pytest.raises(FileNotFoundError):
        editor.extract_audio(missing_path, Path("out.mp3"))

    with pytest.raises(FileNotFoundError):
        editor.get_duration(missing_path)

    with pytest.raises(FileNotFoundError):
        editor.get_video_info(missing_path)

    # 2. VideoEditorEngine methods
    with pytest.raises(FileNotFoundError):
        engine.create_final_video(missing_path)

    with pytest.raises(FileNotFoundError):
        engine.auto_cut_silence(missing_path, Path("out.mp4"))


def test_detect_gpu_exception(tmp_path, caplog):
    """_detect_gpu 内で例外が発生した際に適切に False を返し警告ログを出力するか検証"""
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "/mock/ffmpeg"
    
    with patch("subprocess.run", side_effect=OSError("Mock OS Error")), \
         caplog.at_level("WARNING"):
        use_gpu = editor._detect_gpu()
        assert use_gpu is False
        assert any("GPU detection failed" in record.message for record in caplog.records)


def test_get_video_info_json_decode_error(tmp_path, caplog):
    """get_video_info 内で JSONDecodeError が発生した際に default_info を返し警告ログを出力するか検証"""
    editor = FFmpegEditor(output_dir=tmp_path)
    editor.ffmpeg_path = "/mock/ffmpeg"
    
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="invalid json"))
    
    with patch("video_editor_engine.FFmpegEditor._resolve_ffprobe_path", return_value="in.mp4"), \
         patch("subprocess.run", return_value=mock_run), \
         caplog.at_level("WARNING"):
        
        info = editor.get_video_info(Path("in.mp4"))
        assert info == {
            "width": 0,
            "height": 0,
            "video_codec": "",
            "audio_codec": "",
            "duration": 0.0
        }
        assert any("Failed to get video info" in record.message for record in caplog.records)
