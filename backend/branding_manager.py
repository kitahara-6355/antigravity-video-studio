try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

import os
import json
import time
import logging
from pathlib import Path

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

BRANDING_DIR = os.path.dirname(os.path.abspath(__file__)) + "/branding"

# この3つは**設定であり、かつ実行時に書き換わる**。BRANDING_DIR 直下を
# 直接指していたため、テストが Git 追跡下の本番ファイルを上書きしていた
# （constitution.json / user_model.json の実測あり）。
#
# evolution_log.json と同じく writable_path で解決する。ただしこちらは
# 読み取りも兼ねるので、conftest が本番の内容を writable root へ複製する。
# 中身が要るテストが空ファイルを読むことにならないようにするため。
#
# BRANDING_DIR 自体は据え置く。ロゴや BGM のような読み取り専用の素材が
# ぶら下がっており、そちらを移すと読めなくなる。
CONSTITUTION_PATH = str(_writable_path("backend/branding/constitution.json"))
STRATEGY_PATH = str(_writable_path("backend/branding/strategy.json"))
USER_MODEL_PATH = str(_writable_path("backend/branding/user_model.json"))
# 字幕データのパス（プロジェクトルートからの相対パスを想定）
SUBTITLES_PATH = os.path.join(os.path.dirname(BRANDING_DIR), "src", "segments_a_plus_plus.json")

