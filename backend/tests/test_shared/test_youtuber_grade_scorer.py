import subprocess
import json
import pytest
from unittest.mock import patch, MagicMock
from backend.graded_previews.youtuber_grade_scorer import (
    get_video_info,
    get_loudness,
    score_against_youtuber_standard
)

@pytest.fixture
def mock_spec_json(tmp_path):
    spec_data = {
      "version": "1.0",
      "categories": {}
    }
    file_path = tmp_path / "youtuber_standard_spec.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(spec_data, f)
    return str(file_path)

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_success(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_stdout = json.dumps({
        "format": {
            "duration": "1200.50",
            "size": "500000000",
            "bit_rate": "3333333"
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 3840,
                "height": 2160,
                "r_frame_rate": "60/1",
                "codec_name": "vp9",
                "bit_rate": "3000000"
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "bit_rate": "320000"
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout, stderr="", returncode=0)
    
    info = get_video_info("dummy_video.mp4")
    
    assert info["resolution"] == "3840x2160"
    assert info["width"] == 3840
    assert info["height"] == 2160
    assert info["frame_rate"] == 60.0
    assert info["video_codec"] == "vp9"
    assert info["duration_sec"] == 1200.50
    assert info["sampling_rate_hz"] == 48000

@patch("os.path.exists")
def test_get_video_info_not_found(mock_exists):
    mock_exists.return_value = False
    with pytest.raises(FileNotFoundError):
        get_video_info("non_existent.mp4")

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_fallback(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = subprocess.SubprocessError("ffprobe error")
    info = get_video_info("dummy_video.mp4")
    
    assert info["resolution"] == "1920x1080"
    assert info["width"] == 1920
    assert info["height"] == 1080
    assert info["frame_rate"] == 30.0

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_loudness_success(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_stderr = """
    some logs
    {
        "input_i" : "-13.50",
        "input_tp" : "-1.0"
    }
    other logs
    """
    mock_run.return_value = MagicMock(stdout="", stderr=mock_stderr, returncode=0)
    
    loudness = get_loudness("dummy_video.mp4")
    assert loudness == -13.50

@patch("os.path.exists")
def test_get_loudness_not_found(mock_exists):
    mock_exists.return_value = False
    loudness = get_loudness("non_existent.mp4")
    assert loudness == -14.0

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_loudness_fallback(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_run.side_effect = subprocess.SubprocessError("ffmpeg error")
    loudness = get_loudness("dummy_video.mp4")
    assert loudness == -14.0

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_excellent(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # 動画の長さは60秒（1分）
    mock_get_video_info.return_value = {
        "resolution": "3840x2160",
        "width": 3840,
        "height": 2160,
        "frame_rate": 60.0,
        "video_codec": "vp9",
        "audio_codec": "aac",
        "video_bitrate_kbps": 40000.0,
        "audio_bitrate_kbps": 320.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 60.0,
        "file_size_bytes": 5000000000
    }
    mock_get_loudness.return_value = -13.5
    
    # 1分間に10個のセグメント = カット頻度10回/分（Excellent）
    # 各セグメントは4秒間で10文字 = 2.5文字/秒（Excellent）
    # 1行最大文字数は10文字（Excellent）
    # セグメント間ギャップは0.5秒（Excellent）
    segments = []
    for i in range(10):
        start = i * 6.0
        end = start + 5.5
        segments.append({
            "start": start,
            "end": end,
            "text": "こんにちは" if i % 2 == 0 else "コメントで教えてください"
        })
        
    metadata = {
        "titles": ["一流YouTuber動画企画の決定版！"],
        "description": "概要文1行目\n概要文2行目\n概要文3行目 http://example.com",
        "tags": ["ビジネス", "教育", "解説", "YouTube", "ノウハウ", "思考", "対談", "勉強", "成長", "お金"],
        "chapters": True
    }
    
    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    
    assert result["total_score"] >= 90
    assert result["grade"] == "A"
    assert "video_technical" in result["category_scores"]
    assert "audio_technical" in result["category_scores"]
    assert "subtitle_spec" in result["category_scores"]
    assert "editing_structure" in result["category_scores"]
    assert "thumbnail_metadata" in result["category_scores"]
    assert "engagement_design" in result["category_scores"]
    assert len(result["gap_analysis"]) == 0

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_medium(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # Good / Acceptable の中間スペック
    mock_get_video_info.return_value = {
        "resolution": "1920x1080",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "video_bitrate_kbps": 10000.0,
        "audio_bitrate_kbps": 192.0,
        "sampling_rate_hz": 44100,
        "duration_sec": 120.0, # 2分
        "file_size_bytes": 100000000
    }
    mock_get_loudness.return_value = -15.5
    
    # 2分動画に12セグメント = カット頻度 6.0回/分 (Good)
    # 平均速度：15文字で3秒 = 5.0文字/秒 (Good)
    # 1行最大文字数 18文字 (Good)
    # セグメント間ギャップは1.2秒 (Good)
    segments = []
    for i in range(12):
        start = i * 10.0
        end = start + 8.8
        segments.append({
            "start": start,
            "end": end,
            "text": "これはちょうどよいテストです"
        })
        
    metadata = {
        "titles": ["かなり普通で良いタイトルですね"],
        "description": "概要文1行目\n概要文2行目",
        "tags": ["ビジネス", "教育", "解説", "YouTube", "ノウハウ"]
    }
    
    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    assert 70 <= result["total_score"] <= 90
    assert result["grade"] in ["B", "C"]

@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_poor(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # 低クオリティ動画のシミュレーション
    mock_get_video_info.return_value = {
        "resolution": "640x360",
        "width": 640,
        "height": 360,
        "frame_rate": 12.0,
        "video_codec": "mpeg4",
        "audio_codec": "mp2",
        "video_bitrate_kbps": 2000.0,
        "audio_bitrate_kbps": 64.0,
        "sampling_rate_hz": 22050,
        "duration_sec": 600.0, # 10分
        "file_size_bytes": 10000000
    }
    mock_get_loudness.return_value = -25.0
    
    # 10分動画に2セグメント = カット頻度 0.2回/分 (Fail)
    # 1秒間に30文字（超早口で読めない、Fail）
    # 1行最大文字数 45文字 (Fail)
    # セグメント間ギャップは4.0秒 (Fail)
    segments = [
        {"start": 1.0, "end": 2.0, "text": "これは一秒の間に非常に多くの文字が詰め込まれていて絶対に読めないような字幕のテストデータです"},
        {"start": 6.0, "end": 7.0, "text": "テスト"}
    ]
    metadata = {
        "titles": ["短い"],
        "description": "短い",
        "tags": ["1つのみ"]
    }
    
    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    
    assert result["total_score"] <= 70
    assert result["grade"] in ["C", "D", "F"]
    assert len(result["gap_analysis"]) > 0


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_exception_fallback(mock_run, mock_exists):
    mock_exists.return_value = True
    # subprocess.run が例外を投げた場合のフォールバックテスト
    mock_run.side_effect = subprocess.SubprocessError("Process failed unexpectedly")
    
    info = get_video_info("dummy_video.mp4")
    assert info["resolution"] == "1920x1080"
    assert info["video_codec"] == "h264"
    assert info["video_bitrate_kbps"] == 12000.0


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_loudness_invalid_json_fallback(mock_run, mock_exists):
    mock_exists.return_value = True
    # 正規表現にマッチしない、または不正なJSON形式の出力
    mock_run.return_value = MagicMock(stdout="", stderr="some random error output without json", returncode=0)
    
    loudness = get_loudness("dummy_video.mp4")
    assert loudness == -14.0


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_loudness_json_parse_error(mock_run, mock_exists):
    mock_exists.return_value = True
    # JSON構造ではあるがパースに失敗するケース
    mock_run.return_value = MagicMock(stdout="", stderr="{invalid_json}", returncode=0)
    
    loudness = get_loudness("dummy_video.mp4")
    assert loudness == -14.0



# -------------------------------------------------------------
# 追加の境界値・例外フォールバック・未カバー箇所のテスト
# -------------------------------------------------------------

@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_single_fps(mock_run, mock_exists):
    mock_exists.return_value = True
    # r_frame_rate に "/" が含まれないケース
    mock_stdout = json.dumps({
        "format": {"duration": "100.0", "size": "1000", "bit_rate": "1000"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30",  # スラッシュなし
                "codec_name": "h264",
                "bit_rate": "800"
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout, stderr="", returncode=0)
    info = get_video_info("dummy.mp4")
    assert info["frame_rate"] == 30.0


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_bitrate_fallback(mock_run, mock_exists):
    mock_exists.return_value = True
    # total_bitrate > 0 且つ video_bitrate_kbps == 0.0
    # audio_bitrate > 0 のケース
    mock_stdout = json.dumps({
        "format": {"duration": "100.0", "size": "100000", "bit_rate": "1000000"}, # 1000 kbps
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "codec_name": "h264"
                # video bitrate なし
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "bit_rate": "200000" # 200 kbps
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout, stderr="", returncode=0)
    info = get_video_info("dummy.mp4")
    assert info["video_bitrate_kbps"] == 800.0 # 1000 - 200

    # audio_bitrate == 0.0 のケース
    mock_stdout_no_audio_br = json.dumps({
        "format": {"duration": "100.0", "size": "100000", "bit_rate": "1000000"}, # 1000 kbps
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "codec_name": "h264"
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout_no_audio_br, stderr="", returncode=0)
    info2 = get_video_info("dummy.mp4")
    assert info2["video_bitrate_kbps"] == 1000.0


@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_boundaries_and_coverage(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # 各種未カバー分岐を満たす入力を与えるテストケース
    mock_get_video_info.return_value = {
        "resolution": "1280x720",
        "width": 1280,
        "height": 720,
        "frame_rate": 45.0,
        "video_codec": "hevc",
        "audio_codec": "aac",
        "video_bitrate_kbps": 6000.0,
        "audio_bitrate_kbps": 160.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 120.0,
        "file_size_bytes": 100000000
    }
    mock_get_loudness.return_value = -17.0

    # 平均表示速度が 5.5超 7.0以下 (avg_speed = 6.5)
    # 1行最大文字数が 18超 22以下 (max_chars_line = 20)
    # カット頻度が 3.0以上 5.0未満 (cuts_per_min = 4.0)
    # 最大無音区間が 1.5秒超 2.2秒以下 (max_gap = 2.0)
    # タイトル文字数が 25以上 35以下 (title_len = 27)
    
    # 2分動画に8個のセグメント = 8/2 = 4.0 回/分
    # 7個のセグメントは 2.0秒で13文字 -> 6.5文字/秒
    # 1個のセグメントは 4.0秒で20文字 -> 5.0文字/秒 (1行最大文字数20)
    segments = []
    for i in range(7):
        start = i * 15.0
        end = start + 2.0
        segments.append({
            "start": start,
            "end": end,
            "text": "あいうえおかきくけこさしす" # 13文字
        })
    segments.append({
        "start": 105.0,
        "end": 109.0,
        "text": "あいうえおかきくけこさしすせそたちつてと" # 20文字
    })

    metadata = {
        "titles": ["これは２５文字以上３５文字以下のタイトル例です"], # 27文字
        "description": "概要文1行目\n概要文2行目\n概要文3行目 http://example.com",
        "tags": ["ビジネス", "教育", "解説", "YouTube", "ノウハウ", "思考", "対談", "勉強", "成長", "お金"],
        "chapters": True
    }

    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    assert "video_technical" in result["category_scores"]
    assert "audio_technical" in result["category_scores"]
    assert "subtitle_spec" in result["category_scores"]
    assert "editing_structure" in result["category_scores"]
    assert "thumbnail_metadata" in result["category_scores"]
    assert "engagement_design" in result["category_scores"]


@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_poor_grade_d_f(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # 総合スコアが低く、D/Fになるケース
    mock_get_video_info.return_value = {
        "resolution": "320x240",
        "width": 320,
        "height": 240,
        "frame_rate": 10.0,
        "video_codec": "unknown",
        "audio_codec": "unknown",
        "video_bitrate_kbps": 100.0,
        "audio_bitrate_kbps": 32.0,
        "sampling_rate_hz": 11025,
        "duration_sec": 60.0, # 1分
        "file_size_bytes": 1000000
    }
    mock_get_loudness.return_value = -30.0

    # 1分動画で2セグメント
    segments = [
        {"start": 0.0, "end": 0.1, "text": "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"}, 
        {"start": 50.0, "end": 50.1, "text": "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"}
    ]

    metadata = {
        "titles": ["短"],
        "description": "短",
        "tags": []
    }

    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    assert result["grade"] in ["D", "F"]


@patch("backend.graded_previews.youtuber_grade_scorer.get_video_info")
@patch("backend.graded_previews.youtuber_grade_scorer.get_loudness")
def test_score_against_youtuber_standard_intermediate_levels(mock_get_loudness, mock_get_video_info, mock_spec_json):
    # 他の未カバー行を個別にカバーするためのテストケース
    mock_get_video_info.return_value = {
        "resolution": "1920x1080",
        "width": 1920,
        "height": 1080,
        "frame_rate": 30.0,
        "video_codec": "h264",
        "audio_codec": "aac",
        "video_bitrate_kbps": 12000.0,
        "audio_bitrate_kbps": 192.0,
        "sampling_rate_hz": 48000,
        "duration_sec": 60.0,
        "file_size_bytes": 90000000
    }
    mock_get_loudness.return_value = -14.0

    # 1.0秒で5文字喋る -> avg_speed = 5.0
    # 17文字
    segments = [
        {"start": 0.0, "end": 3.4, "text": "あいうえおかきくけこさしすせそ"}, # 15文字 / 3.4秒 = 4.4文字/秒
        {"start": 5.0, "end": 8.0, "text": "あいうえおかきくけこさしすせそた"} # 16文字 / 3.0秒 = 5.3文字/秒
    ]

    metadata = {
        "titles": ["タイトル文字数３０文字の非常に優秀なタイトル例です"], # 30文字
        "description": "概要文1行目\n概要文2行目\n概要文3行目 http://example.com",
        "tags": ["ビジネス", "教育", "解説", "YouTube", "ノウハウ", "思考", "対談", "勉強", "成長", "お金"],
        "chapters": True
    }
    result = score_against_youtuber_standard(mock_spec_json, "dummy.mp4", segments, metadata)
    assert result["grade"] in ["A", "B", "C"]


def test_get_grade_from_score():
    from backend.graded_previews.youtuber_grade_scorer import get_grade_from_score
    assert get_grade_from_score(95) == "A"
    assert get_grade_from_score(85) == "B"
    assert get_grade_from_score(75) == "C"
    assert get_grade_from_score(65) == "D"
    assert get_grade_from_score(50) == "F"


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_fps_zero_denominator(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_stdout = json.dumps({
        "format": {
            "duration": "120.0",
            "size": "5000000",
            "bit_rate": "333333"
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/0",
                "codec_name": "h264",
                "bit_rate": "300000"
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout, stderr="", returncode=0)
    
    info = get_video_info("dummy_video.mp4")
    assert info["frame_rate"] == 0.0


@patch("os.path.exists")
@patch("subprocess.run")
def test_get_video_info_other_codec_type(mock_run, mock_exists):
    mock_exists.return_value = True
    mock_stdout = json.dumps({
        "format": {
            "duration": "120.0",
            "size": "5000000",
            "bit_rate": "333333"
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "codec_name": "h264",
                "bit_rate": "300000"
            },
            {
                "codec_type": "subtitle",
                "codec_name": "mov_text"
            }
        ]
    })
    mock_run.return_value = MagicMock(stdout=mock_stdout, stderr="", returncode=0)
    
    info = get_video_info("dummy_video.mp4")
    assert info["resolution"] == "1920x1080"
    assert info["video_codec"] == "h264"

def test_robustness_invalid_types_and_inputs():
    # 1. get_video_info の型異常/空データテスト
    fallback_info = get_video_info(None)
    assert fallback_info["resolution"] == "1920x1080"
    
    fallback_info_empty = get_video_info("")
    assert fallback_info_empty["resolution"] == "1920x1080"
    
    fallback_info_list = get_video_info(["invalid_path"])
    assert fallback_info_list["resolution"] == "1920x1080"

    # 2. get_loudness の型異常/空データテスト
    assert get_loudness(None) == -14.0
    assert get_loudness("") == -14.0
    assert get_loudness(["invalid_path"]) == -14.0

    # 3. score_against_youtuber_standard の不整合データテスト
    # 全て None もしくは不正な型で呼び出す
    result = score_against_youtuber_standard(
        spec_path=None,
        video_path=None,
        segments=None,
        metadata=None
    )
    assert isinstance(result, dict)
    assert "total_score" in result
    assert "grade" in result
    assert "category_scores" in result

    # segments が不整合なリスト（dictでない要素、不正な値など）
    bad_segments = [
        "not_a_dict",
        {"start": "invalid_float", "end": 5.0, "text": None},
        {"start": 1.0, "end": "invalid_float", "text": "hello"}
    ]
    # metadata の titles が list ではない、description が None
    bad_metadata = {
        "titles": "not_a_list",
        "description": None,
        "tags": None
    }
    
    result2 = score_against_youtuber_standard(
        spec_path="non_existent_spec.json",
        video_path="non_existent_video.mp4",
        segments=bad_segments,
        metadata=bad_metadata
    )
    assert isinstance(result2, dict)
    assert result2["total_score"] > 0

def test_robustness_coverage_edge_cases():
    from unittest.mock import patch
    
    # 1. get_video_info で os.path.exists が OSError を投げるケース
    with patch("os.path.exists", side_effect=OSError("Permission denied")):
        res = get_video_info("dummy_video.mp4")
        assert res["resolution"] == "1920x1080"
        
    # 2. get_video_info で subprocess.run が FileNotFoundError (ffprobe が無いなど) を投げるケース
    # 明示的な FileNotFoundError テストが通ることを確認
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run", side_effect=FileNotFoundError("ffprobe not found")):
            try:
                get_video_info("dummy_video.mp4")
                assert False, "Should raise FileNotFoundError"
            except FileNotFoundError:
                pass

    # 3. get_loudness で os.path.exists が OSError を投げるケース
    with patch("os.path.exists", side_effect=OSError("Permission denied")):
        assert get_loudness("dummy_video.mp4") == -14.0

    # 4. score_against_youtuber_standard 内の spec 読み込みで Exception が発生するケース
    # JSONDecodeError などをモック
    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with patch("os.path.exists", return_value=True):
            res = score_against_youtuber_standard(
                spec_path="dummy_spec.json",
                video_path="dummy_video.mp4",
                segments=[],
                metadata={}
            )
            assert isinstance(res, dict)

    # 5. score_against_youtuber_standard 内の get_loudness 呼び出しで Exception が発生するケース
    # get_loudness が例外を投げる
    with patch("backend.graded_previews.youtuber_grade_scorer.get_loudness", side_effect=RuntimeError("Loudness extraction crashed")):
        res = score_against_youtuber_standard(
            spec_path="dummy_spec.json",
            video_path="dummy_video.mp4",
            segments=[],
            metadata={}
        )
        assert isinstance(res, dict)

    # 6. get_video_info 内の r_frame_rate パース時のエッジケース (カバレッジ L74, 90-91, 95-96)
    # ケースA: r_frame_rate が "/abc" や "30/abc" または分母0で ValueError/ZeroDivisionError を起こすケース
    dummy_data_A = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/abc",
                "codec_name": "h264",
                "bit_rate": "12000000"
            }
        ]
    }
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(dummy_data_A)
            mock_run.return_value.stderr = ""
            res = get_video_info("dummy.mp4")
            assert res["frame_rate"] == 0.0

    # ケースB: r_frame_rate が "abc" で "/" なし、floatパースエラーになるケース
    dummy_data_B = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "abc",
                "codec_name": "h264",
                "bit_rate": "12000000"
            }
        ]
    }
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(dummy_data_B)
            mock_run.return_value.stderr = ""
            res = get_video_info("dummy.mp4")
            assert res["frame_rate"] == 0.0

    # ケースC: r_frame_rate が "/" なしの数値文字列 ("30") であるケース (L74 else)
    dummy_data_C = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30",
                "codec_name": "h264",
                "bit_rate": "12000000"
            }
        ]
    }
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(dummy_data_C)
            mock_run.return_value.stderr = ""
            res = get_video_info("dummy.mp4")
            assert res["frame_rate"] == 30.0

    # 7. streams に dict 以外の値が含まれる場合のガードテスト (L74 解決用)
    dummy_data_D = {
        "streams": [
            "not_a_dict_in_streams_list",
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30",
                "codec_name": "h264",
                "bit_rate": "12000000"
            }
        ]
    }
    with patch("os.path.exists", return_value=True):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = json.dumps(dummy_data_D)
            mock_run.return_value.stderr = ""
            res = get_video_info("dummy.mp4")
            assert res["frame_rate"] == 30.0
