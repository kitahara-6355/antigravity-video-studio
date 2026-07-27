import os
import sys
import json
import logging
import argparse
from datetime import datetime

try:
    from google.genai.errors import APIError
    from google.api_core.exceptions import GoogleAPIError
except ImportError:
    class APIError(Exception):
        pass
    class GoogleAPIError(Exception):
        pass

logger = logging.getLogger(__name__)

# パスの解決
AGENTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMORY_DIR = os.path.join(AGENTS_DIR, "memory")
BACKEND_DIR = os.path.dirname(AGENTS_DIR)

# インポートエラー（FAIL）を防ぐための sys.path 補正
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from gemini_client_factory import get_gemini_client

class MemoryDistiller:
    def __init__(self):
        self.client = get_gemini_client()
        try:
            from model_registry import get_model
            self.model_name = get_model("supervisor")
        except ImportError:
            self.model_name = "gemini-2.5-flash"

    @staticmethod
    def _resolve_soul_path(agent_name: str) -> str:
        """Soul ファイルのパスを大文字小文字を区別せずに解決する。

        2026-07-26: 従来は agent_name.capitalize() で正規化していたが、
        capitalize() は「先頭を大文字にし残りを小文字化」するため
        "DistillTestAgent" → "Distilltestagent" とファイル名を壊していた。
        Windows は大小を区別しないファイルシステムなので一致していたが、
        Linux(CI) では一致せず「Soul file not found」で早期リターンし、
        テスト4件が失敗していた。

        大小を区別しない照合は仕様（小文字で渡しても正しいファイルを更新する
        テストが存在する）なので、ファイルシステムの挙動に依存せず
        ディレクトリを走査して解決する。
        """
        exact = os.path.join(MEMORY_DIR, f"{agent_name}.json")
        if os.path.exists(exact):
            return exact
        target = f"{agent_name}.json".lower()
        try:
            for entry in os.listdir(MEMORY_DIR):
                if entry.lower() == target:
                    return os.path.join(MEMORY_DIR, entry)
        except OSError:
            pass
        # 見つからない場合はそのままのパスを返す（存在チェックは呼び出し側で行う）
        return exact

    def distill_agent_memory(self, agent_name: str, force: bool = False, max_lessons: int = 20) -> bool:
        """指定されたエージェントの教訓リストを要約（蒸留）し、メモリサイズを定常化する。"""
        # クロスプラットフォーム大文字小文字対応（FS の挙動に依存しない）
        soul_path = self._resolve_soul_path(agent_name)
        normalized_agent_name = os.path.splitext(os.path.basename(soul_path))[0]
        if not os.path.exists(soul_path):
            logger.warning(f"Soul file not found for {agent_name} at {soul_path}")
            return False

        if self.client is None:
            logger.warning(f"Gemini client is not initialized. Skipping distillation for {normalized_agent_name}.")
            return False

        try:
            with open(soul_path, "r", encoding="utf-8") as f:
                soul = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read soul file for {normalized_agent_name}: {e}")
            return False

        lessons = soul.get("lessons", [])
        if not lessons:
            logger.info(f"No lessons to distill for {normalized_agent_name}")
            return False

        if len(lessons) < max_lessons and not force:
            logger.info(f"Lessons count ({len(lessons)}) is below threshold ({max_lessons}) for {normalized_agent_name}. Distillation skipped.")
            return False

        logger.info(f"🔮 Distilling {len(lessons)} lessons for {normalized_agent_name}...")
        
        # レッスン一覧をテキスト化
        lessons_text = "\n".join([f"- {l.get('text', '')}" for l in lessons])

        sys_prompt = f"""
あなたはAIエージェント「{normalized_agent_name}」の知見蒸留エンジンです。
このエージェントは過去の提案却下（REJECT）から、以下の具体的な「失敗の教訓（Lessons Learned）」を蓄積しています。

{lessons_text}

【ミッション】
これらの具体的・個別的な教訓を分析し、今後エージェントが行動指針として遵守すべき、
より抽象度が高く強力な「5つのガイドライン（黄金ルール）」に集約・統合（蒸留）してください。
出力形式は、各ルールを日本語で1行にまとめたプレーンな箇条書きのJSON配列とします。

出力形式 (JSON):
[
    "ガイドライン1: 〇〇を避けるため、常に✕✕すること",
    "ガイドライン2: 〇〇というフィードバックに基づき、✕✕のルールを守ること",
    ...
]
"""

        try:
            from google.genai import types
            response = self.client.models.generate_content(
                model=self.model_name,
                contents="教訓を蒸留してガイドライン化してください。",
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    response_mime_type="application/json",
                    temperature=0.3
                )
            )

            cleaned_text = response.text.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:-3].strip()
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:-3].strip()

            new_rules = json.loads(cleaned_text)
            if not isinstance(new_rules, list):
                raise ValueError("Response is not a JSON list")

            logger.info(f"Successfully generated {len(new_rules)} distilled rules for {normalized_agent_name}")

            # 魂ファイルの更新
            # 旧個別レッスンはアーカイブに退避してデータロスを防ぐ
            archived = soul.setdefault("archived_lessons", [])
            archived.extend(lessons)

            # 新ルールをマージして保存
            distilled = soul.setdefault("distilled_rules", [])
            # 重複を防ぎつつ追加
            for rule in new_rules:
                if rule not in distilled:
                    distilled.append(rule)

            # 蒸留上限を超えないように直近5件程度にトリムするか、あるいは既存のものと再マージも可能。
            # 今回は最大10個のルールに制限してさらにコンテキストの肥大化を防ぐ
            soul["distilled_rules"] = distilled[-10:]

            # アクティブな個別教訓リストをクリーンアップ（リセット）
            soul["lessons"] = []

            # 変更の書き戻し
            with open(soul_path, "w", encoding="utf-8") as f:
                json.dump(soul, f, indent=2, ensure_ascii=False)

            logger.info(f"✨ Distillation completed for {normalized_agent_name}. Archived {len(lessons)} individual lessons.")
            return True

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse LLM rules for {normalized_agent_name}: {e}")
            return False
        except OSError as e:
            logger.error(f"Failed to write soul file for {normalized_agent_name}: {e}")
            return False
        except (APIError, GoogleAPIError, ImportError) as e:
            logger.error(f"API or import error during distillation for {normalized_agent_name}: {e}", exc_info=True)
            return False

def main():
    parser = argparse.ArgumentParser(description="Agent Memory Distiller")
    parser.add_argument("--agent", type=str, required=True, help="Agent name (e.g. Director, Strategist)")
    parser.add_argument("--force", action="store_true", help="Force distillation regardless of lessons count")
    parser.add_argument("--max", type=int, default=20, help="Max lessons count threshold before distillation")
    args = parser.parse_args()

    distiller = MemoryDistiller()
    success = distiller.distill_agent_memory(args.agent, force=args.force, max_lessons=args.max)
    if success:
        print(f"Success: Agent {args.agent} memory distilled.")
    else:
        print(f"Failed or Skipped: Distillation not executed.")

if __name__ == "__main__":
    main()
