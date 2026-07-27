"""council_decision_extractor.py — 評議会ファクトベース合意形成 (DS-021)

本モジュールは、Nexus-Council 3.0 の合議ログから最終的なアトミック意思決定を抽出し、
VerifiedFacts（検証済みファクト）に自動記録する機能を実装します。
また、three_point_check の要件（入力ガードレール、定量的マッピング、セーフティフォールバック）を包含します。
"""

import os
import re
import sys
import json
import logging
import traceback
from typing import List, Dict, Any, Optional, Tuple
from backend.agents.memory.verified_facts import verified_facts_store
from backend.agents.memory.technical_debt import technical_debt_store

logger = logging.getLogger(__name__)


# ==============================================================
# 1. 入力ガードレール (Input Guardrail)
# ==============================================================
class ExtractorInputGuardrail:
    """合議ログデータに対するバリデーションおよびセキュリティ検証を行うガードレール。"""

    SUSPICIOUS_PATTERNS = [
        r"System\.exit",
        r"import\s+os",
        r"subprocess\.",
        r"eval\(",
        r"exec\(",
        r"<script>",
    ]

    @classmethod
    def validate_log_data(cls, log_data: Any) -> Dict[str, Any]:
        """ログデータの妥当性と安全性を検証。

        Args:
            log_data: 辞書型または JSON 文字列型の合議ログ。

        Returns:
            検証済みの辞書データ。

        Raises:
            ValueError: ガードレール違反があった場合。
        """
        validated_dict = cls._deserialize_and_validate(log_data)
        
        synthesis = validated_dict.get("synthesis")
        cls._validate_synthesis(synthesis)

        debate_flow = validated_dict.get("debate_flow", [])
        cls._validate_debate_flow(debate_flow)

        return validated_dict

    @classmethod
    def _check_payload_size(cls, raw_str: str) -> None:
        """入力データのサイズが制限を超えていないか検証する。"""
        # 最大 1MB = 1,048,576 バイト
        if len(raw_str.encode("utf-8")) > 1048576:
            raise ValueError("入力データのサイズが制限（1MB）を超えています。")

    @classmethod
    def _check_suspicious_patterns(cls, content_str: str, error_msg: str) -> None:
        """文字列中に不審なインジェクションパターンが含まれていないか検証する。"""
        for suspicious_pattern in cls.SUSPICIOUS_PATTERNS:
            if re.search(suspicious_pattern, content_str, re.IGNORECASE):
                raise ValueError(error_msg)

    @classmethod
    def _deserialize_and_validate(cls, log_data: Any) -> Dict[str, Any]:
        """JSON文字列のデコードおよび辞書型の基本検証を行う。"""
        if log_data is None:
            raise ValueError("ログデータが指定されていません。")

        # JSON 文字列の場合は辞書にデシリアライズ
        if isinstance(log_data, str):
            cls._check_payload_size(log_data)
            cls._check_suspicious_patterns(log_data, "不審な文字パターンが検出されました。")

            try:
                decoded_data = json.loads(log_data)
            except json.JSONDecodeError as decode_error:
                raise ValueError(f"JSON のデコードに失敗しました: {decode_error}")
            
            log_data = decoded_data

        if not isinstance(log_data, dict):
            raise ValueError("ログデータは辞書型または有効な JSON 文字列である必要があります。")

        # 必須フィールドの確認
        if "synthesis" not in log_data:
            raise ValueError("ログデータに 'synthesis' フィールドが含まれていません。")

        return log_data

    @classmethod
    def _validate_synthesis(cls, synthesis: Any) -> None:
        """synthesisフィールドの検証を行う。"""
        if not synthesis or not isinstance(synthesis, (str, dict)):
            raise ValueError("'synthesis' は非空の文字列または辞書である必要があります。")

        # synthesis が辞書の場合は文字列に変換、または文字列としてパース
        if isinstance(synthesis, dict):
            synthesis_str = json.dumps(synthesis, ensure_ascii=False)
        else:
            synthesis_str = str(synthesis)

        # 文字列としてインジェクションチェック（再度検証）
        cls._check_suspicious_patterns(synthesis_str, "synthesis 内に不審な文字パターンが検出されました。")

    @classmethod
    def _validate_debate_flow(cls, debate_flow: Any) -> None:
        """debate_flowフィールドの検証を行う。"""
        if not isinstance(debate_flow, list):
            raise ValueError("'debate_flow' はリスト形式である必要があります。")

        for flow_entry in debate_flow:
            if not isinstance(flow_entry, dict):
                raise ValueError("'debate_flow' の要素は辞書型である必要があります。")
            
            agent_name = flow_entry.get("agent")
            if agent_name is not None and not isinstance(agent_name, str):
                raise ValueError("'agent' は文字列である必要があります。")

            speech_summary = flow_entry.get("summary")
            if speech_summary is not None:
                if not isinstance(speech_summary, str):
                    raise ValueError("'summary' は文字列である必要があります。")
                cls._check_suspicious_patterns(speech_summary, "debate_flow 内に不審な文字パターンが検出されました。")


