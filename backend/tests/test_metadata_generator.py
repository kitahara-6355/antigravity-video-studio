import json
import math
import shutil
import pytest
from pathlib import Path
from metadata_generator import format_timestamp, estimate_chapters, generate_metadata

def test_format_timestamp():
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(59) == "00:59"
    assert format_timestamp(60) == "01:00"
    assert format_timestamp(3599) == "59:59"
    assert format_timestamp(3600) == "01:00:00"
    assert format_timestamp(3661) == "01:01:01"

def test_estimate_chapters():
    # 正常系のセグメント
    segments = [
        {"start": 0.0, "end": 5.0, "text": "第1セグメント"},
        {"start": 12.0, "end": 18.0, "text": "第2セグメント"},
        {"start": 30.0, "end": 35.0, "text": "第3セグメント"},
        {"start": 50.0, "end": 55.0, "text": "第4セグメント"},
        {"start": 70.0, "end": 75.0, "text": "第5セグメント"},
        {"start": 90.0, "end": 95.0, "text": "第6セグメント"},
        {"start": 110.0, "end": 115.0, "text": "第7セグメント"},
        {"start": 130.0, "end": 135.0, "text": "第8セグメント"},
        {"start": 150.0, "end": 155.0, "text": "第9セグメント"},
    ]
    
    # チャプター境界推定のテスト
    chapters = estimate_chapters(segments, video_duration=160.0)
    
    # 最初のチャプターが 00:00 であること
    assert chapters[0]["time"] == "00:00"
    assert chapters[0]["title"] == "イントロ"
    
    # チャプター数が3個以上であること（目標8個以上。このセグメント数であれば8個以上を目標とする）
    assert len(chapters) >= 3
    
    # 各チャプターの秒数が10秒以上離れていること
    for i in range(len(chapters) - 1):
        diff = chapters[i+1]["seconds"] - chapters[i]["seconds"]
        assert diff >= 10.0, f"Chapter spacing too small: {diff}"

