import os
import sys
import json
import shutil
import time
import pytest
import subprocess
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# テスト対象モジュールの動的インポート
# パッケージ名に "." (v3.0) が含まれており直接 import できないため
target_module_path = Path(__file__).parent.parent.parent / "archives" / "archive_stable_v3.0_20260118_0953" / "video_processor.py"
spec = importlib.util.spec_from_file_location("archive_video_processor", str(target_module_path))
video_processor_module = importlib.util.module_from_spec(spec)
sys.modules["archive_video_processor"] = video_processor_module
spec.loader.exec_module(video_processor_module)

VideoProcessor = video_processor_module.VideoProcessor
ProcessingTask = video_processor_module.ProcessingTask
ProcessingPhase = video_processor_module.ProcessingPhase
MoodSettings = video_processor_module.MoodSettings
MOOD_SETTINGS = video_processor_module.MOOD_SETTINGS


# ────────────────────────────────────────────────────────
# 安全なプロセスモッククラス
# ────────────────────────────────────────────────────────
class SafeMockProcess:
    """無限ループを防止しつつ、進捗ログをパースするための安全なプロセスモック"""
    def __init__(self, lines=None, returncode=0, should_timeout=False):
        self.lines = lines or []
        self.idx = 0
        self._returncode = None if lines else returncode
        self.wait_called = False
        self.kill_called = False
        self.should_timeout = should_timeout

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        self.wait_called = True
        if self.should_timeout:
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        self._returncode = self.returncode
        return self.returncode

    def kill(self):
        self.kill_called = True
        self._returncode = -9

    def terminate(self):
        pass

    @property
    def returncode(self):
        return self._returncode

    class MockStream:
        def __init__(self, parent):
            self.parent = parent

        def readline(self):
            # ログ行が残っていれば返し、無くなれば終了コードを 0 にしてループを終わらせる
            if self.parent.idx < len(self.parent.lines):
                line = self.parent.lines[self.parent.idx]
                self.parent.idx += 1
                return line
            else:
                self.parent._returncode = 0
                return ""

        def read(self):
            return "mock stderr message"

    @property
    def stderr(self):
        return self.MockStream(self)

    @property
    def stdout(self):
        return self.MockStream(self)


# ────────────────────────────────────────────────────────
# テストケース
# ────────────────────────────────────────────────────────

def test_processor_init_and_mood_settings(tmp_path):
    """初期化とムード設定取得のテスト"""
    output_dir = tmp_path / "video_out"
    processor = VideoProcessor(output_dir=str(output_dir))
    
    assert processor.output_dir == output_dir
    assert output_dir.exists()
    
    # ムード設定の取得
    settings = processor.get_mood_settings("elegant")
    assert settings.name == "エレガント"
    
    settings_upper = processor.get_mood_settings("DYNAMIC")
    assert settings_upper.name == "ダイナミック"
    
    settings_invalid = processor.get_mood_settings("invalid_mood")
    assert settings_invalid.name == "エレガント"  # デフォルトにフォールバック


