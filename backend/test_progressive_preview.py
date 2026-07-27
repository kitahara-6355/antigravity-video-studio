"""
E2E Test for Progressive Preview System
プログレッシブ・プレビュー・システムの統合テスト
"""

import sys
import json
from pathlib import Path

# テスト環境設定
sys.path.insert(0, str(Path(__file__).parent))

from progressive_preview import ProgressivePreview
from progressive_preview_report import PreviewReportGenerator


def run_e2e_test():
    """E2Eテスト実行"""
    print("=" * 60)
    print("🧪 Progressive Preview System - E2E Test")
    print("=" * 60)
    
    # テスト用動画パス
    test_videos = [
        r"C:\Users\PC_User\Desktop\script\video-automation\test_10sec.mp4",
        r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン04_後編02.mp4"
    ]
    
    video_path = None
    for v in test_videos:
        if Path(v).exists():
            video_path = v
            break
    
    if not video_path:
        print("❌ テスト動画が見つかりません")
        return False
    
    print(f"\n📹 テスト動画: {Path(video_path).name}")
    
    # 1. セッション作成
    print("\n[1/4] セッション作成...")
    preview = ProgressivePreview(session_id="e2e_test_session")
    print(f"  ✅ Session ID: {preview.session_id}")
    print(f"  ✅ Output Dir: {preview.output_dir}")
    
    # 2. 特徴点検出テスト
    print("\n[2/4] 特徴点検出テスト...")
    feature_points = preview.detect_feature_points(video_path, max_points=3)
    print(f"  ✅ 検出されたポイント: {feature_points}")
    
    # 3. スナップショット生成テスト（同一動画でBefore/Afterテスト）
    print("\n[3/4] スナップショット生成テスト...")
    try:
        result = preview.snapshot_step(
            step_name="test_crop",
            before_video=video_path,
            after_video=video_path,
            num_samples=3
        )
        print(f"  ✅ 生成された比較画像: {len(result['comparisons'])}枚")
        
        for comp in result['comparisons']:
            comp_path = Path(comp['comparison'])
            if comp_path.exists():
                print(f"    - {comp_path.name} ({comp_path.stat().st_size / 1024:.1f} KB)")
            else:
                print(f"    - ❌ {comp_path.name} が見つかりません")
    except Exception as e:
        print(f"  ❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. HTMLレポート生成テスト
    print("\n[4/4] HTMLレポート生成テスト...")
    try:
        generator = PreviewReportGenerator()
        report_path = generator.generate_from_session_dir(str(preview.output_dir))
        report_file = Path(report_path)
        
        if report_file.exists():
            print(f"  ✅ レポート生成成功: {report_file.name}")
            print(f"  ✅ サイズ: {report_file.stat().st_size / 1024:.1f} KB")
            
            # HTMLの検証
            content = report_file.read_text(encoding='utf-8')
            checks = [
                ("セッションID表示", preview.session_id in content),
                ("比較画像埋め込み", "data:image/png;base64" in content),
                ("承認ボタン", "btn-approve" in content),
                ("却下ボタン", "btn-reject" in content),
                ("JavaScript", "submitDecision" in content)
            ]
            
            print("\n  📋 HTMLレポート検証:")
            all_passed = True
            for check_name, passed in checks:
                status = "✅" if passed else "❌"
                print(f"    {status} {check_name}")
                if not passed:
                    all_passed = False
        else:
            print(f"  ❌ レポートファイルが見つかりません: {report_path}")
            return False
    except Exception as e:
        print(f"  ❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 結果サマリー
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 E2Eテスト完了: 全項目パス")
    else:
        print("⚠️ E2Eテスト完了: 一部項目に問題あり")
    print("=" * 60)
    
    print(f"\n📂 出力ディレクトリ: {preview.output_dir}")
    print(f"📄 HTMLレポート: {report_path}")
    
    return all_passed


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)  # ログを抑制
    
    success = run_e2e_test()
    sys.exit(0 if success else 1)


# ==============================================================================
# Pytest Unit Tests for Progressive Preview System
# ==============================================================================
import pytest
from PIL import Image

@pytest.fixture
def dummy_images(tmp_path):
    """テスト用のダミー画像を作成するフィクスチャ"""
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    
    # 異なる色の画像を作成して差分が出るようにする
    img_before = Image.new("RGB", (640, 360), color=(100, 100, 100))
    img_after = Image.new("RGB", (640, 360), color=(150, 100, 100))
    
    img_before.save(before_path)
    img_after.save(after_path)
    
    return before_path, after_path

def test_preview_initialization(tmp_path):
    """初期化テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    assert preview.session_id == "test_session"
    assert preview.output_dir == tmp_path
    assert len(preview.steps) == 0

def test_fallback_sampling(tmp_path, monkeypatch):
    """フォールバックサンプリングのテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # _get_video_duration が正常な値を返す場合
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 10.0)
    points = preview._fallback_sampling("dummy.mp4", 3)
    assert len(points) == 3
    assert points == [2.5, 5.0, 7.5]
    
    # _get_video_duration が 0 を返す場合
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 0.0)
    points = preview._fallback_sampling("dummy.mp4", 3)
    assert len(points) == 3
    assert points == [1.0, 3.0, 5.0]

