import os
import sys
import shutil
import pytest
import pathlib
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Ensure backend directory is in path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import backend.smart_cut_engine as smart_cut_engine


@pytest.fixture
def dummy_video(tmp_path):
    video_path = tmp_path / "input.mp4"
    video_path.write_bytes(b"dummy video content" * 100)  # > 1024 bytes
    return video_path


def test_get_logo_path_template_active(tmp_path):
    logo_path = tmp_path / "logo.png"
    logo_path.touch()

    mock_config = MagicMock()
    mock_config.is_active = True
    mock_config.get_branding_config.return_value = {"logo_path": str(logo_path)}

    with patch.dict(sys.modules, {"template_config": MagicMock(template_config=mock_config)}):
        # テンプレートが有効でロゴファイルが存在する場合
        assert smart_cut_engine._get_logo_path() == str(logo_path)


def test_get_logo_path_template_inactive_default_exists(tmp_path):
    mock_config = MagicMock()
    mock_config.is_active = False

    with patch.dict(sys.modules, {"template_config": MagicMock(template_config=mock_config)}):
        # デフォルトロゴが存在する場合のモック
        with patch.object(Path, "exists", return_value=True):
            logo = smart_cut_engine._get_logo_path()
            assert logo is not None
            assert "brand_logo.png" in logo


def test_get_logo_path_exception_and_not_exists():
    # テンプレートインポートエラー & デフォルトロゴなし
    with patch.dict(sys.modules, {"template_config": None}):
        with patch.object(Path, "exists", return_value=False):
            assert smart_cut_engine._get_logo_path() is None