def test_task_creation_and_retrieval(tmp_path):
    """タスク作成と取得のテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    task_id = "task_123"
    video_paths = ["video1.mp4", "video2.mp4"]
    
    task = processor.create_task(
        task_id=task_id,
        video_paths=video_paths,
        mood="dynamic",
        guest_assets=["logo.png"],
        output_name="my_output"
    )
    
    assert task.task_id == task_id
    assert task.video_paths == video_paths
    assert task.mood == "dynamic"
    assert task.guest_assets == ["logo.png"]
    assert task.output_name == "my_output"
    assert task.phase == ProcessingPhase.IDLE
    
    retrieved_task = processor.get_task(task_id)
    assert retrieved_task == task
    
    assert processor.get_task("nonexistent") is None


def test_record_soul_narrative(tmp_path):
    """Soul Narrative 記録機能のテスト（正常系と例外系）"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    settings = MOOD_SETTINGS["elegant"]
    
    # 1. 正常系：新規作成（ファイルが存在しない場合）
    with patch("archive_video_processor.Path.exists", return_value=False), \
         patch("builtins.open", mock_open()) as m_open:
        
        processor._record_soul_narrative("task_001", "out_001", settings, 3)
        
        m_open.assert_called_once()
        handle = m_open()
        written_data = "".join([call.args[0] for call in handle.write.call_args_list if call.args])
        parsed = json.loads(written_data)
        assert len(parsed["entries"]) == 1
        assert parsed["entries"][0]["task_id"] == "task_001"

    # 2. 正常系：追記（既存ログファイルが存在する場合）
    initial_json = json.dumps({"entries": [{"task_id": "task_old"}]})
    with patch("archive_video_processor.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=initial_json)) as m_open:
        
        processor._record_soul_narrative("task_new", "out_new", settings, 3)
        
        handle = m_open()
        written_data = "".join([call.args[0] for call in handle.write.call_args_list if call.args])
        parsed = json.loads(written_data)
        assert len(parsed["entries"]) == 2
        assert parsed["entries"][0]["task_id"] == "task_old"
        assert parsed["entries"][1]["task_id"] == "task_new"

    # 3. 件数制限のテスト（最大10件）
    ten_entries = [{"task_id": f"task_{i}"} for i in range(10)]
    initial_json_10 = json.dumps({"entries": ten_entries})
    with patch("archive_video_processor.Path.exists", return_value=True), \
         patch("builtins.open", mock_open(read_data=initial_json_10)) as m_open:
        
        processor._record_soul_narrative("task_new", "out_new", settings, 3)
        
        handle = m_open()
        written_data = "".join([call.args[0] for call in handle.write.call_args_list if call.args])
        parsed = json.loads(written_data)
        assert len(parsed["entries"]) == 10
        assert parsed["entries"][0]["task_id"] == "task_1"
        assert parsed["entries"][-1]["task_id"] == "task_new"

    # 4. 例外系のテスト（OSError をスロー）
    with patch("archive_video_processor.Path.exists", return_value=False), \
         patch("builtins.open", mock_open()), \
         patch("json.dump", side_effect=OSError("mock error")):
        # 内部でキャッチされ、クラッシュしないこと
        processor._record_soul_narrative("task_err", "out_err", settings, 1)


@patch("time.sleep", return_value=None)  # テスト高速化のために sleep をスキップ
def test_process_video_success(mock_sleep, tmp_path):
    """動画処理の正常系テスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # テスト用のダミー動画ファイルを準備
    video1 = tmp_path / "video1.mp4"
    video2 = tmp_path / "video2.mp4"
    video1.write_text("dummy")
    video2.write_text("dummy")
    
    task_id = "task_success_123"
    task = processor.create_task(
        task_id=task_id,
        video_paths=[str(video1), str(video2)],
        mood="dynamic",
        output_name="final_output"
    )
    
    # 進捗コールバックの設定
    progress_calls = []
    def progress_cb(t):
        progress_calls.append((t.phase, t.progress, t.current_step))
    processor.set_progress_callback(progress_cb)
    
    # branding/logos/brand_logo.png の存在モックのために Path をパッチ
    with patch("archive_video_processor.Path.exists", return_value=True), \
         patch.object(processor, "_run_ffmpeg", return_value=True) as mock_run, \
         patch.object(processor, "_record_soul_narrative") as mock_record:
         
        success = processor.process_video(task_id)
        
        assert success is True
        assert task.phase == ProcessingPhase.COMPLETE
        assert task.progress == 100
        assert task.output_path == str(tmp_path / f"final_output_{task_id[:8]}.mp4")
        assert task.preview_url == f"/api/video/preview/{task_id}"
        
        # 進捗コールバックが複数回呼ばれていること
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == ProcessingPhase.COMPLETE
        
        # 各FFmpeg処理（シーン処理×2、マージ、ブランディング）が呼び出されていること
        assert mock_run.call_count == 4
        mock_record.assert_called_once()


@patch("time.sleep", return_value=None)
def test_process_video_demo_fallback(mock_sleep, tmp_path):
    """動画ファイルが存在しない場合のデモ動画フォールバックのテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # glob が返すデモファイルを物理的に作成しておく
    demo1 = tmp_path / "demo_1.mp4"
    demo2 = tmp_path / "demo_2.mp4"
    demo1.write_text("demo1")
    demo2.write_text("demo2")
    
    task_id = "task_demo_123"
    task = processor.create_task(
        task_id=task_id,
        video_paths=["nonexistent_1.mp4"],
        mood="elegant"
    )
    
    # パス解決と exists のモック
    def mock_exists(self):
        # 必要なファイルが「存在する」と判定されるようにする
        path_str = str(self)
        if "raw_videos" in path_str or "demo_" in path_str or "scene_" in path_str or "merged_" in path_str or "output_" in path_str or "final_" in path_str or "branding" in path_str:
            return True
        return False
        
    def mock_glob(self, pattern):
        # 物理的に作成したダミーファイルのパスを返す
        return [demo1, demo2]
        
    with patch("archive_video_processor.Path.exists", mock_exists), \
         patch("archive_video_processor.Path.glob", mock_glob), \
         patch.object(processor, "_run_ffmpeg", return_value=True), \
         patch.object(processor, "_record_soul_narrative"):
         
        success = processor.process_video(task_id)
        assert success is True
        assert task.phase == ProcessingPhase.COMPLETE


def test_process_video_task_not_found(tmp_path):
    """存在しないタスクIDに対する処理テスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    success = processor.process_video("nonexistent")
    assert success is False


@patch("time.sleep", return_value=None)
def test_process_video_failure(mock_sleep, tmp_path):
    """動画処理のエラーハンドリングテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    video1 = tmp_path / "video1.mp4"
    video1.write_text("dummy")
    
    task_id = "task_fail_123"
    task = processor.create_task(
        task_id=task_id,
        video_paths=[str(video1)],
        mood="elegant"
    )
    
    # _process_scene で意図的に例外を投げる
    with patch.object(processor, "_process_scene", side_effect=RuntimeError("FFmpeg error")):
        success = processor.process_video(task_id)
        
        assert success is False
        assert task.phase == ProcessingPhase.ERROR
        assert "FFmpeg error" in task.error
        assert task.current_step == "エラー: FFmpeg error"


def test_run_ffmpeg_realtime_progress(tmp_path):
    """FFmpegコマンド実行時のリアルタイム進捗更新の検証"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    task = processor.create_task("task_progress", ["v.mp4"], "elegant")
    
    # 進捗通知コールバック
    progress_calls = []
    processor.set_progress_callback(lambda t: progress_calls.append(t.progress))
    
    # 擬似的な FFmpeg ログストリーム
    ffmpeg_logs = [
        "Input #0, mov,mp4,m4a,3gp,3g2,mj2\n",
        "  Duration: 00:01:40.00, start: 0.000000, bitrate: 1204 kb/s\n",
        "Stream mapping:\n",
        "frame=   50 fps=0.0 q=0.0 size=       0kB time=00:00:10.00 bitrate=   0.0kbits/s speed=   0x\n",
        "frame=  100 fps=50.0 q=28.0 size=     256kB time=00:00:50.00 bitrate=  41.0kbits/s speed=   1x\n",
        "frame=  200 fps=60.0 q=-1.0 size=    1024kB time=00:01:40.00 bitrate=  81.9kbits/s speed=1.2x\n",
    ]
    
    mock_process = SafeMockProcess(lines=ffmpeg_logs)
    
    with patch("subprocess.Popen", return_value=mock_process), \
         patch("time.time", side_effect=[100.0, 100.0, 101.1, 101.1, 102.2, 102.2, 103.3, 103.3, 104.4, 104.4, 105.5]):
         
        # _run_ffmpeg の実行
        success = processor._run_ffmpeg(
            cmd=["ffmpeg", "-y"],
            description="Test progress",
            task=task,
            base_progress=10,
            progress_range=20
        )
        
        assert success is True
        # 進捗が 10% (00:00:10.00 -> 10%), 20% (00:00:50.00 -> 50%), 30% (00:01:40.00 -> 100%) のように更新されていること
        assert len(progress_calls) > 0
        assert max(progress_calls) <= 30


def test_run_ffmpeg_timeout(tmp_path):
    """FFmpegコマンド実行時のタイムアウトハンドリングテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # タイムアウトを発生させるプロセスモック
    mock_process = SafeMockProcess(should_timeout=True)
    
    with patch("subprocess.Popen", return_value=mock_process):
        success = processor._run_ffmpeg(
            cmd=["ffmpeg"],
            description="Timeout test",
            timeout=1
        )
        assert success is False
        assert mock_process.kill_called is True


def test_run_ffmpeg_generic_error(tmp_path):
    """FFmpegコマンド実行時のその他の例外ハンドリングテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # Popen実行時に OSError をスローさせる
    with patch("subprocess.Popen", side_effect=OSError("Permission denied")):
        success = processor._run_ffmpeg(
            cmd=["ffmpeg"],
            description="Error test"
        )
        assert success is False


def test_run_ffmpeg_non_zero_exit(tmp_path):
    """FFmpegコマンド実行時に非ゼロの終了コードを返した場合のハンドリングテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # 終了コード 1 のプロセスモック
    mock_process = SafeMockProcess(returncode=1)
    
    with patch("subprocess.Popen", return_value=mock_process):
        success = processor._run_ffmpeg(
            cmd=["ffmpeg"],
            description="Non-zero exit test"
        )
        assert success is False


def test_process_scene_fallback_copy(tmp_path):
    """FFmpeg失敗時に shutil.copy にフォールバックするテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    input_file.write_text("input video data")
    
    settings = MOOD_SETTINGS["elegant"]
    
    # _run_ffmpeg が失敗を返すようにモック
    with patch.object(processor, "_run_ffmpeg", return_value=False), \
         patch("shutil.copy", wraps=shutil.copy) as mock_copy:
         
        processor._process_scene(str(input_file), str(output_file), settings)
        
        # フォールバックとしてコピー処理が行われていること
        mock_copy.assert_called_once_with(str(input_file), str(output_file))
        assert output_file.exists()
        assert output_file.read_text() == "input video data"


def test_process_scene_fallback_copy_error(tmp_path):
    """フォールバックコピーも失敗した場合のエラーハンドリングテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    # _run_ffmpeg 失敗かつ shutil.copy がエラーを投げる
    with patch.object(processor, "_run_ffmpeg", return_value=False), \
         patch("shutil.copy", side_effect=shutil.Error("disk full")):
         
        # 例外が内部でキャッチされ、クラッシュしないこと
        processor._process_scene("in.mp4", "out.mp4", MOOD_SETTINGS["elegant"])


def test_process_scene_no_color_filter(tmp_path):
    """カラープリセットがない場合のシーン処理テスト（else分岐カバー）"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    input_file.write_text("input video data")
    
    # color_preset が存在しない値（""）に設定されたカスタム MoodSettings を用意
    settings = MoodSettings(
        name="カスタム",
        color_preset="",  # 空文字列にしてカラーフィルタを適用しない
        transition="fade",
        music_style="classical",
        telop_style="minimal"
    )
    
    with patch.object(processor, "_run_ffmpeg", return_value=True) as mock_run:
        processor._process_scene(str(input_file), str(output_file), settings)
        
        mock_run.assert_called_once()
        called_cmd = mock_run.call_args[0][0]
        vf_idx = called_cmd.index("-vf")
        assert called_cmd[vf_idx + 1] == "scale=1280:720"  # カラーフィルタなし


def test_merge_scenes_single_scene(tmp_path):
    """シーンが1つの場合にコピー処理を行うテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    scene = tmp_path / "scene1.mp4"
    scene.write_text("scene data")
    
    output = tmp_path / "merged.mp4"
    
    # shutil.copy と実際の return 405 を検証
    with patch("shutil.copy", wraps=shutil.copy) as mock_copy:
        res = processor._merge_scenes([str(scene)], str(output))
        assert res is None
        mock_copy.assert_called_once_with(str(scene), str(output))
        assert output.read_text() == "scene data"


def test_merge_scenes_no_scenes(tmp_path):
    """有効なシーンが存在しない場合のテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    processor._merge_scenes([], "merged.mp4")
    # 例外を出さずに終了すること


def test_merge_scenes_multiple_scenes_fallback(tmp_path):
    """複数シーンのマージに失敗した際に、最初のシーンをコピーするフォールバックテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    scene1 = tmp_path / "scene1.mp4"
    scene2 = tmp_path / "scene2.mp4"
    scene1.write_text("scene 1 data")
    scene2.write_text("scene 2 data")
    
    output = tmp_path / "merged.mp4"
    
    # _run_ffmpeg が失敗を返す
    with patch.object(processor, "_run_ffmpeg", return_value=False), \
         patch("shutil.copy", wraps=shutil.copy) as mock_copy:
         
        processor._merge_scenes([str(scene1), str(scene2)], str(output))
        
        # フォールバックとして最初のシーンがコピーされていること
        mock_copy.assert_called_once_with(str(scene1), str(output))
        assert output.read_text() == "scene 1 data"


def test_apply_branding_no_logo(tmp_path):
    """ブランドロゴ画像が存在しない場合に、ロゴ適用をスキップしてコピーするテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    input_file.write_text("source video data")
    
    settings = MOOD_SETTINGS["elegant"]
    
    # ロゴ画像が存在しない (Path.exists が False を返す)
    with patch("archive_video_processor.Path.exists", return_value=False), \
         patch("shutil.copy", wraps=shutil.copy) as mock_copy:
         
        processor._apply_branding(str(input_file), str(output_file), settings)
        
        mock_copy.assert_called_once_with(str(input_file), str(output_file))
        assert output_file.read_text() == "source video data"


def test_apply_branding_fallback(tmp_path):
    """ロゴ適用処理 (FFmpeg) が失敗した場合に、ブランディングなしでコピーするフォールバックテスト"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    
    input_file = tmp_path / "input.mp4"
    output_file = tmp_path / "output.mp4"
    input_file.write_text("source video data")
    
    settings = MOOD_SETTINGS["elegant"]
    
    # ロゴ画像は存在するが、FFmpeg実行が失敗する
    with patch("archive_video_processor.Path.exists", return_value=True), \
         patch.object(processor, "_run_ffmpeg", return_value=False), \
         patch("shutil.copy", wraps=shutil.copy) as mock_copy:
         
        processor._apply_branding(str(input_file), str(output_file), settings)
        
        mock_copy.assert_called_once_with(str(input_file), str(output_file))
        assert output_file.read_text() == "source video data"


def test_process_video_demo_loop_exhausted(tmp_path):
    """デモ動画の探索ループがbreakせずに終了するケースのテスト (219->226, 220->219, 222->219 分岐カバー)"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    task_id = "task_demo_exhausted"
    task = processor.create_task(
        task_id=task_id,
        video_paths=["nonexistent_input.mp4"],
        mood="elegant"
    )
    
    exists_calls = []
    
    def mock_exists(self_path):
        path_str = str(self_path)
        if "evolution_log" in path_str or "temp" in path_str or "video_output" in path_str:
            return True
        if "AI Studio" in path_str:
            exists_calls.append(path_str)
            if len(exists_calls) == 2:
                return True
            return False
        return False
        
    def mock_glob(self_path, pattern):
        return []
        
    with patch("archive_video_processor.Path.exists", mock_exists),          patch("archive_video_processor.Path.glob", mock_glob),          patch.object(processor, "_run_ffmpeg", return_value=True),          patch.object(processor, "_record_soul_narrative"):
         
        success = processor.process_video(task_id)
        assert success is False
        assert task.phase == ProcessingPhase.ERROR


def test_merge_scenes_failure_no_valid_scenes(tmp_path):
    """シーンマージに失敗し、かつ有効なシーンが存在しない場合のテスト (465->exit 分岐カバー)"""
    processor = VideoProcessor(output_dir=str(tmp_path))
    output_path = tmp_path / "merged_output.mp4"
    
    scene_paths = [str(tmp_path / "nonexistent_scene.mp4")]
    
    with patch.object(processor, "_run_ffmpeg", return_value=False),          patch("shutil.copy") as mock_copy:
         
        processor._merge_scenes(scene_paths, str(output_path))
        
        mock_copy.assert_not_called()


def test_mood_settings_tempo_property():
    """MoodSettings の tempo プロパティが正しく追加・取得できることを検証"""
    settings_elegant = MOOD_SETTINGS["elegant"]
    assert settings_elegant.tempo == "slow"
    
    settings_dynamic = MOOD_SETTINGS["dynamic"]
    assert settings_dynamic.tempo == "fast"
    
    settings_dramatic = MOOD_SETTINGS["dramatic"]
    assert settings_dramatic.tempo == "normal"
    
    # デフォルト値の検証
    custom_settings = MoodSettings(
        name="カスタム",
        color_preset="warm",
        transition="fade",
        music_style="jazz",
        telop_style="retro"
    )
    assert custom_settings.tempo == "normal"
