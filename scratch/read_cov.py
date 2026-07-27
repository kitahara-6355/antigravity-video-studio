import sys

def try_read(path):
    encodings = ["utf-8", "utf-16", "utf-16le", "cp932", "shift-jis"]
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc) as f:
                content = f.read()
                print(f"--- SUCCESS with {enc} for {path} ---")
                return content
        except Exception as e:
            continue
    print(f"--- FAILED to read {path} ---")
    return None

def main():
    paths = [
        "backend/coverage_branch_report.txt",
        "backend/_cov_batch_a_result.txt"
    ]
    for p in paths:
        content = try_read(p)
        if content:
            # 最初の20行と最後の20行を出力
            lines = content.splitlines()
            print(f"Total lines: {len(lines)}")
            for l in lines[:40]:
                print(l)
            print("...")
            for l in lines[-20:]:
                print(l)
            print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    main()