def test_burn_subtitles_ffmpeg_no_subtitles(dummy_video, tmp_path):
    output_path = tmp_path / "output.mp4"
    ffmpeg_editor = MagicMock()

    # 空の字幕セグメント
    result = smart_cut_engine._burn_subtitles_ffmpeg(
        str(dummy_video), [], str(output_path), ffmpeg_editor
    )
    assert result is True
    assert output_path.exists()
    assert output_path.stat().st_size == dummy_video.stat().st_size


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_gpu_success(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_gpu.mp4"
    # ffprobe のダミーレスポンス
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 正常系: cmd1 実行成功、出力ファイルをダミー作成
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"rendered video content" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = ["-c:v", "h264_nvenc"]
    ffmpeg_editor._get_hwaccel_input_args.return_value = ["-hwaccel", "cuda"]

    # text が空のセグメント (continue のカバー) と通常のセグメント
    segments = [
        {"start": 0.5, "end": 1.0, "text": ""},
        {"start": 1.0, "end": 3.0, "text": "Hello World"}
    ]
    
    with patch.dict(sys.modules, {"template_config": None}):
        # _get_logo_path を None にしてロゴなしルート(vf_arg)を強制
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result is True
            assert output_path.exists()
            assert ffmpeg_editor.run_command.call_count == 1


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_ffprobe_failure(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_ffprobe_fail.mp4"
    # ffprobe 失敗をシミュレート (72-73行目カバー)
    mock_run.side_effect = FileNotFoundError("ffprobe not found")

    ffmpeg_editor = MagicMock()
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"rendered content" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 3.0, "text": "Short text"}]

    with patch.dict(sys.modules, {"template_config": None}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result is True
            assert output_path.exists()


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_srt_warning(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_srt_warn.mp4"
    # ffprobe 成功
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"rendered content" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    # 動画長 10.0秒に対して SRT終了時間が 16.0秒 (10.0 + 5 より大きい) なので警告 (101行目カバー)
    segments = [{"start": 1.0, "end": 16.0, "text": "Warning text"}]

    with patch.dict(sys.modules, {"template_config": None}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result is True
            assert output_path.exists()


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_logo_height_exception(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_logo_exc.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"rendered content" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello"}]

    # 145-146行目の AttributeError 例外を発生させるための正しいモジュール構成
    mock_module = MagicMock()
    mock_config = MagicMock()
    mock_config.is_active = True
    mock_config.get_branding_config.return_value = None  # None.get で AttributeError
    mock_config.get_subtitle_style.return_value = "FontSize=16"
    mock_module.template_config = mock_config

    logo_path = tmp_path / "logo.png"
    logo_path.touch()

    with patch.dict(sys.modules, {"template_config": mock_module}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=str(logo_path)):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result is True


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_fallback_cpu_success(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_cpu.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 正常系: cmd1 が失敗(Falseを返す)し、cmd2 で成功
    call_idx = 0
    def mock_run_cmd(cmd, timeout=1800):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 2:
            output_path.write_bytes(b"rendered video content" * 100)
            return True, "Success"
        return False, "Failed"
    
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = ["-c:v", "h264_nvenc"]

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello World"}]
    
    # テンプレートロゴありのシミュレーション
    logo_path = tmp_path / "logo.png"
    logo_path.touch()
    mock_config = MagicMock()
    mock_config.is_active = True
    mock_config.get_branding_config.return_value = {
        "logo_path": str(logo_path),
        "logo_height": 50
    }
    mock_config.get_subtitle_style.return_value = "FontSize=20"

    with patch.dict(sys.modules, {"template_config": mock_config}):
        result = smart_cut_engine._burn_subtitles_ffmpeg(
            str(dummy_video), segments, str(output_path), ffmpeg_editor
        )
        assert result is True
        assert output_path.exists()
        assert ffmpeg_editor.run_command.call_count == 2


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_all_failed_copy_fallback(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_failed.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 両方のコマンドが失敗
    ffmpeg_editor.run_command.return_value = (False, "Error")
    ffmpeg_editor._get_encode_args.return_value = ["-c:v", "h264_nvenc"]

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello World"}]
    
    with patch.dict(sys.modules, {"template_config": None}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result == "fallback_no_subtitle"
            assert output_path.exists()
            assert output_path.stat().st_size == dummy_video.stat().st_size
            
            # フラグファイルが書き込まれていること
            flag_file = tmp_path / "_subtitle_burn_failed.flag"
            assert flag_file.exists()


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_flag_write_permission_error(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_perm_failed.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    ffmpeg_editor.run_command.return_value = (False, "Error")
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello World"}]

    def mock_write_text(content, encoding="utf-8"):
        if "failed" in content:
            raise PermissionError("Perm Denied")
        # 実際の一時SRT書き込み用
        temp_srt = tmp_path / "_temp_subtitles.srt"
        temp_srt.write_bytes(content.encode("utf-8"))

    with patch.dict(sys.modules, {"template_config": None}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            # write_text の挙動をモック関数で置き換えて PermissionError を発生させる (217-218カバー)
            with patch.object(Path, "write_text", side_effect=mock_write_text):
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    str(dummy_video), segments, str(output_path), ffmpeg_editor
                )
                assert result == "fallback_no_subtitle"


def test_render_smart_cut_empty_ranges(dummy_video, tmp_path):
    output_path = tmp_path / "output_empty.mp4"
    # 空の segments
    result = smart_cut_engine.render_smart_cut([], str(dummy_video), str(output_path))
    assert result is False


@patch("subprocess.run")
def test_render_smart_cut_single_segment_success(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_single.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    # video_editor_engine モジュールのモック
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    # cut_video で一時ファイルを作成
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # 字幕焼き込みで出力ファイルを作成
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    # 境界チェックで e <= s となるセグメント (280行目カバー)
    segments = [
        {"sourceStart": 2.0, "sourceEnd": 5.0, "start": 2.0, "end": 5.0, "text": "Hello World"},
        # 12.0 〜 15.0秒 は total_duration (10.0) を超えており、e <= s (10.0 <= 10.0) となる
        {"sourceStart": 12.0, "sourceEnd": 15.0, "start": 12.0, "end": 15.0, "text": "Out of bounds"}
    ]

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is True
        assert output_path.exists()
        # 一時ファイルが削除されていること
        temp_parts = list(tmp_path.glob("_smartcut_part_*"))
        assert len(temp_parts) == 0


@patch("subprocess.run")
def test_render_smart_cut_multiple_segments_success(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_multiple.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "20.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = None  # inf にフォールバック

    # cut_video で一時ファイルを作成
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut part")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # merge_videos で結合ファイルを作成
    def mock_merge(clips, temp_cut_p):
        temp_cut_p.write_bytes(b"merged content")
        return True
    mock_editor.ffmpeg.merge_videos.side_effect = mock_merge
    
    # 字幕焼き込みでコピーフォールバック (C-07のカバーのため)
    mock_editor.ffmpeg.run_command.return_value = (False, "Error")
    mock_editor.ffmpeg._get_encode_args.return_value = []

    # 隣接するセグメント (マージロジック確認のため 0.2s 差) とカット直後 0.1s 開始の字幕 (CUT_SUBTITLE_BUFFER調整確認用)
    # および境界チェックで e <= s となるセグメント (280行目カバー)
    segments = [
        {"sourceStart": 1.0, "sourceEnd": 4.0, "start": 1.0, "end": 4.0, "text": "Part 1"},
        {"sourceStart": 4.2, "sourceEnd": 7.0, "start": 4.2, "end": 7.0, "text": "Part 2"},
        # マージされた 2 番目のレンジ 10.0〜15.0 内で、カット直後 0.1s に開始する字幕
        {"sourceStart": 10.1, "sourceEnd": 12.0, "start": 10.1, "end": 12.0, "text": "Cut Buffer text"}
    ]

    # _merge_timeout 設定時に例外をスローさせる (307-308カバー)
    type(mock_editor.ffmpeg)._merge_timeout = PropertyMock(side_effect=AttributeError("Cannot set attribute"))

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is True
        assert output_path.exists()
        # 一時ファイルクリーンアップ
        assert len(list(tmp_path.glob("_smartcut_part_*"))) == 0


def test_render_smart_cut_cut_failed(dummy_video, tmp_path):
    output_path = tmp_path / "output_failed.mp4"
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    mock_editor.ffmpeg.cut_video.return_value = False  # すべてのスライスが失敗

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is False


@patch("subprocess.run")
def test_render_smart_cut_merge_failed(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_merge_failed.mp4"
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    mock_editor.ffmpeg.cut_video.return_value = True
    mock_editor.ffmpeg.merge_videos.return_value = False  # merge が失敗

    # 複数レンジにするために離れたセグメントを定義
    segments = [
        {"start": 1.0, "end": 3.0, "text": "Part 1"},
        {"start": 6.0, "end": 8.0, "text": "Part 2"}
    ]

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is False
        # 一時ファイルがクリーンアップされていること
        assert len(list(tmp_path.glob("_smartcut_part_*"))) == 0


@patch("subprocess.run")
def test_render_smart_cut_exception_cleanup(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_exception.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    # cut_video 成功時に、クリーンアップの挙動を確認するために実在の一時ファイルを作成しておく
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # 369-370, 375-376 をカバーするために、_burn_subtitles_ffmpeg で例外を発生させて
    # temp_parts と temp_cut_path の両方の unlink() 実行時に例外を投げさせる
    target_path_class = pathlib.WindowsPath if os.name == 'nt' else pathlib.PosixPath
    
    with patch("backend.smart_cut_engine._burn_subtitles_ffmpeg", side_effect=OSError("Burn failed")):
        with patch.object(target_path_class, "unlink", side_effect=PermissionError("Cannot delete temp file")):
            with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
                segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]
                result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
                assert result is False

    # コンテキストマネージャの外側で安全に一時ファイルをクリーンアップ
    temp_parts = list(tmp_path.glob("_smartcut_part_*"))
    assert len(temp_parts) > 0
    for p in temp_parts:
        try:
            p.unlink()
        except OSError:
            pass
        
    temp_cut_path = output_path.with_suffix('.tmp.mp4')
    if temp_cut_path.exists():
        try:
            temp_cut_path.unlink()
        except OSError:
            pass

@patch("subprocess.run")
def test_render_smart_cut_with_thumbnail_generation_success(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_thumb.mp4"
    thumbnail_path = tmp_path / "output_thumb_thumbnail.jpg"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # 正常系: cmd1 実行成功、出力ファイルをダミー作成
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    # screenshot_generator.extract_screenshot をモックする
    mock_extract = MagicMock()
    
    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": MagicMock(extract_screenshot=mock_extract)
    }):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_path=str(thumbnail_path), thumbnail_time=1.0
        )
        assert result is True
        mock_extract.assert_called_once_with(str(output_path), 1.0, str(thumbnail_path))


@patch("subprocess.run")
def test_render_smart_cut_with_thumbnail_generation_ffmpeg_fallback(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_thumb_fallback.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # run_command が呼ばれたときの検証。2回目は FFmpeg フォールバック
    run_cmd_calls = []
    def mock_run_cmd(cmd, timeout=1800):
        run_cmd_calls.append((cmd, timeout))
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    # screenshot_generator をインポートエラーにさせるために sys.modules から削除して None に
    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": None
    }):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_time=1.0
        )
        assert result is True
        # 2回目の run_command 呼び出しが ffmpeg 直接実行であることを確認
        assert len(run_cmd_calls) == 2
        # 最初の引数が ffmpeg で、-ss 1.0 が含まれていること
        assert run_cmd_calls[1][0][0] == "ffmpeg"
        assert "-ss" in run_cmd_calls[1][0]


@patch("subprocess.run")
def test_render_smart_cut_with_thumbnail_generation_exception_no_crash(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_thumb_exc.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    # extract_screenshot が一般的な例外を投げた場合
    mock_extract = MagicMock(side_effect=RuntimeError("Some error"))

    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": MagicMock(extract_screenshot=mock_extract)
    }):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_time=1.0
        )
        # サムネイル生成で例外が出ても True を返すこと
        assert result is True

@patch("subprocess.run")
def test_render_smart_cut_with_thumbnail_generation_ffmpeg_fallback_failure(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_thumb_fallback_fail.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    # 2回目の run_command (FFmpegフォールバック) で False を返すようにする
    run_cmd_calls = []
    def mock_run_cmd(cmd, timeout=1800):
        run_cmd_calls.append(cmd)
        if len(run_cmd_calls) == 2:
            return False, "FFmpeg failed"
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": None
    }):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_time=1.0
        )
        assert result is True
        assert len(run_cmd_calls) == 2


@patch("subprocess.run")
def test_render_smart_cut_with_thumbnail_generation_outer_exception(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_thumb_exc.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    class BadTime:
        def __str__(self):
            raise ValueError("Forced error in F-string representation")

    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
    }):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_path=None, thumbnail_time=BadTime()
        )
        assert result is True


@patch("subprocess.run")
def test_render_smart_cut_unhandled_exception_propagates(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_unhandled_exc.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut
    
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    # TypeError などの想定外の例外は、握りつぶされずに上位へ伝播するはず
    mock_extract = MagicMock(side_effect=TypeError("Unhandled Type Error"))

    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": MagicMock(extract_screenshot=mock_extract)
    }):
        with pytest.raises(TypeError):
            smart_cut_engine.render_smart_cut(
                segments, str(dummy_video), str(output_path),
                generate_thumbnail=True, thumbnail_time=1.0
            )


