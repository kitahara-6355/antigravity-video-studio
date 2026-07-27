import pytest
import json
import base64
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image
from progressive_preview_report import PreviewReportGenerator


def test_pp_report_image_to_base64_success(tmp_path):
    """画像が存在する場合に正常にBase64エンコードされること"""
    img_path = tmp_path / "test.png"
    from PIL import Image
    import io
    img = Image.new("RGB", (1280, 720), color="blue")
    out = io.BytesIO()
    img.save(out, format="PNG")
    img_bytes = out.getvalue()
    img_path.write_bytes(img_bytes)
    
    generator = PreviewReportGenerator()
    b64_str = generator._image_to_base64(str(img_path))
    
    assert b64_str != ""
    decoded = base64.b64decode(b64_str)
    img_decoded = Image.open(io.BytesIO(decoded))
    img_decoded.load()
    assert img_decoded.size == (1280, 720)


def test_pp_report_image_to_base64_file_not_found(tmp_path):
    """画像が存在しない場合に空文字列が返り、FileNotFoundErrorが捕捉されること"""
    non_existent = tmp_path / "non_existent.png"
    
    generator = PreviewReportGenerator()
    with patch("progressive_preview_report.logger.warning") as mock_warning:
        b64_str = generator._image_to_base64(str(non_existent))
        assert b64_str == ""
        mock_warning.assert_called_once()
        assert "Failed to encode image (File not found)" in mock_warning.call_args[0][0]


def test_pp_report_image_to_base64_permission_error(tmp_path):
    """読み込み中にPermissionErrorが発生した場合に空文字列が返り、PermissionErrorが捕捉されること"""
    img_path = tmp_path / "error.png"
    img_path.write_bytes(b"dummy")
    
    generator = PreviewReportGenerator()
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with patch("progressive_preview_report.logger.warning") as mock_warning:
            b64_str = generator._image_to_base64(str(img_path))
            assert b64_str == ""
            mock_warning.assert_called_once()
            assert "Failed to encode image (Permission denied)" in mock_warning.call_args[0][0]
            assert "Permission denied" in mock_warning.call_args[0][0]


def test_pp_report_image_to_base64_os_error(tmp_path):
    """読み込み中に一般的なOSErrorが発生した場合に空文字列が返り、OSErrorが捕捉されること"""
    img_path = tmp_path / "error.png"
    img_path.write_bytes(b"dummy")
    
    generator = PreviewReportGenerator()
    with patch("builtins.open", side_effect=OSError("Disk crash")):
        with patch("progressive_preview_report.logger.warning") as mock_warning:
            b64_str = generator._image_to_base64(str(img_path))
            assert b64_str == ""
            mock_warning.assert_called_once()
            assert "Failed to encode image (OS error)" in mock_warning.call_args[0][0]
            assert "Disk crash" in mock_warning.call_args[0][0]


def test_pp_report_image_to_base64_unexpected_exception(tmp_path):
    """読み込み中に予期せぬ例外が発生した場合に、logger.errorがexc_info=Trueで実行されること"""
    img_path = tmp_path / "error.png"
    img_path.write_bytes(b"dummy")
    
    generator = PreviewReportGenerator()
    with patch("builtins.open", side_effect=ValueError("Unexpected type")):
        with patch("progressive_preview_report.logger.error") as mock_error:
            b64_str = generator._image_to_base64(str(img_path))
            assert b64_str == ""
            mock_error.assert_called_once()
            assert "Unexpected error encoding image" in mock_error.call_args[0][0]
            assert "Unexpected type" in mock_error.call_args[0][0]
            assert mock_error.call_args[1].get("exc_info") is True


def test_pp_report_generate_html_empty_metadata(tmp_path):
    """メタデータが空の場合でも、デフォルト値を用いてHTMLが正常生成されること"""
    output_file = tmp_path / "report.html"
    generator = PreviewReportGenerator()
    
    result_path = generator.generate_html_report({}, str(output_file))
    
    assert Path(result_path).exists()
    content = Path(result_path).read_text(encoding="utf-8")
    assert "プレミアム・プレビューレポート - unknown" in content
    assert "0 サンプル" not in content


