import json
import os
import argparse

DEFAULT_LOG_PATH = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\logs\transcript.jsonl"


def read_transcript_lines(log_path: str) -> list[str]:
    """トランスクリプトのログファイルからすべての行を読み込みます。"""
    if not log_path or not os.path.exists(log_path) or os.path.isdir(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def parse_transcript_line(line: str) -> dict:
    """1行のログデータをパースし、JSON形式で返します。"""
    data = json.loads(line)
    if not isinstance(data, dict):
        raise ValueError(f"Parsed JSON must be a dictionary, got {type(data).__name__}")
    return data


def format_transcript_data(data: dict) -> str:
    """パースされたログデータから出力用のテキストをフォーマットします。"""
    if not isinstance(data, dict):
        raise TypeError("Input data must be a dictionary")

    parts = []
    source = data.get("source")
    if source is None:
        source = "<missing>"
    type_ = data.get("type")
    if type_ is None:
        type_ = "<missing>"
    status = data.get("status")
    if status is None:
        status = "<missing>"
    parts.append(f"source={source} type={type_} status={status}")

    if "content" in data:
        content = data["content"]
        if not isinstance(content, str):
            content = str(content)
        parts.append(f"content: {content[:400]}")

    if "tool_calls" in data:
        tool_calls = data["tool_calls"]
        try:
            tool_calls_str = json.dumps(tool_calls)
        except (TypeError, ValueError, OverflowError, RecursionError):
            tool_calls_str = str(tool_calls)
        parts.append(f"tool_calls: {tool_calls_str[:400]}")

    return "\n".join(parts)


def print_transcript_range(log_path: str, start: int = 784, end: int = 796) -> None:
    """指定されたログファイル内の特定のインデックス範囲のログをパースして表示します。"""
    if start < 0 or end < 0:
        print("Error: Indices must be non-negative")
        return
    if start > end:
        print("Error: Start index must be less than or equal to end index")
        return

    if not log_path or not os.path.exists(log_path):
        print("Error: Log file not found")
        return
    if os.path.isdir(log_path):
        print("Error: Path is a directory")
        return

    lines = read_transcript_lines(log_path)
    if not lines:
        print("Warning: Log file is empty or could not be read")
        return

    if start >= len(lines):
        print(f"Warning: Start index {start} is out of bounds (total lines: {len(lines)})")
        return

    end_idx = min(len(lines), end)
    for i in range(start, end_idx):
        print(f"=== Line {i} ===")
        try:
            data = parse_transcript_line(lines[i])
            formatted = format_transcript_data(data)
            print(formatted)
        except json.JSONDecodeError as e:
            print(f"Error parsing line {i} as JSON: {e}")
        except TypeError as e:
            print(f"Type error on line {i}: {e}")
        except ValueError as e:
            print(f"Value error on line {i}: {e}")
        except (KeyError, AttributeError) as e:
            print(f"Unexpected error on line {i}: {e}")


def main() -> None:
    """メインのエントリーポイント。コマンドライン引数をパースして実行します。"""
    parser = argparse.ArgumentParser(
        description="Antigravity 会話ログ（transcript.jsonl）のデバッグツール"
    )
    parser.add_argument(
        "--path",
        type=str,
        default=DEFAULT_LOG_PATH,
        help="パース対象 of transcript.jsonl のパス",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=784,
        help="開始行インデックス (0ベース、デフォルト: 784)",
    )
    parser.add_argument(
        "--end",
        type=int,
        default=796,
        help="終了行インデックス (独占、デフォルト: 796)",
    )

    args = parser.parse_args()
    print_transcript_range(args.path, args.start, args.end)


if __name__ == "__main__":
    main()
