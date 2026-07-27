"""
Cleanup Manager - 自動クリーンアップシステム

Progressive Quality Pipeline Phase 2
古い一時ファイルの自動削除とRAW動画の保護

設計原則:
- RAW動画は絶対に削除しない（protected = True）
- 中間ファイルは保持期間と最大件数で管理
- 再生成可能なファイルは積極的に削除
"""

import os
import time
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CleanupRule:
    """クリーンアップルール"""
    category: str
    directory: Path
    retention_days: Optional[int]  # None = 永久保持
    max_count: Optional[int]       # None = 無制限
    protected: bool = False        # True = 絶対削除禁止
    extensions: List[str] = None   # 対象拡張子

    def __post_init__(self):
        # directoryをPathオブジェクトに強制し、表記ゆれを防ぐ
        try:
            if not isinstance(self.directory, Path):
                self.directory = Path(self.directory)
        except (TypeError, ValueError, OSError, AttributeError) as e:
            logger.warning(f"⚠️ Invalid directory for {self.category}, fallback to path: {e}")
            
        # retention_daysの型と値のバリデーション
        if self.retention_days is not None:
            try:
                self.retention_days = int(self.retention_days)
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Invalid retention_days '{self.retention_days}' for {self.category}: {e}")
                self.retention_days = None

        # max_countの型と値のバリデーション
        if self.max_count is not None:
            try:
                self.max_count = int(self.max_count)
            except (ValueError, TypeError) as e:
                logger.warning(f"⚠️ Invalid max_count '{self.max_count}' for {self.category}: {e}")
                self.max_count = None