def test_pp_report_generate_html_with_steps_and_embedding(tmp_path):
    """ステップと画像指定がある場合、正常にBase64埋め込みが行われること"""
    from PIL import Image
    import io
    
    def create_png():
        img = Image.new("RGB", (1280, 720), color="blue")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
        
    img1_bytes = create_png()
    img2_bytes = create_png()
    
    img1 = tmp_path / "img1.png"
    img1.write_bytes(img1_bytes)
    img2 = tmp_path / "img2.png"
    img2.write_bytes(img2_bytes)
    
    metadata = {
        "session_id": "test_session_123",
        "created_at": "2026-05-24T12:00:00",
        "steps": [
            {
                "step_name": "Resize Step",
                "comparisons": [
                    {
                        "timestamp": 12.5,
                        "comparison": str(img1),
                        "before": str(img2),
                        "after": "",
                        "diff_highlight": "non_existent.png"
                    }
                ]
            }
        ]
    }
    
    output_file = tmp_path / "sub_dir" / "report.html"
    generator = PreviewReportGenerator()
    
    result_path = generator.generate_html_report(metadata, str(output_file), embed_images=True)
    
    assert Path(result_path).exists()
    content = Path(result_path).read_text(encoding="utf-8")
    
    assert "Resize Step" in content
    assert "1 サンプル" in content
    # 最適化されたBase64文字列が埋め込まれていることを確認
    assert "data:image/png;base64," in content
    assert 'src=""' in content


def test_pp_report_generate_from_session_dir_default_path(tmp_path):
    """session_dirから正常に読み込み、デフォルトパスにHTMLを出力すること"""
    metadata = {
        "session_id": "session_dir_test",
        "steps": []
    }
    metadata_file = tmp_path / "session_metadata.json"
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
    
    generator = PreviewReportGenerator()
    result_path = generator.generate_from_session_dir(str(tmp_path))
    
    expected_path = tmp_path / "preview_report.html"
    assert result_path == str(expected_path)
    assert expected_path.exists()
    assert "session_dir_test" in expected_path.read_text(encoding="utf-8")


def test_pp_report_generate_from_session_dir_custom_path(tmp_path):
    """session_dirから正常に読み込み、カスタムパスにHTMLを出力すること"""
    metadata = {
        "session_id": "session_dir_custom_test",
        "steps": []
    }
    metadata_file = tmp_path / "session_metadata.json"
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
    
    custom_output = tmp_path / "custom_dir" / "custom_report.html"
    generator = PreviewReportGenerator()
    result_path = generator.generate_from_session_dir(str(tmp_path), output_path=str(custom_output))
    
    assert result_path == str(custom_output)
    assert custom_output.exists()
    assert "session_dir_custom_test" in custom_output.read_text(encoding="utf-8")


def test_pp_report_generate_from_session_dir_not_found(tmp_path):
    """メタデータファイルが存在しない場合にFileNotFoundErrorが発生すること"""
    generator = PreviewReportGenerator()
    with pytest.raises(FileNotFoundError):
        generator.generate_from_session_dir(str(tmp_path / "empty_dir"))


def test_pp_report_main_block():
    """スクリプトのメインブロックが正常に実行され、例外を投げないこと"""
    possible_outputs = [
        Path("backend/temp/test_report.html"),
        Path("backend/backend/temp/test_report.html"),
        Path("temp/test_report.html"),
    ]
    
    # 実行前に既存のファイルを削除
    for out_file in possible_outputs:
        if out_file.exists():
            try:
                out_file.unlink()
            except OSError:
                pass
        
    test_dir = Path(__file__).resolve().parent
    script_path = None
    for p in [
        test_dir / "progressive_preview_report.py",
        test_dir.parent / "progressive_preview_report.py",
        test_dir.parent.parent / "progressive_preview_report.py",
        test_dir.parent.parent / "backend" / "progressive_preview_report.py",
        Path("backend/progressive_preview_report.py"),
        Path("progressive_preview_report.py")
    ]:
        if p.exists():
            script_path = p.absolute()
            break
            
    assert script_path is not None, "Could not find progressive_preview_report.py"
    
    try:
        runpy.run_path(str(script_path), run_name="__main__")
        assert any(p.exists() for p in possible_outputs)
    finally:
        for out_file in possible_outputs:
            if out_file.exists():
                try:
                    out_file.unlink()
                except OSError:
                    pass


