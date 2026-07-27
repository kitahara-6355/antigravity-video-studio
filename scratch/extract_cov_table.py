import re

def main():
    path = "backend/coverage_branch_report.txt"
    try:
        with open(path, "r", encoding="utf-16") as f:
            content = f.read()
    except Exception:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"Failed to read: {e}")
            return

    # "Name" と "Stmts" または "Miss" または "Cover" が含まれる行からテーブルが始まる
    # pytest-cov のテーブルを抽出
    lines = content.splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        if "Name " in line and "Stmts " in line and "Cover" in line:
            in_table = True
        if in_table:
            table_lines.append(line)
            if "TOTAL " in line:
                in_table = False # TOTAL の行で終わり

    if table_lines:
        print("=== EXTRACTED COVERAGE TABLE ===")
        for tl in table_lines:
            print(tl)
    else:
        # テーブルが見つからなかった場合、"TOTAL" を探すなど
        print("Coverage table not found. Print last 100 lines instead:")
        for tl in lines[-100:]:
            print(tl)

if __name__ == "__main__":
    main()
