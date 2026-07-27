"""
設計乖離自己検証ガード (compliance_guard.py)

設計書（implementation_plan.md）で定義された要件（REQ-）と、
実装コード（# satisfies: REQ-）、テストコード（# verifies: REQ-）の
対応関係を自動走査し、乖離度（ギャップ）を計算・レポートする。
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Any, Set

class DesignComplianceGuard:
    def __init__(self, workspace_path: str = None, plan_path: str = None):
        # REQ-COMP-01 / REQ-COMP-02 / REQ-COMP-03 / REQ-COMP-04: クラスの初期化
        self.workspace_path = Path(workspace_path or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
        
        # デフォルトの設計書パス（本セッションの implementation_plan.md）
        if plan_path:
            self.plan_path = Path(plan_path)
        else:
            # ワークスペースパスから遡って implementation_plan.md を探す
            detected_plan = None
            current_dir = self.workspace_path
            # ルートに達するか、最大5階層上まで探索する
            for _ in range(6):
                possible_plan = current_dir / "implementation_plan.md"
                if possible_plan.exists():
                    detected_plan = possible_plan
                    break
                if current_dir == current_dir.parent:
                    break
                current_dir = current_dir.parent
            
            if detected_plan:
                self.plan_path = detected_plan
            else:
                # フォールバックとして従来のパス
                home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "~").expanduser()
                self.plan_path = home / ".gemini" / "antigravity" / "brain" / "28e3f94b-9983-483d-ab3b-1bd4e3ee5bda" / "implementation_plan.md"

        self.backend_dir = self.workspace_path / "backend"

    def parse_requirements(self) -> Set[str]:
        """設計書から要件ID (REQ-で始まるもの) をパース・抽出する。"""
        # satisfies: REQ-COMP-01
        requirements = set()
        if not self.plan_path.exists():
            return requirements

        # 設計書ファイルを走査して「REQ-」パターンを検出
        req_pattern = re.compile(r"REQ-[A-Z0-9_-]+")
        try:
            with open(self.plan_path, "r", encoding="utf-8") as f:
                for line in f:
                    # テーブル行やテキスト内の要件IDを抽出
                    matches = req_pattern.findall(line)
                    for match in matches:
                        # プレースホルダーの除外
                        if match == "REQ-ID":
                            continue
                        requirements.add(match)
        except OSError:
            pass
        return requirements

    def scan_codebase(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """コードベースを走査し、# satisfies および # verifies タグを抽出する。"""
        # satisfies: REQ-COMP-02
        # satisfies: REQ-COMP-03
        scan_results = {
            "satisfies": {},  # REQ-ID -> [{"file": file_rel_path, "line": line_no}]
            "verifies": {}    # REQ-ID -> [{"file": file_rel_path, "line": line_no}]
        }

        satisfies_pattern = re.compile(r"#\s*satisfies:\s*(REQ-[A-Z0-9_-]+)")
        verifies_pattern = re.compile(r"#\s*verifies:\s*(REQ-[A-Z0-9_-]+)")

        if not self.backend_dir.exists():
            return scan_results

        # backend/ 配下を再帰的に走査 (tmp, .pytest_cache などの不要ディレクトリは除外)
        for root, dirs, files in os.walk(self.backend_dir):
            # 除外ディレクトリ
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".pytest_cache", "venv", "env", "node_modules", "tmp")]
            
            for file in files:
                if not file.endswith(".py"):
                    continue
                
                file_path = Path(root) / file
                rel_path = file_path.relative_to(self.workspace_path).as_posix()

                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        for idx, line in enumerate(f, 1):
                            # satisfies のスキャン (REQ-COMP-02)
                            sat_match = satisfies_pattern.search(line)
                            if sat_match:
                                req_id = sat_match.group(1)
                                if req_id not in scan_results["satisfies"]:
                                    scan_results["satisfies"][req_id] = []
                                scan_results["satisfies"][req_id].append({"file": rel_path, "line": idx})

                            # verifies のスキャン (REQ-COMP-03)
                            ver_match = verifies_pattern.search(line)
                            if ver_match:
                                req_id = ver_match.group(1)
                                if req_id not in scan_results["verifies"]:
                                    scan_results["verifies"][req_id] = []
                                scan_results["verifies"][req_id].append({"file": rel_path, "line": idx})
                except OSError:
                    continue

        return scan_results

    def evaluate_compliance(self) -> Dict[str, Any]:
        """設計書と実装状況を比較し、準拠度・乖離度を評価する。"""
        # satisfies: REQ-COMP-04
        reqs = self.parse_requirements()
        scan = self.scan_codebase()

        report = {
            "total_requirements": len(reqs),
            "requirements": {},
            "metrics": {
                "implementation_pct": 0.0,
                "verification_pct": 0.0,
                "compliance_pct": 0.0
            },
            "unimplemented": [],
            "unverified": [],
            "passed": False
        }

        if not reqs:
            # 要件定義が存在しない場合は100%合格とみなす
            report["metrics"]["compliance_pct"] = 100.0
            report["passed"] = True
            return report

        implemented_count = 0
        verified_count = 0
        compliant_count = 0

        for req in sorted(reqs):
            impl_sources = scan["satisfies"].get(req, [])
            ver_sources = scan["verifies"].get(req, [])

            is_impl = len(impl_sources) > 0
            is_ver = len(ver_sources) > 0
            is_compliant = is_impl and is_ver

            if is_impl:
                implemented_count += 1
            else:
                report["unimplemented"].append(req)

            if is_ver:
                verified_count += 1
            else:
                report["unverified"].append(req)

            if is_compliant:
                compliant_count += 1

            report["requirements"][req] = {
                "implemented": is_impl,
                "verified": is_ver,
                "compliant": is_compliant,
                "implementations": impl_sources,
                "verifications": ver_sources
            }

        # スコア計算
        total = len(reqs)
        report["metrics"]["implementation_pct"] = round((implemented_count / total) * 100, 1)
        report["metrics"]["verification_pct"] = round((verified_count / total) * 100, 1)
        report["metrics"]["compliance_pct"] = round((compliant_count / total) * 100, 1)

        # 総合合格判定 (実装かつ検証がすべて完了していること)
        report["passed"] = compliant_count == total

        return report

    def generate_report_markdown(self, report: Dict[str, Any] = None) -> str:
        """乖離度分析の Markdown レポートを生成する。"""
        if report is None:
            report = self.evaluate_compliance()

        metrics = report["metrics"]
        score = metrics["compliance_pct"]
        
        # プログレスバーの描画
        bar_len = 20
        filled_len = int(round(bar_len * score / 100))
        bar = "█" * filled_len + "░" * (bar_len - filled_len)

        md = f"### 🛡️ 設計乖離度分析 (Design compliance Guard)\n\n"
        md += f"**総合準拠スコア**: `{score}%` | `[{bar}]` ({'🟢 合格' if report['passed'] else '🔴 乖離あり'})\n"
        md += f"- **実装率**: `{metrics['implementation_pct']}%` | **検証テスト率**: `{metrics['verification_pct']}%` | **定義要件数**: `{report['total_requirements']}`件\n\n"

        if not report["passed"]:
            md += "#### ⚠️ 検出された設計乖離\n"
            if report["unimplemented"]:
                md += "- **未実装要件**: " + ", ".join([f"`{r}`" for r in report["unimplemented"]]) + "\n"
            if report["unverified"]:
                md += "- **未検証要件**: " + ", ".join([f"`{r}`" for r in report["unverified"]]) + "\n"
            md += "\n"
        else:
            md += "✨ すべての設計要件に対する実装およびテストによる検証が完了し、乖離度は **0%** です。\n\n"

        # 詳細テーブル
        md += "| 要件ID | 実装状況 | 検証状況 | 準拠状態 | 該当ファイル |\n"
        md += "| :--- | :---: | :---: | :---: | :--- |\n"
        for req, status in sorted(report["requirements"].items()):
            impl_status = "✅" if status["implemented"] else "❌"
            ver_status = "✅" if status["verified"] else "❌"
            comp_status = "🟢 合格" if status["compliant"] else "🔴 乖離"
            
            # 代表ファイルの表示
            files = []
            for impl in status["implementations"]:
                files.append(f"`{os.path.basename(impl['file'])}`")
            for ver in status["verifications"]:
                files.append(f"`{os.path.basename(ver['file'])}` (T)")
                
            files_str = ", ".join(files) if files else "N/A"
            md += f"| `{req}` | {impl_status} | {ver_status} | {comp_status} | {files_str} |\n"

        return md

if __name__ == "__main__":
    guard = DesignComplianceGuard()
    rep = guard.evaluate_compliance()
    print(guard.generate_report_markdown(rep))