def test_extract_srt_timestamps(tmp_path):
    """SRTからのタイムスタンプ抽出テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # ダミーのSRTファイル作成
    srt_content = """1
00:00:01,500 --> 00:00:03,200
こんにちは

2
00:00:05,123 --> 00:00:07,456
さようなら
"""
    srt_path = tmp_path / "test.srt"
    srt_path.write_text(srt_content, encoding="utf-8")
    
    timestamps = preview._extract_srt_timestamps(str(srt_path), max_points=2)
    assert len(timestamps) == 2
    assert abs(timestamps[0] - 1.5) < 0.001
    assert abs(timestamps[1] - 5.123) < 0.001

    # 存在しないSRTの場合
    assert preview._extract_srt_timestamps("nonexistent.srt") == []

def test_get_video_duration_success(tmp_path, monkeypatch):
    """動画の長さ取得テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    import subprocess
    class MockCompletedProcess:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0
            
    def mock_run(*args, **kwargs):
        return MockCompletedProcess("12.34\n")
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    duration = preview._get_video_duration("dummy.mp4")
    assert duration == 12.34

def test_extract_screenshot(tmp_path, monkeypatch):
    """スクリーンショット抽出テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    import subprocess
    called = []
    def mock_run(cmd, **kwargs):
        called.append(cmd)
        # 実際にファイルを生成
        out_path = cmd[-1]
        Path(out_path).touch()
        class MockProc:
            returncode = 0
        return MockProc()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    out = tmp_path / "ss.png"
    res = preview.extract_screenshot("dummy.mp4", 5.0, str(out))
    assert res == str(out)
    assert out.exists()
    assert len(called) == 1
    assert "ffmpeg" in called[0]

def test_create_comparison_image(tmp_path, dummy_images):
    """比較画像の生成テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    before_path, after_path = dummy_images
    output_path = tmp_path / "comparison.png"
    
    res = preview.create_comparison_image(
        str(before_path),
        str(after_path),
        str(output_path),
        label_before="Before",
        label_after="After"
    )
    assert res == str(output_path)
    assert output_path.exists()
    
    # 異常系（存在しないファイル）
    with pytest.raises(Exception):
        preview.create_comparison_image("nonexistent1.png", "nonexistent2.png", str(output_path))

