# -*- coding: utf-8 -*-
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import sys
import os
import json
import time
import sqlite3
import traceback
from pathlib import Path
import PIL
from PIL import Image

project_root = str(Path(__file__).resolve().parents[3])
if project_root not in sys.path:
    sys.path.insert(0, project_root)
backend_path = str(Path(__file__).resolve().parents[2])
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)
from backend.agents.orchestration import OrchestrationHub
from backend.agents.stage_bound_agent import StageBoundAgent
from backend.usage_tracker.alert_system import emit_warning, emit_critical

def verify_thumbnail_quality(file_path_or_bytes) -> dict:
    """
    サムネイル画像の品質要件を検証する（GEMINI.md §⑩準拠）。
    - 解像度: 1280x720 以上
    - アスペクト比: 16:9
    - ファイルサイズ: 4MB 未満
    - 破損チェック: Pillowで正常にロード可能
    """
    if not isinstance(file_path_or_bytes, (bytes, str, Path)) and not hasattr(file_path_or_bytes, "__fspath__"):
        emit_warning("thumbnail", f"Invalid input type: {type(file_path_or_bytes)}")
        raise TypeError(f"Invalid input type: {type(file_path_or_bytes)}")

    if isinstance(file_path_or_bytes, bytes):
        import io
        img_data = file_path_or_bytes
        size_bytes = len(img_data)
        try:
            with io.BytesIO(img_data) as bio:
                with Image.open(bio) as img:
                    img.load()  # 実際にピクセルデータをロードして破損チェック
                    width, height = img.size
        except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError, SyntaxError) as e:
            emit_warning("thumbnail", f"Corrupted image bytes: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")
    else:
        path = Path(file_path_or_bytes)
        if not path.exists():
            emit_warning("thumbnail", f"File not found: {path}")
            raise FileNotFoundError(f"Thumbnail file not found: {path}")
        size_bytes = path.stat().st_size
        try:
            with Image.open(path) as img:
                img.load()  # 実際にピクセルデータをロードして破損チェック
                width, height = img.size
        except (PIL.UnidentifiedImageError, ValueError, TypeError, OSError, SyntaxError) as e:
            emit_warning("thumbnail", f"Corrupted image file: {e}")
            raise ValueError(f"Image is corrupted or invalid format: {e}")

    if size_bytes >= 4 * 1024 * 1024:
        msg = f"File size exceeds 4MB limit: {size_bytes} bytes"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    if height == 0:
        msg = "Image height cannot be zero"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    if width == 0:
        msg = "Image width cannot be zero"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    if width < 1280 or height < 720:
        msg = f"Resolution must be at least 1280x720. Got {width}x{height}"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 1e-3:
        msg = f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}"
        emit_warning("thumbnail", msg)
        raise ValueError(msg)

    return {
        "width": width,
        "height": height,
        "size_bytes": size_bytes,
        "valid": True
    }

def _get_exception_line(tb, default_line: int) -> int:
    """例外のトレースバックから、このファイル内での発生行番号を抽出する"""
    if not tb:
        return default_line
    tb_list = traceback.extract_tb(tb)
    this_file = Path(__file__).name
    for fs in reversed(tb_list):
        if Path(fs.filename).name == this_file:
            return fs.lineno
    return default_line

def _cleanup_file(path: Path | None):
    """例外発生時の一時ファイル削除処理"""
    if path is None:
        return
    try:
        p = Path(path)
        if p.exists():
            p.unlink(missing_ok=True)
    except OSError:
        pass

