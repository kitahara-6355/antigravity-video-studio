import os
import json
import pytest
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# プロジェクトルートを追加
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if os.path.join(project_root, "backend") not in sys.path:
    sys.path.insert(0, os.path.join(project_root, "backend"))

from backend.agents.memory.verified_facts import VerifiedFactsStore
from backend.agents.memory.technical_debt import TechnicalDebtStore
from backend.agents.memory.council_decision_extractor import (
    CouncilDecisionExtractor,
    ExtractorInputGuardrail,
    ExtractorQuantitativeMapping,
    ExtractorSafetyFallback
)


@pytest.fixture
def temp_facts_and_debt_stores(monkeypatch):
    """本番データを汚染しないためのテスト用一時ストアフィクスチャ。"""
    with tempfile.TemporaryDirectory() as tmpdir_facts, tempfile.TemporaryDirectory() as tmpdir_debt:
        facts_path = Path(tmpdir_facts)
        debt_path = Path(tmpdir_debt)
        
        # テスト用の独立したストアインスタンスを作成
        test_facts_store = VerifiedFactsStore(facts_dir=facts_path)
        test_debt_store = TechnicalDebtStore(debt_dir=debt_path)
        
        # モジュール内のシングルトンをテスト用ストアで置換
        monkeypatch.setattr(
            "backend.agents.memory.council_decision_extractor.verified_facts_store", 
            test_facts_store
        )
        monkeypatch.setattr(
            "backend.agents.memory.council_decision_extractor.technical_debt_store", 
            test_debt_store
        )
        
        yield test_facts_store, test_debt_store


# ==============================================================
# 1. 入力ガードレール (Input Guardrail) のテスト
# ==============================================================

def test_input_guardrail_valid_data():
    # 正常なデータ
    valid_data = {
        "session_id": "session-123",
        "synthesis": "今回の合議により、新しいアーキテクチャ設計を採用することを決定しました。",
        "debate_flow": [
            {"agent": "Analyst", "summary": "データ分析に基づき、提案を支持します。"}
        ]
    }
    validated = ExtractorInputGuardrail.validate_log_data(valid_data)
    assert validated["session_id"] == "session-123"


def test_input_guardrail_valid_json_string():
    # JSON文字列形式での入力
    valid_json = json.dumps({
        "session_id": "session-456",
        "synthesis": "ビデオ演出に関する編集ルールを策定しました。",
        "debate_flow": []
    })
    validated = ExtractorInputGuardrail.validate_log_data(valid_json)
    assert validated["session_id"] == "session-456"


def test_input_guardrail_invalid_input_types():
    # 無効な型
    with pytest.raises(ValueError, match="指定されていません"):
        ExtractorInputGuardrail.validate_log_data(None)
        
    with pytest.raises(ValueError, match="辞書型または有効な JSON 文字列である必要があります"):
        ExtractorInputGuardrail.validate_log_data([1, 2, 3])


def test_input_guardrail_missing_synthesis():
    # 必須キー欠損
    invalid_data = {
        "session_id": "session-789"
        # synthesis がない
    }
    with pytest.raises(ValueError, match="synthesis"):
        ExtractorInputGuardrail.validate_log_data(invalid_data)


def test_input_guardrail_suspicious_patterns():
    # インジェクションパターン検知
    suspicious_data = {
        "session_id": "session-injection",
        "synthesis": "import os; os.system('echo hack')",
        "debate_flow": []
    }
    with pytest.raises(ValueError, match="不審な文字パターン"):
        ExtractorInputGuardrail.validate_log_data(suspicious_data)


def test_input_guardrail_huge_payload():
    # サイズ制限超過
    huge_str = "a" * (1024 * 1024 + 10)  # 1MB を少し超えるサイズ
    with pytest.raises(ValueError, match="サイズが制限"):
        ExtractorInputGuardrail.validate_log_data(huge_str)


# ==============================================================
# 2. 定量的マッピング (Quantitative Mapping) のテスト
# ==============================================================

