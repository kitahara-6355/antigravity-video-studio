"""
Model Guardian — モデルハードコード検出・防止チェッカー

PURPOSE:
  モデル名の直書きがコードベースに混入するのを防止する。
  起動時に全 .py ファイルをスキャンし、get_model() を経由せず
  直接モデル名をハードコードしている箇所を検出・警告する。

DESIGN:
  - 「定義」箇所（model_config.json, model_registry.py）は許容
  - 「使用」箇所での直書きのみ検出
  - deprecated モデルの参照は ERROR レベル
  - 現行モデルの直書きは WARNING レベル
  - アーカイブ・deprecated ファイルは除外

USAGE:
    from model_guardian import model_guardian
    issues = model_guardian.scan()  # 起動時に自動実行
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# スキャン対象のルートディレクトリ
BACKEND_DIR = Path(__file__).parent

# スキャン除外パス（正規表現）
EXCLUDE_PATTERNS = [
    r"_deprecated",
    r"archives",
    r"__pycache__",
    r"\.pyc$",
    r"model_config\.json",
    r"model_guardian\.py",      # 自身は除外
    r"test_model_guardian\.py",
    r"\.env",
    r"venv",
    r"node_modules",
]

# デフォルトフォールバック用非推奨モデル
DEFAULT_DEPRECATED_MODELS = [
    "gemini-2.0-flash-live-001",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-2.0-flash-exp",
]

# デフォルトフォールバック用現行モデル
DEFAULT_CURRENT_MODELS = [
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]

# 直書き許容パターン（これらの文脈では警告しない）
ALLOW_PATTERNS = [
    r"#.*gemini-",            # コメント内
    r"\"deprecated\"",         # deprecated セクション内
    r"\"removed\"",            # removed セクション内
    r"\"replacement\"",        # replacement 定義内
    r"fallback_chain",         # フォールバックチェーン定義
    r"def get_model",          # get_model 関数定義内
    r"from model_registry",    # model_registry インポート
    r"get_model\(",            # get_model() 呼び出し
    r"MODEL_NAME\s*=\s*get_model",  # get_model 経由の定義
]

# 定義ファイル（ここでのハードコードは許容）
DEFINITION_FILES = {
    "model_registry.py",
    "model_config.json",
    "sdk_checker.py",
}


class ModelGuardian:
    """モデルハードコード検出・防止チェッカー"""

    def __init__(self):
        self._issues: List[Dict] = []
        self._scanned_files = 0
        self._deprecated_models, self._current_models = self._load_models_from_config()

    def _load_models_from_config(self) -> Tuple[List[str], List[str]]:
        """model_config.json からモデルリストを動的に取得する"""
        config_path = BACKEND_DIR / "model_config.json"
        
        # フォールバック用初期値のコピー
        deprecated = list(DEFAULT_DEPRECATED_MODELS)
        current = list(DEFAULT_CURRENT_MODELS)
        
        if not config_path.exists():
            return sorted(deprecated), sorted(current)
            
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            cfg_deprecated = list(data.get("deprecated", {}).keys())
            cfg_removed = list(data.get("removed", {}).keys())
            
            deprecated_set = set(deprecated) | set(cfg_deprecated) | set(cfg_removed)
            
            current_set = set()
            for category in ["text_generation", "image_generation", "video_generation"]:
                cat_data = data.get(category, {})
                if "default_model" in cat_data:
                    current_set.add(cat_data["default_model"])
                tiers = cat_data.get("tiers", {})
                for tier_info in tiers.values():
                    if isinstance(tier_info, dict) and "model" in tier_info:
                        current_set.add(tier_info["model"])
                        
            current_set = current_set | set(current)
            # 非推奨モデルが現行リストに含まれていれば除外する
            current_set = current_set - deprecated_set
            
            return sorted(list(deprecated_set)), sorted(list(current_set))
        except (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"Failed to load model config in ModelGuardian: {e}")
            return sorted(deprecated), sorted(current)

    def scan(self, root: Optional[Path] = None) -> List[Dict]:
        """
        全 .py ファイルをスキャンしてモデル直書きを検出。

        Returns:
            [{"file": str, "line": int, "model": str, "severity": str, "content": str}, ...]
        """
        root = root or BACKEND_DIR
        self._issues = []
        self._scanned_files = 0

        for py_file in root.rglob("*.py"):
            # 除外パスチェック
            if self._is_excluded(py_file):
                continue

            # 定義ファイルは許容
            if py_file.name in DEFINITION_FILES:
                continue

            self._scan_file(py_file)
            self._scanned_files += 1

        if self._issues:
            errors = [i for i in self._issues if i["severity"] == "ERROR"]
            warns = [i for i in self._issues if i["severity"] == "WARNING"]
            if errors:
                logger.error(
                    f"🚨 ModelGuardian: {len(errors)} deprecated model references found!"
                )
                for e in errors:
                    logger.error(
                        f"  {e['file']}:{e['line']} — {e['model']} (deprecated)"
                    )
            if warns:
                logger.warning(
                    f"⚠️ ModelGuardian: {len(warns)} hardcoded model references. "
                    f"Use get_model(task) instead."
                )
                for w in warns:
                    logger.warning(
                        f"  {w['file']}:{w['line']} — {w['model']} (current)"
                    )
        else:
            logger.info(
                f"✅ ModelGuardian: {self._scanned_files} files scanned, "
                f"no hardcoded model references found."
            )

        return self._issues

    def _is_excluded(self, path: Path) -> bool:
        """除外パスかどうか"""
        path_str = str(path)
        return any(re.search(pat, path_str) for pat in EXCLUDE_PATTERNS)

    def _scan_file(self, path: Path) -> None:
        """1ファイルをスキャン"""
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (FileNotFoundError, PermissionError, OSError):
            return

        for line_no, line in enumerate(content.split("\n"), 1):
            # 空行・コメント行をスキップ
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # 許容パターンに該当する場合はスキップ
            if any(re.search(pat, line) for pat in ALLOW_PATTERNS):
                continue

            # deprecated モデルの検出（ERROR）
            for model in self._deprecated_models:
                if model in line:
                    self._issues.append({
                        "file": str(path.relative_to(BACKEND_DIR)),
                        "line": line_no,
                        "model": model,
                        "severity": "ERROR",
                        "content": stripped[:120],
                    })

            # 現行モデルの検出（WARNING）
            for model in self._current_models:
                if model in line:
                    self._issues.append({
                        "file": str(path.relative_to(BACKEND_DIR)),
                        "line": line_no,
                        "model": model,
                        "severity": "WARNING",
                        "content": stripped[:120],
                    })

    def get_summary(self) -> str:
        """結果サマリーを返す"""
        if not self._issues:
            return f"✅ ModelGuardian: {self._scanned_files} files clean"

        errors = len([i for i in self._issues if i["severity"] == "ERROR"])
        warns = len([i for i in self._issues if i["severity"] == "WARNING"])
        return (
            f"ModelGuardian: {errors} errors, {warns} warnings "
            f"in {self._scanned_files} files"
        )


# シングルトン
model_guardian = ModelGuardian()


# === 起動時自動実行 ===
def run_guardian_check() -> List[Dict]:
    """起動時チェック。main.py の startup から呼ばれる。"""
    return model_guardian.scan()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    issues = run_guardian_check()
    if issues:
        print(f"\n{'='*60}")
        print(f"⚠️ {len(issues)} issues found:")
        for i in issues:
            print(f"  [{i['severity']}] {i['file']}:{i['line']} — {i['model']}")
            print(f"         {i['content']}")
        print(f"{'='*60}")
