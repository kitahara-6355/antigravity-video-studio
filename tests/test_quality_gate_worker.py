# -*- coding: utf-8 -*-
import pytest
import subprocess
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

from agents.pipeline_types import PipelineContext, StageResult
from agents.workers.quality_gate_worker import QualityGateWorker

# --- フィクスチャ定義 ---

@pytest.fixture
def base_context():
    ctx = PipelineContext(
        video_path="/dummy/video.mp4",
        preview_path="/dummy/preview.mp4",
        target_minutes=10,
        segments=[{"text": "テスト", "start": 0.0, "end": 2.0}],
    )
    ctx.thumbnail_path = "/dummy/thumbnail.jpg"
    return ctx

@pytest.fixture
def worker():
    return QualityGateWorker()

# --- テストケース定義 ---

def test_worker_initialization(worker):
    assert worker.name == "品質チェック"
    assert worker.icon == "✅"
    assert worker.get_definition_of_done() == "品質スコア90点以上かつ致命的エラーゼロ"

def test_verify_method(worker):
    mock_res = StageResult(
        stage_name=worker.name,
        success=True,
        detail="スコア: 95点",
        data={"score": 95},
        duration_seconds=1.0
    )
    assert worker.verify(mock_res) is True

    mock_res_fail = StageResult(
        stage_name=worker.name,
        success=False,
        detail="スコア: 85点",
        data={"score": 85},
        duration_seconds=1.0
    )
    assert worker.verify(mock_res_fail) is False

@pytest.mark.asyncio
async def test_execute_basic_flow_no_plugins(worker, base_context):
    with patch.dict("sys.modules", {"quality_gate_plugins": None}):
        base_context.preview_path = "/dummy/non_existent_preview.mp4"
        base_context.thumbnail_path = None
        if hasattr(base_context, "metadata"):
            del base_context.metadata

        res = await worker.execute(base_context)
        
        assert res.success is False
        assert res.data["score"] < 90
        assert any("プレビューファイルが存在しない" in f for f in res.data["feedback"])

@pytest.mark.asyncio
async def test_execute_basic_flow_with_preview_exists(worker, base_context):
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        
        mock_stat.return_value.st_size = 5000
        base_context.thumbnail_path = None
        
        with patch.object(worker, "_ffprobe_physical_check", side_effect=OSError("ffprobe missing")), \
             patch.dict("sys.modules", {"quality_gate_plugins": None}):
            
            res = await worker.execute(base_context)
            assert res.data["score"] == 80

@pytest.mark.asyncio
async def test_execute_ffprobe_warning_and_success(worker, base_context):
    # FFprobeで警告が発生しつつ、全体は成功（PASS）するケース
    ffprobe_res = {"failures": [], "warnings": ["ffprobe spec warning"]}
    thumb_res = {"failures": [], "warnings": []}
    plugin_res = {"total_deductions": 0, "feedback": [], "category_report": [], "category_scores": {}}
    
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", return_value=thumb_res), \
         patch.dict("sys.modules", {"quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins), "template_config": None}):
        
        res = await worker.execute(base_context)
        assert res.success is True
        assert res.data["score"] == 100
        assert any("⚠️ FFprobe: ffprobe spec warning" in f for f in res.data["feedback"])

@pytest.mark.asyncio
async def test_execute_thumbnail_warning_and_success(worker, base_context):
    # サムネイル物理チェックで警告が発生しつつ、全体は成功（PASS）するケース
    ffprobe_res = {"failures": [], "warnings": []}
    thumb_res = {"failures": [], "warnings": ["thumbnail size warning"]}
    plugin_res = {"total_deductions": 5, "feedback": ["plugin warning"], "category_report": [], "category_scores": {}}
    
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", return_value=thumb_res), \
         patch.dict("sys.modules", {"quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins), "template_config": None}):
        
        res = await worker.execute(base_context)
        assert res.success is True
        assert res.data["score"] == 95  # 100 - 5
        assert any("⚠️ サムネイル: thumbnail size warning" in f for f in res.data["feedback"])
        assert any("plugin warning" in f for f in res.data["feedback"])

