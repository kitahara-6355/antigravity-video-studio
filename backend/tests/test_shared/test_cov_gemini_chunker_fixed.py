# -*- coding: utf-8 -*-
"""
Coverage improvement and edge case tests for gemini_chunker_fixed.py.
Covers branches, JSON parsing fallbacks, exception handling (TDR-442), and CLI execution.
"""

import os
import sys
import io
import json
import pytest
import runpy
from pathlib import Path
from unittest.mock import MagicMock, patch

# Adjust sys.path to import backend modules
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class DummyStream:
    def __init__(self):
        self.buffer = io.BytesIO()
    def write(self, msg):
        pass
    def flush(self):
        pass

import gemini_chunker_fixed


@pytest.fixture
def mock_gemini_client():
    """Gemini client をモック化し、元の状態に戻すためのフィクスチャ"""
    original_client = gemini_chunker_fixed.client
    mock = MagicMock()
    gemini_chunker_fixed.client = mock
    yield mock
    gemini_chunker_fixed.client = original_client


@pytest.fixture
def temp_whisper_json(tmp_path):
    """テスト用のダミーWhisper JSONファイルを生成するフィクスチャ"""
    data = {
        "segments": [
            {"start": 1.5, "end": 4.2, "text": "こんにちは、テストです。"},
            {"start": 4.5, "end": 8.0, "text": "これはセマンティックチャンカーのテストコードです。"}
        ]
    }
    file_path = tmp_path / "whisper_test.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return file_path


# =========================================================================
# 1. process_whisper_segments のテスト
# =========================================================================

def test_process_whisper_segments_json_markdown_block(mock_gemini_client, temp_whisper_json):
    """Geminiの応答が ```json で囲まれている場合の正常系テスト"""
    mock_response = MagicMock()
    mock_response.text = (
        "いくつかの前置き文章...\n"
        "```json\n"
        "[\n"
        "  {\"start\": 1.5, \"end\": 4.2, \"text\": \"こんにちは、テストです。\"},\n"
        "  {\"start\": 4.5, \"end\": 8.0, \"text\": \"セマンティックチャンカーテスト。\"}\n"
        "]\n"
        "```\n"
        "後ろの説明文章..."
    )
    mock_gemini_client.models.generate_content.return_value = mock_response

    results = gemini_chunker_fixed.process_whisper_segments(
        str(temp_whisper_json),
        video_theme="テストテーマ",
        batch_size=50
    )

    assert len(results) == 2
    assert results[0]["text"] == "こんにちは、テストです。"
    assert results[1]["text"] == "セマンティックチャンカーテスト。"


def test_process_whisper_segments_generic_markdown_block(mock_gemini_client, temp_whisper_json):
    """Geminiの応答が ``` (json指定なし) で囲まれている場合の正常系テスト"""
    mock_response = MagicMock()
    mock_response.text = (
        "```\n"
        "[\n"
        "  {\"start\": 1.5, \"end\": 8.0, \"text\": \"結合されたテキスト。\"}\n"
        "]\n"
        "```"
    )
    mock_gemini_client.models.generate_content.return_value = mock_response

    results = gemini_chunker_fixed.process_whisper_segments(
        str(temp_whisper_json),
        batch_size=50
    )

    assert len(results) == 1
    assert results[0]["text"] == "結合されたテキスト。"


def test_process_whisper_segments_raw_json(mock_gemini_client, temp_whisper_json):
    """Geminiの応答が囲みなしの生のJSON文字列である場合の正常系テスト"""
    mock_response = MagicMock()
    mock_response.text = "[\n  {\"start\": 1.5, \"end\": 8.0, \"text\": \"生のJSON応答です。\"}\n]"
    mock_gemini_client.models.generate_content.return_value = mock_response

    results = gemini_chunker_fixed.process_whisper_segments(
        str(temp_whisper_json),
        batch_size=1  # 2バッチに分かれるようにバッチサイズを調整
    )

    # 2つのバッチそれぞれが生のJSON応答を返し、結合される
    assert len(results) == 2
    assert results[0]["text"] == "生のJSON応答です。"
    assert results[1]["text"] == "生のJSON応答です。"


def test_process_whisper_segments_empty_segments(mock_gemini_client, tmp_path):
    """入力の segments が空リストの場合のテスト"""
    empty_data = {"segments": []}
    file_path = tmp_path / "empty_whisper.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(empty_data, f)

    results = gemini_chunker_fixed.process_whisper_segments(str(file_path))
    assert results == []
    mock_gemini_client.models.generate_content.assert_not_called()


