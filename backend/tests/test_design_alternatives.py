import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from backend.design_alternatives import (
    generate_design_alternatives,
    DesignAlternativesError
)

# ============================================================
# 入力バリデーションのテスト
# ============================================================

def test_validation_input_video_empty(tmp_path):
    with pytest.raises(ValueError, match="input_video cannot be empty or None"):
        generate_design_alternatives("", str(tmp_path))

def test_validation_input_video_none(tmp_path):
    with pytest.raises(ValueError, match="input_video cannot be empty or None"):
        generate_design_alternatives(None, str(tmp_path))

def test_validation_input_video_not_found(tmp_path):
    non_existent = tmp_path / "non_existent.mp4"
    with pytest.raises(FileNotFoundError, match="input_video does not exist"):
        generate_design_alternatives(str(non_existent), str(tmp_path))

def test_validation_output_dir_empty(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    with pytest.raises(ValueError, match="output_dir cannot be empty or None"):
        generate_design_alternatives(str(input_video), "")

def test_validation_output_dir_none(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    with pytest.raises(ValueError, match="output_dir cannot be empty or None"):
        generate_design_alternatives(str(input_video), None)

def test_output_dir_creation_failure(tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    # 既存のファイルを output_dir に指定すると、mkdirでOSErrorが発生する
    invalid_output_dir = tmp_path / "blocked_by_file"
    invalid_output_dir.write_text("not a directory")
    with pytest.raises(DesignAlternativesError, match="Failed to create output directory"):
        generate_design_alternatives(str(input_video), str(invalid_output_dir))


# ============================================================
# 正常系のテスト
# ============================================================

@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.design_alternatives.LogoOverlay")
@patch("backend.design_alternatives.LogoManager")
def test_generate_design_alternatives_success(
    mock_logo_manager,
    mock_logo_overlay,
    mock_combined_overlay,
    mock_sub_run,
    tmp_path
):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy video")
    output_dir = tmp_path / "output"
    
    # Mock setups
    # LogoManager
    instance_logo_manager = mock_logo_manager.return_value
    instance_logo_manager.get_logo_path.return_value = "/dummy/logo.png"

    # 実行
    alternatives = generate_design_alternatives(str(input_video), str(output_dir))
    
    # 成果物の検証
    assert len(alternatives) == 4
    assert alternatives[0] == ("A案（現在）", str(output_dir / "A_current_logo60_telop24.mp4"))
    assert alternatives[1] == ("B案（控えめ）", str(output_dir / "B_moderate_logo45.mp4"))
    assert alternatives[2] == ("C案（ミニマル）", str(output_dir / "C_minimal_logo35.mp4"))
    assert alternatives[3] == ("D案（ロゴのみ）", str(output_dir / "D_logo_only.mp4"))
    
    # ffmpegが呼ばれたことの確認
    mock_sub_run.assert_called_once()
    
    # 一時ファイルが削除されていることの検証
    assert not (output_dir / "base_10s.mp4").exists()


# ============================================================
# 異常系・例外マッピングのテスト
# ============================================================

# 1. FFmpeg CalledProcessError
@patch("backend.design_alternatives.subprocess.run")
def test_ffmpeg_process_error(mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy video")
    
    mock_sub_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd="ffmpeg", stderr="mock ffmpeg error"
    )
    
    with pytest.raises(DesignAlternativesError, match="FFmpeg extraction failed"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 2. FFmpeg FileNotFoundError (command not found)
@patch("backend.design_alternatives.subprocess.run")
def test_ffmpeg_not_found_error(mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy video")
    
    mock_sub_run.side_effect = FileNotFoundError("command not found")
    
    with pytest.raises(DesignAlternativesError, match="ffmpeg command not found"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 3. CombinedOverlay 初期化失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
def test_combined_overlay_init_failure(mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy video")
    
    mock_combined_overlay.side_effect = RuntimeError("init failed")
    
    with pytest.raises(DesignAlternativesError, match="Failed to initialize CombinedOverlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 4. A案 overlay 適用失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
def test_overlay_a_failure(mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy video")
    
    instance = mock_combined_overlay.return_value
    instance.apply_brand_overlay.side_effect = RuntimeError("overlay a failed")
    
    with pytest.raises(DesignAlternativesError, match="Failed to apply A案 overlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 5. B案用 Telop 生成失敗は削除（Dead Code 除去に伴い不要）

# 6. B案 overlay 適用失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
def test_overlay_b_failure(mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    instance_overlay = mock_combined_overlay.return_value
    # A案は成功させ、B案適用時にエラー
    instance_overlay.apply_brand_overlay.side_effect = [None, RuntimeError("overlay b failed")]
    
    with pytest.raises(DesignAlternativesError, match="Failed to apply B案 overlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 7. C案 overlay 適用失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
def test_overlay_c_failure(mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    instance_overlay = mock_combined_overlay.return_value
    # A案, B案は成功させ、C案適用時にエラー
    instance_overlay.apply_brand_overlay.side_effect = [None, None, RuntimeError("overlay c failed")]
    
    with pytest.raises(DesignAlternativesError, match="Failed to apply C案 overlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 8. LogoOverlay / LogoManager 初期化失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.design_alternatives.LogoManager")
def test_logo_init_failure(mock_logo_manager, mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    instance_overlay = mock_combined_overlay.return_value
    instance_overlay.apply_brand_overlay.side_effect = [None, None, None]
    
    mock_logo_manager.side_effect = RuntimeError("logo init failed")
    
    with pytest.raises(DesignAlternativesError, match="Failed to initialize logo manager/overlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))

# 9. D案 logo overlay 適用失敗
@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.design_alternatives.LogoOverlay")
@patch("backend.design_alternatives.LogoManager")
def test_logo_d_failure(
    mock_logo_manager,
    mock_logo_overlay,
    mock_combined_overlay,
    mock_sub_run,
    tmp_path
):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    instance_overlay = mock_combined_overlay.return_value
    instance_overlay.apply_brand_overlay.side_effect = [None, None, None]
    
    instance_logo_manager = mock_logo_manager.return_value
    instance_logo_manager.get_logo_path.return_value = "/dummy/logo.png"
    
    instance_logo_overlay = mock_logo_overlay.return_value
    instance_logo_overlay.apply_logo_with_fade.side_effect = RuntimeError("logo apply failed")
    
    with pytest.raises(DesignAlternativesError, match="Failed to apply D案 logo overlay"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))


# ============================================================
# クリーンアップのテスト
# ============================================================

@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
def test_cleanup_on_failure(mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 正常処理時に削除されるべき一時ファイルを事前作成
    temp_video = output_dir / "base_10s.mp4"
    temp_video.write_text("temp video content")
    
    # A案で失敗させる
    instance = mock_combined_overlay.return_value
    instance.apply_brand_overlay.side_effect = RuntimeError("overlay failed")
    
    with pytest.raises(DesignAlternativesError):
        generate_design_alternatives(str(input_video), str(output_dir))
        
    # 一時ファイルがfinallyブロックで確実に削除されていることを検証
    assert not temp_video.exists()


# ============================================================
# 技術負債登録のテスト
# ============================================================

@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_technical_debt_registration_on_exception(mock_debt_store, mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    # 想定外の例外をスローさせる（個別catchされないsubprocess.runなどでZeroDivisionErrorを投げる）
    mock_sub_run.side_effect = ZeroDivisionError("unexpected division by zero")
    
    mock_store_instance = mock_debt_store.return_value
    
    with pytest.raises(DesignAlternativesError, match="Design alternatives generation failed: unexpected division by zero"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))
        
    # TechnicalDebtStore.register_debt が正しく呼ばれたことを検証。
    # line_number は traceback から実行時に取る値なので、期待値も
    # ソースから引く。数値を直書きすると、上に 1 行足しただけで落ちる。
    import backend.design_alternatives as da_mod

    source_lines = Path(da_mod.__file__).read_text(encoding="utf-8").splitlines()
    expected_line = next(
        i for i, line in enumerate(source_lines, 1)
        if "subprocess.run(extract_cmd" in line
    )

    mock_store_instance.register_debt.assert_called_once_with(
        category="MINOR_INFRA",
        file_path="backend/design_alternatives.py",
        line_number=expected_line,
        pattern="except Exception as e:",
        cause_pattern="DP-01",
        fix_pattern="具体的な例外の個別キャッチ",
        registered_by="thumbnail_robustification",
        notes="一時ファイル削除のための最終防壁catch"
    )


# ============================================================
# 例外処理の追加カバレッジテスト
# ============================================================

@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.agents.memory.technical_debt.TechnicalDebtStore")
def test_technical_debt_registration_fails(mock_debt_store, mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    # 想定外の例外をスローさせる
    mock_sub_run.side_effect = ZeroDivisionError("unexpected division by zero")
    
    # register_debt が例外を投げるようにする
    mock_store_instance = mock_debt_store.return_value
    mock_store_instance.register_debt.side_effect = RuntimeError("debt store failure")
    
    with pytest.raises(DesignAlternativesError, match="Design alternatives generation failed: unexpected division by zero"):
        generate_design_alternatives(str(input_video), str(tmp_path / "output"))


@patch("backend.design_alternatives.subprocess.run")
@patch("backend.design_alternatives.CombinedOverlay")
@patch("backend.design_alternatives.Path.unlink")
def test_cleanup_unlink_fails(mock_unlink, mock_combined_overlay, mock_sub_run, tmp_path):
    input_video = tmp_path / "input.mp4"
    input_video.write_text("dummy")
    
    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 正常処理時に削除されるべき一時ファイルを事前作成
    temp_video = output_dir / "base_10s.mp4"
    temp_video.write_text("temp video content")
    
    # A案で失敗させる
    instance = mock_combined_overlay.return_value
    instance.apply_brand_overlay.side_effect = RuntimeError("overlay failed")
    
    # unlinkが失敗するようにモック
    mock_unlink.side_effect = RuntimeError("permission denied on unlink")
    
    with pytest.raises(DesignAlternativesError):
        generate_design_alternatives(str(input_video), str(output_dir))
