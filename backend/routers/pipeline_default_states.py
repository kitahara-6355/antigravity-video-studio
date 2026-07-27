"""
Pipeline Default States — 制作パイプライン API のデフォルト状態・ダミーデータ定義
"""
import copy

# ============================================================
# デフォルト状態の定義 (定数)
# ============================================================

INITIAL_PIPELINE_STATE = {
    "session_id": None,
    "status": "idle",           # idle | running | checkpoint | completed | error
    "current_stage": 0,         # 0-6 (7ステージ)
    "stages": [
        {"name": "文字起こし", "icon": "🎤", "status": "pending", "detail": ""},
        {"name": "AI校閲", "icon": "📝", "status": "pending", "detail": ""},
        {"name": "SmartCut構成", "icon": "✂️", "status": "pending", "detail": ""},
        {"name": "プレビュー生成", "icon": "🎬", "status": "pending", "detail": ""},
        {"name": "YouTube最適化", "icon": "📊", "status": "pending", "detail": ""},
        {"name": "品質チェック", "icon": "✅", "status": "pending", "detail": ""},
        {"name": "最終レンダリング", "icon": "🎞️", "status": "pending", "detail": ""},
    ],
    "checkpoint": None,          # 現在のチェックポイントデータ
    "video_path": "",
    "video_paths": [],           # 複数動画パス
    "video_count": 0,
    "target_minutes": 20,
    "started_at": None,
    "completed_at": None,
    "error": None,
    "result": None,
}

INITIAL_TRANSCRIPTION_STATE = {
    "model": "medium",
    "status": "idle",  # idle | running | completed | error
    "progress": 0,
    "elapsed_seconds": 0,
    "error_message": None,
    "segments": [],
    "started_at": None,
}

INITIAL_PROOFREADING_STATE = {
    "status": "idle",  # idle | running | completed
    "progress": 0,
    "segments": [],
    "skip": False,
}

INITIAL_QUALITY_GATE_STATE = {
    "status": "idle",  # idle | checking | passed | failed
    "overall_score": 85,
    "threshold": 90,
    "categories": [
        {
            "id": "audio",
            "name": "音声品質",
            "score": 88,
            "weight": 25,
            "details": [
                {"item": "音量レベル", "score": 90, "status": "pass", "description": "ラウドネスが-14 LUFS以内"},
                {"item": "ノイズレベル", "score": 85, "status": "pass", "description": "背景ノイズが-40dB以下"},
                {"item": "音声クリッピング", "score": 92, "status": "pass", "description": "クリッピング検出なし"},
                {"item": "音声同期", "score": 84, "status": "warning", "description": "映像との同期ずれ < 50ms"},
            ],
        },
        {
            "id": "video",
            "name": "映像品質",
            "score": 82,
            "weight": 25,
            "details": [
                {"item": "解像度", "score": 90, "status": "pass", "description": "1080p以上"},
                {"item": "フレームレート", "score": 85, "status": "pass", "description": "30fps以上の安定"},
                {"item": "ビットレート", "score": 78, "status": "warning", "description": "適正ビットレート範囲"},
                {"item": "エンコード品質", "score": 75, "status": "warning", "description": "VMAF 80以上"},
            ],
        },
        {
            "id": "subtitle",
            "name": "字幕品質",
            "score": 90,
            "weight": 25,
            "details": [
                {"item": "文字数制限", "score": 95, "status": "pass", "description": "1行18文字以内"},
                {"item": "表示時間", "score": 88, "status": "pass", "description": "適切な表示秒数"},
                {"item": "誤字脱字", "score": 85, "status": "pass", "description": "AI校閲済み"},
                {"item": "フォーマット", "score": 92, "status": "pass", "description": "SRT準拠"},
            ],
        },
        {
            "id": "structure",
            "name": "構成品質",
            "score": 80,
            "weight": 25,
            "details": [
                {"item": "動画尺", "score": 85, "status": "pass", "description": "目標尺の±10%以内"},
                {"item": "トランジション", "score": 78, "status": "warning", "description": "シーン遷移の滑らかさ"},
                {"item": "テンポ", "score": 75, "status": "warning", "description": "視聴維持率予測"},
                {"item": "エンゲージメント", "score": 82, "status": "pass", "description": "注目ポイント配置"},
            ],
        },
    ],
    "improvements": [],
    "history": [
        {"iteration": 0, "score": 72, "timestamp": "2026-04-29T10:00:00"},
        {"iteration": 1, "score": 80, "timestamp": "2026-04-29T10:05:00"},
        {"iteration": 2, "score": 85, "timestamp": "2026-04-29T10:10:00"},
    ],
    "checked_at": None,
}

