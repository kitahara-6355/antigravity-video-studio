"""
AdvisorGate — Claude Code Advisor Tool の Antigravity 移植版

Claude Code の流出コードから判明した「内部二重検証」パターンを実装。
Worker が提案した内容を、独立した Reviewer エージェントが検証し、
検証に通過しない限り実行させない「ゲートキーパー」。

Claude Code における Advisor Tool の動作:
    1. Worker が「これからこの操作を実行する」と宣言
    2. Advisor に「副作用はないか？」「Verified Facts と矛盾しないか？」を照会
    3. Advisor が承認した場合のみ実行
    4. 不承認の場合は具体的な修正コマンドを返す

Antigravity での適用対象:
    - SmartCut の構成提案（③）
    - 最終レンダリング前の品質確認（⑦）
    - YouTube メタデータ生成（⑧）
    - Council の戦略決定

設計方針:
    - SelfReviewEngine（実行後レビュー）と対を成す「実行前レビュー」
    - Verified Facts との自動照合
    - Gemini Flash でコスト効率を維持
"""

import json
import logging
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Model Registry (SSoT: model_config.json)
try:
    from model_registry import get_model
except Exception as e:
    logger.warning(f"model_registryの読み込み失敗 (フォールバックを使用): {e}")
    def get_model(task): return "gemini-2.5-flash"

logger = logging.getLogger(__name__)

# ============================================================
# 定数
# ============================================================
DEFAULT_REVIEWER_MODEL = get_model("quality_gate")


# ============================================================
# データ構造
# ============================================================

class Verdict(Enum):
    """Advisor の判定結果"""
    APPROVED = "approved"               # 実行許可
    APPROVED_WITH_WARNINGS = "approved_with_warnings"  # 警告付き許可
    REJECTED = "rejected"               # 実行拒否（修正必要）
    NEEDS_HUMAN_REVIEW = "needs_human_review"  # 人間の判断が必要


@dataclass
class AdvisorVerdict:
    """Advisor の判定結果"""
    verdict: str            # Verdict の値
    confidence: float       # 0.0-1.0
    reasoning: str          # 判定の理由
    warnings: List[str] = field(default_factory=list)
    corrections: List[Dict] = field(default_factory=list)  # 修正コマンド
    verified_facts_conflicts: List[str] = field(default_factory=list)
    reviewed_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        # verdict が Enum の場合は文字列に変換する
        if isinstance(self.verdict, Enum):
            self.verdict = self.verdict.value
        elif not isinstance(self.verdict, str):
            self.verdict = str(self.verdict)


# ============================================================
# メインクラス
# ============================================================

