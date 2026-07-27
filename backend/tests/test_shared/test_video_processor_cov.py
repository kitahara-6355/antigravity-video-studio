"""
video_processor.py のカバレッジ向上およびエッジケース検証テスト
"""

import pytest
from unittest.mock import patch, MagicMock, mock_open, PropertyMock
from pathlib import Path
import json
import time
import subprocess
import shutil

from video_processor import (
    VideoProcessor,
    ProcessingTask,
    ProcessingPhase,
    MoodSettings,
    MOOD_SETTINGS
)

# ============================================================
# 1. 基本メソッドと状態管理のテスト
# ============================================================

def test_vp_notify_progress():
    """_notify_progress の動作確認"""
    vp = VideoProcessor()
    task = ProcessingTask(task_id="t_notify", video_paths=[], mood="elegant")
    
    # コールバックが設定されていない状態
    vp._notify_progress(task)
    
    # コールバックが設定されている状態
    cb = MagicMock()
    vp.set_progress_callback(cb)
    vp._notify_progress(task)
    cb.assert_called_once_with(task)


def test_vp_get_mood_settings():
    """get_mood_settings のフォールバックと大文字小文字処理"""
    vp = VideoProcessor()
    
    # 正常系 (大文字小文字)
    settings = vp.get_mood_settings("ElEgAnT")
    assert settings.name == "エレガント"
    
    # 存在しないムードの場合は elegant にフォールバック
    settings_fallback = vp.get_mood_settings("unknown_mood")
    assert settings_fallback.name == "エレガント"


def test_vp_get_task():
    """get_task と create_task の連携"""
    vp = VideoProcessor()
    task = vp.create_task(
        task_id="t_get",
        video_paths=["/path/to/v1.mp4"],
        mood="dynamic",
        guest_assets=["/path/to/g1.png"],
        output_name="my_output"
    )
    
    assert vp.get_task("t_get") == task
    assert vp.get_task("non_existing") is None


# ============================================================
# 2. Soul Narrative 記録機能のテスト
# ============================================================

def test_vp_record_soul_narrative_no_existing(tmp_path):
    """evolution_log.json が存在しない場合の新規作成"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    # brandingフォルダの evolution_log.json のパスをモック
    log_dir = tmp_path / "branding"
    log_dir.mkdir()
    
    with patch("video_processor.Path") as mock_path:
        # パス構築時の division 演算子に対応
        mock_instance = MagicMock()
        mock_instance.exists.return_value = False
        mock_instance.parent = log_dir
        
        # openのモック
        m_open = mock_open()
        
        # Path() の呼び出しで mock_instance を返す
        mock_path.return_value = mock_instance
        # Path / 'branding' / 'evolution_log.json' などの連鎖に対応
        mock_instance.__truediv__.return_value = mock_instance
        
        with patch("video_processor.open", m_open):
            vp._record_soul_narrative("t_soul", "out_name", settings, 3)
            
        # 書き込みが行われたことを検証
        m_open.assert_called_once()
        args, kwargs = m_open.call_args
        assert str(args[0]).endswith("evolution_log.json")
        assert args[1] == 'w'
        assert kwargs.get('encoding') == 'utf-8'
        
        # 書込みデータをキャプチャ
        handle = m_open()
        written_data = "".join([call.args[0] for call in handle.write.call_args_list])
        log_data = json.loads(written_data)
        assert "entries" in log_data
        assert len(log_data["entries"]) == 1
        assert log_data["entries"][0]["task_id"] == "t_soul"


def test_vp_record_soul_narrative_with_existing(tmp_path):
    """existing ログが存在し、10件制限でトリムされる場合の挙動"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["dynamic"]
    
    # 既存の12件のエントリを用意
    existing_entries = [{"task_id": f"t_{i}", "timestamp": time.time()} for i in range(12)]
    existing_log = {"entries": existing_entries, "philosophies": []}
    existing_content = json.dumps(existing_log)
    
    with patch("video_processor.Path") as mock_path:
        mock_instance = MagicMock()
        mock_instance.exists.return_value = True
        
        # 読込み用と書込み用のモック
        m_open = mock_open(read_data=existing_content)
        
        mock_path.return_value = mock_instance
        mock_instance.__truediv__.return_value = mock_instance
        
        with patch("video_processor.open", m_open):
            vp._record_soul_narrative("t_new", "out_name", settings, 2)
            
        # 10件にトリムされ、新エントリが追加されて最終的に10件になっているか検証
        handle = m_open()
        
        # 書き込みデータを検索
        write_calls = [call.args[0] for call in handle.write.call_args_list if call.args]
        written_data = "".join(write_calls)
        log_data = json.loads(written_data)
        assert len(log_data["entries"]) == 10
        # 最新のエントリが追加されているか
        assert log_data["entries"][-1]["task_id"] == "t_new"


