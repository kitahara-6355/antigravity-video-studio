import json
import os
from pathlib import Path

# 対象となるサブエージェントIDのリスト
NEW_SUBAGENT_IDS = [
    "c0f1a051-25b0-4b90-908a-1fbec6c2e848",
    "62882ce0-f954-433e-ae67-d6cbf4f18cea",
    "000d1367-a11a-4932-b3fa-0a77ed368545",
    "2c56e554-35a2-447f-83a8-1824cf222e2e",
    "c9860a46-ba88-4583-9e1a-ab7d7ed29aba",
    "124c8d71-2d3e-4025-8b2b-5ec91dda4477"
]

def get_base_brain_dir() -> Path:
    """環境変数またはデフォルトのパスから brain ディレクトリへのパスを取得する"""
    app_data_dir_env = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
    if app_data_dir_env:
        return Path(app_data_dir_env) / "brain"
    return Path.home() / ".gemini" / "antigravity" / "brain"

def format_log_line(line: str) -> str | None:
    """ログの1行をパースし、指定されたフォーマットの文字列を返す。

    JSONDecodeErrorの場合はNoneを返し、その他の例外は呼び出し元へ伝播させる。
    """
    data = json.loads(line)
    content = data.get("content", "")
    summary = (content[:250] + "...") if len(content) > 250 else content
    return f"Step {data.get('step_index')} ({data.get('type')} / {data.get('source')}): {summary}"

def parse_and_print_log_line(subagent_id: str, line: str) -> None:
    """ログの1行をパースし、指定されたフォーマットで標準出力に出力する。

    （既存インターフェース互換性維持のため残し、内部実装をformat_log_lineに委譲）
    """
    try:
        formatted = format_log_line(line)
        if formatted is not None:
            print(formatted)
    except json.JSONDecodeError:
        # JSONのデコードエラー（不完全な行など）は無視する
        pass
    except Exception as e:
        # その他の例外は原因究明のために警告を出力
        print(f"[{subagent_id}] Error parsing line: {e}")

def read_last_log_lines(log_path: Path, count: int = 3) -> list[str]:
    """指定されたログファイルから末尾の行を取得する。"""
    with open(log_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return lines[-count:]

def process_subagent_log(subagent_id: str, base_brain_dir: Path) -> None:
    """単一のサブエージェントのログファイルを読み込んで処理する"""
    log_path = base_brain_dir / subagent_id / ".system_generated" / "logs" / "transcript.jsonl"
    if not log_path.exists():
        print(f"[{subagent_id}] Log does not exist.")
        return

    try:
        lines = read_last_log_lines(log_path, count=3)
    except OSError as e:
        print(f"[{subagent_id}] Failed to read log file: {e}")
        return

    print(f"=== Subagent: {subagent_id} ===")
    for line in lines:
        parse_and_print_log_line(subagent_id, line)
    print("-" * 50)

def check_all_subagents() -> None:
    """登録されているすべてのサブエージェントのログを確認する"""
    base_brain_dir = get_base_brain_dir()
    for subagent_id in NEW_SUBAGENT_IDS:
        process_subagent_log(subagent_id, base_brain_dir)

# インポート時またはスクリプト実行時に自動で確認処理を実行する（既存のテスト・運用との互換性維持のため）
check_all_subagents()