class CleanupManager:
    """自動クリーンアップ管理クラス"""
    
    def __init__(self):
        """初期化"""
        base_dir = Path(__file__).parent
        
        # クリーンアップルール定義
        self.rules: Dict[str, CleanupRule] = {
            "screenshots": CleanupRule(
                category="screenshots",
                directory=base_dir / "temp" / "previews",
                retention_days=7,
                max_count=100,
                protected=False,
                extensions=[".png", ".jpg", ".jpeg", ".webp"]
            ),
            "drafts": CleanupRule(
                category="drafts",
                directory=base_dir / "temp" / "drafts" / "drafts",
                retention_days=3,
                max_count=10,
                protected=False,
                extensions=[".mp4", ".webm"]
            ),
            "prefinal": CleanupRule(
                category="prefinal",
                directory=base_dir / "temp" / "drafts" / "prefinal",
                retention_days=1,
                max_count=3,
                protected=False,
                extensions=[".mp4"]
            ),
            "final": CleanupRule(
                category="final",
                directory=base_dir / "temp" / "drafts" / "final",
                retention_days=None,  # 永久保持
                max_count=None,
                protected=True,  # 保護対象
                extensions=[".mp4", ".srt"]
            ),
            "raw": CleanupRule(
                category="raw",
                directory=base_dir / "videos",  # RAW動画ディレクトリ
                retention_days=None,
                max_count=None,
                protected=True,  # 絶対削除禁止
                extensions=[".mp4", ".mov", ".avi", ".mkv"]
            ),
            "video_output": CleanupRule(
                category="video_output",
                directory=base_dir / "temp" / "video_output",
                retention_days=7,
                max_count=20,
                protected=False,
                extensions=[".mp4"]
            )
        }
        
        # ディレクトリ作成は必要になるまで遅延評価 (Lazy Creation) します
        pass

    def _ensure_directories_exist(self) -> None:
        """必要なディレクトリが確実に存在することを確認（遅延評価用）"""
        for rule in self.rules.values():
            try:
                rule.directory.mkdir(parents=True, exist_ok=True)
            except (OSError, TypeError, AttributeError) as e:
                logger.warning(f"⚠️ Failed to create directory {rule.directory}: {e}")
    
    def is_protected(self, path: str) -> bool:
        """
        保護対象かどうかを判定
        
        Args:
            path: ファイルパス
        
        Returns:
            True = 削除禁止
        """
        if path is None:
            logger.warning("⚠️ is_protected received None path")
            return False
            
        if not isinstance(path, (str, Path)):
            logger.error(f"❌ Invalid path type in is_protected: {type(path)}")
            return False
            
        try:
            # 入力を文字列に標準化してから絶対パス化・小文字正規化
            abs_path = os.path.abspath(str(path))
            norm_path = Path(abs_path.lower())
        except (TypeError, ValueError) as e:
            logger.error(f"❌ Invalid path format in is_protected: {path}, error: {e}")
            return False
        
        for rule in self.rules.values():
            if rule.protected:
                try:
                    # ディレクトリパスも絶対パス化し小文字化して表記ゆれを許容
                    norm_dir = Path(os.path.abspath(rule.directory).lower())
                    # パスがルールのディレクトリ内にあるかチェック
                    norm_path.relative_to(norm_dir)
                    logger.warning(f"⚠️ Protected file: {path}")
                    return True
                except ValueError:
                    continue
                except (TypeError, AttributeError) as e:
                    try:
                        dir_str = str(rule.directory)
                    except (TypeError, ValueError, AttributeError):
                        dir_str = "<unprintable directory>"
                    logger.warning(f"⚠️ TypeError/AttributeError in is_protected checking rule {rule.category} with directory {dir_str}: {e}", exc_info=True)
                    continue
        
        return False
    
    def cleanup(self, category: str = None, dry_run: bool = False) -> Dict:
        """
        クリーンアップを実行
        
        Args:
            category: 対象カテゴリ（Noneで全カテゴリ）
            dry_run: Trueの場合、削除せずにリストのみ返す
        
        Returns:
            削除結果レポート
        """
        results = {
            "deleted": [],
            "protected": [],
            "freed_bytes": 0,
            "dry_run": dry_run
        }
        
        # ディレクトリの存在を保証 (遅延評価)
        self._ensure_directories_exist()

        if category is not None:
            if not isinstance(category, str):
                logger.error(f"❌ Cleanup category must be a string, got: {type(category)}")
                return results
            if category not in self.rules:
                logger.error(f"❌ Unknown cleanup category: {category}")
                return results
            rules_to_process = [self.rules[category]]
        else:
            rules_to_process = self.rules.values()
        
        for rule in rules_to_process:
            if rule.protected:
                logger.info(f"⏭️ Skipping protected category: {rule.category}")
                continue
            
            try:
                if not rule.directory.exists():
                    continue
            except (OSError, AttributeError) as e:
                logger.error(f"❌ Error accessing directory {rule.directory}: {e}")
                continue
            
            # 対象ファイルを取得
            files = []
            try:
                for ext in (rule.extensions or ["*"]):
                    pattern = ext if ext == "*" else f"*{ext}"
                    try:
                        files.extend(rule.directory.glob(pattern, case_sensitive=False))
                    except TypeError:
                        # Fallback for Python versions before 3.13
                        files.extend(rule.directory.glob(pattern))
            except (OSError, TypeError, ValueError) as e:
                logger.error(f"❌ Error listing files in {rule.directory}: {e}")
                continue
            
            if not files:
                continue
            
            # 削除対象を決定
            files_to_delete = []
            
            # 保持期間チェック
            if rule.retention_days is not None:
                try:
                    retention_days = rule.retention_days
                    if isinstance(retention_days, (int, float)) and retention_days < 0:
                        logger.warning(f"⚠️ Negative retention_days detected for {rule.category}: {retention_days}. Skipping retention check.")
                        cutoff_time = 0
                    else:
                        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
                    
                    if cutoff_time > 0:
                        for f in files:
                            try:
                                if f.stat().st_mtime < cutoff_time:
                                    files_to_delete.append(f)
                            except (FileNotFoundError, OSError):
                                continue
                except (TypeError, ValueError) as e:
                    logger.error(f"❌ Error during retention check calculation: {e}")
            
            # 最大件数チェック
            if rule.max_count is not None:
                try:
                    max_count = rule.max_count
                    if isinstance(max_count, int) and max_count < 0:
                        logger.warning(f"⚠️ Negative max_count detected for {rule.category}: {max_count}. Skipping max_count check.")
                        max_count = None
                    
                    if max_count is not None:
                        valid_files_with_mtime = []
                        for f in files:
                            try:
                                mtime = f.stat().st_mtime
                                valid_files_with_mtime.append((f, mtime))
                            except (FileNotFoundError, OSError):
                                continue
                        
                        # 新しい順にソート (mtimeでソート)
                        files_sorted = sorted(valid_files_with_mtime, key=lambda x: x[1], reverse=True)
                        if len(files_sorted) > max_count:
                            files_to_delete.extend([x[0] for x in files_sorted[max_count:]])
                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(f"❌ Error sorting files by mtime: {e}")
            
            # 重複を除去
            files_to_delete = list(set(files_to_delete))
            
            # 削除実行
            for f in files_to_delete:
                if self.is_protected(str(f)):
                    results["protected"].append(str(f))
                    continue
                
                try:
                    size = f.stat().st_size
                except (FileNotFoundError, OSError):
                    size = 0
                
                if not dry_run:
                    try:
                        f.unlink()
                        logger.info(f"🗑️ Deleted: {f.name}")
                        results["deleted"].append(str(f))
                        results["freed_bytes"] += size
                    except OSError as e:
                        logger.error(f"❌ Failed to delete {f}: {e}", exc_info=True)
                    except (ValueError, TypeError) as e:
                        # パス指定や型不整合などの予期せぬ例外を保護
                        logger.error(f"❌ Unexpected error failed to delete {f}: {e}", exc_info=True)
                else:
                    results["deleted"].append(str(f))
                    results["freed_bytes"] += size
        
        freed_mb = results["freed_bytes"] / (1024 * 1024)
        logger.info(f"✅ Cleanup complete: {len(results['deleted'])} files, {freed_mb:.1f}MB freed")
        
        return results
    
    def get_storage_stats(self) -> Dict:
        """
        ストレージ使用状況を取得
        
        Returns:
            カテゴリ別のストレージ使用状況
        """
        stats = {
            "categories": {},
            "total_size_mb": 0,
            "protected_size_mb": 0
        }
        
        # ディレクトリの存在を保証 (遅延評価)
        self._ensure_directories_exist()

        for name, rule in self.rules.items():
            try:
                if not rule.directory.exists():
                    stats["categories"][name] = {
                        "count": 0,
                        "size_mb": 0,
                        "protected": rule.protected,
                        "retention_days": rule.retention_days,
                        "max_count": rule.max_count
                    }
                    continue
            except (OSError, AttributeError) as e:
                logger.error(f"❌ Error checking directory existence for {name}: {e}")
                stats["categories"][name] = {
                    "count": 0,
                    "size_mb": 0,
                    "protected": rule.protected,
                    "retention_days": rule.retention_days,
                    "max_count": rule.max_count
                }
                continue
            
            files = []
            try:
                for ext in (rule.extensions or ["*"]):
                    pattern = ext if ext == "*" else f"*{ext}"
                    try:
                        files.extend(rule.directory.glob(pattern, case_sensitive=False))
                    except TypeError:
                        # Fallback for Python versions before 3.13
                        files.extend(rule.directory.glob(pattern))
            except (OSError, TypeError) as e:
                logger.error(f"❌ Error listing files for stats in {rule.directory}: {e}")
            
            total_size = 0
            mtimes = []
            for f in files:
                try:
                    if f.is_file():
                        total_size += f.stat().st_size
                        mtimes.append(f.stat().st_mtime)
                except (FileNotFoundError, OSError):
                    continue
            
            size_mb = total_size / (1024 * 1024)
            
            stats["categories"][name] = {
                "count": len(mtimes),
                "size_mb": round(size_mb, 2),
                "protected": rule.protected,
                "retention_days": rule.retention_days,
                "max_count": rule.max_count,
                "oldest_file": min(mtimes, default=None),
                "newest_file": max(mtimes, default=None)
            }
            
            stats["total_size_mb"] += size_mb
            if rule.protected:
                stats["protected_size_mb"] += size_mb
        
        stats["total_size_mb"] = round(stats["total_size_mb"], 2)
        stats["protected_size_mb"] = round(stats["protected_size_mb"], 2)
        stats["deletable_size_mb"] = round(stats["total_size_mb"] - stats["protected_size_mb"], 2)
        
        return stats
    
    def preview_cleanup(self) -> Dict:
        """
        クリーンアップのプレビュー（削除せずに結果を表示）
        
        Returns:
            削除予定 of files
        """
        return self.cleanup(dry_run=True)

    def auto_cleanup(self) -> Dict:
        """パイプライン完了後の自動クリーンアップ統合メソッド

        Sprint 4.3.2: パイプライン完了フックから呼出される。
        以下を一括実行:
        1. ストレージクリーンアップ (§11 保護階層準拠)
        2. trust_history 100件トリミング (m-02)
        3. pending_proposals 50件トリミング (m-03)
        4. cleanup結果をevolution_logに記録 (§12.3 appendのみ)

        Returns:
            cleanup結果辞書
        """
        # 1. ストレージクリーンアップ実行
        result = self.cleanup()
        logger.info(
            f"🧹 [auto_cleanup] 完了: "
            f"{len(result.get('deleted', []))} files, "
            f"{result.get('freed_bytes', 0) / (1024*1024):.1f}MB freed"
        )

        # 2. m-02: trust_history トリミング統合呼出
        try:
            from services.evolution_trigger_service import EvolutionTriggerService
            try:
                trigger_svc = EvolutionTriggerService()
            except (TypeError, ValueError, OSError) as e:
                logger.warning(f"[auto_cleanup] EvolutionTriggerService initialization failed (expected error): {e}", exc_info=True)
                trigger_svc = None
            except (AttributeError, RuntimeError, ImportError, KeyError, NameError, Exception) as e:
                logger.error(f"[auto_cleanup] EvolutionTriggerService initialization failed (unexpected error): {e}", exc_info=True)
                trigger_svc = None
        except (ImportError, ModuleNotFoundError) as e:
            logger.info(f"[auto_cleanup] EvolutionTriggerService is unavailable (ImportError): {e}")
            trigger_svc = None

        if trigger_svc is not None:
            try:
                evo_log = trigger_svc._load_evolution_log()
                trigger_svc._trim_trust_history(evo_log)
                trigger_svc._save_evolution_log(evo_log)
            except OSError as e:
                logger.warning(f"[auto_cleanup] Failed to read/write evolution log file (expected error): {e}", exc_info=True)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[auto_cleanup] trust_history structure error: {e}", exc_info=True)
            except (AttributeError, RuntimeError, KeyError, IndexError, Exception) as e:
                logger.error(f"[auto_cleanup] trust_history trim失敗 (unexpected error): {e}", exc_info=True)

        # 3. m-03: pending_proposals トリミング統合呼出
        try:
            from services.philosophy_proposal_service import PhilosophyProposalService

            try:
                proposal_svc = PhilosophyProposalService()
            except (TypeError, ValueError, OSError) as e:
                logger.warning(f"[auto_cleanup] PhilosophyProposalService initialization failed (expected error): {e}", exc_info=True)
                proposal_svc = None
            except (AttributeError, RuntimeError, ImportError, KeyError, NameError, Exception) as e:
                logger.error(f"[auto_cleanup] PhilosophyProposalService initialization failed (unexpected error): {e}", exc_info=True)
                proposal_svc = None
        except (ImportError, ModuleNotFoundError) as e:
            logger.info(f"[auto_cleanup] PhilosophyProposalService is unavailable (ImportError): {e}")
            proposal_svc = None

        if proposal_svc is not None:
            try:
                proposal_svc._trim_pending_proposals()
            except OSError as e:
                logger.warning(f"[auto_cleanup] Failed to trim pending proposals file (expected error): {e}", exc_info=True)
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"[auto_cleanup] pending_proposals structure error: {e}", exc_info=True)
            except (AttributeError, RuntimeError, KeyError, IndexError, Exception) as e:
                logger.error(f"[auto_cleanup] pending_proposals trim失敗 (unexpected error): {e}", exc_info=True)

        # 4. evolution_logにcleanup結果を記録
        self.report_to_evolution_log(result)

        return result

    def report_to_evolution_log(self, cleanup_result: Dict, evolution_log_path: Path = None) -> None:
        """cleanup結果をevolution_logに記録 (§12.3: appendのみ)

        Sprint 4.3.2: cleanup実行結果をevolution_log.jsonのentriesに追記。
        既存エントリは絶対に上書き・削除しない。

        Args:
            cleanup_result: cleanup()の戻り値
            evolution_log_path: evolution_logのパス (テスト用オーバーライド)
        """
        import json
        from datetime import datetime

        if not isinstance(cleanup_result, dict):
            logger.error(f"❌ cleanup_result must be a dictionary, got: {type(cleanup_result)}")
            return

        if evolution_log_path is not None:
            try:
                evo_path = Path(evolution_log_path)
            except (TypeError, ValueError) as e:
                logger.error(f"❌ Invalid evolution_log_path (expected): {evolution_log_path}, error: {e}")
                return
        else:
            evo_path = (
                Path(__file__).parent / "branding" / "evolution_log.json"
            )

        try:
            from utils.json_safe_io import safe_load_json, safe_save_json
            from filelock import Timeout
        except (ImportError, ModuleNotFoundError) as e:
            logger.warning(f"json_safe_ioモジュールのインポートに失敗しました（非致命的）: {e}", exc_info=True)
            return

        try:
            evo_log = safe_load_json(evo_path) or {}

            # §12.3: appendのみ — 既存entriesは非破壊
            evo_log.setdefault("entries", []).append({
                "type": "storage_cleanup",
                "timestamp": datetime.now().isoformat(),
                "deleted_count": len(cleanup_result.get("deleted", [])),
                "freed_mb": round(
                    cleanup_result.get("freed_bytes", 0) / (1024 * 1024), 2
                ),
                "protected_count": len(cleanup_result.get("protected", [])),
                "dry_run": cleanup_result.get("dry_run", False),
                "summary": (
                    f"Auto cleanup: {len(cleanup_result.get('deleted', []))} files, "
                    f"{cleanup_result.get('freed_bytes', 0) / (1024*1024):.1f}MB freed"
                ),
            })

            safe_save_json(evo_path, evo_log)
            logger.info(
                f"📝 [cleanup→evolution_log] "
                f"deleted={len(cleanup_result.get('deleted', []))}, "
                f"freed={cleanup_result.get('freed_bytes', 0) / (1024*1024):.1f}MB"
            )
        except Timeout as e:
            logger.warning(f"evolution_log記録失敗 (Timeout): {e}", exc_info=True)
        except OSError as e:
            logger.warning(f"evolution_logのI/O処理に失敗しました（非致命的）: {e}", exc_info=True)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning(f"evolution_logのデータ構造または形式が無効です: {e}", exc_info=True)
        except (AttributeError, RuntimeError, KeyError, IndexError) as e:
            logger.error(f"evolution_log記録失敗 (unexpected): {e}", exc_info=True)
        except Exception as e:
            logger.warning(f"evolution_log記録失敗 (unexpected): {e}", exc_info=True)


# シングルトンインスタンス
cleanup_manager = CleanupManager()
