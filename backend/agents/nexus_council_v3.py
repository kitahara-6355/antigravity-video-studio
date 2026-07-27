"""nexus_council_v3.py — Nexus-Council 3.0 完全自律合議エンジン

このモジュールは、意図解析、3専門家（Analyst, Strategist, Director）の自律合議、
タスク自動ブレイクダウン、および30秒タイムアウト厳守を実装します。
また、three_point_check に対応する「入力ガードレール」「セーフティフォールバック」「定量的マッピング」を含みます。
"""

import asyncio
import logging
import re
import uuid
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# ==============================================================
# 1. 入力ガードレール (Input Guardrail)
# ==============================================================
class InputGuardrail:
    """入力クエリに対するバリデーションおよびセキュリティ検証を行うガードレール。"""
    
    # 簡易なインジェクション検出パターン
    SUSPICIOUS_PATTERNS = [
        r"System\.exit",
        r"import\s+os",
        r"subprocess\.",
        r"eval\(",
        r"exec\(",
        r"<script>",
    ]

    @classmethod
    def validate_query(cls, query: Optional[str]) -> str:
        """クエリの検証を実行。不適切な場合は ValueError を送出する。"""
        if query is None:
            raise ValueError("クエリが指定されていません。")
            
        # 前後の空白を除去
        query_str = query.strip()
        
        if not query_str:
            raise ValueError("クエリが空、または空白のみです。")
            
        if len(query_str) > 2000:
            raise ValueError("クエリが制限（2000文字）を超えています。")
            
        # 不審なパターンの検出
        for pattern in cls.SUSPICIOUS_PATTERNS:
            if re.search(pattern, query_str, re.IGNORECASE):
                raise ValueError("不審な文字パターンが検出されました。")
                
        return query_str


# ==============================================================
# 2. 定量的マッピング (Quantitative Mapping)
# ==============================================================
class QuantitativeMapping:
    """入力の複雑度に基づいて処理パラメータ（タイムアウト、最大反復数）をマッピングする。"""
    
    COMPLEXITY_KEYWORDS = ["詳細", "分析", "ブレイクダウン", "戦略", "シミュレーション", "根本原因"]

    @classmethod
    def resolve_parameters(cls, query: str) -> Dict[str, Any]:
        """クエリの文字数やキーワードから、タイムアウト時間と max_iterations を定量的に決定する。"""
        length = len(query)
        
        # 基本マッピングの決定
        if length < 20:
            timeout_seconds = 10.0
            max_iterations = 2
        elif length < 100:
            timeout_seconds = 20.0
            max_iterations = 3
        else:
            timeout_seconds = 30.0
            max_iterations = 5
            
        # キーワードによる複雑度ブースト
        has_complex_keyword = any(kw in query for kw in cls.COMPLEXITY_KEYWORDS)
        if has_complex_keyword:
            timeout_seconds = min(30.0, timeout_seconds + 5.0)
            max_iterations = min(5, max_iterations + 1)
            
        return {
            "timeout_seconds": timeout_seconds,
            "max_iterations": max_iterations,
            "complexity_level": "HIGH" if length >= 100 or has_complex_keyword else "NORMAL"
        }


