import pytest
import json
import logging
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

# sys.path に backend フォルダを追加して、インポート可能にする
import sys
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from usage_tracker.tracker import DailyUsage, UsageRecord, UsageTracker, _load_model_config

# テスト用のヘルパー関数: 一時的な usage_data.json と model_config.json を準備
@pytest.fixture
def temp_configs(tmp_path):
    usage_path = tmp_path / "usage_data.json"
    config_path = tmp_path / "model_config.json"
    
    # ダミーの model_config.json 作成
    dummy_config = {
        "version": "5.0.0",
        "free_tier_limits": {
            "gemini-2.5-flash": {
                "rpd": 5,
                "tier": "standard"
            },
            "gemini-2.5-flash-lite": {
                "rpd": 10,
                "tier": "batch"
            },
            "limited-model": {
                "rpd": 0,
                "tier": "none"
            }
        },
        "text_generation": {
            "fallback_chain": {
                "gemini-2.5-flash": "gemini-2.5-flash-lite",
                "gemini-2.5-flash-lite": None
            }
        },
        "image_generation": {
            "fallback_chain": {}
        },
        "video_generation": {
            "fallback_chain": {}
        },
        "alert_thresholds": {
            "info": 0.5,
            "warning": 0.7,
            "block": 0.9,
            "critical": 1.0
        }
    }
    
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(dummy_config, f, indent=2)
        
    return usage_path, config_path


def test_usage_record_init():
    record = UsageRecord(model="gemini-2.5-flash", requests=2)
    assert record.model == "gemini-2.5-flash"
    assert record.requests == 2
    assert record.tokens_in == 0
    assert record.tokens_out == 0
    assert record.timestamp is not None


def test_daily_usage_robustness():
    du = DailyUsage(date=date.today().isoformat())
    
    # 正常ケース
    du.add_request("gemini-2.5-flash", 100, 200)
    assert du.get_requests("gemini-2.5-flash") == 1
    assert du.models["gemini-2.5-flash"]["tokens_in"] == 100
    assert du.models["gemini-2.5-flash"]["tokens_out"] == 200
    
    # ガード処理テスト: 空文字モデル
    with pytest.raises(ValueError, match="Model name cannot be empty"):
        du.add_request("")
        
    # ガード処理テスト: 負のトークン数
    du.add_request("gemini-2.5-flash", -50, -100)
    # 負の数は max(0, ...) で丸められるため、値は加算されない
    assert du.models["gemini-2.5-flash"]["tokens_in"] == 100
    assert du.models["gemini-2.5-flash"]["tokens_out"] == 200
    
    # get_requests に空文字を渡した場合
    assert du.get_requests("") == 0
    assert du.get_requests("non-existent") == 0


def test_load_model_config_exceptions(tmp_path, caplog):
    # 1. 存在しないパス
    non_existent = tmp_path / "not_found.json"
    with caplog.at_level(logging.WARNING):
        config = _load_model_config(non_existent)
        assert config == {}
        assert "UsageTracker: model_config.json load failed" in caplog.text
        
    caplog.clear()
    
    # 2. 壊れたJSON
    broken_json = tmp_path / "broken.json"
    with open(broken_json, "w", encoding="utf-8") as f:
        f.write("{invalid json}")
        
    with caplog.at_level(logging.WARNING):
        config = _load_model_config(broken_json)
        assert config == {}
        assert "UsageTracker: model_config.json load failed" in caplog.text
        
    caplog.clear()
    
    # 3. OSErrorをシミュレート
    with patch("builtins.open", side_effect=OSError("Disk full or physical OS error")):
        with caplog.at_level(logging.ERROR):
            config = _load_model_config(tmp_path / "some_file.json")
            assert config == {}
            assert "UsageTracker: model_config.json OS error" in caplog.text


def test_tracker_load_or_create_daily_usage(temp_configs):
    usage_path, config_path = temp_configs
    
    # 初期化時に usage_data.json が存在しない場合 → 新規作成
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    assert tracker._daily_usage.date == date.today().isoformat()
    assert usage_path.exists()
    
    # 既存の usage_data.json があり、本日日付の場合 → ロードされること
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": date.today().isoformat(),
            "models": {
                "gemini-2.5-flash": {"requests": 3, "tokens_in": 10, "tokens_out": 20}
            }
        }, f)
        
    tracker2 = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    assert tracker2._daily_usage.get_requests("gemini-2.5-flash") == 3
    
    # 既存の usage_data.json が壊れたJSONの場合 → 新規作成され、ログ出力警告
    with open(usage_path, "w", encoding="utf-8") as f:
        f.write("invalid json content")
        
    with patch("logging.Logger.warning") as mock_warn:
        tracker3 = UsageTracker(usage_path=usage_path, model_config_path=config_path)
        assert tracker3._daily_usage.date == date.today().isoformat()
        assert tracker3._daily_usage.get_requests("gemini-2.5-flash") == 0
        mock_warn.assert_called()
        
    # 読み込み時に OSError が発生した場合 → 新規作成され、エラーログ
    # ファイルオブジェクトを開く builtins.open に side_effect=OSError を与える
    with patch("builtins.open", side_effect=OSError("Read blocked")):
        with patch("logging.Logger.error") as mock_err:
            tracker4 = UsageTracker(usage_path=usage_path, model_config_path=config_path)
            assert tracker4._daily_usage.date == date.today().isoformat()
            mock_err.assert_called()


