import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "branding"
AB_TESTS_FILE = DATA_DIR / "ab_tests.json"

class YouTubeABTestService:
    """
    [Phase 1.4: A/B Test API Bridge]
    YouTube Studio 2026のネイティブA/Bテスト機能（サムネ+タイトル）との連携を想定したブリッジ。
    ※APIが公式提供されるまでのスタブ/モック実装を含む
    """
    def __init__(self):
        self._loaded = False
        self._active_tests = {}
        self._load_error_occurred = False

    @property
    def active_tests(self) -> Dict[str, Any]:
        """A/Bテストデータの遅延ロード"""
        if not self._loaded:
            try:
                self._ensure_file_exists()
                loaded_data = self._load()
                if loaded_data is not None:
                    self._active_tests = loaded_data
                    self._loaded = True
                    self._load_error_occurred = False
                else:
                    self._load_error_occurred = True
            except (OSError, TypeError, ValueError) as e:
                logger.error(f"Storage initialization failed during active_tests load: {e}")
                self._load_error_occurred = True
                self._active_tests = {}
                self._loaded = True
        return self._active_tests

    @active_tests.setter
    def active_tests(self, value: Dict[str, Any]):
        self._active_tests = value
        self._loaded = True
        self._load_error_occurred = False
        
    def _ensure_file_exists(self):
        if not DATA_DIR.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not AB_TESTS_FILE.exists():
            with open(AB_TESTS_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

    def _load(self) -> Optional[Dict[str, Any]]:
        """永続化ファイルの読み込み (Fix③)"""
        try:
            with open(AB_TESTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load AB tests: {e}")
            return None

    def _save(self):
        """永続化ファイルの書き込み (Fix③)"""
        if self._load_error_occurred:
            logger.error("Skipping save because the last load operation failed. Preventing data corruption.")
            return
        try:
            with open(AB_TESTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.active_tests, f, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save AB tests: {e}")
        
    async def register_ab_test(self, video_id: str, title_candidates: List[str], thumbnail_paths: List[str]) -> str:
        """
        最大3案のサムネイルとタイトルをYouTubeのA/Bテストシステムに登録する
        """
        if not isinstance(video_id, str):
            raise TypeError("video_id must be a string")
        if not isinstance(title_candidates, (list, tuple)):
            raise TypeError("title_candidates must be a list or tuple")
        if not isinstance(thumbnail_paths, (list, tuple)):
            raise TypeError("thumbnail_paths must be a list or tuple")

        if not video_id.strip():
            raise ValueError("video_id cannot be empty")
        if not title_candidates:
            raise ValueError("title_candidates cannot be empty")
        if not thumbnail_paths:
            raise ValueError("thumbnail_paths cannot be empty")

        if len(title_candidates) != len(thumbnail_paths):
            raise ValueError("The number of title_candidates and thumbnail_paths must be equal")

        for i, title in enumerate(title_candidates):
            if not isinstance(title, str):
                raise TypeError(f"title_candidates[{i}] must be a string")
            if not title.strip():
                raise ValueError(f"title_candidates[{i}] cannot be empty")

        for i, path in enumerate(thumbnail_paths):
            if not isinstance(path, str):
                raise TypeError(f"thumbnail_paths[{i}] must be a string")
            if not path.strip():
                raise ValueError(f"thumbnail_paths[{i}] cannot be empty")

        title_candidates = list(title_candidates)
        thumbnail_paths = list(thumbnail_paths)

        if len(thumbnail_paths) > 3 or len(title_candidates) > 3:
            logger.warning("YouTube native A/B test only supports up to 3 variants. Truncating.")
            thumbnail_paths = thumbnail_paths[:3]
            title_candidates = title_candidates[:3]
            
        test_id = f"ab_test_{video_id}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        
        self.active_tests[test_id] = {
            "video_id": video_id,
            "titles": title_candidates,
            "thumbnails": thumbnail_paths,
            "status": "RUNNING",
            "start_time": datetime.now().isoformat()
        }
        self._save()
        
        logger.info(f"🧪 [A/B Test Service] Started test {test_id} for video {video_id} with {len(thumbnail_paths)} variants.")
        return test_id
        
    async def get_test_results(self, test_id: str) -> Dict[str, Any]:
        """
        72時間後などにテスト結果を取得する（モック）
        """
        if not test_id:
            return {"error": "Invalid test_id"}

        if test_id not in self.active_tests:
            return {"error": "Test not found"}
            
        test_info = self.active_tests[test_id]
        
        # モックのテスト結果
        mock_results = {
            "test_id": test_id,
            "video_id": test_info.get("video_id", ""),
            "winner_index": 0,  # 0番目が勝者と仮定
            "variants": []
        }
        
        thumbnails = test_info.get("thumbnails", [])
        total_variants = len(thumbnails)
        if total_variants == 0:
            return mock_results
        
        for i in range(total_variants):
            # Fix②: total_variants == 1 のとき (total_variants - 1) == 0 でZeroDivisionError になるバグを修正
            if total_variants > 1:
                loser_watch_share = round(60.0 / (total_variants - 1), 1)
            else:
                loser_watch_share = 0.0
                
            titles = test_info.get("titles", [])
            if titles:
                variant_title = titles[i] if i < len(titles) else titles[0]
            else:
                variant_title = "Untitled Variant"

            mock_results["variants"].append({
                "index": i,
                "title": variant_title,
                "thumbnail": thumbnails[i],
                "watch_time_share": 40.0 if i == 0 else loser_watch_share,
                "ctr": 5.2 if i == 0 else 3.1
            })
            
        return mock_results
        
    async def distill_results_to_knowledge(self, test_results: Dict[str, Any], wagamama_manager=None) -> bool:
        """
        A/Bテストの「勝者」の傾向をAnalystの知識DBにパターンとして蒸留する (Fix②)
        """
        if not isinstance(test_results, dict):
            logger.error("test_results must be a dictionary.")
            return False

        if "error" in test_results:
            return False
            
        variants = test_results.get("variants", [])
        if not isinstance(variants, list) or not variants:
            logger.warning("No variants found in test results.")
            return False

        winner_idx = test_results.get("winner_index", 0)
        if not isinstance(winner_idx, int) or winner_idx < 0 or winner_idx >= len(variants):
            logger.warning(f"winner_index {winner_idx} is invalid or out of bounds.")
            return False

        winner = variants[winner_idx]
        if not isinstance(winner, dict):
            logger.warning("Winner variant is not a dictionary.")
            return False

        test_id = test_results.get("test_id", "unknown_test")
        winner_title = winner.get("title", "Untitled Variant")
        winner_ctr = winner.get("ctr", 0.0)

        distilled_pattern = f"A/B Test {test_id}: '{winner_title}' strongly outperformed variants with CTR {winner_ctr}%. Correlates with higher watch-time retention."
        
        logger.info(f"🧠 [A/B Test Service] Distilled Pattern: {distilled_pattern}")
        
        if wagamama_manager:
            if hasattr(wagamama_manager, "add_distilled_knowledge"):
                try:
                    # 取得結果を Wagamama Manager を通して知識として登録する
                    wagamama_manager.add_distilled_knowledge(
                        topic="A/B Test Winner",
                        pattern=distilled_pattern,
                        confidence=0.9
                    )
                except (OSError, TypeError, ValueError, RuntimeError) as e:
                    logger.error(f"Failed to add distilled knowledge to wagamama_manager: {e}")
            else:
                logger.warning("wagamama_manager does not have add_distilled_knowledge method.")
            
        # テストを完了状態にする
        if test_id in self.active_tests:
            self.active_tests[test_id]["status"] = "COMPLETED"
            self._save()
            
        return True

# Singleton
ab_test_service = YouTubeABTestService()