# --- サムネイル画像生成・品質検証・StageBoundAgent連携テスト ---
import shutil
import sqlite3
import asyncio
from progressive_preview_report import (
    generate_progressive_preview_thumbnail,
    validate_thumbnail,
    resolve_progressive_preview_report_task,
    OUTPUT_DIR
)
from agents.stage_bound_agent import StageBoundAgent

def test_pp_report_thumbnail_generation_quality(tmp_path):
    """正常なサムネイル画像が生成され、品質基準を満たし、validate_thumbnailで検証に成功すること"""
    output_path = tmp_path / "valid_thumbnail.png"
    
    # 正常な画像生成
    result_path = generate_progressive_preview_thumbnail(output_path, width=1280, height=720, text="Quality Test Title\nDetail message here")
    assert Path(result_path).exists()
    
    # 品質検証
    info = validate_thumbnail(result_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] < 4 * 1024 * 1024
    assert info["size_bytes"] > 0
    assert Path(info["path"]) == output_path

def test_pp_report_thumbnail_invalid_params(tmp_path):
    """無効な解像度やアスペクト比を指定した場合にValueErrorが発生すること"""
    output_path = tmp_path / "invalid.png"
    
    # 解像度不足
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=640, height=360)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # アスペクト比不正 (16:10 など)
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=1280, height=800)
    assert "Aspect ratio must be 16:9" in str(exc.value)

def test_pp_report_thumbnail_corrupted_detect(tmp_path):
    """ファイルが存在しない、または破損している場合に適切な例外が発生すること"""
    non_existent = tmp_path / "not_exist.png"
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(non_existent)
        
    corrupted = tmp_path / "corrupted.png"
    corrupted.write_bytes(b"invalid png signature but short")
    with pytest.raises(ValueError) as exc:
        validate_thumbnail(corrupted)
    assert "Image is corrupted" in str(exc.value)

@pytest.mark.asyncio
async def test_pp_report_stage_bound_agent_integration(tmp_path):
    """StageBoundAgentと連携して、DBマイグレーション、結果保存、および自動リトライ機能が正常に動作すること"""
    # SQLite DBパスの設定 (:memory: はコネクションを閉じるとデータが消える or 共有できないため物理ファイルを使用)
    db_path = str(tmp_path / "test.db")
    
    # 1. DBマイグレーションの検証
    agent = StageBoundAgent(stage_name="progressive_preview", db_path=db_path, poll_interval=0.01)
    
    # tasks テーブルが作成され、新カラム（result, retry_count, max_retries）が存在するか確認
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor.fetchall()]
    conn.close()
    
    assert "result" in columns
    assert "retry_count" in columns
    assert "max_retries" in columns
    
    # 2. タスク結果保存の連携検証
    # 非同期プロセッサ関数をバインド
    async def mock_process(task_id: str) -> str:
        return await resolve_progressive_preview_report_task(agent, task_id)
        
    await agent.start(mock_process)
    
    task_id = "test_task_success"
    await agent.register_task(task_id, initial_status="READY")
    
    # 処理完了を最大3秒待機
    for _ in range(30):
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 実行結果（JSON文字列）が tasks テーブルに保存されているか確認
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    result_json = json.loads(row[0])
    assert "width" in result_json
    assert "height" in result_json
    assert "size_bytes" in result_json
    
    # 3. 自動リトライ機能の連携検証
    fail_count = 0
    async def mock_fail_process(task_id: str) -> str:
        nonlocal fail_count
        fail_count += 1
        raise RuntimeError("Mock execution failure")
        
    # エージェントのプロセッサを切り替えてテスト
    await agent.stop()
    agent = StageBoundAgent(stage_name="progressive_preview_fail", db_path=db_path, poll_interval=0.01)
    await agent.start(mock_fail_process)
    
    fail_task_id = "test_task_fail_retry"
    # max_retries = 2 で登録
    await agent.register_task(fail_task_id, initial_status="READY", max_retries=2)
    
    # リトライ最大回数(2回) + 初回実行(1回) = 合計3回試行されて FAILED になるのを待機
    for _ in range(50):
        status = await agent.get_task_status(fail_task_id)
        if status == "FAILED":
            break
        await asyncio.sleep(0.1)
        
    status = await agent.get_task_status(fail_task_id)
    assert status == "FAILED"
    assert fail_count == 3  # 初回(1) + リトライ(2)
    
    # 最終的なクリーンアップ
    await agent.stop()
    
    # 生成された一時サムネイル画像のクリーンアップ
    output_dir = Path(OUTPUT_DIR)
    if output_dir.exists():
        shutil.rmtree(output_dir)