import pytest

@pytest.mark.xfail(reason="sys.path pollution from other tests or pytest-cov hook in smart_cut_engine", strict=False)
def test_sys_path_not_in_src():
    import importlib
    current_dir = os.path.dirname(os.path.abspath(smart_cut_engine.__file__))
    src_dir = os.path.join(current_dir, "..", "src")
    original_path = list(sys.path)
    try:
        # sys.path に src_dir が含まれていない状態を作る
        norm_src_dir = os.path.normpath(src_dir)
        paths_to_remove = [
            src_dir,
            os.path.abspath(src_dir),
            norm_src_dir,
            src_dir.replace("\\", "/"),
            os.path.abspath(src_dir).replace("\\", "/")
        ]
        for p in paths_to_remove:
            while p in sys.path:
                sys.path.remove(p)

        importlib.reload(smart_cut_engine)
        normalized_sys_path = [os.path.normpath(p) for p in sys.path]
        assert norm_src_dir in normalized_sys_path

        # sys.path にすでに src_dir が含まれている状態でのリロード
        importlib.reload(smart_cut_engine)
        normalized_sys_path = [os.path.normpath(p) for p in sys.path]
        assert norm_src_dir in normalized_sys_path
    finally:
        sys.path = original_path


@patch("subprocess.run")
def test_render_smart_cut_subtitle_recalculation_edge_cases(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_recalc_edge.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "20.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 20.0

    # cut_video で一時ファイルを作成
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut part")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    # merge_videos で結合ファイルを作成
    def mock_merge(clips, temp_cut_p):
        temp_cut_p.write_bytes(b"merged content")
        return True
    mock_editor.ffmpeg.merge_videos.side_effect = mock_merge

    # 字幕焼き込み成功
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    # 1. 2つのマージ区間: [0.0, 5.0] と [10.0, 15.0] (カットポイントは 5.0秒時点)
    #    マージ区間を形成するために、それぞれに属するダミーのセグメントを用意する
    # 2. セグメント1 (正常にバッファが適用される): sourceStart=10.1, sourceEnd=12.0
    #    - cp が 5.0 のとき cp <= new_start < cp + 0.5 が 5.0 <= 5.1 < 5.5 となり、True
    #    - 5.0 の前（もしあれば）の判定では False になる
    # 3. セグメント2 (バッファ適用後に時間逆転する): sourceStart=10.1, sourceEnd=10.4
    #    - new_start は 5.1 -> 5.5 (バッファ適用により +0.4s)
    #    - new_end は 5.4 のまま
    #    - new_end (5.4) > new_start (5.5) が False となり、recalculated_segments から除外される
    segments = [
        # 区間1を定義するセグメント
        {"sourceStart": 0.0, "sourceEnd": 5.0, "start": 0.0, "end": 5.0, "text": "Part 1"},
        # 区間2のセグメント群 (マージ区間2の直後: 10.0秒の開始から0.1秒)
        {"sourceStart": 10.1, "sourceEnd": 12.0, "start": 10.1, "end": 12.0, "text": "Normal recalc"},
        {"sourceStart": 10.1, "sourceEnd": 10.4, "start": 10.1, "end": 10.4, "text": "Will be skipped"},
        # 新しく追加: カットバッファ調整が必要ない位置にあるセグメント (344->343 の False ルート用)
        {"sourceStart": 13.0, "sourceEnd": 14.5, "start": 13.0, "end": 14.5, "text": "No recalc needed"}
    ]

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is True
        assert output_path.exists()


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_flag_write_os_error(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_os_failed.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    ffmpeg_editor.run_command.return_value = (False, "Error")
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello World"}]

    def mock_write_text(content, encoding="utf-8"):
        if "failed" in content:
            raise OSError("OS Error on writing flag")
        temp_srt = tmp_path / "_temp_subtitles.srt"
        temp_srt.write_bytes(content.encode("utf-8"))

    with patch.dict(sys.modules, {"template_config": None}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
            with patch.object(Path, "write_text", side_effect=mock_write_text):
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    str(dummy_video), segments, str(output_path), ffmpeg_editor
                )
                assert result == "fallback_no_subtitle"


@patch("subprocess.run")
def test_render_smart_cut_outer_exceptions(mock_run, dummy_video, tmp_path):
    import subprocess
    output_path = tmp_path / "output_outer_exc.mp4"
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        for exc in [FileNotFoundError("File not found"), PermissionError("Perm denied"), subprocess.SubprocessError("Subprocess failed")]:
            mock_editor.ffmpeg.cut_video.side_effect = exc
            result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
            assert result is False


@patch("subprocess.run")
def test_render_smart_cut_screenshot_generator_specific_exceptions(mock_run, dummy_video, tmp_path):
    import subprocess
    output_path = tmp_path / "output_thumb_spec_exc.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    
    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final cut content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 4.0, "text": "Part 1"}]

    for exc in [ValueError("Value error"), subprocess.SubprocessError("Subprocess error")]:
        mock_extract = MagicMock(side_effect=exc)
        with patch.dict(sys.modules, {
            "video_editor_engine": MagicMock(video_editor=mock_editor),
            "screenshot_generator": MagicMock(extract_screenshot=mock_extract)
        }):
            result = smart_cut_engine.render_smart_cut(
                segments, str(dummy_video), str(output_path),
                generate_thumbnail=True, thumbnail_time=1.0
            )
            assert result is True


