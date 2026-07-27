import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from draft_manager import DraftManager, DraftSettings, DRAFT_PRESETS

def test_init_default():
    # output_dir=None のデフォルト挙動をテスト
    # ディレクトリ作成が実際に行われないように Path.mkdir をモックする
    with patch.object(Path, "mkdir") as mock_mkdir:
        manager = DraftManager()
        # パスが backend/temp/drafts になっていること
        expected_base = Path(__file__).parent.parent / "temp" / "drafts"
        assert manager.output_dir == expected_base
        # ディレクトリ作成が呼ばれたことを検証
        assert mock_mkdir.call_count >= 4  # output_dir, drafts, prefinal, final の各mkdir

def test_init_with_dir(tmp_path):
    # output_dir を指定した場合の挙動をテスト
    output_dir = tmp_path / "custom_drafts"
    manager = DraftManager(str(output_dir))
    assert manager.output_dir == output_dir
    assert (output_dir / "drafts").exists()
    assert (output_dir / "prefinal").exists()
    assert (output_dir / "final").exists()

def test_create_draft_input_not_found(tmp_path):
    manager = DraftManager(str(tmp_path))
    non_existent = tmp_path / "non_existent.mp4"
    result = manager.create_draft(str(non_existent))
    assert result is None

@patch("time.time", return_value=1234567890)
def test_create_draft_success(mock_time, tmp_path):
    manager = DraftManager(str(tmp_path))
    
    # 入力ファイルを作成
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024 * 1024) # 1MB
    
    # 出力ファイルが作成されたとみなすための準備
    output_name = "custom_draft"
    expected_output = tmp_path / "drafts" / f"{output_name}.mp4"
    
    # subprocess.run のモック
    # 成功して出力ファイルが存在する状態を作る
    mock_run = MagicMock()
    mock_run.returncode = 0
    
    # Popen安全モック規約への準拠 (poll, readline の安全応答設定)
    mock_run.poll.return_value = 0
    mock_run.stderr = ""
    mock_run.stdout = ""
    
    def side_effect(*args, **kwargs):
        # コマンド実行のタイミングで出力ファイルを生成する
        expected_output.write_bytes(b"0" * 1024 * 512) # 0.5MB (50%削減)
        return mock_run

    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run:
        # quality="low"
        result = manager.create_draft(str(input_file), quality="low", output_name=output_name)
        assert result == str(expected_output)
        assert expected_output.exists()
        
        # FFmpegの引数チェック
        cmd = mock_sub_run.call_args[0][0]
        assert "ffmpeg" in cmd
        assert str(input_file) in cmd
        assert str(expected_output) in cmd
        assert "-crf" in cmd
        assert "32" in cmd  # low preset crf is 32

        # quality="medium" 且つ output_name=None の場合 (タイムスタンプ自動生成)
        expected_auto_output = tmp_path / "drafts" / "draft_input_medium_1234567890.mp4"
        def side_effect_auto(*args, **kwargs):
            expected_auto_output.write_bytes(b"0" * 1024 * 256)
            return mock_run
            
        mock_sub_run.side_effect = side_effect_auto
        result_auto = manager.create_draft(str(input_file), quality="medium")
        assert result_auto == str(expected_auto_output)
        
        # 存在しない品質を指定した場合はデフォルトのmediumが使われる
        result_invalid = manager.create_draft(str(input_file), quality="invalid_preset")
        # mediumの設定が適用されていることを検証
        cmd_invalid = mock_sub_run.call_args[0][0]
        assert "28" in cmd_invalid  # medium preset crf is 28

        # 元のサイズが0だった場合のサイズ削減率の計算を検証
        zero_input = tmp_path / "zero.mp4"
        zero_input.write_bytes(b"")
        expected_zero_output = tmp_path / "drafts" / "draft_zero_medium_1234567890.mp4"
        def side_effect_zero(*args, **kwargs):
            expected_zero_output.write_bytes(b"")
            return mock_run
        mock_sub_run.side_effect = side_effect_zero
        result_zero = manager.create_draft(str(zero_input), quality="medium")
        assert result_zero == str(expected_zero_output)

