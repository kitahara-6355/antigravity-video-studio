import pytest
import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, message="coroutine .*get_thumbnails.* was never awaited")
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")
import sys
import importlib
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from PIL import Image
from core import ProductionContext
import plugins.thumbnail_plugin

def test_tp_get_model_fallback():
    # model_registryのインポートが失敗したときのフォールバックをテストするため、
    # 一時的に sys.modules['model_registry'] を None にしてモジュールをリロードする
    with patch.dict('sys.modules', {'model_registry': None}):
        import plugins.thumbnail_plugin
        importlib.reload(plugins.thumbnail_plugin)
        
        # フォールバックされた get_model をテスト
        # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
        # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
        # **この経路が返すのは工程別のモデルではなく既定モデル**
        from model_policy import default_model
        assert plugins.thumbnail_plugin.get_model("thumbnail") == default_model()
        assert not plugins.thumbnail_plugin.get_model("thumbnail").startswith("gemini-2.5")
        
    # テスト後に正常な状態に戻すため、再度リロード
    importlib.reload(plugins.thumbnail_plugin)

def test_tp_can_execute():
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    context = ProductionContext(task_id="test")
    
    # video_title がない場合は False
    assert plugin.can_execute(context) is False
    
    # video_title がある場合は True
    context.set_extension("video_title", "Sample Title")
    assert plugin.can_execute(context) is True

def test_tp_execute_success(tmp_path):
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=2)
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    context.set_extension("video_description", "Sample Desc")
    context.segments = [{"start": 0, "end": 10, "text": "Hello"}]
    
    img_path1 = tmp_path / "c1.png"
    Image.new("RGB", (1280, 720), color="blue").save(img_path1)
    
    img_path2 = tmp_path / "c2.png"
    Image.new("RGB", (1280, 720), color="red").save(img_path2)
    
    # candidatesのモック作成
    mock_candidate_1 = MagicMock()
    mock_candidate_1.id = "c1"
    mock_candidate_1.concept = "concept1"
    mock_candidate_1.target_emotion = "emotion1"
    mock_candidate_1.text_overlay = "overlay1"
    mock_candidate_1.predicted_ctr = 5.5
    mock_candidate_1.path = img_path1
    
    mock_candidate_2 = MagicMock()
    mock_candidate_2.id = "c2"
    mock_candidate_2.concept = "concept2"
    mock_candidate_2.target_emotion = "emotion2"
    mock_candidate_2.text_overlay = "overlay2"
    mock_candidate_2.predicted_ctr = 6.5
    mock_candidate_2.path = img_path2
    
    mock_result = MagicMock()
    mock_result.thumbnail_candidates = [mock_candidate_1, mock_candidate_2]
    
    # optimize_contextのモック
    mock_optimize = AsyncMock(return_value=mock_result)
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize):
        result_context = plugin.execute(context)
        
        # コンテキストへの設定内容の確認
        assert len(result_context.thumbnail_candidates) == 2
        assert result_context.thumbnail_candidates[0]["id"] == "c1"
        assert result_context.thumbnail_candidates[0]["path"] == img_path1
        assert result_context.thumbnail_candidates[1]["id"] == "c2"
        assert result_context.thumbnail_candidates[1]["path"] == img_path2
        assert result_context.get_extension("thumbnail_count") == 2

@pytest.mark.asyncio
async def test_tp_execute_running_loop(tmp_path):
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=1)
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    img_path = tmp_path / "c1.png"
    Image.new("RGB", (1280, 720), color="blue").save(img_path)
    
    mock_candidate = MagicMock()
    mock_candidate.id = "c1"
    mock_candidate.concept = "concept1"
    mock_candidate.target_emotion = "emotion1"
    mock_candidate.text_overlay = "overlay1"
    mock_candidate.predicted_ctr = 5.5
    mock_candidate.path = img_path
    
    mock_result = MagicMock()
    mock_result.thumbnail_candidates = [mock_candidate]
    
    mock_optimize = AsyncMock(return_value=mock_result)
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize):
        result_context = plugin.execute(context)
        assert result_context.get_extension("thumbnail_count") == 1
        assert len(result_context.thumbnail_candidates) == 1

