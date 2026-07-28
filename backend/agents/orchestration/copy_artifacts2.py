import shutil
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.path_resolver import brain_dir, project_root


def copy_artifacts(src_base=None, dest_base=None) -> bool:
    """
    成果物ファイルをコピーする。
    """
    if src_base is None:
        # 会話 UUID は当時のもの。親（brain/）を解決に通しておく。
        default_src = (
            brain_dir()
            / "129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096"
            / ".system_generated"
            / "worktrees"
            / "subagent-pipeline-tools-py------self-6be1122a"
        )
        src_base = os.environ.get("SRC_BASE", str(default_src))
    if dest_base is None:
        dest_base = os.environ.get("DEST_BASE", str(project_root()))

    success = True
    
    # コピーするファイルの定義
    # (src_rel, dest_rel, try_alternative_src)
    files_to_copy = [
        ("backend/tests/test_shared/test_pipeline_coordinator.py", "backend/tests/test_shared/test_pipeline_coordinator.py", False),
        ("backend/tests/test_shared/test_pipeline_coordinator_coverage.py", "backend/tests/test_shared/test_pipeline_coordinator_coverage.py", False),
        ("backend/tests/test_pipeline_tools.py", "backend/tests/test_pipeline_tools.py", True)
    ]

    for src_rel, dest_rel, has_alt in files_to_copy:
        # OS固有のセパレータに対応
        src_parts = src_rel.replace("\\", "/").split("/")
        dest_parts = dest_rel.replace("\\", "/").split("/")
        src_path = os.path.join(src_base, *src_parts)
        dest_path = os.path.join(dest_base, *dest_parts)
        
        if has_alt and not os.path.exists(src_path):
            src_path = os.path.join(src_base, "tests", "test_pipeline_tools.py")
            
        try:
            # コピー先の親ディレクトリが存在することを確認する（必要なら作成）
            dest_dir = os.path.dirname(dest_path)
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                
            shutil.copy2(src_path, dest_path)
            print(f"Copied: {src_path} -> {dest_path}")
        except FileNotFoundError as e:
            print(f"Warning: File not found during copy: {e}", file=sys.stderr)
            success = False
        except PermissionError as e:
            print(f"Warning: Permission denied during copy: {e}", file=sys.stderr)
            success = False
        except (OSError, TypeError, ValueError) as e:
            print(f"Error occurred during copy: {e}", file=sys.stderr)
            success = False
            
    if success:
        print("COPIED")
    else:
        print("COPY FAILED")
        
    return success

if __name__ == "__main__":
    copy_artifacts()
