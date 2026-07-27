import sys
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock, mock_open
import subprocess

# 対象モジュールのインポート
sys.path.append(str(Path(__file__).parent.parent))
from trim_segments import cut_segments

def test_cut_segments_success(tmp_path):
    # テスト用ディレクトリ構造の準備
    # input_videoが存在するようにダミーファイルを置く
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()
    
    # subprocess.runをモックする
    def mock_run(cmd, *args, **kwargs):
        # cmd[0]がffmpegの場合、出力先ファイル（cmd[-1]）を作成する
        if cmd[0] == "ffmpeg":
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            # ダミーの動画ファイル（1MB相当）を作成して、stat().st_sizeが動くようにする
            out_file.write_bytes(b"\x00" * (1024 * 1024))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        elif cmd[0] == "ffprobe":
            # ffprobeの出力をシミュレート（duration = 2400.5 秒）
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="2400.5\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run) as mock_subrun:
        result = cut_segments(base_dir=tmp_path)
        
        # 検証
        assert result == str(tmp_path / "soul_narrative_FINAL_EDITED.mp4")
        # 結合リスト（concat.txt）が作られ、中身が正しいか確認
        concat_txt = tmp_path / "backend" / "temp" / "trimmed_segments" / "concat.txt"
        assert concat_txt.exists()
        content = concat_txt.read_text(encoding="utf-8")
        assert "segment1.mp4" in content
        assert "segment2.mp4" in content
        assert "segment3.mp4" in content

        # 呼び出し回数の確認
        # セグメント3回 + 結合1回 + duration確認1回 = 計5回
        assert mock_subrun.call_count == 5

def test_cut_segments_extract_failed(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # ffmpegの最初の呼び出しで失敗させる
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg" and "segment1.mp4" in cmd[-1]:
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="FFmpeg syntax error")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        assert result is False

def test_cut_segments_concat_failed(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # セグメント抽出は成功するが、結合で失敗させる
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            if "concat" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Concat failed")
            else:
                out_file = Path(cmd[-1])
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(b"\x00")
                return subprocess.CompletedProcess(args=cmd, returncode=0)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        assert result is None

def test_cut_segments_ffprobe_failed(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # ffprobeのみが失敗するケース
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        elif cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Probe failed")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        # 関数自体は出力ファイルのパスを返す
        assert result == str(tmp_path / "soul_narrative_FINAL_EDITED.mp4")

def test_main_block():
    # runpy で trim_segments をスクリプトとして動かすテスト
    
    # 1. 正常終了ケース (SUCCESSを表示させる)
    def mock_run_success(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        elif cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="120.0\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run_success) as mock_subrun, \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.stat") as mock_stat:
        
        # stat() が返すオブジェクトの st_size を 1MB にする
        mock_stat.return_value.st_size = 1024 * 1024
        
        with patch("builtins.open", mock_open()):
            import runpy
            runpy.run_module("trim_segments", run_name="__main__")
            assert mock_subrun.call_count == 5

    # 2. 異常終了ケース (FAILEDを表示させる)
    def mock_run_fail(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="Error")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run_fail) as mock_subrun, \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("pathlib.Path.exists", return_value=True):
        
        # sys.modulesから削除して、確実にrunpyで再評価されるようにする
        if "trim_segments" in sys.modules:
            del sys.modules["trim_segments"]
            
        import runpy
        runpy.run_module("trim_segments", run_name="__main__")

def test_cut_segments_input_not_found(tmp_path):
    # input_video (soul_narrative_FIXED.mp4) をtouchしない
    result = cut_segments(base_dir=tmp_path)
    # 早期エラーリターンで False になるはず
    assert result is False

def test_cut_segments_ffprobe_parse_value_error(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # ffprobeは成功するが出力が不正 (ValueErrorを引き起こす)
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        elif cmd[0] == "ffprobe":
            # float()でパースできない文字列を出力
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="not_a_float\n", stderr="")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        # ValueErrorをキャッチしてクラッシュせず、出力ファイルパスを返すはず
        assert result == str(tmp_path / "soul_narrative_FINAL_EDITED.mp4")

def test_cut_segments_unexpected_exception_tdr(tmp_path):
    # base_dirに不正な型(整数)を渡すことで、Pathオブジェクト生成時に TypeError を発生させ、
    # 全体を囲む try-except (具体例外) でキャッチされることを検証する。
    with patch("agents.memory.technical_debt.TechnicalDebtStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        
        result = cut_segments(base_dir=12345)
        
        assert result is None
        # TDRに登録されたかアサート
        mock_store.register_debt.assert_called_once()
        args, kwargs = mock_store.register_debt.call_args
        assert kwargs["category"] == "MINOR_INFRA"
        assert "except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as e:" in kwargs["pattern"]
        assert "expected type" in kwargs["notes"] or "argument" in kwargs["notes"] or "Unexpected exception caught" in kwargs["notes"]

def test_cut_segments_mkdir_oserror(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    with patch("pathlib.Path.mkdir", side_effect=OSError("Failed to mkdir")):
        result = cut_segments(base_dir=tmp_path)
        assert result is False

def test_cut_segments_ffmpeg_subprocess_error(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Subprocess failed")):
        result = cut_segments(base_dir=tmp_path)
        assert result is False

def test_cut_segments_write_concat_oserror(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # セグメント抽出が正常に動くように mock_run を設定
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"\x00" * (1024 * 1024))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    # open が concat.txt に対して OSError を投げるようにする
    original_open = open
    def mock_open_func(file, mode="r", *args, **kwargs):
        if "concat.txt" in str(file):
            raise OSError("Permission denied")
        return original_open(file, mode, *args, **kwargs)

    with patch("subprocess.run", side_effect=mock_run), \
         patch("builtins.open", side_effect=mock_open_func):
        result = cut_segments(base_dir=tmp_path)
        assert result is False

def test_cut_segments_concat_subprocess_error(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # セグメント抽出は成功するが、結合で SubprocessError を投げる
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            if "concat" in cmd:
                raise subprocess.SubprocessError("Concat crash")
            else:
                out_file = Path(cmd[-1])
                out_file.parent.mkdir(parents=True, exist_ok=True)
                out_file.write_bytes(b"\x00")
                return subprocess.CompletedProcess(args=cmd, returncode=0)
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        assert result is None

def test_cut_segments_ffprobe_subprocess_error(tmp_path):
    input_video = tmp_path / "soul_narrative_FIXED.mp4"
    input_video.touch()

    # ffprobeで SubprocessError を投げる
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "ffmpeg":
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"\x00")
            return subprocess.CompletedProcess(args=cmd, returncode=0)
        elif cmd[0] == "ffprobe":
            raise subprocess.SubprocessError("ffprobe crash")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    with patch("subprocess.run", side_effect=mock_run):
        result = cut_segments(base_dir=tmp_path)
        assert result == str(tmp_path / "soul_narrative_FINAL_EDITED.mp4")

def test_cut_segments_unexpected_exception_tdr_error_handling(tmp_path):
    # TDR登録時に KeyError を発生させる
    with patch("agents.memory.technical_debt.TechnicalDebtStore") as mock_store_cls:
        mock_store = MagicMock()
        mock_store.register_debt.side_effect = KeyError("Mock TDR write error")
        mock_store_cls.return_value = mock_store
        
        # 例外処理内で発生した KeyError がキャッチされ、クラッシュせずに None を返すことを確認
        result = cut_segments(base_dir=12345)
        assert result is None
        mock_store.register_debt.assert_called_once()