def test_create_diff_highlight(tmp_path, dummy_images):
    """差分ハイライト画像の生成テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    before_path, after_path = dummy_images
    output_path = tmp_path / "diff.png"
    
    res = preview.create_diff_highlight(
        str(before_path),
        str(after_path),
        str(output_path)
    )
    assert res == str(output_path)
    assert output_path.exists()
    
    # サイズの異なる画像でのテスト
    large_before = tmp_path / "large_before.png"
    Image.new("RGB", (1280, 720), color=(100, 100, 100)).save(large_before)
    
    res_resized = preview.create_diff_highlight(
        str(large_before),
        str(after_path),
        str(output_path)
    )
    assert res_resized == str(output_path)
    assert output_path.exists()

def test_detect_silence_points(tmp_path, monkeypatch):
    """無音区間検出テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    import subprocess
    class MockCompletedProcess:
        def __init__(self):
            self.stderr = "silence_start: 1.5\nsilence_end: 3.0\nsilence_start: 7.2\n"
            self.returncode = 0
            
    def mock_run(*args, **kwargs):
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    points = preview.detect_silence_points("dummy.mp4", max_points=2)
    assert points == [1.5, 7.2]

def test_detect_feature_points_fallback_branch(tmp_path, monkeypatch):
    """特徴点検出のフォールバックブランチ検証"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    import subprocess
    # TimeoutExpired を発生させる
    def mock_run_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=60)
        
    monkeypatch.setattr(subprocess, "run", mock_run_timeout)
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 10.0)
    points = preview.detect_feature_points("dummy.mp4", max_points=3)
    assert points == [2.5, 5.0, 7.5]
    
    # Exception を発生させる
    def mock_run_error(*args, **kwargs):
        raise RuntimeError("FFprobe error")
        
    monkeypatch.setattr(subprocess, "run", mock_run_error)
    points = preview.detect_feature_points("dummy.mp4", max_points=3)
    assert points == [2.5, 5.0, 7.5]

def test_detect_feature_points_enhanced(tmp_path, monkeypatch):
    """拡張特徴点検出テスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # 各検出メソッドのモック
    monkeypatch.setattr(preview, "detect_feature_points", lambda *args, **kwargs: [1.0, 4.0, 8.0])
    monkeypatch.setattr(preview, "detect_silence_points", lambda *args, **kwargs: [2.0, 9.0])
    
    points = preview.detect_feature_points_enhanced("dummy.mp4", max_points=5, include_silence=True)
    # 重複除去とソート、近すぎる（2秒以内）の除去が行われる
    # [1.0, 2.0, 4.0, 8.0, 9.0] -> 1.0, 4.0, 8.0 (2.0は1.0に近いので除去、9.0は8.0に近いので除去)
    assert points == [1.0, 4.0, 8.0]

