"""
FV検証用 Ground Truth データ — TV-01 (tv01_real_clip.mp4)

TV-01のWhisperチェックポイント出力を正解データとして定義。
FV-01 (WER) と FV-02 (セグメント品質) で使用する。

注意: Whisperの出力はそのまま使用。FV-01では「再実行時の一貫性」を検証する。
"""

# TV-01のWhisper出力テキスト（正解テキスト）
# 各セグメントの text フィールドを連結
TV01_GROUND_TRUTH_TEXTS = [
    "では、記念すべき第1回目のゲストは、日本デザイン処動作家協会日次庁で、デザイン処動の第一人者、クキタヒロノブ先生です。",
    "お願いいたします。",
    "こんにちは。もう初回にね、呼んでいただいて、声でございます。",
    "ありがとうございます。",
    "恐縮しています。",
    "先生は株式会社、稼し合った代表で クキタデザイン所導塾主催",
    "そして一般社団法人日本デザイン所導 佐賀教会の理事長でいらっしゃいまして",
    "著者としても筆文字デザインの 書籍が多数終わりだということなんですが",
    "まず先生が最初に初に出会った きっかけというのは何かありますでしょうか",
    "その当時僕はダガシアによく行ってましたよね",
    "はい",
    "で、ダガシアの隣に引き戻がある建物があったんですよ",
    "はい",
    "これが興味があったんで、こう引いたらそこが正道教授さん",
    "あ、へぇそういう出会いなんですね",
    "え、しかも僕は幼稚園から幼馴染みだった加藤不尼子君がそこにいたんですよ",
    "そうか、はい",
    "でびっくりしちゃって",
    "ダガシアなんか言ってる場合じゃないやってどういうわけだか思ったのか",
    "母親に僕も修士入れていって言って",
    "それが",
    "8歳以来",
    "小学校3年生です",
    "行ったんですよ",
    "猛逸ですか",
    "3って書いても覚えてるんですけど",
    "知ったらもう",
    "周りから笑われて",
    "それで泣きながら帰ったっていうのが僕のデビューなんですよ。",
    "デビューですか?",
    "うん。",
    "それが良かったんじゃないですか?",
    "しかね、そう思いして次回、次の週から行かなくなったってことはないので、",
    "あのー…",
    "克服しようとする感じですか?",
    "そう、何かやっぱり好きだ。",
]

# TV-01のセグメントタイムスタンプ（正解時刻）
TV01_GROUND_TRUTH_TIMESTAMPS = [
    {"start": 0.0, "end": 14.0},
    {"start": 14.0, "end": 15.0},
    {"start": 15.0, "end": 19.0},
    {"start": 19.0, "end": 20.0},
    {"start": 20.0, "end": 21.0},
    {"start": 21.0, "end": 29.7},
    {"start": 29.7, "end": 37.14},
    {"start": 37.14, "end": 43.94},
    {"start": 43.94, "end": 50.64},
    {"start": 50.64, "end": 54.64},
    {"start": 54.64, "end": 55.64},
    {"start": 55.64, "end": 60.64},
    {"start": 60.64, "end": 61.64},
    {"start": 61.64, "end": 67.64},
    {"start": 67.64, "end": 69.64},
    {"start": 69.64, "end": 75.64},
    {"start": 75.64, "end": 77.64},
    {"start": 77.64, "end": 80.52},
    {"start": 80.52, "end": 85.36},
    {"start": 85.36, "end": 90.36},
    {"start": 90.36, "end": 93.16},
    {"start": 93.16, "end": 94.84},
    {"start": 94.84, "end": 96.72},
    {"start": 96.72, "end": 97.64},
    {"start": 97.64, "end": 98.92},
    {"start": 98.92, "end": 101.8},
    {"start": 101.8, "end": 103.52},
    {"start": 103.52, "end": 106.44},
    {"start": 106.44, "end": 110.04},
    {"start": 110.04, "end": 111.04},
    {"start": 111.04, "end": 112.04},
    {"start": 112.04, "end": 114.04},
    {"start": 114.04, "end": 119.04},
    {"start": 119.04, "end": 120.04},
    {"start": 120.04, "end": 122.04},
    {"start": 122.04, "end": 124.04},
]

# TV-01の全テキスト（連結）
TV01_REFERENCE_TEXT = " ".join(TV01_GROUND_TRUTH_TEXTS)

# TV-01のセグメント数
TV01_SEGMENT_COUNT = len(TV01_GROUND_TRUTH_TEXTS)

# TV-01の総尺（秒）
TV01_TOTAL_DURATION = 124.04


def get_ground_truth_segments():
    """Ground Truthセグメントリストを返す（チェックポイント形式）"""
    if TV01_GROUND_TRUTH_TEXTS is None or TV01_GROUND_TRUTH_TIMESTAMPS is None:
        raise ValueError("Ground Truth text or timestamp list cannot be None.")

    try:
        len_texts = len(TV01_GROUND_TRUTH_TEXTS)
        len_timestamps = len(TV01_GROUND_TRUTH_TIMESTAMPS)
    except TypeError as e:
        raise TypeError("Ground Truth data lists must be iterable and support len().") from e

    if len_texts != len_timestamps:
        raise ValueError(
            f"Mismatched data lengths: TV01_GROUND_TRUTH_TEXTS ({len_texts}) and "
            f"TV01_GROUND_TRUTH_TIMESTAMPS ({len_timestamps}) must have the same size."
        )

    segments = []
    for i, (text, ts) in enumerate(
        zip(TV01_GROUND_TRUTH_TEXTS, TV01_GROUND_TRUTH_TIMESTAMPS)
    ):
        if not isinstance(ts, dict):
            raise TypeError(f"Timestamp at index {i} must be a dictionary.")
        if "start" not in ts or "end" not in ts:
            raise KeyError(f"Timestamp dict at index {i} must contain both 'start' and 'end' keys.")

        start = ts["start"]
        end = ts["end"]

        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            raise TypeError(f"Timestamp values at index {i} must be int or float.")
        if start > end:
            raise ValueError(f"Invalid timestamp range at index {i}: start ({start}) cannot be greater than end ({end}).")
        if not isinstance(text, str):
            raise TypeError(f"Text value at index {i} must be a string.")

        segments.append({
            "start": start,
            "end": end,
            "text": text,
            "sourceStart": start,
            "sourceEnd": end,
        })
    return segments
