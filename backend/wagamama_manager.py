"""
Wagamama Manager - わがまま台帳（Experience/Evolution Story）管理システム

【PROJECT_CONSTITUTION 整合性】
- §2 ユーザーの要望と解決策の軌跡
- §24 ドキュメント体系（物語層: wagamama_ledger.json）
- Council, Decision Logger, Learning Loop と連動し、ユーザーの「痛み」から「解決」までのストーリーを自動記録する。

主な機能:
1. Nexusからの「痛み（pain）」検出と新規レコード起票
2. Councilセッションの紐づけ（議論プロセスの記録）
3. Decision Logger / Learning Loop における「解決（magic）」の自動クローズ
4. USER_MANUAL of 品質ギャップ（未記載）自動検知
"""

import os
import json
import uuid
from datetime import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from safe_io import SafeJsonStore

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "branding"
LEDGER_FILE = DATA_DIR / "wagamama_ledger.json"

class WagamamaManager:
    """わがまま台帳システムの中核。マルチユーザーストーリーの管理を行う"""

    def __init__(self):
        initial_data = {
            "version": "1.0",
            "name": "Wagamama Ledger",
            "description": "Multi-user story management registry",
            "records": []
        }
        self.store = SafeJsonStore(LEDGER_FILE, default=initial_data)
        self.ledger_data = self._load()
        self._ensure_file_exists()
        self.manual_path = Path(__file__).parent.parent / "docs" / "USER_MANUAL.md"

    def _ensure_file_exists(self):
        if not LEDGER_FILE.exists():
            try:
                self.store.save(self.ledger_data)
            except (OSError, TypeError, ValueError) as e:
                logger.error(f"Failed to initialize wagamama ledger file: {e}")

    def _load(self) -> Dict[str, Any]:
        """台帳ファイルの読み込み"""
        return self.store.load()

    def _save(self):
        """台帳ファイルの保存"""
        try:
            self.store.save(self.ledger_data)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"Failed to save wagamama ledger: {e}")

    def create_experience_story(self, user_voice: str, detected_by: str = "nexus", feature_id: str = "", youtube_video_id: str = "") -> str:
        if not isinstance(user_voice, str):
            raise TypeError("user_voice must be a string")
        if not isinstance(detected_by, str):
            raise TypeError("detected_by must be a string")
        if not isinstance(feature_id, str):
            raise TypeError("feature_id must be a string")
        if not isinstance(youtube_video_id, str):
            raise TypeError("youtube_video_id must be a string")
        """
        [トリガー: Nexus意図解析]
        エンドユーザー（チャンネル主）から不満(Pain)を検出した際に自動起票する
        
        Args:
            youtube_video_id: 公開後にここへYouTubeのVideo IDをセットする（feedback-loop用）
        
        Returns: wagamama_id
        """
        # 番号の発番 (W-XXX)
        records = self.ledger_data.get("records")
        if records is None:
            records = []
            self.ledger_data["records"] = records
        elif not isinstance(records, list):
            raise ValueError("wagamama ledger records must be a list")

        next_id_num = len(records) + 1
        w_id = f"W-{next_id_num:03d}"
        feature_id = feature_id or f"auto_feature_{uuid.uuid4().hex[:8]}"

        new_record = {
            "wagamama_id": w_id,
            "feature_id": feature_id,
            "youtube_video_id": youtube_video_id,  # Fix①: 公開後にセットされるYouTube Video ID
            "lanes": {
                "experience": {
                    "pain": user_voice,
                    "pain_detected_by": detected_by,
                    "pain_timestamp": datetime.now().isoformat()
                }
            },
            "manual_section": None,
            "quality_gap": True,  # 初期はマニュアル未記載
            "status": "investigating"
        }

        self.ledger_data["records"].append(new_record)
        self._save()
        logger.info(f"🆕 [Wagamama Ledger] 起票 '{w_id}': {user_voice[:30]}...")
        return w_id

    def link_council_session(self, wagamama_id: str, session_id: str, log_file: str, synthesis: dict):
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        if not isinstance(log_file, str):
            raise TypeError("log_file must be a string")
        if not isinstance(synthesis, dict):
            raise TypeError("synthesis must be a dictionary")
        if "summary" in synthesis and not isinstance(synthesis["summary"], str):
            raise TypeError("synthesis['summary'] must be a string")
        """
        [トリガー: 議会（Council）]
        課題解決のために開かれた議会のログを紐づける
        """
        record = self.get_record(wagamama_id)
        if not record:
            return False

        if "lanes" not in record or not isinstance(record["lanes"], dict):
            record["lanes"] = {}
        exp_lane = record["lanes"].setdefault("experience", {})
        if not isinstance(exp_lane, dict):
            exp_lane = {}
            record["lanes"]["experience"] = exp_lane

        exp_lane["council"] = {
            "session_id": session_id,
            "log_file": log_file,
            "synthesis": synthesis.get("summary", "No synthesis logic provided")
        }
        record["status"] = "in_debate"
        self._save()
        logger.info(f"⚖️ [Wagamama Ledger] 議会ログ紐付け ({wagamama_id} -> {session_id})")
        return True

    def _auto_detect_manual_section(self, record: dict) -> Optional[str]:
        """
        USER_MANUAL.md を Python 経由で読み込み、feature_id などに関連する見出しセクションを自動検索する
        """
        if not self.manual_path or not self.manual_path.exists():
            return None
            
        feature_id = record.get("feature_id", "")
        if not feature_id:
            return None
            
        try:
            with open(self.manual_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        # 見出し行からシャープ記号を除去
                        heading = stripped.lstrip("#").strip()
                        # feature_id が見出しテキストに含まれるか判定（部分一致）
                        if feature_id in heading:
                            return heading
        except (OSError, ValueError) as e:
            logger.error(f"Failed to auto detect manual section: {e}")
            
        return None

    def find_matching_story(self, topic: str, tags: List[str] = None) -> Optional[str]:
        if not topic or not isinstance(topic, str):
            return None
        if tags is not None and not isinstance(tags, list):
            return None
        """
        トピックやタグに基づいて、現在進行中の関連ストーリー（W-XXX）を検索する
        """
        records = self.ledger_data.get("records")
        if not isinstance(records, list):
            return None

        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("status") not in ("investigating", "in_debate"):
                continue
                
            feature_id = record.get("feature_id", "")
            if not isinstance(feature_id, str):
                feature_id = ""
            
            # 1. feature_id が topic に含まれるか
            if feature_id and feature_id in topic:
                return record["wagamama_id"]
                
            # 2. tags が指定され、その中に feature_id が含まれるか
            if tags and any(isinstance(t, str) and feature_id == t for t in tags):
                return record["wagamama_id"]
                
            # 3. pain の内容が topic に部分一致するか
            lanes = record.get("lanes")
            if not isinstance(lanes, dict):
                continue
            exp = lanes.get("experience")
            if not isinstance(exp, dict):
                continue
            pain = exp.get("pain", "")
            if not isinstance(pain, str):
                pain = ""
            if pain:
                words = (w for w in (feature_id, pain[:10]) if w)
                if any(word in topic for word in words):
                    return record["wagamama_id"]
                
        return None

    def resolve_story(self, wagamama_id: str, solution_description: str, emotion: str = "満足"):
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        if not isinstance(solution_description, str):
            raise TypeError("solution_description must be a string")
        if not isinstance(emotion, str):
            raise TypeError("emotion must be a string")
        """
        [トリガー: DecisionLogger(Approve) または 実装完了テスト]
        解決策が承認・実装された時点で、ストーリーを完了（Magic）させる
        """
        record = self.get_record(wagamama_id)
        if not record:
            return False

        if "lanes" not in record or not isinstance(record["lanes"], dict):
            record["lanes"] = {}
        exp_lane = record["lanes"].setdefault("experience", {})
        if not isinstance(exp_lane, dict):
            exp_lane = {}
            record["lanes"]["experience"] = exp_lane

        exp_lane["magic"] = solution_description
        exp_lane["emotion"] = emotion
        exp_lane["resolved_at"] = datetime.now().isoformat()
        
        record["status"] = "resolved"
        
        # マニュアルセクションがまだ設定されていない場合、自動検出を試みる
        if not record.get("manual_section"):
            detected_section = self._auto_detect_manual_section(record)
            if detected_section:
                record["manual_section"] = detected_section
        
        # 品質ギャップの再評価
        record["quality_gap"] = (record.get("manual_section") is None)
        
        self._save()
        logger.info(f"✅ [Wagamama Ledger] クローズ '{wagamama_id}': 解決策 -> {solution_description[:30]}...")
        
        # マニュアル未記載の場合は警告
        if record["quality_gap"]:
            logger.warning(f"⚠️ [Wagamama Ledger] {wagamama_id} は解決されましたが、USER_MANUALへの紐付けがありません（品質ギャップ）。")
            
        return True

    def set_youtube_video_id(self, wagamama_id: str, youtube_video_id: str) -> bool:
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        if not isinstance(youtube_video_id, str):
            raise TypeError("youtube_video_id must be a string")
        """
        [Fix①: Phase 2 feedback-loop のための video_id 記録]
        動画が公開された時点で、YouTubeのVideo IDを台帳に記録する。
        feedback-loop エンドポイントはこのIDをもとに実際の動画の成績を照会する。
        """
        record = self.get_record(wagamama_id)
        if not record:
            return False
        record["youtube_video_id"] = youtube_video_id
        self._save()
        logger.info(f"📺 [Wagamama Ledger] YouTube Video ID '{youtube_video_id}' set for '{wagamama_id}'")
        return True

    def enterprise_gate_check(self, wagamama_id: str, predicted_ctr: float, min_threshold: float = 3.0) -> dict:
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        if not isinstance(predicted_ctr, (int, float)):
            raise TypeError("predicted_ctr must be a number")
        if not isinstance(min_threshold, (int, float)):
            raise TypeError("min_threshold must be a number")
        import math
        if math.isnan(predicted_ctr) or math.isinf(predicted_ctr):
            raise ValueError("predicted_ctr must be a finite number")
        if math.isnan(min_threshold) or math.isinf(min_threshold):
            raise ValueError("min_threshold must be a finite number")
        """
        [Phase 1.3: Enterprise Assessment Gate]
        企画段階（Pre-Production）でのGo/No-Go判定。
        CTR予測値が閾値を下回る場合、再審議（No-Go）を返す。
        """
        record = self.get_record(wagamama_id)
        if not record:
            return {"status": "error", "message": "Record not found"}

        exp_lane = record["lanes"].setdefault("experience", {})
        exp_lane["predicted_ctr"] = predicted_ctr  # P1 -> P2 受け渡し用
        
        is_go = predicted_ctr >= min_threshold
        gate_result = "Go" if is_go else "No-Go (Revise planning)"
        
        exp_lane["enterprise_gate"] = {
            "predicted_ctr": predicted_ctr,
            "threshold": min_threshold,
            "result": gate_result,
            "timestamp": datetime.now().isoformat()
        }
        
        self._save()
        logger.info(f"🚪 [Wagamama Ledger] Enterprise Gate Check for '{wagamama_id}': {gate_result} (CTR: {predicted_ctr}%)")
        
        return {
            "is_go": is_go,
            "predicted_ctr": predicted_ctr,
            "message": "企画は承認されました" if is_go else f"予測CTR({predicted_ctr}%)が閾値({min_threshold}%)を下回っています。タイトル・サムネ方針の再審議を推奨します。"
        }

    def link_manual_section(self, wagamama_id: str, manual_section: str):
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        if not isinstance(manual_section, str):
            raise TypeError("manual_section must be a string")
        """
        [トリガー: 手動更新 または AI推論]
        USER_MANUALの該当セクションを紐づけし、品質ギャップを解消する
        """
        record = self.get_record(wagamama_id)
        if not record:
            return False

        record["manual_section"] = manual_section
        record["quality_gap"] = False
        self._save()
        logger.info(f"📘 [Wagamama Ledger] マニュアル紐付け '{wagamama_id}' -> {manual_section}")
        return True

    def get_quality_gaps(self) -> List[Dict]:
        """
        マニュアル未記載など、品質ギャップがある項目（実装済みだが文書化されていない項目）を抽出
        四半期ごとの棚卸しやレビュー時に使用
        """
        return [
            {
                "id": r["wagamama_id"],
                "feature": r.get("feature_id"),
                "pain": r.get("lanes", {}).get("experience", {}).get("pain", "Unknown pain")
            }
            for r in self.ledger_data.get("records", [])
            if r.get("status") == "resolved" and r.get("quality_gap") is True
        ]

    def get_record(self, wagamama_id: str) -> Optional[Dict]:
        """指定された wagamama_id のレコードを検索して返す（パブリックAPI）"""
        if not isinstance(wagamama_id, str):
            raise TypeError("wagamama_id must be a string")
        for r in self.ledger_data.get("records", []):
            if r.get("wagamama_id") == wagamama_id:
                return r
        return None

    # DT-02: 後方互換エイリアス（既存の内部呼び出しを壊さないため）
    _find_record = get_record

    def add_distilled_knowledge(self, topic: str, pattern: str, confidence: float = 0.9):
        if not isinstance(topic, str):
            raise TypeError("topic must be a string")
        if not isinstance(pattern, str):
            raise TypeError("pattern must be a string")
        if not isinstance(confidence, (int, float)):
            raise TypeError("confidence must be a number")
        import math
        if math.isnan(confidence) or math.isinf(confidence):
            raise ValueError("confidence must be a finite number")
        """
        [Phase 2: Analyst Knowledge Distiller (Pre-Implementation)]
        A/Bテストや実行結果から得られた成功パターン（蒸留知識）を、Analystが参照可能な領域に保存する.
        現在はWagamama Ledgerの knowledge_base レーンとして簡易記録する.
        """
        knowledge_list = self.ledger_data.setdefault("knowledge_base", [])
        
        # 既存のパターンの重複チェックと更新を行うことも可能だが、今回は追記
        new_knowledge = {
            "id": f"K-{len(knowledge_list) + 1:03d}",
            "topic": topic,
            "pattern": pattern,
            "confidence": confidence,
            "distilled_at": datetime.now().isoformat()
        }
        
        knowledge_list.append(new_knowledge)
        self._save()
        logger.info(f"🧠 [Wagamama Ledger] Distilled Knowledge Added: {topic} -> {pattern[:30]}...")
        return new_knowledge["id"]

# Singleton Instance
wagamama_manager = WagamamaManager()