INITIAL_IMPROVEMENT_STATE = {
    "status": "idle",  # idle | running | completed | aborted
    "iteration": 0,
    "max_iterations": 3,
    "initial_score": 72,
    "current_score": 85,
    "actions": [
        {
            "id": "act-001",
            "name": "音量正規化",
            "category": "audio",
            "status": "completed",  # pending | running | completed | skipped
            "score_before": 72,
            "score_after": 78,
            "description": "ラウドネスを-14 LUFSに正規化",
        },
        {
            "id": "act-002",
            "name": "ビットレート最適化",
            "category": "video",
            "status": "completed",
            "score_before": 78,
            "score_after": 82,
            "description": "目標ビットレートにリエンコード",
        },
        {
            "id": "act-003",
            "name": "字幕文字数調整",
            "category": "subtitle",
            "status": "pending",
            "score_before": 82,
            "score_after": None,
            "description": "18文字超過行を自動分割",
        },
        {
            "id": "act-004",
            "name": "テンポ調整",
            "category": "structure",
            "status": "pending",
            "score_before": None,
            "score_after": None,
            "description": "冗長区間をカットしテンポ向上",
        },
    ],
    "score_history": [
        {"iteration": 0, "score": 72, "action": "初期状態"},
        {"iteration": 1, "score": 78, "action": "音量正規化"},
        {"iteration": 2, "score": 82, "action": "ビットレート最適化"},
    ],
    "applied_actions": ["act-001", "act-002"],
}

# ============================================================
# デモ・デフォルト用ダミーデータの定義
# ============================================================

DEFAULT_TRANCRIPTION_SEGMENTS = [
    {"id": 0, "start": 0.0, "end": 3.5, "text": "こんにちは、今日は新機能について紹介します", "speaker_id": "speaker_0"},
    {"id": 1, "start": 3.5, "end": 7.2, "text": "まず最初に、パイプラインの概要をご説明します", "speaker_id": "speaker_0"},
    {"id": 2, "start": 7.2, "end": 12.0, "text": "この機能により、動画編集が大幅に効率化されます", "speaker_id": "speaker_1"},
]

DEFAULT_PROOFREADING_SEGMENTS = [
    {
        "id": 0, "start": 0.0, "end": 3.5,
        "original": "こんにちは、きょうは新機能について紹介します",
        "corrected": "こんにちは、今日は新機能について紹介します",
        "changes": [{"type": "replace", "original": "きょう", "corrected": "今日", "position": 5}],
        "status": "pending",  # pending | approved | rejected
    },
    {
        "id": 1, "start": 3.5, "end": 7.2,
        "original": "まず最初にパイプラインの概要をご説明します",
        "corrected": "まず最初に、パイプラインの概要をご説明します",
        "changes": [{"type": "insert", "original": "", "corrected": "、", "position": 5}],
        "status": "pending",
    },
    {
        "id": 2, "start": 7.2, "end": 12.0,
        "original": "この機能により動画編集が大幅に効率化されますこの文章は十八文字を超える非常に長い行です",
        "corrected": "この機能により、動画編集が大幅に効率化されます",
        "changes": [
            {"type": "insert", "original": "", "corrected": "、", "position": 6},
            {"type": "delete", "original": "この文章は十八文字を超える非常に長い行です", "corrected": "", "position": 23},
        ],
        "status": "pending",
    },
]

# ============================================================
# ヘルパー関数 (引数バリデーション)
# ============================================================

def _validate_pipeline_args(session_id: str = None, video_path: str = "", target_minutes: int = 20) -> None:
    """get_initial_pipeline_state の引数を検証します。"""
    if session_id is not None and (not isinstance(session_id, str) or isinstance(session_id, bool)):
        raise TypeError("session_id must be a string or None")
    if (not isinstance(video_path, str) or isinstance(video_path, bool)):
        raise TypeError("video_path must be a string")
    if (not isinstance(target_minutes, int) or isinstance(target_minutes, bool)):
        raise TypeError("target_minutes must be an integer")
    if target_minutes <= 0:
        raise ValueError("target_minutes must be a positive integer")

def _validate_transcription_args(model: str) -> None:
    """get_initial_transcription_state の引数を検証します。"""
    if not isinstance(model, str) or isinstance(model, bool):
        raise TypeError("model must be a string")
    if not model.strip():
        raise ValueError("model must not be empty")


# ============================================================
# ファクトリ関数 (ディープコピーおよび引数バリデーション付き)
# ============================================================

def get_initial_pipeline_state(session_id: str = None, video_path: str = "", target_minutes: int = 20):
    """
    パイプラインの初期状態オブジェクトを取得します。
    """
    _validate_pipeline_args(session_id, video_path, target_minutes)

    state = copy.deepcopy(INITIAL_PIPELINE_STATE)
    state["session_id"] = session_id
    state["video_path"] = video_path
    state["target_minutes"] = target_minutes
    return state

def get_initial_transcription_state(model: str = "medium"):
    """
    文字起こしの初期状態オブジェクトを取得します。
    """
    _validate_transcription_args(model)
    state = copy.deepcopy(INITIAL_TRANSCRIPTION_STATE)
    state["model"] = model
    return state

def get_initial_proofreading_state():
    return copy.deepcopy(INITIAL_PROOFREADING_STATE)

def get_initial_quality_gate_state():
    return copy.deepcopy(INITIAL_QUALITY_GATE_STATE)

def get_initial_improvement_state():
    return copy.deepcopy(INITIAL_IMPROVEMENT_STATE)

def get_default_transcription_segments():
    return copy.deepcopy(DEFAULT_TRANCRIPTION_SEGMENTS)

def get_default_proofreading_segments():
    return copy.deepcopy(DEFAULT_PROOFREADING_SEGMENTS)