def test_snapshot_step(tmp_path, monkeypatch):
    """スナップショットステップ全体のテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # extract_screenshotのモック
    def mock_extract(video_path, ts, output_path, **kwargs):
        # 実際に空画像を保存する
        Image.new("RGB", (320, 180), color=(100, 100, 100)).save(output_path)
        return output_path
        
    monkeypatch.setattr(preview, "extract_screenshot", mock_extract)
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 10.0)
    
    # detect_feature_pointsのモック
    monkeypatch.setattr(preview, "detect_feature_points", lambda *args: [2.0, 5.0])
    
    result = preview.snapshot_step(
        step_name="crop",
        before_video="before.mp4",
        after_video="after.mp4",
        num_samples=2
    )
    
    assert result["step_name"] == "crop"
    assert len(result["comparisons"]) == 2
    assert len(preview.steps) == 1
    assert preview.get_all_comparisons() == [comp["comparison"] for comp in result["comparisons"]]

def test_report_generator_html(tmp_path, dummy_images):
    """HTMLレポート生成テスト"""
    generator = PreviewReportGenerator()
    before_path, after_path = dummy_images
    
    metadata = {
        "session_id": "test_session",
        "created_at": "2026-05-22T00:00:00",
        "steps": [
            {
                "step_name": "crop",
                "comparisons": [
                    {
                        "timestamp": 2.0,
                        "before": str(before_path),
                        "after": str(after_path),
                        "comparison": str(before_path),
                        "diff_highlight": str(after_path)
                    }
                ]
            }
        ]
    }
    
    output_html = tmp_path / "report.html"
    res = generator.generate_html_report(metadata, str(output_html), embed_images=True)
    assert res == str(output_html)
    assert output_html.exists()
    
    html_content = output_html.read_text(encoding="utf-8")
    assert "test_session" in html_content
    assert "data:image/png;base64" in html_content
    
    # 画像埋め込みなしの場合
    res_no_embed = generator.generate_html_report(metadata, str(output_html), embed_images=False)
    assert res_no_embed == str(output_html)

def test_report_generator_from_dir(tmp_path, dummy_images):
    """セッションディレクトリからのレポート生成テスト"""
    generator = PreviewReportGenerator()
    before_path, after_path = dummy_images
    
    # ディレクトリ構成のセットアップ
    session_dir = tmp_path / "session_dir"
    session_dir.mkdir()
    
    metadata = {
        "session_id": "test_session_dir",
        "created_at": "2026-05-22T00:00:00",
        "steps": []
    }
    
    with open(session_dir / "session_metadata.json", "w", encoding="utf-8") as f:
        import json
        json.dump(metadata, f)
        
    res = generator.generate_from_session_dir(str(session_dir))
    assert Path(res).exists()
    assert Path(res).name == "preview_report.html"
    
    # 存在しないディレクトリの場合のエラー検証
    with pytest.raises(FileNotFoundError):
        generator.generate_from_session_dir("nonexistent_dir")

def test_detect_feature_points_success(tmp_path, monkeypatch):
    """ffprobeでのシーン検出が正常に動作する場合のテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    import subprocess
    class MockCompletedProcess:
        def __init__(self):
            self.stdout = "2.5\n5.0\n7.5\n9.8\n"
            self.returncode = 0
            
    def mock_run(*args, **kwargs):
        return MockCompletedProcess()
        
    monkeypatch.setattr(subprocess, "run", mock_run)
    points = preview.detect_feature_points("dummy.mp4", max_points=3)
    assert len(points) <= 3

def test_extract_srt_timestamps_thinning(tmp_path):
    """SRTから多くのタイムスタンプを抽出した際の間引き処理のテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # 20個の字幕タイムスタンプを作成
    srt_content = ""
    for i in range(1, 21):
        srt_content += f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n字幕{i}\n\n"
        
    srt_path = tmp_path / "large.srt"
    srt_path.write_text(srt_content, encoding="utf-8")
    
    timestamps = preview._extract_srt_timestamps(str(srt_path), max_points=3)
    assert len(timestamps) == 6

def test_snapshot_step_insufficient_timestamps(tmp_path, monkeypatch):
    """snapshot_stepでタイムスタンプが不足した場合の等間隔サンプリングテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    monkeypatch.setattr(preview, "detect_feature_points", lambda *args: [])
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 10.0)
    
    def mock_extract(video_path, ts, output_path, **kwargs):
        Image.new("RGB", (320, 180)).save(output_path)
        return output_path
    monkeypatch.setattr(preview, "extract_screenshot", mock_extract)
    
    result = preview.snapshot_step(
        step_name="crop",
        before_video="before.mp4",
        after_video="after.mp4",
        num_samples=3
    )
    
    assert len(result["comparisons"]) == 3
    for comp in result["comparisons"]:
        assert comp["timestamp"] < 9.5

def test_snapshot_step_thread_exception(tmp_path, monkeypatch):
    """並列処理で一部のスクリーンショット抽出が失敗（例外発生）した場合のテスト"""
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    monkeypatch.setattr(preview, "_get_video_duration", lambda path: 10.0)
    monkeypatch.setattr(preview, "detect_feature_points", lambda *args: [2.0])
    
    def mock_extract_fail(*args, **kwargs):
        raise RuntimeError("Mock extract failure")
    monkeypatch.setattr(preview, "extract_screenshot", mock_extract_fail)
    
    result = preview.snapshot_step(
        step_name="crop",
        before_video="before.mp4",
        after_video="after.mp4",
        num_samples=1
    )
    assert len(result["comparisons"]) == 0

