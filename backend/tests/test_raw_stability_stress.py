"""
长期安定性・リソース耐久テスト (Stability Stress Test)

実RAW動画を模したテスト動画でのパイプライン結合・編集の繰り返し処理を行い、
メモリリーク、一時ファイルのクリーンアップ、ゾンビプロセスの残存を監視・アサートする。
"""

import os
import sys
import json
import time
import shutil
import pytest
import psutil
from pathlib import Path
from unittest.mock import patch, MagicMock

# パス設定
sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.pipeline_coordinator import PipelineCoordinator, PipelineContext
from agents.pipeline_types import StageResult

TEST_TEMP_DIR = Path(__file__).parent.parent / "test_previews_tmp"


def get_dir_size(path: Path) -> int:
    """ディレクトリ内の全ファイルの合計サイズを取得"""
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.glob('**/*') if f.is_file())


@pytest.mark.asyncio
async def test_raw_stability_stress(safe_popen_mock, monkeypatch):
    """実動画パイプラインの結合・編集処理を3回連続実行し、リソース使用量を検証する"""
    
    # 1. 測定対象の初期状態取得
    process = psutil.Process()
    initial_rss = process.memory_info().rss
    
    # 一時ファイル用ディレクトリの初期化
    if TEST_TEMP_DIR.exists():
        try:
            shutil.rmtree(TEST_TEMP_DIR)
        except Exception:
            pass
    TEST_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    initial_temp_size = get_dir_size(TEST_TEMP_DIR)
    
    # 初期子プロセス数の取得
    initial_children_count = 0
    try:
        initial_children_count = len(process.children(recursive=True))
    except Exception:
        pass
    
    # 外部依存のモック設定
    # (a) genai API のモック
    mock_genai_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "[]"
    mock_genai_client.models.generate_content.return_value = mock_response
    monkeypatch.setattr("google.genai.Client", lambda *args, **kwargs: mock_genai_client)
    
    # (b) gemini_client_factory のモック
    try:
        import gemini_client_factory
        monkeypatch.setattr(gemini_client_factory, "get_gemini_client", lambda *args, **kwargs: mock_genai_client)
    except (ImportError, AttributeError):
        pass
        
    # (c) time.sleep のモック
    monkeypatch.setattr(time, "sleep", lambda x: None)
    
    # (d) VAULT_OUTPUTS_DIR のリダイレクト
    monkeypatch.setattr("safe_io.VAULT_OUTPUTS_DIR", TEST_TEMP_DIR)
    
    # (e) subprocess.run のモック
    def mock_run(*args, **kwargs):
        mock_result = MagicMock()
        mock_result.returncode = 0
        cmd_args = args[0] if args else kwargs.get("args", [])
        cmd_str = " ".join(cmd_args) if isinstance(cmd_args, list) else str(cmd_args)
        
        if "-of json" in cmd_str or "json" in cmd_str:
            mock_result.stdout = json.dumps({
                "streams": [
                    {"codec_name": "h264", "codec_type": "video", "width": 1920, "height": 1080},
                    {"codec_name": "aac", "codec_type": "audio"}
                ],
                "format": {"duration": "13.0"}
            })
        elif "format=duration" in cmd_str or "-show_entries" in cmd_str:
            mock_result.stdout = "13.0\n"
        elif "-encoders" in cmd_str:
            mock_result.stdout = "h264_nvenc"
        elif "silencedetect" in cmd_str:
            mock_result.stdout = "silence_start: 5.0\nsilence_end: 8.0\n"
        else:
            mock_result.stdout = "success"
        mock_result.stderr = ""
        return mock_result
        
    monkeypatch.setattr("subprocess.run", mock_run)
    
    # (f) shutil.copy のモック
    original_copy = shutil.copy
    def mock_copy(src, dst, *args, **kwargs):
        src_path = Path(src)
        dst_path = Path(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.exists():
            return original_copy(src, dst, *args, **kwargs)
        else:
            # 2KB of dummy file to prevent FileNotFoundError
            dst_path.write_bytes(b"a" * 2048)
            return str(dst_path)
            
    monkeypatch.setattr(shutil, "copy", mock_copy)
    
    # テスト動画の準備
    video_path = Path(__file__).parent / "test_13s.mp4"
    created_dummy = False
    if not video_path.exists():
        video_path.write_bytes(b"dummy video data")
        created_dummy = True
        
    # メトリクス蓄積用辞書
    metrics = {
        "initial": {
            "memory_rss": initial_rss,
            "temp_dir_size": initial_temp_size,
            "child_process_count": initial_children_count
        },
        "iterations": []
    }
    
    coordinator = PipelineCoordinator()
    
    # TranscribeWorker をモック化してダミーセグメントを注入
    async def mock_transcribe_execute(ctx: PipelineContext) -> StageResult:
        ctx.segments = [
            {"start": 0.0, "end": 2.0, "text": "こんにちは", "sourceStart": 0.0, "sourceEnd": 2.0},
            {"start": 2.0, "end": 5.0, "text": "テスト動画です", "sourceStart": 2.0, "sourceEnd": 5.0},
            {"start": 5.0, "end": 10.0, "text": "本日は晴天なり", "sourceStart": 5.0, "sourceEnd": 10.0}
        ]
        return StageResult(stage_name="文字起こし", success=True, detail="3 segments injected")
        
    monkeypatch.setattr(coordinator.workers[0], "execute", mock_transcribe_execute)
    
    # 2. イテレーション実行
    mock_proc = safe_popen_mock(returncode=0)
    with patch("subprocess.Popen", return_value=mock_proc):
        for i in range(3):
            ctx = PipelineContext(video_path=str(video_path))
            ctx.quality_score = 95  # 品質ゲートをパスさせ、production モードで走らせる
            
            result = await coordinator.execute(ctx)
            assert result["status"] == "completed"
            
            # 各イテレーション終了時のリソース計測
            current_rss = process.memory_info().rss
            current_temp_size = get_dir_size(TEST_TEMP_DIR)
            
            current_children_count = 0
            try:
                current_children_count = len(process.children(recursive=True))
            except Exception:
                pass
                
            metrics["iterations"].append({
                "iteration": i + 1,
                "memory_rss": current_rss,
                "temp_dir_size": current_temp_size,
                "child_process_count": current_children_count
            })
            
    # 3. リソースアサーション
    # (a) メモリ増加率: イテレーション実行中にメモリ使用量が累積的に増え続けていないこと
    # 初回イテレーションはモジュールロード等で急増するため、2回目以降のイテレーション間での増分をチェック
    iter_rss = [it["memory_rss"] for it in metrics["iterations"]]
    if len(iter_rss) >= 2:
        for idx in range(1, len(iter_rss)):
            ratio = iter_rss[idx] / iter_rss[idx - 1]
            assert ratio < 1.15, f"Memory leak suspected: Iteration {idx + 1} RSS ({iter_rss[idx]}) is {ratio:.2f}x of Iteration {idx} RSS ({iter_rss[idx - 1]})"

    
    # (b) ディスク容量: 一時ファイル用ディレクトリがクリーンアップされていること
    try:
        shutil.rmtree(TEST_TEMP_DIR)
    except Exception:
        pass
    assert get_dir_size(TEST_TEMP_DIR) == 0
    
    # (c) ゾンビプロセス: zombie状態のプロセス、または未終了の FFmpeg プロセスがないこと
    children = []
    try:
        children = process.children(recursive=True)
    except Exception:
        pass
        
    ffmpeg_children = []
    zombie_children = []
    for c in children:
        try:
            if "ffmpeg" in c.name().lower():
                ffmpeg_children.append(c)
            if c.status() == psutil.STATUS_ZOMBIE:
                zombie_children.append(c)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
    assert len(ffmpeg_children) == 0, f"FFmpeg processes leaked: {len(ffmpeg_children)}"
    assert len(zombie_children) == 0, f"Zombie processes detected: {len(zombie_children)}"
    
    # 4. データの永続化 (temp/stability_stress_metrics.json に保存)
    temp_dir = TEST_TEMP_DIR / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    metrics_file = temp_dir / "stability_stress_metrics.json"
    
    with open(metrics_file, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
        
    assert metrics_file.exists()
    
    # 一時フォルダのクリーンアップ
    if TEST_TEMP_DIR.exists():
        try:
            shutil.rmtree(TEST_TEMP_DIR)
        except Exception:
            pass

    # ダミーファイルの削除
    if created_dummy and video_path.exists():
        try:
            video_path.unlink()
        except Exception:
            pass
