import re
from pathlib import Path

class PrefixMapper:
    """テストコードやクラスブロックから特定のプレフィックスを検出およびマッピングするクラス。"""

    def __init__(self, prefixes=None):
        if prefixes is None:
            self.prefixes = [
                "O1-", "O2-", "O3-", "O4-", "O5-", "O6-", "O7-", "O8-", "O9-", "O10-", "O11-", "O12-",
                "A1-", "A2-", "A3-", "A4-", "A5-", "A6-", "A7-", "A8-", "A9-"
            ]
        else:
            self.prefixes = prefixes

    def parse_class_blocks(self, content):
        """Pythonのソースコードテキストからクラスごとのブロックを抽出する。"""
        class_blocks = []
        current_class = None
        current_block = []

        for line in content.splitlines():
            class_match = re.match(r"^class\s+(\w+)", line)
            if class_match:
                if current_class:
                    class_blocks.append((current_class, "\n".join(current_block)))
                current_class = class_match.group(1)
                current_block = [line]
            else:
                if current_class:
                    if self._is_block_end(line):
                        class_blocks.append((current_class, "\n".join(current_block)))
                        current_class = None
                        current_block = []
                    else:
                        current_block.append(line)
                        
        if current_class:
            class_blocks.append((current_class, "\n".join(current_block)))
        return class_blocks

    def parse_classes(self, content):
        """非推奨エイリアス（後方互換性用）。"""
        return self.parse_class_blocks(content)

    def _is_block_end(self, line):
        """現在の行がクラスブロックの終端（インデントがなく、空行やコメントでもない行）であるかを判定する。"""
        stripped = line.strip()
        is_empty_or_comment = (stripped == "" or stripped.startswith("#"))
        is_indented = line.startswith(" ") or line.startswith("\t")
        return not is_indented and not is_empty_or_comment

    def find_prefixes(self, block):
        """ブロックテキスト内に定義されているプレフィックス（またはハイフンをアンダースコアに置換したもの）を探索する。"""
        found_prefixes = []
        for prefix in self.prefixes:
            underscore_prefix = prefix.replace("-", "_")
            if prefix in block or underscore_prefix in block:
                found_prefixes.append(prefix)
        return found_prefixes

    def find_hints(self, block):
        """ブロックテキスト内から、プレフィックスのハイフンを除去したキーワード（ヒント）を境界付き正規表現で探索する。"""
        hints = []
        for prefix in self.prefixes:
            clean_prefix = prefix.replace("-", "")
            escaped_prefix = re.escape(clean_prefix)
            
            pattern = self._build_hint_pattern(clean_prefix, escaped_prefix)
            if re.search(pattern, block):
                hints.append(clean_prefix)
        return hints

    def _build_hint_pattern(self, clean_prefix, escaped_prefix):
        """ヒント検出用の境界付き正規表現パターンを構築する。"""
        pattern = r'\b' + escaped_prefix if re.match(r'^\w', clean_prefix) else escaped_prefix
        pattern = pattern + r'\b' if re.search(r'\w$', clean_prefix) else pattern
        return pattern

def scan_file(filepath, prefixes=None):
    """ファイルを読み込み、クラスごとのプレフィックスおよびヒントのマッピング結果を返す。"""
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {filepath}")

    mapper = PrefixMapper(prefixes)
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    class_blocks = mapper.parse_class_blocks(content)
    class_scan_results = {}
    for name, block in class_blocks:
        found_prefixes = mapper.find_prefixes(block)
        if found_prefixes:
            class_scan_results[name] = {
                "prefixes": found_prefixes,
                "hints": []
            }
        else:
            hints = mapper.find_hints(block)
            class_scan_results[name] = {
                "prefixes": [],
                "hints": hints
            }
    return class_scan_results