@pytest.mark.asyncio
async def test_execute_thumbnail_exception_handled(worker, base_context):
    # サムネイル物理チェックで例外が発生した場合のハンドリング
    ffprobe_res = {"failures": [], "warnings": []}
    plugin_res = {"total_deductions": 0, "feedback": [], "category_report": [], "category_scores": {}}
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", side_effect=RuntimeError("thumbnail read error")), \
         patch.dict("sys.modules", {"quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins), "template_config": None}):
        
        res = await worker.execute(base_context)
        assert res.success is True
        assert any("⚠️ サムネイル検証実行不可: thumbnail read error" in f for f in res.data["feedback"])

@pytest.mark.asyncio
async def test_execute_plugins_success_and_import_errors(worker, base_context):
    # プラグインとテンプレート設定のインポート成功ケース
    ffprobe_res = {"failures": [], "warnings": []}
    thumb_res = {"failures": [], "warnings": []}
    plugin_res = {"total_deductions": 10, "feedback": ["plugin error"], "category_report": [{"cat": "text"}], "category_scores": {"text": 90}}
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    mock_tc = MagicMock()
    
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", return_value=thumb_res), \
         patch.dict("sys.modules", {
             "quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins),
             "template_config": MagicMock(template_config=mock_tc)
         }):
        
        res = await worker.execute(base_context)
        assert res.success is True
        assert res.data["score"] == 90
        assert res.data["category_report"] == [{"cat": "text"}]
        assert res.data["category_scores"] == {"text": 90}

@pytest.mark.asyncio
async def test_execute_basic_flow_small_preview_file(worker, base_context):
    # プレビューサイズが 1024 バイト未満の場合の basic check
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        
        mock_stat.return_value.st_size = 500  # 1024未満
        base_context.thumbnail_path = None
        
        with patch.object(worker, "_ffprobe_physical_check", side_effect=OSError("ffprobe missing")), \
             patch.dict("sys.modules", {"quality_gate_plugins": None}):
            
            res = await worker.execute(base_context)
            assert res.data["score"] == 50  # 100 - pluginsなし(20) - サイズ小(30) = 50
            assert any("ファイルサイズが異常に小さい" in f for f in res.data["feedback"])

# --- FFprobe 物理検証テスト ---

def test_ffprobe_physical_check_no_preview(worker, base_context):
    base_context.preview_path = None
    res = worker._ffprobe_physical_check(base_context)
    assert len(res["failures"]) == 1
    assert "プレビューファイルが存在しない" in res["failures"][0]["message"]

@patch("subprocess.run")
def test_ffprobe_physical_check_success(mock_run, worker, base_context):
    ffprobe_data = {
        "format": {
            "duration": "600.0",
            "size": "50000000"
        },
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"}
        ]
    }
    
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(ffprobe_data),
        stderr=""
    )
    
    with patch.object(Path, "exists", return_value=True):
        res = worker._ffprobe_physical_check(base_context)
        assert len(res["failures"]) == 0
        assert len(res["warnings"]) == 0

@patch("subprocess.run")
def test_ffprobe_physical_check_failures_and_warnings(mock_run, worker, base_context):
    ffprobe_data = {
        "format": {
            "duration": "2400.0",
            "size": "5000000"
        },
        "streams": []
    }
    
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(ffprobe_data),
        stderr=""
    )
    
    with patch.object(Path, "exists", return_value=True):
        res = worker._ffprobe_physical_check(base_context)
        
        failures = [f["message"] for f in res["failures"]]
        assert any("出力尺異常" in f for f in failures)
        assert any("出力尺が目標の" in f for f in failures)
        assert any("ファイルサイズ異常" in f for f in failures)
        assert any("音声トラックが存在しない" in f for f in failures)
        assert any("映像ストリームが存在しない" in f for f in failures)

