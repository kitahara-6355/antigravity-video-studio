# -*- coding: utf-8 -*-
"""
履歴考慮とカスタムルール

推奨タスク P4.2: 過去の会話履歴を考慮した意図解析
推奨タスク P4.3: ユーザー定義のディスパッチルール
推奨タスク P7.3: エージェント実行の優先度設定（負荷分散）
"""

from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
import re

logger = logging.getLogger(__name__)


@dataclass
class ConversationEntry:
    """会話エントリ"""
    role: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    intent: str = ""
    agents_used: List[str] = field(default_factory=list)


@dataclass
class DispatchRule:
    """カスタムディスパッチルール"""
    id: str
    name: str
    pattern: str  # 正規表現パターン
    agents: List[str]  # 割り当てるエージェント
    priority: int = 0  # 高いほど優先
    enabled: bool = True


class ConversationHistory:
    """会話履歴管理（P4.2）"""
    
    def __init__(self, max_entries: int = 50):
        self._history: List[ConversationEntry] = []
        self.max_entries = max_entries
    
    def add(self, role: str, content: str, intent: str = "", agents: List[str] = None):
        """履歴追加"""
        try:
            if agents is None:
                agents_used = []
            elif isinstance(agents, str):
                agents_used = [agents]
            else:
                try:
                    agents_used = list(agents)
                except TypeError as e:
                    logger.warning(f"Invalid agents list: {e}. Defaulting to empty list.")
                    agents_used = []

            entry = ConversationEntry(
                role=str(role) if role is not None else "",
                content=str(content) if content is not None else "",
                intent=str(intent) if intent is not None else "",
                agents_used=agents_used
            )
            self._history.append(entry)
            
            # 最大数を超えたら古いものを削除
            if len(self._history) > self.max_entries:
                self._history = self._history[-self.max_entries:]
        except (TypeError, ValueError, AttributeError) as e:
            logger.error(f"Error adding conversation entry to history: {e}", exc_info=True)
            # 最小限のフォールバックで追加試行
            try:
                entry = ConversationEntry(
                    role=str(role) if role is not None else "unknown",
                    content=str(content) if content is not None else ""
                )
                self._history.append(entry)
            except (TypeError, AttributeError, ValueError):
                pass
    
    def get_recent(self, count: int = 10) -> List[ConversationEntry]:
        """最近の履歴取得"""
        try:
            return self._history[-count:]
        except TypeError as e:
            logger.error(f"Error getting recent conversation entries: {e}", exc_info=True)
            return self._history[-10:] if self._history else []
    
    def get_context_summary(self) -> str:
        """文脈サマリー生成"""
        try:
            if not self._history:
                return "会話履歴なし"
            
            recent = self.get_recent(5)
            summary_parts = []
            for entry in recent:
                try:
                    summary_parts.append(f"- [{entry.role}]: {entry.content[:100]}...")
                except AttributeError:
                    continue
            
            return "\n".join(summary_parts) if summary_parts else "会話履歴なし"
        except (TypeError, AttributeError) as e:
            logger.error(f"Error generating context summary: {e}", exc_info=True)
            return "会話履歴なし"
    
    def get_used_agents_stats(self) -> Dict[str, int]:
        """使用エージェント統計"""
        try:
            from collections import Counter
            all_agents = []
            for entry in self._history:
                try:
                    if isinstance(entry.agents_used, list):
                        all_agents.extend(entry.agents_used)
                    else:
                        all_agents.extend(list(entry.agents_used))
                except TypeError as e:
                    logger.error(f"Error extracting agents_used from entry: {e}", exc_info=True)
            return dict(Counter(all_agents))
        except TypeError as e:
            logger.error(f"Error generating used agents stats: {e}", exc_info=True)
            return {}
    
    def infer_user_preference(self) -> Dict[str, Any]:
        """ユーザー傾向推定"""
        try:
            stats = self.get_used_agents_stats()
            total = sum(stats.values())
            
            if total == 0:
                return {"preference": "balanced"}
            
            preferences = {
                agent: count / total for agent, count in stats.items()
            }
            
            dominant = max(preferences, key=preferences.get) if preferences else None
            
            return {
                "preference": dominant,
                "distribution": preferences,
                "total_interactions": total
            }
        except (TypeError, ValueError) as e:
            logger.error(f"Error inferring user preference: {e}", exc_info=True)
            return {"preference": "balanced", "distribution": {}, "total_interactions": 0}