def test_process_whisper_segments_api_error_fallback(mock_gemini_client, temp_whisper_json):
    """Gemini API呼び出しで例外が発生した場合のフォールバックテスト (TDR-442のカバー)"""
    mock_gemini_client.models.generate_content.side_effect = Exception("API Quota Exceeded")

    results = gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))

    # フォールバックにより、元のセグメントがそのまま返されること
    assert len(results) == 2
    assert results[0]["text"] == "こんにちは、テストです。"
    assert results[1]["text"] == "これはセマンティックチャンカーのテストコードです。"


def test_process_whisper_segments_invalid_json_fallback(mock_gemini_client, temp_whisper_json):
    """Gemini APIが不正なJSONを返して json.loads が失敗した場合のフォールバックテスト (TDR-442のカバー)"""
    mock_response = MagicMock()
    mock_response.text = "不正なレスポンス形式（JSONではないもの）"
    mock_gemini_client.models.generate_content.return_value = mock_response

    results = gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))

    # パースエラーにより、フォールバックして元のセグメントがそのまま返されること
    assert len(results) == 2
    assert results[0]["text"] == "こんにちは、テストです。"
    assert results[1]["text"] == "これはセマンティックチャンカーのテストコードです。"


# =========================================================================
# 2. save_as_srt のテスト
# =========================================================================

def test_save_as_srt(tmp_path):
    """save_as_srt のタイムスタンプ計算とファイル保存の境界値テスト"""
    segments = [
        {"start": 0.0, "end": 0.5, "text": "最初"},
        {"start": 75.321, "end": 125.005, "text": "中間"},
        {"start": 3661.8, "end": 3665.0, "text": "1時間超"}
    ]
    output_file = tmp_path / "output.srt"
    
    gemini_chunker_fixed.save_as_srt(segments, str(output_file))
    
    assert output_file.exists()
    content = output_file.read_text(encoding="utf-8")
    
    # タイムスタンプフォーマットの確認
    # ミリ秒精度が丸め誤差なしで正確に計算されることを確認
    assert "1\n00:00:00,000 --> 00:00:00,500\n最初\n\n" in content
    assert "2\n00:01:15,321 --> 00:02:05,005\n中間\n\n" in content
    assert "3\n01:01:01,800 --> 01:01:05,000\n1時間超\n\n" in content


# =========================================================================
# 3. main のテスト
# =========================================================================

def test_main_file_not_found():
    """存在しないファイルパスを渡した場合に None が返されること"""
    result = gemini_chunker_fixed.main("non_existent_file.json")
    assert result is None