@patch("subprocess.run")
def test_ffprobe_physical_check_duration_warning(mock_run, worker, base_context):
    ffprobe_data = {
        "format": {
            "duration": "840.0",
            "size": "20000000"
        },
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio"}
        ]
    }
    
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(ffprobe_data),
        stderr=""
    )
    
    with patch.object(Path, "exists", return_value=True):
        res = worker._ffprobe_physical_check(base_context)
        assert len(res["failures"]) == 0
        assert len(res["warnings"]) == 1
        assert "出力尺やや乖離" in res["warnings"][0]

@patch("subprocess.run")
def test_ffprobe_physical_check_cmd_error(mock_run, worker, base_context):
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="ffprobe error details"
    )
    
    with patch.object(Path, "exists", return_value=True):
        with pytest.raises(subprocess.SubprocessError) as excinfo:
            worker._ffprobe_physical_check(base_context)
        assert "ffprobe failed: ffprobe error details" in str(excinfo.value)

@patch("subprocess.run")
def test_ffprobe_physical_check_invalid_json(mock_run, worker, base_context):
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="not a json string",
        stderr=""
    )
    
    with patch.object(Path, "exists", return_value=True):
        with pytest.raises(ValueError) as excinfo:
            worker._ffprobe_physical_check(base_context)
        assert "Failed to parse ffprobe output" in str(excinfo.value)

@patch("subprocess.run")
def test_ffprobe_physical_check_edge_cases(mock_run, worker, base_context):
    # duration, size が None や空文字、不正文字列、非辞書データの edge cases
    test_cases = [
        {"format": {"duration": None, "size": None}, "streams": None},
        {"format": {"duration": "", "size": ""}, "streams": "not_a_list"},
        {"format": {"duration": "invalid_float", "size": "invalid_int"}, "streams": [{"codec_type": "audio"}, "not_a_dict"]},
        {"format": None, "streams": []},
        "not_a_dict"
    ]
    
    with patch.object(Path, "exists", return_value=True):
        for tc in test_cases:
            if isinstance(tc, str):
                mock_run.return_value = MagicMock(returncode=0, stdout=tc, stderr="")
                with pytest.raises(ValueError):
                    worker._ffprobe_physical_check(base_context)
            else:
                mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps(tc), stderr="")
                res = worker._ffprobe_physical_check(base_context)
                assert isinstance(res, dict)
                # 正常に例外なく解析され、デフォルト値(duration=0, size=0)により失敗項目が判定されていること
                failures = [f["message"] for f in res["failures"]]
                assert any("映像ストリームが存在しない" in f for f in failures)

# --- サムネイル物理検証テスト ---

def test_thumbnail_physical_check_no_path(worker, base_context):
    base_context.thumbnail_path = None
    if hasattr(base_context, "metadata"):
        del base_context.metadata
    
    res = worker._thumbnail_physical_check(base_context)
    assert len(res["failures"]) == 1
    assert "サムネイルパスが設定されていません" in res["failures"][0]["message"]

    # 不正な型のパス
    base_context.thumbnail_path = ["invalid_path_type"]
    res = worker._thumbnail_physical_check(base_context)
    assert len(res["failures"]) == 1
    assert "サムネイルパスが設定されていません" in res["failures"][0]["message"]

    # metadata から取得するフォールバック
    base_context.thumbnail_path = None
    base_context.metadata = {"thumbnail_path": "/dummy/meta_thumb.jpg"}
    res = worker._thumbnail_physical_check(base_context)
    assert len(res["failures"]) == 1
    assert "サムネイルファイルが存在しません: meta_thumb.jpg" in res["failures"][0]["message"]

def test_thumbnail_physical_check_not_exists(worker, base_context):
    base_context.thumbnail_path = "/dummy/non_existent_thumb.jpg"
    res = worker._thumbnail_physical_check(base_context)
    assert len(res["failures"]) == 1
    assert "サムネイルファイルが存在しません: non_existent_thumb.jpg" in res["failures"][0]["message"]