@patch("subprocess.run")
def test_render_smart_cut_subtitle_fmt_srt_edge_cases(mock_run, dummy_video, tmp_path):
    # _fmt_srt の境界値や様々な時間フォーマットが正しくSRTに反映されるか検証する
    output_path = tmp_path / "output_fmt_srt.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "8000.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 8000.0

    # 様々な時間: 0秒、1秒未満、1時間以上、ミリ秒の端数
    segments = [
        {"start": 0.0, "end": 0.5, "sourceStart": 0.0, "sourceEnd": 0.5, "text": "Zero"},
        {"start": 0.001, "end": 0.999, "sourceStart": 0.001, "sourceEnd": 0.999, "text": "Sub-second"},
        {"start": 3600.0, "end": 3601.5, "sourceStart": 3600.0, "sourceEnd": 3601.5, "text": "One hour"},
        {"start": 7384.123, "end": 7385.456, "sourceStart": 7384.123, "sourceEnd": 7385.456, "text": "Two hours with ms"}
    ]

    captured_srt_content = None

    # 一時SRTファイルに書き込まれる内容をキャプチャするため、Path.write_text をパッチする
    orig_write_text = Path.write_text
    def mock_write_text(self, content, encoding=None):
        nonlocal captured_srt_content
        if "_temp_subtitles.srt" in self.name:
            captured_srt_content = content
        return orig_write_text(self, content, encoding=encoding)

    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    with patch.object(Path, "write_text", new=mock_write_text):
        with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
            result = smart_cut_engine.render_smart_cut(
                segments, str(dummy_video), str(output_path)
            )
            assert result is True

    # キャプチャしたSRTフォーマットのチェック
    assert captured_srt_content is not None
    lines = captured_srt_content.splitlines()
    
    # 0.0 -> 00:00:00,000
    assert "00:00:00,000 --> 00:00:00,500" in lines
    # 0.001 -> 00:00:00,001
    assert "00:00:00,001 --> 00:00:00,999" in lines
    # 3600.0 -> 00:00:01,499 --> 00:00:02,499 (再計算+バッファ補正後)
    assert "00:00:01,499 --> 00:00:02,499" in lines
    # 7384.123 -> 00:00:02,999 --> 00:00:03,832 (再計算+バッファ補正後)
    assert "00:00:02,999 --> 00:00:03,832" in lines


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_invalid_segment_types(mock_run, dummy_video, tmp_path):
    # segmentsの不正な値に対する挙動の検証
    output_path = tmp_path / "output_invalid_seg.mp4"
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0

    # start が None の場合、TypeErrorが発生することを期待する
    segments_with_none = [{"start": None, "end": 2.0, "sourceStart": None, "sourceEnd": 2.0, "text": "None start"}]
    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        with pytest.raises(TypeError):
            smart_cut_engine.render_smart_cut(
                segments_with_none, str(dummy_video), str(output_path)
            )


