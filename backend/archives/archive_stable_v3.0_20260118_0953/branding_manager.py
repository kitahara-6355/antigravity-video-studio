import os
import json
import time
import logging
from typing import Any, Dict, List, Optional, Union

# ロガーの設定
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from branding.history_manager import history_manager, EventType

from agents.context_resolver import ContextResolver

# 意思決定記録システム（自動進化連携）
try:
    from decision_logger import decision_logger
except ImportError:
    decision_logger = None  # 後方互換性

BRANDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "branding")
CONSTITUTION_PATH = os.path.join(BRANDING_DIR, "constitution.json")
# ファイルI/O安全規約（UTF-8破損問題）に対応するため、適切なエンコーディングで処理する。
STRATEGY_PATH = os.path.join(BRANDING_DIR, "strategy.json")
USER_MODEL_PATH = os.path.join(BRANDING_DIR, "user_model.json")
# 字幕データのパス（プロジェクトルートからの相対パスを想定）
SUBTITLES_PATH = os.path.join(os.path.dirname(BRANDING_DIR), "src", "segments_a_plus_plus.json")

class BrandingManager:
    def __init__(self) -> None:
        """BrandingManagerを初期化し、各種設定ファイルをロードします。"""
        self.constitution = self._load_json(CONSTITUTION_PATH)
        self.strategy = self._load_json(STRATEGY_PATH)
        self.user_model = self._load_json(USER_MODEL_PATH)
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.current_vision = "" # 現在のセッションのこだわり/想い

    def _load_json(self, path: str) -> dict:
        """指定されたパスからJSONデータをロードします。

        Args:
            path (str): ロードするJSONファイルのパス。

        Returns:
            dict: ロードされたJSONデータ。エラー発生時または存在しない場合は空の辞書。
        """
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError as e:
            logger.warning(f"File not found: {path} (Using empty dict/default config)")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error loading {path}: Invalid JSON format: {e}", exc_info=True)
            return {}
        except OSError as e:
            logger.error(f"Error loading {path}: OS error: {e}", exc_info=True)
            return {}

    def _save_json(self, path: str, data: dict) -> None:
        """指定されたJSONデータをファイルに保存します。

        Args:
            path (str): 保存先のファイルパス。
            data (dict): 保存するデータ。
        """
        try:
            dir_name = os.path.dirname(path)
            if dir_name and not os.path.exists(dir_name):
                os.makedirs(dir_name, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except TypeError as e:
            logger.error(f"Error saving {path}: Type error during JSON serialization: {e}", exc_info=True)
        except OSError as e:
            logger.error(f"Error saving {path}: OS error during write: {e}", exc_info=True)
        except ValueError as e:
            logger.error(f"Error saving {path}: Value error: {e}", exc_info=True)

    def get_context_block(self) -> str:
        """AIのシステムプロンプトに注入するためのブランド、戦略、およびユーザーコンテキストのテキストブロックを構築します。

        Returns:
            str: 構築されたコンテキストのテキストブロック。
        """
        c = self.constitution
        s = self.strategy
        u = self.user_model
        
        # Get Collaborative Context
        admin = u.get('profiles', {}).get('admin', {})
        owner = u.get('profiles', {}).get('owner', {})
        tech_rank = admin.get('ranks', {}).get('tech_rank', {})
        biz_rank = owner.get('ranks', {}).get('biz_rank', {})
        collab = u.get('collaborative_settings', {})
        
        # Build the context string
        context = f"""
        ## 🛡️ BRAND CONSTITUTION (Absolute Rules)
        - Channel: {c.get('channel_name')}
        - Target Audience: {c.get('target_audience')}
        - Personality/Tone: {c.get('brand_personality', {}).get('tone')}
        - Visual Style: {c.get('visual_identity', {}).get('style_prompt')}
        
        ## ♟️ STRATEGIC MISSION
        - Phase: {s.get('current_phase')}
        - Current Goal: {s.get('current_mission', {}).get('focus')} -> Target: {s.get('current_mission', {}).get('target_value')}
        - Strategic Advice: "{s.get('current_mission', {}).get('advice')}"
        
        ## 👤 COLLABORATIVE PROFILE (Trinity 2.0)
        - Studio Name: {u.get('name')}
        - 🛠️ Admin ({admin.get('name')}): Tech Rank: {tech_rank.get('level')} (XP: {tech_rank.get('xp')})
        - 🎭 Owner ({owner.get('name')}): Biz Rank: {biz_rank.get('level')} (XP: {biz_rank.get('xp')})
        - 🤖 Collaborative Auto-Pilot: {collab.get('auto_pilot_ratio', 0.9) * 100}%
        ## 🧠 PHILOSOPHY HERITAGE (Soul Narrative)
        {self.get_philosophies_context()}
        """
        return context
    
    def get_philosophies_context(self) -> str:
        """過去の全哲学エントリーをコンテキストとして取得します（憲法 5.2 哲学の深化）。

        Returns:
            str: 哲学履歴や最新の学びを含むコンテキスト文字列。
        """
        EVOLUTION_LOG_PATH = os.path.join(BRANDING_DIR, "evolution_log.json")
        evo_log = self._load_json(EVOLUTION_LOG_PATH)
        
        if not evo_log:
            return "- 哲学履歴: 初心者からスタート"
        
        philosophies = evo_log.get("philosophies", [])
        entries = evo_log.get("entries", [])
        
        # 哲学履歴を構築
        context_lines = []
        
        # 統合哲学（最新）
        integrated = evo_log.get("integrated_philosophy")
        if integrated:
            context_lines.append(f"- 🎯 統合哲学: 「{integrated}」")
        
        # 過去の哲学（最新から3件）
        if philosophies:
            context_lines.append(f"- 📚 哲学履歴 ({len(philosophies)}件):")
            for i, p in enumerate(philosophies[-3:], 1):
                context_lines.append(f"  {i}. 「{p.get('philosophy', p) if isinstance(p, dict) else p}」")
        
        # 最新の学び
        if entries:
            latest = entries[-1]
            context_lines.append(f"- 🔮 最新の学び: {latest.get('summary', '')}")
        
        return "\n        ".join(context_lines) if context_lines else "- 哲学履歴: 初心者からスタート"

    def get_deep_context(self) -> str:
        """現在の動画字幕データとユーザーのこだわり/ビジョンを取得します。

        Returns:
            str: 解決された詳細コンテキスト。
        """
        return ContextResolver.get_deep_context_block(SUBTITLES_PATH, self.current_vision)

    def update_user_rank(self, rank_type: str, amount: int = 10) -> None:
        """特定のプロファイルで指定されたランクのXPを更新します。
        tech_rank -> admin, biz_rank -> owner

        Args:
            rank_type (str): 更新するランクの種類 ("tech_rank" または "biz_rank")。
            amount (int, optional): 加算するXP量。デフォルトは 10。
        """
        profile_key = "admin" if rank_type == "tech_rank" else "owner"
        profiles = self.user_model.get("profiles", {})
        
        if profile_key in profiles:
            ranks = profiles[profile_key].get("ranks", {})
            if rank_type in ranks:
                current_xp = ranks[rank_type].get('xp', 0)
                new_xp = current_xp + amount
                ranks[rank_type]['xp'] = new_xp
                self._save_json(USER_MODEL_PATH, self.user_model)
                
                # Log to History
                history_manager.log_event(EventType.STATUS_CHANGE, {
                    "rank_type": rank_type,
                    "profile": profile_key,
                    "old_xp": current_xp,
                    "new_xp": new_xp,
                    "change": amount
                })
                
                # Recalculate Automation Settings if Tech Rank changed
                if rank_type == "tech_rank":
                    self._recalculate_automation_level(new_xp)

    def evolve_constitution(self, success_event: dict) -> None:
        """AIパーソナリティ自己進化ロジック（Phase 26）。
        ユーザーの選択に基づいて憲法を更新します。

        Args:
            success_event (dict): 成功イベントに関する辞書。
        """
        try:
            # 成功事例の要約（タイトル、コンセプト名など）
            event_summary = f"Success: {success_event.get('type')} - {success_event.get('value')}"
            
            # ソウル・ナラティブの更新（簡易版）
            self.constitution['evolution_vision'] += f"\n- {event_summary}"
            
            # 特定のキーワードが選ばれた場合、ブランドキーワードに追加
            new_keyword = success_event.get('keyword')
            if new_keyword and new_keyword not in self.constitution['brand_personality']['keywords']:
                self.constitution['brand_personality']['keywords'].append(new_keyword)
                
            self._save_json(CONSTITUTION_PATH, self.constitution)
            logger.info(f"Constitution evolved: {event_summary}")
            
            # 履歴にも記録
            history_manager.log_event(EventType.CONTENT_EXPORT, {
                "evolution": event_summary,
                "detail": success_event
            })
            
        except (AttributeError, KeyError, TypeError, OSError, ValueError, RuntimeError) as e:
            logger.error(f"Evolution error: {e}", exc_info=True)

    def sync_decisions_to_constitution(self) -> dict:
        """意思決定の傾向をconstitution.jsonに自動反映します（憲法10条）。

        - 3回以上却下されたパターン → content_policyに追加
        - 頻出の承認タグ → keywordsに追加

        Returns:
            dict: 同期の結果を示す辞書。
        """
        if not decision_logger:
            logger.warning("decision_logger not available, skipping sync")
            return {"synced": False, "reason": "decision_logger not imported"}
        
        try:
            preferences = decision_logger.get_director_preferences()
            changes_made = []
            
            # === 却下パターンからcontent_policyに追加 ===
            rejection_patterns = preferences.get('こだわり（却下傾向）', {})
            for pattern, count in rejection_patterns.items():
                if count >= 3:  # 3回以上却下されたパターン
                    new_policy = f"Avoid '{pattern}' adjustments; conflicts with director's preferences."
                    if new_policy not in self.constitution.get('content_policy', []):
                        if 'content_policy' not in self.constitution:
                            self.constitution['content_policy'] = []
                        self.constitution['content_policy'].append(new_policy)
                        changes_made.append(f"content_policy: +'{pattern}'")
                        logger.info(f"📜 Constitution evolved: Added policy for '{pattern}'")
            
            # === 承認パターンからkeywordsに追加 ===
            approval_patterns = preferences.get('好み（承認傾向）', {})
            for keyword, count in approval_patterns.items():
                if count >= 5:  # 5回以上承認されたキーワード
                    if keyword not in self.constitution.get('brand_personality', {}).get('keywords', []):
                        if 'brand_personality' not in self.constitution:
                            self.constitution['brand_personality'] = {}
                        if 'keywords' not in self.constitution['brand_personality']:
                            self.constitution['brand_personality']['keywords'] = []
                        self.constitution['brand_personality']['keywords'].append(keyword)
                        changes_made.append(f"keywords: +'{keyword}'")
                        logger.info(f"📜 Constitution evolved: Added keyword '{keyword}'")
            
            # 変更があれば保存
            if changes_made:
                self._save_json(CONSTITUTION_PATH, self.constitution)
                history_manager.log_event(EventType.SYSTEM_EVENT, {
                    "event": "CONSTITUTION_AUTO_EVOLUTION",
                    "changes": changes_made,
                    "source": "decision_logger"
                })
            
            return {
                "synced": True,
                "changes": changes_made,
                "rejection_patterns": rejection_patterns,
                "approval_patterns": approval_patterns
            }
            
        except (AttributeError, KeyError, TypeError, RuntimeError, OSError, ValueError) as e:
            logger.error(f"Decision sync error: {e}", exc_info=True)
            return {"synced": False, "error": str(e)}

    def auto_evolve_all(self) -> dict:
        """全ての自動進化処理を実行します（定期実行用）。

        1. 意思決定からconstitution.jsonを更新
        2. evolution_logをdecision_loggerに同期
        3. 哲学の統合チェック

        Returns:
            dict: 各自動進化処理の結果を含む辞書。
        """
        results = {
            "decision_sync": None,
            "soul_narrative_sync": None,
            "philosophy_check": None
        }
        
        # 1. 意思決定 → constitution.json
        results["decision_sync"] = self.sync_decisions_to_constitution()
        
        # 2. decision_logger → evolution_log
        if decision_logger:
            try:
                results["soul_narrative_sync"] = decision_logger.sync_to_soul_narrative()
            except (AttributeError, RuntimeError) as e:
                logger.error(f"Soul narrative sync error: {e}", exc_info=True)
                results["soul_narrative_sync"] = {"error": str(e)}
        
        # 3. 哲学の統合チェック（10件ごと）
        evo_log = self.get_evolution_log()
        philosophy_count = len(evo_log.get("philosophies", []))
        if philosophy_count > 0 and philosophy_count % 10 == 0:
            self._integrate_philosophies(evo_log)
            self.save_evolution_log(evo_log)
            results["philosophy_check"] = {"integrated": True, "count": philosophy_count}
        else:
            results["philosophy_check"] = {"integrated": False, "count": philosophy_count}
        
        logger.info(f"🔄 Auto-evolution complete: {results}")
        return results

    def _recalculate_automation_level(self, xp: int) -> None:
        """Tech XPに基づいてAuto-Pilot比率を動的に調整します。
        - Novice (< 100 XP): 90% Automation (AI does everything)
        - Intermediate (< 500 XP): 50% Automation (Co-pilot)
        - Master (>= 500 XP): 10% Automation (AI is the hands, User is the brain)

        Args:
            xp (int): 現在のTech XP。
        """
        ratio = 0.9 # Default Novice
        level_title = "Novice"
        
        if xp >= 500:
            ratio = 0.1
            level_title = "Director (Master)"
        elif xp >= 100:
            ratio = 0.5
            level_title = "Editor (Intermediate)"
            
        # Update User Model
        if 'collaborative_settings' not in self.user_model:
            self.user_model['collaborative_settings'] = {}
            
        old_ratio = self.user_model['collaborative_settings'].get('auto_pilot_ratio', 0.9)
        self.user_model['collaborative_settings']['auto_pilot_ratio'] = ratio
        
        # Sync rank level
        admin_profile = self.user_model.get("profiles", {}).get("admin", {})
        if admin_profile:
            admin_profile['ranks']['tech_rank']['level'] = level_title
        
        if old_ratio != ratio:
            logger.info(f"🔄 Automation Level Evolved: {old_ratio*100}% -> {ratio*100}% ({level_title})")
            history_manager.log_event(EventType.SYSTEM_EVENT, {
                "event": "AUTOMATION_LEVEL_UPDATE",
                "old_ratio": old_ratio,
                "new_ratio": ratio,
                "level": level_title
            })
            self._save_json(USER_MODEL_PATH, self.user_model)

    def process_analytics_update(self) -> dict:
        """AnalyticsManagerから最新の統計を取得し、Biz Rankを更新します。
        フィードバックループを実装します。

        Returns:
            dict: 統計情報、ライバル情報、および新規クエスト情報を含む辞書。
        """
        from branding.analytics_manager import analytics_manager
        
        # 1. Get Real World Data
        stats = analytics_manager.get_my_stats()
        current_subs = stats['subscribers']
        current_views = stats['total_views']
        
        # 2. Scout Rivals
        rivals = analytics_manager.scout_rivals(stats)
        quests = analytics_manager.calculate_gap(stats, rivals)
        
        # 3. Calculate Biz XP based on Views (Simple Logic: 100 views = 1 XP)
        # In a real app, we would calculate diff from last time.
        # For prototype, we just recalc total XP based on views.
        calculated_xp = int(current_views / 100)
        
        # 4. Update Biz Rank
        owner_profile = self.user_model.get("profiles", {}).get("owner", {})
        biz_rank_xp = owner_profile.get("ranks", {}).get("biz_rank", {}).get("xp", 0)
        self.update_user_rank("biz_rank", calculated_xp - biz_rank_xp)
        
        # 5. Update Status in User Model
        if 'external_status' not in self.user_model:
            self.user_model['external_status'] = {}
            
        self.user_model['external_status']['youtube'] = stats
        self.user_model['external_status']['rivals'] = rivals
        self.user_model['external_status']['quests'] = quests
        
        self._save_json(USER_MODEL_PATH, self.user_model)
        
        return {
            "stats": stats,
            "rivals": rivals,
            "quests": quests,
            "biz_xp": calculated_xp
        }

    def update_user_model(self, note: Optional[str] = None) -> None:
        """ユーザーモデル内のAIノートなどを更新します。

        Args:
            note (Optional[str], optional): 追加するノートの内容。デフォルトは None。
        """
        if note:
            # Append note simply for now
            current = self.user_model.get('ai_notes', "")
            self.user_model['ai_notes'] = current + " " + note
        
        self._save_json(USER_MODEL_PATH, self.user_model)

    def update_strategy(self, phase: Optional[str] = None, advise: Optional[str] = None) -> None:
        """戦略ファイル（フェーズやアドバイス）を更新します。

        Args:
            phase (Optional[str], optional): 更新後のフェーズ名。デフォルトは None。
            advise (Optional[str], optional): 更新後の戦略的アドバイス。デフォルトは None。
        """
        if phase:
            self.strategy['current_phase'] = phase
        if advise:
            self.strategy['current_mission']['advice'] = advise
        
        self._save_json(STRATEGY_PATH, self.strategy)

    def ingest_report(self, report_data: dict) -> dict:
        """制作レポートを取り込みます。
        1. XPを付与
        2. 質的な進化をログ記録
        3. 会議用のアジェンダを返却

        Args:
            report_data (dict): レポートデータを含む辞書。

        Returns:
            dict: 成功ステータス、付与XP、提案されたアジェンダを含む辞書。
        """
        xp = report_data.get('xp_grant', 50)
        self.update_user_rank("tech_rank", amount=xp)
        
        # [NEW] Log Narrative Evolution automatically
        self.log_evolution(report_data)
        
        return {
            "status": "success",
            "xp_granted": xp,
            "agenda": report_data.get('agenda_proposal', "")
        }

    def get_evolution_log(self) -> dict:
        """evolution_log.jsonを読み込みます。

        Returns:
            dict: 読み込まれた進化ログデータ。
        """
        EVOLUTION_LOG_PATH = os.path.join(BRANDING_DIR, "evolution_log.json")
        return self._load_json(EVOLUTION_LOG_PATH)

    def save_evolution_log(self, data: dict) -> None:
        """evolution_log.json を保存します。

        Args:
            data (dict): 保存する進化ログデータ。
        """
        EVOLUTION_LOG_PATH = os.path.join(BRANDING_DIR, "evolution_log.json")
        self._save_json(EVOLUTION_LOG_PATH, data)

    def log_evolution(self, session_data: dict) -> Optional[dict]:
        """セッションデータからナラティブ進化の洞察を抽出し、evolution_log.jsonに保存します。

        Args:
            session_data (dict): セッションの成果データ。

        Returns:
            Optional[dict]: 作成されたログエントリ、またはエラー時は None。
        """
        EVOLUTION_LOG_PATH = os.path.join(BRANDING_DIR, "evolution_log.json")
        
        # 1. Load existing log
        evo_log = self._load_json(EVOLUTION_LOG_PATH)
        if not evo_log:
            evo_log = {"entries": [], "philosophy": "初心者からスタート。"}

        # 2. Extract Narrative using Gemini
        # We use a dedicated prompt to find 'Growth'
        prompt = f"""
        あなたは映像制作チーム of 「精神的支柱」であるAIです。
        今回の制作セッションの結果から、ユーザー（監督）の「成長」と「制作哲学の進化」を読み取り、
        未来への記録（ナラティブ）として要約してください。

        ## セッションデータ
        {json.dumps(session_data, indent=2, ensure_ascii=False)}

        ## 出力形式 (JSON Only)
        {{
            "summary": "今回の成長の一言（日本語）",
            "insight": "具体的にどのような変化があったか（日本語 2-3分）",
            "stat_changes": ["Tech Rank +10", "New Style Discovered"],
            "new_philosophy_hint": "このセッションから得られた新たな教訓やモットー"
        }}
        """

        try:
            from google import genai
            from google.genai import types
            from model_registry import get_model
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=get_model("branding"),
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            narrative = json.loads(response.text)
            
            # 3. Append to log
            entry = {
                "timestamp": time.time(),
                "iso_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                **narrative
            }
            evo_log["entries"].append(entry)
            
            # === 憲法 5.2: 哲学の累積的保存 ===
            # philosophy → philosophies 配列に追記（上書き禁止）
            if narrative.get("new_philosophy_hint"):
                if "philosophies" not in evo_log:
                    evo_log["philosophies"] = []
                
                philosophy_entry = {
                    "philosophy": narrative["new_philosophy_hint"],
                    "timestamp": entry["iso_time"],
                    "session_summary": narrative.get("summary", "")
                }
                evo_log["philosophies"].append(philosophy_entry)
                
                # 10セッションごとに哲学を統合
                if len(evo_log["philosophies"]) % 10 == 0:
                    self._integrate_philosophies(evo_log)

            self._save_json(EVOLUTION_LOG_PATH, evo_log)
            logger.info(f"✨ Evolution Logged: {narrative['summary']}")
            logger.info(f"📚 Philosophies accumulated: {len(evo_log.get('philosophies', []))}")
            return entry

        except (ImportError, ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError) as e:
            logger.error(f"Failed to log evolution: {e}", exc_info=True)
            return None
    
    def _integrate_philosophies(self, evo_log: dict) -> None:
        """過去の全哲学を統合し、より深い洞察として昇華させます（憲法 5.2 哲学の統合）。

        Args:
            evo_log (dict): 哲学履歴を含む進化ログデータ。
        """
        philosophies = evo_log.get("philosophies", [])
        if len(philosophies) < 3:
            return
        
        # 哲学リストを作成
        philosophy_texts = [p.get('philosophy', p) if isinstance(p, dict) else p for p in philosophies]
        
        prompt = f"""
        あなたは映像制作チーム of 「精神的支柱」であるAIです。
        以下の哲学の履歴を分析し、より深い洞察として統合・昇華させてください。
        
        ## 哲学の履歴
        {chr(10).join([f"- {p}" for p in philosophy_texts])}
        
        ## 出力形式
        「...」形式で、1文で統合哲学を述べてください。
        """
        
        try:
            from google import genai
            from model_registry import get_model
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=get_model("branding"),
                contents=prompt
            )
            
            # 統合哲学を保存
            integrated = response.text.strip()
            evo_log["integrated_philosophy"] = integrated
            evo_log["integration_history"] = evo_log.get("integration_history", []) + [{
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "philosophy": integrated,
                "source_count": len(philosophies)
            }]
            
            logger.info(f"🧬 Philosophy integrated: {integrated[:50]}...")
            
        except (ImportError, RuntimeError, ValueError, AttributeError, TypeError, OSError) as e:
            logger.error(f"Philosophy integration failed: {e}", exc_info=True)

branding_manager = BrandingManager()