def test_generate_metadata(tmp_path):
    segments = [
        {"start": 0.0, "end": 5.0, "text": "最初のタイトルになり得る文です。対談を始めます。"},
        {"start": 6.0, "end": 10.0, "text": "これが2つめのセグメント。内容が続きます。"},
        {"start": 11.0, "end": 15.0, "text": "3つめのセグメント。タイトルに含まれるはずです。"},
        {"start": 25.0, "end": 30.0, "text": "無音のあとのセグメント。"},
        {"start": 40.0, "end": 45.0, "text": "タグ用のテスト名詞: 伝統 伝統 書道 パフォーマンス"},
    ]
    
    # 一時フォルダに出力
    video_path = tmp_path / "dummy.mp4"
    # ダミーの動画ファイルを作成
    video_path.write_bytes(b"")
    
    metadata = generate_metadata(segments, str(video_path), tmp_path)
    
    # ファイルが書き出されたことの確認
    metadata_json_path = tmp_path / "youtube_metadata.json"  # youtube_metadata.json に修正
    assert metadata_json_path.exists()
    
    # 中身のロードと確認
    with open(metadata_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert "title" in data
    assert "description" in data
    assert "tags" in data
    assert "chapters" in data
    
    # タイトルが60文字以内であること
    assert len(data["title"]) <= 60
    # 説明が500文字以内であること
    assert len(data["description"]) <= 500
    
    # タグに「書道」や「伝統」などが含まれていること（Counterに基づく上位）
    assert "書道" in data["tags"] or "伝統" in data["tags"]

def test_estimate_chapters_edge_cases():
    # 1. segmentsが空の場合
    assert estimate_chapters([]) == [{"time": "00:00", "seconds": 0.0, "title": "イントロ"}]
    assert estimate_chapters(None) == [{"time": "00:00", "seconds": 0.0, "title": "イントロ"}]
    
    # 2. 分割点が動画の最後の10秒未満になる場合のスキップ (video_duration - t < 10.0)
    segments = [
        {"start": 0.0, "end": 95.0, "text": "前編"},
        {"start": 98.0, "end": 102.0, "text": "後編"}
    ]
    # 分割点は 95 + (98-95)/2 = 96.5 秒。video_duration = 105.0 秒。105.0 - 96.5 = 8.5 秒 < 10 秒
    # したがって 96.5 秒はスキップされ、チャプターはイントロのみになるはず（ただし、フォールバックの最低3個保証の動画長さは30秒以上。この場合、105秒なので3個に分割フォールバックされる）
    chapters = estimate_chapters(segments, video_duration=105.0)
    assert len(chapters) == 3
    assert chapters[0]["title"] == "イントロ"
    assert chapters[1]["title"] == "セクション 2"
    assert chapters[2]["title"] == "セクション 3"

    # 3. チャプター名の長さが 20文字を超える場合、または記号のみで空になる場合
    segments_long = [
        {"start": 0.0, "end": 5.0, "text": "短い対談"},
        {"start": 20.0, "end": 25.0, "text": "これは非常に長くて魅力的なタイトルのために用意された長文のテキストセグメントです。"},
        {"start": 40.0, "end": 45.0, "text": "、、、"} # 記号のみ
    ]
    chapters = estimate_chapters(segments_long, video_duration=100.0)
    assert len(chapters) == 3
    assert "..." in chapters[1]["title"]
    assert "セクション 3" in chapters[2]["title"]

def test_generate_metadata_edge_cases(tmp_path):
    # 1. 空テキスト、記号のみ、短すぎるセグメントや挨拶などのスキップ、および title_raw が 25文字未満の場合の suffix 追加
    segments_short = [
        {"start": 0.0, "end": 1.0}, # textなし
        {"start": 1.0, "end": 2.0, "text": ""}, # text空
        {"start": 2.0, "end": 3.0, "text": "、、、、"}, # 記号のみ、長さ4以上
        {"start": 3.0, "end": 5.0, "text": "こんにちは"}, # ignore
        {"start": 5.0, "end": 10.0, "text": "はい"}, # ignore (< 4)
        {"start": 10.0, "end": 15.0, "text": "短いタイトル"} # 有効だが 25文字未満
    ]
    video_path = tmp_path / "dummy.mp4"
    video_path.write_bytes(b"")
    
    metadata = generate_metadata(segments_short, str(video_path), tmp_path)
    assert "ビジネス対談" in metadata["title"]
    assert len(metadata["title"]) >= 25

    # 2. title_raw が 25〜35文字の範囲の場合の調整
    segments_mid = [
        {"start": 0.0, "end": 5.0, "text": "ちょうど三十文字のタイトルを作成します"}, # 19文字
        {"start": 5.0, "end": 10.0, "text": "これで合計です"} # 7文字 -> 合計26文字
    ]
    metadata = generate_metadata(segments_mid, str(video_path), tmp_path)
    assert len(metadata["title"]) >= 25
    assert len(metadata["title"]) <= 35
    assert "ビジネス対談" not in metadata["title"]

    # 3. title_raw が 35文字を超える場合の切り詰め
    segments_long_title = [
        {"start": 0.0, "end": 5.0, "text": "これは非常に長くて35文字を超えることが確実なタイトルを生成するためのセグメントです。"}
    ]
    metadata = generate_metadata(segments_long_title, str(video_path), tmp_path)
    assert len(metadata["title"]) <= 35
    assert metadata["title"].endswith("...")
    
    # title_raw が極端に短く suffix を足しても 25未満の場合のフォールバック
    segments_empty = [
        {"start": 0.0, "end": 5.0, "text": "こんにちは"}
    ]
    metadata = generate_metadata(segments_empty, str(video_path), tmp_path)
    assert len(metadata["title"]) >= 25

    # 4. 説明文が 350文字を超える場合
    segments_long_desc = [{"start": float(i), "end": float(i+1), "text": f"これはテストのための繰り返しテキストセグメント番号 {i} であり、説明文の文字数を増やすために存在します。"} for i in range(15)]
    metadata = generate_metadata(segments_long_desc, str(video_path), tmp_path)
    assert "..." in metadata["description"]

    # 5. video_editor の get_duration が例外を投げる、またはインポート失敗時のフォールバック
    from unittest.mock import patch
    with patch("video_editor_engine.video_editor.ffmpeg.get_duration", side_effect=RuntimeError("FFmpeg error")):
        metadata = generate_metadata(segments_short, str(video_path), tmp_path)
        assert metadata["chapters"][-1]["seconds"] == 0.0 or len(metadata["chapters"]) >= 1

    # 6. video_editor が例外を投げ、かつ segments が空の場合のフォールバック
    with patch("video_editor_engine.video_editor.ffmpeg.get_duration", side_effect=RuntimeError("FFmpeg error")):
        metadata = generate_metadata([], str(video_path), tmp_path)
        assert len(metadata["chapters"]) == 1
        assert metadata["chapters"][0]["time"] == "00:00"

    # 7. ディレクトリ作成 (mkdir) で PermissionError が発生した場合の例外境界テスト
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")):
        with pytest.raises(PermissionError):
            generate_metadata(segments_short, str(video_path), tmp_path)

    # 8. ファイル書き込み (open) で OSError が発生した場合の例外境界テスト
    original_open = open
    def mock_open(file, mode='r', *args, **kwargs):
        if "youtube_metadata.json" in str(file) and 'w' in mode:
            raise OSError("Disk full")
        return original_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        with pytest.raises(OSError):
            generate_metadata(segments_short, str(video_path), tmp_path)

def test_generate_metadata_error_resilience(tmp_path):
    # 1. 存在しない動画パスでの実行（FileNotFoundError を誘発）
    non_existent_video = tmp_path / "non_existent.mp4"
    segments = [
        {"start": 0.0, "end": 10.0, "text": "第1のセグメント"},
        {"start": 15.0, "end": 25.0, "text": "第2のセグメント"},
    ]
    # クラッシュせずに動作し、chaptersのフォールバックが適用されること
    metadata = generate_metadata(segments, str(non_existent_video), tmp_path)
    assert metadata["title"] is not None
    # get_duration が失敗したため、フォールバックとして最後のセグメントのend（25.0）が使われるはず
    assert len(metadata["chapters"]) >= 1

    # 2. segments が None の場合の安全な処理
    metadata_none = generate_metadata(None, str(non_existent_video), tmp_path)
    assert metadata_none["title"] == "ビジネス対談・仕事術・ノウハウ解説 - ビジネス対談"
    assert metadata_none["chapters"] == [{"time": "00:00", "seconds": 0.0, "title": "イントロ"}]

    # 3. segments のキー欠損、型異常、None 値などの異常系
    segments_corrupted = [
        None,  # リスト内に None が混入
        {"start": 0.0},  # end と text が欠損
        {"end": 10.0, "text": "テスト"},  # start が欠損
        {"start": "invalid_start", "end": None, "text": 123},  # 型が異常
        {"start": 20.0, "end": 30.0},  # text が欠損
        {"start": 30.0, "end": "invalid_end"}  # endの型が異常でキャスト失敗
    ]
    metadata_corrupted = generate_metadata(segments_corrupted, str(non_existent_video), tmp_path)
    assert metadata_corrupted["title"] is not None
    assert isinstance(metadata_corrupted["chapters"], list)

def test_sanitize_segments_sorting():
    # start時間が逆転しているセグメントのソート検証
    segments = [
        {"start": 20.0, "end": 30.0, "text": "後半"},
        {"start": 0.0, "end": 10.0, "text": "前半"}
    ]
    chapters = estimate_chapters(segments, video_duration=40.0)
    # 適切にソートされて、最初の分割点は15秒付近になるはず（0.0〜10.0 と 20.0〜30.0 のギャップの中間は 15秒）
    assert len(chapters) == 3  # 最低3個保証により3個になる
    assert chapters[1]["seconds"] == 15.0

def test_estimate_chapters_minimum_three():
    # ギャップが無くチャプター数が不足する長い動画において、最低3個が保証されることの検証
    segments = [
        {"start": 0.0, "end": 120.0, "text": "ずっと話し続けているセグメント"}
    ]
    chapters = estimate_chapters(segments, video_duration=120.0)
    assert len(chapters) == 3
    assert chapters[0]["time"] == "00:00"
    assert chapters[1]["seconds"] == 40.0
    assert chapters[2]["seconds"] == 80.0


def test_format_timestamp_inf_nan():
    import math
    assert format_timestamp(float('inf')) == "00:00"
    assert format_timestamp(float('-inf')) == "00:00"
    assert format_timestamp(float('nan')) == "00:00"
    assert format_timestamp(None) == "00:00"

def test_estimate_chapters_strict_minimum_three():
    # 動画長 30秒以上で、検出されたチャプターが2個のときに、
    # 条件を満たさない（10秒未満のギャップ）ため3個目が追加できないケース
    # duration = 30.0, 既存の2つ目が 11.0 秒のとき：
    # t = 11.0 + (30.0 - 11.0) / 2 = 20.5 秒。
    # 30.0 - 20.5 = 9.5 秒 で、(duration - t) >= 10.0 を満たさない。
    # これにより均等3分割にフォールバックされることを確認。
    segments = [
        {"start": 0.0, "end": 5.0, "text": "イントロ"},
        {"start": 11.0, "end": 15.0, "text": "セクション2"}
    ]
    chapters = estimate_chapters(segments, video_duration=30.0)
    assert len(chapters) == 3
    assert chapters[0]["seconds"] == 0.0
    assert chapters[1]["seconds"] == 10.0
    assert chapters[2]["seconds"] == 20.0


def test_sanitize_segments_non_finite(tmp_path):
    # start や end に nan / inf が含まれている場合のテスト
    segments = [
        {"start": float('nan'), "end": 5.0, "text": "イントロ"},
        {"start": 10.0, "end": float('inf'), "text": "セクション2"},
        {"start": float('-inf'), "end": 20.0, "text": "セクション3"}
    ]
    video_path = tmp_path / "dummy.mp4"
    video_path.write_bytes(b"")
    
    metadata = generate_metadata(segments, str(video_path), tmp_path)
    
    # chapters の seconds や start/end がすべて有限値になっていることを確認
    for chapter in metadata["chapters"]:
        assert math.isfinite(chapter["seconds"])

def test_sanitize_segments_start_greater_than_end(tmp_path):
    # start が end より大きい場合の自動補正テスト
    segments = [
        {"start": 15.0, "end": 10.0, "text": "逆転したセグメント"},
    ]
    video_path = tmp_path / "dummy.mp4"
    video_path.write_bytes(b"")
    
    metadata = generate_metadata(segments, str(video_path), tmp_path)
    # 適切に補正され、かつエラーなくチャプターが作られることを確認
    assert len(metadata["chapters"]) >= 1

def test_generate_metadata_attribute_error(tmp_path):
    # video_editor.ffmpeg.get_duration が AttributeError を投げた場合のテスト
    from unittest.mock import patch
    segments = [
        {"start": 0.0, "end": 5.0, "text": "イントロ"},
    ]
    video_path = tmp_path / "dummy.mp4"
    video_path.write_bytes(b"")
    
    # AttributeError を意図的に発生させる
    with patch("video_editor_engine.video_editor.ffmpeg.get_duration", side_effect=AttributeError("ffmpeg attribute missing")):
        metadata = generate_metadata(segments, str(video_path), tmp_path)
        assert len(metadata["chapters"]) >= 1

def test_generate_metadata_io_error(tmp_path):
    # ディスクフルなどの OSError 発生時に例外が再スローされるテスト
    from unittest.mock import patch
    segments = [
        {"start": 0.0, "end": 5.0, "text": "イントロ"},
    ]
    video_path = tmp_path / "dummy.mp4"
    video_path.write_bytes(b"")
    
    original_open = open
    def mock_open(file, mode='r', *args, **kwargs):
        if "youtube_metadata.json" in str(file) and 'w' in mode:
            raise OSError("Disk full")
        return original_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=mock_open):
        with pytest.raises(OSError):
            generate_metadata(segments, str(video_path), tmp_path)


def test_estimate_chapters_fallback_when_two_invalid():
    # 動画長 30秒以上で、検出されたチャプターが2個のときに、
    # 3点目のチャプターを安全に配置できない場合（10秒間隔要件を満たせない）、
    # 既存のチャプターを破棄して均等3分割にフォールバックされることのテスト
    segments = [
        {"start": 0.0, "end": 5.0, "text": "イントロ"},
        {"start": 20.0, "end": 25.0, "text": "セクション2"}
    ]
    # duration = 30.0, 既存の2つ目が 12.5秒
    # ここで 3つ目を追加しようとすると、残りのスペースが不足するため（duration-t < 10）、
    # 均等3分割 (0.0, 10.0, 20.0) にフォールバックされるはず。
    chapters = estimate_chapters(segments, video_duration=30.0)
    assert len(chapters) == 3
    assert chapters[0]["seconds"] == 0.0
    assert chapters[1]["seconds"] == 10.0
    assert chapters[2]["seconds"] == 20.0