class AdvisorGate:
    """
    実行前二重検証ゲートキーパー。

    Usage:
        gate = AdvisorGate()

        verdict = await gate.review_before_execution(
            task_description="SmartCut で20分版の構成を決定",
            proposed_action={
                "action": "smart_cut",
                "segments_count": 45,
                "target_minutes": 20,
            },
            definition_of_done="20分±2分の構成が生成され、重要シーンが含まれること",
        )

        if verdict.verdict == "approved":
            # 実行
            result = execute_smart_cut(...)
        elif verdict.verdict == "rejected":
            # 修正を適用
            for correction in verdict.corrections:
                apply_correction(correction)
    """

    def __init__(self, reviewer_model: str = DEFAULT_REVIEWER_MODEL):
        self.reviewer_model = reviewer_model
        self.review_history: List[AdvisorVerdict] = []

    async def review_before_execution(
        self,
        task_description: str,
        proposed_action: Dict,
        definition_of_done: str,
        context: Optional[Dict] = None,
    ) -> AdvisorVerdict:
        """
        実行前レビューを実行。

        Args:
            task_description: タスクの説明
            proposed_action: 実行しようとしているアクション
            definition_of_done: 成功条件（TaskContract 由来）
            context: 追加コンテキスト

        Returns:
            AdvisorVerdict
        """
        logger.info(f"🔍 AdvisorGate レビュー開始: {task_description[:60]}...")

        # Step 1: Verified Facts との照合
        fact_conflicts = self._check_verified_facts(proposed_action)

        # Step 2: LLM によるレビュー
        llm_verdict = await self._llm_review(
            task_description, proposed_action, definition_of_done, context
        )

        # Step 3: 最終判定
        verdict = self._synthesize_verdict(llm_verdict, fact_conflicts)

        # 履歴に記録
        self.review_history.append(verdict)

        # ログ出力
        emoji = {
            "approved": "✅",
            "approved_with_warnings": "⚠️",
            "rejected": "❌",
            "needs_human_review": "👤",
        }.get(verdict.verdict, "❓")

        logger.info(
            f"{emoji} AdvisorGate 判定: {verdict.verdict} "
            f"(confidence={verdict.confidence:.2f}) — {verdict.reasoning[:80]}"
        )

        return verdict

    # ============================================================
    # Step 1: Verified Facts との照合
    # ============================================================

    def _check_verified_facts(self, proposed_action: Dict) -> List[str]:
        """
        Verified Facts と矛盾がないかチェック。

        Returns:
            矛盾するファクトのリスト
        """
        conflicts = []
        try:
            from agents.memory.verified_facts import verified_facts_store
            import re

            # proposed_action の値をすべて文字列として再帰的に収集
            def extract_values(val) -> List[str]:
                res = []
                if isinstance(val, dict):
                    for k, v in val.items():
                        res.append(str(k))
                        res.extend(extract_values(v))
                elif isinstance(val, (list, tuple, set)):
                    for item in val:
                        res.extend(extract_values(item))
                else:
                    res.append(str(val))
                return res

            action_values = extract_values(proposed_action)
            action_text = " ".join(action_values).lower()

            # 同義語マッピング（日・英のブリッジ用）
            synonyms = {
                "タイトル": ["title"],
                "カット": ["cut", "segment"],
                "解像度": ["resolution"],
                "画質": ["quality"],
                "音量": ["volume", "audio"]
            }

            # 「回避」カテゴリのファクトと照合
            preference_facts = verified_facts_store.get_facts_by_category("preference")
            for fact in preference_facts:
                content_lower = fact.content.lower()

                # 「避ける」「禁止」「NG」などのネガティブファクトと照合
                negative_keywords = ["避ける", "禁止", "ng", "使わない", "却下", "avoid", "restrict", "ban", "don't"]
                if any(kw in content_lower for kw in negative_keywords):
                    # ファクトからキーワードを抽出（日本語の漢字・カタカナ、英語の単語）
                    raw_words = re.findall(r'[一-龠𠮷]+|[ァ-ヴー]+|[a-zA-Z0-9_]+', content_lower)
                    
                    stop_words = {
                        "避ける", "禁止", "ng", "使わない", "却下", "avoid", "restrict", "ban", "don", "t", "not", "no",
                        "する", "しない", "こと", "用", "テスト", "ファクト", "の", "を", "は", "が", "に", "と", "で",
                        "避", "禁", "防"
                    }
                    
                    keywords = [w for w in raw_words if w not in stop_words]
                    if not keywords:
                        continue

                    # 抽出したキーワードのうち、アクションテキストに部分一致する単語の数をカウント
                    overlap_count = 0
                    for kw in keywords:
                        aliases = [kw] + synonyms.get(kw, [])
                        if any(alias in action_text for alias in aliases):
                            overlap_count += 1

                    # 2つ以上のキーワードが一致した、あるいはキーワードが1つのみ抽出されそれが一致した場合は衝突とする
                    if overlap_count >= 2 or (len(keywords) == 1 and overlap_count == 1):
                        conflicts.append(
                            f"Verified Fact と矛盾の可能性: {fact.content}"
                        )

        except ImportError as ie:
            logger.warning(f"Verified Facts 読み込み失敗 (ImportError): {ie}")
        except json.JSONDecodeError as jde:
            logger.warning(f"Verified Facts 読み込み失敗 (JSONDecodeError): {jde}")
        except TypeError as te:
            logger.warning(f"Verified Facts 提案シリアライズ失敗 (TypeError): {te}")
        except OSError as oe:
            logger.warning(f"Verified Facts ファイルアクセス失敗 (OSError): {oe}")
        except re.error as re_err:
            logger.warning(f"Verified Facts チェック中の正規表現処理でエラーが発生しました (re.error): {re_err}", exc_info=True)
        except (KeyError, IndexError) as struct_err:
            logger.warning(f"Verified Facts チェック中のデータ構造エラーが発生しました (KeyError/IndexError): {struct_err}", exc_info=True)
        except (AttributeError, ValueError) as e:
            logger.warning(f"Verified Facts チェック中に予期せぬエラーが発生しました: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Verified Facts チェック中に未知のエラーが発生しました: {e}", exc_info=True)
            try:
                from agents.memory.technical_debt import technical_debt_store
                technical_debt_store.register_debt(
                    category="ACCEPTED_SAFETY",
                    file_path="backend/agents/advisor_gate.py",
                    line_number=253,
                    pattern="except Exception as e: Verified Facts チェックの最終フォールバック",
                    cause_pattern="DP-02",
                    fix_pattern="特定の例外クラスを明示的にキャッチするようにリファクタリング",
                    registered_by="T-batch_e438ee-bug_hunter-008",
                    notes=f"システムクラッシュ防止のための最終フォールバック: {str(e)[:100]}"
                )
            except (ImportError, AttributeError, KeyError) as e_td:
                logger.warning(f"技術負債の自動登録に失敗しました: {e_td}")

        return conflicts

    # ============================================================
    # Step 2: LLM レビュー
    # ============================================================

    async def _llm_review(
        self,
        task_description: str,
        proposed_action: Dict,
        definition_of_done: str,
        context: Optional[Dict],
    ) -> Dict:
        """LLM による独立レビュー"""
        # Step 1: 依存関係のインポートを安全に行う
        try:
            from google.genai import types
            from google.genai.errors import APIError
            has_genai = True
        except ImportError:
            has_genai = False
            APIError = None  # placeholder

        if not has_genai:
            logger.warning("AdvisorGate LLM レビュー スキップ: google-genai 未インストール")
            return {
                "verdict": "approved_with_warnings",
                "confidence": 0.5,
                "reasoning": "google-genai未インストールののためLLMレビューをスキップし、警告付きでフォールバック許可します",
                "warnings": ["google-genaiがインストールされていません"],
                "corrections": [],
            }

        # キャッチする例外リストを動的に構築して UnboundLocalError を回避
        # 技術負債（TD-1224）の指摘に基づき、AttributeError, KeyError, IndexError もキャッチ対象に含める
        catchable_exceptions = [ValueError, RuntimeError, TypeError, AttributeError, KeyError, IndexError]
        if APIError is not None:
            catchable_exceptions.append(APIError)

        try:
            from gemini_client_factory import get_gemini_client

            client = get_gemini_client()
            if client is None:
                logger.warning("AdvisorGate LLM レビュー スキップ: GOOGLE_API_KEY 未設定")
                return {
                    "verdict": "approved_with_warnings",
                    "confidence": 0.5,
                    "reasoning": "GOOGLE_API_KEY未設定のためLLMレビューをスキップし、警告付きでフォールバック許可します",
                    "warnings": ["GOOGLE_API_KEYが設定されていません"],
                    "corrections": [],
                }

            # Verified Facts コンテキストを取得
            verified_context = ""
            try:
                from agents.memory.verified_facts import verified_facts_store
                verified_context = verified_facts_store.get_facts_for_context(max_tokens=1000)
            except ImportError:
                pass

            # proposed_action の JSON 化（TypeError 対策）
            try:
                action_json = json.dumps(proposed_action, ensure_ascii=False, indent=2)
            except TypeError as te:
                logger.warning(f"proposed_action のシリアライズ失敗 (TypeError): {te}")
                action_json = str(proposed_action)

            prompt = f"""あなたは品質レビュアー（Advisor）です。
以下のタスクと提案アクションを検証し、実行して問題ないか判定してください。

## タスク
{task_description}

## 提案アクション
{action_json}

## 成功条件（Definition of Done）
{definition_of_done}

{f'## 検証済みファクト（矛盾チェック用）' + chr(10) + verified_context if verified_context else ''}

{f'## 追加コンテキスト' + chr(10) + json.dumps(context, ensure_ascii=False, indent=2) if context else ''}

## 判定基準
1. 提案は成功条件を満たす可能性が高いか？
2. 検証済みファクトと矛盾しないか？
3. 致命的な副作用のリスクはないか？
4. より効率的な代替案はないか？

## 出力形式（JSON）
{{
    "verdict": "approved" | "approved_with_warnings" | "rejected" | "needs_human_review",
    "confidence": 0.0-1.0,
    "reasoning": "判定理由",
    "warnings": ["警告1", "警告2"],
    "corrections": [{{"field": "修正対象", "current": "現在値", "suggested": "提案値", "reason": "理由"}}]
}}"""

            response = client.models.generate_content(
                model=self.reviewer_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,  # 低温度で一貫性を重視
                ),
            )

            # response.text が None または空文字の場合のハンドリング
            if not response or not response.text:
                raise ValueError("API returned empty response text")

            return json.loads(response.text)

        except json.JSONDecodeError as jde:
            logger.error(f"AdvisorGate LLM 応答パースエラー (JSONDecodeError): {jde}")
            return {
                "verdict": "approved_with_warnings",
                "confidence": 0.5,
                "reasoning": f"LLMレビュー応答パース失敗のためフォールバック許可: {str(jde)[:100]}",
                "warnings": ["AdvisorGate LLMレビュー応答の解析に失敗しました"],
                "corrections": [],
            }
        except Exception as e:
            # catchable_exceptions 内の BaseException を継承するクラスだけを抽出する（モックやインポート汚染対策）
            safe_exceptions = [
                exc for exc in catchable_exceptions
                if isinstance(exc, type) and issubclass(exc, BaseException)
            ]
            if type(e) in safe_exceptions or any(isinstance(e, exc) for exc in safe_exceptions):
                logger.error(f"AdvisorGate LLM レビュー致命的エラー ({type(e).__name__}): {e}", exc_info=True)
                # レビュー失敗時は警告付き許可（安全なフォールバック）
                return {
                    "verdict": "approved_with_warnings",
                    "confidence": 0.5,
                    "reasoning": f"LLMレビュー失敗のためフォールバック許可: {str(e)[:100]}",
                    "warnings": ["AdvisorGate LLMレビューが実行できませんでした"],
                    "corrections": [],
                }
            
            # 予期せぬ致命的エラーの最終フォールバック
            logger.error(f"AdvisorGate LLM レビューで予期せぬ致命的エラーが発生しました: {e}", exc_info=True)
            try:
                from agents.memory.technical_debt import technical_debt_store
                technical_debt_store.register_debt(
                    category="ACCEPTED_SAFETY",
                    file_path="backend/agents/advisor_gate.py",
                    line_number=403,
                    pattern="except Exception as e: LLM レビューの最終フォールバック",
                    cause_pattern="DP-02",
                    fix_pattern="特定の例外クラスを明示的にキャッチするようにリファクタリング",
                    registered_by="T-batch_e438ee-bug_hunter-008",
                    notes=f"システムクラッシュ防止のための最終フォールバック: {str(e)[:100]}"
                )
            except (ImportError, AttributeError, KeyError) as e_td:
                logger.warning(f"技術負債の自動登録に失敗しました: {e_td}")
            return {
                "verdict": "approved_with_warnings",
                "confidence": 0.5,
                "reasoning": f"LLMレビューで予期せぬ致命的エラー発生のためフォールバック許可: {str(e)[:100]}",
                "warnings": ["AdvisorGate LLMレビューが実行できませんでした"],
                "corrections": [],
            }

    # ============================================================
    # Step 3: 最終判定の合成
    # ============================================================

    def _synthesize_verdict(
        self, llm_verdict: Dict, fact_conflicts: List[str]
    ) -> AdvisorVerdict:
        """LLM レビューと Verified Facts チェックの結果を統合"""
        # llm_verdict の型安全性を保証
        if not isinstance(llm_verdict, dict):
            logger.error(f"llm_verdict が辞書型ではありません: {type(llm_verdict)}")
            llm_verdict = {}

        verdict_str = llm_verdict.get("verdict", "approved_with_warnings")
        confidence = llm_verdict.get("confidence", 0.5)

        # Verified Facts の矛盾がある場合は判定を厳しくする
        if fact_conflicts:
            if verdict_str == "approved":
                verdict_str = "approved_with_warnings"
            confidence = min(confidence, 0.6)

        return AdvisorVerdict(
            verdict=verdict_str,
            confidence=confidence,
            reasoning=llm_verdict.get("reasoning", ""),
            warnings=llm_verdict.get("warnings", []),
            corrections=llm_verdict.get("corrections", []),
            verified_facts_conflicts=fact_conflicts,
        )

    # ============================================================
    # ユーティリティ
    # ============================================================

    def get_review_stats(self) -> Dict:
        """レビュー統計"""
        total = len(self.review_history)
        if total == 0:
            return {"total_reviews": 0}

        verdicts = {}
        for v in self.review_history:
            verdicts[v.verdict] = verdicts.get(v.verdict, 0) + 1

        confidences = []
        for v in self.review_history:
            try:
                confidences.append(float(v.confidence))
            except (TypeError, ValueError):
                confidences.append(0.5)

        return {
            "total_reviews": total,
            "verdicts": verdicts,
            "avg_confidence": round(
                sum(confidences) / total, 2
            ),
            "rejection_rate": round(
                verdicts.get("rejected", 0) / total * 100, 1
            ),
        }

    def should_review(self, task_type: str) -> bool:
        """レビューが必要なタスクタイプか判定"""
        # 重要なステージのみレビュー（コスト最適化）
        reviewable = {
            "smart_cut",        # ③ 構成決定
            "render_final",     # ⑦ 最終レンダリング
            "youtube_metadata", # ⑧ YouTube最適化
            "council_strategy", # Council の戦略決定
        }
        return task_type in reviewable


# ============================================================
# シングルトンインスタンス
# ============================================================
advisor_gate = AdvisorGate()
