# -*- coding: utf-8 -*-
"""
Quality Unified Unit Tests for Edge Cases and Exception Handling
"""
import sys
import json
import logging
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock, mock_open

# Ensure paths are added
backend_dir = Path(__file__).parent.parent
archives_dir = backend_dir / "archives"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
if str(archives_dir) not in sys.path:
    sys.path.insert(0, str(archives_dir))

from unified.quality_unified import QualityUnified, QualityLevel, QualityResult, quality_unified


def test_load_constitution_file_not_found():
    """constitution.jsonが存在しない場合に空辞書を返すことを検証"""
    with patch("builtins.open", side_effect=FileNotFoundError("Mocked file not found")):
        engine = QualityUnified()
        assert engine._constitution == {}


def test_load_constitution_json_decode_error():
    """constitution.jsonが破損している場合に空辞書を返すことを検証"""
    # JSONDecodeErrorをシミュレート
    mock_file = mock_open(read_data="invalid json data")
    with patch("builtins.open", mock_file):
        engine = QualityUnified()
        assert engine._constitution == {}


def test_comprehensive_check_default_types():
    """check_typesがNoneの場合にデフォルトタイプで実行されることを検証"""
    engine = QualityUnified()
    result = engine.comprehensive_check(content={"text": "テスト"})
    assert result.details["check_types"] == ["spelling", "brand", "rhythm", "consistency"]
    assert result.passed is True
    # 平均スコア (95 + 90 + 88 + 92) / 4 = 91.25 -> EXCELLENT
    assert result.score == 91.25
    assert result.level == QualityLevel.EXCELLENT


def test_comprehensive_check_empty_types():
    """check_typesが空リストの場合にavg_scoreが0、BLOCKEDになることを検証"""
    engine = QualityUnified()
    result = engine.comprehensive_check(content={"text": "テスト"}, check_types=[])
    assert result.score == 0
    assert result.passed is False
    assert result.level == QualityLevel.BLOCKED


def test_comprehensive_check_unknown_type():
    """未知のcheck_typeが指定された場合、スコア100で処理されることを検証"""
    engine = QualityUnified()
    result = engine.comprehensive_check(content={"text": "テスト"}, check_types=["unknown"])
    assert result.score == 100
    assert result.passed is True
    assert result.level == QualityLevel.EXCELLENT


@pytest.mark.parametrize(
    "score,expected_level",
    [
        (100.0, QualityLevel.EXCELLENT),
        (90.0, QualityLevel.EXCELLENT),
        (89.9, QualityLevel.GOOD),
        (80.0, QualityLevel.GOOD),
        (79.9, QualityLevel.WARNING),
        (70.0, QualityLevel.WARNING),
        (69.9, QualityLevel.POOR),
        (60.0, QualityLevel.POOR),
        (59.9, QualityLevel.BLOCKED),
        (0.0, QualityLevel.BLOCKED),
        (-10.0, QualityLevel.BLOCKED),
    ]
)
def test_determine_level(score, expected_level):
    """スコア境界値におけるレベル判定を検証"""
    engine = QualityUnified()
    assert engine._determine_level(score) == expected_level


def test_self_improve_passed_immediately():
    """初期段階で合格している場合に改善ループが走らないことを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=85.0,
        level=QualityLevel.GOOD,
        passed=True,
        issues=[],
        improvements=[],
        details={}
    )
    
    with patch.object(engine, "_apply_improvements") as mock_apply, \
         patch.object(engine, "comprehensive_check") as mock_check:
        
        improved_content, final_result = engine.self_improve(content, initial_result)
        
        # 改善処理が呼ばれていないこと
        mock_apply.assert_not_called()
        mock_check.assert_not_called()
        assert improved_content == content
        assert final_result == initial_result


def test_self_improve_max_attempts():
    """改善しても不合格のままの場合、最大3回でループが終了することを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    
    # 改善後もずっと不合格のままにする
    fail_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    
    with patch.object(engine, "comprehensive_check", return_value=fail_result) as mock_check:
        improved_content, final_result = engine.self_improve(content, initial_result)
        
        # comprehensive_checkが3回呼ばれたこと
        assert mock_check.call_count == 3
        assert len(final_result.improvements) == 3
        assert final_result.improvements == [
            "Attempt 1: 50.0点",
            "Attempt 2: 50.0点",
            "Attempt 3: 50.0点"
        ]