# ==============================================================
# 3. セーフティフォールバック (Safety Fallback)
# ==============================================================
class SafetyFallback:
    """エラーやタイムアウトが発生した際のセーフティネット。"""

    @classmethod
    def generate_response(
        cls, 
        query: str, 
        reason: str, 
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """フォールバック用の定型レスポンスを生成する。"""
        sid = session_id or f"fallback-{uuid.uuid4()}"
        logger.warning(f"Safety fallback triggered (session: {sid}). Reason: {reason}")
        
        # 30秒タイムアウト（あるいはタイムアウト関連の理由）の場合
        if "タイムアウト" in reason or "Timeout" in reason or "timeout" in reason:
            synthesis = (
                f"【タイムアウト自律リカバリ発動】3者合議がタイムアウトに達したため、Analystの意見をスキップし、"
                f"Director主導による2者（Director & Strategist）の合意で強制着火しました。\n"
                f"以下は2者合意によるフォールバック提案です：\n"
                f"- ユーザーのクエリ「{query[:30]}...」に対し、演出および戦略的アプローチを優先して実行します。"
            )
            return {
                "synthesis": synthesis,
                "debate_flow": [
                    {
                        "agent": "Strategist", 
                        "summary": "タイムアウトに伴う代替戦略の提示。"
                    },
                    {
                        "agent": "Director",
                        "summary": "演出・編集面の即時着火決定。"
                    }
                ],
                "tasks": [
                    "タスク1: Director主導による演出構成の即時反映",
                    "タスク2: Strategistによる戦略的マイルストーンの再調整"
                ],
                "session_id": sid,
                "status": "fallback_2_party"
            }
        
        synthesis = (
            f"システムは現在一時的に制限されています（原因: {reason}）。\n"
            f"以下はストラテジストによる基本的なフォールバック提案です：\n"
            f"- ユーザーのクエリ「{query[:30]}...」に対して、優先的にコンテンツの質（演出および視聴維持率）を改善することを推奨します。"
        )
        
        return {
            "synthesis": synthesis,
            "debate_flow": [
                {
                    "agent": "Strategist", 
                    "summary": f"フォールバック提案: {reason}に伴う代替戦略 of 提示。"
                }
            ],
            "tasks": [
                "タスク1: クエリ意図に沿ったコンテンツ品質改善案の再確認",
                "タスク2: 視聴維持率データの取得と分析"
            ],
            "session_id": sid,
            "status": "fallback"
        }

    @classmethod
    def generate_partial_response(
        cls,
        query: str,
        responded_agents: List[str],
        skipped_agents: List[str],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """DS-023: 部分合意フォールバック。応答済みエージェントの意見のみで合意形成する。"""
        sid = session_id or f"partial-{uuid.uuid4()}"
        responded_text = "・".join(responded_agents)
        skipped_text = "・".join(skipped_agents)
        logger.warning(
            f"Partial consensus triggered (session: {sid}). "
            f"Responded: {responded_agents}, Skipped: {skipped_agents}"
        )
        synthesis = (
            f"【部分合意フォールバック発動（DS-023）】\n"
            f"タイムアウトにより一部エージェントが未応答のため、応答済みの{responded_text}による部分合意を形成しました。\n"
            f"スキップされたエージェント: {skipped_text}\n\n"
            f"ユーザーのクエリ「{query[:50]}...」に対し、{responded_text}の意見を統合して提案します。"
        )
        debate_flow = [
            {"agent": agent, "summary": f"{agent} が合議に参加し、提言を行いました。"}
            for agent in responded_agents
        ]
        debate_flow.extend([
            {"agent": agent, "summary": f"{agent} はタイムアウトによりスキップされました。"}
            for agent in skipped_agents
        ])
        return {
            "synthesis": synthesis,
            "debate_flow": debate_flow,
            "tasks": [
                f"タスク1: {responded_text}の合意に基づく即時実行",
                f"タスク2: {skipped_text}の意見を次回合議で補完",
            ],
            "session_id": sid,
            "status": "partial_consensus",
            "quality_warning": True,
            "agent_status": {
                "responded": responded_agents,
                "skipped": skipped_agents,
            },
        }

# ==============================================================
# 4. 意図解析 (Intent Analysis) & 専門家召喚
# ==============================================================
class IntentAnalyzer:
    """クエリの意図を分析し、最適な専門家エージェントの選定を行う。"""

    @classmethod
    def analyze_experts(cls, query: str) -> List[str]:
        """クエリ内のキーワードから、関与すべき専門家のリストを返す。"""
        experts = []
        
        # アナリスト（データ・分析系）
        if any(kw in query for kw in ["分析", "維持率", "データ", "数", "アナリティクス", "CTR", "視聴"]):
            experts.append("Analyst")
            
        # ストラテジスト（戦略・中長期計画系）
        if any(kw in query for kw in ["戦略", "計画", "成長", "中長期", "ロードマップ", "ターゲット"]):
            experts.append("Strategist")
            
        # ディレクター（映像・演出・デザイン系）
        if any(kw in query for kw in ["演出", "編集", "デザイン", "サムネイル", "カット", "テロップ", "音楽"]):
            experts.append("Director")
            
        # 該当がない場合は全員を召喚（完全合議）
        if not experts:
            experts = ["Analyst", "Strategist", "Director"]
            
        return experts


# ==============================================================
# 5. タスク自動ブレイクダウン (Task Breakdown)
# ==============================================================
class TaskBreakdownEngine:
    """合成されたテキストから、実行可能なサブタスクのリストを抽出する。"""

    @classmethod
    def extract_tasks(cls, synthesis: str) -> List[str]:
        """synthesis から箇条書きなどをパースしてタスクリストに変換する。"""
        if not synthesis:
            return ["タスク1: 詳細なアクションプランの策定"]

        tasks = []
        # 改行で分割
        lines = synthesis.split("\n")
        
        # 箇条書きパターン (例: - タスク, * タスク, 1. タスク, タスク1: ...)
        bullet_pattern = re.compile(r"^\s*[-*•]\s*(.+)$")
        numbered_pattern = re.compile(r"^\s*\d+[\.\)]\s*(.+)$")
        task_prefix_pattern = re.compile(r"^\s*[-*•]?\s*(タスク\d+[:：]\s*)(.+)$")

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
                
            # タスクプレフィックスのチェック
            m_prefix = task_prefix_pattern.match(line_str)
            if m_prefix:
                tasks.append(f"タスク: {m_prefix.group(2).strip()}")
                continue
                
            # 箇条書きチェック
            m_bullet = bullet_pattern.match(line_str)
            if m_bullet:
                tasks.append(m_bullet.group(1).strip())
                continue
                
            # 番号付きチェック
            m_num = numbered_pattern.match(line_str)
            if m_num:
                tasks.append(m_num.group(1).strip())
                continue

        # タスクが全く抽出できなかった場合のデフォルトブレイクダウン
        if not tasks:
            tasks = [
                "タスク1: 統合レポートに示された提案事項の具現化",
                "タスク2: 関連する演出/構成案のドラフト作成"
            ]
            
        return tasks


# ==============================================================
# 6. Nexus-Council 3.0 メイン処理 (自律合議 & 30秒タイムアウト)
# ==============================================================
async def run_nexus_council_v3(
    user_query: str,
    session_id: Optional[str] = None,
    mock_adk_runner: Optional[Any] = None
) -> Dict[str, Any]:
    """Nexus-Council 3.0 の完全自律合議を実行する非同期エントリポイント。

    Args:
        user_query: ユーザーからの質問・課題
        session_id: セッションID（省略時は自動生成）
        mock_adk_runner: テスト用のADK Runnerモック（省略時は本番動作）

    Returns:
        合議結果のレスポンス辞書。タイムアウト時はセーフティフォールバックを返す。
    """
    sid = session_id or str(uuid.uuid4())
    
    try:
        # Step 1: 入力ガードレール
        validated_query = InputGuardrail.validate_query(user_query)
        
        # Step 2: 定量的マッピングの決定
        params = QuantitativeMapping.resolve_parameters(validated_query)
        timeout_seconds = params["timeout_seconds"]
        max_iterations = params["max_iterations"]
        
        # Step 3: タイムアウト厳守の非同期ラッパー + DS-023 段階的フォールバック
        result = None
        agent_status = {exp: "pending" for exp in IntentAnalyzer.analyze_experts(validated_query)}
        try:
            result = await asyncio.wait_for(
                _execute_council_flow(validated_query, sid, max_iterations, mock_adk_runner, agent_status),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            # DS-023: 部分合意フォールバック — 応答済みエージェントの意見で合意形成
            responded = [k for k, v in agent_status.items() if v == "responded"]
            skipped = [k for k, v in agent_status.items() if v != "responded"]
            
            if responded:
                # 部分結果が存在する場合は部分合意で返す
                result = SafetyFallback.generate_partial_response(
                    query=validated_query,
                    responded_agents=responded,
                    skipped_agents=skipped,
                    session_id=sid,
                )
            else:
                result = SafetyFallback.generate_response(
                    query=validated_query,
                    reason=f"タイムアウト超過（{timeout_seconds}秒）。全エージェント未応答。",
                    session_id=sid
                )
            
        # 決定事項の自動抽出 ＆ VerifiedFacts 記録フックの実行
        try:
            from agents.memory.council_decision_extractor import CouncilDecisionExtractor
            CouncilDecisionExtractor.process_and_record(result)
        except Exception as extractor_err:
            logger.error(f"VerifiedFacts への決定事項自動記録に失敗しました: {extractor_err}", exc_info=True)
            
        return result
            
    except ValueError as val_err:
        # ガードレール違反等の明示的バリデーションエラー
        logger.error(f"Guardrail check failed: {val_err}")
        raise val_err
    except (RuntimeError, ValueError, KeyError, TypeError, ImportError, AttributeError, NameError) as e:
        # その他の想定外エラーに対するフォールバック
        logger.error(f"Unexpected error in run_nexus_council_v3: {e}", exc_info=True)
        fallback_res = SafetyFallback.generate_response(
            query=user_query,
            reason=f"内部例外: {str(e)}",
            session_id=sid
        )
        # 例外時もフォールバック結果を記録
        try:
            from agents.memory.council_decision_extractor import CouncilDecisionExtractor
            CouncilDecisionExtractor.process_and_record(fallback_res)
        except Exception as extractor_err:
            logger.error(f"VerifiedFacts への決定事項自動記録に失敗しました（例外フォールバック）: {extractor_err}", exc_info=True)
        return fallback_res


async def _execute_council_flow(
    query: str,
    session_id: str,
    max_iterations: int,
    mock_adk_runner: Optional[Any] = None,
    agent_status: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """自律合議およびブレイクダウン処理のメインフロー。
    
    DS-023: agent_status辞書を受け取り、各エージェントの応答状態を追跡する。
    """
    
    # 1. 意図解析による関与専門家の決定
    experts = IntentAnalyzer.analyze_experts(query)
    
    # 2. ADK エージェントのインポートと実行（モックまたは本番）
    if mock_adk_runner is not None:
        # テスト等でモックが渡された場合はそれを使用
        synthesis, debate_flow = await mock_adk_runner(query, experts, max_iterations)
        # DS-023: モック実行時も全専門家を responded に更新
        if agent_status is not None:
            for exp in experts:
                agent_status[exp] = "responded"
    else:
        # 本番動作: google-adk をインポートして実行
        try:
            from google.adk.runners import InMemoryRunner
            from google.adk.agents.run_config import RunConfig
            from google.genai import types as genai_types
            from agents.council_graph import _build_council_agents
        except ImportError as imp_err:
            # ADK がない場合のセーフティフォールバック
            return SafetyFallback.generate_response(
                query=query,
                reason=f"Google ADK ライブラリ不在: {imp_err}",
                session_id=session_id
            )
            
        root_agent, analyst, strategist, director = _build_council_agents()
        
        # 意図解析に基づいて召喚された専門家に絞り込むための、プロンプトの動的追加
        summoned_text = "、".join(experts)
        modified_query = (
            f"【今回の召喚専門家: {summoned_text}】\n"
            f"ユーザー指示: {query}"
        )
        
        runner = InMemoryRunner(agent=root_agent, app_name="antigravity_council")
        
        initial_state = {
            "session_id": session_id,
            "council_mode": "post_production",
            "findings": {},
        }
        
        await runner.session_service.create_session(
            app_name="antigravity_council",
            user_id="council_user",
            session_id=session_id,
            state=initial_state,
        )
        
        run_config = RunConfig(max_llm_calls=max_iterations)
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=modified_query)],
        )
        
        synthesis = ""
        async for event in runner.run_async(
            user_id="council_user",
            session_id=session_id,
            new_message=content,
            run_config=run_config,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        synthesis += part.text
                        
        if not synthesis:
            updated_session = await runner.session_service.get_session(
                app_name="antigravity_council",
                user_id="council_user",
                session_id=session_id,
            )
            synthesis = updated_session.state.get("council_synthesis", "")
            
        if not synthesis:
            raise RuntimeError("ADKからの応答が空でした。")
            
        # debate_flow の疑似的な構築 (ADKのセッション履歴などから抽出)
        # 本番ではセッション履歴から構築、簡易的には各専門家のstanceを反映
        debate_flow = []
        for exp in experts:
            debate_flow.append({
                "agent": exp,
                "summary": f"{exp} が合議に参加し、提言を行いました。"
            })
            
    # 3. タスク自動ブレイクダウン
    tasks = TaskBreakdownEngine.extract_tasks(synthesis)
    
    return {
        "synthesis": synthesis,
        "debate_flow": debate_flow,
        "tasks": tasks,
        "session_id": session_id,
        "status": "success"
    }
