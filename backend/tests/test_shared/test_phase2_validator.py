import pytest
from unittest.mock import patch, MagicMock
import requests
import json
import subprocess
from pathlib import Path

# テスト対象のモジュール
from tests import phase2_validator

# 正常系のモックデータ定義
MOCK_COMPLETED_DATA = {
    "status": "completed",
    "result": {
        "segments_count": 5,
        "preview_path": "/path/to/preview.mp4",
        "final_path": "/path/to/final.mp4",
        "quality_score": 92,
        "duration_seconds": 120,
        "stage_results": [
            {"name": "文字起こし", "success": True, "detail": "5 segments found"},
            {"name": "AI校閲", "success": True, "detail": "2 corrections applied"},
            {"name": "SmartCut", "success": True, "detail": "cut from 5m to 1m"},
        ],
        "quality_details": {
            "score": 92,
            "category_report": [
                {"category": "core"},
                {"category": "template"},
                {"category": "broadcast"},
                {"category": "youtube"},
            ]
        },
        "metadata": {
            "titles": ["驚くべき動画"],
            "tags": ["テスト", "自動化", "動画", "AI", "パイプライン"],
            "chapters": [{"time": "0:00", "title": "イントロ"}]
        }
    }
}


class TestPhase2Validator:

    @patch("requests.get")
    def test_get_pipeline_result(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "completed"}
        mock_get.return_value = mock_resp
        
        result = phase2_validator.get_pipeline_result()
        assert result == {"status": "completed"}

    @patch("requests.get")
    def test_get_pipeline_result_exception(self, mock_get):
        mock_get.side_effect = requests.exceptions.RequestException("connection failed")
        result = phase2_validator.get_pipeline_result()
        assert result["status"] == "error"
        assert "Connection failed" in result["error"]

    def test_check_stage_result_found(self):
        stages = [
            {"name": "文字起こしステージ", "success": True},
            {"name": "AI校閲ステージ", "success": False}
        ]
        res = phase2_validator.check_stage_result(stages, "文字起こし")
        assert res == {"name": "文字起こしステージ", "success": True}

    def test_check_stage_result_not_found(self):
        stages = [
            {"name": "文字起こしステージ", "success": True}
        ]
        res = phase2_validator.check_stage_result(stages, "SmartCut")
        assert res is None

    @patch("subprocess.run")
    def test_check_ffprobe_success(self, mock_run):
        # 1回目 (video): h264, 2回目 (audio): aac
        mock_res_video = MagicMock()
        mock_res_video.stdout = json.dumps({"streams": [{"codec_name": "h264"}]})
        mock_res_audio = MagicMock()
        mock_res_audio.stdout = json.dumps({"streams": [{"codec_name": "aac"}]})
        
        mock_run.side_effect = [mock_res_video, mock_res_audio]
        
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert v_codec == "h264"
        assert a_codec == "aac"

    @patch("subprocess.run")
    def test_check_ffprobe_error(self, mock_run):
        mock_run.side_effect = subprocess.SubprocessError("ffprobe failed")
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert "error" in v_codec
        assert a_codec == ""

    @patch("subprocess.run")
    def test_check_ffprobe_empty_streams(self, mock_run):
        mock_res_video = MagicMock()
        mock_res_video.stdout = json.dumps({"streams": []})
        mock_res_audio = MagicMock()
        mock_res_audio.stdout = json.dumps({"streams": []})
        mock_run.side_effect = [mock_res_video, mock_res_audio]
        
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert v_codec == ""
        assert a_codec == ""

    @patch("subprocess.run")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    def test_run_checks_all_pass(self, mock_stat, mock_exists, mock_run):
        mock_exists.return_value = True
        mock_stat_val = MagicMock()
        mock_stat_val.st_size = 2 * 1024 * 1024  # 2MB
        mock_stat.return_value = mock_stat_val
        
        # ffprobeのモック
        mock_res_video = MagicMock()
        mock_res_video.stdout = json.dumps({"streams": [{"codec_name": "h264"}]})
        mock_res_audio = MagicMock()
        mock_res_audio.stdout = json.dumps({"streams": [{"codec_name": "aac"}]})
        mock_run.side_effect = [mock_res_video, mock_res_audio]

        checks = phase2_validator.run_checks(MOCK_COMPLETED_DATA)
        for name, ok, detail in checks:
            assert ok is True, f"{name} failed: {detail}"

    @patch("pathlib.Path.exists")
    def test_run_checks_failures(self, mock_exists):
        # プレビューと最終成果物が存在しない、またはサイズが不足している場合のテスト
        mock_exists.return_value = False
        
        # データの一部を未完了やエラーにする
        bad_data = {
            "status": "completed",
            "result": {
                "segments_count": 0,  # ①不合格
                "preview_path": None,
                "final_path": None,
                "stage_results": [
                    {"name": "文字起こし", "success": False},  # ①不合格
                    {"name": "AI校閲", "success": False},      # ②不合格
                    # ③SmartCut未実行
                ],
                "quality_details": {
                    "score": 75,  # ⑤不合格 (80点未満)
                    "category_report": [
                        {"category": "core"}  # ⑤不合格 (カテゴリ不足)
                    ]
                },
                "metadata": {
                    "titles": [],  # ⑦不合格
                    "tags": [],    # ⑦不合格
                    "chapters": [] # ⑦不合格
                }
            }
        }
        
        checks = phase2_validator.run_checks(bad_data)
        
        # すべて不合格であることを検証
        for name, ok, detail in checks:
            assert ok is False, f"Expected {name} to fail, but it passed: {detail}"

    @patch("tests.phase2_validator.get_pipeline_result")
    @patch("tests.phase2_validator.run_checks")
    def test_main_not_completed(self, mock_run_checks, mock_get_result):
        mock_get_result.return_value = {"status": "running"}
        passed = phase2_validator.main()
        assert passed is False
        mock_run_checks.assert_not_called()

    @patch("tests.phase2_validator.get_pipeline_result")
    @patch("tests.phase2_validator.run_checks")
    def test_main_completed_all_pass(self, mock_run_checks, mock_get_result):
        mock_get_result.return_value = {"status": "completed"}
        mock_run_checks.return_value = [("Check 1", True, "ok"), ("Check 2", True, "ok")]
        
        passed = phase2_validator.main()
        assert passed is True

    @patch("tests.phase2_validator.get_pipeline_result")
    @patch("tests.phase2_validator.run_checks")
    def test_main_completed_with_failure(self, mock_run_checks, mock_get_result):
        mock_get_result.return_value = {"status": "completed"}
        mock_run_checks.return_value = [("Check 1", True, "ok"), ("Check 2", False, "fail")]
        
        passed = phase2_validator.main()
        assert passed is False


    @patch("requests.get")
    def test_get_pipeline_result_timeout(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")
        result = phase2_validator.get_pipeline_result()
        assert result["status"] == "error"
        assert "Connection failed" in result["error"]
        assert "Request timed out" in result["error"]

    @patch("requests.get")
    def test_get_pipeline_result_http_error(self, mock_get):
        mock_get.side_effect = requests.exceptions.HTTPError("HTTP error occurred")
        result = phase2_validator.get_pipeline_result()
        assert result["status"] == "error"
        assert "Connection failed" in result["error"]
        assert "HTTP error occurred" in result["error"]

    @patch("subprocess.run")
    def test_check_ffprobe_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=10)
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert "error" in v_codec
        assert a_codec == ""

    @patch("subprocess.run")
    def test_check_ffprobe_invalid_json(self, mock_run):
        mock_res = MagicMock()
        mock_res.stdout = "{ invalid json }"
        mock_run.return_value = mock_res
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert "error" in v_codec
        assert a_codec == ""

    @patch("subprocess.run")
    def test_check_ffprobe_filenotfound(self, mock_run):
        mock_run.side_effect = FileNotFoundError("[Errno 2] No such file or directory: 'ffprobe'")
        v_codec, a_codec = phase2_validator.check_ffprobe("dummy_path.mp4")
        assert "error" in v_codec
        assert a_codec == ""

    @patch("subprocess.run")
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.stat")
    def test_run_checks_boundary_file_sizes(self, mock_stat, mock_exists, mock_run):
        mock_exists.return_value = True
        
        # ちょうど1MB (1024 * 1024)
        mock_stat_val = MagicMock()
        mock_stat_val.st_size = 1 * 1024 * 1024
        mock_stat.return_value = mock_stat_val
        
        mock_res_video = MagicMock()
        mock_res_video.stdout = json.dumps({"streams": [{"codec_name": "h264"}]})
        mock_res_audio = MagicMock()
        mock_res_audio.stdout = json.dumps({"streams": [{"codec_name": "aac"}]})
        mock_run.side_effect = [mock_res_video, mock_res_audio, mock_res_video, mock_res_audio]

        checks = phase2_validator.run_checks(MOCK_COMPLETED_DATA)
        # ④ プレビュー生成 (1MB以下はFalse) と ⑥ 最終レンダリング (1MB以下はFalse) が不合格になること
        checks_dict = {name: ok for name, ok, _ in checks}
        assert checks_dict["④ プレビュー生成"] is False
        assert checks_dict["⑥ 最終レンダリング"] is False

        # 1MB超 (1024 * 1024 + 1)
        mock_stat_val.st_size = 1 * 1024 * 1024 + 1
        checks = phase2_validator.run_checks(MOCK_COMPLETED_DATA)
        checks_dict = {name: ok for name, ok, _ in checks}
        assert checks_dict["④ プレビュー生成"] is True
        assert checks_dict["⑥ 最終レンダリング"] is True

    def test_run_checks_missing_fields(self):
        # 必要なフィールドが完全に欠落している場合の例外フォールバック検証
        bad_data = {}
        checks = phase2_validator.run_checks(bad_data)
        for name, ok, detail in checks:
            assert ok is False


    def test_run_checks_corrupted_structure(self):
        # データ構造が破損している・想定外の型であるケースの検証（防衛ガードテスト）
        
        # 1. dataが辞書でない
        checks = phase2_validator.run_checks(None)
        for _, ok, _ in checks:
            assert ok is False

        # 2. resultが辞書でない
        checks = phase2_validator.run_checks({"result": "not_a_dict"})
        for _, ok, _ in checks:
            assert ok is False

        # 3. stage_resultsがNone
        checks = phase2_validator.run_checks({"result": {"stage_results": None}})
        for _, ok, _ in checks:
            assert ok is False

        # 4. stage_resultsの中に辞書でない要素がある
        checks = phase2_validator.run_checks({"result": {"stage_results": ["not_a_dict"]}})
        for _, ok, _ in checks:
            assert ok is False

        # 5. quality_detailsがNone
        checks = phase2_validator.run_checks({"result": {"quality_details": None}})
        for _, ok, _ in checks:
            assert ok is False

        # 6. category_reportがNone
        checks = phase2_validator.run_checks({"result": {"quality_details": {"category_report": None}}})
        for _, ok, _ in checks:
            assert ok is False

        # 7. metadataがNone
        checks = phase2_validator.run_checks({"result": {"metadata": None}})
        for _, ok, _ in checks:
            assert ok is False

        # 8. titles, tags, chaptersがNone
        checks = phase2_validator.run_checks({
            "result": {
                "metadata": {
                    "titles": None,
                    "tags": None,
                    "chapters": None
                }
            }
        })
        for _, ok, _ in checks:
            assert ok is False

    @patch("requests.get")
    def test_get_pipeline_result_invalid_json_http_error(self, mock_get):
        mock_resp = MagicMock()
        import requests.exceptions
        mock_resp.json.side_effect = requests.exceptions.JSONDecodeError("Expecting value", "", 0)
        mock_get.return_value = mock_resp
        
        result = phase2_validator.get_pipeline_result()
        assert result["status"] == "error"
        assert "Connection failed" in result["error"]

    def test_run_checks_category_report_mixed_types(self):
        # category_report のリストに辞書以外のオブジェクトが混在している場合
        bad_data = {
            "status": "completed",
            "result": {
                "quality_details": {
                    "score": 90,
                    "category_report": [
                        {"category": "core"},
                        None,
                        "not_a_dict",
                        {"category": "template"},
                        {"category": "broadcast"},
                        {"category": "youtube"}
                    ]
                }
            }
        }
        checks = phase2_validator.run_checks(bad_data)
        checks_dict = {name: ok for name, ok, _ in checks}
        assert checks_dict["⑤ 品質ゲート"] is True


    def test_run_checks_invalid_path_types(self):
        # preview_path や final_path が辞書やリストなどの想定外の型であるケース
        # および OS 的に例外を投げるような無効な文字を含むケース
        bad_path_data_dict = {
            "status": "completed",
            "result": {
                "preview_path": {"invalid": "type"},
                "final_path": ["invalid", "type"]
            }
        }
        checks = phase2_validator.run_checks(bad_path_data_dict)
        checks_dict = {name: ok for name, ok, _ in checks}
        assert checks_dict["④ プレビュー生成"] is False
        assert checks_dict["⑥ 最終レンダリング"] is False

        # preview_path や final_path が無効な文字（ヌル文字など）を含み OSError を投げるケースの擬似検証
        bad_path_data_oserror = {
            "status": "completed",
            "result": {
                "preview_path": "invalid\x00path",
                "final_path": "invalid\x00path"
            }
        }
        checks2 = phase2_validator.run_checks(bad_path_data_oserror)
        checks_dict2 = {name: ok for name, ok, _ in checks2}
        assert checks_dict2["④ プレビュー生成"] is False
        assert checks_dict2["⑥ 最終レンダリング"] is False

    @patch("pathlib.Path.exists")
    def test_run_checks_path_exceptions(self, mock_exists):
        # exists() が OSError などの例外を投げる場合の検証
        mock_exists.side_effect = OSError("mocked os error")
        
        bad_path_data = {
            "status": "completed",
            "result": {
                "preview_path": "/some/path.mp4",
                "final_path": "/some/path.mp4"
            }
        }
        checks = phase2_validator.run_checks(bad_path_data)
        checks_dict = {name: ok for name, ok, _ in checks}
        # クラッシュせずに False になること
        assert checks_dict["④ プレビュー生成"] is False
        assert checks_dict["⑥ 最終レンダリング"] is False

    def test_check_preview_image_success(self, tmp_path):
        from combined_overlay import CombinedOverlay
        overlay = CombinedOverlay()
        img_path = tmp_path / "valid_thumb.png"
        overlay.generate_thumbnail(img_path, width=1280, height=720, text="Valid")
        
        result = {
            "preview_path": str(img_path)
        }
        ok, detail = phase2_validator._check_preview(result)
        assert ok is True
        assert "valid_thumb.png" in detail

    def test_check_preview_image_low_res(self, tmp_path):
        from PIL import Image
        img_path = tmp_path / "low_res.png"
        img = Image.new("RGB", (640, 360), color=(73, 109, 137))
        img.save(img_path, "PNG")
        
        result = {
            "preview_path": str(img_path)
        }
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "Resolution must be at least 1280x720" in detail

    def test_check_preview_image_bad_aspect(self, tmp_path):
        from PIL import Image
        img_path = tmp_path / "bad_aspect.png"
        img = Image.new("RGB", (1280, 800), color=(73, 109, 137))
        img.save(img_path, "PNG")
        
        result = {
            "preview_path": str(img_path)
        }
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "Aspect ratio must be 16:9" in detail

    def test_check_preview_image_too_large(self, tmp_path):
        from PIL import Image
        img_path = tmp_path / "too_large.png"
        # 1280x720 の画像を保存
        img = Image.new("RGB", (1280, 720), color=(73, 109, 137))
        img.save(img_path, "PNG")
        # サイズを偽装するために 4MB 以上追記
        with open(img_path, "ab") as f:
            f.write(b"\x00" * (4 * 1024 * 1024 + 100))
            
        result = {
            "preview_path": str(img_path)
        }
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "File size must be less than 4MB" in detail

    def test_check_preview_image_corrupted(self, tmp_path):
        img_path = tmp_path / "corrupt.png"
        img_path.write_text("invalid data", encoding="utf-8")
        
        result = {
            "preview_path": str(img_path)
        }
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "Image verify failed" in detail

    def test_check_preview_stage_bound_agent_success(self, tmp_path):
        from agents.stage_bound_agent import StageBoundAgent
        from combined_overlay import CombinedOverlay
        import sqlite3
        import json
        
        db_file = tmp_path / "agent_test.db"
        img_path = tmp_path / "valid_thumb.png"
        
        overlay = CombinedOverlay()
        overlay.generate_thumbnail(img_path, width=1280, height=720, text="Valid")
        
        # StageBoundAgentの準備
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
        task_id = "t_phase2_success"
        
        # DBにタスク登録
        conn = sqlite3.connect(str(db_file))
        try:
            conn.execute(
                "INSERT INTO tasks (id, stage, status, retry_count, result) VALUES (?, ?, ?, ?, ?)",
                (task_id, "thumbnail", "COMPLETED", 0, json.dumps({"width": 1280, "height": 720, "path": str(img_path)}))
            )
            conn.commit()
        finally:
            conn.close()
            
        result = {
            "preview_path": str(img_path),
            "db_path": str(db_file),
            "task_id": task_id
        }
        
        ok, detail = phase2_validator._check_preview(result)
        assert ok is True
        assert "valid_thumb.png" in detail

    def test_check_preview_stage_bound_agent_failure(self, tmp_path):
        from agents.stage_bound_agent import StageBoundAgent
        from combined_overlay import CombinedOverlay
        import sqlite3
        
        db_file = tmp_path / "agent_test_fail.db"
        img_path = tmp_path / "valid_thumb.png"
        
        overlay = CombinedOverlay()
        overlay.generate_thumbnail(img_path, width=1280, height=720, text="Valid")
        
        # StageBoundAgentの準備
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
        
        # DBにタスク登録 (FAILED)
        conn = sqlite3.connect(str(db_file))
        try:
            conn.execute(
                "INSERT INTO tasks (id, stage, status, retry_count, error) VALUES (?, ?, ?, ?, ?)",
                ("t_phase2_fail", "thumbnail", "FAILED", 2, "Some error occurred")
            )
            conn.commit()
        finally:
            conn.close()
            
        result = {
            "preview_path": str(img_path),
            "db_path": str(db_file),
            "task_id": "t_phase2_fail"
        }
        
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "status is FAILED, expected COMPLETED" in detail

    def test_check_preview_stage_bound_agent_missing_task(self, tmp_path):
        from agents.stage_bound_agent import StageBoundAgent
        from combined_overlay import CombinedOverlay
        import sqlite3
        
        db_file = tmp_path / "agent_test_missing.db"
        img_path = tmp_path / "valid_thumb.png"
        
        overlay = CombinedOverlay()
        overlay.generate_thumbnail(img_path, width=1280, height=720, text="Valid")
        
        # StageBoundAgentの準備 (空のテーブルを作成)
        agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
            
        result = {
            "preview_path": str(img_path),
            "db_path": str(db_file),
            "task_id": "non_existent_task"
        }
        
        ok, detail = phase2_validator._check_preview(result)
        assert ok is False
        assert "Task non_existent_task not found in database" in detail


    @patch("sqlite3.connect")
    def test_fetch_agent_task_record_db_error(self, mock_connect):
        import sqlite3
        mock_connect.side_effect = sqlite3.Error("Mocked SQLite connection error")
        row, err = phase2_validator._fetch_agent_task_record("dummy.db", "task_1")
        assert row is None
        assert "Database connection/query failed" in err

    @patch("sqlite3.connect")
    def test_fetch_agent_task_record_close_error(self, mock_connect):
        import sqlite3
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.fetchone.return_value = ("COMPLETED", "{}", 0)
        mock_conn.close.side_effect = sqlite3.Error("Mocked close error")
        mock_connect.return_value = mock_conn
        
        row, err = phase2_validator._fetch_agent_task_record("dummy.db", "task_1")
        assert row == ("COMPLETED", "{}", 0)
        assert err is None

    def test_validate_agent_task_record_empty_result(self):
        row = ("COMPLETED", "", 0)
        ok, err = phase2_validator._validate_agent_task_record("task_1", row)
        assert ok is False
        assert "has empty result in database" in err

    def test_validate_agent_task_record_invalid_dimensions(self):
        row = ("COMPLETED", '{"path": "foo"}', 0)
        ok, err = phase2_validator._validate_agent_task_record("task_1", row)
        assert ok is False
        assert "result data is invalid" in err

    def test_validate_agent_task_record_invalid_retry(self):
        row = ("COMPLETED", '{"width": 1280, "height": 720}', -1)
        ok, err = phase2_validator._validate_agent_task_record("task_1", row)
        assert ok is False
        assert "has invalid retry_count" in err

        row2 = ("COMPLETED", '{"width": 1280, "height": 720}', None)
        ok2, err2 = phase2_validator._validate_agent_task_record("task_1", row2)
        assert ok2 is False
        assert "has invalid retry_count" in err2

    def test_validate_agent_task_record_json_error(self):
        row = ("COMPLETED", "{invalid_json", 0)
        ok, err = phase2_validator._validate_agent_task_record("task_1", row)
        assert ok is False
        assert "JSON validation failed" in err

    def test_check_preview_invalid_path_type_non_str(self):
        result = {"preview_path": 12345}
        ok, err = phase2_validator._check_preview(result)
        assert ok is False
        assert "does not exist" in err

    @patch("tests.phase2_validator._fetch_agent_task_record")
    def test_verify_stage_bound_agent_db_error(self, mock_fetch):
        mock_fetch.return_value = (None, "Mocked DB connection failed")
        ok, err = phase2_validator._verify_stage_bound_agent("dummy.db", "task_1")
        assert ok is False
        assert "Mocked DB connection failed" in err