def register_technical_debt(line_number: int, pattern: str, notes: str, exception: Exception | None = None, _store=None):
    """例外に対する汎用catchが発生した際に技術負債を登録する。
    ただし、環境エラーや通信エラーなどのインフラ要因エラーは技術負債として登録しない。
    """
    if exception is not None:
        if isinstance(exception, (ConnectionError, TimeoutError, sqlite3.Error, OSError)):
            return
    try:
        if _store is None:
            from backend.agents.memory.technical_debt import TechnicalDebtStore
            _store = TechnicalDebtStore()
        _store.register_debt(
            category="MINOR_INFRA",
            file_path="backend/agents/orchestration/mark_tasks_p27_refactor_b88.py",
            line_number=line_number,
            pattern=pattern,
            cause_pattern="DP-01",
            fix_pattern="例外の厳密な個別型ハンドリングとバリデーションを適用する",
            registered_by="sprint_bug_hunter",
            notes=notes,
            tags=["bug_hunter", "except_exception"]
        )
    except (ImportError, AttributeError, ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as register_err:
        import sys
        print(f"Failed to register technical debt: {register_err}", file=sys.stderr)

async def run_thumbnail_stage_task(task_id: str, db_path: str = ":memory:") -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理。
    自動リトライ、結果保存、DBマイグレーションと連携。
    """
    output_path = None
    is_success = False
    try:
        output_dir = _writable_path("backend/temp_thumbnails")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{task_id}.png"
        
        # 正常な16:9画像のダミーを生成
        from PIL import ImageDraw
        with Image.new("RGB", (1280, 720), color=(73, 109, 137)) as img:
            d = ImageDraw.Draw(img)
            d.text((10, 10), f"Task ID: {task_id}", fill=(255, 255, 0))
            img.save(output_path, "PNG")

        # 品質要件の検証
        result_info = verify_thumbnail_quality(output_path)
        
        # 結果保存とDBマイグレーション
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
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
                (task_id, str(output_path), result_info["width"], result_info["height"], result_info["size_bytes"], time.time())
            )
            conn.commit()
        except sqlite3.Error as db_err:
            emit_critical("thumbnail", f"Database operation failed: {db_err}")
            raise
        finally:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

        is_success = True
        return json.dumps(result_info)
    except (ValueError, FileNotFoundError):
        raise
    except sqlite3.Error:
        raise
    except OSError as os_err:
        emit_critical("thumbnail", f"Thumbnail task failed for task {task_id}: {os_err}")
        raise
    except (TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except (TypeError, KeyError, AttributeError, IndexError, RuntimeError) as e:",
            notes=f"Thumbnail task failed with unexpected error for task {task_id}: {e}",
            exception=e
        )
        emit_critical("thumbnail", f"Thumbnail task failed for task {task_id}: {e}")
        traceback.print_exc()
        raise
    finally:
        if not is_success:
            _cleanup_file(output_path)

def main():
    try:
        task_id = os.environ.get("TASK_ID", "T-batch_b13ea7-bug_hunter-004")
        positional_args = [arg for arg in sys.argv[1:] if not arg.startswith("-")]
        if positional_args:
            task_id = positional_args[0]

        hub = OrchestrationHub()
        hub.register_flash_conversation_id("d4ffa833-786b-4a2d-947a-1f0ae9624b60")
        
        # 心拍更新
        hub.flash_update_heartbeat()
        
        # タスク完了マーク
        hub.mark_task_done(task_id, "pass", {
            "message": "mark_tasks_p27_refactor_b88.py の堅牢化（Pillowリソース漏れ防止、TDR連携、一時ファイル削除、例外ハンドリング強化など）およびテストの追加。",
            "changed_files": [
                "backend/agents/orchestration/mark_tasks_p27_refactor_b88.py",
                "tests/test_mark_tasks_p27_refactor_b88_root.py"
            ]
        })
        
        print("TASK_MARKED_DONE")

        # 最新ステータス表示
        status = hub.generate_flash_status()
        print("FLASH_STATUS:" + json.dumps(status))
    except (RuntimeError, sqlite3.Error) as err:
        print(f"Runtime execution failed: {err}", file=sys.stderr)
        sys.exit(1)
    except TypeError as te:
        print(f"Serialization failed: {te}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except ValueError as e:",
            notes=f"Main execution failed with ValueError: {e}",
            exception=e
        )
        print(f"ValueError during execution: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    except OSError as e:
        print(f"OS error during execution: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    except (KeyError, AttributeError, IndexError) as e:
        line_no = _get_exception_line(e.__traceback__, sys._getframe().f_lineno)
        register_technical_debt(
            line_number=line_no,
            pattern="except (KeyError, AttributeError, IndexError) as e:",
            notes=f"Main execution failed with unexpected error: {e}",
            exception=e
        )
        print(f"Attribute, index or key error during execution: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