def test_main_success(mock_gemini_client, temp_whisper_json):
    """存在するファイルを渡した際の main 関数の正常実行テスト"""
    mock_response = MagicMock()
    mock_response.text = (
        "```json\n"
        "[\n"
        "  {\"start\": 1.5, \"end\": 8.0, \"text\": \"メイン成功のテキスト\"}\n"
        "]\n"
        "```"
    )
    mock_gemini_client.models.generate_content.return_value = mock_response

    output_srt_path = gemini_chunker_fixed.main(str(temp_whisper_json), "テーマ動画")
    
    assert output_srt_path is not None
    assert Path(output_srt_path).exists()
    assert Path(output_srt_path).suffix == ".srt"
    
    # 期待される出力ファイルの存在確認
    output_json_path = temp_whisper_json.parent / f"{temp_whisper_json.stem}_semantic.json"
    assert output_json_path.exists()
    
    # 内容の簡易検証
    with open(output_json_path, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
    assert len(saved_data["segments"]) == 1
    assert saved_data["segments"][0]["text"] == "メイン成功のテキスト"


# =========================================================================
# 4. CLI 起動 (__main__ ブロック) のテスト
# =========================================================================

def test_cli_insufficient_arguments():
    """引数が不足している場合、エラーメッセージを出して sys.exit(1) すること"""
    test_args = ["gemini_chunker_fixed.py"]
    with patch.object(sys, "argv", test_args):
        # Protect stdout/stderr during runpy module execution
        current_stdout = sys.stdout
        current_stderr = sys.stderr
        sys.stdout = DummyStream()
        sys.stderr = DummyStream()
        try:
            with pytest.raises(SystemExit) as exc_info:
                runpy.run_module("gemini_chunker_fixed", run_name="__main__")
            assert exc_info.value.code == 1
        finally:
            sys.stdout = current_stdout
            sys.stderr = current_stderr


def test_cli_success(mock_gemini_client, temp_whisper_json):
    """十分な引数がある場合、CLIで main が正常実行されること"""
    mock_response = MagicMock()
    mock_response.text = "[]"
    mock_gemini_client.models.generate_content.return_value = mock_response

    # sys.argvをパッチしてモジュール実行
    test_args = ["gemini_chunker_fixed.py", str(temp_whisper_json), "CLIテストテーマ"]
    with patch.object(sys, "argv", test_args):
        # mock get_gemini_client factory function so reload gets the mock client
        with patch("gemini_client_factory.get_gemini_client") as mock_factory:
            mock_factory.return_value = mock_gemini_client
            
            # Protect stdout/stderr during runpy module execution
            current_stdout = sys.stdout
            current_stderr = sys.stderr
            sys.stdout = DummyStream()
            sys.stderr = DummyStream()
            try:
                runpy.run_module("gemini_chunker_fixed", run_name="__main__")
            finally:
                sys.stdout = current_stdout
                sys.stderr = current_stderr
    
    # generate_content が呼ばれたことを検証
    assert mock_gemini_client.models.generate_content.called


# =========================================================================
# 5. 追加の堅牢性・フォールバックテスト
# =========================================================================

def test_import_error_fallback():
    """model_registry のインポート失敗時にデフォルトモデル 'gemini-2.5-flash' が設定されること"""
    # gemini_chunker_fixed を sys.modules から削除して再インポートさせる
    if "gemini_chunker_fixed" in sys.modules:
        del sys.modules["gemini_chunker_fixed"]
    
    class CustomDummy:
        def __init__(self):
            self.buffer = io.BytesIO()
        def write(self, msg): pass
        def flush(self): pass

    # model_registry のインポートを失敗させる
    with patch.dict("sys.modules", {"model_registry": None}):
        # sys.stdout と sys.stderr を完全にダミーにして、インポート時の io.TextIOWrapper によるクローズを回避する
        orig_out = sys.stdout
        orig_err = sys.stderr
        sys.stdout = CustomDummy()
        sys.stderr = CustomDummy()
        try:
            import gemini_chunker_fixed as gcf_fallback
            assert gcf_fallback.DEFAULT_MODEL == "gemini-2.5-flash"
        finally:
            sys.stdout = orig_out
            sys.stderr = orig_err

    # テスト後に正常に再ロードされるように sys.modules を元に戻す
    if "gemini_chunker_fixed" in sys.modules:
        del sys.modules["gemini_chunker_fixed"]
    
    orig_out = sys.stdout
    orig_err = sys.stderr
    sys.stdout = CustomDummy()
    sys.stderr = CustomDummy()
    try:
        import gemini_chunker_fixed
    finally:
        sys.stdout = orig_out
        sys.stderr = orig_err


def test_process_whisper_segments_logging_on_errors(mock_gemini_client, temp_whisper_json):
    """例外発生時に適切な logger 警告またはエラーが出力されること (TD-442の検証)"""
    # 1. JSONパースエラー時のログ検証
    mock_response = MagicMock()
    mock_response.text = "無効なJSONテキスト"
    mock_gemini_client.models.generate_content.return_value = mock_response

    with patch.object(gemini_chunker_fixed.logger, "warning") as mock_warning:
        gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))
        assert mock_warning.called
        # ログメッセージに「JSONパースエラー」が含まれることを検証
        args, _ = mock_warning.call_args
        assert "JSONパースエラー" in args[0]

    # 2. 予期せぬ一般例外発生時のログ検証
    mock_gemini_client.models.generate_content.side_effect = Exception("予期せぬAPIエラー")

    with patch.object(gemini_chunker_fixed.logger, "error") as mock_error:
        gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))
        assert mock_error.called
        args, kwargs = mock_error.call_args
        assert "予期せぬエラー" in args[0]
        assert kwargs.get("exc_info") is True


# =========================================================================
# 6. 新規追加: Client が None の場合のフォールバックテスト
# =========================================================================

def test_process_whisper_segments_client_none_fallback(temp_whisper_json):
    """Gemini client が None の場合（APIキー未設定など）のフォールバックテスト"""
    with patch("gemini_client_factory.get_gemini_client", return_value=None):
        # グローバル client がすでに初期化されている可能性があるため、None に一度リセットする
        original_client = gemini_chunker_fixed.client
        gemini_chunker_fixed.client = None
        try:
            results = gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))
            # クライアントがNoneなので、元のセグメントがそのまま返されること
            assert len(results) == 2
            assert results[0]["text"] == "こんにちは、テストです。"
            assert results[1]["text"] == "これはセマンティックチャンカーのテストコードです。"
        finally:
            gemini_chunker_fixed.client = original_client


