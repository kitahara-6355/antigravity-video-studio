def main():
    file_path = "backend/tests/test_fitness_functions.py"
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    is_crlf = "\r\n" in content
    content_lf = content.replace("\r\n", "\n")

    # テストクラスの定義を追加
    test_code = """

# ============================================================
# FF-29: プレミアムサムネイル画像生成および品質検証の自動化
# ============================================================

class TestFF29PremiumThumbnailQuality:
    \"\"\"FF-29: プレミアムサムネイル画像生成の品質検証と StageBoundAgent 連携の検証\"\"\"

    @pytest.mark.anyio
    async def test_premium_thumbnail_quality_and_load(self, tmp_path):
        \"\"\"生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能であること\"\"\"
        from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
        from PIL import Image

        out_path = tmp_path / "premium_thumbnail_test.png"
        
        # 1. 画像生成の実行
        PremiumThumbnailGenerator.generate(
            out_path,
            width=1280,
            height=720,
            text="FF29 Quality Test",
            draw_arrow=True,
            draw_circle=True,
            use_banner=True
        )

        assert out_path.exists()

        # 2. ファイルを読み込んで検証
        with open(out_path, "rb") as f:
            img_bytes = f.read()

        # 品質要件の検証
        assert ThumbnailValidator.validate_image(img_bytes)

        # 3. Pillowロードの確認
        with Image.open(out_path) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05
            assert len(img_bytes) < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_stage_bound_agent_integration(self, tmp_path):
        \"\"\"StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができること\"\"\"
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import resolve_thumbnail_task

        db_file = tmp_path / "test_tasks_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "task-thumbnail-ff29-001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動 (resolve_thumbnail_task をバインドして登録)
        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=str(tmp_path))

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        
        # さらに結果が thumbnail_results テーブルにも保存されていることを確認
        cursor_res = conn.execute("SELECT width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row_res = cursor_res.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0  # リトライなしで成功したこと

        assert row_res is not None
        assert row_res[0] >= 1280
        assert row_res[1] >= 720
        assert row_res[2] > 0

        await agent.stop()

    @pytest.mark.anyio
    async def test_stage_bound_agent_retry_on_failure(self, tmp_path):
        \"\"\"例外発生時に自動リトライが走り、最終的に FAILED ステータスになることの検証\"\"\"
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import resolve_thumbnail_task

        db_file = tmp_path / "test_tasks_thumbnail_retry.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "task-thumbnail-fail-001"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 無効な出力先を設定し例外をスローさせる
        invalid_output_dir = "invalid://path/does/not/exist"

        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=invalid_output_dir)

        await agent.start(process_task)

        # FAILED を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数の確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が残っている

        await agent.stop()

    @pytest.mark.anyio
    async def test_thumbnail_corrupted_image(self, tmp_path):
        \"\"\"破損画像（PNG/JPEGの末尾が欠損しているものなど）に対して適切に ImageValidationError が発生することを検証\"\"\"
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        
        # 1. 短すぎるデータ
        short_bytes = b"\\x89PNG\\r\\n\\x1a\\n12345"
        with pytest.raises(ImageValidationError, match="too small|invalid PNG"):
            ThumbnailValidator.validate_image(short_bytes)

        # 2. PNGヘッダはあるがIENDがないもの
        corrupted_png = b"\\x89PNG\\r\\n\\x1a\\n" + b"\\x00" * 50
        with pytest.raises(ImageValidationError, match="corrupted|IEND"):
            ThumbnailValidator.validate_image(corrupted_png)

        # 3. JPEGヘッダはあるがEOIがないもの
        corrupted_jpeg = b"\\xff\\xd8" + b"\\x00" * 50
        with pytest.raises(ImageValidationError, match="corrupted|EOI"):
            ThumbnailValidator.validate_image(corrupted_jpeg)

    @pytest.mark.anyio
    async def test_thumbnail_resolution_aspect_ratio_boundaries(self):
        \"\"\"解像度やアスペクト比の境界値に対する検証エラー検出\"\"\"
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io

        # 1. 1280x720 未満 (例: 1000x562, アスペクト比は16:9に近い)
        img_small = Image.new("RGB", (1000, 562), color="red")
        f_small = io.BytesIO()
        img_small.save(f_small, format="PNG")
        with pytest.raises(ImageValidationError, match="below minimum requirement"):
            ThumbnailValidator.validate_image(f_small.getvalue())

        # 2. アスペクト比が 16:9 でない (例: 1280x1280, 1:1)
        img_square = Image.new("RGB", (1280, 1280), color="blue")
        f_square = io.BytesIO()
        img_square.save(f_square, format="PNG")
        with pytest.raises(ImageValidationError, match="Aspect ratio"):
            ThumbnailValidator.validate_image(f_square.getvalue())
"""

    content_lf += test_code

    if is_crlf:
        final_content = content_lf.replace("\n", "\r\n")
    else:
        final_content = content_lf

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(final_content)
    print("Successfully appended FF-29 test class to test_fitness_functions.py")

if __name__ == '__main__':
    main()
