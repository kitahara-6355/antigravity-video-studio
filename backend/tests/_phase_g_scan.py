"""Phase G: Tier 0-1 修正対象の精密スキャン"""
import re, ast
from pathlib import Path

backend = Path(__file__).resolve().parent.parent

# ===== N系列: except:pass スキャン =====
print("=" * 60)
print("N系列: except:pass 残存スキャン")
print("=" * 60)

# FF-5 対象外(周辺モジュール)を含む全ファイルスキャン
exclude_dirs = {"_deprecated", "__pycache__", ".git", "node_modules", "archives"}
n_total = 0
n_files = []

for p in sorted(backend.rglob("*.py")):
    if any(d in str(p) for d in exclude_dirs):
        continue
    if "test_" in p.name or p.name.startswith("_"):
        continue
    try:
        src = p.read_text(encoding="utf-8")
        # except ... : pass パターン検出
        matches = list(re.finditer(
            r"(except\s*(?:[\w\s,()]+)?:\s*\n\s+pass\s*$)", src, re.MULTILINE
        ))
        if matches:
            rel = str(p.relative_to(backend))
            n_total += len(matches)
            n_files.append((rel, len(matches)))
            for m in matches:
                line_no = src[:m.start()].count("\n") + 1
                print(f"  {rel}:{line_no}: {m.group(0).strip()}")
    except (OSError, UnicodeDecodeError) as e:
        print(f"Warning: Failed to scan {p} for N-series: {e}")

print(f"\nN系列合計: {n_total}件 ({len(n_files)}ファイル)")

# ===== M系列: print() スキャン =====
print("\n" + "=" * 60)
print("M系列: print() 残存スキャン (テスト除外)")
print("=" * 60)

m_total = 0
m_files = []

for p in sorted(backend.rglob("*.py")):
    if any(d in str(p) for d in exclude_dirs):
        continue
    if "test_" in p.name or p.name.startswith("_"):
        continue
    try:
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        
        # __main__ ブロックの範囲を特定
        main_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                try:
                    if (isinstance(node.test, ast.Compare) and 
                        isinstance(node.test.left, ast.Name) and 
                        node.test.left.id == "__name__"):
                        main_ranges.append(
                            (node.lineno, node.end_lineno or node.lineno + 200)
                        )
                except AttributeError:
                    pass
        
        prints = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and 
                isinstance(node.func, ast.Name) and 
                node.func.id == "print"):
                if not any(s <= node.lineno <= e for s, e in main_ranges):
                    prints.append(node.lineno)
        
        if prints:
            rel = str(p.relative_to(backend))
            m_total += len(prints)
            m_files.append((rel, len(prints)))
            if len(prints) <= 5:
                for ln in prints:
                    lines = src.split("\n")
                    if ln - 1 < len(lines):
                        print(f"  {rel}:{ln}: {lines[ln-1].strip()[:80]}")
            else:
                print(f"  {rel}: {len(prints)}箇所")
    except (OSError, SyntaxError, ValueError) as e:
        print(f"Warning: Failed to scan {p} for M-series: {e}")

print(f"\nM系列合計: {m_total}件 ({len(m_files)}ファイル)")

# ===== その他 Tier 0-1 =====
print("\n" + "=" * 60)
print("その他 Tier 0-1 個別チェック")
print("=" * 60)

# E-05: vault-assets
try:
    router = (backend / "routers/pipeline_router.py").read_text(encoding="utf-8")
    if "vault-assets" in router:
        line = [i+1 for i, l in enumerate(router.split("\n")) if "vault-assets" in l]
        print(f"E-05 vault-assets ハードコード: 残存 (L{line})")
    else:
        print("E-05 vault-assets: 解決済み")
except OSError as e:
    print(f"Warning: Failed to check E-05 (vault-assets): {e}")

# F-03: AIRuleCheck
try:
    qg = (backend / "quality_gate_plugins.py").read_text(encoding="utf-8")
    if re.search(r"except\s*\(ImportError.*?Exception\).*?pass", qg, re.DOTALL):
        print("F-03 AIRuleCheck exception握潰し: 残存")
    elif "except" in qg and "pass" in qg:
        # 別形式チェック
        matches = re.findall(r"except.*?:\s*\n\s+pass", qg)
        if matches:
            print(f"F-03 AIRuleCheck: except:pass {len(matches)}件残存")
except OSError as e:
    print(f"Warning: Failed to check F-03 (AIRuleCheck): {e}")

# G-01: GovernanceScope SmartCut
try:
    gov = (backend / "harness/governance.py").read_text(encoding="utf-8")
    if "smartcut" in gov.lower() or "smart_cut" in gov.lower():
        print("G-01 GovernanceScope SmartCut: 解決済み")
    else:
        print("G-01 GovernanceScope SmartCut: 未追加")
except OSError as e:
    print(f"Warning: Failed to check G-01 (GovernanceScope SmartCut): {e}")

# H-01: duck_amount
try:
    am = (backend / "audio_master.py").read_text(encoding="utf-8")
    if "duck_amount" in am:
        # FFmpegコマンド内で使用されているかチェック
        duck_fn_start = am.find("def duck_bgm")
        if duck_fn_start >= 0:
            duck_fn = am[duck_fn_start:am.find("\n    def ", duck_fn_start + 1)]
            if "duck_amount" in duck_fn.split("sidechaincompress")[0] if "sidechaincompress" in duck_fn else True:
                print("H-01 duck_amount: 引数定義あるがFFmpegに未反映")
    # H-03: AudioMaster template
    if "template_config" not in am:
        print("H-03 AudioMaster template連携: 未連携")
except OSError as e:
    print(f"Warning: Failed to check H-01/H-03 (AudioMaster): {e}")

# I-01: /api/pipeline/report
print("\nI-01 /api/pipeline/report 404:")
try:
    fe_src = (backend.parent / "frontend/src/components/ProductionPipeline.jsx").read_text(encoding="utf-8")
    if "pipeline/report" in fe_src:
        line = [i+1 for i, l in enumerate(fe_src.split("\n")) if "pipeline/report" in l]
        print(f"  フロントエンドにリンク残存 (L{line})")
except OSError as e:
    print(f"Warning: Failed to check I-01 (frontend link): {e}")


# ===== サムネイル品質検証ロジック (Phase 27) =====
def run_thumbnail_quality_check(image_path: Path) -> dict:
    """
    サムネイルの品質基準を検証するロジック (改善版)
    """
    from PIL import Image
    if not image_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {image_path}")
    
    size_bytes = image_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
        
    try:
        with Image.open(image_path) as img:
            img.verify()
        with Image.open(image_path) as img:
            img.load()
            w, h = img.size
    except (OSError, ValueError) as e:
        raise ValueError(f"Image is corrupted or invalid: {e}")
        
    if w < 1280 or h < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {w}x{h}")
        
    aspect_ratio = w / h
    if abs(aspect_ratio - (16.0 / 9.0)) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "status": "OK",
        "width": w,
        "height": h,
        "size_bytes": size_bytes
    }
