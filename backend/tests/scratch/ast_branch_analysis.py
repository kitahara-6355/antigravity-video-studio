"""
AST Branch Analysis Script — Sprint 2.3.4
"""
import ast
import sys
from pathlib import Path

TARGET_FILES = [
    ("progressive_preview.py", "backend"),
    ("progressive_preview_report.py", "backend"),
    ("preview_system.py", "backend"),
    ("routers/preview.py", "backend"),
    ("services/preview_report_generator.py", "backend"),
]

class BranchCounter(ast.NodeVisitor):
    """AST Branch Counter"""
    
    def __init__(self):
        self.branches = []
        self.current_func = None
        self.current_class = None
        self.classes = []
        self.functions = []
        self._func_stack = []
    
    def visit_ClassDef(self, node):
        old_class = self.current_class
        self.current_class = node.name
        self.classes.append(node.name)
        self.generic_visit(node)
        self.current_class = old_class
    
    def visit_FunctionDef(self, node):
        parent_scope = self._func_stack[-1]["scope"] if self._func_stack else None
        if parent_scope:
            scope = f"{parent_scope}.{node.name}"
        elif self.current_class:
            scope = f"{self.current_class}.{node.name}"
        else:
            scope = node.name
            
        self.functions.append(scope)
        
        branch_info = {
            "scope": scope,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", "?"),
            "branch_count": 0,
        }
        self.branches.append(branch_info)
        self._func_stack.append(branch_info)
        
        self.generic_visit(node)
        self._func_stack.pop()
    
    visit_AsyncFunctionDef = visit_FunctionDef

    def _increment_branch(self, count=1):
        if self._func_stack:
            self._func_stack[-1]["branch_count"] += count

    def visit_If(self, node):
        self._increment_branch(1)
        self.generic_visit(node)

    def visit_For(self, node):
        self._increment_branch(1)
        self.generic_visit(node)

    def visit_While(self, node):
        self._increment_branch(1)
        self.generic_visit(node)

    def visit_Try(self, node):
        handlers_count = len(node.handlers) if hasattr(node, "handlers") else 0
        orelse_count = 1 if node.orelse else 0
        self._increment_branch(handlers_count + orelse_count)
        self.generic_visit(node)

    def visit_TryStar(self, node):
        handlers_count = len(node.handlers) if hasattr(node, "handlers") else 0
        orelse_count = 1 if node.orelse else 0
        self._increment_branch(handlers_count + orelse_count)
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self._increment_branch(1)
        self.generic_visit(node)

    def visit_IfExp(self, node):
        self._increment_branch(1)
        self.generic_visit(node)

def analyze_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()
    
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    
    lines = len(source.splitlines())
    total_branches = sum(b["branch_count"] for b in counter.branches)
    
    return {
        "lines": lines,
        "total_branches": total_branches,
        "classes": counter.classes,
        "functions": counter.functions,
        "branch_details": sorted(counter.branches, key=lambda x: -x["branch_count"]),
    }

def main(backend_dir=None, target_files=None):
    if backend_dir is None:
        backend_dir = Path(__file__).resolve().parent.parent.parent
    if target_files is None:
        target_files = TARGET_FILES
        
    print("=" * 80)
    print("Sprint 2.3.4 AST Branch Analysis")
    print("=" * 80)
    
    grand_total_branches = 0
    grand_total_lines = 0
    grand_total_classes = 0
    grand_total_funcs = 0
    
    for rel_path, base in target_files:
        filepath = backend_dir / rel_path
        if not filepath.exists():
            print()
            print(f"⚠️ Not found: {filepath}")
            continue
        
        try:
            result = analyze_file(filepath)
        except (SyntaxError, OSError, ValueError) as e:
            print()
            print(f"⚠️ Failed to analyze {rel_path}: {e}")
            continue

        grand_total_branches += result["total_branches"]
        grand_total_lines += result["lines"]
        grand_total_classes += len(result["classes"])
        grand_total_funcs += len(result["functions"])
        
        print()
        print(f"{'-' * 60}")
        print(f"📄 {rel_path}")
        print(f"   Lines: {result['lines']} | Branches: {result['total_branches']} | "
              f"Classes: {len(result['classes'])} | Functions: {len(result['functions'])}")
        print(f"   Classes: {result['classes']}")
        print()
        
        for b in result["branch_details"]:
            if b["branch_count"] > 0:
                print(f"   [{b['branch_count']:2d} branches] L{b['line']}-L{b['end_line']}  {b['scope']}")
            else:
                print(f"   [ 0 branches] L{b['line']}-L{b['end_line']}  {b['scope']}")
    
    print()
    print(f"{'=' * 80}")
    print(f"Total: {grand_total_lines} lines / {grand_total_branches} branches / "
          f"{grand_total_classes} classes / {grand_total_funcs} functions")
    print(f"{'=' * 80}")
    
    return {
        "lines": grand_total_lines,
        "branches": grand_total_branches,
        "classes": grand_total_classes,
        "functions": grand_total_funcs
    }


# ============================================================
# サムネイル生成・品質検証ロジック
# ============================================================
import logging
logger = logging.getLogger(__name__)

def generate_thumbnail(
    output_path,
    width: int = 1280,
    height: int = 720,
    text: str = "Thumbnail"
):
    """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
    from PIL import Image, ImageDraw
    import uuid
    from pathlib import Path
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        d = ImageDraw.Draw(img)
        d.text((10, 10), text, fill=(255, 255, 0))
        img.save(temp_path, "PNG")
        
        # 正常に保存されたらリネーム
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except (OSError, ValueError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        logger.error(f"Failed to generate thumbnail atomically: {e}")
        raise
        
    return output_path

def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    from PIL import Image
    from pathlib import Path
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    # 1. 簡易的なverify
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, ValueError, SyntaxError, RuntimeError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (OSError, ValueError, SyntaxError, RuntimeError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_thumbnail_task(agent, task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    import json
    from pathlib import Path
    output_dir = Path(getattr(agent, "output_dir", None) or "backend/temp_thumbnails")
    output_path = output_dir / f"{task_id}.png"
    
    width = getattr(agent, "width", 1280)
    height = getattr(agent, "height", 720)
    text = getattr(agent, "text", "Thumbnail")
    
    generate_thumbnail(output_path, width=width, height=height, text=text)
    result_info = validate_thumbnail(output_path)
    return json.dumps(result_info)

if __name__ == "__main__":
    main()
