# -*- coding: utf-8 -*-
import os
import sys
import json
import pytest
import asyncio
from pathlib import Path
from PIL import Image
from unittest.mock import MagicMock, patch

# プロジェクトルートをパスに追加
backend_dir = Path(__file__).resolve().parents[1]
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from subtitle_engine.speaker_diarizer import (
    SpeakerDiarizer,
    DiarizationResult,
    SpeakerSegment,
    run_diarizer_thumbnail_task
)
from agents.stage_bound_agent import StageBoundAgent

@pytest.fixture
def temp_output_dir(tmp_path):
    d = tmp_path / "thumbnails"
    d.mkdir()
    yield d

def test_speaker_diarizer_thumbnail_success(temp_output_dir):
    """正常系: 1280x720 16:9 の話者分離結果サムネイルが生成され、検証を満たすこと"""
    diarizer = SpeakerDiarizer()
    out_path = temp_output_dir / "diarizer_thumb.png"
    
    # テスト用データ準備
    segments = [
        SpeakerSegment(start=0.0, end=2.5, speaker_id="speaker_0", confidence=0.8),
        SpeakerSegment(start=2.5, end=5.0, speaker_id="speaker_1", confidence=0.75),
        SpeakerSegment(start=5.0, end=10.0, speaker_id="speaker_0", confidence=0.9),
    ]
    diarization = DiarizationResult(
        segments=segments,
        num_speakers=2,
        method="vad",
        duration=10.0
    )
    
    # サムネイル生成
    generated_path = diarizer.generate_diarization_thumbnail(
        output_path=str(out_path),
        diarization=diarization,
        width=1280,
        height=720,
        title="Diarization Visualizer Test"
    )
    
    assert Path(generated_path).exists()
    
    # 品質基準の検証
    # 1. 解像度 1280x720 以上
    with Image.open(generated_path) as img:
        width, height = img.size
        assert width >= 1280
        assert height >= 720
        # 2. アスペクト比 16:9
        aspect_ratio = width / height
        assert abs(aspect_ratio - 16.0 / 9.0) < 0.01
        # 4. 正常にロード可能で破損していない
        img.load()
        
    # 3. ファイルサイズ 4MB 未満
    size_bytes = Path(generated_path).stat().st_size
    assert size_bytes < 4 * 1024 * 1024

def test_speaker_diarizer_thumbnail_invalid_resolution(temp_output_dir):
    """異常系: 解像度が 1280x720 未満の場合に例外が発生すること"""
    diarizer = SpeakerDiarizer()
    out_path = temp_output_dir / "diarizer_thumb_low.png"
    
    diarization = DiarizationResult(segments=[], num_speakers=1, method="vad", duration=5.0)
    
    with pytest.raises(ValueError) as excinfo:
        diarizer.generate_diarization_thumbnail(
            output_path=str(out_path),
            diarization=diarization,
            width=640,
            height=360
        )
    assert "Resolution must be at least 1280x720" in str(excinfo.value)

def test_speaker_diarizer_thumbnail_invalid_aspect_ratio(temp_output_dir):
    """異常系: アスペクト比が 16:9 以外の場合に例外が発生すること"""
    diarizer = SpeakerDiarizer()
    out_path = temp_output_dir / "diarizer_thumb_square.png"
    
    diarization = DiarizationResult(segments=[], num_speakers=1, method="vad", duration=5.0)
    
    with pytest.raises(ValueError) as excinfo:
        diarizer.generate_diarization_thumbnail(
            output_path=str(out_path),
            diarization=diarization,
            width=1280,
            height=1280
        )
    assert "Aspect ratio must be 16:9" in str(excinfo.value)

@pytest.mark.asyncio
async def test_speaker_diarizer_stage_bound_agent_integration(temp_output_dir):
    """StageBoundAgent 連携テスト: タスク登録、実行、結果保存、リトライの挙動を確認"""
    db_file = str(temp_output_dir / "test_stage_bound.db")
    task_id = "T-diarizer-thumb-001"
    output_file = str(temp_output_dir / "diarizer_task_thumb.png")
    
    # テスト用話者データJSON
    diarization_json = json.dumps({
        "segments": [
            {"start": 0.0, "end": 3.0, "speaker_id": "speaker_0", "confidence": 0.8},
            {"start": 3.0, "end": 6.0, "speaker_id": "speaker_1", "confidence": 0.85}
        ],
        "num_speakers": 2,
        "method": "stereo",
        "duration": 6.0
    })
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_file)
    
    # タスクの登録 (最大リトライ回数 2)
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    # 状態の確認 (初期値は READY)
    status = await agent.get_task_status(task_id)
    assert status == "READY"
    
    # タスク処理関数の定義
    async def process_task(tid):
        assert tid == task_id
        # run_diarizer_thumbnail_task を呼び出す
        return await run_diarizer_thumbnail_task(
            db_path=db_file,
            task_id=tid,
            output_path=output_file,
            diarization_data_json=diarization_json,
            width=1280,
            height=720,
            title="Agent Integration Test"
        )
        
    # エージェントの起動
    await agent.start(process_task)
    
    # 完了するまで少し待つ
    await asyncio.sleep(0.5)
    
    # エージェント停止
    await agent.stop()
    
    # タスクの状態が COMPLETED になっていることを確認
    status = await agent.get_task_status(task_id)
    assert status == "COMPLETED"
    
    # 結果が保存されていることを確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    result_val = row[0]
    error_val = row[1]
    conn.close()
    
    assert error_val is None
    assert result_val is not None
    result_data = json.loads(result_val)
    assert "width" in result_data
    assert result_data["width"] == 1280
    assert result_data["height"] == 720
    assert os.path.exists(output_file)

@pytest.mark.asyncio
async def test_speaker_diarizer_stage_bound_agent_retry(temp_output_dir):
    """StageBoundAgent 連携テスト: エラー時の自動リトライと最終的な FAILED への遷移を確認"""
    db_file = str(temp_output_dir / "test_stage_bound_retry.db")
    task_id = "T-diarizer-thumb-fail"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=db_file)
    
    # 最大リトライ 1 回のタスクを登録
    await agent.register_task(task_id, initial_status="READY", max_retries=1)
    
    # 毎回例外を投げるタスク処理関数
    call_count = 0
    def failing_process(tid):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"Simulated failure {call_count}")
        
    await agent.start(failing_process)
    
    # リトライと最終失敗まで待つ
    await asyncio.sleep(0.5)
    await agent.stop()
    
    # リトライ上限を超えて FAILED になっているはず
    status = await agent.get_task_status(task_id)
    assert status == "FAILED"
    assert call_count == 2  # 初回 (1) + リトライ (1)