def test_pp_report_thumbnail_edge_resolutions(tmp_path):
    """最小解像度や高解像度制限が正しく動作し、ガードされていること"""
    output_path = tmp_path / "edge_res.png"
    
    # 正常な高解像度 (1920x1080)
    result_path = generate_progressive_preview_thumbnail(output_path, width=1920, height=1080, text="1080p Test")
    info = validate_thumbnail(result_path)
    assert info["width"] == 1920
    assert info["height"] == 1080
    
    # 最小値未満
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=640, height=360)
    assert "Resolution must be at least 1280x720" in str(exc.value)
    
    # 最大値超え
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=4000, height=2250)
    assert "Resolution exceeds maximum limit" in str(exc.value)

def test_pp_report_thumbnail_strict_aspect_ratio(tmp_path):
    """16:9以外のアスペクト比が正しく拒否されること"""
    output_path = tmp_path / "aspect.png"
    
    # 16:10 のアスペクト比
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=1280, height=800)
    assert "Aspect ratio must be 16:9" in str(exc.value)
    
    # 4:3 のアスペクト比
    with pytest.raises(ValueError) as exc:
        generate_progressive_preview_thumbnail(output_path, width=1440, height=1080)
    assert "Aspect ratio must be 16:9" in str(exc.value)

def test_pp_report_thumbnail_file_size_and_corruption(tmp_path):
    """ファイルサイズ上限/下限と破損、PNG以外のフォーマット検証が正しく機能すること"""
    output_path = tmp_path / "file_size_test.png"
    
    # 正常生成時のファイルサイズ検証 (< 4MB)
    generate_progressive_preview_thumbnail(output_path, text="File size check")
    info = validate_thumbnail(output_path)
    assert info["size_bytes"] < 4 * 1024 * 1024
    assert info["size_bytes"] >= 100
    
    # 極端に小さいファイルサイズ (下限チェック)
    small_file = tmp_path / "too_small.png"
    small_file.write_bytes(b"short PNG header")
    with pytest.raises(ValueError) as exc:
        validate_thumbnail(small_file)
    assert "Image is corrupted" in str(exc.value)
    
    # PNG以外のフォーマット検証 (JPEGをPNG拡張子で保存した場合など)
    jpeg_file = tmp_path / "fake_png.png"
    from PIL import Image
    # JPEGで画像を生成して保存
    img = Image.new("RGB", (1280, 720), color="blue")
    img.save(jpeg_file, "JPEG")
    
    with pytest.raises(ValueError) as exc:
        validate_thumbnail(jpeg_file)
    assert "Unsupported image format" in str(exc.value)