class CustomRuleManager:
    """カスタムルール管理（P4.3）"""
    
    def __init__(self):
        self._rules: List[DispatchRule] = []
        self._load_default_rules()
    
    def _load_default_rules(self):
        """デフォルトルール"""
        self._rules = [
            DispatchRule(
                id="urgent",
                name="緊急対応",
                pattern=r"(緊急|至急|急ぎ|今すぐ)",
                agents=["Strategist", "Director"],
                priority=100
            ),
            DispatchRule(
                id="data_request",
                name="データ分析依頼",
                pattern=r"(分析|データ|統計|数字|再生数)",
                agents=["Analyst"],
                priority=50
            ),
            DispatchRule(
                id="creative",
                name="クリエイティブ依頼",
                pattern=r"(演出|編集|カット|エモ|雰囲気)",
                agents=["Director"],
                priority=50
            ),
            DispatchRule(
                id="strategy",
                name="戦略相談",
                pattern=r"(戦略|方針|ブランド|長期|計画)",
                agents=["Strategist"],
                priority=50
            ),
        ]
    
    def add_rule(self, rule: DispatchRule):
        """ルール追加"""
        try:
            if not isinstance(rule, DispatchRule):
                logger.warning(f"Invalid rule type, expected DispatchRule: {rule}")
                return
            # 正規表現パターンの妥当性検証
            re.compile(rule.pattern)
            self._rules.append(rule)
            self._rules.sort(key=lambda r: -r.priority)
        except re.error as re_err:
            logger.error(f"Invalid regex pattern '{rule.pattern}' in rule {rule.id}: {re_err}")
        except (TypeError, ValueError, AttributeError) as e:
            logger.error(f"Error adding rule to CustomRuleManager: {e}", exc_info=True)
    
    def remove_rule(self, rule_id: str) -> bool:
        """ルール削除"""
        try:
            for i, rule in enumerate(self._rules):
                if rule.id == rule_id:
                    del self._rules[i]
                    return True
            return False
        except (TypeError, AttributeError) as e:
            logger.error(f"Error removing rule from CustomRuleManager: {e}", exc_info=True)
            return False
    
    def match(self, text: str) -> Optional[DispatchRule]:
        """テキストにマッチするルールを検索"""
        try:
            if text is None:
                return None
            text_str = str(text)
            for rule in self._rules:
                if not rule.enabled:
                    continue
                try:
                    if re.search(rule.pattern, text_str):
                        return rule
                except re.error as re_err:
                    logger.error(f"Invalid regex pattern '{rule.pattern}' in rule {rule.id}: {re_err}")
                except AttributeError as e:
                    logger.error(f"Error checking rule pattern '{rule.pattern}': {e}", exc_info=True)
        except (TypeError, AttributeError) as e:
            logger.error(f"Error matching rules: {e}", exc_info=True)
        return None
    
    def get_all_rules(self) -> List[Dict[str, Any]]:
        """全ルール取得"""
        try:
            return [
                {
                    "id": r.id,
                    "name": r.name,
                    "pattern": r.pattern,
                    "agents": r.agents,
                    "priority": r.priority,
                    "enabled": r.enabled
                }
                for r in self._rules
            ]
        except (TypeError, AttributeError) as e:
            logger.error(f"Error getting all rules: {e}", exc_info=True)
            return []


class LoadBalancer:
    """エージェント負荷分散（P7.3）"""
    
    def __init__(self):
        self._agent_load: Dict[str, int] = {}
        self._agent_priority: Dict[str, int] = {
            "Strategist": 3,
            "Director": 2,
            "Analyst": 1,
        }
    
    def record_usage(self, agent: str):
        """使用記録"""
        try:
            agent_str = str(agent)
            self._agent_load[agent_str] = self._agent_load.get(agent_str, 0) + 1
        except TypeError as e:
            logger.error(f"Error recording agent usage: {e}", exc_info=True)
    
    def get_recommended_order(self, agents: List[str]) -> List[str]:
        """推奨実行順序（負荷の低い順）"""
        try:
            if not agents:
                return []
            
            # 各エージェントオブジェクトの文字列変換を事前計算してキャッシュ
            agent_str_map = {}
            for a in agents:
                try:
                    agent_str_map[id(a)] = str(a)
                except (TypeError, ValueError, AttributeError) as e:
                    logger.error(f"Invalid agent representation: {e}")
                    agent_str_map[id(a)] = ""
            
            def sort_key(agent):
                agent_str = agent_str_map.get(id(agent), "")
                load = self._agent_load.get(agent_str, 0)
                priority = self._agent_priority.get(agent_str, 0)
                return (load, -priority)
            
            return sorted(list(agents), key=sort_key)
        except (TypeError, KeyError, AttributeError) as e:
            logger.error(f"Error sorting agents in LoadBalancer: {e}", exc_info=True)
            return list(agents) if agents is not None else []
    
    def get_stats(self) -> Dict[str, Any]:
        """統計"""
        try:
            return {
                "load": self._agent_load,
                "priority": self._agent_priority
            }
        except (TypeError, AttributeError) as e:
            logger.error(f"Error getting load balancer stats: {e}", exc_info=True)
            return {"load": {}, "priority": {}}
    
    def reset(self):
        """リセット"""
        try:
            self._agent_load.clear()
        except AttributeError as e:
            logger.error(f"Error resetting load balancer: {e}", exc_info=True)


# シングルトン
conversation_history = ConversationHistory()
custom_rule_manager = CustomRuleManager()
load_balancer = LoadBalancer()