def test_create_draft_failure(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "FFmpeg error message"
    mock_run.poll.return_value = 0
    
    with patch("subprocess.run", return_value=mock_run):
        result = manager.create_draft(str(input_file), quality="low")
        assert result is None

def test_create_draft_timeout(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 600)):
        result = manager.create_draft(str(input_file), quality="low")
        assert result is None

def test_create_draft_exception(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    
    with patch("subprocess.run", side_effect=RuntimeError("Unexpected error")):
        with pytest.raises(RuntimeError, match="Unexpected error"):
            manager.create_draft(str(input_file), quality="low")

def test_create_prefinal_no_valid_paths(tmp_path):
    manager = DraftManager(str(tmp_path))
    # 存在しないパスのリスト
    result = manager.create_prefinal([str(tmp_path / "ghost.mp4")])
    assert result is None

def test_create_prefinal_single_path(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft = tmp_path / "drafts" / "draft1.mp4"
    draft.parent.mkdir(parents=True, exist_ok=True)
    draft.write_bytes(b"draft content")
    
    # 1つの場合はコピー
    with patch("shutil.copy", wraps=shutil.copy) as mock_copy:
        result = manager.create_prefinal([str(draft)])
        assert result is not None
        assert Path(result).exists()
        assert Path(result).name.startswith("prefinal_")
        mock_copy.assert_called_once()
        
        # 出力名を指定する場合
        result_named = manager.create_prefinal([str(draft)], output_name="custom_prefinal")
        assert Path(result_named).name == "custom_prefinal.mp4"

def test_create_prefinal_multiple_paths_success(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    
    expected_output = tmp_path / "prefinal" / "custom_prefinal.mp4"
    
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.poll.return_value = 0
    
    def side_effect(*args, **kwargs):
        expected_output.write_bytes(b"merged draft")
        return mock_run
        
    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run:
        result = manager.create_prefinal([str(draft1), str(draft2)], output_name="custom_prefinal")
        assert result == str(expected_output)
        assert expected_output.exists()
        # concat_list.txt が削除されていること
        assert not list(tmp_path.glob("concat_list_*.txt"))
        
        cmd = mock_sub_run.call_args[0][0]
        assert "concat" in cmd

def test_create_prefinal_multiple_paths_failure(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "merge failed"
    mock_run.poll.return_value = 0
    
    with patch("subprocess.run", return_value=mock_run):
        result = manager.create_prefinal([str(draft1), str(draft2)])
        assert result is None
        # concat_list.txt が削除されていること
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_prefinal_multiple_paths_exception(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    
    with patch("subprocess.run", side_effect=RuntimeError("error during merge")):
        with pytest.raises(RuntimeError, match="error during merge"):
            manager.create_prefinal([str(draft1), str(draft2)])
        # 例外時でも concat_list.txt が削除されていること
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_final_prefinal_not_found(tmp_path):
    manager = DraftManager(str(tmp_path))
    non_existent = tmp_path / "prefinal" / "ghost.mp4"
    mp4_path, srt_path = manager.create_final(str(non_existent))
    assert mp4_path is None
    assert srt_path is None

def test_create_final_success_without_srt(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    
    expected_output = tmp_path / "final" / "custom_final.mp4"
    
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.poll.return_value = 0
    
    def side_effect(*args, **kwargs):
        expected_output.write_bytes(b"final output")
        return mock_run
        
    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run:
        mp4_path, srt_path = manager.create_final(str(prefinal), output_name="custom_final")
        assert mp4_path == str(expected_output)
        assert srt_path is None
        assert expected_output.exists()

def test_create_final_success_with_srt(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    
    dummy_srt = tmp_path / "subtitles.srt"
    dummy_srt.write_text("1\n00:00:00,000 -> 00:00:05,000\nHello World\n", encoding="utf-8")
    
    expected_output = tmp_path / "final" / "custom_final.mp4"
    expected_srt = tmp_path / "final" / "custom_final.srt"
    
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.poll.return_value = 0
    
    def side_effect(*args, **kwargs):
        expected_output.write_bytes(b"final output")
        return mock_run
        
    with patch("subprocess.run", side_effect=side_effect):
        mp4_path, srt_path = manager.create_final(
            str(prefinal), 
            output_name="custom_final",
            srt_path=str(dummy_srt)
        )
        assert mp4_path == str(expected_output)
        assert srt_path == str(expected_srt)
        assert expected_output.exists()
        assert expected_srt.exists()
        assert expected_srt.read_text(encoding="utf-8") == dummy_srt.read_text(encoding="utf-8")

def test_create_final_failure(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    
    mock_run = MagicMock()
    mock_run.returncode = 1
    mock_run.stderr = "FFmpeg final error"
    mock_run.poll.return_value = 0
    
    with patch("subprocess.run", return_value=mock_run):
        mp4_path, srt_path = manager.create_final(str(prefinal))
        assert mp4_path is None
        assert srt_path is None

def test_create_final_exception(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    
    with patch("subprocess.run", side_effect=RuntimeError("unhandled error")):
        with pytest.raises(RuntimeError, match="unhandled error"):
            manager.create_final(str(prefinal))

def test_get_stats(tmp_path):
    manager = DraftManager(str(tmp_path))
    
    # 複数ファイルを作成
    # drafts: 3個 (各0.5MB)
    for i in range(3):
        f = tmp_path / "drafts" / f"draft_{i}.mp4"
        f.write_bytes(b"0" * int(0.5 * 1024 * 1024))
        
    # prefinal: 1個 (1.2MB)
    f = tmp_path / "prefinal" / "prefinal_1.mp4"
    f.write_bytes(b"0" * int(1.2 * 1024 * 1024))
    
    # final: 0個 (0MB)
    
    stats = manager.get_stats()
    
    assert stats["drafts"]["count"] == 3
    assert stats["drafts"]["size_mb"] == 1.5
    assert len(stats["drafts"]["files"]) == 3
    
    assert stats["prefinal"]["count"] == 1
    assert stats["prefinal"]["size_mb"] == 1.2
    assert len(stats["prefinal"]["files"]) == 1
    
    assert stats["final"]["count"] == 0
    assert stats["final"]["size_mb"] == 0.0
    assert len(stats["final"]["files"]) == 0


def test_create_draft_os_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    with patch("subprocess.run", side_effect=OSError("Mock OS error")):
        result = manager.create_draft(str(input_file), quality="low")
        assert result is None

def test_create_draft_subprocess_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Mock subprocess error")):
        result = manager.create_draft(str(input_file), quality="low")
        assert result is None

def test_create_prefinal_timeout(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 300)):
        result = manager.create_prefinal([str(draft1), str(draft2)])
        assert result is None
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_prefinal_os_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    with patch("subprocess.run", side_effect=OSError("Mock OS error")):
        result = manager.create_prefinal([str(draft1), str(draft2)])
        assert result is None
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_prefinal_subprocess_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Mock subprocess error")):
        result = manager.create_prefinal([str(draft1), str(draft2)])
        assert result is None
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_prefinal_unexpected_exception(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    with patch("subprocess.run", side_effect=RuntimeError("Mock unexpected error")):
        with pytest.raises(RuntimeError, match="Mock unexpected error"):
            manager.create_prefinal([str(draft1), str(draft2)])
        assert not list(tmp_path.glob("concat_list_*.txt"))

def test_create_final_timeout(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 1800)):
        mp4_path, srt_path = manager.create_final(str(prefinal))
        assert mp4_path is None
        assert srt_path is None

def test_create_final_os_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    with patch("subprocess.run", side_effect=OSError("Mock OS error")):
        mp4_path, srt_path = manager.create_final(str(prefinal))
        assert mp4_path is None
        assert srt_path is None

def test_create_final_subprocess_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    with patch("subprocess.run", side_effect=subprocess.SubprocessError("Mock subprocess error")):
        mp4_path, srt_path = manager.create_final(str(prefinal))
        assert mp4_path is None
        assert srt_path is None

def test_create_final_unexpected_exception(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    with patch("subprocess.run", side_effect=RuntimeError("Mock unexpected error")):
        with pytest.raises(RuntimeError, match="Mock unexpected error"):
            manager.create_final(str(prefinal))


def test_create_prefinal_with_single_quote_in_path(tmp_path):
    manager = DraftManager(str(tmp_path))
    # パスにシングルクォートを含むダミーファイルを作成
    draft1 = tmp_path / "drafts" / "draft'1.mp4"
    draft1.parent.mkdir(parents=True, exist_ok=True)
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft'2.mp4"
    draft2.write_bytes(b"draft2")
    
    expected_output = tmp_path / "prefinal" / "custom_prefinal.mp4"
    
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.poll.return_value = 0
    
    def side_effect(*args, **kwargs):
        concat_files = list(tmp_path.glob("concat_list_*.txt"))
        assert len(concat_files) == 1
        concat_content = concat_files[0].read_text(encoding="utf-8")
        assert "draft'\\''1.mp4" in concat_content
        assert "draft'\\''2.mp4" in concat_content
        
        expected_output.write_bytes(b"merged draft")
        return mock_run
        
    with patch("subprocess.run", side_effect=side_effect):
        result = manager.create_prefinal([str(draft1), str(draft2)], output_name="custom_prefinal")
        assert result == str(expected_output)
        assert expected_output.exists()


def test_create_draft_value_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024)
    with patch("subprocess.run", side_effect=ValueError("Mock value error")):
        with pytest.raises(ValueError, match="Mock value error"):
            manager.create_draft(str(input_file), quality="low")


def test_create_prefinal_type_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    draft1 = tmp_path / "drafts" / "draft1.mp4"
    draft1.write_bytes(b"draft1")
    draft2 = tmp_path / "drafts" / "draft2.mp4"
    draft2.write_bytes(b"draft2")
    with patch("subprocess.run", side_effect=TypeError("Mock type error")):
        with pytest.raises(TypeError, match="Mock type error"):
            manager.create_prefinal([str(draft1), str(draft2)])
        assert not list(tmp_path.glob("concat_list_*.txt"))


def test_create_final_attribute_error(tmp_path):
    manager = DraftManager(str(tmp_path))
    prefinal = tmp_path / "prefinal" / "prefinal.mp4"
    prefinal.parent.mkdir(parents=True, exist_ok=True)
    prefinal.write_bytes(b"prefinal")
    with patch("subprocess.run", side_effect=AttributeError("Mock attribute error")):
        with pytest.raises(AttributeError, match="Mock attribute error"):
            manager.create_final(str(prefinal))


def test_parse_bitrate_to_kbps():
    from draft_manager import _parse_bitrate_to_kbps
    assert _parse_bitrate_to_kbps("500k") == 500
    assert _parse_bitrate_to_kbps("1M") == 1024
    assert _parse_bitrate_to_kbps("8M") == 8192
    assert _parse_bitrate_to_kbps("1000") == 1000
    assert _parse_bitrate_to_kbps(" 3m ") == 3072


def test_create_draft_bufsize_with_m_unit(tmp_path):
    manager = DraftManager(str(tmp_path))
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"0" * 1024 * 1024)
    
    expected_output = tmp_path / "drafts" / "draft_input_medium.mp4"
    
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.poll.return_value = 0
    
    def side_effect(*args, **kwargs):
        expected_output.write_bytes(b"0" * 1024 * 256)
        return mock_run
        
    with patch("subprocess.run", side_effect=side_effect) as mock_sub_run:
        # quality="medium" の bitrate は "1M"
        result = manager.create_draft(str(input_file), quality="medium", output_name="draft_input_medium")
        assert result == str(expected_output)
        
        cmd = mock_sub_run.call_args[0][0]
        # bufsizeが f"{_parse_bitrate_to_kbps('1M')*2}k" = "2048k" になっていることを検証
        assert "-bufsize" in cmd
        bufsize_index = cmd.index("-bufsize")
        assert cmd[bufsize_index + 1] == "2048k"