# ==============================================================
# 2. 定量的マッピング (Quantitative Mapping)
# ==============================================================
class ExtractorQuantitativeMapping:
    """入力ログの複雑度に基づいて処理パラメータ（確信度閾値、最大抽出数など）をマッピングする。"""

    @classmethod
    def _calculate_total_length(cls, synthesis_str: str, debate_flow: Any) -> int:
        """ログデータの総文字数を計算する。"""
        total_len = len(synthesis_str)
        if isinstance(debate_flow, list):
            for flow_entry in debate_flow:
                if isinstance(flow_entry, dict):
                    summary_value = flow_entry.get("summary")
                    if summary_value is not None:
                        total_len += len(str(summary_value))
        return total_len

    @classmethod
    def resolve_parameters(cls, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """ログデータの複雑度（文字数・対話数）から抽出用のパラメータを定量的に決定する。"""
        synthesis = log_data.get("synthesis", "")
        synthesis_str = json.dumps(synthesis, ensure_ascii=False) if isinstance(synthesis, dict) else str(synthesis)
        
        debate_flow = log_data.get("debate_flow", [])
        
        # 複雑度の計算
        total_length = cls._calculate_total_length(synthesis_str, debate_flow)

        # パラメータマッピングの決定
        if total_length < 200:
            # 簡易ログ
            max_facts = 2
            confidence_threshold = 0.8
            complexity_level = "LOW"
        elif total_length < 1000:
            # 通常ログ
            max_facts = 5
            confidence_threshold = 0.85
            complexity_level = "MEDIUM"
        else:
            # 詳細ログ（複雑）
            max_facts = 8
            confidence_threshold = 0.90
            complexity_level = "HIGH"

        return {
            "max_facts": max_facts,
            "confidence_threshold": confidence_threshold,
            "complexity_level": complexity_level,
            "calculated_length": total_length
        }


# ==============================================================
# 3. セーフティフォールバック (Safety Fallback)
# ==============================================================
class ExtractorSafetyFallback:
    """エラーや例外が発生した際のセーフティネット。"""

    @classmethod
    def execute_fallback(
        cls,
        error_msg: str,
        session_id: Optional[str] = None,
        file_path: Optional[str] = None,
        line_number: Optional[int] = None
    ) -> Dict[str, Any]:
        """エラーを技術負債ストアに自動記録し、デフォルトのフォールバックファクトをVerifiedFactsに保存する。"""
        resolved_session_id = session_id or "unknown-session"
        logger.warning(f"Safety Fallback triggered for session: {resolved_session_id}. Reason: {error_msg}")

        # 例外位置情報を解決
        file_path, line_number = cls._resolve_error_location(file_path, line_number)

        # 1. 技術負債に自動登録
        cls._register_technical_debt(error_msg, file_path, line_number, resolved_session_id)

        # 2. 最低限のデフォルトファクトを VerifiedFacts に自動記録
        fallback_fact_content = f"合議セッション {resolved_session_id} が完了しました（詳細決定は自動抽出失敗のためフォールバック記録）。"
        fallback_fact = cls._record_fallback_fact(resolved_session_id, error_msg, fallback_fact_content)

        return {
            "status": "fallback",
            "error": error_msg,
            "session_id": resolved_session_id,
            "extracted_facts": [fallback_fact_content] if fallback_fact else []
        }

    @classmethod
    def _resolve_error_location(
        cls,
        file_path: Optional[str],
        line_number: Optional[int]
    ) -> Tuple[str, int]:
        """例外が発生している場合、動的にファイル名と行番号を取得する。"""
        exception_type, exception_value, exception_traceback = sys.exc_info()
        if exception_traceback:
            traceback_list = traceback.extract_tb(exception_traceback)
            if traceback_list:
                last_frame = traceback_list[-1]
                if not file_path:
                    file_path = os.path.relpath(last_frame.filename)
                    # パス区切りをスラッシュに統一
                    file_path = file_path.replace("\\", "/")
                if not line_number:
                    line_number = last_frame.lineno

        if not file_path:
            file_path = "backend/agents/memory/council_decision_extractor.py"
        if not line_number:
            line_number = 100

        return file_path, line_number

    @classmethod
    def _register_technical_debt(
        cls,
        error_msg: str,
        file_path: str,
        line_number: int,
        session_id: str
    ) -> None:
        """技術負債ストアへ例外情報を登録する。"""
        try:
            technical_debt_store.register_debt(
                category="ACCEPTED_SAFETY",
                file_path=file_path,
                line_number=line_number,
                pattern=f"fallback due to: {error_msg[:50]}",
                cause_pattern="DP-05",  # 堅牢なエラー耐性とフォールバック
                fix_pattern="自動回復可能だが、合議ログのパース失敗の調査推奨",
                registered_by="council_decision_extractor",
                notes=f"Session: {session_id}, Error: {error_msg}"
            )
        except (ValueError, OSError) as registration_error:
            logger.error(f"技術負債への登録中にエラーが発生しました: {registration_error}")

    @classmethod
    def _record_fallback_fact(
        cls,
        session_id: str,
        error_msg: str,
        fallback_fact_content: str
    ) -> Optional[Any]:
        """VerifiedFacts にデフォルトの進捗レコードを書き込む。"""
        fallback_fact = None
        try:
            fallback_fact = verified_facts_store.add_fact(
                category="progress",
                content=fallback_fact_content,
                evidence=f"Safety Fallback (Error: {error_msg[:100]})",
                source="council",
                confidence=1.0,
                tags=["fallback", f"session_{session_id}"]
            )
        except OSError as write_error:
            logger.error(f"VerifiedFacts へのフォールバック書き込み中にエラーが発生しました: {write_error}")
        return fallback_fact


# ==============================================================
# 4. 意思決定の抽出 ＆ 自動記録メイン処理
# ==============================================================
class CouncilDecisionExtractor:
    """合議ログから最終的な決定事項を抽出し、VerifiedFacts に自動記録する。"""

    # ファクトを抽出するための正規表現パターンとキーワード
    DECISION_PATTERNS = [
        # 〜を決定した、〜を採用した、〜に合意した、〜と決定
        r"([^。\n]+?(?:決定|採用|合意|確定)し(?:た|ます|ている))",
        r"([^。\n]+?(?:決定|採用|合意)(?:事項|案|した仕様|結果|内容))",
        r"確定仕様として(?:は|、)\s*(.+?)(?:とする|と決定|を採用)",
        r"(?:方針|ルール)として(?:は|、)\s*(.+?)(?:とする|と決定|を採用)",
        # 文末が「〜と決定。」や「〜に合意。」などで終わるケース
        r"([^。\n]+?(?:決定|採用|合意|確定)(?:。|\b))",
        # 箇条書きの末尾が「決定。」などで終わるケースを含む
        r"[-*•]\s*(.+?(?:決定|採用|合意|確定|適用する|変更する|廃止する|と決定|を好む)[^。\n]*)"
    ]

    @classmethod
    def _categorize_fact(cls, text: str) -> str:
        """テキストの内容から適切な VerifiedFacts カテゴリを割り当てる。"""
        lowered_text = text.lower()
        if any(keyword in lowered_text for keyword in ["アーキテクチャ", "構成", "設計", "コンポーネント", "モジュール", "ディレクトリ", "ライブラリ", "依存"]):
            return "architecture"
        elif any(keyword in lowered_text for keyword in ["好み", "好む", "こだわり", "希望", "カラー", "配色", "フォント", "デザイン", "トーン", "スタイル"]):
            return "preference"
        elif any(keyword in lowered_text for keyword in ["仕様", "機能", "ルール", "要件", "インタフェース", "インターフェース", "閾値", "パラメータ", "上限", "制限"]):
            return "specification"
        elif any(keyword in lowered_text for keyword in ["教訓", "反省", "失敗", "リスク", "バグ", "対策", "トラブル"]):
            return "lesson"
        else:
            return "progress"

    @classmethod
    def _contains_negation(cls, text: str) -> bool:
        """テキスト内に決定・合意などを打ち消す否定表現が含まれているか判定する。"""
        negation_keywords = ["決定", "採用", "合意", "確定"]
        for kw in negation_keywords:
            for neg in [f"{kw}には至りませんでした", f"{kw}していません", f"{kw}は行いませんでした"]:
                if neg in text:
                    return True
        return False

    @classmethod
    def _find_decision_candidates(cls, line: str) -> List[str]:
        """行に対して決定正規表現パターンマッチングを行い、マッチした文字列のリストを返す。"""
        candidates = []
        for pattern in cls.DECISION_PATTERNS:
            matches = re.findall(pattern, line)
            for m in matches:
                decision_value = m[0] if isinstance(m, tuple) else m
                decision_value = decision_value.strip()
                if len(decision_value) > 5:
                    candidates.append(decision_value)
        return candidates

    @classmethod
    def extract_decisions(
        cls,
        synthesis_str: str,
        debate_flow: List[Dict[str, Any]]
    ) -> List[Tuple[str, str]]:
        """synthesis_str および debate_flow から決定事項をルールベースで抽出する。"""
        synthesis_candidates = cls._extract_from_synthesis(synthesis_str)
        debate_candidates = cls._extract_from_debate_flow(debate_flow)
        
        all_candidates = synthesis_candidates + debate_candidates
        return cls._deduplicate_candidates(all_candidates)

    @classmethod
    def _process_synthesis_line(cls, line_str: str) -> List[Tuple[str, str]]:
        """synthesis 内の1行を評価し、決定事項候補を抽出する。"""
        line_str = line_str.strip()
        if not line_str:
            return []

        # 否定表現が含まれる場合はスキップする（誤検出防止）
        if cls._contains_negation(line_str):
            return []

        candidates = []
        # パターンマッチング
        matched_values = cls._find_decision_candidates(line_str)
        for val in matched_values:
            candidates.append((val, "synthesis"))
        
        # 箇条書きの中で決定などのキーワードが明示的に含まれる場合のみ、マッチしていないものも補足
        if not matched_values and line_str.startswith(("-", "*", "•")):
            if any(kw in line_str for kw in ["決定", "採用", "合意", "確定"]):
                cleaned = re.sub(r"^[-*•\s]+", "", line_str).strip()
                if len(cleaned) > 10:
                    candidates.append((cleaned, "synthesis"))

        return candidates

    @classmethod
    def _extract_from_synthesis(cls, synthesis_str: str) -> List[Tuple[str, str]]:
        """synthesis_str から決定事項を抽出する。"""
        candidates = []
        lines = synthesis_str.split("\n")
        
        for line in lines:
            line_candidates = cls._process_synthesis_line(line)
            candidates.extend(line_candidates)

        return candidates

    @classmethod
    def _extract_from_debate_flow(cls, debate_flow: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """debate_flow から各エージェントの決定事項を抽出する。"""
        candidates = []

        for idx, entry in enumerate(debate_flow):
            if not isinstance(entry, dict):
                continue
            agent = entry.get("agent", f"Agent-{idx}")
            summary = entry.get("summary", "")
            if not summary:
                continue
            
            summary_str = str(summary)
            
            # 否定表現チェック
            if cls._contains_negation(summary_str):
                continue

            if any(kw in summary_str for kw in ["決定", "採用", "合意", "確定", "推奨する"]):
                cleaned = re.sub(r"^[-*•\d\.\)\s]+", "", summary_str).strip()
                if len(cleaned) > 10:
                    candidates.append((f"{agent}: {cleaned}", "debate_flow"))

        return candidates

    @classmethod
    def _deduplicate_candidates(cls, candidates: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
        """重複の削除（順序を維持）。表記揺れも考慮する。"""
        seen = set()
        unique_candidates = []
        for text, src in candidates:
            # 記号などの軽微な表記揺れを除去して一意にする
            normalized = re.sub(r"[^\w\s]", "", text)
            if normalized not in seen:
                seen.add(normalized)
                unique_candidates.append((text, src))
        return unique_candidates

    @classmethod
    def process_and_record(cls, log_data: Any) -> Dict[str, Any]:
        """合議ログを検証・解析し、決定事項を VerifiedFacts に自動記録するメインフロー。

        Args:
            log_data: 辞書型または JSON 文字列型の合議ログ。

        Returns:
            処理結果（status, extracted_facts 等の辞書）。
        """
        session_id = "unknown"
        try:
            # Step 1: 入力ガードレール
            validated_data = ExtractorInputGuardrail.validate_log_data(log_data)
            
            session_id = str(validated_data.get("session_id", "unknown"))

            # Step 2: 定量的マッピング
            params = ExtractorQuantitativeMapping.resolve_parameters(validated_data)
            max_facts = params["max_facts"]
            confidence_threshold = params["confidence_threshold"]

            # ログデータのパース
            synthesis = validated_data.get("synthesis", "")
            synthesis_str = json.dumps(synthesis, ensure_ascii=False) if isinstance(synthesis, dict) else str(synthesis)
            debate_flow = validated_data.get("debate_flow", [])

            # Step 3: 意思決定の抽出
            candidates = cls.extract_decisions(synthesis_str, debate_flow)

            # パラメータに基づき抽出件数を制限
            candidates = candidates[:max_facts]

            recorded_facts = []
            for text, src in candidates:
                category = cls._categorize_fact(text)
                
                # VerifiedFacts Store に記録
                # アトミック書き込みおよび排他ロックは verified_facts_store 側で自動保証される
                fact = verified_facts_store.add_fact(
                    category=category,
                    content=text,
                    evidence=f"Council Session: {session_id} ({src} extraction)",
                    source="council",
                    confidence=confidence_threshold,  # 定量的マッピングで決定された閾値を反映
                    tags=["decision", f"session_{session_id}"]
                )
                recorded_facts.append(fact.content)

            # 万が一何も抽出されなかった場合は、最低限の進捗ファクトを記録する（安全弁）
            if not recorded_facts:
                progress_fact = verified_facts_store.add_fact(
                    category="progress",
                    content=f"合議セッション {session_id} が完了し、合意形成が記録されました。",
                    evidence=f"Council Session: {session_id} (No detailed decisions extracted)",
                    source="council",
                    confidence=confidence_threshold,
                    tags=["progress", f"session_{session_id}"]
                )
                recorded_facts.append(progress_fact.content)

            return {
                "status": "success",
                "session_id": session_id,
                "extracted_facts": recorded_facts,
                "complexity_level": params["complexity_level"]
            }

        except ValueError as val_err:
            # バリデーションエラー時は Safety Fallback を実行（例外から動的に行番号とファイル名を取得）
            return ExtractorSafetyFallback.execute_fallback(
                error_msg=f"入力検証エラー: {val_err}",
                session_id=session_id
            )
        except (TypeError, KeyError, AttributeError, OSError) as e:
            # 想定外の例外時も Safety Fallback で保護（例外から動的に行番号とファイル名を取得）
            return ExtractorSafetyFallback.execute_fallback(
                error_msg=f"想定外のシステムエラー: {e}",
                session_id=session_id
            )
