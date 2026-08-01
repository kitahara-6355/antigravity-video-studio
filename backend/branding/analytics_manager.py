# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import random
import json
import os
from datetime import datetime, timedelta

class AnalyticsManager:
    """
    Manages real-world data link (YouTube Analytics) and Rival System.
    Currently operates in MOCK mode for development.
    """
    def __init__(self):
        # Mock Data Store
        self.mock_my_stats = {
            "subscribers": 150,
            "total_views": 4500,
            "videos": 12,
            "last_updated": datetime.now().isoformat()
        }
        
        # Mock Database of potential rivals
        self.mock_rival_db = [
            {"name": "TechStarter", "subs": 180, "views": 5000, "genre": "Tech"}, # Nemesis Candidate
            {"name": "GadgetReviewer", "subs": 250, "views": 8000, "genre": "Tech"}, # Nemesis Candidate
            {"name": "CodeLife", "subs": 1200, "views": 50000, "genre": "Vlog"},
            {"name": "TechMastery", "subs": 15000, "views": 1500000, "genre": "Tech"}, # Benchmark Candidate
            {"name": "CinemaGod", "subs": 1000000, "views": 90000000, "genre": "Cinema"} # Benchmark Candidate
        ]

    def get_my_stats(self):
        """Fetches current channel statistics."""
        # TODO: Replace with real YouTube API call
        return self.mock_my_stats

    def scout_rivals(self, my_stats):
        """
        Implements the Dual-Tier Rival System Logic.
        1. Nemesis: +10% ~ +50% Subscribers
        2. Benchmark: x10 ~ x100 Subscribers
        """
        rivals = {
            "nemesis": None,
            "benchmark": None
        }
        if not my_stats or not isinstance(my_stats, dict):
            return rivals

        current_subs = my_stats.get('subscribers', 0)
        if current_subs <= 0:
            return rivals

        # Logic for Nemesis (The Good Rival)
        # Goldilocks Rule: Not too hard, not too easy.
        nemesis_candidates = [
            r for r in self.mock_rival_db 
            if 1.1 <= (r['subs'] / current_subs) <= 1.5
        ]
        if nemesis_candidates:
            rivals['nemesis'] = random.choice(nemesis_candidates)

        # Logic for Benchmark (The Mentor)
        # Social Comparison: The ideal self.
        benchmark_candidates = [
            r for r in self.mock_rival_db 
            if 10 <= (r['subs'] / current_subs) <= 100
        ]
        if benchmark_candidates:
            rivals['benchmark'] = random.choice(benchmark_candidates)
            
        return rivals

    def calculate_gap(self, my_stats, rivals):
        """
        Calculates the 'Distance' to targets for Gamification.
        Returns a 'Quest' object.
        """
        quests = []
        if not my_stats or not isinstance(my_stats, dict) or not rivals or not isinstance(rivals, dict):
            return quests
        
        if rivals.get('nemesis'):
            n = rivals['nemesis']
            if isinstance(n, dict) and 'subs' in n and 'subscribers' in my_stats:
                gap = n['subs'] - my_stats['subscribers']
                quests.append({
                    "type": "NEMESIS_BATTLE",
                    "target_name": n['name'],
                    "target_val": n['subs'],
                    "current_val": my_stats['subscribers'],
                    "gap": gap,
                    "reward_xp": 100 # Biz XP Reward
                })
            
        return quests

    # --- Simulation Tools ---
    def sim_add_views(self, amount):
        """Debug tool to simulate viral hit."""
        self.mock_my_stats['total_views'] += amount
        # Simple logic: 1 sub per 100 views
        new_subs = int(amount / 100)
        self.mock_my_stats['subscribers'] += new_subs
        return {
            "added_views": amount,
            "added_subs": new_subs,
            "new_stats": self.mock_my_stats
        }

    async def generate_and_validate_thumbnail(
        self,
        task_id: str,
        title: str,
        text: str = "Thumbnail",
        db_path: str = ":memory:",
        output_dir=None,
        max_retries: int = 2,
        width: int = 1280,
        height: int = 720,
        aspect_ratio: str = "16:9",
        max_size_bytes: int = 4 * 1024 * 1024,
        draw_arrow: bool = False,
        draw_circle: bool = False,
        use_banner: bool = True
    ) -> dict:
        """
        StageBoundAgentと連携してサムネイル画像を生成・検証し、
        結果をDBマイグレーション機能と連携して保存する。
        自動リトライやエラーハンドリングを適用する。
        """
        import sqlite3
        import time
        import json
        import logging
        import asyncio
        from pathlib import Path
        
        # 既存ロガーの取得
        logger = logging.getLogger(__name__)
        
        # インフラ関係のインポート
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import ThumbnailValidator, PremiumThumbnailGenerator, ImageValidationError
        
        # パラメータの事前検証（回復不能なエラーはリトライ前にValueErrorを発生させて無駄なリトライを防ぐ）
        if not title or not title.strip():
            raise ValueError("Video title cannot be empty")
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Resolution must be positive integers. Got {width}x{height}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        if max_size_bytes <= 0:
            raise ValueError(f"Max size bytes must be positive. Got {max_size_bytes}")
            
        # アスペクト比の事前チェック
        if aspect_ratio == "16:9":
            target_ratio = 16.0 / 9.0
            actual_ratio = float(width) / float(height)
            if abs(actual_ratio - target_ratio) > 0.05:
                raise ValueError(f"Aspect ratio must be 16:9. Got {actual_ratio:.3f}")
        
        if output_dir is None:
            # プロジェクトルート以下の temp_thumbnails
            output_dir = _writable_path("temp_thumbnails")
        else:
            output_dir = Path(output_dir)
            
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}.png"
        
        # StageBoundAgent の初期化
        agent = StageBoundAgent(stage_name="thumbnail", db_path=db_path)
        
        # 実際の処理を定義（非同期）
        async def process_func(tid: str) -> str:
            # 1. プレミアムサムネイルの生成
            try:
                PremiumThumbnailGenerator.generate(
                    output_path=output_path,
                    width=width,
                    height=height,
                    text=text,
                    draw_arrow=draw_arrow,
                    draw_circle=draw_circle,
                    use_banner=use_banner
                )
            except (OSError, ValueError, TypeError) as e:
                logger.error(f"Image generation failed: {e}", exc_info=True)
                raise ImageValidationError(f"Failed to generate premium thumbnail image: {e}") from e
                
            # 2. 生成されたファイルの存在確認
            if not output_path.exists():
                raise FileNotFoundError(f"Generated thumbnail file not found at: {output_path}")
                
            # 3. 画像バイナリの読み込みと品質要件の検証
            try:
                with open(output_path, "rb") as f:
                    img_bytes = f.read()
            except OSError as e:
                raise ImageValidationError(f"Failed to read generated image bytes: {e}") from e
                
            # 4. バリデーション (Pillowによるロード破損チェック & 各要件検証)
            try:
                from PIL import Image, UnidentifiedImageError
                import io
                # verify と load の両方で厳格にチェック
                with Image.open(io.BytesIO(img_bytes)) as img:
                    img.verify()
                with Image.open(io.BytesIO(img_bytes)) as img:
                    img.load()
            except UnidentifiedImageError as uie:
                raise ImageValidationError(f"Generated image is not a recognized image format: {uie}") from uie
            except (OSError, ValueError, SyntaxError) as e:
                raise ImageValidationError(f"Generated image is corrupted or invalid format: {e}") from e
                
            # 閾値を動的に検証
            ThumbnailValidator.validate_image(
                img_bytes,
                min_width=width,
                min_height=height,
                aspect_ratio=aspect_ratio,
                max_size_bytes=max_size_bytes
            )
            
            # 5. DBマイグレーション & 結果保存
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS thumbnail_results (
                        task_id TEXT PRIMARY KEY,
                        path TEXT,
                        width INTEGER,
                        height INTEGER,
                        size_bytes INTEGER,
                        verified_at REAL
                    )
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO thumbnail_results VALUES (?, ?, ?, ?, ?, ?)",
                    (tid, str(output_path), width, height, len(img_bytes), time.time())
                )
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Failed to write to migration DB: {e}")
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise e
            finally:
                conn.close()
                
            res = {
                "task_id": tid,
                "path": str(output_path),
                "width": width,
                "height": height,
                "size_bytes": len(img_bytes),
                "verified_at": time.time()
            }
            return json.dumps(res)
            
        # タスク登録
        await agent.register_task(task_id, initial_status="READY", max_retries=max_retries)
        
        # エージェント開始
        await agent.start(process_func)
        
        # 完了または失敗まで待機するポーリング処理
        final_status = "PENDING"
        timeout = 30.0
        start_time = time.time()
        
        try:
            while time.time() - start_time < timeout:
                final_status = await agent.get_task_status(task_id)
                if final_status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
        finally:
            # 確実にエージェントのポーリングループを停止する
            await agent.stop()
            
        if final_status == "COMPLETED":
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT result FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                if row and row["result"]:
                    return json.loads(row["result"])
            finally:
                conn.close()
            # 万が一結果がDBから読めない場合のフォールバック
            return {
                "task_id": task_id,
                "path": str(output_path),
                "width": width,
                "height": height,
                "verified_at": time.time()
            }
        elif final_status == "FAILED":
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT error FROM tasks WHERE id = ?", (task_id,))
                row = cursor.fetchone()
                err_msg = row["error"] if row else "Unknown error"
            finally:
                conn.close()
            raise RuntimeError(f"Thumbnail generation task failed: {err_msg}")
        else:
            # タイムアウトした場合、DBのステータスを FAILED に更新してタイムアウトエラー内容を記録
            try:
                conn = sqlite3.connect(db_path, timeout=30.0)
                conn.execute(
                    "UPDATE tasks SET status = 'FAILED', error = ?, updated_at = ? WHERE id = ?",
                    ("Thumbnail generation timed out", time.time(), task_id)
                )
                conn.commit()
                conn.close()
            except sqlite3.Error as e:
                logger.error(f"Failed to set timeout status to FAILED in DB: {e}")
            raise TimeoutError("Thumbnail generation timed out")



analytics_manager = AnalyticsManager()
