"""
record_skill_metrics.py - スキルメトリクス記録ツール (Kitchen)

各スキルの実行完了時に、Anthropicガイドラインに基づく改善メトリクスをJSONL形式で記録する。
Vault分離原則に従い、ログはコード領域を汚染しない `vault-outputs/logs/` 配下に保存される。

Usage:
    python tools/record_skill_metrics.py --skill <skill_name> --success true --tokens 8000 --trigger_accuracy high --tool_efficiency high
"""
import argparse
import json
import os
import datetime
import sys

def main():
    # Windowsコンソールでの文字化け防止 (出力エンコーディングの強制)
    if sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')

    parser = argparse.ArgumentParser(description="スキルメトリクス記録ツール")
    parser.add_argument("--skill", required=True, help="実行されたスキルの名前")
    parser.add_argument("--success", type=str, required=True, help="'true' または 'false'")
    parser.add_argument("--tokens", type=int, default=0, help="消費トークン数の推定値")
    parser.add_argument("--time_ms", type=int, default=0, help="実行時間（ミリ秒）")
    parser.add_argument("--failures", default="[]", help="JSON文字列によるツール失敗履歴")
    parser.add_argument("--suggestion", default="", help="次回に向けた改善の提案（失敗時など）")
    # 追加したメトリクス
    parser.add_argument("--trigger_accuracy", default="N/A", help="トリガー精度 (high/medium/low等)")
    parser.add_argument("--tool_efficiency", default="N/A", help="ツール呼び出し効率 (high/medium/low等)")
    
    args = parser.parse_args()
    
    log_dir = os.path.join("vault-outputs", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "skills_metrics.jsonl")
    
    try:
        failures_list = json.loads(args.failures)
    except json.JSONDecodeError:
        failures_list = [{"parse_error": "Invalid JSON provided for --failures"}]

    is_success = str(args.success).lower() == "true"

    metric_data = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "skill_name": args.skill,
        "execution_time_ms": args.time_ms,
        "tokens_estimated": args.tokens,
        "trigger_accuracy": args.trigger_accuracy,
        "tool_call_efficiency": args.tool_efficiency,
        "tool_failures": failures_list,
        "success": is_success,
        "optimization_suggestion": args.suggestion
    }

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(metric_data, ensure_ascii=False) + "\n")
        
    print(json.dumps({
        "status": "success", 
        "message": f"Metrics recorded for {args.skill}",
        "log_path": log_file
    }, ensure_ascii=False, indent=2))
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