def test_vp_record_soul_narrative_exception():
    """例外が発生した際に例外がキャッチされ、ハングやクラッシュが起きないこと"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["dramatic"]
    
    with patch("video_processor.Path") as mock_path:
        mock_instance = MagicMock()
        mock_path.return_value = mock_instance
        mock_instance.__truediv__.return_value = mock_instance
        
        # openで強制的に例外を発生させる
        with patch("video_processor.open", side_effect=IOError("Permission denied")):
            # 例外が内部でキャッチされるため、エラーにならずに正常終了すること
            vp._record_soul_narrative("t_fail", "out_name", settings, 1)


# ============================================================
# 3. FFmpeg 実行ラッパー (_run_ffmpeg) のテスト
# ============================================================

def test_vp_run_ffmpeg_success(safe_popen_mock):
    """_run_ffmpeg の正常終了ルート (poll=0)"""
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=0)
    
    with patch("subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg", "-version"], "Check Version")
        assert success is True


def test_vp_run_ffmpeg_failure(safe_popen_mock):
    """_run_ffmpeg のエラー終了ルート (poll=1)"""
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=1, stderr_text="FFmpeg custom error")
    
    with patch("subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg", "-invalid"], "Invalid Cmd")
        assert success is False


def test_vp_run_ffmpeg_timeout(safe_popen_mock):
    """_run_ffmpeg のタイムアウト例外ハンドリング"""
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=0)
    # waitメソッドで TimeoutExpired を投げる
    proc.wait.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=10)
    
    with patch("subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg"], "Timeout Run", timeout=10)
        assert success is False
        proc.kill.assert_called_once()


def test_vp_run_ffmpeg_general_exception(safe_popen_mock):
    """_run_ffmpeg の一般的な例外ハンドリング"""
    vp = VideoProcessor()
    proc = safe_popen_mock(returncode=0)
    # Popen モック安全規約: 最初の wait() で例外を発生させ、finally/except での kill/wait は正常終了させる
    proc.wait.side_effect = [Exception("System error"), None]
    
    with patch("subprocess.Popen", return_value=proc):
        success = vp._run_ffmpeg(["ffmpeg"], "Exception Run")
        assert success is False


# ============================================================
# 4. 音声・映像フィルタのテスト
# ============================================================

def test_vp_get_color_filter():
    """_get_color_filter の全プリセット動作検証"""
    vp = VideoProcessor()
    
    # 存在する全プリセット
    presets = ["warm", "vibrant", "cinematic", "cool", "energetic", "calm", "elegant"]
    for p in presets:
        settings = MoodSettings(name="test", color_preset=p, transition="", music_style="", telop_style="")
        assert vp._get_color_filter(settings) != ""
        
    # 存在しないプリセット
    settings_unknown = MoodSettings(name="test", color_preset="unknown", transition="", music_style="", telop_style="")
    assert vp._get_color_filter(settings_unknown) == ""


def test_vp_get_audio_normalize_args_2pass():
    """_get_audio_normalize_args で Pass 1 のJSON解析に成功して Pass 2 引数を返すルート"""
    vp = VideoProcessor()
    
    # Pass 1 ffmpeg 実行用のモック
    mock_run_result = MagicMock()
    mock_run_result.stderr = """
    some warnings or logs
    [parsed_loudnorm_0 @ 0000021c3b1a4180] 
    {
        "input_i" : "-18.52",
        "input_lra" : "4.21",
        "input_tp" : "-1.20",
        "input_thresh" : "-28.92",
        "output_i" : "-16.12",
        "output_lra" : "3.10",
        "output_tp" : "-1.00",
        "output_thresh" : "-26.50",
        "normalization_type" : "dynamic",
        "target_offset" : "0.12"
    }
    """
    
    with patch("subprocess.run", return_value=mock_run_result):
        args = vp._get_audio_normalize_args("/path/to/video.mp4")
        assert len(args) == 2
        assert args[0] == "-af"
        assert "measured_I=-18.52" in args[1]
        assert "measured_LRA=4.21" in args[1]


def test_vp_get_audio_normalize_args_1pass_fallback():
    """_get_audio_normalize_args で Pass 1 解析に失敗し 1パスにフォールバックするルート"""
    vp = VideoProcessor()
    
    # JSONが出力に含まれない場合
    mock_run_result = MagicMock()
    mock_run_result.stderr = "FFmpeg errors without JSON output"
    
    with patch("subprocess.run", return_value=mock_run_result):
        args = vp._get_audio_normalize_args("/path/to/video.mp4")
        assert len(args) == 2
        assert args[0] == "-af"
        assert "loudnorm=I=" in args[1]  # デフォルトの1パスフィルター
        assert "measured_i" not in args[1]


def test_vp_get_audio_normalize_args_exception():
    """_get_audio_normalize_args で例外が発生した際に空の引数リストを返すルート"""
    vp = VideoProcessor()
    
    # 例外を投げるモック
    with patch("subprocess.run", side_effect=Exception("FFmpeg not found")):
        args = vp._get_audio_normalize_args("/path/to/video.mp4")
        assert args == []


# ============================================================
# 5. 各種動画編集機能 (_process_scene, _merge_scenes, _apply_branding) のテスト
# ============================================================

def test_vp_process_scene_success():
    """_process_scene の正常ルート"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch.object(vp, "_get_audio_normalize_args", return_value=["-af", "loudnorm"]):
        with patch.object(vp, "_run_ffmpeg", return_value=True) as mock_run:
            vp._process_scene("in.mp4", "out.mp4", settings)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "ffmpeg" in cmd
            assert "-vf" in cmd
            assert "scale=1280:720" in "".join(cmd)