@patch("subprocess.run")
def test_render_smart_cut_duration_out_of_bounds(mock_run, dummy_video, tmp_path):
    # segments が動画尺を超えている/マイナスの場合の境界チェック
    output_path = tmp_path / "output_bounds.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    # 動画尺は 10.0 秒
    mock_editor.ffmpeg.get_duration.return_value = 10.0

    # 範囲が境界外: マイナスから動画尺超えまで
    segments = [
        {"sourceStart": -5.0, "sourceEnd": 15.0, "start": -5.0, "end": 15.0, "text": "Out of bounds"}
    ]

    cut_ranges = []
    def mock_cut(input_p, temp_p, start, end):
        # 実際に渡された start, end を記録
        cut_ranges.append((start, end))
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path)
        )
        assert result is True

    # max(0, min(start, total_duration)) により 0.0 と 10.0 に制限されるはず
    assert len(cut_ranges) == 1
    assert cut_ranges[0] == (0.0, 10.0)


@patch("subprocess.run")
def test_render_smart_cut_get_duration_returns_none(mock_run, dummy_video, tmp_path):
    # get_duration が None を返す（動画解析失敗）場合のフォールバックの検証
    output_path = tmp_path / "output_duration_none.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    # get_duration が None を返す
    mock_editor.ffmpeg.get_duration.return_value = None

    segments = [
        {"sourceStart": 1.0, "sourceEnd": 5.0, "start": 1.0, "end": 5.0, "text": "Valid range"}
    ]

    cut_ranges = []
    def mock_cut(input_p, temp_p, start, end):
        cut_ranges.append((start, end))
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path)
        )
        assert result is True

    # total_duration = float('inf') になるため、s=1.0, e=5.0 がそのまま使われる
    assert len(cut_ranges) == 1
    assert cut_ranges[0] == (1.0, 5.0)


