import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from wagamama_manager import wagamama_manager
import sys
# Prevent instance mismatch from duplicate imports
if "backend.wagamama_manager" not in sys.modules:
    import backend.wagamama_manager
sys.modules["backend.wagamama_manager"] = sys.modules["wagamama_manager"]

from decision_logger import decision_logger
from agents.council_logger import council_logger

@pytest.fixture(autouse=True)
def setup_test_environment(tmp_path):
    # テスト用のテンポラリパスを作成
    temp_ledger = tmp_path / "wagamama_ledger.json"
    temp_decision = tmp_path / "decision_log.json"
    temp_manual = tmp_path / "USER_MANUAL.md"
    temp_evolution = tmp_path / "evolution_log.json"
    
    # 元のパスを退避
    orig_ledger_path = wagamama_manager.store._path
    orig_decision_file = decision_logger.log_file
    orig_log_dir = decision_logger.log_dir
    orig_manual_path = getattr(wagamama_manager, "manual_path", None)
    
    # パスを差し替え
    wagamama_manager.store._path = temp_ledger
    wagamama_manager.manual_path = temp_manual
    decision_logger.log_file = temp_decision
    decision_logger.log_dir = tmp_path
    
    # データをクリアして初期化
    wagamama_manager.ledger_data = {
        "version": "1.0",
        "name": "Wagamama Ledger",
        "description": "Multi-user story management registry",
        "records": []
    }
    wagamama_manager._save()
    
    decision_logger.decisions = []
    decision_logger._save()
    
    # 一時マニュアルの作成
    temp_manual.write_text(
        "# USER MANUAL\n\n## §4.1 NHK基準字幕\nNHKの字幕基準についての説明です。\n\n## §4.2 音声マスタリング\n音声についての説明です。\n",
        encoding="utf-8"
    )
    
    yield
    
    # 元に戻す
    wagamama_manager.store._path = orig_ledger_path
    if orig_manual_path is not None:
        wagamama_manager.manual_path = orig_manual_path
    else:
        if hasattr(wagamama_manager, "manual_path"):
            del wagamama_manager.manual_path
    decision_logger.log_file = orig_decision_file
    decision_logger.log_dir = orig_log_dir
    decision_logger._load()
    wagamama_manager._load()

def test_wagamama_auto_pain_detection():
    """
    同一タグで却下/修正が2回連続した場合にwagamama_ledger.jsonに自動起票されるか検証
    """
    # 1回目の却下
    decision_logger.record_decision(
        target_type="screenshot",
        target_path="previews/scene_001.png",
        target_description="Scene 1 Preview",
        decision="reject",
        reason="字幕のフォントサイズが小さすぎてNHK基準を満たしていない",
        tags=["NHK基準", "字幕フォント"]
    )
    
    # 2回目の却下（同一タグ「NHK基準」を含む）
    decision_logger.record_decision(
        target_type="screenshot",
        target_path="previews/scene_002.png",
        target_description="Scene 2 Preview",
        decision="reject",
        reason="字幕の色が背景と同化して見づらい、NHK基準に違反",
        tags=["NHK基準", "字幕カラー"]
    )
    
    # 同期処理を実行
    decision_logger.sync_to_soul_narrative()
    
    # 自動起票されたストーリーを確認
    records = wagamama_manager.ledger_data.get("records", [])
    assert len(records) == 1
    story = records[0]
    assert story["wagamama_id"] == "W-001"
    assert story["feature_id"] == "NHK基準"
    assert story["status"] == "investigating"
    assert "字幕の色が背景と同化して見づらい" in story["lanes"]["experience"]["pain"]

def test_council_auto_link():
    """
    wagamama_idを指定せずに評議会セッションを記録した際、トピックから関連ストーリーが自動検出されて紐づけられるか検証
    """
    # あらかじめストーリーを起票しておく
    w_id = wagamama_manager.create_experience_story(
        user_voice="字幕のフォントサイズが小さすぎてNHK基準を満たしていない",
        detected_by="nexus",
        feature_id="NHK基準"
    )
    
    # 評議会ログの記録（wagamama_idなし、トピック「NHK基準についての議論」）
    synthesis = {"summary": "フォントサイズを32px以上に修正することで合意"}
    council_logger.log_session(
        session_id="session-999",
        topic="NHK基準についての議論",
        debate_data=[],
        synthesis=synthesis
    )
    
    # ストーリーの状態を確認
    story = wagamama_manager.get_record(w_id)
    assert story["status"] == "in_debate"
    assert story["lanes"]["experience"]["council"]["session_id"] == "session-999"
    assert "フォントサイズを32px以上" in story["lanes"]["experience"]["council"]["synthesis"]

def test_wagamama_auto_resolution_and_manual_check():
    """
    承認時に自動クローズされ、USER_MANUAL.mdの見出し自動スキャンにより品質ギャップが判定されるか検証
    """
    # 1. 進行中ストーリーの準備
    w_id = wagamama_manager.create_experience_story(
        user_voice="字幕のフォントサイズが小さすぎてNHK基準を満たしていない",
        detected_by="nexus",
        feature_id="NHK基準"
    )
    # 評議会で議論中
    wagamama_manager.link_council_session(w_id, "sess-123", "log.json", {"summary": "解決策検討中"})
    
    # 2. 承認（approve）の記録
    decision_logger.record_decision(
        target_type="screenshot",
        target_path="previews/scene_001_v2.png",
        target_description="Scene 1 Preview v2",
        decision="approve",
        reason="フォントサイズが大きくなり、NHK基準を満たしたため承認",
        tags=["NHK基準", f"wagamama_id:{w_id}"]
    )
    
    # 同期処理を実行
    decision_logger.sync_to_soul_narrative()
    
    # 3. 解決状態の検証
    story = wagamama_manager.get_record(w_id)
    assert story["status"] == "resolved"
    # マニュアル「## §4.1 NHK基準字幕」に「NHK基準」が部分一致するため自動紐付けされるはず
    assert story["manual_section"] == "§4.1 NHK基準字幕"
    assert story["quality_gap"] is False
    
    # 4. マニュアルにないfeature_idの場合にquality_gapがTrueになることを検証
    w_id2 = wagamama_manager.create_experience_story(
        user_voice="トランジション効果が激しすぎる",
        detected_by="nexus",
        feature_id="トランジション効果"
    )
    wagamama_manager.resolve_story(w_id2, "トランジション効果を抑制")
    story2 = wagamama_manager.get_record(w_id2)
    assert story2["status"] == "resolved"
    assert story2["manual_section"] is None
    assert story2["quality_gap"] is True