def test_thumbnail_physical_check_zero_size(worker, base_context):
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 0
        res = worker._thumbnail_physical_check(base_context)
        assert len(res["failures"]) == 1
        assert "サムネイルファイルが空です" in res["failures"][0]["message"]

@patch("PIL.Image.open")
def test_thumbnail_physical_check_success_pil(mock_image_open, worker, base_context):
    mock_img = MagicMock()
    mock_img.size = (1280, 720)
    mock_img.format = "JPEG"
    mock_image_open.return_value.__enter__.return_value = mock_img

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 500000  # 500KB
        
        res = worker._thumbnail_physical_check(base_context)
        assert len(res["failures"]) == 0
        assert len(res["warnings"]) == 0

@patch("PIL.Image.open")
def test_thumbnail_physical_check_failures_pil(mock_image_open, worker, base_context):
    mock_img = MagicMock()
    mock_img.size = (600, 400)
    mock_img.format = "GIF"
    mock_image_open.return_value.__enter__.return_value = mock_img

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 3 * 1024 * 1024
        
        res = worker._thumbnail_physical_check(base_context)
        
        failures = [f["message"] for f in res["failures"]]
        assert any("YouTube上限(2MB)を超過しています" in f for f in failures)
        assert any("非サポートのサムネイルフォーマットです" in f for f in failures)
        assert any("サムネイルの幅が小さすぎます" in f for f in failures)
        
        warnings = res["warnings"]
        assert any("アスペクト比が16:9ではありません" in w for w in warnings)

@patch("PIL.Image.open")
def test_thumbnail_physical_check_image_corrupt(mock_image_open, worker, base_context):
    from PIL import UnidentifiedImageError
    mock_image_open.side_effect = UnidentifiedImageError("corrupted image")

    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 50000
        
        res = worker._thumbnail_physical_check(base_context)
        assert len(res["failures"]) == 1
        assert "サムネイル画像が破損しているか、読み込めません" in res["failures"][0]["message"]

def test_thumbnail_physical_check_import_error(worker, base_context):
    with patch.dict("sys.modules", {"PIL": None, "PIL.Image": None}):
        res = worker._thumbnail_physical_check(base_context)
        assert len(res["failures"]) == 1
        assert "Pillowライブラリがインストールされていません" in res["failures"][0]["message"]

@patch("PIL.Image.open")
def test_thumbnail_physical_check_edge_cases(mock_image_open, worker, base_context):
    # img.size の異常値や高さ 0 のエッジケース
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 50000

        # size属性なし
        mock_img_no_size = MagicMock(spec=[])
        mock_image_open.return_value.__enter__.return_value = mock_img_no_size
        res = worker._thumbnail_physical_check(base_context)
        assert any("サイズ情報が取得できません" in f["message"] for f in res["failures"])

        # 高さ0
        mock_img_zero_height = MagicMock()
        mock_img_zero_height.size = (1280, 0)
        mock_img_zero_height.format = "JPEG"
        mock_image_open.return_value.__enter__.return_value = mock_img_zero_height
        res = worker._thumbnail_physical_check(base_context)
        assert any("サムネイル画像の高さが0です" in f["message"] for f in res["failures"])


@pytest.mark.parametrize("exception_cls", [
    ValueError,
    TypeError,
    AttributeError,
    OSError,
    KeyError,
    RuntimeError
])
@pytest.mark.asyncio
async def test_execute_thumbnail_various_exceptions_handled(worker, base_context, exception_cls):
    # サムネイル物理チェックで様々な例外が発生した場合でも、executeで安全にハンドリングされること
    ffprobe_res = {"failures": [], "warnings": []}
    plugin_res = {"total_deductions": 0, "feedback": [], "category_report": [], "category_scores": {}}
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", side_effect=exception_cls("test error")), \
         patch.dict("sys.modules", {"quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins), "template_config": None}):
        
        res = await worker.execute(base_context)
        assert res.success is True
        assert any("⚠️ サムネイル検証実行不可: " in f and "test error" in f for f in res.data["feedback"])


