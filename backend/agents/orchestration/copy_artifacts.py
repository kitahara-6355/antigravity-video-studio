import shutil
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from backend.path_resolver import brain_dir, project_root

# 会話 UUID は当時のもの。親（brain/）とコピー先（プロジェクトルート）を
# 解決に通してあるので、ユーザー名やリポジトリ名が違うマシンでも壊れない。
_WORKTREES = brain_dir() / "129a8bf8-e9c8-40c2-bb9c-e7f79fcc4096" / ".system_generated" / "worktrees"

dest_base = str(project_root())

# 1. ec3af3f3-d7b8-492c-90e3-ad5fa6c8231f
src_ec = str(_WORKTREES / "subagent-comprehensive-preview-py----self-41da65a2")
shutil.copy2(os.path.join(src_ec, "backend", "comprehensive_preview.py"), os.path.join(dest_base, "backend", "comprehensive_preview.py"))
shutil.copy2(os.path.join(src_ec, "backend", "tests", "test_comprehensive_preview_thumbnail.py"), os.path.join(dest_base, "backend", "tests", "test_comprehensive_preview_thumbnail.py"))

# 2. fe90b0f5-b5ec-4295-870f-81e04169f897
src_fe = str(_WORKTREES / "subagent-services-thumbnail-analyzer-py--------self-7eb920b0")
shutil.copy2(os.path.join(src_fe, "backend", "services", "thumbnail_analyzer.py"), os.path.join(dest_base, "backend", "services", "thumbnail_analyzer.py"))

# test_thumbnail_analyzer.py
t_src = os.path.join(src_fe, "backend", "tests", "test_thumbnail_analyzer.py")
if not os.path.exists(t_src):
    t_src = os.path.join(src_fe, "tests", "test_thumbnail_analyzer.py")
shutil.copy2(t_src, os.path.join(dest_base, "backend", "tests", "test_thumbnail_analyzer.py"))

# 3. TDRファイル（fe90b0f5の方をコピー）
shutil.copy2(os.path.join(src_fe, "backend", "agents", "memory", "technical_debt_index.json"), os.path.join(dest_base, "backend", "agents", "memory", "technical_debt_index.json"))
shutil.copy2(os.path.join(src_fe, "backend", "TECHNICAL_DEBT_REGISTRY.md"), os.path.join(dest_base, "backend", "TECHNICAL_DEBT_REGISTRY.md"))

print("ALL_COPIED_SUCCESSFULLY")
