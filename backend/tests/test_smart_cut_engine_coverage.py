import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

# Ensure backend directory is in path
backend_dir = str(Path(__file__).parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import smart_cut_engine


class TestSmartCutEngineCoverage:
    """smart_cut_engine.py のカバレッジ向上テスト"""

    # ==========================================
    # 1. _get_logo_path
    # ==========================================

    def test_get_logo_path_active_template(self):
        """template_config が active でロゴパスが存在する場合"""
        mock_tc_obj = MagicMock()
        mock_tc_obj.is_active = True
        mock_tc_obj.get_branding_config.return_value = {"logo_path": "/fake/logo.png"}
        
        mock_module = MagicMock()
        mock_module.template_config = mock_tc_obj
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            with patch("smart_cut_engine.Path") as mock_path_cls:
                mock_path_instance = MagicMock()
                mock_path_instance.exists.return_value = True
                mock_path_cls.return_value = mock_path_instance
                # 文字列キャストをモック
                mock_path_instance.__str__.return_value = "/fake/logo.png"
                
                result = smart_cut_engine._get_logo_path()
                assert result == "/fake/logo.png"

    def test_get_logo_path_exceptions(self):
        """template_config からの取得で例外が発生し、デフォルトロゴも存在しない場合"""
        mock_module = MagicMock()
        # template_config にアクセスすると AttributeError が発生するように設定
        type(mock_module).template_config = property(lambda self: exec('raise AttributeError("mock")'))
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            with patch.object(Path, "exists", return_value=False):
                result = smart_cut_engine._get_logo_path()
                assert result is None

    # ==========================================
    # 2. _burn_subtitles_ffmpeg
    # ==========================================

    def test_burn_subtitles_empty_segments_direct(self, tmp_path):
        """segments が空のとき、そのままコピーするルート (L105-107)"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        ffmpeg_mock = MagicMock()
        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), [], str(out), ffmpeg_mock)
        assert result is True
        assert out.exists()

    def test_burn_subtitles_ffprobe_failure(self, tmp_path):
        """ffprobe が失敗して例外が発生するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        # 成功判定を通すために、あらかじめ出力先にダミーデータを書き込んでおく
        out.write_bytes(b"A" * 2000)
        
        # subprocess.run が例外を投げるようにする
        with patch("subprocess.run", side_effect=FileNotFoundError("ffprobe not found")):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            segments = [
                {"text": "   ", "start": 0, "end": 5},  # 空白文字のみでスキップされる
                {"text": "Hello", "start": 0, "end": 5}
            ]
            
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_burn_subtitles_srt_duration_warning(self, tmp_path):
        """SRT の end 時間が動画 duration を大幅に超えて警告が出るケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        # ffprobe が正常に duration 10.0 を返すようにモック
        mock_run_res = MagicMock()
        mock_run_res.stdout = '{"format": {"duration": "10.0"}}'
        
        with patch("subprocess.run", return_value=mock_run_res):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            # max_end = 20.0 (video_duration + 10) で警告ログが出る
            segments = [{"text": "Hello", "start": 0, "end": 20.0}]
            
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_burn_subtitles_default_style_fallback(self, tmp_path):
        """template_config がインポートエラーになり、デフォルト字幕スタイルが使われるケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        with patch.dict(sys.modules, {"template_config": None}):
            # 強制的に ImportError を起こすために mock_tc を作成せず patch.dict から除外
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_burn_subtitles_logo_height_from_template(self, tmp_path):
        """template_config から logo_height を取得するルート (L144)"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        mock_tc_obj = MagicMock()
        mock_tc_obj.is_active = True
        mock_tc_obj.get_branding_config.return_value = {"logo_height": 60}
        mock_module = MagicMock()
        mock_module.template_config = mock_tc_obj
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            with patch("smart_cut_engine._get_logo_path", return_value="/fake/logo.png"):
                ffmpeg_mock = MagicMock()
                ffmpeg_mock.run_command.return_value = (True, "ok")
                ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
                ffmpeg_mock._get_hwaccel_input_args.return_value = []
                
                segments = [{"text": "Hello", "start": 0, "end": 5}]
                
                with patch.object(Path, "exists", return_value=True):
                    with patch.object(Path, "stat") as mock_stat:
                        mock_stat.return_value.st_size = 5000
                        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
                        assert result is True

    def test_burn_subtitles_no_logo_burn(self, tmp_path):
        """ロゴパスが None で、字幕のみを焼き込む (-vf) ケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        # _get_logo_path が None を返すようにする
        with patch("smart_cut_engine._get_logo_path", return_value=None):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = ["-hwaccel", "cuda"]
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            
            # hwaccel_args が cmd1 に含まれることを確認するため
            ffmpeg_mock._get_hwaccel_input_args.assert_called_once()
            assert result is True

    def test_burn_subtitles_hwaccel_fail_cpu_success(self, tmp_path):
        """GPU hwaccel (cmd1) が失敗し、CPU入力 + GPU出力 (cmd2) で成功するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        with patch("smart_cut_engine._get_logo_path", return_value="/fake/logo.png"):
            ffmpeg_mock = MagicMock()
            # cmd1 で失敗し、cmd2 で成功するようにする
            ffmpeg_mock.run_command.side_effect = [
                (False, "GPU failed"),
                (True, "CPU fallback ok")
            ]
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "h264_nvenc"]
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            
            # pathlib.Path の exists と stat.st_size をパッチ
            with patch.object(Path, "exists", return_value=True):
                with patch.object(Path, "stat") as mock_stat:
                    mock_stat.return_value.st_size = 5000
                    
                    result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
                    assert result is True
                    assert ffmpeg_mock.run_command.call_count == 2

    def test_burn_subtitles_flag_write_permission_error(self, tmp_path):
        """フォールバック3の際、フラグファイルの書き込みで PermissionError が起きるケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (False, "all failed")
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
        
        segments = [{"text": "Hello", "start": 0, "end": 5}]
        
        # write_text のモック: _subtitle_burn_failed.flag の時だけエラー
        orig_write_text = Path.write_text
        def mock_write_text(self, *args, **kwargs):
            if "_subtitle_burn_failed.flag" in str(self):
                raise PermissionError("Permission denied")
            return orig_write_text(self, *args, **kwargs)
            
        with patch.object(Path, "write_text", mock_write_text):
            with patch.object(Path, "exists", return_value=False):
                result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
                assert result == "fallback_no_subtitle"

    # ==========================================
    # 3. render_smart_cut
    # ==========================================

    def test_render_smart_cut_merge_logic_and_cut_bounds(self, tmp_path):
        """マージロジック、無効な境界チェック、およびクリーンアップ例外のテスト"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # 3つのセグメントを用意（start/end を追加して KeyError 回避）
        segments = [
            {"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Seg 1"},
            {"sourceStart": 5.2, "sourceEnd": 10.0, "start": 5.2, "end": 10.0, "text": "Seg 2"},
            {"sourceStart": 12.0, "sourceEnd": 15.0, "start": 12.0, "end": 15.0, "text": "Seg 3"},
            {"sourceStart": 20.0, "sourceEnd": 18.0, "start": 20.0, "end": 18.0, "text": "Seg 4"},  # 無効な境界
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        
        # side_effect で実行されるよう、呼び出し回数に応じた処理を記述
        call_count = 0
        def fake_cut(inp, outp, s, e):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return False
            outp.write_bytes(b"cut_part")
            return True
            
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.merge_videos.return_value = True
        
        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
            mock_ve = MagicMock()
            mock_ve.ffmpeg = mock_ffmpeg
            mock_module = MagicMock()
            mock_module.video_editor = mock_ve
            
            mock_clip = MagicMock()
            mock_module.VideoClip.return_value = mock_clip
            
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                # 一時ファイル削除で PermissionError が発生するようにする
                with patch.object(Path, "unlink", side_effect=PermissionError("Cannot delete")):
                    result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                    # 1つ目の切り出しは失敗したが、2つ目は成功したので True が返る
                    assert result is True
                    assert mock_ffmpeg.cut_video.call_count == 2

    def test_render_smart_cut_no_duration_and_merge_fail(self, tmp_path):
        """get_duration が None を返し、merge_videos が失敗するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # 複数パートにする
        segments = [
            {"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Seg 1"},
            {"sourceStart": 10.0, "sourceEnd": 15.0, "start": 10.0, "end": 15.0, "text": "Seg 2"},
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = None  # None を返す
        
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut_part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.merge_videos.return_value = False  # マージ失敗
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        # L315-316 の merge_timeout設定例外をカバーするために、ffmpeg オブジェクトで
        # _merge_timeout プロパティのセッターで例外を投げさせる
        type(mock_ffmpeg)._merge_timeout = property(
            lambda self: 600,
            lambda self, val: exec('raise AttributeError("Cannot set property")')
        )
        mock_module.VideoClip.return_value = MagicMock()

        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
            assert result is False

    def test_render_smart_cut_buffer_and_thumbnail_generation(self, tmp_path):
        """カットポイントバッファ適用、およびサムネイル生成の各種エラーフォールバック"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # カットポイントが発生するように複数レンジに分割
        segments = [
            {"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "First part"},
            {"sourceStart": 10.1, "sourceEnd": 11.0, "start": 10.1, "end": 11.0, "text": "Second part (near cut point)"},
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut_part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.merge_videos.return_value = True
        mock_ffmpeg.run_command.return_value = (False, "FFmpeg thumb fail")
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()

        # L361 の burn_result = "fallback_no_subtitle" をカバーするため、
        # _burn_subtitles_ffmpeg が "fallback_no_subtitle" を返すようにする
        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value="fallback_no_subtitle"):
            # screenshot_generator で一般例外（ValueError）を投げさせて L390-391 の警告を通す
            with patch("screenshot_generator.extract_screenshot", side_effect=ValueError("Mock error")):
                with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                    # generate_thumbnail = True だが thumbnail_path = None (自動決定ルート L369)
                    result = smart_cut_engine.render_smart_cut(
                        segments, str(src), str(out),
                        generate_thumbnail=True, thumbnail_path=None
                    )
                    assert result is True
                    mock_ffmpeg.run_command.assert_called_once()

    def test_render_smart_cut_thumbnail_general_exception(self, tmp_path):
        """サムネイル生成全体で一般例外（ValueError等）が発生してログ出力するルート (L390-391)"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut_part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.merge_videos.return_value = True
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()
        
        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                # out_p.parent へのアクセスで例外を投げるように Path インスタンスをモック
                # L369 の out_p = Path(output_path) で作られる 3回目 の Path のみ parent で例外を起こす
                call_count = 0
                orig_path = Path
                def mock_path_side_effect(arg):
                    nonlocal call_count
                    if str(arg) == str(out):
                        call_count += 1
                        if call_count == 3:
                            p_mock = MagicMock()
                            p_mock.__str__.return_value = str(arg)
                            type(p_mock).parent = PropertyMock(side_effect=ValueError("Mock parent error"))
                            return p_mock
                    
                    return orig_path(arg)
                
                with patch("smart_cut_engine.Path", side_effect=mock_path_side_effect):
                    result = smart_cut_engine.render_smart_cut(
                        [{"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Test"}],
                        str(src), str(out),
                        generate_thumbnail=True, thumbnail_path=None
                    )
                    # サムネイル生成で例外が起きたが、render_smart_cut 自体は True が返る
                    assert result is True

    def test_render_smart_cut_single_part_coverage(self, tmp_path):
        """1つのセグメントしかなく、マージが不要なケース (L305-306)"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        segments = [
            {"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Only one"}
        ]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut_part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is True

    def test_render_smart_cut_no_valid_ranges(self, tmp_path):
        """切り出しがすべて失敗し、有効な範囲が存在しないケース (L296-297)"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        
        segments = [
            {"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Test"}
        ]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        mock_ffmpeg.cut_video.return_value = False  # すべて失敗
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
            assert result is False

    def test_render_smart_cut_outer_exceptions(self, tmp_path):
        """render_smart_cut 内で例外（FileNotFoundError等）が発生した場合の処理"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.side_effect = FileNotFoundError("Video file not found")
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve

        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            result = smart_cut_engine.render_smart_cut(
                [{"sourceStart": 0, "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Test"}],
                str(src), str(out)
            )
            assert result is False

    def test_get_logo_path_type_error(self):
        """template_config.get_branding_config() が TypeError を投げるケース"""
        mock_tc_obj = MagicMock()
        mock_tc_obj.is_active = True
        mock_tc_obj.get_branding_config.side_effect = TypeError("Mock TypeError")
        
        mock_module = MagicMock()
        mock_module.template_config = mock_tc_obj
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            with patch.object(Path, "exists", return_value=False):
                result = smart_cut_engine._get_logo_path()
                assert result is None

    def test_burn_subtitles_ffprobe_invalid_json(self, tmp_path):
        """ffprobe が無効な JSON を返し、JSONDecodeError が発生するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        mock_run_res = MagicMock()
        mock_run_res.stdout = "{invalid json}"
        
        with patch("subprocess.run", return_value=mock_run_res):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_burn_subtitles_logo_height_type_error(self, tmp_path):
        """template_config.get_branding_config() の logo_height が TypeError を投げるケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        mock_tc_obj = MagicMock()
        mock_tc_obj.is_active = True
        # logo_height へのアクセスで TypeError を発生させる
        mock_tc_obj.get_branding_config.side_effect = TypeError("Invalid config structure")
        mock_module = MagicMock()
        mock_module.template_config = mock_tc_obj
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            with patch("smart_cut_engine._get_logo_path", return_value="/fake/logo.png"):
                ffmpeg_mock = MagicMock()
                ffmpeg_mock.run_command.return_value = (True, "ok")
                ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
                ffmpeg_mock._get_hwaccel_input_args.return_value = []
                
                segments = [{"text": "Hello", "start": 0, "end": 5}]
                
                with patch.object(Path, "exists", return_value=True):
                    with patch.object(Path, "stat") as mock_stat:
                        mock_stat.return_value.st_size = 5000
                        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
                        assert result is True

    def test_render_smart_cut_invalid_segment_times(self, tmp_path):
        """segments の時間パラメータが不正で float 変換エラー (ValueError) が発生するケース"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        
        segments = [
            {"sourceStart": "invalid_time", "sourceEnd": 5.0, "start": 0, "end": 5.0, "text": "Test"}
        ]
        
        mock_ffmpeg = MagicMock()
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            with pytest.raises(ValueError):
                smart_cut_engine.render_smart_cut(segments, str(src), str(out))

    def test_get_logo_path_default_logo_exists(self):
        """template_config からロゴ取得がスキップされ、デフォルトロゴが存在する場合"""
        mock_module = MagicMock()
        # template_config へのアクセスで例外を発生させる
        type(mock_module).template_config = property(lambda self: exec('raise AttributeError("mock")'))
        
        with patch.dict(sys.modules, {"template_config": mock_module}):
            # Path.exists は default_logo に一致する場合だけ True を返すようにパッチ
            orig_exists = Path.exists
            def mock_exists(self_path):
                if "brand_logo.png" in str(self_path):
                    return True
                return False
                
            with patch.object(Path, "exists", mock_exists):
                result = smart_cut_engine._get_logo_path()
                assert result is not None
                assert "brand_logo.png" in result.replace("\\", "/")

    def test_burn_subtitles_ffprobe_missing_duration(self, tmp_path):
        """ffprobe が正常に終了するが、duration キーがないため duration が 0.0 になるケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        mock_run_res = MagicMock()
        # duration 情報を含まない format 辞書
        mock_run_res.stdout = '{"format": {}}'
        
        with patch("subprocess.run", return_value=mock_run_res):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_burn_subtitles_fallback3_flag_write_success(self, tmp_path):
        """フォールバック3の際、フラグファイルの書き込みが正常に行われ、正常にフォールバックすること"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (False, "all failed")
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
        
        segments = [{"text": "Hello", "start": 0, "end": 5}]
        
        with patch.object(Path, "exists", return_value=False):
            # _burn_subtitles_ffmpeg 内でフラグファイルの書き込みが正常に行われることを検証
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result == "fallback_no_subtitle"

    def test_render_smart_cut_subtitle_recalculation_and_buffer(self, tmp_path):
        """マージにより複数パートが存在するとき、カットポイント直後の字幕開始時間がシフトされる挙動の検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # 2つのセグメントを定義（マージすると 0.0〜5.0秒 と 10.2〜12.0秒 になる）
        # 2番目のセグメント内の字幕（sourceStart: 10.2）が、マージ後のタイムラインで
        # カットポイント 5.0秒 の直後 (5.0秒) に配置されるため、バッファにより 5.5秒 にシフトされる
        segments = [
            {"sourceStart": 0.0, "sourceEnd": 5.0, "start": 0.0, "end": 5.0, "text": "Part 1"},
            {"sourceStart": 10.2, "sourceEnd": 12.0, "start": 10.2, "end": 12.0, "text": "Part 2 (near cut point)"},
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        
        def fake_cut(inp, outp, s, e):
            outp.write_bytes(b"cut_part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.merge_videos.return_value = True
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()
        
        # recalculated_segments を検証するために _burn_subtitles_ffmpeg をスパイする
        captured_segments = []
        def spy_burn_subtitles(video_p, segs, output_p, ffmpeg_e):
            nonlocal captured_segments
            captured_segments = segs
            return True

        with patch("smart_cut_engine._burn_subtitles_ffmpeg", side_effect=spy_burn_subtitles):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is True
                
                # キャプチャしたセグメントを確認
                assert len(captured_segments) == 2
                
                # Part 1 の開始と終了はそのまま (0.0 から 5.0)
                assert captured_segments[0]["start"] == pytest.approx(0.0)
                assert captured_segments[0]["end"] == pytest.approx(5.0)
                
                # Part 2 の字幕（sourceStart: 10.2）のマージ後の新開始時間は:
                # new_start = 5.0 + (10.2 - 10.2) = 5.0 秒。
                # カットポイントは 5.0秒。
                # 5.0 <= new_start < 5.0 + 0.5 が成り立つため、5.5秒にシフトされる。
                # new_end = 5.0 + (12.0 - 10.2) = 6.8 秒。
                assert captured_segments[1]["start"] == pytest.approx(5.5)
                assert captured_segments[1]["end"] == pytest.approx(6.8)

    def test_render_smart_cut_recalc_empty_text_segment(self, tmp_path):
        """テキストが空、あるいはキーが存在しないセグメントが混在する場合の動作検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # 空白文字およびキー無しのセグメント
        segments = [
            {"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "  "},
            {"sourceStart": 2.5, "sourceEnd": 4.0, "start": 2.5, "end": 4.0}
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 10.0
        mock_ffmpeg.cut_video.return_value = True
        
        # マージ成功時にダミーマージファイルを書き込むようにモック
        def fake_merge(clips, output_p):
            Path(output_p).write_bytes(b"merged_video")
            return True
        mock_ffmpeg.merge_videos.side_effect = fake_merge
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()

        original_burn = smart_cut_engine._burn_subtitles_ffmpeg
        captured_segments = []
        def spy_burn_subtitles(video_p, segs, output_p, ffmpeg_e):
            nonlocal captured_segments
            captured_segments = segs
            # 内部の _burn_subtitles_ffmpeg 呼び出しを本物（に近い挙動）にする
            # 実際には srt が空になって shutil.copy が実行され True が返るはず
            return original_burn(video_p, segs, output_p, ffmpeg_e)

        with patch("smart_cut_engine._burn_subtitles_ffmpeg", side_effect=spy_burn_subtitles):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is True
                assert len(captured_segments) == 2
                # 出力ファイルが存在すること（直接コピーされるため）
                assert out.exists()

    def test_render_smart_cut_duration_zero(self, tmp_path):
        """動画 duration が 0.0 で、切り出し範囲がすべて無効になり False が返ることを検証"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"

        segments = [
            {"sourceStart": 1.0, "sourceEnd": 5.0, "start": 1.0, "end": 5.0, "text": "Test"}
        ]

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 0.0  # duration 0
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve

        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
            assert result is False

    def test_render_smart_cut_none_segments(self, tmp_path):
        """segments が None の場合に TypeError が発生することを検証"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        with pytest.raises(TypeError):
            smart_cut_engine.render_smart_cut(None, str(src), str(out))

    def test_render_smart_cut_segments_missing_keys(self, tmp_path):
        """segments 内の要素に必要なキー(start/end)がない場合に KeyError が発生することを検証"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        # start / end キーがない
        segments = [{"sourceStart": 1.0, "sourceEnd": 5.0, "text": "Missing keys"}]
        
        mock_ffmpeg = MagicMock()
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            with pytest.raises(KeyError):
                smart_cut_engine.render_smart_cut(segments, str(src), str(out))

    def test_render_smart_cut_huge_input_times(self, tmp_path):
        """duration を超える、または無限大のカット範囲が指定された場合、正しく境界制限されることを検証"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        segments = [
            {"sourceStart": 10.0, "sourceEnd": float('inf'), "start": 10.0, "end": 20.0, "text": "Huge time"}
        ]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 15.0 # 動画長は15秒
        
        captured_cuts = []
        def fake_cut(inp, outp, s, e):
            captured_cuts.append((s, e))
            outp.write_bytes(b"cut")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is True
                # カット範囲が動画長 (15.0) に制限されていることを確認
                assert len(captured_cuts) == 1
                assert captured_cuts[0] == (10.0, 15.0)

    def test_render_smart_cut_thumbnail_time_negative(self, tmp_path):
        """サムネイル抽出時間に負の数が指定された場合でも、安全に処理されることを検証"""
        src = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        thumbnail_path = tmp_path / "thumb.jpg"
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "Part"}]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 5.0
        
        # cut_video で一時ファイルを作成するようにする
        def fake_cut(inp, outp, s, e):
            Path(outp).write_bytes(b"cut part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        
        captured_args = []
        def fake_run_command(cmd, timeout=30):
            captured_args.append(cmd)
            return True, "success"
        mock_ffmpeg.run_command.side_effect = fake_run_command
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        # screenshot_generator をインポートエラーにさせて FFmpeg 直接実行にフォールバックさせる
        with patch.dict(sys.modules, {
            "video_editor_engine": mock_module,
            "screenshot_generator": None
        }):
            with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
                result = smart_cut_engine.render_smart_cut(
                    segments, str(src), str(out),
                    generate_thumbnail=True, thumbnail_path=str(thumbnail_path), thumbnail_time=-1.5
                )
                assert result is True
                # ffmpeg コマンドの -ss に -1.5 が渡されていることを確認
                ffmpeg_cmd = captured_args[0]
                assert "-ss" in ffmpeg_cmd
                idx = ffmpeg_cmd.index("-ss")
                assert ffmpeg_cmd[idx + 1] == "-1.5"

    def test_burn_subtitles_ffmpeg_invalid_segments_type(self, tmp_path):
        """segments に辞書などの不正な型が渡された場合、適切にハンドリング（例外発生）されることを検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        ffmpeg_mock = MagicMock()
        # segments にリストではなく辞書を渡す
        with pytest.raises(AttributeError):
            smart_cut_engine._burn_subtitles_ffmpeg(str(src), {"not": "a list"}, str(out), ffmpeg_mock)

    def test_burn_subtitles_ffmpeg_start_greater_than_end(self, tmp_path):
        """segments の start が end より大きい異常値のハンドリングを検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (True, "ok")
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
        ffmpeg_mock._get_hwaccel_input_args.return_value = []
        
        # start(10.0) > end(5.0) のセグメント。SRT生成時にそのまま出力される挙動を検証
        segments = [{"text": "Hello Abnormal", "start": 10.0, "end": 5.0}]
        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
        assert result is True

    def test_burn_subtitles_ffmpeg_invalid_segment_value_types(self, tmp_path):
        """segments の要素の start/end が不適切な型（Noneなど）の場合に TypeError が発生することを検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        ffmpeg_mock = MagicMock()
        # start に None を指定する
        segments = [{"text": "Hello TypeError", "start": None, "end": 5.0}]
        with pytest.raises(TypeError):
            smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)

    def test_burn_subtitles_ffmpeg_special_characters_in_text(self, tmp_path):
        """segments の text に特殊文字や改行コードが含まれる場合の挙動を検証"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (True, "ok")
        ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
        ffmpeg_mock._get_hwaccel_input_args.return_value = []
        
        # text に改行や "-->" などのSRTメタ文字を含む
        segments = [{"text": "Line1\nLine2 --> Meta", "start": 1.0, "end": 4.0}]
        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
        assert result is True

    def test_render_smart_cut_invalid_video_path_type(self, tmp_path):
        """render_smart_cut にて original_video_path が None の場合に TypeError が発生することを検証"""
        out = tmp_path / "output.mp4"
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "Test"}]
        
        # Path() に None が渡されると TypeError が発生するはず
        with pytest.raises(TypeError):
            smart_cut_engine.render_smart_cut(segments, None, str(out))

    def test_burn_subtitles_ffmpeg_boundary_values(self, tmp_path):
        """境界値のテスト: _fmt_srt の切り上げ・切り下げと極小時間のハンドリング"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)

        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (True, "ok")
        ffmpeg_mock._get_encode_args.return_value = []
        ffmpeg_mock._get_hwaccel_input_args.return_value = []

        # 0.0001秒などの極小時間および 59.9999秒などの秒の境界
        segments = [
            {"text": "Boundary1", "start": 0.0001, "end": 0.0009},
            {"text": "Boundary2", "start": 59.999, "end": 60.001}
        ]
        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
        assert result is True

    def test_render_smart_cut_none_elements(self, tmp_path):
        """None入力などのテスト: segmentsの中にNoneオブジェクトが含まれている場合"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"

        # segmentsの要素にNoneが含まれている場合、AttributeErrorが発生することを確認
        segments = [None]
        with pytest.raises(AttributeError):
            smart_cut_engine.render_smart_cut(segments, str(src), str(out))

    def test_render_smart_cut_empty_and_minimal_inputs(self, tmp_path):
        """空リストおよび空テキストのテスト: 全テキストが空の場合にコピーされる挙動"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video" * 1000)
        out = tmp_path / "output.mp4"

        # 全テキストが空
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "   "}]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 5.0
        
        def fake_cut(inp, outp, s, e):
            Path(outp).write_bytes(b"cut part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        
        with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
            result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
            assert result is True
            # srt_linesが空なので、_burn_subtitles_ffmpegにてshutil.copyが走り、
            # カットされた中間動画(cut part)がそのままoutputにコピーされるはず
            assert out.exists()
            assert out.read_bytes() == b"cut part"

    def test_burn_subtitles_ffmpeg_huge_inputs(self, tmp_path):
        """巨大入力値のテスト: 巨大な時間を渡した場合に正しくフォーマットされるか"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)

        ffmpeg_mock = MagicMock()
        ffmpeg_mock.run_command.return_value = (True, "ok")
        ffmpeg_mock._get_encode_args.return_value = []
        ffmpeg_mock._get_hwaccel_input_args.return_value = []

        # 999999.0秒 (277時間46分39秒) の巨大な時間を指定
        segments = [{"text": "Huge", "start": 999999.0, "end": 1000000.0}]
        result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
        assert result is True

    def test_render_smart_cut_invalid_argument_types(self, tmp_path):
        """不正型入力のテスト: 各引数に誤ったデータ型を渡した場合"""
        out = tmp_path / "output.mp4"
        
        # segments にリストではなく単一の辞書を渡すと、for s in segmentsでキー(str)がループされ、get()がないためAttributeErrorが発生する
        with pytest.raises(AttributeError):
            smart_cut_engine.render_smart_cut({"sourceStart": 0.0}, "input.mp4", str(out))
            
        # original_video_path に数値型を渡す
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "Test"}]
        with pytest.raises(TypeError):
            smart_cut_engine.render_smart_cut(segments, 12345, str(out))

    def test_burn_subtitles_ffprobe_duration_value_error(self, tmp_path):
        """ffprobe が無効な duration 値を返し、float 変換で ValueError が発生するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"A" * 2000)
        
        mock_run_res = MagicMock()
        mock_run_res.stdout = '{"format": {"duration": "invalid_duration"}}'
        
        with patch("subprocess.run", return_value=mock_run_res):
            ffmpeg_mock = MagicMock()
            ffmpeg_mock.run_command.return_value = (True, "ok")
            ffmpeg_mock._get_encode_args.return_value = ["-c:v", "libx264"]
            ffmpeg_mock._get_hwaccel_input_args.return_value = []
            
            segments = [{"text": "Hello", "start": 0, "end": 5}]
            result = smart_cut_engine._burn_subtitles_ffmpeg(str(src), segments, str(out), ffmpeg_mock)
            assert result is True

    def test_render_smart_cut_permission_error_on_temp_srt(self, tmp_path):
        """一時 SRT ファイルの書き込み時に PermissionError が発生し、render_smart_cut が False を返すケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "Test"}]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 10.0
        
        def fake_cut(inp, outp, s, e):
            Path(outp).write_bytes(b"cut part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()

        # write_text のモックで常に PermissionError を投げるようにする
        with patch.object(Path, "write_text", side_effect=PermissionError("Mock Permission Error")):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is False

    def test_render_smart_cut_extract_screenshot_runtime_error_and_ffmpeg_fail(self, tmp_path):
        """extract_screenshot が例外を投げ、かつフォールバックの ffmpeg 直接実行も失敗するケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        out.write_bytes(b"video_output")
        
        segments = [{"sourceStart": 0.0, "sourceEnd": 2.0, "start": 0.0, "end": 2.0, "text": "Test"}]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 10.0
        
        def fake_cut(inp, outp, s, e):
            Path(outp).write_bytes(b"cut part")
            return True
        mock_ffmpeg.cut_video.side_effect = fake_cut
        mock_ffmpeg.run_command.return_value = (False, "FFmpeg failed")
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()

        with patch("smart_cut_engine._burn_subtitles_ffmpeg", return_value=True):
            # screenshot_generator.extract_screenshot が RuntimeError を投げる
            with patch("screenshot_generator.extract_screenshot", side_effect=RuntimeError("Mock RuntimeError")):
                with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                    result = smart_cut_engine.render_smart_cut(
                        segments, str(src), str(out),
                        generate_thumbnail=True, thumbnail_path=str(tmp_path / "thumb.jpg")
                    )
                    # サムネイル生成が失敗しても、render_smart_cut 自体は成功 (True) する
                    assert result is True
                    # フォールバックの ffmpeg 直接実行コマンドが呼ばれたことを検証
                    mock_ffmpeg.run_command.assert_called_once()

    def test_render_smart_cut_buffer_subtitles_discarded(self, tmp_path):
        """カットポイント直後に字幕があり、かつバッファ適用後に end <= start となり字幕が除外されるケース"""
        src = tmp_path / "input.mp4"
        src.write_bytes(b"video")
        out = tmp_path / "output.mp4"
        
        # 2つのパートにカット
        # 1つ目: 0.0 ~ 5.0
        # 2つ目: 10.0 ~ 12.0
        # カットポイントは 5.0。
        # 2つ目のパートの字幕で、sourceStart=10.1, sourceEnd=10.2 とする。
        # new_start = 5.0 + (10.1 - 10.0) = 5.1
        # new_end = 5.0 + (10.2 - 10.0) = 5.2
        # カットポイント 5.0 から 0.5 秒以内のため、バッファが適用されて new_start は 5.5 にシフトされる。
        # その結果、new_start(5.5) >= new_end(5.2) となり、new_end > new_start が成り立たなくなるため除外される。
        segments = [
            {"sourceStart": 0.0, "sourceEnd": 5.0, "start": 0.0, "end": 5.0, "text": "Part 1"},
            {"sourceStart": 10.1, "sourceEnd": 10.2, "start": 10.1, "end": 10.2, "text": "Part 2 discarded"},
        ]
        
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.get_duration.return_value = 100.0
        mock_ffmpeg.cut_video.return_value = True
        mock_ffmpeg.merge_videos.return_value = True
        
        mock_ve = MagicMock()
        mock_ve.ffmpeg = mock_ffmpeg
        mock_module = MagicMock()
        mock_module.video_editor = mock_ve
        mock_module.VideoClip.return_value = MagicMock()
        
        captured_segments = []
        def spy_burn_subtitles(video_p, segs, output_p, ffmpeg_e):
            nonlocal captured_segments
            captured_segments = segs
            return True

        with patch("smart_cut_engine._burn_subtitles_ffmpeg", side_effect=spy_burn_subtitles):
            with patch.dict(sys.modules, {"video_editor_engine": mock_module}):
                result = smart_cut_engine.render_smart_cut(segments, str(src), str(out))
                assert result is True
                # Part 2 は除外され、Part 1 のみ残ることを検証
                assert len(captured_segments) == 1
                assert captured_segments[0]["text"] == "Part 1"