@pytest.mark.asyncio
async def test_execute_thumbnail_critical_exceptions_not_handled(worker, base_context):
    # SystemExitなどの致命的な例外はハンドリングせず、そのまま上に通すこと
    ffprobe_res = {"failures": [], "warnings": []}
    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", side_effect=SystemExit("exit")):
        
        with pytest.raises(SystemExit):
            await worker.execute(base_context)


@patch("PIL.Image.open")
def test_thumbnail_physical_check_size_not_tuple_or_short(mock_image_open, worker, base_context):
    # img.size がタプルでない場合や、要素数が足りない場合のエッジケース
    with patch.object(Path, "exists", return_value=True), \
         patch.object(Path, "stat") as mock_stat:
        mock_stat.return_value.st_size = 50000

        # タプルではないケース
        mock_img_invalid_type = MagicMock()
        mock_img_invalid_type.size = "1280x720"
        mock_image_open.return_value.__enter__.return_value = mock_img_invalid_type
        res = worker._thumbnail_physical_check(base_context)
        assert any("サイズ情報が取得できません" in f["message"] for f in res["failures"])

        # 要素数が足りないケース
        mock_img_short_tuple = MagicMock()
        mock_img_short_tuple.size = (1280,)
        mock_image_open.return_value.__enter__.return_value = mock_img_short_tuple
        res = worker._thumbnail_physical_check(base_context)
        assert any("サイズ情報が取得できません" in f["message"] for f in res["failures"])


@pytest.mark.asyncio
async def test_execute_template_config_syntax_error_propagates(worker, base_context):
    ffprobe_res = {"failures": [], "warnings": []}
    thumb_res = {"failures": [], "warnings": []}
    plugin_res = {"total_deductions": 0, "feedback": [], "category_report": [], "category_scores": {}}
    mock_run_plugins = MagicMock(return_value=plugin_res)
    
    import builtins
    orig_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name == "template_config":
            raise SyntaxError("syntax error in config")
        return orig_import(name, *args, **kwargs)

    with patch.object(worker, "_ffprobe_physical_check", return_value=ffprobe_res), \
         patch.object(worker, "_thumbnail_physical_check", return_value=thumb_res), \
         patch.dict("sys.modules", {"quality_gate_plugins": MagicMock(run_all_plugins=mock_run_plugins)}), \
         patch("builtins.__import__", side_effect=mock_import):
        
        with pytest.raises(SyntaxError) as excinfo:
            await worker.execute(base_context)
        assert "syntax error in config" in str(excinfo.value)


@patch("subprocess.run")
def test_ffprobe_physical_check_filenotfound_handled(mock_run, worker, base_context):
    mock_run.side_effect = FileNotFoundError("No such file or directory")
    
    with patch.object(Path, "exists", return_value=True):
        with pytest.raises(subprocess.SubprocessError) as excinfo:
            worker._ffprobe_physical_check(base_context)
        assert "ffprobe command not found" in str(excinfo.value)


@patch("subprocess.run")
def test_ffprobe_physical_check_timeout_handled(mock_run, worker, base_context):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=30)
    
    with patch.object(Path, "exists", return_value=True):
        with pytest.raises(subprocess.SubprocessError) as excinfo:
            worker._ffprobe_physical_check(base_context)
        assert "ffprobe command timed out after 30" in str(excinfo.value)


@pytest.mark.asyncio
async def test_execute_ffprobe_subprocess_error_no_tdr_registration(worker, base_context):
    base_context.thumbnail_path = None
    
    with patch.object(worker, "_ffprobe_physical_check", side_effect=subprocess.SubprocessError("ffprobe issue")), \
         patch.dict("sys.modules", {"quality_gate_plugins": None}), \
         patch("agents.memory.technical_debt.technical_debt_store.register_debt") as mock_register:
        
        res = await worker.execute(base_context)
        mock_register.assert_not_called()
        assert any("⚠️ FFprobe検証実行不可: ffprobe issue" in f for f in res.data["feedback"])


