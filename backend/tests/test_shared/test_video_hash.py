"""
video_hash.py のユニットテスト (分離版・インポートバイパス版)
"""

import sys
import importlib.util
from pathlib import Path
import pytest

# パッケージの __init__.py をロードさせないためのバイパス処理
_backend_dir = Path(__file__).resolve().parent.parent.parent
_video_hash_py = _backend_dir / "subtitle_engine" / "video_hash.py"

_spec = importlib.util.spec_from_file_location("subtitle_engine.video_hash", _video_hash_py)
_video_hash_module = importlib.util.module_from_spec(_spec)
sys.modules["subtitle_engine.video_hash"] = _video_hash_module
_spec.loader.exec_module(_video_hash_module)

# モジュールから関数と変数を展開
compute_video_hash = _video_hash_module.compute_video_hash
get_checkpoint_path = _video_hash_module.get_checkpoint_path
OLD_CHECKPOINT_NAME = _video_hash_module.OLD_CHECKPOINT_NAME


class TestVideoHash:

    def test_compute_video_hash_success(self, tmp_path):
        dummy_file = tmp_path / "dummy_video.mp4"
        dummy_file.write_bytes(b"hello world video content")
        
        h = compute_video_hash(str(dummy_file))
        assert len(h) == 8
        assert h == "ffe49e2f"
        
        h_long = compute_video_hash(str(dummy_file), length=16)
        assert len(h_long) == 16
        assert h_long == "ffe49e2fbe11f970"

    def test_compute_video_hash_file_not_found(self):
        with pytest.raises(FileNotFoundError, match="動画ファイルが見つかりません"):
            compute_video_hash("non_existent_file.mp4")

    def test_get_checkpoint_path(self, tmp_path):
        dummy_file = tmp_path / "dummy_video.mp4"
        dummy_file.write_bytes(b"hello world video content")
        
        expected_path = str(tmp_path / "_whisper_ffe49e2f.jsonl")
        assert get_checkpoint_path(str(dummy_file)) == expected_path

    def test_old_checkpoint_name(self):
        assert OLD_CHECKPOINT_NAME == "_whisper_segments.jsonl"

    def test_compute_video_hash_path_object(self, tmp_path):
        dummy_file = tmp_path / "dummy_video_path.mp4"
        dummy_file.write_bytes(b"path object content")
        
        # pathlib.Path を直接渡す
        h = compute_video_hash(dummy_file)
        assert len(h) == 8
        
        # get_checkpoint_path も pathlib.Path を渡す
        expected_path = str(tmp_path / f"_whisper_{h}.jsonl")
        assert get_checkpoint_path(dummy_file) == expected_path

    def test_compute_video_hash_is_directory(self, tmp_path):
        # tmp_path はディレクトリ
        with pytest.raises(ValueError, match="指定されたパスはファイルではありません"):
            compute_video_hash(tmp_path)

    def test_compute_video_hash_invalid_length(self, tmp_path):
        dummy_file = tmp_path / "dummy_len.mp4"
        dummy_file.write_bytes(b"some content")
        
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            compute_video_hash(dummy_file, length=0)
            
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            compute_video_hash(dummy_file, length=-5)

    def test_compute_video_hash_extreme_length(self, tmp_path):
        dummy_file = tmp_path / "dummy_len.mp4"
        dummy_file.write_bytes(b"some content")
        
        # SHA256の16進数文字数は64文字なので、それ以上を指定しても64文字で制限される
        h = compute_video_hash(dummy_file, length=100)
        assert len(h) == 64

    def test_compute_video_hash_invalid_type(self):
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            compute_video_hash(None)
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            compute_video_hash([1, 2, 3])

    def test_compute_video_hash_permission_error(self, tmp_path):
        dummy_file = tmp_path / "dummy_perm.mp4"
        dummy_file.write_bytes(b"some content")
        
        from unittest.mock import patch
        with patch("builtins.open", side_effect=PermissionError("Permission denied")):
            with pytest.raises(PermissionError, match="動画ファイルの読み取り権限がありません"):
                compute_video_hash(dummy_file)

    def test_compute_video_hash_os_error(self, tmp_path):
        dummy_file = tmp_path / "dummy_os.mp4"
        dummy_file.write_bytes(b"some content")
        
        from unittest.mock import patch
        with patch("builtins.open", side_effect=OSError("I/O error")):
            with pytest.raises(OSError, match="動画ファイルの読み込み中にI/Oエラーが発生しました"):
                compute_video_hash(dummy_file)

    def test_get_checkpoint_path_resolved(self, tmp_path):
        # 相対パスや .. を含むパスを resolve して一貫した絶対パスが返ることを検証
        dummy_file = tmp_path / "dummy_video.mp4"
        dummy_file.write_bytes(b"hello world video content")
        
        import os
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            rel_path = "dummy_video.mp4"
            expected_path = str((tmp_path / f"_whisper_ffe49e2f.jsonl").resolve())
            assert get_checkpoint_path(rel_path) == expected_path
            
            # .. を含むパス
            dotdot_path = f"./../{tmp_path.name}/dummy_video.mp4"
            assert get_checkpoint_path(dotdot_path) == expected_path
        finally:
            os.chdir(orig_cwd)

    def test_compute_video_hash_invalid_length_type(self, tmp_path):
        dummy_file = tmp_path / "dummy_len.mp4"
        dummy_file.write_bytes(b"some content")
        
        with pytest.raises(TypeError, match="ハッシュの長さは整数でなければなりません"):
            compute_video_hash(dummy_file, length="8")
        with pytest.raises(TypeError, match="ハッシュの長さは整数でなければなりません"):
            compute_video_hash(dummy_file, length=8.5)

    def test_get_checkpoint_path_invalid_type(self):
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            get_checkpoint_path(None)
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            get_checkpoint_path([1, 2])

    def test_compute_sha256_from_stream(self):
        import io
        stream = io.BytesIO(b"stream content")
        _compute_sha256_from_stream = _video_hash_module._compute_sha256_from_stream
        h = _compute_sha256_from_stream(stream)
        assert h == "365ec5d3b78db79a4bc1fd4bef3ea8786aa4a5b571bea3ef6ac7c67fd82f5deb"


    def test_generate_checkpoint_filename(self):
        _generate_checkpoint_filename = _video_hash_module._generate_checkpoint_filename
        assert _generate_checkpoint_filename("abcdef") == "_whisper_abcdef.jsonl"

    def test_validate_video_path_type_directly(self):
        _validate_video_path_type = _video_hash_module._validate_video_path_type
        # 正常系 (検証エラーが発生しないこと)
        _validate_video_path_type("test_path.mp4")
        _validate_video_path_type(Path("test_path.mp4"))
        
        # 異常系
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            _validate_video_path_type(123)
        with pytest.raises(TypeError, match="動画ファイルパスは str または Path でなければなりません"):
            _validate_video_path_type(None)

    def test_validate_hash_length_param_directly(self):
        _validate_hash_length_param = _video_hash_module._validate_hash_length_param
        # 正常系 (検証エラーが発生しないこと)
        _validate_hash_length_param(1)
        _validate_hash_length_param(8)
        _validate_hash_length_param(64)
        
        # 異常系: 型エラー
        with pytest.raises(TypeError, match="ハッシュの長さは整数でなければなりません"):
            _validate_hash_length_param("8")
        with pytest.raises(TypeError, match="ハッシュの長さは整数でなければなりません"):
            _validate_hash_length_param(8.5)
            
        # 異常系: 値エラー
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            _validate_hash_length_param(0)
        with pytest.raises(ValueError, match="ハッシュの長さは正の整数でなければなりません"):
            _validate_hash_length_param(-10)

    def test_normalize_to_absolute_path_directly(self):
        _normalize_to_absolute_path = _video_hash_module._normalize_to_absolute_path
        # 相対パスが絶対パスとして正規化されること
        normalized = _normalize_to_absolute_path("dummy.mp4")
        assert normalized.is_absolute()
        assert normalized.name == "dummy.mp4"

    def test_compute_video_hash_max_length(self, tmp_path):
        dummy_file = tmp_path / "dummy_max.mp4"
        dummy_file.write_bytes(b"content for max hash length test")
        
        # SHA256ハッシュ最大文字数である64文字が完全に取得できること
        h = compute_video_hash(dummy_file, length=64)
        assert len(h) == 64
        # 64文字を超えて指定しても64文字のままスライスされること
        h_over = compute_video_hash(dummy_file, length=70)
        assert len(h_over) == 64
        assert h == h_over

    def test_compute_video_hash_empty_file(self, tmp_path):
        # 0バイトの空ファイルに対するハッシュ算出
        empty_file = tmp_path / "empty_video.mp4"
        empty_file.write_bytes(b"")
        
        h = compute_video_hash(empty_file, length=8)
        assert len(h) == 8
        # 空文字列のSHA256ハッシュの先頭8文字は e3b0c442 であることを検証
        assert h == "e3b0c442"