def test_self_improve_becomes_passed():
    """改善ループの途中で合格した場合、そこで終了することを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    
    # 1回目の改善では不合格、2回目の改善で合格にする
    fail_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    success_result = QualityResult(
        score=85.0,
        level=QualityLevel.GOOD,
        passed=True,
        issues=[],
        improvements=[],
        details={}
    )
    
    with patch.object(engine, "comprehensive_check", side_effect=[fail_result, success_result]) as mock_check:
        improved_content, final_result = engine.self_improve(content, initial_result)
        
        # comprehensive_checkが2回しか呼ばれていないこと（3回目は呼ばれない）
        assert mock_check.call_count == 2
        assert len(final_result.improvements) == 1
        assert final_result.improvements == [
            "Attempt 2: 85.0点"
        ]
        assert final_result.passed is True
        assert final_result.score == 85.0


def test_singleton_instance_export():
    """シングルトンインスタンスが正常にインポート可能であることを検証"""
    assert isinstance(quality_unified, QualityUnified)


def test_load_constitution_success():
    """constitution.jsonが正常にロードされた場合に、辞書データが正しく_constitutionにセットされることを検証"""
    mock_data = {
        "content_policy": ["policy1"],
        "brand_personality": {
            "keywords": ["keyword1"]
        }
    }
    with patch("builtins.open", mock_open(read_data=json.dumps(mock_data, ensure_ascii=False))):
        engine = QualityUnified()
        assert engine._constitution == mock_data
        assert engine._constitution["content_policy"] == ["policy1"]


def test_load_constitution_permission_error():
    """constitution.json読み込み時にPermissionErrorが発生した場合に空辞書を返すことを検証"""
    with patch("builtins.open", side_effect=PermissionError("Mocked permission error")):
        engine = QualityUnified()
        assert engine._constitution == {}


def test_apply_improvements_basic():
    """_apply_improvementsがコンテンツをコピーして返すことを検証"""
    engine = QualityUnified()
    content = {"text": "元のテキスト", "flag": True}
    issues = [{"type": "brand", "message": "error"}]
    improved = engine._apply_improvements(content, issues)
    assert improved == content
    assert improved is not content  # コピーであることを確認


def test_load_constitution_os_error():
    """constitution.json読み込み時にOSErrorが発生した場合に空辞書を返すことを検証"""
    with patch("builtins.open", side_effect=OSError("Mocked OS error")):
        engine = QualityUnified()
        assert engine._constitution == {}


def test_comprehensive_check_invalid_content_type():
    """contentがNoneや辞書以外の型だった場合に、クラッシュせずBLOCKEDを返すことを検証"""
    engine = QualityUnified()
    
    # content = None
    result_none = engine.comprehensive_check(None)
    assert result_none.score == 0
    assert result_none.passed is False
    assert result_none.level == QualityLevel.BLOCKED
    assert any("invalid content type" in issue.get("message", "").lower() for issue in result_none.issues)
    
    # content = string
    result_str = engine.comprehensive_check("invalid content type")
    assert result_str.score == 0
    assert result_str.passed is False
    assert result_str.level == QualityLevel.BLOCKED


def test_comprehensive_check_individual_exceptions():
    """個別チェックの中で例外が発生した場合に、comprehensive_checkが中断されずに走りきり、例外発生チェックのスコアが0、エラーissueが追加されることを検証"""
    engine = QualityUnified()
    
    # _check_brand_consistencyが例外を投げるようにモックする
    with patch.object(engine, "_check_brand_consistency", side_effect=ValueError("Brand check system failure")):
        result = engine.comprehensive_check(content={"text": "テスト"})
        
        # 4つのチェックのうち、1つが失敗してスコア0（他は95, 88, 92）
        # 平均: (95 + 0 + 88 + 92) / 4 = 68.75 -> POOR
        assert result.score == 68.75
        assert result.passed is False
        assert result.level == QualityLevel.POOR
        
        # 例外内容がissuesに追加されていること
        assert len(result.issues) > 0
        error_issue = next((issue for issue in result.issues if "Brand check system failure" in issue.get("message", "")), None)
        assert error_issue is not None
        assert error_issue["type"] == "brand_error"


def test_self_improve_improvements_none():
    """initial_resultのimprovementsがNoneの場合でも、例外が発生せずに処理されることを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=None,  # Noneを明示的に指定
        details={}
    )
    
    # 改善処理が走り、improvementsが正常に記録されること
    with patch.object(engine, "comprehensive_check", return_value=QualityResult(
        score=85.0, level=QualityLevel.GOOD, passed=True, issues=[], improvements=[], details={}
    )):
        improved_content, final_result = engine.self_improve(content, initial_result)
        assert final_result.passed is True
        assert final_result.improvements == ["Attempt 1: 85.0点"]


def test_self_improve_apply_improvements_exception():
    """_apply_improvementsで例外が発生した場合にクラッシュせず、最後の有効な結果が返されることを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    
    # _apply_improvementsで例外を発生させる
    with patch.object(engine, "_apply_improvements", side_effect=ValueError("Improvement logic crashed")):
        improved_content, final_result = engine.self_improve(content, initial_result)
        
        # 例外が発生したため、改善処理がスキップ/中断され、最初の結果が返る
        assert improved_content == content
        assert final_result.passed is False
        assert final_result.score == 50.0
        # issuesにエラー情報が追記されていること
        error_issue = next((issue for issue in final_result.issues if "Improvement logic crashed" in issue.get("message", "")), None)
        assert error_issue is not None


def test_determine_level_invalid_score():
    """scoreにNoneや無効な値が指定された場合に、例外にならずBLOCKEDを返すことを検証"""
    engine = QualityUnified()
    assert engine._determine_level(None) == QualityLevel.BLOCKED
    assert engine._determine_level(float("nan")) == QualityLevel.BLOCKED

def test_self_improve_apply_improvements_uncaught_exception():
    """_apply_improvementsで対象外の例外(RuntimeError)が発生した場合に、キャッチされずに呼び出し元へ伝播することを検証"""
    engine = QualityUnified()
    content = {"text": "テストコンテンツ"}
    initial_result = QualityResult(
        score=50.0,
        level=QualityLevel.BLOCKED,
        passed=False,
        issues=[{"type": "spelling", "message": "error"}],
        improvements=[],
        details={}
    )
    
    with patch.object(engine, "_apply_improvements", side_effect=RuntimeError("Fatal system crash")):
        with pytest.raises(RuntimeError) as excinfo:
            engine.self_improve(content, initial_result)
        assert "Fatal system crash" in str(excinfo.value)


def test_comprehensive_check_individual_uncaught_exceptions():
    """個別チェックの中で対象外の例外(RuntimeError)が発生した場合に、キャッチされず伝播することを検証"""
    engine = QualityUnified()
    
    with patch.object(engine, "_check_brand_consistency", side_effect=RuntimeError("Database connection lost")):
        with pytest.raises(RuntimeError) as excinfo:
            engine.comprehensive_check(content={"text": "テスト"})
        assert "Database connection lost" in str(excinfo.value)