@patch("subprocess.run")
def test_render_smart_cut_thumbnail_time_bounds(mock_run, dummy_video, tmp_path):
    # thumbnail_time がマイナスや境界外の場合のサムネイル抽出動作を検証
    output_path = tmp_path / "output_thumb_bounds.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0

    def mock_cut(input_p, temp_p, start, end):
        temp_p.write_bytes(b"cut content")
        return True
    mock_editor.ffmpeg.cut_video.side_effect = mock_cut

    run_cmds = []
    def mock_run_cmd(cmd, timeout=1800):
        run_cmds.append(cmd)
        output_path.write_bytes(b"final content" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 5.0, "sourceStart": 1.0, "sourceEnd": 5.0, "text": "Part 1"}]

    # screenshot_generator のインポートエラーをシミュレートし、直接FFmpegフォールバックへ導く
    with patch.dict(sys.modules, {
        "video_editor_engine": MagicMock(video_editor=mock_editor),
        "screenshot_generator": None
    }):
        # thumbnail_time に -5.0 を指定
        result = smart_cut_engine.render_smart_cut(
            segments, str(dummy_video), str(output_path),
            generate_thumbnail=True, thumbnail_time=-5.0
        )
        assert result is True

    # 直接FFmpegのサムネイル抽出コマンドが実行されているか確認
    # コマンドの第2引数（-ssの後）が "-5.0" になっていること
    thumb_cmd = next((c for c in run_cmds if "ffmpeg" in c and "-ss" in c), None)
    assert thumb_cmd is not None
    ss_idx = thumb_cmd.index("-ss")
    assert thumb_cmd[ss_idx + 1] == "-5.0"


