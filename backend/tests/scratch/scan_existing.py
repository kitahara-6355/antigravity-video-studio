import os
import re
import sys

def list_target_files(dir_path: str) -> list[str]:
    """E2Eテストファイルのリストを取得する。"""
    try:
        return [f for f in os.listdir(dir_path) if f.startswith("test_e2e_m36_") and f.endswith(".py")]
    except OSError as e:
        print(f"Failed to list directory {dir_path}: {e}", file=sys.stderr)
        raise

def extract_classes_from_file(file_path: str, label: str = "file") -> list[str]:
    """ファイルからTestE2Eで始まるクラス名を抽出する。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"Failed to read {label} {file_path}: {e}", file=sys.stderr)
        raise
    return re.findall(r"^class\s+(TestE2E\w+)", content, re.MULTILINE)

def scan_all_files(dir_path: str, files: list[str]) -> dict[str, list[str]]:
    """すべてのE2Eテストファイルからクラスを走査する。"""
    existing_classes = {}
    for file_name in files:
        full_path = os.path.join(dir_path, file_name)
        existing_classes[file_name] = extract_classes_from_file(full_path, "file")
    return existing_classes

def print_extracted_classes(existing_classes: dict[str, list[str]]) -> set[str]:
    """抽出されたクラス名を出力し、ユニークなセットを返す。"""
    all_existing_classes = set()
    for file_name, classes in existing_classes.items():
        print(f"{file_name}:")
        for cls in sorted(classes):
            print(f"  - {cls}")
            all_existing_classes.add(cls)
    return all_existing_classes

def print_missing_classes(orig_classes: list[str], all_existing_classes: set[str]) -> None:
    """抽出されていない未抽出クラスを出力する。"""
    print("\n--- NOT EXTRACTED CLASSES ---")
    for cls in orig_classes:
        if cls not in all_existing_classes:
            print(f"  - {cls}")

def run_scan() -> None:
    """スキャン全体のメインロジックを実行する。"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    dir_path = os.path.abspath(os.path.join(current_dir, "..", "e2e"))
    
    files = list_target_files(dir_path)
    existing_classes = scan_all_files(dir_path, files)
    all_existing_classes = print_extracted_classes(existing_classes)
    
    orig_path = os.path.abspath(os.path.join(dir_path, "archives", "test_e2e_browser_m36.py"))
    orig_classes = extract_classes_from_file(orig_path, "original file")
    
    print_missing_classes(orig_classes, all_existing_classes)

if __name__ == "__main__":  # pragma: no cover
    run_scan()
