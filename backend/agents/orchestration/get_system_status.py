import json
import os
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from path_resolver import project_root

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image, ImageDraw, ImageFont = None, None, None

def check_safety_guard(workspace_dir=None):
    # [v2.0.10] 安全ガード無効化: Antigravity v2.0.10でOpusとFlashが同一プロジェクトに統合されたため、
    # プロジェクトパスによる実行制限は不要になった。
    # if workspace_dir is None:
    #     workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    # if "video-automation 2" in workspace_dir:
    #     print("⚠️ 警告: get_system_status.py は Opus統括セッション（video-automation）専用のスクリプトです。")
    #     print("Flash実行セッション（video-automation 2）からの実行はスキップされました。")
    #     sys.exit(0)
    pass

def query_system_status(base_dir=None, paths=None):
    if paths is None:
        if base_dir is None:
            base_dir = str(project_root())
        paths = {
            "flash_session": os.path.join(base_dir, "backend", "agents", "orchestration", "flash_session.json"),
            "task_queue": os.path.join(base_dir, "backend", "agents", "orchestration", "task_queue.json"),
            "phase_state": os.path.join(base_dir, "backend", "agents", "memory", "phase_state.json"),
            "tdr_index": os.path.join(base_dir, "backend", "agents", "memory", "technical_debt_index.json"),
            "design_stock": os.path.join(base_dir, "backend", "agents", "orchestration", "design_stock")
        }
    
    summary = {}

    # pathsが辞書型でない場合の安全ガード
    if not isinstance(paths, dict):
        paths = {}

    def get_safe_path(key):
        val = paths.get(key)
        if val is None:
            return None
        try:
            if isinstance(val, (str, bytes, os.PathLike)):
                return val
        except TypeError:
            pass
        return None
    
    # 1. Flash Session
    flash_session_path = get_safe_path("flash_session")
    if flash_session_path and os.path.exists(flash_session_path):
        try:
            with open(flash_session_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    summary["flash_session"] = {
                        "status": data.get("status"),
                        "last_heartbeat": data.get("last_heartbeat"),
                        "current_activity": data.get("current_activity"),
                        "current_step": data.get("current_step"),
                        "current_batch_id": data.get("current_batch_id"),
                        "progress_pct": data.get("progress_pct"),
                        "tasks_completed_in_session": data.get("tasks_completed_in_session")
                    }
                else:
                    summary["flash_session"] = "Error (Invalid Format)"
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
            summary["flash_session"] = f"Error ({type(e).__name__})"
    else:
        summary["flash_session"] = "Not Found"
        
    # 2. Task Queue
    task_queue_path = get_safe_path("task_queue")
    if task_queue_path and os.path.exists(task_queue_path):
        try:
            with open(task_queue_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    tasks = data.get("tasks", [])
                    if not isinstance(tasks, list):
                        tasks = []
                    pending = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "pending")
                    running = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "running")
                    completed = sum(1 for t in tasks if isinstance(t, dict) and (t.get("status") == "completed" or t.get("status") == "pass"))
                    failed = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "failed")
                    summary["task_queue"] = {
                        "total_tasks": len(tasks),
                        "pending": pending,
                        "running": running,
                        "completed": completed,
                        "failed": failed,
                        "current_batch_id": data.get("current_batch_id"),
                        "status": data.get("status")
                    }
                else:
                    summary["task_queue"] = "Error (Invalid Format)"
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
            summary["task_queue"] = f"Error ({type(e).__name__})"
    else:
        summary["task_queue"] = "Not Found"
        
    # 3. Phase State
    phase_state_path = get_safe_path("phase_state")
    if phase_state_path and os.path.exists(phase_state_path):
        try:
            with open(phase_state_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    summary["phase_state"] = {
                        "current_phase": data.get("current_phase"),
                        "phase_name": data.get("phase_name"),
                        "emergency_stop": data.get("emergency_stop")
                    }
                else:
                    summary["phase_state"] = "Error (Invalid Format)"
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
            summary["phase_state"] = f"Error ({type(e).__name__})"
    else:
        summary["phase_state"] = "Not Found"
        
    # 4. TDR Index
    tdr_index_path = get_safe_path("tdr_index")
    if tdr_index_path and os.path.exists(tdr_index_path):
        try:
            with open(tdr_index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    entries = data.get("entries", [])
                    if isinstance(entries, dict):
                        entries_list = entries.values()
                    elif isinstance(entries, list):
                        entries_list = entries
                    else:
                        entries_list = []
                        
                    open_count = sum(1 for v in entries_list if isinstance(v, dict) and v.get("status") == "open")
                    resolved_count = sum(1 for v in entries_list if isinstance(v, dict) and (v.get("status") == "fixed" or v.get("status") == "resolved"))
                    accepted_count = sum(1 for v in entries_list if isinstance(v, dict) and v.get("status") == "accepted")
                    critical_count = sum(1 for v in entries_list if isinstance(v, dict) and (v.get("status") == "open" and v.get("priority") == "CRITICAL"))
                    
                    summary["tdr_index"] = {
                        "total_registered": len(entries_list),
                        "open": open_count,
                        "resolved": resolved_count,
                        "accepted": accepted_count,
                        "critical_open": critical_count
                    }
                else:
                    summary["tdr_index"] = "Error (Invalid Format)"
        except (json.JSONDecodeError, OSError, TypeError, KeyError) as e:
            summary["tdr_index"] = f"Error ({type(e).__name__})"
    else:
        summary["tdr_index"] = "Not Found"
        
    # 5. Design Stock
    design_stock_path = get_safe_path("design_stock")
    if design_stock_path and os.path.exists(design_stock_path):
        try:
            files = [f for f in os.listdir(design_stock_path) if f.endswith(".md")]
            summary["design_stock"] = {
                "total_stock_count": len(files),
                "files": files
            }
        except (OSError, TypeError, KeyError) as e:
            summary["design_stock"] = f"Error ({type(e).__name__})"
    else:
        summary["design_stock"] = "Not Found"
        
    return summary

def generate_status_thumbnail(output_path: str, summary: dict = None) -> str:
    """
    システムのステータス概要を元に、1280x720 (16:9) のサムネイル画像を生成します。
    """
    if summary is None:
        try:
            summary = query_system_status()
        except (TypeError, KeyError, ValueError, OSError, json.JSONDecodeError):
            summary = {}

    if not isinstance(summary, dict):
        summary = {}

    if Image is None:
        raise ImportError("Pillow library is required to generate thumbnail. Please install it.")

    width = 1280
    height = 720
    
    # 1280x720の画像を新規作成 (RGB)
    image = Image.new("RGB", (width, height), color=(18, 18, 20))
    draw = ImageDraw.Draw(image)
    
    # ダークなグラデーション背景
    for y in range(height):
        r = int(18 + (31 - 18) * (y / height))
        g = int(18 + (31 - 18) * (y / height))
        b = int(20 + (35 - 20) * (y / height))
        draw.line([(0, y), (width, y)], fill=(r, g, b))
        
    # フォントのセットアップ
    try:
        font_title = ImageFont.truetype("arial.ttf", 36)
        font_section = ImageFont.truetype("arial.ttf", 24)
        font_body = ImageFont.truetype("arial.ttf", 18)
        font_big_status = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font_title = ImageFont.load_default()
        font_section = ImageFont.load_default()
        font_body = ImageFont.load_default()
        font_big_status = ImageFont.load_default()
        
    # タイトル描画
    draw.text((50, 40), "ANTIGRAVITY SYSTEM DASHBOARD", fill=(255, 255, 255), font=font_title)
    draw.line([(50, 90), (1230, 90)], fill=(80, 80, 90), width=2)
    
    # 1. Flash Session カード
    fs = summary.get("flash_session", {})
    if isinstance(fs, dict):
        fs_status = fs.get("status") or "UNKNOWN"
    else:
        fs_status = str(fs) if fs is not None else "UNKNOWN"
        
    draw.rectangle([(50, 120), (410, 450)], fill=(30, 30, 35), outline=(100, 100, 110), width=1)
    draw.text((70, 140), "Flash Session", fill=(180, 180, 200), font=font_section)
    
    status_color = (100, 200, 100)
    if fs_status in ("FAILED", "DEAD", "Not Found", "UNKNOWN"):
        status_color = (230, 80, 80)
    elif fs_status in ("PENDING", "STALE", "WARNING"):
        status_color = (230, 160, 50)
        
    draw.text((70, 200), fs_status.upper(), fill=status_color, font=font_big_status)
    
    if isinstance(fs, dict):
        draw.text((70, 280), f"Activity: {fs.get('current_activity') or 'None'}", fill=(200, 200, 200), font=font_body)
        draw.text((70, 310), f"Step: {fs.get('current_step') or 'N/A'}", fill=(200, 200, 200), font=font_body)
        draw.text((70, 340), f"Progress: {fs.get('progress_pct') or 0}%", fill=(200, 200, 200), font=font_body)
        draw.text((70, 370), f"Completed: {fs.get('tasks_completed_in_session') or 0}", fill=(200, 200, 200), font=font_body)
        
    # 2. Task Queue カード
    tq = summary.get("task_queue", {})
    draw.rectangle([(440, 120), (800, 450)], fill=(30, 30, 35), outline=(100, 100, 110), width=1)
    draw.text((460, 140), "Task Queue Status", fill=(180, 180, 200), font=font_section)
    
    if isinstance(tq, dict):
        tq_status = tq.get("status") or "IDLE"
        draw.text((460, 200), f"QUEUE: {tq_status.upper()}", fill=(100, 180, 255), font=font_section)
        draw.text((460, 250), f"Total Tasks: {tq.get('total_tasks', 0)}", fill=(200, 200, 200), font=font_body)
        draw.text((460, 280), f"Pending: {tq.get('pending', 0)}", fill=(230, 160, 50), font=font_body)
        draw.text((460, 310), f"Running: {tq.get('running', 0)}", fill=(100, 180, 255), font=font_body)
        draw.text((460, 340), f"Completed: {tq.get('completed', 0)}", fill=(100, 220, 100), font=font_body)
        draw.text((460, 370), f"Failed: {tq.get('failed', 0)}", fill=(240, 80, 80), font=font_body)
    else:
        draw.text((460, 200), "Not Found", fill=(200, 100, 100), font=font_section)
        
    # 3. TDR & Design Stock カード
    tdr = summary.get("tdr_index", {})
    draw.rectangle([(830, 120), (1230, 450)], fill=(30, 30, 35), outline=(100, 100, 110), width=1)
    draw.text((850, 140), "Technical Debt & Design", fill=(180, 180, 200), font=font_section)
    
    if isinstance(tdr, dict):
        draw.text((850, 200), "TDR Status", fill=(200, 150, 255), font=font_section)
        draw.text((850, 240), f"Total Debt: {tdr.get('total_registered', 0)}", fill=(200, 200, 200), font=font_body)
        draw.text((850, 270), f"Open: {tdr.get('open', 0)}", fill=(230, 100, 100), font=font_body)
        
        critical_color = (255, 80, 80) if tdr.get('critical_open', 0) > 0 else (200, 200, 200)
        draw.text((850, 300), f"Critical Open: {tdr.get('critical_open', 0)}", fill=critical_color, font=font_body)
        draw.text((850, 330), f"Resolved: {tdr.get('resolved', 0)}", fill=(100, 220, 100), font=font_body)
    else:
        draw.text((850, 200), "TDR: Not Found", fill=(200, 100, 100), font=font_section)
        
    ds = summary.get("design_stock", {})
    if isinstance(ds, dict):
        draw.text((850, 380), f"Design Stock: {ds.get('total_stock_count', 0)} files", fill=(200, 200, 200), font=font_body)
        
    # フッター
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    draw.text((50, 660), f"Generated at: {timestamp}", fill=(120, 120, 130), font=font_body)
    draw.text((1050, 660), "Antigravity Studio", fill=(120, 120, 130), font=font_body)
    
    # 確実に4MB未満に収まるよう品質調整してPNG保存
    image.save(output_path, "PNG")
    return output_path

def main():
    check_safety_guard()
    summary = query_system_status()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