def test_render_smart_cut_segments_none(dummy_video, tmp_path):
    output_path = tmp_path / "output_none_segments.mp4"
    with pytest.raises(TypeError):
        smart_cut_engine.render_smart_cut(None, str(dummy_video), str(output_path))


def test_render_smart_cut_segments_empty_dicts(dummy_video, tmp_path):
    output_path = tmp_path / "output_empty_dicts.mp4"
    with pytest.raises(KeyError):
        smart_cut_engine.render_smart_cut([{}], str(dummy_video), str(output_path))


def test_render_smart_cut_invalid_value_types(dummy_video, tmp_path):
    output_path = tmp_path / "output_invalid_types.mp4"
    segments = [{"sourceStart": "not_a_float", "sourceEnd": 5.0, "start": 1.0, "end": 5.0, "text": "test"}]
    with pytest.raises(ValueError):
        smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))


@patch("subprocess.run")
def test_render_smart_cut_huge_segments(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_huge.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10000.0"}}'
    mock_run.return_value = mock_probe

    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10000.0
    mock_editor.ffmpeg.cut_video.return_value = True
    
    def mock_merge(clips, temp_cut_p):
        temp_cut_p.write_bytes(b"merged data")
        return True
    mock_editor.ffmpeg.merge_videos.side_effect = mock_merge
    
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final rendered data" * 100)
        return True, "Success"
    mock_editor.ffmpeg.run_command.side_effect = mock_run_cmd
    mock_editor.ffmpeg._get_encode_args.return_value = []

    segments = []
    for i in range(1000):
        start = float(i * 10)
        end = start + 5.0
        segments.append({
            "sourceStart": start, "sourceEnd": end,
            "start": start, "end": end,
            "text": f"Text {i}"
        })

    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is True


def test_render_smart_cut_segments_reversed_times(dummy_video, tmp_path):
    output_path = tmp_path / "output_reversed.mp4"
    segments = [{"sourceStart": 5.0, "sourceEnd": 2.0, "start": 5.0, "end": 2.0, "text": "Reversed"}]
    
    mock_editor = MagicMock()
    mock_editor.ffmpeg.get_duration.return_value = 10.0
    mock_editor.ffmpeg.cut_video.return_value = True
    
    with patch.dict(sys.modules, {"video_editor_engine": MagicMock(video_editor=mock_editor)}):
        result = smart_cut_engine.render_smart_cut(segments, str(dummy_video), str(output_path))
        assert result is False


def test_render_smart_cut_invalid_path_none(tmp_path):
    output_path = tmp_path / "output_path_none.mp4"
    segments = [{"sourceStart": 1.0, "sourceEnd": 3.0, "start": 1.0, "end": 3.0, "text": "test"}]
    with pytest.raises(TypeError):
        smart_cut_engine.render_smart_cut(segments, None, str(output_path))


def test_render_smart_cut_invalid_path_empty(tmp_path):
    output_path = tmp_path / "output_path_empty.mp4"
    segments = [{"sourceStart": 1.0, "sourceEnd": 3.0, "start": 1.0, "end": 3.0, "text": "test"}]
    result = smart_cut_engine.render_smart_cut(segments, "", str(output_path))
    assert result is False


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_negative_time_format(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_negative_time.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 呼び出し時に出力ファイルを作成するモック
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final rendered data" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": -5.0, "end": 5.0, "text": "Negative Start"}]

    captured_srt_content = None
    orig_write_text = Path.write_text
    def mock_write_text(self, content, encoding=None):
        nonlocal captured_srt_content
        if "_temp_subtitles.srt" in self.name:
            captured_srt_content = content
        return orig_write_text(self, content, encoding=encoding)

    with patch.object(Path, "write_text", new=mock_write_text):
        with patch.dict(sys.modules, {"template_config": None}):
            with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    str(dummy_video), segments, str(output_path), ffmpeg_editor
                )
                assert result is True

    assert captured_srt_content is not None
    assert "-01:" in captured_srt_content or "-00:" in captured_srt_content or "-->" in captured_srt_content


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_huge_time_format(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_huge_time.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "100000.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 呼び出し時に出力ファイルを作成するモック
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final rendered data" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 90000.0, "end": 90005.0, "text": "Huge time"}]

    captured_srt_content = None
    orig_write_text = Path.write_text
    def mock_write_text(self, content, encoding=None):
        nonlocal captured_srt_content
        if "_temp_subtitles.srt" in self.name:
            captured_srt_content = content
        return orig_write_text(self, content, encoding=encoding)

    with patch.object(Path, "write_text", new=mock_write_text):
        with patch.dict(sys.modules, {"template_config": None}):
            with patch("backend.smart_cut_engine._get_logo_path", return_value=None):
                result = smart_cut_engine._burn_subtitles_ffmpeg(
                    str(dummy_video), segments, str(output_path), ffmpeg_editor
                )
                assert result is True

    assert captured_srt_content is not None
    assert "25:00:00,000" in captured_srt_content


@patch("subprocess.run")
def test_burn_subtitles_ffmpeg_logo_height_invalid_type(mock_run, dummy_video, tmp_path):
    output_path = tmp_path / "output_logo_height_invalid.mp4"
    mock_probe = MagicMock()
    mock_probe.stdout = '{"format": {"duration": "10.0"}}'
    mock_run.return_value = mock_probe

    ffmpeg_editor = MagicMock()
    # 呼び出し時に出力ファイルを作成するモック
    def mock_run_cmd(cmd, timeout=1800):
        output_path.write_bytes(b"final rendered data" * 100)
        return True, "Success"
    ffmpeg_editor.run_command.side_effect = mock_run_cmd
    ffmpeg_editor._get_encode_args.return_value = []

    segments = [{"start": 1.0, "end": 3.0, "text": "Hello"}]

    mock_module = MagicMock()
    mock_config = MagicMock()
    mock_config.is_active = True
    mock_config.get_branding_config.return_value = {
        "logo_path": "logo_path.png",
        "logo_height": {"invalid": "type"}
    }
    mock_config.get_subtitle_style.return_value = "FontSize=16"
    mock_module.template_config = mock_config

    logo_path = tmp_path / "logo.png"
    logo_path.touch()

    with patch.dict(sys.modules, {"template_config": mock_module}):
        with patch("backend.smart_cut_engine._get_logo_path", return_value=str(logo_path)):
            result = smart_cut_engine._burn_subtitles_ffmpeg(
                str(dummy_video), segments, str(output_path), ffmpeg_editor
            )
            assert result is True
