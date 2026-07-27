import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import shutil
import os

from backend.fix_video_quality import fix_and_concat, run_ffmpeg

def test_run_ffmpeg_success():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        res = run_ffmpeg(["ffmpeg", "-version"], "Test Success")
        assert res is True
        mock_run.assert_called_once()

def test_run_ffmpeg_failure():
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error message"
        mock_run.return_value = mock_result
        
        res = run_ffmpeg(["ffmpeg", "-version"], "Test Failure")
        assert res is False
        mock_run.assert_called_once()

def test_fix_and_concat_success(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
        mock_run.return_value = mock_result
        
        final_output_path = base_dir / "soul_narrative_FIXED.mp4"
        def side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 0:
                out_path = Path(cmd[-1])
                if out_path.suffix in ('.mp4', '.txt'):
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if not out_path.exists():
                        out_path.write_text("mock video output", encoding="utf-8")
            return mock_result
        mock_run.side_effect = side_effect
        
        output = fix_and_concat(base_dir=base_dir)
        
        assert output == str(final_output_path)
        assert final_output_path.exists()

def test_fix_and_concat_already_exists(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    
    # 事前に fixed ファイルを作成しておくことでexists() == True の分岐を通す
    (fixed_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (fixed_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (fixed_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
        mock_run.return_value = mock_result
        
        final_output_path = base_dir / "soul_narrative_FIXED.mp4"
        def side_effect(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 0:
                out_path = Path(cmd[-1])
                if out_path.suffix in ('.mp4', '.txt'):
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    if not out_path.exists():
                        out_path.write_text("mock video output", encoding="utf-8")
            return mock_result
        mock_run.side_effect = side_effect
        
        output = fix_and_concat(base_dir=base_dir)
        
        assert output == str(final_output_path)
        assert final_output_path.exists()
        
        # 呼ばれるのは結合(Concat)と品質チェック(probe)のみ（シーン2, 3のFFmpegはスキップされるはず）
        calls = mock_run.call_args_list
        assert len(calls) == 2

def test_fix_and_concat_failure(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "concat failed"
        mock_run.return_value = mock_result
        
        output = fix_and_concat(base_dir=base_dir)
        assert output is None

def test_fix_and_concat_default_base_dir_env(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    # 環境変数をセットしてテスト
    with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE": str(base_dir)}):
        with patch("subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
            mock_run.return_value = mock_result
            
            final_output_path = base_dir / "soul_narrative_FIXED.mp4"
            def side_effect(cmd, *args, **kwargs):
                if isinstance(cmd, list) and len(cmd) > 0:
                    out_path = Path(cmd[-1])
                    if out_path.suffix in ('.mp4', '.txt'):
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        if not out_path.exists():
                            out_path.write_text("mock video output", encoding="utf-8")
                return mock_result
            mock_run.side_effect = side_effect
            
            output = fix_and_concat(base_dir=None)
            assert output == str(final_output_path)

def test_fix_and_concat_default_base_dir_no_env(tmp_path):
    # 環境変数がなく、__file__ からの相対パスが使用される場合のテスト
    # モック対象ディレクトリを作成するため、Path(__file__).resolve().parent.parent から算出されるパスを mock
    mock_base = tmp_path / "video-automation"
    phase1_dir = mock_base / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = mock_base / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")

    # Path(__file__) の挙動をモックするために、 Path("backend/fix_video_quality.py") をフックする
    # あるいは単に Path("backend/fix_video_quality.py").resolve().parent.parent の戻り値を mock_base にする
    with patch.dict(os.environ):
        if "VIDEO_AUTOMATION_BASE" in os.environ:
            del os.environ["VIDEO_AUTOMATION_BASE"]
            
        with patch.object(Path, "resolve") as mock_resolve:
            # resolve が mock_base / "backend" / "fix_video_quality.py" を返すようにする
            mock_resolve.return_value = mock_base / "backend" / "fix_video_quality.py"
            
            with patch("subprocess.run") as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
                mock_run.return_value = mock_result
                
                final_output_path = mock_base / "soul_narrative_FIXED.mp4"
                def side_effect(cmd, *args, **kwargs):
                    if isinstance(cmd, list) and len(cmd) > 0:
                        out_path = Path(cmd[-1])
                        if out_path.suffix in ('.mp4', '.txt'):
                            out_path.parent.mkdir(parents=True, exist_ok=True)
                            if not out_path.exists():
                                out_path.write_text("mock video output", encoding="utf-8")
                    return mock_result
                mock_run.side_effect = side_effect
                
                output = fix_and_concat(base_dir=None)
                assert output == str(final_output_path)

@patch("subprocess.run")
def test_fix_video_quality_main_flow(mock_run, tmp_path):
    import runpy
    import sys
    
    # テンポラリベースの構築
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    # ffmpeg / ffprobe のモック
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
    mock_run.return_value = mock_result
    
    # rename/copy時の最終出力ファイルを生成するside_effectを設定
    final_output_path = base_dir / "soul_narrative_FIXED.mp4"
    def side_effect(cmd, *args, **kwargs):
        if isinstance(cmd, list) and len(cmd) > 0:
            out_path = Path(cmd[-1])
            if out_path.suffix in ('.mp4', '.txt'):
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if not out_path.exists():
                    out_path.write_text("mock video output", encoding="utf-8")
        return mock_result
    mock_run.side_effect = side_effect
    
    # 環境変数とargvのモック
    with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE": str(base_dir)}):
        if "backend.fix_video_quality" in sys.modules:
            del sys.modules["backend.fix_video_quality"]
            
        with patch.object(sys, "argv", ["backend/fix_video_quality.py"]):
            runpy.run_module("backend.fix_video_quality", run_name="__main__")
            
    assert final_output_path.exists()


@patch("subprocess.run")
def test_fix_video_quality_main_flow_failed(mock_run, tmp_path):
    import runpy
    import sys
    
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    # 失敗のモック
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "error in concat"
    mock_run.return_value = mock_result
    
    with patch.dict(os.environ, {"VIDEO_AUTOMATION_BASE": str(base_dir)}):
        if "backend.fix_video_quality" in sys.modules:
            del sys.modules["backend.fix_video_quality"]
            
        with patch.object(sys, "argv", ["backend/fix_video_quality.py"]):
            runpy.run_module("backend.fix_video_quality", run_name="__main__")


def test_fix_and_concat_scene02_failed(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result_fail = MagicMock()
        mock_result_fail.returncode = 1
        mock_result_fail.stderr = "scene 02 ffmpeg failed"
        mock_run.return_value = mock_result_fail
        
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene01_copy_failed(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene02_final.mp4").write_text("mock video 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock video 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock video 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene01_copy_oserror(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock video 1", encoding="utf-8")
    
    with patch("shutil.copy", side_effect=OSError("Permission denied")):
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene02_source_missing(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    output = fix_and_concat(base_dir=base_dir)
    assert output is None


def test_fix_and_concat_scene02_fixed_missing_after_processing(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene03_source_missing(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    
    output = fix_and_concat(base_dir=base_dir)
    assert output is None


def test_fix_and_concat_scene03_processing_failed(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene03_fixed_missing_after_processing(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_scene04_source_missing(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (fixed_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    
    output = fix_and_concat(base_dir=base_dir)
    assert output is None


def test_fix_and_concat_scene04_copy_oserror(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (fixed_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock 4", encoding="utf-8")
    
    import shutil
    original_copy = shutil.copy
    def mock_copy(src, dst):
        if "scene04_final" in str(dst):
            raise OSError("disk full")
        return original_copy(src, dst)
        
    with patch("shutil.copy", side_effect=mock_copy):
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_missing_expected_scene(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    fixed_dir = base_dir / "backend" / "temp" / "fixed_unified"
    fixed_dir.mkdir(parents=True, exist_ok=True)
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (fixed_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (fixed_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock 4", encoding="utf-8")
    
    original_copy = shutil.copy
    def mock_copy(src, dst):
        res = original_copy(src, dst)
        if "scene01_final" in str(dst):
            os.remove(dst)
        return res
        
    with patch("shutil.copy", side_effect=mock_copy):
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_fix_and_concat_final_concat_failed(tmp_path):
    base_dir = tmp_path / "video-automation"
    phase1_dir = base_dir / "backend" / "temp" / "phase1_final"
    phase1_dir.mkdir(parents=True, exist_ok=True)
    scene03_final_dir = base_dir / "backend" / "temp" / "scene03_final"
    scene03_final_dir.mkdir(parents=True, exist_ok=True)
    
    (phase1_dir / "scene01_final.mp4").write_text("mock 1", encoding="utf-8")
    (phase1_dir / "scene02_final.mp4").write_text("mock 2", encoding="utf-8")
    (scene03_final_dir / "scene03_final.mp4").write_text("mock 3", encoding="utf-8")
    (phase1_dir / "scene04_final.mp4").write_text("mock 4", encoding="utf-8")
    
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, *args, **kwargs):
            mock_res = MagicMock()
            if isinstance(cmd, list) and "concat" in cmd:
                mock_res.returncode = 1
                mock_res.stderr = "concat error"
            else:
                mock_res.returncode = 0
                mock_res.stdout = '{"streams": [], "format": {"duration": "10.0"}}'
                if isinstance(cmd, list) and len(cmd) > 0:
                    out_path = Path(cmd[-1])
                    if out_path.suffix in ('.mp4', '.txt'):
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        if not out_path.exists():
                            out_path.write_text("mock video output", encoding="utf-8")
            return mock_res
            
        mock_run.side_effect = side_effect
        output = fix_and_concat(base_dir=base_dir)
        assert output is None


def test_run_ffmpeg_exception():
    with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
        with pytest.raises(FileNotFoundError):
            run_ffmpeg(["ffmpeg", "-version"], "Test Exception")


def test_fix_and_concat_invalid_base_dir_type():
    """base_dirに不正な型（整数）を渡した場合、TypeErrorが発生することを確認"""
    with pytest.raises(TypeError):
        fix_and_concat(base_dir=12345)


def test_fix_and_concat_empty_string_base_dir():
    """base_dirに空文字列を渡した場合、ソースファイルが見つからずNoneが返ることを確認"""
    res = fix_and_concat(base_dir="")
    assert res is None


def test_run_ffmpeg_empty_cmd():
    """cmdが空リストの場合、WindowsではOSErrorが発生することを確認"""
    with pytest.raises(OSError):
        run_ffmpeg([], "Empty command")


def test_run_ffmpeg_invalid_cmd_type():
    """cmdに不正な型（None）を渡した場合、TypeErrorが発生することを確認"""
    with pytest.raises(TypeError):
        run_ffmpeg(None, "Invalid cmd type")


def test_run_ffmpeg_description_none():
    """descriptionがNoneの場合でも、例外が発生せず正常に処理されることを確認"""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        res = run_ffmpeg(["ffmpeg", "-version"], None)
        assert res is True
        mock_run.assert_called_once()


def test_run_ffmpeg_huge_description():
    """descriptionが非常に長い文字列の場合でも、例外が発生せず正常に処理されることを確認"""
    huge_desc = "A" * 10000
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        
        res = run_ffmpeg(["ffmpeg", "-version"], huge_desc)
        assert res is True
