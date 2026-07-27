"""
test_thumbnail_candidates.py — S9: サムネイル複数候補生成・スコアリングのテスト
"""

import os
from unittest.mock import MagicMock
import pytest
from PIL import Image

from backend.video_pipeline.thumbnail_generator import (
    ThumbnailCandidate,
    ThumbnailGenerator,
    ThumbnailResult,
)


@pytest.fixture
def dummy_video(tmp_path):
    """ダミーの動画ファイルを作成するフィクスチャ。"""
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(b"dummy video content")
    return str(video_file)


@pytest.fixture
def generator(tmp_path):
    """ThumbnailGeneratorのインスタンスを生成するフィクスチャ。"""
    return ThumbnailGenerator(output_dir=str(tmp_path))


def _mock_extract_frame_with_dummy_images(generator, tmp_path):
    """_extract_frame をモックして実際に画像ファイルを生成させるヘルパー。"""
    counter = 0

    def mock_extract(video_path, timestamp, output_suffix=""):
        nonlocal counter
        counter += 1
        img_path = str(tmp_path / f"frame_{counter}{output_suffix}.jpg")
        # それぞれ異なる色合い・パターンの画像を生成
        img = Image.new("RGB", (100, 100), color=(counter * 30 % 255, 100, 150))
        img.save(img_path, "JPEG")
        return img_path

    return mock_extract


def test_generate_candidates_count(dummy_video, generator, tmp_path, monkeypatch):
    """generate_candidates() が指定した数の候補を返すことを検証。"""
    monkeypatch.setattr(
        generator,
        "_extract_frame",
        _mock_extract_frame_with_dummy_images(generator, tmp_path),
    )
    monkeypatch.setattr(generator, "_get_video_duration", lambda v: 10.0)

    candidates = generator.generate_candidates(dummy_video, num_candidates=5)
    assert len(candidates) == 5
    for cand in candidates:
        assert isinstance(cand, ThumbnailCandidate)
        assert os.path.exists(cand.image_path)


def test_candidate_scores_in_range(dummy_video, generator, tmp_path, monkeypatch):
    """各候補のスコアが 0-100 の範囲内であることを検証。"""
    monkeypatch.setattr(
        generator,
        "_extract_frame",
        _mock_extract_frame_with_dummy_images(generator, tmp_path),
    )
    monkeypatch.setattr(generator, "_get_video_duration", lambda v: 10.0)

    candidates = generator.generate_candidates(dummy_video, num_candidates=5)
    assert len(candidates) == 5
    for cand in candidates:
        assert 0.0 <= cand.score <= 100.0
        assert "brightness" in cand.score_details
        assert "contrast" in cand.score_details
        assert "entropy" in cand.score_details


def test_candidates_sorted_descending(dummy_video, generator, tmp_path, monkeypatch):
    """候補がスコア降順でソートされていることを検証。"""
    monkeypatch.setattr(
        generator,
        "_extract_frame",
        _mock_extract_frame_with_dummy_images(generator, tmp_path),
    )
    monkeypatch.setattr(generator, "_get_video_duration", lambda v: 10.0)

    candidates = generator.generate_candidates(dummy_video, num_candidates=5)
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_generate_selects_best_candidate(
    dummy_video, generator, tmp_path, monkeypatch
):
    """generate() が最高スコア候補を選択することを検証。"""
    mock_extract = _mock_extract_frame_with_dummy_images(generator, tmp_path)
    monkeypatch.setattr(generator, "_extract_frame", mock_extract)
    monkeypatch.setattr(generator, "_get_video_duration", lambda v: 10.0)

    result = generator.generate(dummy_video, title="")
    assert result.success is True
    assert isinstance(result, ThumbnailResult)
    assert len(result.candidates) == 5

    best_cand = result.candidates[0]
    assert result.score == best_cand.score
    assert result.source_frame_time == best_cand.source_frame_time


def test_pillow_unavailable_fallback_score(
    dummy_video, generator, tmp_path, monkeypatch
):
    """Pillow未利用時のフォールバックスコア（50.0）を検証。"""
    img_path = str(tmp_path / "test.jpg")
    img = Image.new("RGB", (100, 100), color=(128, 128, 128))
    img.save(img_path)

    monkeypatch.setattr(generator, "_is_pillow_available", lambda: False)

    score, details = generator._score_frame(img_path)
    assert score == 50.0
    assert details == {"brightness": 50.0, "contrast": 50.0, "entropy": 50.0}


def test_generate_candidates_failure_fallback(
    dummy_video, generator, tmp_path, monkeypatch
):
    """generate_candidates() 失敗時、generate() が従来の30%位置にフォールバックすることを検証。"""
    monkeypatch.setattr(generator, "generate_candidates", lambda v, num_candidates=5: [])

    def mock_extract_single(video_path, timestamp, output_suffix=""):
        path = str(tmp_path / "fallback_thumb.jpg")
        img = Image.new("RGB", (100, 100), color=(200, 200, 200))
        img.save(path)
        return path

    monkeypatch.setattr(generator, "_extract_frame", mock_extract_single)
    monkeypatch.setattr(generator, "_get_video_duration", lambda v: 10.0)

    result = generator.generate(dummy_video, title="")
    assert result.success is True
    assert result.source_frame_time == 3.0  # 10.0 * 0.3
    assert os.path.exists(result.image_path)


def test_score_frame_metrics(generator, tmp_path):
    """_score_frame() の明るさ・コントラスト・エントロピー計算が正しく行われることを検証。"""
    # 均一なグレー画像
    flat_path = str(tmp_path / "flat.jpg")
    flat_img = Image.new("RGB", (100, 100), color=(125, 125, 125))
    flat_img.save(flat_path)

    flat_score, flat_details = generator._score_frame(flat_path)
    # 明るさは125ぴったりで100点に近い
    assert flat_details["brightness"] >= 95.0
    # コントラスト（標準偏差0）とエントロピー（全ピクセル同じ）は低め
    assert flat_details["contrast"] == 0.0

    # パターン付き（ノイズ/グラデーション）画像
    pattern_path = str(tmp_path / "pattern.jpg")
    pattern_img = Image.new("RGB", (100, 100))
    pixels = []
    for y in range(100):
        for x in range(100):
            pixels.append((x * 2 % 256, y * 2 % 256, (x + y) * 2 % 256))
    pattern_img.putdata(pixels)
    pattern_img.save(pattern_path)

    pat_score, pat_details = generator._score_frame(pattern_path)
    assert pat_details["contrast"] > 0.0
    assert pat_details["entropy"] > 0.0
