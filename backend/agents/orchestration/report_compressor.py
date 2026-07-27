# -*- coding: utf-8 -*-
import re
from typing import List, Dict, Any, Optional, Tuple

class ReportCompressor:
    """
    1,500タスクなどの大量の実行レポートをアウターループ用に圧縮・集約するエンジン。
    
    v2追加機能:
    - compress_agent_response(): 個々のサブエージェント応答を短いサマリーに圧縮
    - compress_test_output(): pytestの冗長な出力を圧縮
    これにより、Flash本体のコンテキスト消費を大幅に削減し、セッション寿命を延長する。
    """
    
    # 圧縮後の最大文字数（約100トークン相当）
    MAX_SUMMARY_CHARS = 400
    MAX_TEST_OUTPUT_CHARS = 300
    MAX_TRACEBACK_LINES = 5
    
    def _normalize_error(self, error_message: Any) -> str:
        """
        エラーメッセージから可変値（アドレス、数値、パス等）を除去して正規化する。
        """
        if not error_message:
            return "UnknownError"
        
        try:
            if not isinstance(error_message, str):
                error_message = str(error_message)
        except (TypeError, ValueError, AttributeError, RuntimeError):
            return "UnknownError"
            
        if not error_message.strip():
            return "UnknownError"
            
        # 1行目だけを取得（スタックトレース全体ではなくエラーの主メッセージ）
        first_line = error_message.split("\n")[0]
        
        # メモリ番地等の除去 (e.g. 0x7f83e20)
        normalized = re.sub(r"0x[0-9a-fA-F]+", "0x...", first_line)
        # 数値の正規化
        normalized = re.sub(r"\b\d+\b", "N", normalized)
        # ファイルパスの簡略化
        normalized = re.sub(r"[\w\\/\.\-]+\.py", "file.py", normalized)
        
        return normalized.strip() or "UnknownError"

    def compress_agent_response(self, response_text: str, task_id: str = "",
                                 modified_files: Optional[List[str]] = None) -> str:
        """
        サブエージェントの応答テキストを短いサマリーに圧縮する。
        
        Flashのコンテキストに戻す応答をMAX_SUMMARY_CHARS以内に制限し、
        詳細はファイル（flash_reports.jsonl等）に記録する。
        
        Returns:
            圧縮されたサマリー文字列（約100トークン以内）
        """
        if not response_text:
            return f"[{task_id}] 応答なし"
        
        if not isinstance(response_text, str):
            response_text = str(response_text)
        
        # 既に十分短い場合はそのまま返す
        if len(response_text) <= self.MAX_SUMMARY_CHARS:
            return response_text
        
        summary_parts = []
        
        # ステータス行を抽出
        status_lines = self._extract_status_indicators(response_text)
        if status_lines:
            summary_parts.append(" | ".join(status_lines))
        
        # 変更ファイルリスト
        if modified_files:
            validated_files = []
            if isinstance(modified_files, (list, tuple)):
                for f in modified_files:
                    if f is not None:
                        validated_files.append(str(f))
            else:
                validated_files.append(str(modified_files))
            
            if validated_files:
                summary_parts.append(self._format_modified_files(validated_files))
        
        # サマリーが空の場合は先頭を切り出し
        if not summary_parts:
            summary_parts.append(self._fallback_truncate(response_text))
        
        formatted_summary = f"[{task_id}] " + " | ".join(summary_parts)
        return formatted_summary[:self.MAX_SUMMARY_CHARS]

    def _extract_status_indicators(self, response_text: str) -> List[str]:
        """
        応答テキストからステータスを示す行（✅, ❌, PASS, FAIL等）を抽出する。
        """
        status_lines = []
        for line in response_text.split("\n"):
            line_stripped = line.strip()
            if any(marker in line_stripped for marker in ["✅", "❌", "PASS", "FAIL", "pass", "fail", "完了", "成功", "失敗"]):
                status_lines.append(line_stripped[:100])
            if len(status_lines) >= 3:
                break
        return status_lines

    def _format_modified_files(self, modified_files: List[str]) -> str:
        """
        変更されたファイルのリストを要約された文字列に整形する。
        """
        files_str = ", ".join(modified_files[:5])
        if len(modified_files) > 5:
            files_str += f" (+{len(modified_files) - 5}件)"
        return f"変更: {files_str}"

    def _fallback_truncate(self, response_text: str) -> str:
        """
        応答テキストの先頭と末尾を切り出して結合するフォールバック要約を作成する。
        """
        return response_text[:300] + "..." + response_text[-100:]
    
    def compress_test_output(self, pytest_output: str) -> str:
        """
        pytestの出力を圧縮する。成功時は1行サマリー、失敗時はエラー箇所のみ抽出。
        
        Returns:
            圧縮されたテスト出力（MAX_TEST_OUTPUT_CHARS以内）
        """
        if not pytest_output:
            return "テスト出力なし"
        
        if not isinstance(pytest_output, str):
            pytest_output = str(pytest_output)
        
        if len(pytest_output) <= self.MAX_TEST_OUTPUT_CHARS:
            return pytest_output
        
        output_lines = pytest_output.split("\n")
        
        # pytest のサマリー行を探す
        summary_line = self._extract_pytest_summary(output_lines)
        
        # FAILED行とERROR行の抽出
        failed_lines, error_lines = self._extract_failed_and_error_lines(output_lines)
        
        result_parts = []
        if summary_line:
            result_parts.append(summary_line)
        if failed_lines:
            result_parts.append("FAILED: " + " | ".join(failed_lines))
        if error_lines and not failed_lines:
            result_parts.append("ERROR: " + " | ".join(error_lines))
        
        if not result_parts:
            # フォールバック: 末尾のサマリー部分を抽出
            result_parts.append(output_lines[-1].strip() if output_lines else "不明")
        
        result = " | ".join(result_parts)
        return result[:self.MAX_TEST_OUTPUT_CHARS]

    def _extract_pytest_summary(self, output_lines: List[str]) -> str:
        """
        pytest出力の各行からサマリー行（"X passed", "X failed" 等）を後方から探索して取得する。
        """
        for line in reversed(output_lines):
            if re.search(r"\d+ passed", line) or re.search(r"\d+ failed", line):
                return line.strip()
        return ""

    def _extract_failed_and_error_lines(self, output_lines: List[str]) -> Tuple[List[str], List[str]]:
        """
        pytest出力からFAILEDおよびERROR行を抽出する。
        """
        failed_lines = [line.strip() for line in output_lines if "FAILED" in line][:self.MAX_TRACEBACK_LINES]
        error_lines = [line.strip() for line in output_lines if "ERROR" in line or "Error" in line][:self.MAX_TRACEBACK_LINES]
        return failed_lines, error_lines
    
    def compress_traceback(self, traceback_str: str) -> str:
        """
        Pythonトレースバックを圧縮する。最後のN行（エラーの核心部分）のみ保持。
        さらに最大300文字に切り詰める。
        """
        if not traceback_str:
            return ""
        
        if not isinstance(traceback_str, str):
            traceback_str = str(traceback_str)
        
        lines = traceback_str.strip().split("\n")
        if len(lines) > self.MAX_TRACEBACK_LINES:
            # 最後のMAX_TRACEBACK_LINES行を保持
            compressed = lines[-self.MAX_TRACEBACK_LINES:]
            traceback_str = f"...({len(lines) - self.MAX_TRACEBACK_LINES}行省略)\n" + "\n".join(compressed)
        
        # 最終的な文字数が300文字を超える場合は切り詰め
        if len(traceback_str) > 300:
            traceback_str = traceback_str[:300]
            
        return traceback_str

    def compress(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        タスク報告リストを定量的メトリクスとクラスタリングされたエラー情報に圧縮する。
        """
        if not isinstance(tasks, list):
            tasks = []

        total = len(tasks)
        passed = 0
        failed = 0
        error_groups = {}

        for task in tasks:
            if not isinstance(task, dict):
                continue
            status = task.get("status")
            if status == "pass":
                passed += 1
            elif status == "fail":
                failed += 1
                try:
                    self._cluster_single_task_error(task, error_groups)
                except (AttributeError, KeyError, TypeError, ValueError) as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Error clustering single task: {e}")

        success_rate = round(passed / total * 100, 1) if total > 0 else 0.0

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": success_rate,
            "clustered_errors": list(error_groups.values())
        }

    def _cluster_single_task_error(self, task: Dict[str, Any], error_groups: Dict[str, Dict[str, Any]]) -> None:
        """
        個別タスクのFAIL情報からエラーを抽出し、指定のグループ辞書へクラスタリングする。
        """
        report = task.get("report")
        if not isinstance(report, dict):
            extracted_error_message = str(report) if report else "Unknown error occurred"
            traceback_str = ""
        else:
            extracted_error_message = report.get("error") or report.get("message") or "Unknown error occurred"
            traceback_str = report.get("traceback") or ""
        
        normalized = self._normalize_error(extracted_error_message)
        module = task.get("target_module") or "unknown"
        
        if normalized not in error_groups:
            error_groups[normalized] = {
                "error": normalized,
                "count": 0,
                "module": module,
                "sample_traceback": self.compress_traceback(traceback_str)
            }
        error_groups[normalized]["count"] += 1