def test_vp_process_scene_ffmpeg_fail_copy_success():
    """_process_scene の FFmpeg 失敗時 shutil.copy フォールバック成功ルート"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch.object(vp, "_run_ffmpeg", return_value=False):
        with patch("shutil.copy") as mock_copy:
            vp._process_scene("in.mp4", "out.mp4", settings)
            mock_copy.assert_called_once_with("in.mp4", "out.mp4")


def test_vp_process_scene_copy_fail_exception():
    """_process_scene の FFmpeg 失敗・shutil.copy も失敗時の例外ハンドリング"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch.object(vp, "_run_ffmpeg", return_value=False):
        with patch("shutil.copy", side_effect=OSError("Disk full")):
            # 例外がキャッチされ、クラッシュしないことを確認
            vp._process_scene("in.mp4", "out.mp4", settings)


def test_vp_merge_scenes_no_scenes():
    """_merge_scenes でシーンが0件の場合"""
    vp = VideoProcessor()
    with patch.object(vp, "_run_ffmpeg") as mock_run:
        vp._merge_scenes([], "out.mp4")
        mock_run.assert_not_called()


def test_vp_merge_scenes_single_scene():
    """_merge_scenes でシーンが1件の場合 (単純コピー)"""
    vp = VideoProcessor()
    
    # ファイル存在確認をTrueにする
    with patch("pathlib.Path.exists", return_value=True):
        with patch("shutil.copy") as mock_copy:
            with patch.object(vp, "_run_ffmpeg") as mock_run:
                vp._merge_scenes(["scene1.mp4"], "out.mp4")
                mock_copy.assert_called_once_with("scene1.mp4", "out.mp4")
                mock_run.assert_not_called()


def test_vp_merge_scenes_multiple_scenes_success():
    """_merge_scenes で複数シーンの結合 (正常系)"""
    vp = VideoProcessor()
    
    with patch("pathlib.Path.exists", return_value=True):
        m_open = mock_open()
        with patch("video_processor.open", m_open):
            with patch.object(vp, "_run_ffmpeg", return_value=True) as mock_run:
                vp._merge_scenes(["s1.mp4", "s2.mp4"], "out.mp4")
                mock_run.assert_called_once()
                # concat用ファイル書込みが行われたか検証
                m_open.assert_called_with(vp.output_dir / "concat_list.txt", "w", encoding="utf-8")


def test_vp_merge_scenes_multiple_scenes_fail_fallback():
    """_merge_scenes で複数シーン結合が失敗した際のフォールバック (最初シーンコピー)"""
    vp = VideoProcessor()
    
    with patch("pathlib.Path.exists", return_value=True):
        m_open = mock_open()
        with patch("video_processor.open", m_open):
            with patch.object(vp, "_run_ffmpeg", return_value=False):
                with patch("shutil.copy") as mock_copy:
                    vp._merge_scenes(["s1.mp4", "s2.mp4"], "out.mp4")
                    mock_copy.assert_called_once_with("s1.mp4", "out.mp4")