def test_tracker_save_usage_exceptions(temp_configs, caplog):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # 1. TypeError (シリアライズ不可なオブジェクトを入れる)
    tracker._daily_usage.models["gemini-2.5-flash"] = {"requests": set([1, 2])} # setはJSONシリアライズ不可
    with caplog.at_level(logging.ERROR):
        tracker._save_usage()
        assert "Failed to serialize usage data" in caplog.text
        
    caplog.clear()
    
    # 2. OSError (書き込み不可など)
    tracker._daily_usage.models["gemini-2.5-flash"] = {"requests": 1, "tokens_in": 0, "tokens_out": 0}
    with patch("builtins.open", side_effect=OSError("Write blocked")):
        with caplog.at_level(logging.ERROR):
            tracker._save_usage()
            assert "OS error saving usage data" in caplog.text


def test_tracker_track_request_guards_and_date_change(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # 引数ガード: 空のモデル
    with pytest.raises(ValueError, match="Model name cannot be empty"):
        tracker.track_request("")
        
    # 日付切り替わりテスト
    # 前日の日付にセット
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tracker._daily_usage = DailyUsage(
        date=yesterday,
        models={"gemini-2.5-flash": {"requests": 4, "tokens_in": 100, "tokens_out": 100}}
    )
    
    # track_request すると日付が本日に更新され、リクエスト数がリセットされてから 1 になること
    res = tracker.track_request("gemini-2.5-flash", 50, 50)
    assert tracker._daily_usage.date == date.today().isoformat()
    assert res["requests_today"] == 1
    assert res["blocked"] is False


def test_tracker_usage_ratios_and_escalation(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # rpd=5 のモデルに対してリクエストを送る
    model = "gemini-2.5-flash"
    
    # 1回目 (20%): normal
    res = tracker.track_request(model)
    assert res["alert_level"] == "normal"
    assert tracker.can_make_request(model) is True
    
    # 3回目 (60%): info (閾値0.5以上)
    tracker.track_request(model)
    res = tracker.track_request(model)
    assert res["alert_level"] == "info"
    assert tracker.can_make_request(model) is True
    
    # 4回目 (80%): warning (閾値0.7以上)
    res = tracker.track_request(model)
    assert res["alert_level"] == "warning"
    assert tracker.can_make_request(model) is True
    
    # 5回目 (100%): critical (閾値1.0以上)
    res = tracker.track_request(model)
    assert res["alert_level"] == "critical"
    assert res["blocked"] is True
    assert tracker.can_make_request(model) is False
    assert tracker.get_remaining_requests(model) == 0

    # block (閾値0.9以上) のテストを追加 (rpd=10)
    model_lite = "gemini-2.5-flash-lite"
    for _ in range(8):
        tracker.track_request(model_lite)
    res_block = tracker.track_request(model_lite)
    assert res_block["alert_level"] == "block"
    assert tracker.can_make_request(model_lite) is False


def test_tracker_callback_exception(temp_configs, caplog):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # 例外を投げるコールバック
    def broken_callback(result):
        raise RuntimeError("Callback crashed")
        
    tracker.register_alert_callback(broken_callback)
    
    # コールバックがクラッシュしても、track_request は最後まで正常終了すること
    with caplog.at_level(logging.ERROR):
        res = tracker.track_request("gemini-2.5-flash")
        assert res["requests_today"] == 1
        assert "Alert callback failed" in caplog.text
        
    # コールバック登録のガード
    with pytest.raises(TypeError, match="Callback must be callable"):
        tracker.register_alert_callback("not-callable")


def test_tracker_guards_on_query_methods(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # model が空または None の場合
    assert tracker.get_usage_ratio("") == 0.0
    assert tracker.can_make_request("") is False
    assert tracker.get_remaining_requests("") == 0
    
    # RPDが 0 のモデル
    assert tracker.get_usage_ratio("limited-model") == 0.0
    assert tracker.can_make_request("limited-model") is True
    
    # 登録されていないモデル (デフォルト RPD=1000)
    assert tracker.get_usage_ratio("unknown-model") == 0.0
    assert tracker.can_make_request("unknown-model") is True
    assert tracker.get_remaining_requests("unknown-model") == 1000
    
    # 内部メソッドの空モデル名ガードのテスト
    assert tracker._get_rpd("") == 1000


def test_tracker_get_daily_summary(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    tracker.track_request("gemini-2.5-flash")
    summary = tracker.get_daily_summary()
    
    assert summary["date"] == date.today().isoformat()
    assert "gemini-2.5-flash" in summary["models"]
    assert summary["models"]["gemini-2.5-flash"]["used"] == 1
    # limit=0 の limited-model は除外されていること
    assert "limited-model" not in summary["models"]


def test_tracker_get_model_recommendation(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # 引数ガード
    with pytest.raises(ValueError, match="Task name cannot be empty"):
        tracker.get_model_recommendation("")
        
    # normal: model_registry から正常取得 (mock する)
    # mock_get_model を model_registry モジュールからインポートしたように見せる
    sys.modules["model_registry"] = MagicMock()
    import model_registry
    model_registry.get_model.return_value = "gemini-2.5-flash"
    
    rec = tracker.get_model_recommendation("transcribe")
    assert rec == "gemini-2.5-flash"
    
    # フォールバック: 推奨モデルが制限に達している場合
    # gemini-2.5-flash の RPD を使い切る (limit=5)
    for _ in range(5):
        tracker.track_request("gemini-2.5-flash")
        
    assert tracker.can_make_request("gemini-2.5-flash") is False
    
    # get_model_recommendation が "gemini-2.5-flash" から "gemini-2.5-flash-lite" へフォールバックすること
    rec_fallback = tracker.get_model_recommendation("transcribe")
    assert rec_fallback == "gemini-2.5-flash-lite"
    
    # 例外パス: model_registry の読み込みで ImportError 等が発生
    del sys.modules["model_registry"]
    if "model_registry" in sys.modules:
        sys.modules.pop("model_registry")
        
    # get_model を呼び出したときに NameError が起きる状況をシミュレート
    with patch("builtins.__import__", side_effect=ImportError("No module named model_registry")):
        rec_ex = tracker.get_model_recommendation("transcribe")
        # デフォルトの gemini-2.5-flash が返るが、制限に達しているので gemini-2.5-flash-lite へフォールバック
        assert rec_ex == "gemini-2.5-flash-lite"
        
    # 一般例外 (Exception) パス
    sys.modules["model_registry"] = MagicMock()
    import model_registry as mr_mock
    mr_mock.get_model.side_effect = Exception("Registry corrupted")
    
    rec_gen_ex = tracker.get_model_recommendation("transcribe")
    assert rec_gen_ex == "gemini-2.5-flash-lite"


def test_tracker_load_old_daily_usage(temp_configs):
    usage_path, config_path = temp_configs
    
    # 昨日の日付で usage_data.json を作成
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with open(usage_path, "w", encoding="utf-8") as f:
        json.dump({
            "date": yesterday,
            "models": {
                "gemini-2.5-flash": {"requests": 3, "tokens_in": 10, "tokens_out": 20}
            }
        }, f)
        
    # 初期化時に過去日付のデータが存在する場合、本日日付で新規作成されること
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    assert tracker._daily_usage.date == date.today().isoformat()
    assert tracker._daily_usage.get_requests("gemini-2.5-flash") == 0


def test_tracker_get_model_recommendation_no_fallback(temp_configs):
    usage_path, config_path = temp_configs
    tracker = UsageTracker(usage_path=usage_path, model_config_path=config_path)
    
    # model_registry から "gemini-2.5-flash-lite" が返るように設定
    sys.modules["model_registry"] = MagicMock()
    import model_registry
    model_registry.get_model.return_value = "gemini-2.5-flash-lite"
    
    # "gemini-2.5-flash-lite" を上限（rpd=10）まで使い切る
    for _ in range(10):
        tracker.track_request("gemini-2.5-flash-lite")
        
    assert tracker.can_make_request("gemini-2.5-flash-lite") is False
    
    # gemini-2.5-flash-lite のフォールバック先は None であるため、
    # フォールバックされずに優先モデル "gemini-2.5-flash-lite" が返る
    rec = tracker.get_model_recommendation("transcribe")
    assert rec == "gemini-2.5-flash-lite"
    
    # ケース 2b: フォールバック先も制限に達している場合
    # 優先モデルを "gemini-2.5-flash" (rpd=5) に戻し、そのフォールバック先 "gemini-2.5-flash-lite" も使い切っている状態にする
    model_registry.get_model.return_value = "gemini-2.5-flash"
    
    # "gemini-2.5-flash" も上限（rpd=5）まで使い切る
    for _ in range(5):
        tracker.track_request("gemini-2.5-flash")
        
    assert tracker.can_make_request("gemini-2.5-flash") is False
    assert tracker.can_make_request("gemini-2.5-flash-lite") is False
    
    # 両方制限到達しているので、優先モデル "gemini-2.5-flash" がそのまま返る
    rec2 = tracker.get_model_recommendation("transcribe")
    assert rec2 == "gemini-2.5-flash"