def test_package_import_resolves_model_registry():
    """パッケージとして backend.gemini_chunker_fixed がインポートされた際、
    相対インポートにより backend.model_registry.get_model が正常に呼び出され、
    DEFAULT_MODEL が設定されることをテストする。
    """
    import importlib
    import sys
    from pathlib import Path
    
    # backendフォルダ (parents[2]) と project_root (parents[3]) を取得
    backend_dir = Path(__file__).resolve().parents[2]
    project_root = Path(__file__).resolve().parents[3]
    
    # 一度 sys.modules から削除して再インポートさせる
    for mod_name in ["backend.gemini_chunker_fixed", "gemini_chunker_fixed"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    # backend.model_registry をインポートするために sys.path をクリーンにし、project_root を追加する
    original_sys_path_setup = sys.path.copy()
    try:
        sys.path = [p for p in sys.path if "backend" not in p]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        import backend.model_registry
    finally:
        sys.path = original_sys_path_setup

    # backend.model_registry.get_model をパッチ
    with patch("backend.model_registry.get_model", return_value="custom-governed-model") as mock_get_model:
        # sys.path に project_root を残したまま、backend_dir (backendフォルダ) を一時的に除外して、
        # 絶対インポート 'model_registry' が失敗する環境を作る
        original_sys_path = sys.path.copy()
        try:
            if str(backend_dir) in sys.path:
                sys.path.remove(str(backend_dir))
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            
            # backend.gemini_chunker_fixed をインポート
            import backend.gemini_chunker_fixed as bgcf
            
            # 相対インポートで backend.model_registry.get_model が呼ばれ、
            # カスタムモデル名が設定されていることを確認
            assert bgcf.DEFAULT_MODEL == "custom-governed-model"
            mock_get_model.assert_called_once_with("semantic_chunker")
            
        finally:
            sys.path = original_sys_path

    # クリーンアップ
    for mod_name in ["backend.gemini_chunker_fixed", "gemini_chunker_fixed"]:
        if mod_name in sys.modules:
            del sys.modules[mod_name]



# =========================================================================
# 7. CLIにおける標準出力/標準エラーの reconfigure テスト
# =========================================================================

def test_cli_reconfigure_called(temp_whisper_json):
    """CLI起動時に sys.stdout/stderr の reconfigure が呼び出されることを検証"""
    mock_stdout = MagicMock()
    mock_stderr = MagicMock()
    # reconfigure 属性を持つように設定
    mock_stdout.reconfigure = MagicMock()
    mock_stderr.reconfigure = MagicMock()

    test_args = ["gemini_chunker_fixed.py", str(temp_whisper_json)]
    
    with patch.object(sys, "argv", test_args), \
         patch("sys.stdout", mock_stdout), \
         patch("sys.stderr", mock_stderr):
        
        # モジュールを実行
        runpy.run_module("gemini_chunker_fixed", run_name="__main__")
        
        # reconfigure が utf-8 設定で呼び出されたことを確認
        mock_stdout.reconfigure.assert_called_once_with(encoding='utf-8', errors='replace')
        mock_stderr.reconfigure.assert_called_once_with(encoding='utf-8', errors='replace')
        
        # 出力ファイルが生成されたことを確認
        output_srt = temp_whisper_json.parent / f"{temp_whisper_json.stem}_semantic.srt"
        assert output_srt.exists()


def test_cli_no_reconfigure_fallback(temp_whisper_json):
    """reconfigure メソッドを持たないストリームでのフォールバック動作を検証"""
    # reconfigure を持たないダミーストリーム
    class MinimalStream:
        def __init__(self):
            self.buffer = io.BytesIO()
        def write(self, msg): pass
        def flush(self): pass

    mock_stdout = MinimalStream()
    mock_stderr = MinimalStream()

    test_args = ["gemini_chunker_fixed.py", str(temp_whisper_json)]
    
    with patch.object(sys, "argv", test_args), \
         patch("sys.stdout", mock_stdout), \
         patch("sys.stderr", mock_stderr):
        
        # エラーや警告が発生せずに正常実行されることを確認
        runpy.run_module("gemini_chunker_fixed", run_name="__main__")
        
        # sys.stdout/stderr が io.TextIOWrapper で置き換わっていることを確認
        assert isinstance(sys.stdout, io.TextIOWrapper)
        assert isinstance(sys.stderr, io.TextIOWrapper)
        
        # 出力ファイルが生成されたことを確認
        output_srt = temp_whisper_json.parent / f"{temp_whisper_json.stem}_semantic.srt"
        assert output_srt.exists()


# =========================================================================
# 8. 例外処理ハンドリングテスト（reconfigure/TextIOWrapperの例外処理）
# =========================================================================

def test_cli_reconfigure_raises_exception(mock_gemini_client, temp_whisper_json):
    """reconfigure が例外をスローした場合、正常にキャッチされて無視されることを検証"""
    mock_response = MagicMock()
    mock_response.text = "[]"
    mock_gemini_client.models.generate_content.return_value = mock_response

    mock_stdout = MagicMock()
    mock_stderr = MagicMock()
    
    # reconfigure が例外を投げるように設定
    mock_stdout.reconfigure = MagicMock(side_effect=RuntimeError("stdout reconfigure failed"))
    mock_stderr.reconfigure = MagicMock(side_effect=RuntimeError("stderr reconfigure failed"))

    test_args = ["gemini_chunker_fixed.py", str(temp_whisper_json)]
    
    original_client = gemini_chunker_fixed.client
    gemini_chunker_fixed.client = None
    try:
        with patch.object(sys, "argv", test_args), \
             patch("sys.stdout", mock_stdout), \
             patch("sys.stderr", mock_stderr), \
             patch("gemini_client_factory.get_gemini_client", return_value=mock_gemini_client):
            
            # 例外がスローされずに正常実行されることを確認
            runpy.run_module("gemini_chunker_fixed", run_name="__main__")
            
            # 出力ファイルが生成されたことを確認
            output_srt = temp_whisper_json.parent / f"{temp_whisper_json.stem}_semantic.srt"
            assert output_srt.exists()
    finally:
        gemini_chunker_fixed.client = original_client


def test_cli_text_io_wrapper_raises_exception(mock_gemini_client, temp_whisper_json):
    """TextIOWrapper の作成が例外をスローした場合、正常にキャッチされて無視されることを検証"""
    mock_response = MagicMock()
    mock_response.text = "[]"
    mock_gemini_client.models.generate_content.return_value = mock_response

    # reconfigure を持たないダミーストリーム
    class MinimalStream:
        def __init__(self):
            self.buffer = io.BytesIO()
        def write(self, msg): pass
        def flush(self): pass

    mock_stdout = MinimalStream()
    mock_stderr = MinimalStream()

    test_args = ["gemini_chunker_fixed.py", str(temp_whisper_json)]
    
    original_client = gemini_chunker_fixed.client
    gemini_chunker_fixed.client = None
    try:
        with patch.object(sys, "argv", test_args), \
             patch("sys.stdout", mock_stdout), \
             patch("sys.stderr", mock_stderr), \
             patch("io.TextIOWrapper", side_effect=ValueError("Wrapper instantiation failed")), \
             patch("gemini_client_factory.get_gemini_client", return_value=mock_gemini_client):
            
            # 例外がスローされずに正常実行されることを確認
            runpy.run_module("gemini_chunker_fixed", run_name="__main__")
            
            # 出力ファイルが生成されたことを確認
            output_srt = temp_whisper_json.parent / f"{temp_whisper_json.stem}_semantic.srt"
            assert output_srt.exists()
    finally:
        gemini_chunker_fixed.client = original_client


# =========================================================================
# 9. process_whisper_segments での構造不正（TypeError/KeyError/ValueError）テスト
# =========================================================================

def test_process_whisper_segments_type_error_fallback(mock_gemini_client, temp_whisper_json):
    """Geminiの応答が有効なJSON（リスト）だが、要素が辞書ではなく TypeError になる場合のテスト"""
    mock_response = MagicMock()
    # リストだが、要素が辞書ではなく文字列になっており TypeError になる
    mock_response.text = "null"
    mock_gemini_client.models.generate_content.return_value = mock_response

    results = gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))

    # フォールバックにより、元のセグメントがそのまま返されること
    assert len(results) == 2
    assert results[0]["text"] == "こんにちは、テストです。"


def test_process_whisper_segments_key_error_fallback(mock_gemini_client, temp_whisper_json):
    """Geminiの応答に必要なキーが存在せず KeyError になる場合のテスト"""
    mock_response = MagicMock()
    mock_response.text = "[]"
    mock_gemini_client.models.generate_content.return_value = mock_response

    original_loads = json.loads
    def mock_loads(s, *args, **kwargs):
        if "segments" in s:
            return original_loads(s, *args, **kwargs)
        raise KeyError("Simulated KeyError during loads")

    with patch("json.loads", side_effect=mock_loads):
        results = gemini_chunker_fixed.process_whisper_segments(str(temp_whisper_json))
        # KeyError が発生し、フォールバックされること
        assert len(results) == 2
