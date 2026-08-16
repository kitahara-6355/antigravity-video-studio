r"""字幕焼き付けの経路を守る。

2026-08-17 の実走で見つけた沈黙を再発させないためのテスト。

`-vf subtitles='<path>'` の中では `\` がエスケープ文字として解釈される。
Windows の `os.path.join` が返す `\` をそのまま渡すと、区切りが消えて
`job_xxxsubtitles.srt` になり ffmpeg が開けない。**CI は Linux で `/` なので
この経路は原理的に再現しない。** だから実測で見つかるまで緑のままだった。

さらに悪いのは失敗の握り潰し方で、
`add_subtitles()` が "" を返す → `compose()` の `if subtitled:` が falsy で素通り
→ 字幕なしの動画をそのままコピー → **`success=True`**。
10/10 ステージ完走・品質ゲート PASS で、成果物は入力とバイト一致だった。

ここで守るのは2つ:
  1. フィルタに渡すパスが、区切りを失わない形になっていること
  2. 字幕を焼けと言われて焼けなかったら、成功と言わないこと
"""

import os
from unittest.mock import patch

from backend.video_pipeline.video_composer import VideoComposer

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. フィルタに渡すパスが壊れない
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _captured_vf(composer: VideoComposer, video: str, srt: str) -> str:
    """add_subtitles が組んだ -vf の中身を取り出す。"""
    captured: list[list[str]] = []

    def _capture(cmd):
        captured.append(list(cmd))

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    with patch.object(composer, "_run_ffmpeg", side_effect=_capture):
        composer.add_subtitles(video, srt)

    assert captured, "_run_ffmpeg が呼ばれていない"
    cmd = captured[0]
    return cmd[cmd.index("-vf") + 1]


def test_区切りがエスケープに食われない(tmp_path):
    """フィルタ引数の中に、srt のファイル名が区切り付きで残ること。"""
    composer = VideoComposer(output_dir=str(tmp_path))
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nあ\n", encoding="utf-8")

    vf = _captured_vf(composer, str(tmp_path / "in.mp4"), str(srt))

    # 親ディレクトリ名と subtitles.srt が連結されていたら区切りを失っている
    assert "subtitles.srt" in vf
    assert f"{tmp_path.name}subtitles.srt" not in vf, (
        f"区切りが消えている: {vf}"
    )


def test_フィルタ引数に生のバックスラッシュを残さない(tmp_path):
    """`\\` は ffmpeg のフィルタグラフでエスケープ文字なので、パス区切りに使わない。

    ドライブレターのコロンだけは `\\:` の形で意図的にエスケープするので、
    それ以外の `\\` が無いことを見る。
    """
    composer = VideoComposer(output_dir=str(tmp_path))
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nあ\n", encoding="utf-8")

    vf = _captured_vf(composer, str(tmp_path / "in.mp4"), str(srt))
    path_part = vf.split("subtitles='", 1)[1].split("'", 1)[0]

    assert "\\\\" not in path_part, f"生のバックスラッシュが残っている: {path_part}"
    for i, ch in enumerate(path_part):
        if ch == "\\":
            assert path_part[i + 1 : i + 2] == ":", (
                f"`\\:` 以外のバックスラッシュがある: {path_part}"
            )


def test_ドライブレターのコロンはエスケープする(tmp_path):
    """Windows の絶対パスは `C:` を `C\\:` にしないとフィルタの区切りと衝突する。"""
    composer = VideoComposer(output_dir=str(tmp_path))
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nあ\n", encoding="utf-8")

    vf = _captured_vf(composer, str(tmp_path / "in.mp4"), str(srt))
    path_part = vf.split("subtitles='", 1)[1].split("'", 1)[0]

    drive = os.path.splitdrive(str(srt.resolve()))[0]
    if drive:  # Windows のときだけ意味がある
        assert f"{drive[0]}\\:" in path_part, (
            f"ドライブレターがエスケープされていない: {path_part}"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. 焼けなかったら成功と言わない
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def test_字幕を焼けなかったら成功にしない(tmp_path):
    """**これが本体。** 字幕を指定されて焼けなかったら FAIL にする。

    従来は "" が返ると `if subtitled:` を素通りして、字幕なしの動画を
    そのままコピーしたうえで success=True を返していた。
    """
    composer = VideoComposer(output_dir=str(tmp_path))
    video = tmp_path / "in.mp4"
    video.write_bytes(b"\x00" * 32)
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nあ\n", encoding="utf-8")

    with patch.object(composer, "add_subtitles", return_value=""):
        result = composer.compose(
            video_path=str(video),
            subtitle_path=str(srt),
            output_path=str(tmp_path / "out.mp4"),
        )

    assert result.success is False, "字幕焼きが失敗したのに success=True を返した"
    assert result.error, "失敗の理由が残っていない"


def test_字幕を焼けなかったら入力をそのまま出力しない(tmp_path):
    """入力とバイト一致の成果物を「完成した動画」として残さない。"""
    composer = VideoComposer(output_dir=str(tmp_path))
    video = tmp_path / "in.mp4"
    video.write_bytes(b"\x00" * 32)
    srt = tmp_path / "subtitles.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nあ\n", encoding="utf-8")
    out = tmp_path / "out.mp4"

    with patch.object(composer, "add_subtitles", return_value=""):
        composer.compose(
            video_path=str(video),
            subtitle_path=str(srt),
            output_path=str(out),
        )

    if out.exists():
        assert out.read_bytes() != video.read_bytes(), (
            "字幕なしの入力をそのまま成果物として置いている"
        )


def test_字幕の指定が無いときは従来どおり通す(tmp_path):
    """字幕を頼まれていないなら、焼けなくても失敗ではない（退行防止）。"""
    composer = VideoComposer(output_dir=str(tmp_path))
    video = tmp_path / "in.mp4"
    video.write_bytes(b"\x00" * 32)

    result = composer.compose(
        video_path=str(video),
        output_path=str(tmp_path / "out.mp4"),
    )

    assert result.success is True
