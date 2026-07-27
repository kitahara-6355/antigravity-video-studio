import os
import pytest
import shutil
from pathlib import Path
from unittest.mock import MagicMock
from backend.video_pipeline.video_composer import VideoComposer, CompositionSegment, ComposeResult, ExportResult

# パラメータ化テストの定義
# (case_name, method, args, kwargs, expected_success, expected_error_contains)
test_cases = [
    # 正常系 (2+)
    ("export_high", "export", ("dummy_video.mp4", "output_high.mp4"), {"quality": "high"}, True, None),
    ("export_medium", "export", ("dummy_video.mp4", "output_medium.mp4"), {"quality": "medium"}, True, None),
    ("add_bgm_with_file", "add_bgm", ("dummy_video.mp4", "dummy_bgm.mp3"), {"volume": 0.3}, True, None),
    
    # 境界値 (2+)
    ("export_low", "export", ("dummy_video.mp4", "output_low.mp4"), {"quality": "low"}, True, None),
    ("add_bgm_volume_zero", "add_bgm", ("dummy_video.mp4", "dummy_bgm.mp3"), {"volume": 0.0}, True, None),
    ("add_bgm_volume_one", "add_bgm", ("dummy_video.mp4", "dummy_bgm.mp3"), {"volume": 1.0}, True, None),
    
    # 異常系 (2+)
    ("export_invalid_preset", "export", ("dummy_video.mp4", "output.mp4"), {"quality": "invalid"}, False, "不明な品質プリセット"),
    ("compose_empty_segments", "compose", ([],), {}, False, "合成するセグメントが指定されていません"),
    ("add_bgm_missing_bgm_file", "add_bgm", ("dummy_video.mp4", ""), {}, True, None), # BGMファイルなしでもエラーにならずコピーで成功
    ("add_bgm_copy_fail", "add_bgm", ("nonexistent_video.mp4", ""), {}, False, None), # コピー失敗で例外ハンドラに入りTDR登録される
]

@pytest.mark.parametrize(
    "case_name, method, args, kwargs, expected_success, expected_error_contains",
    test_cases
)
def test_composer_mocked(
    tmp_path,
    safe_popen_mock,
    case_name,
    method,
    args,
    kwargs,
    expected_success,
    expected_error_contains
):
    """safe_popen_mockを使用して、実際のFFmpegを実行せずに振る舞いを検証するテスト (6-10ケース)"""
    # safe_popen_mock の Popen インスタンスに対して __enter__ をモックして unpack エラーを回避する
    proc = safe_popen_mock.return_value
    proc.__enter__.return_value = proc
    
    composer = VideoComposer(work_dir=str(tmp_path))
    
    # 必要なダミーファイルのパスを解決し、作成
    resolved_args = []
    for arg in args:
        if isinstance(arg, str):
            if not arg:  # 空文字列（BGMファイルなしなど）
                resolved_args.append("")
            elif "dummy" in arg or "output" in arg:
                p = tmp_path / arg
                if "output" not in arg:
                    p.write_text("dummy content")
                resolved_args.append(str(p))
            else:
                resolved_args.append(arg)
        elif isinstance(arg, list):
            resolved_args.append(arg)
        else:
            resolved_args.append(arg)
            
    resolved_kwargs = {}
    for k, v in kwargs.items():
        if isinstance(v, str) and "dummy" in v:
            p = tmp_path / v
            p.write_text("dummy content")
            resolved_kwargs[k] = str(p)
        else:
            resolved_kwargs[k] = v

    func = getattr(composer, method)
    
    if method in ("add_bgm", "add_subtitles"):
        res = func(*resolved_args, **resolved_kwargs)
        if expected_success:
            assert res != ""
            # モックされている場合、実際のファイルは作られない（BGM欠損時のコピーを除く）のでexists()はアサートしない
        else:
            assert res == ""
    else:
        # compose or export
        res = func(*resolved_args, **resolved_kwargs)
        assert res.success == expected_success
        if not expected_success and expected_error_contains:
            assert expected_error_contains in res.error

@pytest.mark.slow
def test_composer_slow_real_ffmpeg():
    """実際のFFmpegを動かす結合テスト (@pytest.mark.slow)

    WindowsでのFFmpeg subtitlesフィルタのパス問題（バックスラッシュやコロン）を避けるため、
    カレントディレクトリ相対パスを使用してテストを実行する。
    """
    import subprocess
    
    # FFmpegがインストールされているか確認
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        pytest.skip("FFmpeg is not installed in the environment.")

    # カレントディレクトリ相対パスを使用
    video_path = Path("tmp_test_video.mp4")
    bgm_path = Path("tmp_test_bgm.mp3")
    srt_path = Path("tmp_test_subs.srt")
    work_dir = Path("tmp_test_work")

    # 作成された一時ファイルの追跡
    created_paths = [video_path, bgm_path, srt_path, work_dir]

    try:
        # ダミー動画の作成（ビデオと音声ストリームの両方を含む）
        cmd_video = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=30",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264",
            "-c:a", "aac",
            "-pix_fmt", "yuv420p",
            str(video_path)
        ]
        subprocess.run(cmd_video, check=True, capture_output=True)

        # ダミーBGM의 作成
        cmd_bgm = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1",
            str(bgm_path)
        ]
        subprocess.run(cmd_bgm, check=True, capture_output=True)

        # ダミーSRTの作成
        srt_content = (
            "1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "Test Subtitle\n"
        )
        srt_path.write_text(srt_content, encoding="utf-8")

        composer = VideoComposer(work_dir=str(work_dir))

        # 1. add_subtitles テスト
        sub_video = composer.add_subtitles(str(video_path), str(srt_path))
        assert sub_video != ""
        assert Path(sub_video).exists()
        assert Path(sub_video).stat().st_size > 0

        # 2. add_bgm テスト (BGMファイルあり)
        bgm_video = composer.add_bgm(str(video_path), str(bgm_path), volume=0.5)
        assert bgm_video != ""
        assert Path(bgm_video).exists()
        assert Path(bgm_video).stat().st_size > 0

        # 3. add_bgm テスト (BGMファイルなし - エラーにならない)
        bgm_missing_video = composer.add_bgm(str(video_path), "", volume=0.5)
        assert bgm_missing_video != ""
        assert Path(bgm_missing_video).exists()
        assert Path(bgm_missing_video).stat().st_size > 0

        # 4. export テスト (high/medium/low)
        for q in ["high", "medium", "low"]:
            export_out = work_dir / f"export_{q}.mp4"
            res = composer.export(str(video_path), str(export_out), quality=q)
            assert res.success is True
            assert Path(res.output_path).exists()
            assert res.file_size > 0
            assert res.bitrate != ""

        # 5. compose テスト
        seg = CompositionSegment(
            source_path=str(video_path),
            start_time=0.0,
            end_time=1.0,
            transition="cut"
        )
        compose_res = composer.compose([seg])
        assert compose_res.success is True
        assert Path(compose_res.output_path).exists()
        assert compose_res.file_size > 0
        assert compose_res.duration == 1.0

    finally:
        # 一時ファイルのクリーンアップ
        for path in created_paths:
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
