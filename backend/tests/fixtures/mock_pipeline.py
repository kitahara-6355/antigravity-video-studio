"""
PipelineContext & セグメントのモックファクトリ

MASTER v3.6 モックデータカタログ (MD-01〜MD-07) 対応。
全Workerのユニットテストで使用する標準的なテストデータ生成関数を提供。

使用例:
    from fixtures.mock_pipeline import create_mock_ctx, create_mock_segments

    ctx = create_mock_ctx(segments=10)               # MD-03: 標準
    ctx = create_mock_ctx(segments=0)                 # MD-01: 空
    ctx = create_mock_ctx(segments=50)                # MD-04: 大量
    ctx = create_mock_ctx(corrupt=True)               # MD-05: 破損データ
    ctx = create_mock_ctx(type_error=True)             # MD-06: 型不正
    ctx = create_mock_ctx(segments=100)                # MD-07: 長尺
"""

import copy
import sys
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

# backend ディレクトリをパスに追加（テストからのインポート解決用）
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_coordinator import PipelineContext, StageResult


# ============================================================
# セグメント生成
# ============================================================

# リアルなテキストサンプル（Whisper出力に近い日本語テキスト）
_SAMPLE_TEXTS = [
    "では、記念すべき第1回目のゲストをご紹介します。",
    "お願いいたします。",
    "こんにちは。もう初回にね、呼んでいただいて、光栄でございます。",
    "ありがとうございます。",
    "恐縮しています。",
    "先生のデザインに対する考え方を伺いたいんですけど。",
    "デザインというのはですね、一言で言えば問題解決なんです。",
    "見た目を美しくするだけではなく、本質的な課題に向き合うこと。",
    "それはすごく大事なことですよね。",
    "ユーザーの体験を常に中心に据えることが重要です。",
    "技術は手段であって、目的ではないということですね。",
    "まさにその通りです。テクノロジーは人を幸せにするためにある。",
    "最近のAIの進化についてはどう思われますか？",
    "AIは道具として非常に強力ですが、使い方次第です。",
    "クリエイティブな分野でもAIは活用できると思いますか？",
    "もちろんです。ただし、人間の感性が最終判断を下すべきです。",
    "なるほど。それは興味深い視点ですね。",
    "常にユーザー視点で考えることを忘れないこと。",
    "本日はありがとうございました。",
    "こちらこそ。楽しい時間でした。",
]


def create_mock_segments(
    count: int = 10,
    duration_each: float = 15.0,
    corrupt: bool = False,
    type_error: bool = False,
    start_offset: float = 0.0,
    with_source_times: bool = True,
) -> List[Dict[str, Any]]:
    """テスト用セグメントリストを生成

    Args:
        count: セグメント数
        duration_each: 各セグメントの秒数
        corrupt: True → text欠落、start>end を混入 (MD-05)
        type_error: True → start=str, end=None を混入 (MD-06)
        start_offset: 開始時刻のオフセット（秒）
        with_source_times: sourceStart/sourceEnd を含めるか

    Returns:
        セグメントのリスト。各セグメントは dict で
        {"start", "end", "text", "sourceStart", "sourceEnd"} を含む。
    """
    segments = []
    for i in range(count):
        start = start_offset + i * duration_each
        end = start + duration_each
        text = _SAMPLE_TEXTS[i % len(_SAMPLE_TEXTS)]

        seg: Dict[str, Any] = {
            "start": start,
            "end": end,
            "text": text,
        }

        if with_source_times:
            seg["sourceStart"] = start
            seg["sourceEnd"] = end

        # MD-05: 破損データ — 5個に1個を破損
        if corrupt and i % 5 == 3:
            del seg["text"]  # text フィールド欠落
        if corrupt and i % 5 == 4:
            seg["start"] = end + 10  # start > end

        # MD-06: 型不正データ — 4個に1個を型不正
        if type_error and i % 4 == 2:
            seg["start"] = str(seg["start"])  # float → str
        if type_error and i % 4 == 3:
            seg["end"] = None  # float → None

        segments.append(seg)
    return segments


# ============================================================
# PipelineContext 生成
# ============================================================

def create_mock_ctx(
    segments: int = 10,
    video_path: str = "",
    target_minutes: int = 20,
    corrupt: bool = False,
    type_error: bool = False,
    with_selected: bool = False,
    template_id: Optional[str] = None,
    session_id: str = "test-session-001",
    duration_each: float = 15.0,
) -> PipelineContext:
    """PipelineContext モックファクトリ

    MASTER v3.6 モックデータカタログ対応:
        segments=0              → MD-01: 空パイプライン
        segments=1              → MD-02: 最小パイプライン
        segments=10 (default)   → MD-03: 標準パイプライン
        segments=50             → MD-04: 大量セグメント
        corrupt=True            → MD-05: 破損データ (text欠落, start>end)
        type_error=True         → MD-06: 型不正データ (start=str, end=None)
        segments=100            → MD-07: 長尺データ (30分相当)

    Args:
        segments: 生成するセグメント数
        video_path: 動画ファイルパス（空の場合はデフォルトTV-01パスを使用）
        target_minutes: 目標尺（分）
        corrupt: MD-05 破損データモード
        type_error: MD-06 型不正モード
        with_selected: selected_segments も同時に設定するか
        template_id: テンプレートID
        session_id: セッションID
        duration_each: 各セグメントのデフォルト秒数

    Returns:
        テスト用 PipelineContext インスタンス
    """
    if not video_path:
        # デフォルトパス: プロジェクトルートの test_videos/tv01_real_clip.mp4
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        video_path = str(project_root / "test_videos" / "tv01_real_clip.mp4")

    segs = create_mock_segments(
        count=segments,
        corrupt=corrupt,
        type_error=type_error,
        duration_each=duration_each,
    )

    ctx = PipelineContext(
        video_path=video_path,
        target_minutes=target_minutes,
        session_id=session_id,
        started_at="2026-04-20T12:00:00",
        segments=segs,
    )

    if with_selected:
        ctx.selected_segments = copy.deepcopy(segs)

    if template_id:
        ctx.template_id = template_id

    return ctx


# ============================================================
# StageResult ヘルパー
# ============================================================

def create_mock_stage_result(
    stage_name: str = "テスト",
    success: bool = True,
    detail: str = "テスト成功",
    data: Optional[Dict] = None,
    duration_seconds: float = 1.0,
) -> StageResult:
    """テスト用 StageResult を生成"""
    return StageResult(
        stage_name=stage_name,
        success=success,
        detail=detail,
        data=data or {},
        duration_seconds=duration_seconds,
    )