@pytest.mark.asyncio
async def test_pp_report_mandatory_standards_and_agent_flow(tmp_path):
    """
    ユーザーの必須品質基準を満たすサムネイル生成と StageBoundAgent 連携を検証する総合テスト
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent に登録され、結果保存、自動リトライ、DBマイグレーションの各機能と連携すること
    """
    db_path = str(tmp_path / "integration_standards.db")
    
    # 1. DBマイグレーションとAgent初期化
    agent = StageBoundAgent(stage_name="standards_verification", db_path=db_path, poll_interval=0.01)
    
    # DBテーブルと必須カラムの存在検証 (マイグレーションの検証)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("PRAGMA table_info(tasks)")
    cols = [row[1] for row in cursor.fetchall()]
    conn.close()
    assert "result" in cols
    assert "retry_count" in cols
    assert "max_retries" in cols
    
    # 2. Agent起動とタスク登録
    # テスト用の作業ディレクトリを設定
    with patch("progressive_preview_report.OUTPUT_DIR", str(tmp_path / "output_test")):
        async def process_task(task_id: str) -> str:
            return await resolve_progressive_preview_report_task(agent, task_id)
            
        await agent.start(process_task)
        
        task_id = "test_mandatory_standards_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=3)
        
        # 処理完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.1)
            
        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"
        
        # 3. 結果保存の連携と生成画像の検証
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        result_info = json.loads(row[0])
        
        # 画像パスの取得
        generated_image_path = Path(result_info["path"])
        
        # 必須基準自動検証
        # - 出力ファイルが正常に存在すること
        assert generated_image_path.exists()
        
        # - ファイルサイズが 4MB 未満であること
        size_bytes = generated_image_path.stat().st_size
        assert size_bytes < 4 * 1024 * 1024
        assert size_bytes >= 100 # 最低限のヘッダーサイズ保障
        
        # - 生成画像の解像度が 1280x720 以上であること
        # - アスペクト比が 16:9 であること
        # - 破損していない (Pillow等で正常にロード可能であること)
        with Image.open(generated_image_path) as img:
            img.verify() # 破損チェック
            
        with Image.open(generated_image_path) as img:
            img.load() # ピクセルデータロード
            width, height = img.size
            
        assert width >= 1280
        assert height >= 720
        
        aspect_ratio = width / height
        assert abs(aspect_ratio - (16.0 / 9.0)) <= 0.01
        
        # 4. 自動リトライ機能の連携検証
        fail_counter = 0
        async def fail_process(t_id: str) -> str:
            nonlocal fail_counter
            fail_counter += 1
            raise ValueError("Intentional error for retry test")
            
        await agent.stop()
        retry_agent = StageBoundAgent(stage_name="standards_retry", db_path=db_path, poll_interval=0.01)
        await retry_agent.start(fail_process)
        
        retry_task_id = "test_mandatory_retry_task"
        await retry_agent.register_task(retry_task_id, initial_status="READY", max_retries=2)
        
        # リトライ(2) + 初回(1) = 3回失敗するのを待機
        for _ in range(50):
            stat = await retry_agent.get_task_status(retry_task_id)
            if stat == "FAILED":
                break
            await asyncio.sleep(0.1)
            
        stat = await retry_agent.get_task_status(retry_task_id)
        assert stat == "FAILED"
        assert fail_counter == 3
        
        # クリーンアップ
        await retry_agent.stop()


def test_pp_report_thumbnail_font_load_default_os_error(tmp_path):
    """ImageFont.load_default()がOSErrorを投げた際、正常にNoneへフォールバックされること"""
    from unittest.mock import patch
    from PIL import ImageFont
    from progressive_preview_report import generate_progressive_preview_thumbnail
    
    output_path = tmp_path / "fallback_font_test.png"
    
    with patch("PIL.ImageFont.load_default", side_effect=OSError("Mocked font load error")):
        # OSErrorが発生しても例外がキャッチされ、正常にNoneフォールバックで画像が生成されるはず
        result = generate_progressive_preview_thumbnail(output_path, text="Font fallback test")
        assert result.exists()


def test_pp_report_thumbnail_rename_os_error_and_shutil_os_error(tmp_path):
    """renameとshutil.copy2がOSErrorを投げた際、最終的にOSErrorが送出されること"""
    from unittest.mock import patch
    import pytest
    from progressive_preview_report import generate_progressive_preview_thumbnail
    
    output_path = tmp_path / "rename_fail.png"
    
    # renameとshutil.copy2の両方がOSErrorを投げるようにモックする
    with patch("pathlib.Path.rename", side_effect=OSError("Mocked rename error")), \
         patch("shutil.copy2", side_effect=OSError("Mocked copy2 error")):
        with pytest.raises(OSError) as exc:
            generate_progressive_preview_thumbnail(output_path, text="Rename failure test")
        assert "Fallback failed to rename temp file" in str(exc.value)