def test_quantitative_mapping_low_complexity():
    # 短いログ（低複雑度）
    log_data = {
        "synthesis": "演出案を採用する。",  # ~9文字
        "debate_flow": [
            {"agent": "Analyst", "summary": "了解。"}  # ~3文字
        ]
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "LOW"
    assert params["max_facts"] == 2
    assert params["confidence_threshold"] == 0.8


def test_quantitative_mapping_medium_complexity():
    # 中規模ログ
    synthesis = "合議結果として、以下の3つの仕様を確定仕様とします。\n" + "1. テロップのカラーは白文字に黒縁とする。\n" * 10
    log_data = {
        "synthesis": synthesis,
        "debate_flow": [
            {"agent": "Director", "summary": "演出方法についての合意が形成されました。"}
        ]
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "MEDIUM"
    assert params["max_facts"] == 5
    assert params["confidence_threshold"] == 0.85


def test_quantitative_mapping_high_complexity():
    # 大規模ログ（高複雑度）
    synthesis = "詳細な戦略ロードマップの策定。\n" + "この件について、メンバー間で以下の通り合意形成を行いました。\n" + "仕様決定: 音声の最大デシベルは-3dBとする。\n" * 40
    log_data = {
        "synthesis": synthesis,
        "debate_flow": [
            {"agent": "Strategist", "summary": "長期的なスケール戦略について分析と議論を行いました。"},
            {"agent": "Analyst", "summary": "競合動画の維持率データを提示し、それに基づく調整に合意しました。"},
            {"agent": "Director", "summary": "動画編集およびエフェクトに関する詳細設計を確定しました。"}
        ]
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "HIGH"
    assert params["max_facts"] == 8
    assert params["confidence_threshold"] == 0.90


# ==============================================================
# 3. セーフティフォールバック (Safety Fallback) のテスト
# ==============================================================

def test_safety_fallback_registers_debt_and_fact(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores
    
    # 意図的にエラーを渡してフォールバック実行
    session_id = "test-fallback-session-999"
    result = ExtractorSafetyFallback.execute_fallback(
        error_msg="テスト用のパースエラー",
        session_id=session_id,
        file_path="backend/tests/test_council_decision_extractor.py",
        line_number=42
    )
    
    assert result["status"] == "fallback"
    assert session_id in result["extracted_facts"][0]
    
    # 1. 技術負債に正しく登録されたか検証
    debts = debt_store.get_open_entries()
    assert len(debts) == 1
    assert debts[0].category == "ACCEPTED_SAFETY"
    assert debts[0].file_path == "backend/tests/test_council_decision_extractor.py"
    assert "test-fallback-session-999" in debts[0].notes

    # 2. VerifiedFacts にデフォルト記録が書き込まれたか検証
    facts = facts_store.get_facts_by_category("progress")
    assert len(facts) == 1
    assert facts[0].category == "progress"
    assert session_id in facts[0].content


# ==============================================================
# 4. 意思決定の抽出機能と自動記録メインフローのテスト
# ==============================================================

def test_extract_decisions_logic():
    synthesis = (
        "## 合議サマリー\n"
        "本日の合議で以下の内容を決定しました。\n"
        "- アーキテクチャの基本設計として、Vite を採用することを決定しました。\n"
        "- また、ユーザーの好みを反映し、ダークモードの配色を HSL で定義することに合意しました。\n"
        "確定仕様としては、すべての動画出力形式を MP4 とする。\n"
        "学んだ教訓として、ffmpeg の同時実行スレッド数は最大2と決定。"
    )
    debate_flow = [
        {"agent": "Analyst", "summary": "性能データを元に、スレッド数制限を推奨する。"},
        {"agent": "Director", "summary": "ダークモードの採用に合意。"}
    ]
    
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, debate_flow)
    
    # 抽出された決定の数と中身を検証
    assert len(decisions) >= 3
    
    # Vite 採用が synthesis から抽出されていること
    assert any("Vite" in text for text, src in decisions)
    # 確定仕様 MP4 が入っていること
    assert any("MP4" in text for text, src in decisions)
    # 教訓 ffmpeg スレッド数が入っていること
    assert any("ffmpeg" in text for text, src in decisions)


def test_process_and_record_success(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores

    log_data = {
        "session_id": "session-success-100",
        "synthesis": (
            "合議で決定された事項は以下の通りです。\n"
            "- バックエンドのAPIバージョンを v2 に変更することを決定しました。\n"
            "- トーン＆マナーとして、ビビッドな配色を好む傾向を反映し、サムネイルのフォントサイズを72pxに決定。"
        ),
        "debate_flow": [
            {"agent": "Director", "summary": "サムネイルのフォントサイズ72px案を採用することを合意。"}
        ]
    }

    result = CouncilDecisionExtractor.process_and_record(log_data)
    
    assert result["status"] == "success"
    assert result["session_id"] == "session-success-100"
    assert len(result["extracted_facts"]) >= 2
    
    # VerifiedFacts ストアの中身を確認
    # APIバージョン変更 (カテゴリはデフォルトで progress、または判定条件による)
    # サムネイルフォントサイズ (好みにマッチするので preference になるはず)
    pref_facts = facts_store.get_facts_by_category("preference")
    assert len(pref_facts) == 1
    assert "フォントサイズ" in pref_facts[0].content

    # インデックスファイルと Markdown がアトミックに書き込まれているか確認
    assert os.path.exists(facts_store.facts_path)
    assert os.path.exists(facts_store.index_path)

    # 技術負債が登録されていないことを確認（正常終了時のため）
    assert len(debt_store.get_open_entries()) == 0


def test_process_and_record_no_decisions_safety_net(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores

    # 決定に関するキーワードが一切含まれない曖昧なログ
    log_data = {
        "session_id": "session-empty-200",
        "synthesis": "今日の対話では、特に具体的な合意には至りませんでした。雑談を中心に行いました。",
        "debate_flow": []
    }

    result = CouncilDecisionExtractor.process_and_record(log_data)
    
    assert result["status"] == "success"
    assert len(result["extracted_facts"]) == 1
    # 安全弁としてのprogressファクトが登録されていること
    assert "完了し" in result["extracted_facts"][0]
    
    progress_facts = facts_store.get_facts_by_category("progress")
    assert len(progress_facts) == 1
    assert "session-empty-200" in progress_facts[0].content


def test_process_and_record_invalid_input_fallback(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores

    # 不正な入力（synthesis がない）
    bad_log_data = {
        "session_id": "session-bad-300"
    }

    result = CouncilDecisionExtractor.process_and_record(bad_log_data)
    
    # ValueError を検知し、Safety Fallback が実行されて status="fallback" になること
    assert result["status"] == "fallback"
    
    # 技術負債と VerifiedFacts にそれぞれフォールバック情報が登録されていること
    assert len(debt_store.get_open_entries()) == 1
    assert len(facts_store.get_facts_by_category("progress")) == 1


def test_input_guardrail_size_boundaries():
    # ちょうど 1MB (1,048,576 バイト)
    base_data = {
        "session_id": "session-boundary",
        "synthesis": "正常な合議内容",
        "debate_flow": []
    }
    base_json = json.dumps(base_data, ensure_ascii=False)
    base_len = len(base_json.encode("utf-8"))
    
    # ちょうど 1MB になるように余白を埋める
    padding_len = 1048576 - base_len - 15  # "padding": "..." の分を考慮
    padded_data = {
        "session_id": "session-boundary",
        "synthesis": "正常な合議内容",
        "debate_flow": [],
        "padding": "x" * padding_len
    }
    padded_json = json.dumps(padded_data, ensure_ascii=False)
    
    # 微調整
    actual_len = len(padded_json.encode("utf-8"))
    if actual_len < 1048576:
        padded_data["padding"] += "x" * (1048576 - actual_len)
        padded_json = json.dumps(padded_data, ensure_ascii=False)
    elif actual_len > 1048576:
        padded_data["padding"] = padded_data["padding"][:- (actual_len - 1048576)]
        padded_json = json.dumps(padded_data, ensure_ascii=False)
        
    assert len(padded_json.encode("utf-8")) == 1048576
    validated = ExtractorInputGuardrail.validate_log_data(padded_json)
    assert validated["session_id"] == "session-boundary"

    # 1MB + 1バイト (1,048,577 バイト)
    padded_data["padding"] += "y"
    too_large_json = json.dumps(padded_data, ensure_ascii=False)
    
    # 微調整
    actual_len = len(too_large_json.encode("utf-8"))
    if actual_len < 1048577:
        padded_data["padding"] += "y" * (1048577 - actual_len)
        too_large_json = json.dumps(padded_data, ensure_ascii=False)
    elif actual_len > 1048577:
        padded_data["padding"] = padded_data["padding"][:- (actual_len - 1048577)]
        too_large_json = json.dumps(padded_data, ensure_ascii=False)

    assert len(too_large_json.encode("utf-8")) == 1048577
    with pytest.raises(ValueError, match="サイズが制限"):
        ExtractorInputGuardrail.validate_log_data(too_large_json)


def test_input_guardrail_suspicious_patterns_case_sensitivity():
    # 大文字小文字の混在したインジェクションコード
    suspicious_cases = [
        "Import Os",
        "IMPORT OS",
        "Subprocess.Popen",
        "SUBPROCESS.",
        "Eval('1+1')",
        "EVAL(",
        "Exec('a=1')",
        "EXEC(",
        "<Script>",
        "<SCRIPT>"
    ]
    for case in suspicious_cases:
        suspicious_data = {
            "session_id": "session-injection-case",
            "synthesis": f"コード: {case}",
            "debate_flow": []
        }
        with pytest.raises(ValueError, match="不審な文字パターン"):
            ExtractorInputGuardrail.validate_log_data(suspicious_data)


def test_quantitative_mapping_boundaries():
    # 長さ199 (LOW)
    log_data_199 = {
        "synthesis": "a" * 199,
        "debate_flow": []
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data_199)
    assert params["complexity_level"] == "LOW"
    assert params["max_facts"] == 2

    # ちょうど 200 文字 (MEDIUM)
    log_data_200 = {
        "synthesis": "a" * 200,
        "debate_flow": []
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data_200)
    assert params["complexity_level"] == "MEDIUM"
    assert params["max_facts"] == 5

    # ちょうど 999 文字 (MEDIUM)
    log_data_999 = {
        "synthesis": "a" * 999,
        "debate_flow": []
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data_999)
    assert params["complexity_level"] == "MEDIUM"
    assert params["max_facts"] == 5

    # ちょうど 1000 文字 (HIGH)
    log_data_1000 = {
        "synthesis": "a" * 1000,
        "debate_flow": []
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data_1000)
    assert params["complexity_level"] == "HIGH"
    assert params["max_facts"] == 8


def test_safety_fallback_with_exception_object(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores

    # 例外オブジェクトが発生したと仮定してフォールバック処理を呼び出し
    try:
        raise RuntimeError("想定外のパースエラーが発生しました")
    except Exception as e:
        err_msg = str(e)
        result = ExtractorSafetyFallback.execute_fallback(
            error_msg=err_msg,
            session_id="session-exception-400",
            file_path="backend/tests/test_council_decision_extractor.py",
            line_number=350
        )
        
    assert result["status"] == "fallback"
    assert "session-exception-400" in result["extracted_facts"][0]
    
    # 技術負債が正しく登録されているか確認
    debts = debt_store.get_open_entries()
    assert len(debts) == 1
    assert "session-exception-400" in debts[0].notes
    assert "RuntimeError" in debts[0].notes or "想定外のパースエラー" in debts[0].notes


def test_safety_fallback_dynamic_exception_trace(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores
    
    # 1. 明示的な line_number を指定せず、例外コンテキストもない場合（デフォルト値が使われるはず）
    result = ExtractorSafetyFallback.execute_fallback(
        error_msg="No context error",
        session_id="no-ctx-session"
    )
    assert result["status"] == "fallback"
    debts = debt_store.get_open_entries()
    assert len(debts) == 1
    assert debts[0].line_number == 100 # デフォルト値
    
    # 2. 例外コンテキストが存在し、引数で line_number を指定しない場合（動的に例外発生箇所が取得されるはず）
    try:
        # 意図的に例外を発生させる
        x = 1 / 0
    except ZeroDivisionError as e:
        result2 = ExtractorSafetyFallback.execute_fallback(
            error_msg=str(e),
            session_id="zero-div-session"
        )
        
    debts2 = debt_store.get_open_entries()
    assert len(debts2) == 2
    # 動的に取得された行番号が zero-div-session の notes に含まれ、かつ line_number が 1 / 0 の行付近であることを検証
    target_debt = next(d for d in debts2 if d.notes and "zero-div-session" in d.notes)
    assert target_debt.line_number > 100  # デフォルトの100より大きいはず
    assert "test_council_decision_extractor.py" in target_debt.file_path


def test_input_guardrail_invalid_debate_flow_types():
    # debate_flow の entry 内の値が不正な型の場合
    bad_data_1 = {
        "session_id": "session-bad-flow-1",
        "synthesis": "正常な合議内容",
        "debate_flow": [
            {"agent": 123, "summary": "発言内容が文字列ではない"} # agent が数値
        ]
    }
    with pytest.raises(ValueError, match="'agent' は文字列である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data_1)

    bad_data_2 = {
        "session_id": "session-bad-flow-2",
        "synthesis": "正常な合議内容",
        "debate_flow": [
            {"agent": "Analyst", "summary": ["リスト形式の発言", "これはNG"]} # summary がリスト
        ]
    }
    with pytest.raises(ValueError, match="'summary' は文字列である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data_2)


def test_quantitative_mapping_invalid_elements():
    # debate_flow に辞書以外の要素が混ざっている、または summary が None の場合
    # resolve_parameters がクラッシュせずに動くことを確認
    log_data = {
        "synthesis": "合議内容",
        "debate_flow": [
            "不正な文字列要素", # 辞書ではない
            {"agent": "Analyst", "summary": None}, # summary が None
            {"agent": "Director"} # summary が存在しない
        ]
    }
    
    # クラッシュせずにパラメータが解決できること
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "LOW"
    assert params["calculated_length"] > 0


def test_extract_decisions_robustness():
    # extract_decisions に直接、不正な形式の debate_flow が渡された場合の堅牢性
    synthesis = "- 合議で Vite を採用することを決定しました。"
    bad_flow = [
        "不正な文字列", # 辞書ではない
        {"agent": "Analyst", "summary": None}, # summary が None
        {"agent": "Director", "summary": "仕様Aを採用することを決定。"} # 正常
    ]
    
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, bad_flow)
    assert len(decisions) >= 2
    assert any("Vite" in text for text, src in decisions)
    assert any("仕様A" in text for text, src in decisions)


# ==============================================================
# 5. カバレッジ向上のための追加テスト
# ==============================================================

def test_input_guardrail_suspicious_patterns_json_string():
    # JSON文字列でのインジェクションパターン検出 (行61)
    suspicious_json = json.dumps({
        "session_id": "session-injection-json",
        "synthesis": "import os; os.system('echo hack')",
        "debate_flow": []
    })
    with pytest.raises(ValueError, match="不審な文字パターン"):
        ExtractorInputGuardrail.validate_log_data(suspicious_json)


def test_input_guardrail_invalid_json_format():
    # JSONDecodeError ハンドリング (行65-66)
    with pytest.raises(ValueError, match="JSON のデコードに失敗しました"):
        ExtractorInputGuardrail.validate_log_data("{invalid_json_format")


def test_input_guardrail_invalid_synthesis_types():
    # synthesis フィールドが無効な型の場合のバリデーション (行77)
    bad_data_1 = {
        "session_id": "session-bad-synthesis-1",
        "synthesis": "",  # 空の文字列
        "debate_flow": []
    }
    with pytest.raises(ValueError, match="'synthesis' は非空の文字列または辞書である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data_1)

    bad_data_2 = {
        "session_id": "session-bad-synthesis-2",
        "synthesis": 12345,  # 数値型
        "debate_flow": []
    }
    with pytest.raises(ValueError, match="'synthesis' は非空の文字列または辞書である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data_2)


def test_input_guardrail_synthesis_dict_type():
    # synthesis が辞書型の場合の処理 (行82)
    dict_synthesis_data = {
        "session_id": "session-dict-synthesis",
        "synthesis": {
            "summary": "今回の合議により、新しいアーキテクチャ設計を採用することを決定しました。",
            "details": "詳細設計書に準拠します。"
        },
        "debate_flow": []
    }
    validated = ExtractorInputGuardrail.validate_log_data(dict_synthesis_data)
    assert validated["session_id"] == "session-dict-synthesis"


def test_input_guardrail_invalid_debate_flow_type():
    # debate_flow がリスト形式ではない場合 (行94)
    bad_data = {
        "session_id": "session-bad-flow-type",
        "synthesis": "正常な合議内容",
        "debate_flow": "not_a_list"  # 文字列型
    }
    with pytest.raises(ValueError, match="'debate_flow' はリスト形式である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data)


def test_input_guardrail_debate_flow_entry_not_dict():
    # debate_flow の要素が辞書型ではない場合 (行98)
    bad_data = {
        "session_id": "session-bad-flow-entry",
        "synthesis": "正常な合議内容",
        "debate_flow": ["not_a_dict"]  # 文字列型要素
    }
    with pytest.raises(ValueError, match="'debate_flow' の要素は辞書型である必要があります"):
        ExtractorInputGuardrail.validate_log_data(bad_data)


def test_input_guardrail_debate_flow_suspicious_patterns():
    # debate_flow 内の不審な文字パターン検出 (行110)
    suspicious_data = {
        "session_id": "session-bad-flow-suspicious",
        "synthesis": "正常な合議内容",
        "debate_flow": [
            {"agent": "Analyst", "summary": "System.exit(0)"}
        ]
    }
    with pytest.raises(ValueError, match="debate_flow 内に不審な文字パターンが検出されました"):
        ExtractorInputGuardrail.validate_log_data(suspicious_data)


def test_safety_fallback_debt_store_exception(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores
    # Fallback 時の技術負債登録エラー（ValueError, OSError）ハンドリング (行211-212)
    with patch.object(debt_store, 'register_debt', side_effect=OSError("Disk full simulated")):
        result = ExtractorSafetyFallback.execute_fallback(
            error_msg="テスト用のパースエラー",
            session_id="session-debt-err",
            file_path="backend/tests/test_council_decision_extractor.py",
            line_number=42
        )
        assert result["status"] == "fallback"
        assert "session-debt-err" in result["extracted_facts"][0]


def test_safety_fallback_vf_store_exception(temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores
    # Fallback 時の VerifiedFacts 登録エラー（OSError）ハンドリング (行226-227)
    with patch.object(facts_store, 'add_fact', side_effect=OSError("Write error simulated")):
        result = ExtractorSafetyFallback.execute_fallback(
            error_msg="テスト用のパースエラー",
            session_id="session-vf-err",
            file_path="backend/tests/test_council_decision_extractor.py",
            line_number=42
        )
        assert result["status"] == "fallback"
        assert result["extracted_facts"] == []  # 書き込みエラーのため空になる


def test_categorize_fact_various_categories():
    # _categorize_fact 内のカテゴリ決定 (行261, 265, 267)
    # architecture
    assert CouncilDecisionExtractor._categorize_fact("新しいモジュール構成を決定した") == "architecture"
    # specification
    assert CouncilDecisionExtractor._categorize_fact("タイムアウトの閾値を5秒に設定した") == "specification"
    # lesson
    assert CouncilDecisionExtractor._categorize_fact("ffmpegのバグに対する教訓を得た") == "lesson"
    # progress (default)
    assert CouncilDecisionExtractor._categorize_fact("通常のミーティングを実施しました") == "progress"


def test_extract_decisions_with_empty_lines():
    # 空行のスキップ (行285)
    synthesis = "合議で決定された事項は以下の通りです。\n\n- アーキテクチャ構成として Vite を採用決定。\n\n"
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    assert len(decisions) >= 1
    assert any("Vite" in d[0] for d in decisions)


def test_extract_decisions_bullet_keywords():
    # 箇条書きでパターンマッチしないがキーワードを含む場合の補足 (行304-306)
    # ハイフンの直後に「決定」が来ることで正規表現マッチを回避し、箇条書きフォールバックをトリガーする
    synthesis = "-決定された方針については後述する。"
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    assert len(decisions) >= 1
    assert any("決定された方針" in d[0] for d in decisions)


def test_extract_decisions_debate_flow_negation():
    # debate_flow 内の否定表現によるスキップ (行320)
    debate_flow = [
        {"agent": "Analyst", "summary": "この件については決定には至りませんでした。"},
        {"agent": "Director", "summary": "新機能を適用することに決定。"}
    ]
    decisions = CouncilDecisionExtractor.extract_decisions("サマリー", debate_flow)
    # 最初のものはスキップされ、2番目のものだけ抽出されるはず
    assert len(decisions) == 1
    assert "Director" in decisions[0][0]


@patch("backend.agents.memory.council_decision_extractor.ExtractorInputGuardrail.validate_log_data")
def test_process_and_record_type_error_exception(mock_validate, temp_facts_and_debt_stores):
    # process_and_record 内の想定外の例外ハンドリング (行413-415)
    mock_validate.side_effect = TypeError("Mocked TypeError for system error test")
    result = CouncilDecisionExtractor.process_and_record({"synthesis": "dummy"})
    assert result["status"] == "fallback"
    assert "想定外のシステムエラー" in result["error"]


# ==============================================================
# 6. ブランチカバレッジ向上のための追加テスト
# ==============================================================

def test_input_guardrail_debate_flow_missing_summary():
    # debate_flow の entry で summary が None または存在しないケース (行105->96)
    log_data_missing_summary = {
        "session_id": "session-missing-summary",
        "synthesis": "正常な合議内容",
        "debate_flow": [
            {"agent": "Analyst"},  # summary が存在しない
            {"agent": "Director", "summary": None},  # summary が None
            {"agent": "Designer", "summary": "UIデザインを決定した"}  # 正常
        ]
    }
    validated = ExtractorInputGuardrail.validate_log_data(log_data_missing_summary)
    assert validated["session_id"] == "session-missing-summary"


def test_quantitative_mapping_non_list_debate_flow():
    # resolve_parameters で debate_flow がリストではないケース (行131->139)
    log_data = {
        "synthesis": "合議内容",
        "debate_flow": "not_a_list"
    }
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "LOW"
    assert params["max_facts"] == 2


def test_safety_fallback_empty_traceback(temp_facts_and_debt_stores):
    # execute_fallback で traceback はあるが tb_list が空のケース (行185->194)
    # traceback.extract_tb をモックして空リストを返すようにする
    with patch("traceback.extract_tb", return_value=[]):
        try:
            raise RuntimeError("Test error")
        except RuntimeError as e:
            result = ExtractorSafetyFallback.execute_fallback(
                error_msg=str(e),
                session_id="session-empty-tb"
            )
    assert result["status"] == "fallback"
    # デフォルトの行番号が使われていることを確認
    facts_store, debt_store = temp_facts_and_debt_stores
    debts = debt_store.get_open_entries()
    assert len(debts) == 1
    assert debts[0].line_number == 100  # デフォルト値


def test_extract_decisions_short_matched_val():
    # synthesis から抽出されたマッチテキストが 5 文字以下のケース (行298->295)
    synthesis = "aと決定"  # マッチした val が 'aと決定' で長さ 4 <= 5
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    # 5文字以下のため候補から除外され、結果が空になることを確認
    assert len(decisions) == 0


def test_extract_decisions_short_bullet_val():
    # 箇条書きのクリーン結果が 10 文字以下のケース (行305->282)
    synthesis = "-決定"  # クリーン後は '決定' で長さ 2 <= 10
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    # 10文字以下のため候補から除外され、結果が空になることを確認
    assert len(decisions) == 0


def test_extract_decisions_debate_flow_no_keywords():
    # debate_flow の要約に決定キーワードが含まれないケース (行322->309)
    debate_flow = [
        {"agent": "Analyst", "summary": "通常の議論を行ったが、結論は出ず。"}
    ]
    decisions = CouncilDecisionExtractor.extract_decisions("サマリー", debate_flow)
    assert len(decisions) == 0


def test_extract_decisions_debate_flow_short_summary():
    # debate_flow の要約が短く、クリーン後 10 文字以下のケース (行324->309)
    debate_flow = [
        {"agent": "Director", "summary": "Vite採用に合意。"}  # クリーン後 'Vite採用に合意。' は 9文字
    ]
    decisions = CouncilDecisionExtractor.extract_decisions("サマリー", debate_flow)
    assert len(decisions) == 0


def test_extract_decisions_duplicate_normalization():
    # 重複する決定（表記揺れを含む）が存在する場合に重複を除外するケース (行333->330)
    synthesis = (
        "- APIバージョンを v2 に変更することを決定しました。\n"
        "- APIバージョンを v2 に変更することを決定しました！\n"  # 記号のみ異なる
    )
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    # 正規化（記号除去）により重複とみなされ、1つだけ抽出されることを確認
    assert len(decisions) == 1
    assert "変更することを決定しました" in decisions[0][0]


# ==============================================================
# 7. Phase 33 追加エッジケーステスト
# ==============================================================

def test_quantitative_mapping_complex_length():
    # synthesis が辞書形式、かつ debate_flow が非文字列オブジェクトを含む場合の定量パラメータ決定
    log_data = {
        "synthesis": {
            "key1": "a" * 50,
            "key2": "b" * 50
        },
        "debate_flow": [
            {"agent": "Analyst", "summary": 1234567890},  # 数値
            {"agent": "Director", "summary": True}         # ブール値
        ]
    }
    # 計算された文字数 (synthesis の json.dumps 長 ＋ summary 達の長さ)
    # json.dumps({"key1": "...", "key2": "..."}) -> 約130文字
    # summary 達 -> len("1234567890") + len("True") = 14文字
    # 合計 144文字 前後 (< 200 文字) -> LOW になるはず
    params = ExtractorQuantitativeMapping.resolve_parameters(log_data)
    assert params["complexity_level"] == "LOW"
    assert params["max_facts"] == 2
    assert params["confidence_threshold"] == 0.8
    assert params["calculated_length"] > 100


def test_input_guardrail_unknown_keys():
    # debate_flow 内のエントリに未知のメタデータフィールドが存在してもバリデーションを通過すること
    valid_data = {
        "session_id": "session-unknown-keys",
        "synthesis": "正常な合議内容",
        "debate_flow": [
            {
                "agent": "Analyst",
                "summary": "分析データを提示して合意した。",
                "timestamp": "2026-06-23T12:00:00Z",
                "metadata": {"score": 0.95}
            }
        ]
    }
    validated = ExtractorInputGuardrail.validate_log_data(valid_data)
    assert validated["session_id"] == "session-unknown-keys"
    assert len(validated["debate_flow"]) == 1
    assert "metadata" in validated["debate_flow"][0]


def test_extract_decisions_special_bullet_patterns():
    # 特殊な箇条書きプレフィックスや番号付き箇条書きのパースと決定抽出
    synthesis = (
        "1. 新モジュールの採用を決定。\n"
        "2) データベース接続の上限を50に合意。\n"
        "【決定】フォントサイズは24pxとする。\n"
        "・カラーパレットに青を採用することを決定。\n"
    )
    decisions = CouncilDecisionExtractor.extract_decisions(synthesis, [])
    
    assert len(decisions) >= 2
    assert any("新モジュール" in text for text, src in decisions)
    assert any("データベース接続" in text for text, src in decisions)


@patch("backend.agents.memory.council_decision_extractor.verified_facts_store.add_fact")
def test_process_and_record_mocked_exceptions(mock_add_fact, temp_facts_and_debt_stores):
    facts_store, debt_store = temp_facts_and_debt_stores
    
    # 最初の add_fact でのみ KeyError を投げ、フォールバックでの add_fact は通すように side_effect を設定
    def side_effect_fn(*args, **kwargs):
        if kwargs.get("category") != "progress" or "Safety Fallback" not in kwargs.get("evidence", ""):
            raise KeyError("Simulated KeyError during add_fact")
        mock_fact = MagicMock()
        mock_fact.content = "フォールバックファクト"
        return mock_fact

    mock_add_fact.side_effect = side_effect_fn
    
    log_data = {
        "session_id": "session-mocked-key-error",
        "synthesis": "新しい設計を採用することを決定した。",
        "debate_flow": []
    }
    
    result = CouncilDecisionExtractor.process_and_record(log_data)
    
    # KeyError がキャッチされてフォールバック処理に入るはず
    assert result["status"] == "fallback"
    assert "想定外のシステムエラー" in result["error"]
    assert "KeyError" in result["error"]
    
    # 技術負債ストアに登録されていること
    debts = debt_store.get_open_entries()
    assert len(debts) == 1
    assert debts[0].category == "ACCEPTED_SAFETY"
    assert "KeyError" in debts[0].notes