def test_tp_execute_loop_runtime_error(tmp_path):
    # loop.run_until_complete が RuntimeError を投げたときの asyncio.run へのフォールバック経路をテスト
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=1)
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    img_path = tmp_path / "c1.png"
    Image.new("RGB", (1280, 720), color="blue").save(img_path)
    
    mock_candidate = MagicMock()
    mock_candidate.id = "c1"
    mock_candidate.concept = "concept1"
    mock_candidate.target_emotion = "emotion1"
    mock_candidate.text_overlay = "overlay1"
    mock_candidate.predicted_ctr = 5.5
    mock_candidate.path = img_path
    
    mock_result = MagicMock()
    mock_result.thumbnail_candidates = [mock_candidate]
    
    mock_optimize = AsyncMock(return_value=mock_result)
    
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = False
    mock_loop.run_until_complete.side_effect = RuntimeError("Loop is closed or something")
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize):
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result_context = plugin.execute(context)
            assert result_context.get_extension("thumbnail_count") == 1
            assert len(result_context.thumbnail_candidates) == 1

def test_tp_execute_exception():
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    # optimize_contextが例外を投げるように設定
    mock_optimize = AsyncMock(side_effect=RuntimeError("Test error"))
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize):
        with pytest.raises(plugins.thumbnail_plugin.ThumbnailPluginError):
            plugin.execute(context)


def test_tp_execute_import_error():
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    with patch.dict('sys.modules', {'plugins.youtube_optimizer_plugin': None}):
        with pytest.raises(plugins.thumbnail_plugin.ThumbnailPluginError):
            plugin.execute(context)

def test_tp_execute_unexpected_exception():
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    with patch.object(context, 'get_extension', side_effect=TypeError("Unexpected mock error")):
        with pytest.raises(plugins.thumbnail_plugin.ThumbnailPluginError):
            plugin.execute(context)


def test_tp_init_robustness():
    p1 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=5)
    assert p1.num_candidates == 5

    p2 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=0)
    assert p2.num_candidates == 1
    p3 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=-5)
    assert p3.num_candidates == 1

    p4 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=15)
    assert p4.num_candidates == 10

    p5 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates="invalid")
    assert p5.num_candidates == 3

    p6 = plugins.thumbnail_plugin.ThumbnailPlugin(num_candidates=4.5)
    assert p6.num_candidates == 4

def test_tp_can_execute_robustness():
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    assert plugin.can_execute(None) is False
    assert plugin.can_execute(object()) is False

def test_tp_execute_robustness(tmp_path):
    plugin = plugins.thumbnail_plugin.ThumbnailPlugin()
    assert plugin.execute(None) is None
    
    context = ProductionContext(task_id="test")
    context.set_extension("video_title", "Sample Title")
    
    mock_candidate = MagicMock()
    mock_candidate.id = "broken"
    mock_candidate.path = None
    mock_result = MagicMock()
    mock_result.thumbnail_candidates = [mock_candidate]
    mock_optimize = AsyncMock(return_value=mock_result)
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize):
        with pytest.raises(plugins.thumbnail_plugin.ThumbnailPluginError):
            plugin.execute(context)

    # 壊れた候補データだが画像パスが実在する場合
    img_path = tmp_path / "broken.png"
    Image.new("RGB", (1280, 720), color="blue").save(img_path)

    # MagicMockの代わりにシンプルなクラスを使用する
    class SimpleCandidate:
        pass
    mock_candidate_broken = SimpleCandidate()
    mock_candidate_broken.path = img_path
    
    mock_result_broken = MagicMock()
    mock_result_broken.thumbnail_candidates = [mock_candidate_broken]
    
    mock_optimize_broken = AsyncMock(return_value=mock_result_broken)
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", mock_optimize_broken):
        result_context = plugin.execute(context)
        assert len(result_context.thumbnail_candidates) == 1
        cand = result_context.thumbnail_candidates[0]
        assert cand["id"] == "unknown_id"
        assert cand["concept"] == ""
        assert cand["target_emotion"] == ""
        assert cand["text_overlay"] == ""
        assert cand["predicted_ctr"] == 0.0

    # loop が返す値がリストではない場合のテスト
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = False
    mock_loop.run_until_complete.return_value = "not_a_list"  # リストではない値を返す
    
    with patch("plugins.youtube_optimizer_plugin.youtube_optimizer.optimize_context", AsyncMock()):
        with patch("asyncio.get_event_loop", return_value=mock_loop):
            result_context = plugin.execute(context)
            assert result_context.thumbnail_candidates == []


