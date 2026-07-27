"""
エラー報告システム

推奨タスク P6.2: 未解決エラーを開発者に自動報告
推奨タスク P6.3: FAQ統合
※ Phase 33 バグ修正タスクに付随する変更対象モジュール
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
import os
import logging
import threading
import random
import time

logger = logging.getLogger(__name__)


@dataclass
class ErrorReport:
    """エラーレポート"""
    id: str
    error_type: str
    message: str
    stack_trace: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    resolved: bool = False
    resolution: str = ""

    def __post_init__(self):
        if not isinstance(self.id, str):
            raise TypeError("id must be a string")
        if not isinstance(self.error_type, str):
            raise TypeError("error_type must be a string")
        if not isinstance(self.message, str):
            raise TypeError("message must be a string")
        if not isinstance(self.stack_trace, str):
            raise TypeError("stack_trace must be a string")
        if not isinstance(self.context, dict):
            raise TypeError("context must be a dictionary")
        if not isinstance(self.timestamp, str):
            raise TypeError("timestamp must be a string")
        if not isinstance(self.resolved, bool):
            raise TypeError("resolved must be a boolean")
        if not isinstance(self.resolution, str):
            raise TypeError("resolution must be a string")


@dataclass
class FAQEntry:
    """FAQ エントリ"""
    id: str
    question: str
    answer: str
    keywords: List[str] = field(default_factory=list)
    error_patterns: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.id, str):
            raise TypeError("id must be a string")
        if not isinstance(self.question, str):
            raise TypeError("question must be a string")
        if not isinstance(self.answer, str):
            raise TypeError("answer must be a string")
        if not isinstance(self.keywords, list) or not all(isinstance(x, str) for x in self.keywords):
            raise TypeError("keywords must be a list of strings")
        if not isinstance(self.error_patterns, list) or not all(isinstance(x, str) for x in self.error_patterns):
            raise TypeError("error_patterns must be a list of strings")


class ErrorReportManager:
    """エラー報告管理"""
    
    def __init__(self, report_dir: str = None):
        self._lock = threading.RLock()
        # 空文字列や空白文字の場合もデフォルト値にフォールバック
        if not report_dir or not report_dir.strip():
            self.report_dir = os.path.join(
                os.path.dirname(__file__), "error_reports"
            )
        else:
            self.report_dir = report_dir
        self._reports: List[ErrorReport] = []
        self._loaded = True  # ロード成否フラグ
        self._load_reports()
    
    def _load_reports(self):
        """既存レポート読み込み"""
        with self._lock:
            report_file = os.path.join(self.report_dir, "reports.json")
        if os.path.exists(report_file):
            try:
                if os.path.getsize(report_file) == 0:
                    self._reports = []
                    self._loaded = True
                    return
            except OSError as e:
                logger.warning(f"Failed to check file size of {report_file}: {e}")
                self._loaded = False
                return

            try:
                with open(report_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    loaded_reports = []
                    if isinstance(data, list):
                        import inspect
                        sig = inspect.signature(ErrorReport)
                        valid_keys = set(sig.parameters.keys())
                        for r in data:
                            try:
                                if isinstance(r, dict):
                                    filtered_r = {k: v for k, v in r.items() if k in valid_keys}
                                    loaded_reports.append(ErrorReport(**filtered_r))
                                else:
                                    logger.warning(f"Skipping invalid report element (not dict): {r}")
                            except (TypeError, KeyError) as e:
                                logger.warning(f"Skipping corrupted report element: {e}")
                        self._reports = loaded_reports
                        self._loaded = True
                    else:
                        raise ValueError("Loaded reports JSON is not a list")
            except (json.JSONDecodeError, TypeError, KeyError, OSError, ValueError) as e:
                logger.warning(f"Failed to load reports: {e}. Moving corrupted file to backup.")
                self._loaded = False
                
                # 自動復旧: 破損したファイルをバックアップに退避
                backup_file = report_file + ".bak"
                try:
                    if os.path.exists(backup_file):
                        os.remove(backup_file)
                    os.rename(report_file, backup_file)
                    logger.info(f"Corrupted reports file backed up to {backup_file}")
                    self._reports = []
                    self._loaded = True
                    self._save_reports()
                except OSError as backup_error:
                    logger.error(f"Failed to auto-recover/backup corrupted reports file: {backup_error}")
                    self._loaded = False
    
    def _save_reports(self):
        """レポート保存"""
        with self._lock:
            if not self._loaded:
                raise RuntimeError("Cannot save reports because the initial load failed. This prevents data loss.")
            report_file = os.path.join(self.report_dir, "reports.json")
            # uuid を使わずに一意な一時ファイルを生成
            temp_name = f"reports.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{random.randint(0, 1000000)}.tmp"
            temp_file = os.path.join(self.report_dir, temp_name)
            try:
                os.makedirs(self.report_dir, exist_ok=True)
                with open(temp_file, 'w', encoding='utf-8') as f:
                    # default=str を用いることでJSONシリアライズ不能オブジェクトも安全に文字列化して保存
                    json.dump([vars(r) for r in self._reports], f, ensure_ascii=False, indent=2, default=str)
                os.replace(temp_file, report_file)
            except OSError as e:
                logger.error(f"Failed to save reports: {e}")
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except OSError:
                        pass
                raise
    
    def report_error(self, 
                     error_type: str,
                     message: str,
                     stack_trace: str = "",
                     context: Dict[str, Any] = None) -> str:
        """エラー報告"""
        if not error_type or not isinstance(error_type, str) or not error_type.strip():
            raise ValueError("error_type must be a non-empty string")
        if not message or not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if stack_trace is not None and not isinstance(stack_trace, str):
            raise TypeError("stack_trace must be a string")
        if context is not None and not isinstance(context, dict):
            raise TypeError("context must be a dictionary")

        with self._lock:
            import uuid
            report_id = None
            while True:
                candidate_id = str(uuid.uuid4())[:8]
                if not any(r.id == candidate_id for r in self._reports):
                    report_id = candidate_id
                    break

            report = ErrorReport(
                id=report_id,
                error_type=error_type,
                message=message,
                stack_trace=stack_trace or "",
                context=context or {}
            )
            self._reports.append(report)
            self._save_reports()
            logger.info(f"Error reported: {report.id}")
            return report.id
    
    def get_unresolved(self) -> List[ErrorReport]:
        """未解決エラー取得"""
        with self._lock:
            return [r for r in self._reports if not r.resolved]
    
    def resolve_error(self, report_id: str, resolution: str) -> bool:
        """エラー解決"""
        if not report_id or not isinstance(report_id, str) or not report_id.strip():
            return False
        if not resolution or not isinstance(resolution, str) or not resolution.strip():
            resolution = "Resolved"
        with self._lock:
            for report in self._reports:
                if report.id == report_id:
                    report.resolved = True
                    report.resolution = resolution
                    self._save_reports()
                    return True
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """統計"""
        with self._lock:
            total = len(self._reports)
            unresolved = len(self.get_unresolved())
            return {
                "total": total,
                "unresolved": unresolved,
                "resolved": total - unresolved,
                "by_type": self._count_by_type()
            }
    
    def _count_by_type(self) -> Dict[str, int]:
        from collections import Counter
        return dict(Counter(r.error_type for r in self._reports))


class FAQManager:
    """FAQ管理"""
    
    def __init__(self):
        self._faqs: List[FAQEntry] = []
        self._load_default_faqs()
    
    def _load_default_faqs(self):
        """デフォルトFAQ"""
        self._faqs = [
            FAQEntry(
                id="faq_1",
                question="バックエンドに接続できません",
                answer="1. resume_dev.ps1を実行してください\n2. ポート8000が使用中でないか確認してください\n3. ファイアウォール設定を確認してください",
                keywords=["接続", "connection", "refused"],
                error_patterns=["ECONNREFUSED", "Connection refused"]
            ),
            FAQEntry(
                id="faq_2",
                question="動画処理が途中で止まります",
                answer="1. メモリ使用量を確認してください\n2. 入力動画のフォーマットを確認してください\n3. GPUドライバを更新してください",
                keywords=["処理", "停止", "freeze"],
                error_patterns=["MemoryError", "CUDA out of memory"]
            ),
            FAQEntry(
                id="faq_3",
                question="AIの応答が遅いです",
                answer="1. ネットワーク接続を確認してください\n2. API利用制限に達していないか確認してください\n3. キャッシュを有効にしてください",
                keywords=["遅い", "slow", "timeout"],
                error_patterns=["timeout", "rate limit"]
            ),
        ]
    
    def search(self, query: str) -> List[FAQEntry]:
        """FAQ検索"""
        if not query or not isinstance(query, str) or not query.strip():
            return []
        
        results = []
        query_lower = query.lower()
        
        for faq in self._faqs:
            score = 0
            # keywords の安全な取り扱い
            keywords = faq.keywords if isinstance(faq.keywords, list) else []
            for kw in keywords:
                if kw and isinstance(kw, str) and kw.lower() in query_lower:
                    score += 2
            # 質問テキストマッチ
            if faq.question and isinstance(faq.question, str) and query_lower in faq.question.lower():
                score += 3
            # エラーパターンマッチ
            error_patterns = faq.error_patterns if isinstance(faq.error_patterns, list) else []
            for pattern in error_patterns:
                if pattern and isinstance(pattern, str) and pattern.lower() in query_lower:
                    score += 5
            
            if score > 0:
                results.append((score, faq))
        
        return [faq for _, faq in sorted(results, key=lambda x: -x[0])]
    
    def find_for_error(self, error_message: str) -> Optional[FAQEntry]:
        """エラーメッセージからFAQ検索"""
        if not error_message or not isinstance(error_message, str):
            return None
        results = self.search(error_message)
        return results[0] if results else None
    
    def add_faq(self, faq: FAQEntry):
        """FAQ追加"""
        if not isinstance(faq, FAQEntry):
            raise TypeError("faq must be an instance of FAQEntry")
        if not faq.question or not isinstance(faq.question, str) or not faq.question.strip():
            raise ValueError("faq.question must be a non-empty string")
        if not faq.answer or not isinstance(faq.answer, str) or not faq.answer.strip():
            raise ValueError("faq.answer must be a non-empty string")
        if faq.keywords is not None and not isinstance(faq.keywords, list):
            raise TypeError("faq.keywords must be a list")
        if faq.error_patterns is not None and not isinstance(faq.error_patterns, list):
            raise TypeError("faq.error_patterns must be a list")
        if any(existing.id == faq.id for existing in self._faqs):
            raise ValueError(f"FAQ with id '{faq.id}' already exists")
        self._faqs.append(faq)


# シングルトン
error_report_manager = ErrorReportManager()
faq_manager = FAQManager()


# FastAPI ルーター
from fastapi import APIRouter, HTTPException, Body

router = APIRouter(prefix="/api/support", tags=["Support"])


@router.post("/report")
async def report_error(
    error_type: str,
    message: str,
    stack_trace: str = "",
    context: Any = Body(None)
):
    """エラー報告"""
    try:
        report_id = error_report_manager.report_error(
            error_type, message, stack_trace, context
        )
        # 関連FAQを検索
        faq = faq_manager.find_for_error(message)
        return {
            "report_id": report_id,
            "related_faq": vars(faq) if faq else None
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:
        logger.error(f"Storage error in report_error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporary unavailable due to storage issue")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in report_error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/unresolved")
async def get_unresolved_errors():
    """未解決エラー取得"""
    try:
        return {"errors": [vars(e) for e in error_report_manager.get_unresolved()]}
    except OSError as e:
        logger.error(f"Storage error in get_unresolved_errors: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporary unavailable due to storage issue")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_unresolved_errors: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/resolve/{report_id}")
async def resolve_error(report_id: str, resolution: str = "Resolved"):
    """エラー解決"""
    if not report_id or not report_id.strip():
        raise HTTPException(status_code=400, detail="report_id cannot be empty")
    if not resolution or not resolution.strip():
        raise HTTPException(status_code=400, detail="resolution cannot be empty")
    
    try:
        success = error_report_manager.resolve_error(report_id, resolution)
        return {"success": success}
    except OSError as e:
        logger.error(f"Storage error in resolve_error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporary unavailable due to storage issue")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in resolve_error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/faq")
async def search_faq(query: str):
    """FAQ検索"""
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query cannot be empty")
    try:
        results = faq_manager.search(query)
        return {"results": [vars(f) for f in results]}
    except OSError as e:
        logger.error(f"Storage error in search_faq: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporary unavailable due to storage issue")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in search_faq: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_error_stats():
    """エラー統計"""
    try:
        return error_report_manager.get_stats()
    except OSError as e:
        logger.error(f"Storage error in get_error_stats: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Service temporary unavailable due to storage issue")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_error_stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