class BrandingManager:
    def __init__(self, constitution=None):
        if constitution is not None:
            self.constitution = constitution
        else:
            self.constitution = self._load_json(CONSTITUTION_PATH)
        if not isinstance(self.constitution, dict):
            self.constitution = {}
        self.strategy = self._load_json(STRATEGY_PATH)
        if not isinstance(self.strategy, dict):
            self.strategy = {}
        self.user_model = self._load_json(USER_MODEL_PATH)
        if not isinstance(self.user_model, dict):
            self.user_model = {}
        self.api_key = os.getenv("GOOGLE_API_KEY")
        self.current_vision = "" # 現在のセッションのこだわり/想い

    def _load_json(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError as e:
            print(f"File not found {path}: {e}")
            return {}
        except json.JSONDecodeError as e:
            print(f"JSON decode error in {path}: {e}")
            return {}
        except PermissionError as e:
            print(f"Permission denied {path}: {e}")
            return {}

    def _save_json(self, path, data):
        try:
            # 保存先が writable_path で差し替えられている場合、親が無いことがある。
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except PermissionError as e:
            print(f"Permission denied writing to {path}: {e}")
        except TypeError as e:
            print(f"Type error serializing JSON to {path}: {e}")
        except OSError as e:
            print(f"OS error writing to {path}: {e}")

    def get_context_block(self):
        """
        Constructs a text block encapsulating the Brand, Strategy, and User Context
        to be injected into the AI's system prompt.
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
    
    def get_philosophies_context(self):
        """
        過去の全哲学エントリーをコンテキストとして取得（憲法 5.2 哲学の深化）
        """
        EVOLUTION_LOG_PATH = str(_writable_path("backend/branding/evolution_log.json"))
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

    def get_deep_context(self):
        """
        Fetches current video subtitles and user vision.
        """
        return ContextResolver.get_deep_context_block(SUBTITLES_PATH, self.current_vision)

    def update_user_rank(self, rank_type, amount=10):
        """
        Updates XP for a specific rank in the corresponding profile.
        tech_rank -> admin, biz_rank -> owner
        """
        profile_key = "admin" if rank_type == "tech_rank" else "owner"
        if not isinstance(self.user_model, dict):
            self.user_model = {}
            
        profiles = self.user_model.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
            self.user_model["profiles"] = profiles
            
        if profile_key not in profiles or not isinstance(profiles[profile_key], dict):
            profiles[profile_key] = {}
            
        profile = profiles[profile_key]
        ranks = profile.get("ranks")
        if not isinstance(ranks, dict):
            ranks = {}
            profile["ranks"] = ranks
            
        if rank_type not in ranks or not isinstance(ranks[rank_type], dict):
            ranks[rank_type] = {}
            
        rank = ranks[rank_type]
        current_xp = rank.get('xp', 0)
        if not isinstance(current_xp, (int, float)):
            current_xp = 0
            
        new_xp = current_xp + amount
        rank['xp'] = new_xp
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

    def evolve_constitution(self, success_event: dict):
        """
        AI Personality Self-Evolution Logic (Phase 26)
        Updates constitution based on user choices.
        """
        try:
            if not isinstance(self.constitution, dict):
                self.constitution = {}
                
            # 成功事例の要約（タイトル、コンセプト名など）
            event_summary = f"Success: {success_event.get('type', 'Unknown')} - {success_event.get('value', 'Unknown')}"
            
            # ソウル・ナラティブの更新（簡易版）
            ev = self.constitution.get('evolution_vision', "")
            if not isinstance(ev, str):
                ev = str(ev)
            self.constitution['evolution_vision'] = ev + f"\n- {event_summary}"
            
            # 特定のキーワードが選ばれた場合、ブランドキーワードに追加
            new_keyword = success_event.get('keyword')
            if new_keyword:
                bp = self.constitution.get('brand_personality')
                if not isinstance(bp, dict):
                    bp = {}
                    self.constitution['brand_personality'] = bp
                    
                keywords = bp.get('keywords')
                if not isinstance(keywords, list):
                    keywords = []
                    bp['keywords'] = keywords
                    
                if new_keyword not in keywords:
                    keywords.append(new_keyword)
                
            self._save_json(CONSTITUTION_PATH, self.constitution)
            logger.info(f"Constitution evolved: {event_summary}")
            
            # 履歴にも記録
            history_manager.log_event(EventType.CONTENT_EXPORT, {
                "evolution": event_summary,
                "detail": success_event
            })
            
        except (KeyError, TypeError) as e:
            logger.error(f"Evolution error: {e}")

    def sync_decisions_to_constitution(self):
        """EvolutionTriggerService に委譲（設計書 §4.1）

        Sprint 4.2.1 以開は EvolutionTriggerService.evaluate_triggers() が
        content_policy/keywords の append 処理を担う。
        後方互換性のため本メソッドは委譲エイリアスとして維持する。
        """
        try:
            from services.evolution_trigger_service import EvolutionTriggerService
            trigger_svc = EvolutionTriggerService(
                constitution_path=Path(CONSTITUTION_PATH),
            )
            trigger_result = trigger_svc.evaluate_triggers()
            fired = trigger_result.get("fired", [])
            changes = [
                f"{r['action']}: {r['detail']}"
                for r in fired
            ]
            return {
                "synced": True,
                "delegated_to": "EvolutionTriggerService",
                "changes": changes,
                "trigger_results": trigger_result,
            }
        except (ImportError, RuntimeError) as e:
            logger.error(f"[BrandingManager] sync_decisions_to_constitution 委譲失敗: {e}")
            return {"synced": False, "error": str(e)}

    def auto_evolve_all(self):
        """
        全ての自動進化処理を実行（定期実行用）
        
        1. 意思決定からconstitution.jsonを更新
        2. evolution_logをdecision_loggerに同期
        3. 哲学の統合チェック
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
                results["soul_narrative_sync"] = {"error": str(e)}
        
        # 3. 哲学の統合チェック（10件ごと）
        evo_log = self.get_evolution_log()
        philosophy_count = len(evo_log.get("philosophies", []))
        if philosophy_count > 0 and philosophy_count % 10 == 0:
            self._integrate_philosophies(evo_log)
            results["philosophy_check"] = {"integrated": True, "count": philosophy_count}
        else:
            results["philosophy_check"] = {"integrated": False, "count": philosophy_count}
        
        logger.info(f"🔄 Auto-evolution complete: {results}")
        return results

    def _recalculate_automation_level(self, xp):
        """
        Dynamically adjusts Auto-Pilot Ratio based on Tech XP.
        - Novice (< 100 XP): 90% Automation (AI does everything)
        - Intermediate (< 500 XP): 50% Automation (Co-pilot)
        - Master (>= 500 XP): 10% Automation (AI is the hands, User is the brain)
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
        if not isinstance(self.user_model, dict):
            self.user_model = {}
            
        collab = self.user_model.get('collaborative_settings')
        if not isinstance(collab, dict):
            collab = {}
            self.user_model['collaborative_settings'] = collab
            
        old_ratio = collab.get('auto_pilot_ratio', 0.9)
        if not isinstance(old_ratio, (int, float)):
            old_ratio = 0.9
            
        collab['auto_pilot_ratio'] = ratio
        
        # Sync rank level
        profiles = self.user_model.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
            self.user_model["profiles"] = profiles
            
        admin_profile = profiles.get("admin")
        if not isinstance(admin_profile, dict):
            admin_profile = {}
            profiles["admin"] = admin_profile
            
        ranks = admin_profile.get("ranks")
        if not isinstance(ranks, dict):
            ranks = {}
            admin_profile["ranks"] = ranks
            
        tech_rank = ranks.get("tech_rank")
        if not isinstance(tech_rank, dict):
            tech_rank = {}
            ranks["tech_rank"] = tech_rank
            
        tech_rank['level'] = level_title
        
        if old_ratio != ratio:
            print(f"🔄 Automation Level Evolved: {old_ratio*100}% -> {ratio*100}% ({level_title})")
            history_manager.log_event(EventType.SYSTEM_EVENT, {
                "event": "AUTOMATION_LEVEL_UPDATE",
                "old_ratio": old_ratio,
                "new_ratio": ratio,
                "level": level_title
            })
            self._save_json(USER_MODEL_PATH, self.user_model)

    def process_analytics_update(self):
        """
        Fetches latest stats from AnalyticsManager and updates Biz Rank.
        Implements the Feedback Loop.
        """
        from branding.analytics_manager import analytics_manager
        
        # 1. Get Real World Data
        stats = analytics_manager.get_my_stats()
        if not isinstance(stats, dict):
            stats = {"subscribers": 0, "total_views": 0}
            
        current_subs = stats.get('subscribers', 0)
        current_views = stats.get('total_views', 0)
        if not isinstance(current_subs, (int, float)):
            current_subs = 0
        if not isinstance(current_views, (int, float)):
            current_views = 0
        
        # 2. Scout Rivals
        rivals = analytics_manager.scout_rivals(stats)
        quests = analytics_manager.calculate_gap(stats, rivals)
        
        # 3. Calculate Biz XP based on Views (Simple Logic: 100 views = 1 XP)
        # In a real app, we would calculate diff from last time.
        # For prototype, we just recalc total XP based on views.
        calculated_xp = int(current_views / 100)
        
        # 4. Update Biz Rank
        if not isinstance(self.user_model, dict):
            self.user_model = {}
            
        profiles = self.user_model.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
            self.user_model["profiles"] = profiles
            
        owner_profile = profiles.get("owner")
        if not isinstance(owner_profile, dict):
            owner_profile = {}
            profiles["owner"] = owner_profile
            
        ranks = owner_profile.get("ranks")
        if not isinstance(ranks, dict):
            ranks = {}
            owner_profile["ranks"] = ranks
            
        biz_rank = ranks.get("biz_rank")
        if not isinstance(biz_rank, dict):
            biz_rank = {}
            ranks["biz_rank"] = biz_rank
            
        biz_rank_xp = biz_rank.get("xp", 0)
        if not isinstance(biz_rank_xp, (int, float)):
            biz_rank_xp = 0
            
        self.update_user_rank("biz_rank", calculated_xp - biz_rank_xp)
        
        # 5. Update Status in User Model
        ext_status = self.user_model.get('external_status')
        if not isinstance(ext_status, dict):
            ext_status = {}
            self.user_model['external_status'] = ext_status
            
        ext_status['youtube'] = stats
        ext_status['rivals'] = rivals
        ext_status['quests'] = quests
        
        self._save_json(USER_MODEL_PATH, self.user_model)

        # **保存の後に印を付ける。** `stats` / `rivals` は `analytics_manager` が
        # 既に印を持っているが、`quests`（`target_val: 180` / `current_val: 150`）は
        # 素のままだった。外へ出す値は集約点を通す（R1.5-C4・10周目 N-1）。
        try:  # backend/ を直接 sys.path に載せている経路にも対応する
            from backend.user_model_marks import 外部実績に印を付ける
        except ImportError:
            from user_model_marks import 外部実績に印を付ける

        return 外部実績に印を付ける({
            "stats": stats,
            "rivals": rivals,
            "quests": quests,
            "biz_xp": calculated_xp
        })

    def update_user_model(self, note=None):
        if note:
            # Append note simply for now
            current = self.user_model.get('ai_notes', "")
            self.user_model['ai_notes'] = current + " " + note
        
        self._save_json(USER_MODEL_PATH, self.user_model)

    def update_strategy(self, phase=None, advise=None):
        if phase:
            self.strategy['current_phase'] = phase
        if advise:
            self.strategy['current_mission']['advice'] = advise
        
        self._save_json(STRATEGY_PATH, self.strategy)

    def ingest_report(self, report_data):
        """
        Ingests the Production Report.
        1. Grants XP.
        2. Logs qualitative evolution.
        3. Returns the agenda for the Boardroom.
        """
        # **XP の既定値を 50 にしない**（R1.5-C4・18周目 反例1と同じ形）。
        # `xp_grant` を持たないレポート（＝実績を主張していないレポート）に
        # 黙って 50 XP を与えると、`user_model.json` の `tech_rank` に
        # **実行動から出ていない実績**が積まれる。`tech_rank` は
        # `backend/user_model_marks.py` が「実行動で稼ぐ値だから印を付けない」
        # と宣言している値なので、ここが崩れるとその宣言ごと嘘になる。
        xp = report_data.get('xp_grant', 0)
        if not isinstance(xp, (int, float)) or isinstance(xp, bool):
            xp = 0
        if report_data.get("is_real") is False:
            # 分析されていないレポート（`generate_production_report` の except が返す形）
            xp = 0
        if xp > 0:
            self.update_user_rank("tech_rank", amount=xp)

        # [NEW] Log Narrative Evolution automatically
        self.log_evolution(report_data)
        
        return {
            "status": "success",
            "xp_granted": xp,
            "agenda": report_data.get('agenda_proposal', "")
        }

    def get_user_model_for_display(self):
        """**外へ出す用**。`external_status` の作り物に印を付けてから返す（R1.5-C4）。

        印そのものは `backend/user_model_marks.py` にある
        （gate-verifier 10周目 N-1）。**読み口が2つある**:

        | 読み口 | 経路 |
        |---|---|
        | `GET /api/status` | `routers/trinity.py` |
        | `GET /api/settings` | `settings_manager.get_all_settings()` |

        10周目が名指ししたのは前者だけだが、**後者は同じクラスの別経路**
        だったので、経路ごとに塞がず1箇所に寄せた。

        保存側（`self.user_model` そのもの）は素のまま。**印がファイルへ
        書き戻らないように、読み書きの入口を分けている**
        （`get_evolution_log_for_display()` と同じ形）。
        """
        try:  # backend/ を直接 sys.path に載せている経路にも対応する
            from backend.user_model_marks import 実績を持つ値に印を付ける
        except ImportError:
            from user_model_marks import 実績を持つ値に印を付ける

        return 実績を持つ値に印を付ける(self.user_model)

    def get_evolution_log(self):
        EVOLUTION_LOG_PATH = str(_writable_path("backend/branding/evolution_log.json"))
        return self._load_json(EVOLUTION_LOG_PATH)

    def get_evolution_log_for_display(self):
        """**外へ出す用**。作り物の「実績」に印を付けてから返す（R1.5-C4）。

        印そのものは `backend/evolution_log_marks.py` にある。
        読み口が3つ（`GET /api/evolution` / `GET /api/director/evolution` /
        `GET /api/v1/mcp/resources/evolution_log`）あり、**3つ目は
        `branding_manager` を通らない**ので、両方が依存できる場所へ出した
        （gate-verifier 7周目 指摘1）。

        保存側（`get_evolution_log()`）は素のまま。**印がファイルへ
        書き戻らないように、読み書きの入口を分けている。**
        """
        try:  # backend/ を直接 sys.path に載せている経路にも対応する
            from backend.evolution_log_marks import 実績に印を付ける
        except ImportError:
            from evolution_log_marks import 実績に印を付ける

        return 実績に印を付ける(self.get_evolution_log())

    def save_evolution_log(self, data):
        """evolution_log.json を保存する"""
        EVOLUTION_LOG_PATH = str(_writable_path("backend/branding/evolution_log.json"))
        self._save_json(EVOLUTION_LOG_PATH, data)

    def log_evolution(self, session_data):
        """
        Extracts narrative evolution insights from a session and saves to evolution_log.json.
        """
        EVOLUTION_LOG_PATH = str(_writable_path("backend/branding/evolution_log.json"))
        
        # 1. Load existing log
        evo_log = self._load_json(EVOLUTION_LOG_PATH)
        if not evo_log:
            evo_log = {"entries": [], "philosophy": "初心者からスタート。"}

        # 2. Extract Narrative using Gemini
        # We use a dedicated prompt to find 'Growth'
        prompt = f"""
        あなたは映像制作チームの「精神的支柱」であるAIです。
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
            from google.genai import types
            from model_registry import get_model
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            if not client:
                raise RuntimeError("GOOGLE_API_KEY not set")
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
                if "philosophies" not in evo_log or not isinstance(evo_log.get("philosophies"), list):
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
            print(f"✨ Evolution Logged: {narrative['summary']}")
            print(f"📚 Philosophies accumulated: {len(evo_log.get('philosophies', []))}")
            return entry

        except (ImportError, RuntimeError, json.JSONDecodeError, KeyError) as e:
            print(f"Failed to log evolution: {e}")
            return None
    
    def _integrate_philosophies(self, evo_log):
        """
        過去の全哲学を統合し、より深い洞察として昇華させる（憲法 5.2 哲学の統合）
        """
        philosophies = evo_log.get("philosophies", [])
        if len(philosophies) < 3:
            return
        
        # 哲学リストを作成
        philosophy_texts = [p.get('philosophy', p) if isinstance(p, dict) else p for p in philosophies]
        
        prompt = f"""
        あなたは映像制作チームの「精神的支柱」であるAIです。
        以下の哲学の履歴を分析し、より深い洞察として統合・昇華させてください。
        
        ## 哲学の履歴
        {chr(10).join([f"- {p}" for p in philosophy_texts])}
        
        ## 出力形式
        「...」形式で、1文で統合哲学を述べてください。
        """
        
        try:
            from model_registry import get_model
            from gemini_client_factory import get_gemini_client
            client = get_gemini_client()
            if not client:
                raise RuntimeError("GOOGLE_API_KEY not set")
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
            
            print(f"🧬 Philosophy integrated: {integrated[:50]}...")
            
        except (ImportError, RuntimeError, ValueError) as e:
            print(f"Philosophy integration failed: {e}")

    def validate_image_quality(self, image_path_or_bytes) -> dict:
        """
        画像（サムネイル/プレビュー）の品質を検証する。
        - 解像度: 1280x720 以上
        - アスペクト比: 16:9
        - ファイルサイズ: 4MB 以下
        """
        import io
        from PIL import Image
        from branding.history_manager import ImageValidationError
        
        # 1. データの読み込み
        img_bytes = None
        file_size = 0
        
        if image_path_or_bytes is None:
            raise TypeError("Input image cannot be None")
            
        if isinstance(image_path_or_bytes, (str, Path)):
            path = Path(image_path_or_bytes)
            if not path.exists():
                raise FileNotFoundError(f"Image file not found at path: {path}")
            file_size = path.stat().st_size
            with open(path, "rb") as f:
                img_bytes = f.read()
        elif isinstance(image_path_or_bytes, bytes):
            img_bytes = image_path_or_bytes
            file_size = len(img_bytes)
        else:
            raise TypeError("Input must be a file path or bytes object")
            
        # 2. ファイルサイズ検証 (4MB = 4 * 1024 * 1024 bytes)
        max_size = 4 * 1024 * 1024
        if file_size >= max_size:
            raise ValueError(
                f"File size exceeds or equals 4MB limit: {file_size} bytes "
                f"(Deviation: {file_size - max_size} bytes excess)"
            )
            
        # 3. 画像の解析と解像度/アスペクト比検証
        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                img.verify()
        except (IOError, SyntaxError, ValueError, TypeError) as e:
            raise IOError(f"Failed to decode image data (corrupted metadata or format): {e}")

        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                img.load()
                width, height = img.size
        except (IOError, SyntaxError, ValueError, TypeError) as e:
            raise IOError(f"Failed to decode image data due to internal Pillow error: {e}")
            
        ratio = width / height
        expected_ratio = 16 / 9
        if abs(ratio - expected_ratio) > 0.02:
            raise ValueError(
                f"Aspect ratio must be 16:9 (approx 1.77-1.78): found {ratio:.3f} ({width}x{height}) "
                f"(Target ratio: {expected_ratio:.3f}, Deviation: {abs(ratio - expected_ratio):.3f})"
            )
            
        if width < 1280 or height < 720:
            raise ValueError(
                f"Resolution must be at least 1280x720: found {width}x{height} "
                f"(Width diff: {1280 - width if width < 1280 else 0}, Height diff: {720 - height if height < 720 else 0})"
            )
            
        return {
            "valid": True,
            "width": width,
            "height": height,
            "aspect_ratio": ratio,
            "size_bytes": file_size
        }

    async def generate_and_validate_thumbnail_async(self, video_title: str, video_description: str = "") -> dict:
        """
        [非同期版] ブランド憲法に基づいてサムネイルを生成し、その品質を即座に自動検証する。
        APIエラーや検証エラーが発生した場合は、フォールバック画像を生成し、それを返す。
        """
        import base64
        
        # 1. 画像生成の品質向上:
        # コンセプト生成および画像生成のプロンプト品質を向上させるため、
        # ビデオの説明にブランド憲法のコンテキスト（ターゲット層、スタイル、トーン）を注入する。
        context_info = ""
        if self.constitution:
            target = self.constitution.get('target_audience', '')
            tone = self.constitution.get('brand_personality', {}).get('tone', '')
            style = self.constitution.get('visual_identity', {}).get('style_prompt', '')
            context_info = f"\n[Brand Context] Target Audience: {target}, Tone: {tone}, Visual Style: {style}"
        
        enhanced_description = (video_description or "") + context_info
        
        # 循環インポート回避のためのローカルインポート
        try:
            from thumbnail_engine.generator import ThumbnailGenerator
            generator = ThumbnailGenerator()
            # `await` を直接使用して非同期で実行
            results = await generator.generate(video_title, enhanced_description, num_variants=1)
        except Exception as e:
            logger.error(f"Thumbnail generation failed, falling back to local generation: {e}", exc_info=True)
            results = []
            
        # 生成された画像がある場合、検証を行う
        if results:
            try:
                thumb = results[0]
                image_bytes = base64.b64decode(thumb["image_base64"])
                # 品質検証
                val_result = self.validate_image_quality(image_bytes)
                return {
                    "status": "success",
                    "concept_name": thumb["concept_name"],
                    "description": thumb["description"],
                    "image_base64": thumb["image_base64"],
                    "ctr_score": thumb["ctr_score"],
                    "validation": val_result
                }
            except Exception as val_err:
                logger.warning(f"Generated thumbnail validation failed: {val_err}. Falling back...", exc_info=True)
                
        # フォールバック処理 (Pillowによる高品質ダミー画像の生成)
        logger.info("Generating fallback brand thumbnail due to API error or validation failure")
        fallback_bytes = self._generate_fallback_image_bytes(video_title)
        val_result = self.validate_image_quality(fallback_bytes)
        
        return {
            "status": "fallback",
            "concept_name": "Standard Fallback Concept",
            "description": "Fallback image due to system errors",
            "image_base64": base64.b64encode(fallback_bytes).decode('utf-8'),
            "ctr_score": 5.0,
            "validation": val_result
        }

    def generate_and_validate_thumbnail(self, video_title: str, video_description: str = "") -> dict:
        """
        ブランド憲法に基づいてサムネイルを生成し、その品質を即座に自動検証する。
        APIエラーや検証エラーが発生した場合は、フォールバック画像を生成し、それを返す。
        """
        import asyncio
        import base64
        
        # 1. 画像生成の品質向上:
        # コンセプト生成および画像生成のプロンプト品質を向上させるため、
        # ビデオの説明にブランド憲法のコンテキスト（ターゲット層、スタイル、トーン）を注入する。
        context_info = ""
        if self.constitution:
            target = self.constitution.get('target_audience', '')
            tone = self.constitution.get('brand_personality', {}).get('tone', '')
            style = self.constitution.get('visual_identity', {}).get('style_prompt', '')
            context_info = f"\n[Brand Context] Target Audience: {target}, Tone: {tone}, Visual Style: {style}"
        
        enhanced_description = (video_description or "") + context_info
        
        # 循環インポート回避のためのローカルインポート
        try:
            from thumbnail_engine.generator import ThumbnailGenerator
            generator = ThumbnailGenerator()
            
            # 非同期イベントループの取得・実行
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
            if loop.is_running():
                try:
                    import nest_asyncio
                    nest_asyncio.apply()
                    results = loop.run_until_complete(generator.generate(video_title, enhanced_description, num_variants=1))
                except Exception as loop_err:
                    logger.warning(f"Failed to nested run_until_complete in running loop: {loop_err}. Falling back to local generation.")
                    results = []
            else:
                results = loop.run_until_complete(generator.generate(video_title, enhanced_description, num_variants=1))
        except Exception as e:
            logger.error(f"Thumbnail generation failed, falling back to local generation: {e}", exc_info=True)
            results = []
            
        # 生成された画像がある場合、検証を行う
        if results:
            try:
                thumb = results[0]
                image_bytes = base64.b64decode(thumb["image_base64"])
                # 品質検証
                val_result = self.validate_image_quality(image_bytes)
                return {
                    "status": "success",
                    "concept_name": thumb["concept_name"],
                    "description": thumb["description"],
                    "image_base64": thumb["image_base64"],
                    "ctr_score": thumb["ctr_score"],
                    "validation": val_result
                }
            except Exception as val_err:
                logger.warning(f"Generated thumbnail validation failed: {val_err}. Falling back...", exc_info=True)
                
        # フォールバック処理 (Pillowによる高品質ダミー画像の生成)
        logger.info("Generating fallback brand thumbnail due to API error or validation failure")
        fallback_bytes = self._generate_fallback_image_bytes(video_title)
        val_result = self.validate_image_quality(fallback_bytes)
        
        return {
            "status": "fallback",
            "concept_name": "Standard Fallback Concept",
            "description": "Fallback image due to system errors",
            "image_base64": base64.b64encode(fallback_bytes).decode('utf-8'),
            "ctr_score": 5.0,
            "validation": val_result
        }

    def _generate_fallback_image_bytes(self, title: str) -> bytes:
        """検証基準を満たす高品質なフォールバック画像(1280x720)を生成してバイナリで返す"""
        import io
        from PIL import Image, ImageDraw, ImageFont
        
        # 1. 1280x720, 16:9 画像を作成 (美しい斜めグラデーション)
        # 深い青から紫への斜めグラデーションを軽量に描画
        img = Image.new("RGB", (1280, 720), color=(20, 20, 35))
        draw = ImageDraw.Draw(img)
        
        for y in range(720):
            factor_y = y / 720.0
            r_start = int(20 + 25 * factor_y)
            r_end = int(30 + 35 * factor_y)
            b_start = int(35 + 15 * factor_y)
            b_end = int(55 + 25 * factor_y)
            
            for x_seg in range(4):
                x1 = x_seg * 320
                x2 = (x_seg + 1) * 320
                factor_x = x_seg / 4.0
                r = int(r_start + (r_end - r_start) * factor_x)
                g = int(20 + 10 * factor_x)
                b = int(b_start + (b_end - b_start) * factor_x)
                draw.line([(x1, y), (x2, y)], fill=(r, g, b))
            
        # 2. 内側にゴールド調の二重境界線を描画してプレミアム感を出す
        draw.rectangle([30, 30, 1250, 690], outline=(218, 165, 32), width=3) # ゴールドカラー
        draw.rectangle([38, 38, 1242, 682], outline=(255, 223, 0), width=1) # 明るいイエローゴールド
        draw.rectangle([45, 45, 1235, 675], outline=(100, 100, 150), width=1)
        
        # 3. テキスト描画 (デフォルトフォント使用、または利用可能なOS標準フォントを探索)
        # タイトルが長い場合は文字サイズを自動調整
        display_title = title if len(title) <= 40 else title[:37] + "..."
        font_size = 48
        if len(display_title) > 15:
            font_size = max(24, int(48 * (15 / len(display_title))))
            
        font_title = None
        font_sub = None
        font_paths = [
            "C:\\Windows\\Fonts\\msgothic.ttc",
            "C:\\Windows\\Fonts\\msmincho.ttc",
            "C:\\Windows\\Fonts\\arial.ttf",
            "C:\\Windows\\Fonts\\segoeui.ttf"
        ]
        for path in font_paths:
            if os.path.exists(path):
                try:
                    font_title = ImageFont.truetype(path, font_size)
                    font_sub = ImageFont.truetype(path, 24)
                    break
                except (OSError, IOError):
                    continue
                    
        if font_title is None:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()
            
        # 4. タイトルテキストの折り返し処理（品質向上）
        max_chars_per_line = 20
        lines = []
        display_title_limit = display_title if len(display_title) <= 60 else display_title[:57] + "..."
        for i in range(0, len(display_title_limit), max_chars_per_line):
            lines.append(display_title_limit[i:i+max_chars_per_line])
            
        max_w = 0
        line_heights = []
        total_h = 0
        
        for line in lines:
            try:
                if hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), line, font=font_title)
                    w = bbox[2] - bbox[0]
                    h = bbox[3] - bbox[1]
                else:
                    w, h = draw.textsize(line, font=font_title)
            except (ValueError, TypeError, AttributeError):
                w, h = len(line) * int(font_size * 0.6), font_size
            max_w = max(max_w, w)
            line_heights.append(h)
            total_h += h + 10
            
        total_h -= 10
            
        # 半透明のテキスト背景帯を描画して文字の視認性を向上 (プレミアムテロップ風)
        overlay_y1 = 360 - int(total_h / 2) - 20
        overlay_y2 = 360 + int(total_h / 2) + 20
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle([0, overlay_y1, 1280, overlay_y2], fill=(0, 0, 0, 160)) # 不透明度60%の黒
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        
        # 複数行のタイトル文字を描画
        current_y = 360 - int(total_h / 2)
        for idx, line in enumerate(lines):
            try:
                if hasattr(draw, "textbbox"):
                    bbox = draw.textbbox((0, 0), line, font=font_title)
                    w = bbox[2] - bbox[0]
                else:
                    w, _ = draw.textsize(line, font=font_title)
            except (ValueError, TypeError, AttributeError):
                w = len(line) * int(font_size * 0.6)
                
            text_x = 640 - int(w / 2)
            draw.text((text_x, current_y), line, fill=(255, 255, 255), font=font_title)
            current_y += line_heights[idx] + 10
        
        # 5. チャンネル名とクレジットを右下と左上に描画
        channel_name = self.constitution.get('channel_name', 'Official Studio') if self.constitution else 'Official Studio'
        try:
            if hasattr(draw, "textbbox"):
                sub_bbox = draw.textbbox((0, 0), channel_name, font=font_sub)
                sw = sub_bbox[2] - sub_bbox[0]
                sh = sub_bbox[3] - sub_bbox[1]
            else:
                sw, sh = draw.textsize(channel_name, font=font_sub)
        except (ValueError, TypeError, AttributeError):
            sw, sh = len(channel_name) * 10, 20
            
        draw.text((60, 60), "PREMIUM BRAND PREVIEW", fill=(218, 165, 32), font=font_sub)
        draw.text((1220 - sw, 660 - sh), channel_name, fill=(200, 200, 250), font=font_sub)
        
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        return buf.getvalue()

    async def resolve_thumbnail_task(self, task_id: str, output_dir: str = str(_writable_path("backend/temp_thumbnails"))) -> str:
        """
        StageBoundAgent の process_func として動作する非同期タスク処理。
        ブランディング設定に基づいて画像を生成し、その結果を指定のパスに保存、
        その品質を自動検証して結果を JSON で返す。
        """
        import json
        from pathlib import Path
        import base64
        import uuid
        
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        output_path = output_dir_path / f"{task_id}.png"
        
        # 憲法のチャンネル名やビジョンなどのブランディングを反映
        title = self.constitution.get('channel_name', 'Official Studio') if self.constitution else 'Official Studio'
        description = f"Automated branding thumbnail for task {task_id}"
        
        thumbnail_res = await self.generate_and_validate_thumbnail_async(title, description)
        
        image_bytes = base64.b64decode(thumbnail_res["image_base64"])
        
        # 原子的なファイル書き込み (Atomic Write)
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            with open(temp_path, "wb") as f:
                f.write(image_bytes)
            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)
        except (OSError, IOError) as e:
            logger.error(f"Failed to write thumbnail image file: {e}")
            raise
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except (OSError, IOError):
                    pass
            
        # 画像品質検証
        val_result = self.validate_image_quality(output_path)
        
        return json.dumps({
            "path": str(output_path),
            "width": val_result["width"],
            "height": val_result["height"],
            "size_bytes": val_result["size_bytes"],
            "status": thumbnail_res["status"],
            "concept_name": thumbnail_res.get("concept_name", "")
        })

branding_manager = BrandingManager()