def test_vp_apply_branding_no_logo():
    """_apply_branding でロゴファイルが存在しない場合のコピーフォールバック"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch("pathlib.Path.exists", return_value=False):
        with patch("shutil.copy") as mock_copy:
            vp._apply_branding("in.mp4", "out.mp4", settings)
            mock_copy.assert_called_once_with("in.mp4", "out.mp4")


def test_vp_apply_branding_with_logo_success():
    """_apply_branding でロゴが存在し FFmpeg 処理成功ルート"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch("pathlib.Path.exists", return_value=True):
        with patch.object(vp, "_run_ffmpeg", return_value=True) as mock_run:
            vp._apply_branding("in.mp4", "out.mp4", settings)
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            cmd_str = "".join(cmd)
            assert "-filter_complex" in cmd_str
            assert "overlay" in cmd_str


def test_vp_apply_branding_with_logo_fail_fallback():
    """_apply_branding でロゴが存在するが FFmpeg が失敗した際のコピーフォールバック"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    with patch("pathlib.Path.exists", return_value=True):
        with patch.object(vp, "_run_ffmpeg", return_value=False):
            with patch("shutil.copy") as mock_copy:
                vp._apply_branding("in.mp4", "out.mp4", settings)
                mock_copy.assert_called_once_with("in.mp4", "out.mp4")


# ============================================================
# 6. process_video ワークフロー全体のテスト
# ============================================================

def test_vp_process_video_workflow_success():
    """process_video ワークフロー全体の正常系シミュレーション"""
    vp = VideoProcessor()
    task = vp.create_task(
        task_id="t_workflow_ok",
        video_paths=["/path/to/v1.mp4", "/path/to/v2.mp4"],
        mood="elegant"
    )
    
    # 各処理をモック
    with patch("pathlib.Path.exists", return_value=True):
        with patch.object(vp, "_process_scene") as mock_scene:
            with patch.object(vp, "_merge_scenes") as mock_merge:
                with patch.object(vp, "_apply_branding") as mock_brand:
                    with patch.object(vp, "_record_soul_narrative") as mock_soul:
                        success = vp.process_video(task.task_id)
                        
                        assert success is True
                        assert task.phase == ProcessingPhase.COMPLETE
                        assert task.progress == 100
                        assert task.error is None
                        
                        # 内部ステップの呼び出し回数などを検証
                        assert mock_scene.call_count == 2
                        mock_merge.assert_called_once()
                        mock_brand.assert_called_once()
                        mock_soul.assert_called_once()


def test_vp_process_video_workflow_demo_glob():
    """素材ファイルが存在せず、デモ用動画フォルダを glob するルートのシミュレーション"""
    vp = VideoProcessor()
    task = vp.create_task(
        task_id="t_workflow_demo",
        video_paths=["/non_existing_file.mp4"],
        mood="dynamic"
    )
    
    # パスチェック用の exists() を最初の1回(タスクの動画パス)は False を返し、
    # その後のデモフォルダ確認では True を返すように設定
    exists_results = [False, True]  # /non_existing_file.mp4 -> False, デモフォルダ -> True
    
    # glob結果をモック
    mock_glob_path = MagicMock()
    mock_glob_path.glob.return_value = [Path("demo1.mp4"), Path("demo2.mp4")]
    
    def exists_side_effect(self, *args, **kwargs):
        if "non_existing_file" in str(self):
            return False
        return True
        
    with patch("pathlib.Path.exists", exists_side_effect):
        with patch("pathlib.Path.glob", return_value=[Path("demo1.mp4"), Path("demo2.mp4")]):
            with patch.object(vp, "_process_scene") as mock_scene:
                with patch.object(vp, "_merge_scenes") as mock_merge:
                    with patch.object(vp, "_apply_branding") as mock_brand:
                        with patch.object(vp, "_record_soul_narrative") as mock_soul:
                            success = vp.process_video(task.task_id)
                            
                            assert success is True
                            assert task.phase == ProcessingPhase.COMPLETE
                            assert mock_scene.call_count == 2


def test_vp_process_video_workflow_exception():
    """process_video 中に例外が発生した際のエラーフェーズ移行"""
    vp = VideoProcessor()
    task = vp.create_task(
        task_id="t_workflow_fail",
        video_paths=["/path/to/v1.mp4"],
        mood="elegant"
    )
    
    with patch("pathlib.Path.exists", return_value=True):
        # 最初のシーン処理で例外を発生させる
        with patch.object(vp, "_process_scene", side_effect=RuntimeError("FFmpeg path not configured")):
            success = vp.process_video(task.task_id)
            
            assert success is False
            assert task.phase == ProcessingPhase.ERROR
            assert "FFmpeg path not configured" in task.error
            assert task.current_step.startswith("エラー:")


def test_vp_process_video_non_existing_task():
    """存在しないタスクIDを指定して process_video を実行した場合の戻り値"""
    vp = VideoProcessor()
    success = vp.process_video("non_existent_task_id")
    assert success is False


# ============================================================
# 7. template_config およびカラーフィルタ無しルートのテスト
# ============================================================

def test_vp_process_scene_template_and_no_filter():
    """template_config が active でカラーフィルタを返すルート、カラーフィルタが無いルート、および例外ルートをカバー (447-451, 463行)"""
    vp = VideoProcessor()
    settings = MOOD_SETTINGS["elegant"]
    
    # 1. template_config が active で get_color_grading_filter が値を返すケース (447-449行目)
    mock_template = MagicMock()
    mock_template.is_active = True
    mock_template.get_color_grading_filter.return_value = "eq=contrast=1.5"
    mock_template.template_id = "test_template"
    
    with patch.object(vp, "_get_audio_normalize_args", return_value=["-af", "loudnorm"]):
        with patch("template_config.template_config", mock_template):
            with patch.object(vp, "_run_ffmpeg", return_value=True) as mock_run:
                vp._process_scene("in.mp4", "out.mp4", settings)
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                assert "eq=contrast=1.5" in "".join(cmd)

        # 2. get_color_grading_filter が空を返し、かつ _get_color_filter(settings) も空を返すケース (463行目)
        mock_template.get_color_grading_filter.return_value = ""
        # settings の color_preset に存在しないものを指定して _get_color_filter が空を返すようにする
        settings_no_filter = MoodSettings(name="test", color_preset="unknown", transition="", music_style="", telop_style="")
        with patch("template_config.template_config", mock_template):
            with patch.object(vp, "_run_ffmpeg", return_value=True) as mock_run:
                vp._process_scene("in.mp4", "out.mp4", settings_no_filter)
                mock_run.assert_called_once()
                cmd = mock_run.call_args[0][0]
                # video_filter = base_filter (463行目) なので、scale=1280:720 のみ
                assert "-vf" in cmd
                vf_idx = cmd.index("-vf")
                assert cmd[vf_idx + 1] == "scale=1280:720"

        # 3. template_config アクセスで例外が発生するケース (450-451行目)
        mock_template_err = MagicMock()
        type(mock_template_err).is_active = PropertyMock(side_effect=RuntimeError("Config error"))
        with patch("template_config.template_config", mock_template_err):
            with patch.object(vp, "_run_ffmpeg", return_value=True):
                # 例外が発生してもキャッチされて正常に処理されること
                vp._process_scene("in.mp4", "out.mp4", settings)


def test_vp_run_ffmpeg_progress_tracking():
    """_run_ffmpeg 内の parse_progress 進捗解析スレッド処理を完全にカバーするテスト"""
    vp = VideoProcessor()
    task = ProcessingTask(task_id="t_progress", video_paths=[], mood="elegant")
    
    # 時間のモック値
    current_mock_time = 100.0
    
    def mock_time():
        nonlocal current_mock_time
        return current_mock_time

    # subprocess.Popen のモック
    mock_proc = MagicMock()
    mock_proc.returncode = 0  # 正常終了コードを設定
    
    # Popen モック安全規約: poll() は return_value=0 （または非 None）で即座に終了コードを返すこと
    mock_proc.poll.return_value = 0
    
    # readline() は空文字列 "" を返す（MagicMockの自動応答ハング防止）
    mock_proc.stderr.readline.return_value = ""
    
    # イテレーション用にジェネレータを設定
    def stderr_generator():
        nonlocal current_mock_time
        # Duration取得用に最初の行を出力
        yield "Duration: 00:00:10.00\n"
        # 1秒以上経過させて進捗更新をトリガー
        current_mock_time = 102.0
        yield "time=00:00:05.00\n"
        yield ""

    # stderr がイテレータとして動作するように `__iter__` をジェネレータにモック化
    mock_proc.stderr.__iter__.return_value = stderr_generator()
    
    with patch("subprocess.Popen", return_value=mock_proc), \
         patch("time.time", side_effect=mock_time):
        
        success = vp._run_ffmpeg(
            ["ffmpeg"],
            "Progress Run",
            task=task,
            base_progress=10,
            progress_range=10
        )
        
        assert success is True
        # 進捗が 10 + 5 = 15 % に更新されていることを確認
        assert task.progress == 15
        assert "Progress Run (50%)" in task.current_step