@pytest.mark.asyncio
async def test_thumbnail_quality_standard_validation(tmp_path):
    """
    最優先ルール: サムネイル品質検証自動化テスト
    - 解像度が 1280x720 以上
    - アスペクト比が 16:9
    - ファイルサイズが 4MB 未満
    - 破損チェック（Pillowでロード可能）
    """
    from PIL import Image
    from pathlib import Path
    from plugins.thumbnail_plugin import validate_and_correct_thumbnail
    
    # テストケース 1: 低解像度 (例えば 640x360, 16:9) の画像が 1280x720 に補正されること
    low_res_path = tmp_path / "low_res.png"
    Image.new("RGB", (640, 360), color="red").save(low_res_path)
    
    corrected_path = validate_and_correct_thumbnail(low_res_path)
    with Image.open(corrected_path) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.01
        
    # テストケース 2: アスペクト比が異なる画像 (例えば 1000x1000, 1:1) が 16:9 かつ 1280x720 以上に補正されること
    square_path = tmp_path / "square.png"
    Image.new("RGB", (1000, 1000), color="blue").save(square_path)
    
    corrected_path2 = validate_and_correct_thumbnail(square_path)
    with Image.open(corrected_path2) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.01

    # テストケース 3: 4MB を超える巨大画像が 4MB 未満に正しく圧縮補正されること
    large_path = tmp_path / "large.png"
    Image.new("RGB", (2000, 2000), color="green").save(large_path)
    
    # 4MB (4 * 1024 * 1024) を超えるようにダミーデータを末尾に追加
    with open(large_path, "ab") as f:
        f.write(b"\0" * (5 * 1024 * 1024))
        
    assert large_path.stat().st_size >= 4 * 1024 * 1024
    
    corrected_path3 = validate_and_correct_thumbnail(large_path)
    assert Path(corrected_path3).stat().st_size < 4 * 1024 * 1024
    with Image.open(corrected_path3) as img:
        img.load()
        w, h = img.size
        assert w >= 1280
        assert h >= 720
        assert abs((w / h) - (16.0 / 9.0)) < 0.01


@pytest.mark.asyncio
async def test_stage_bound_agent_integration_full(tmp_path):
    """
    最優先ルール: StageBoundAgent等に登録され、自動リトライや結果保存、
    DBマイグレーションの各機能と連携して動作することを検証
    """
    import json
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    from plugins.thumbnail_plugin import ThumbnailPlugin
    
    db_path = str(tmp_path / "tasks.db")
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
    
    # DBマイグレーション確認: retry_count や max_retries など必要なカラムが存在すること
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    assert "retry_count" in columns
    assert "max_retries" in columns
    assert "result" in columns
    conn.close()
    
    # タスクの登録とリトライ連携テスト
    task_id = "test_task_001"
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 処理関数 (画像生成を行い、わざと1回失敗して自動リトライさせる)
    call_count = 0
    
    async def process_task(tid):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("Simulated network transient error")
            
        # 2回目は成功させる
        output_dir = tmp_path / "output_thumbnails"
        output_dir.mkdir(parents=True, exist_ok=True)
        img_path = output_dir / f"{tid}.png"
        Image.new("RGB", (1280, 720), color="purple").save(img_path)
        
        # 簡易チェックをして結果情報をjsonで返す
        return json.dumps({
            "path": str(img_path),
            "width": 1280,
            "height": 720,
            "size_bytes": img_path.stat().st_size
        })
        
    # エージェント開始
    await agent.start(process_task)
    
    # 処理完了を待つ (ポーリング)
    for _ in range(50):
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
        await asyncio.sleep(0.1)
        
    await agent.stop()
    
    # 検証: 自動リトライされて、最終的に COMPLETED になること
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    assert call_count == 2  # 1回目の失敗、2回目のリトライで完了
    
    # 結果の保存検証
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    assert row is not None
    result_json = json.loads(row[0])
    assert result_json["width"] == 1280
    assert result_json["height"] == 720
    assert row[1] is not None  # 1回目のエラーメッセージが記録されている
    assert row[2] == 1  # リトライ回数が1回
    conn.close()