def test_image_to_base64_failure():
    """画像変換失敗時の例外ハンドリングテスト"""
    generator = PreviewReportGenerator()
    res = generator._image_to_base64("nonexistent_image.png")
    assert res == ""


def test_progressive_preview_report_main(tmp_path, monkeypatch):
    """__main__ブロックの実行テスト"""
    import runpy
    import progressive_preview_report
    report_path = Path(progressive_preview_report.__file__)
    
    orig_generate_html_report = progressive_preview_report.PreviewReportGenerator.generate_html_report
    def mock_generate_html_report(self, session_metadata, output_path, embed_images=True):
        temp_out = tmp_path / "test_report.html"
        return orig_generate_html_report(self, session_metadata, str(temp_out), embed_images)
        
    monkeypatch.setattr(
        progressive_preview_report.PreviewReportGenerator,
        "generate_html_report",
        mock_generate_html_report
    )
    
    # run_path でスクリプトとして実行
    runpy.run_path(str(report_path), run_name="__main__")

def test_validate_thumbnail_quality(tmp_path):
    """プレビューサムネイル品質バリデータのテスト"""
    from unittest.mock import patch
    preview = ProgressivePreview(session_id="test_session", output_dir=str(tmp_path))
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        preview.validate_thumbnail_quality(tmp_path / "non_existent.png")
        
    # 2. 解像度が低い画像 (例えば 640x360)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        preview.validate_thumbnail_quality(low_res_path)
        
    # 3. アスペクト比が正しくない画像 (4:3 解像度 1280x960)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        preview.validate_thumbnail_quality(bad_ratio_path)
        
    # 4. 正常画像 (1280x720)
    valid_path = tmp_path / "valid.png"
    img_valid = Image.new("RGB", (1280, 720), color="green")
    img_valid.save(valid_path, format="PNG")
    
    result_info = preview.validate_thumbnail_quality(valid_path)
    assert result_info["path"] == str(valid_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    # 5. ファイルサイズ制限 (4MB以上)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            preview.validate_thumbnail_quality(valid_path)

def test_stage_bound_agent_integration_preview(tmp_path):
    """StageBoundAgentとの連携テスト"""
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "preview_agent_test.db"
    output_dir = tmp_path / "previews"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    preview = ProgressivePreview(session_id="agent_test", output_dir=str(output_dir))
    preview.width = 1280
    preview.height = 720
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "preview_task_test"
    
    async def run_test():
        # タスクを登録して READY 状態にする
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェントを起動し、タスク解決処理を開始
        await agent.start(preview.resolve_progressive_preview_task)
        
        # 完了または失敗まで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 生成された画像が正しく存在し、破損していないか確認
        output_path = output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        result_info = preview.validate_thumbnail_quality(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBへの結果保存とリトライカウント等のメタデータ整合性を確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn.close()
            
    asyncio.run(run_test())


# ==============================================================================
# Tests for progressive_preview_report.py
# ==============================================================================
def test_validate_thumbnail_report_quality(tmp_path):
    """progressive_preview_report.py の validate_thumbnail の品質検証テスト"""
    from progressive_preview_report import validate_thumbnail
    from PIL import Image
    from unittest.mock import patch
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(tmp_path / "non_existent.png")
        
    # 2. 解像度が低い画像 (640x360)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res_path)
        
    # 3. アスペクト比が正しくない画像 (4:3 解像度 1280x960)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_ratio_path)
        
    # 4. 正常画像 (1280x720)
    valid_path = tmp_path / "valid.png"
    img_valid = Image.new("RGB", (1280, 720), color="green")
    img_valid.save(valid_path, format="PNG")
    
    result_info = validate_thumbnail(valid_path)
    assert result_info["path"] == str(valid_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    # 5. ファイルサイズ制限 (4MB以上)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(valid_path)

    # 6. 破損画像 (ファイルの中身が壊れている)
    corrupted_path = tmp_path / "corrupted.png"
    with open(corrupted_path, "wb") as f:
        f.write(b"not a png image data at all")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupted_path)

def test_generate_progressive_preview_thumbnail_logic(tmp_path):
    """generate_progressive_preview_thumbnail のパラメータ・折り返し・例外テスト"""
    from progressive_preview_report import generate_progressive_preview_thumbnail, validate_thumbnail
    
    # 1. 正常生成
    out_path = tmp_path / "thumbnail.png"
    text = "TEST HEADER\nLine 1: detail\nLine 2: detail"
    res = generate_progressive_preview_thumbnail(out_path, text=text)
    assert res.exists()
    
    # 検証
    info = validate_thumbnail(out_path)
    assert info["width"] == 1280
    assert info["height"] == 720
    
    # 2. 不正な解像度でのエラー
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        generate_progressive_preview_thumbnail(tmp_path / "bad.png", width=640, height=360)
        
    # 3. 不正なアスペクト比でのエラー
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        generate_progressive_preview_thumbnail(tmp_path / "bad.png", width=1280, height=960)

    # 4. 非常に長いテキスト（自動折り返しと縮小の検証）
    long_text = "VERY LONG TITLE THAT EXCEEDS REGULAR WIDTH LIMIT AND NEEDS WRAPPING\n" + "\n".join([f"Detail line info {i} that is also long" for i in range(15)])
    long_out = tmp_path / "long_thumbnail.png"
    generate_progressive_preview_thumbnail(long_out, text=long_text)
    assert long_out.exists()
    assert validate_thumbnail(long_out)["width"] == 1280

def test_stage_bound_agent_integration_report_preview(tmp_path):
    """resolve_progressive_preview_report_task の StageBoundAgent との連携テスト"""
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    from progressive_preview_report import resolve_progressive_preview_report_task, OUTPUT_DIR
    from unittest.mock import patch
    
    db_file = tmp_path / "report_agent_test.db"
    
    # OUTPUT_DIR をテスト用の一時ディレクトリにモック
    test_output_dir = tmp_path / "temp_thumbnails"
    test_output_dir.mkdir()
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "report_task_test"
    
    async def run_test():
        # タスクを登録して READY 状態にする
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェントを起動し、resolve_progressive_preview_report_task でタスク解決処理を開始
        with patch("progressive_preview_report.OUTPUT_DIR", str(test_output_dir)):
            await agent.start(resolve_progressive_preview_report_task)
            
            # 完了または失敗まで待つ
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 生成された画像が正しく存在し、破損していないか確認
        output_path = test_output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        from progressive_preview_report import validate_thumbnail
        result_info = validate_thumbnail(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBへの結果保存とリトライカウント等のメタデータ整合性を確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn.close()
            
    asyncio.run(run_test())


def test_strict_preview_quality_standards_and_agent_pipeline(tmp_path):
    """
    必須品質基準自動検証テスト:
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること
    - ファイルサイズが 4MB 未満であること
    - 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    - StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """
    import asyncio
    import sqlite3
    from PIL import Image
    from unittest.mock import patch
    from agents.stage_bound_agent import StageBoundAgent
    from progressive_preview_report import (
        generate_progressive_preview_thumbnail, 
        validate_thumbnail,
        resolve_progressive_preview_report_task
    )
    
    # 1. 直接生成時の品質基準チェック
    test_out = tmp_path / "strict_quality_test.png"
    text = "STRICT QUALITY STANDARDS CHECK\nResolution: >= 1280x720\nAspect Ratio: 16:9\nSize: < 4MB\nIntegrity: Verified"
    
    # サムネイル生成
    generate_progressive_preview_thumbnail(test_out, width=1280, height=720, text=text)
    
    # 画像の存在確認と完全性確認
    assert test_out.exists()
    result_info = validate_thumbnail(test_out)
    
    # 解像度検証
    assert result_info["width"] >= 1280
    assert result_info["height"] >= 720
    
    # アスペクト比検証 (16:9)
    aspect_ratio = result_info["width"] / result_info["height"]
    assert abs(aspect_ratio - (16.0 / 9.0)) < 0.01
    
    # ファイルサイズ検証 (< 4MB)
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowで読み込みが問題なく可能であること
    with Image.open(test_out) as img:
        img.verify()
    with Image.open(test_out) as img:
        img.load()  # 完全なピクセルロードで破損をチェック
        
    # 2. フォールバック生成時の品質基準チェック
    fallback_out = tmp_path / "fallback_strict_test.png"
    from progressive_preview_report import _generate_fallback_thumbnail
    _generate_fallback_thumbnail(fallback_out, 1280, 720, "Fallback Text", RuntimeError("Simulated Error"))
    
    assert fallback_out.exists()
    fallback_info = validate_thumbnail(fallback_out)
    assert fallback_info["width"] >= 1280
    assert fallback_info["height"] >= 720
    assert abs((fallback_info["width"] / fallback_info["height"]) - (16.0 / 9.0)) < 0.01
    assert fallback_info["size_bytes"] < 4 * 1024 * 1024
    with Image.open(fallback_out) as img:
        img.load()
        
    # 3. StageBoundAgent 連携 (自動リトライ、結果保存、DBマイグレーションの確認)
    db_file = tmp_path / "strict_agent_test.db"
    test_output_dir = tmp_path / "strict_previews"
    test_output_dir.mkdir(parents=True, exist_ok=True)
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "strict_task_verification"
    
    async def run_agent_test():
        # タスクを登録して READY 状態にする (自動リトライ上限を 3 に設定)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=3)
        
        # エージェントを起動し、resolve_progressive_preview_report_task でタスク解決処理を開始
        with patch("progressive_preview_report.OUTPUT_DIR", str(test_output_dir)):
            await agent.start(resolve_progressive_preview_report_task)
            
            # 完了または失敗まで待つ
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status in ("COMPLETED", "FAILED"):
                    break
                await asyncio.sleep(0.05)
                
            final_status = await agent.get_task_status(task_id)
            await agent.stop()
            
        assert final_status == "COMPLETED"
        
        # 生成された画像が正しく存在し、破損していないか確認
        output_path = test_output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        # 結果情報検証
        agent_result = validate_thumbnail(output_path)
        assert agent_result["width"] >= 1280
        assert agent_result["height"] >= 720
        assert agent_result["size_bytes"] < 4 * 1024 * 1024
        
        # DBへの結果保存とリトライカウント等のメタデータ整合性を確認 (DBマイグレーションと結果保存の検証)
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn.close()
            
        # 4. 自動リトライ機能の連携検証 (失敗タスクがリトライされることの確認)
        fail_task_id = "fail_task_retry_verification"
        await agent.register_task(task_id=fail_task_id, initial_status="READY", max_retries=2)
        
        # 意図的に例外を投げる処理関数
        call_count = 0
        async def resolve_fail_task(tid: str) -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError(f"Simulated failure on call {call_count}")
            
        await agent.start(resolve_fail_task)
        
        # 失敗が確定するまで待つ
        for _ in range(50):
            status = await agent.get_task_status(fail_task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(fail_task_id)
        await agent.stop()
        
        assert final_status == "FAILED"
        # max_retries=2 なので、初期実行(1) + リトライ(2) = 計 3 回呼び出されていることを検証
        assert call_count == 3
        
        # DBにリトライカウントとエラー結果が保存されているか確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count FROM tasks WHERE id = ?", (fail_task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count = row
            assert status == "FAILED"
            assert retry_count == 2
        finally:
            conn.close()

    asyncio.run(run_agent_test())
