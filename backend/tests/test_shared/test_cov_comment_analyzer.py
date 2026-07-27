import pytest
import json
import logging
from unittest.mock import patch, MagicMock
from pathlib import Path
from services.comment_analyzer import CommentAnalyzer

@pytest.fixture
def analyzer():
    return CommentAnalyzer()

def test_analyze_comments_empty(analyzer):
    res = analyzer.analyze_comments([], "test_video")
    assert res["success"] is False
    assert res["message"].encode("utf-8") == bytes.fromhex("e382b3e383a1e383b3e38388e3818ce7a9bae381a7e38199")

def test_sentiment_classification(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        word_pos = bytes.fromhex("e99da2e799bde38184").decode("utf-8")
        res_pos = analyzer.analyze_comments([word_pos], "test_pos")
        assert res_pos["sentiment"]["assessment"].encode("utf-8") == bytes.fromhex("f09f9fa220e9ab98e8a995e4bea1")
        assert res_pos["sentiment"]["positive"] == 1

        word_neg = bytes.fromhex("e381a4e381bee38289e381aae38184").decode("utf-8")
        res_neg = analyzer.analyze_comments([word_neg], "test_neg")
        assert res_neg["sentiment"]["assessment"].encode("utf-8") == bytes.fromhex("f09f94b420e694b9e59684e8a681")
        assert res_neg["sentiment"]["negative"] == 1

        word_neu = bytes.fromhex("e699aee9809a").decode("utf-8")
        res_neu = analyzer.analyze_comments([word_neu], "test_neu")
        assert res_neu["sentiment"]["assessment"].encode("utf-8") == bytes.fromhex("f09f94b420e694b9e59684e8a681")
        assert res_neu["sentiment"]["neutral"] == 1

def test_extact_requests_and_keywords(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        comment_1 = bytes.fromhex("e382b3e383a9e3839ce58b95e794bbe3818ce8a68be3819fe38184e381a7e38199").decode("utf-8")
        comment_2 = bytes.fromhex("e38282e381a3e381a8e38284e381a3e381a6e381bbe38197e38184e381aa").decode("utf-8")
        comment_3 = comment_1
        comment_4 = comment_2

        comments = [comment_1, comment_2, comment_3, comment_4]
        res = analyzer.analyze_comments(comments, "test_req")
        assert len(res["viewer_requests"]) > 0

def test_generate_insights_direct(analyzer):
    insights = analyzer._generate_insights({"positive": 0, "neutral": 0, "negative": 0}, [], [])
    assert insights[0].encode("utf-8") == bytes.fromhex("e382b3e383a1e383b3e38388e695b0e3818ce4b88de8b6b3e38197e381a6e38184e381bee38199e38082")

    insights_pos = analyzer._generate_insights({"positive": 7, "neutral": 2, "negative": 1}, [], [])
    assert bytes.fromhex("e29c8520e8a696e881b4e88085e6ba80e8b6b3e5baa6e3818ce9ab98e38184e38082") in insights_pos[0].encode("utf-8")

    insights_neg = analyzer._generate_insights({"positive": 2, "neutral": 4, "negative": 4}, [], [])
    assert bytes.fromhex("e29aa0efb88f20e3838de382ace38386e382a3e38396e382b3e383a1e383b3e38388e3818c333025") in insights_neg[0].encode("utf-8")

    insights_req = analyzer._generate_insights({"positive": 5, "neutral": 5, "negative": 0}, ["req1", "req2", "req3"], [])
    assert b"3" in insights_req[0].encode("utf-8")

    insights_empty = analyzer._generate_insights({"positive": 5, "neutral": 5, "negative": 0}, [], [])
    assert bytes.fromhex("f09f92a120e382b3e383a1e383b3e38388e58886e69e90e7b590e69e9ce381afe4b8ade7ab8be79a84e381a7e38199e38082") in insights_empty[0].encode("utf-8")

def test_save_analysis_existing_and_rotation(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        for i in range(35):
            res = analyzer.analyze_comments(["test"], f"video_{i}")
            assert res["success"] is True

        data = json.loads(temp_file.read_text(encoding="utf-8"))
        assert len(data) == 30
        assert data[0]["video_id"] == "video_5"

def test_save_analysis_exception(analyzer):
    mock_path = MagicMock(spec=Path)
    mock_path.exists.return_value = False

    with patch("services.comment_analyzer.COMMENTS_FILE", mock_path):
        with patch("services.comment_analyzer.os.replace", side_effect=OSError("Replace error")):
            with patch("services.comment_analyzer.logger.warning") as mock_warn:
                res = analyzer.analyze_comments(["test"], "test_exception")
                assert res["success"] is True
                assert mock_warn.call_count == 1

def test_get_request_trends(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res_no_file = analyzer.get_request_trends()
        assert res_no_file["success"] is False
        assert len(res_no_file["message"]) > 0

        comment_req1 = bytes.fromhex("e382b3e383a1e38388e3818ce7a9bae381a7e38199").decode("utf-8")
        comment_req1 = bytes.fromhex("e382b3e383a9e3839ce58b95e794bbe3818ce8a68be3819fe38184e381a7e38199").decode("utf-8")
        comment_req2 = bytes.fromhex("e38282e381a3e381a8e38284e381a3e381a6e381bbe38197e38184e381aa").decode("utf-8")
        analyzer.analyze_comments([comment_req1, comment_req1, comment_req2], "video_trend")
        res_trends = analyzer.get_request_trends()
        assert res_trends["success"] is True
        assert res_trends["total_requests"] == 3
        assert len(res_trends["unique_requests"]) == 2

        mock_path = MagicMock(spec=Path)
        mock_path.exists.return_value = True
        mock_path.read_text.side_effect = OSError("Read error")
        with patch("services.comment_analyzer.COMMENTS_FILE", mock_path):
            res_err = analyzer.get_request_trends()
            assert res_err["success"] is False
            assert "Read error" in res_err["message"]

# --- 以下、堅牢化に伴う新規追加テストケース ---

def test_analyze_comments_invalid_types(analyzer, tmp_path):
    # comments が None
    res = analyzer.analyze_comments(None)
    assert res["success"] is False
    assert "コメントが空です" in res["message"]

    # comments が リスト/タプル ではない
    res = analyzer.analyze_comments("not a list")
    assert res["success"] is False
    assert "無効な入力データ" in res["message"]

    # video_id が str ではない
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.analyze_comments(["test_comment"], 12345)
        assert res["success"] is True
        assert res["video_id"] == "12345"

        # video_id が None
        res = analyzer.analyze_comments(["test_comment"], None)
        assert res["success"] is True
        assert res["video_id"] == ""

    # comments リスト内に非文字列が混在（クレンジングされて 3 件になること）
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.analyze_comments(["valid_comment", None, 123, True], "mixed")
        assert res["success"] is True
        assert res["total_comments"] == 3

        # 全て None などの無効値の場合のガード
        res_empty = analyzer.analyze_comments([None, None])
        assert res_empty["success"] is False
        assert "コメントが空です" in res_empty["message"]

def test_classify_sentiment_invalid_type(analyzer):
    # 非文字列が渡された場合
    assert analyzer._classify_sentiment(None) == "neutral"
    assert analyzer._classify_sentiment(123) == "neutral"

def test_extract_requests_tuple_edge_cases(analyzer):
    # 非文字列が渡された場合
    assert analyzer._extract_requests(None) == []
    
    with patch.object(analyzer, 'REQUEST_PATTERNS', [r'(a)(b)?']):
        res = analyzer._extract_requests("aaaaaa bbbbbb")
        assert isinstance(res, list)

    # 想定外のオブジェクトがマッチ結果に含まれる場合（else句のカバー）
    with patch("services.comment_analyzer.re.findall") as mock_findall:
        mock_findall.return_value = [123456]
        res = analyzer._extract_requests("test")
        assert len(res) == 3
        assert res[0] == "123456"

def test_extract_keywords_invalid_type(analyzer):
    # 非文字列が渡された場合
    assert analyzer._extract_keywords(None) == []

def test_save_analysis_directory_creation(analyzer, tmp_path):
    deep_dir = tmp_path / "subdir1" / "subdir2"
    temp_file = deep_dir / "comments.json"
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.analyze_comments(["test"], "video_new_dir")
        assert res["success"] is True
        assert temp_file.exists()

def test_save_analysis_invalid_json_format(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    temp_file.write_text("{ invalid json }", encoding="utf-8")
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.analyze_comments(["test"], "video_invalid_json")
        assert res["success"] is True
        data = json.loads(temp_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["video_id"] == "video_invalid_json"

def test_save_analysis_non_list_json(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    temp_file.write_text('{"key": "value"}', encoding="utf-8")
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.analyze_comments(["test"], "video_non_list_json")
        assert res["success"] is True
        data = json.loads(temp_file.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == 1

def test_get_request_trends_invalid_json(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    temp_file.write_text("{ invalid json }", encoding="utf-8")
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.get_request_trends()
        assert res["success"] is False
        assert "分析データが破損しています" in res["message"]

def test_get_request_trends_non_list_json(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    temp_file.write_text('{"key": "value"}', encoding="utf-8")
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.get_request_trends()
        assert res["success"] is False
        assert "分析データの形式が不正です" in res["message"]

def test_get_request_trends_non_dict_entry(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    temp_file.write_text('[{"viewer_requests": ["req1"]}, "invalid_entry"]', encoding="utf-8")
    
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        res = analyzer.get_request_trends()
        assert res["success"] is True
        assert res["total_requests"] == 1

def test_extract_requests_first_pattern(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        comment_request = "次はこれを作ってください"
        res = analyzer.analyze_comments([comment_request], "test_req_pattern_0")
        assert res["success"] is True
        assert len(res["viewer_requests"]) == 1
        assert res["viewer_requests"][0] == "次はこれを作って"

def test_save_analysis_atomic_cleanup(analyzer, tmp_path):
    temp_file = tmp_path / "comments.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        bad_result = {"unserializable": MagicMock()}
        # warning ログをモックし、シリアライズ不能な値で save_analysis を実行
        with patch("services.comment_analyzer.logger.warning") as mock_warn:
            analyzer._save_analysis(bad_result)
            assert mock_warn.call_count == 1
            
        # 一時ファイルが残っていないことを確認
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

def test_analyze_comments_ultra_long(analyzer, tmp_path):
    # 超大容量コメント（ReDoS対策・切り詰め処理の検証）
    temp_file = tmp_path / "comments_long.json"
    with patch("services.comment_analyzer.COMMENTS_FILE", temp_file):
        long_comment = "あ" * 50000 + "次はこれを作ってください"
        res = analyzer.analyze_comments([long_comment], "test_ultra_long")
        assert res["success"] is True
        assert len(res["viewer_requests"]) == 0

def test_save_analysis_attribute_error_robustness(analyzer):
    # _save_analysis 内で AttributeError が発生した場合の堅牢性検証
    with patch("services.comment_analyzer.COMMENTS_FILE", None):
        with patch("services.comment_analyzer.logger.warning") as mock_warn:
            res = analyzer.analyze_comments(["test"], "test_attr_error")
            assert res["success"] is True
            assert mock_warn.call_count == 1