def test_tp_execute_detailed_database_exception():
    """詳細化された例外キャッチ：sqlite3.Error 発生時に Database failure 例外が送出されることを検証"""
    from plugins.thumbnail_plugin import ThumbnailPlugin, ThumbnailPluginError
    import sqlite3
    from unittest.mock import MagicMock, patch, AsyncMock
    import pytest
    
    plugin = ThumbnailPlugin()
    context = MagicMock()
    context.get_extension.return_value = "Test Title"
    
    # youtube_optimizer.optimize_context が適切に await 可能な AsyncMock を返すようにする
    mock_yt_opt = MagicMock()
    mock_yt_opt.optimize_context = AsyncMock(return_value=None)
    
    # sqlite3.connect が例外を投げるようにモックする
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Mock DB Error")),          patch("service_container.container") as mock_container,          patch("service_container.setup_services"):
        mock_container.has.return_value = True
        mock_container.get.return_value = mock_yt_opt
        
        # execute 内で sqlite3.Error がキャッチされ、Database failure に包まれて再スローされることを確認
        with pytest.raises(ThumbnailPluginError) as exc_info:
            plugin.execute(context)
            
        assert "Database failure" in str(exc_info.value)
        assert "Mock DB Error" in str(exc_info.value)


def test_tp_execute_detailed_json_exception(tmp_path):
    """詳細化された例外キャッチ：JSONDecodeError 発生時に JSON format failure 例外が送出されることを検証"""
    from plugins.thumbnail_plugin import ThumbnailPlugin, ThumbnailPluginError
    from agents.stage_bound_agent import StageBoundAgent
    import sqlite3
    import json
    import asyncio
    from unittest.mock import MagicMock, patch, AsyncMock
    import pytest
    
    plugin = ThumbnailPlugin(num_candidates=1)
    context = MagicMock()
    context.get_extension.return_value = "Test Title"
    context.db_path = str(tmp_path / "test_json_err.db")
    
    # StageBoundAgentにテーブル初期化と登録を任せる
    agent = StageBoundAgent(stage_name="thumbnail", db_path=context.db_path)
    
    mock_candidate = MagicMock()
    mock_candidate.id = "c1"
    mock_candidate.path = str(tmp_path / "valid.png")
    
    mock_yt_opt = MagicMock()
    async def dummy_optimize(*args, **kwargs):
        res = MagicMock()
        res.thumbnail_candidates = [mock_candidate]
        return res
    mock_yt_opt.optimize_context = dummy_optimize
    
    with patch("service_container.container") as mock_container,          patch("service_container.setup_services"),          patch("uuid.uuid4") as mock_uuid:
        mock_container.has.return_value = True
        mock_container.get.return_value = mock_yt_opt
        
        # task_id の末尾の uuid.uuid4().hex[:8] を固定
        mock_uuid_obj = MagicMock()
        mock_uuid_obj.hex = "12345678"
        mock_uuid.return_value = mock_uuid_obj
        
        # plugin 内で生成されるタスクIDは thumb_plugin_c1_12345678 になる
        # イベントループで事前に register_task を呼んでスキーマ通り登録させる
        async def prep_db():
            await agent.register_task("thumb_plugin_c1_12345678", initial_status="COMPLETED", max_retries=2)
        asyncio.run(prep_db())
        
        # 登録後、結果情報に意図的に不正なJSON文字列を上書きする
        conn = sqlite3.connect(context.db_path)
        conn.execute(
            "UPDATE tasks SET result = ? WHERE id = ?",
            ("invalid-json-string{", "thumb_plugin_c1_12345678")
        )
        conn.commit()
        conn.close()
        
        with pytest.raises(ThumbnailPluginError) as exc_info:
            plugin.execute(context)
            
        assert "JSON format failure" in str(exc_info.value)
