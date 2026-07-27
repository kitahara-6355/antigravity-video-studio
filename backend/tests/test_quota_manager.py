import pytest
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, mock_open
import sys

# sys.path に backend フォルダを追加して、インポート可能にする
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from usage_tracker.quota_manager import QuotaManager, _load_model_config, get_model

@pytest.fixture
def temp_model_config(tmp_path):
    config_path = tmp_path / "model_config.json"
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {
                    "model": "gemini-2.5-pro",
                    "label": "Premium Model",
                    "description": "High performance",
                    "preserve_ratio": 0.2
                },
                "standard": {
                    "model": "gemini-2.5-flash",
                    "label": "Standard Model",
                    "description": "Balanced",
                    "preserve_ratio": 0.0
                }
            },
            "fallback_chain": {
                "gemini-2.5-pro": "gemini-2.5-flash",
                "gemini-2.5-flash": None
            }
        }
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(dummy_config, f, indent=2)
    return config_path




def test_load_model_config_exceptions(tmp_path, caplog):
    # 1. 存在しないパスでの読み込み
    non_existent = tmp_path / "not_found.json"
    with caplog.at_level(logging.WARNING):
        # デフォルトの CONFIG_PATH は backend/model_config.json を見に行くが、
        # ここでは例外系のカバレッジを通すために、_load_model_config の CONFIG_PATH を patch する。
        with patch("usage_tracker.quota_manager.CONFIG_PATH", non_existent):
            config = _load_model_config()
            assert config == {}
            assert "QuotaManager: model_config.json load failed" in caplog.text

    caplog.clear()

    # 2. open時のOSErrorをシミュレート
    with patch("builtins.open", side_effect=OSError("Read blocked")):
        with caplog.at_level(logging.ERROR):
            config = _load_model_config()
            assert config == {}
            assert "QuotaManager: model_config.json OS error" in caplog.text

    caplog.clear()

    # 3. JSONDecodeError をシミュレート
    with patch("builtins.open", mock_open(read_data="{invalid json")):
        with caplog.at_level(logging.WARNING):
            config = _load_model_config()
            assert config == {}
            assert "QuotaManager: model_config.json load failed" in caplog.text


def test_quota_manager_init(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        assert qm.model_tiers["premium"]["model"] == "gemini-2.5-pro"
        assert qm.fallback_chain["gemini-2.5-pro"] == "gemini-2.5-flash"


def test_get_time_until_reset():
    qm = QuotaManager()
    
    # 1. リセット時刻（15:00 UTC）より前の場合
    # 2026-05-29 10:00:00 UTC に固定
    mock_now = datetime(2026, 5, 29, 10, 0, 0)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = mock_now
        mock_datetime.now.return_value = mock_now
        
        info = qm.get_time_until_reset()
        assert info["remaining_hours"] == 5
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is True
        assert "5時間0分" in info["remaining_display"]

    # 2. リセット時刻（15:00 UTC）より後の場合
    # 2026-05-29 16:00:00 UTC に固定
    mock_now = datetime(2026, 5, 29, 16, 0, 0)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = mock_now
        mock_datetime.now.return_value = mock_now
        
        info = qm.get_time_until_reset()
        assert info["remaining_hours"] == 23
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is False
        assert "23時間0分" in info["remaining_display"]


def test_get_model_with_wait_option_normal(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # usage_trackerのモック
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 8
        qm._usage_tracker = mock_tracker
        
        res = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
        assert res["model"] == "gemini-2.5-pro"
        assert res["available"] is True
        assert res["remaining"] == 8
        assert res["usage_percent"] == 10.0


def test_get_model_with_wait_option_preserved(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # usage_ratio が 0.85 (1.0 - preserve_ratio(0.2) = 0.8 未満なので温存発動)
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.85
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 3
        qm._usage_tracker = mock_tracker
        
        # 1. allow_fallback = True の場合
        res_fallback = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
        assert res_fallback["model"] == "gemini-2.5-flash"  # fallback_chain に従う
        assert res_fallback["available"] is False
        assert res_fallback["reason"] == "premium_preserved"
        assert res_fallback["options"]["fallback"]["available"] is True
        assert res_fallback["options"]["force"]["available"] is True

        # 2. allow_fallback = False の場合
        res_no_fallback = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=False)
        assert res_no_fallback["model"] is None
        assert res_no_fallback["options"]["fallback"]["available"] is False


def test_get_model_with_wait_option_exhausted_fallback(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # 温存チェックを回避するため、一時的に preserve_ratio を 0.0 に変更
        qm._config["text_generation"]["tiers"]["premium"]["preserve_ratio"] = 0.0
        
        # Premiumは枠切れ(can_make_request=False), Standardは枠あり(can_make_request=True)
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.side_effect = lambda m: 1.0 if m == "gemini-2.5-pro" else 0.2
        mock_tracker.can_make_request.side_effect = lambda m: False if m == "gemini-2.5-pro" else True
        mock_tracker.get_remaining_requests.side_effect = lambda m: 0 if m == "gemini-2.5-pro" else 8
        qm._usage_tracker = mock_tracker
        
        res = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
        assert res["model"] == "gemini-2.5-flash"
        assert res["available"] is False
        assert res["reason"] == "quota_exhausted"
        assert res["switched"] is True
        assert res["options"]["fallback"]["available"] is True


def test_get_model_with_wait_option_all_exhausted(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # 全モデル枠切れ
        mock_tracker = MagicMock()
        mock_tracker.can_make_request.return_value = False
        mock_tracker.get_usage_ratio.return_value = 0.0
        mock_tracker.get_remaining_requests.return_value = 0
        qm._usage_tracker = mock_tracker
        
        res = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
        assert res["model"] is None
        assert res["available"] is False
        assert res["reason"] == "all_exhausted"
        assert res["options"]["wait"]["available"] is True


def test_get_two_tier_status_and_tier_status_states(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # usage_trackerのモック
        mock_tracker = MagicMock()
        # standardは warning (0.85), premiumは caution (0.65) になるように設定
        mock_tracker.get_usage_ratio.side_effect = lambda m: 0.65 if m == "gemini-2.5-pro" else 0.85
        mock_tracker.get_remaining_requests.side_effect = lambda m: 15 if m == "gemini-2.5-pro" else 30
        qm._usage_tracker = mock_tracker
        
        status = qm.get_two_tier_status()
        assert "tiers" in status
        assert status["tiers"]["premium"]["status"] == "caution"
        assert status["tiers"]["standard"]["status"] == "warning"

        # 個別の判定関数 _get_tier_status も直接検証
        # exhausted
        assert qm._get_tier_status(1.0, 0.2) == "exhausted"
        assert qm._get_tier_status(1.1, 0.2) == "exhausted"
        # preserved
        assert qm._get_tier_status(0.85, 0.2) == "preserved"
        # warning
        assert qm._get_tier_status(0.82, 0.0) == "warning"
        # caution
        assert qm._get_tier_status(0.65, 0.0) == "caution"
        # normal
        assert qm._get_tier_status(0.3, 0.2) == "normal"


def test_get_available_model(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 10
        qm._usage_tracker = mock_tracker
        
        # 通常ケース
        res = qm.get_available_model(preferred_model="gemini-2.5-pro")
        assert res["model"] == "gemini-2.5-pro"
        assert res["available"] is True
        assert res["original"] == "gemini-2.5-pro"

        # model_configに登録されていない適当なモデル名の場合はstandardフォールバック
        res_unknown = qm.get_available_model(preferred_model="unknown-model")
        assert res_unknown["model"] == "gemini-2.5-flash"




def test_get_all_models_status(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.0
        mock_tracker.get_remaining_requests.return_value = 10
        qm._usage_tracker = mock_tracker

        status = qm.get_all_models_status()
        assert "tiers" in status
        assert "premium" in status["tiers"]
        assert "standard" in status["tiers"]


def test_usage_tracker_property_lazy_load():
    # usage_tracker プロパティの遅延ロードを検証
    qm = QuotaManager()
    qm._usage_tracker = None
    
    tracker = qm.usage_tracker
    assert tracker is not None
    # 2回目以降もキャッシュされたインスタンスが返ることを検証
    assert qm.usage_tracker is tracker


def test_model_registry_import_error():
    # sys.modulesから model_registry と quota_manager を一時的に退避/削除
    import builtins
    orig_import = builtins.__import__
    orig_model_registry = sys.modules.pop("model_registry", None)
    orig_quota_manager = sys.modules.pop("usage_tracker.quota_manager", None)
    
    # インポート時に ImportError を発生させるモック
    def mock_import(name, *args, **kwargs):
        if name == "model_registry":
            raise ImportError("Mocked ImportError")
        return orig_import(name, *args, **kwargs)
        
    try:
        with patch("builtins.__import__", side_effect=mock_import):
            # quota_manager から get_model をインポート
            # これにより quota_manager.py が実行され、ImportErrorが発生し、fallbackのget_modelが定義される
            from usage_tracker.quota_manager import get_model
            assert get_model("proofreader") == "gemini-2.5-flash"
    finally:
        # sys.modulesを元に戻す
        if orig_model_registry is not None:
            sys.modules["model_registry"] = orig_model_registry
        if orig_quota_manager is not None:
            sys.modules["usage_tracker.quota_manager"] = orig_quota_manager

def test_get_model_with_wait_option_edge_cases(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # usage_tracker のモック
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.0
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 10
        qm._usage_tracker = mock_tracker
        
        # 1. 存在しないティアを指定した場合（standardにフォールバックされるはず）
        res = qm.get_model_with_wait_option(preferred_tier="non-existent-tier")
        # standard ティアのモデルは gemini-2.5-flash
        assert res["model"] == "gemini-2.5-flash"
        assert res["tier"] == "non-existent-tier"
        assert res["available"] is True

        # 2. allow_fallback=False かつ 枠切れの場合
        mock_tracker.can_make_request.side_effect = lambda m: False if m == "gemini-2.5-pro" else True
        res_no_fallback = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=False)
        assert res_no_fallback["model"] is None
        assert res_no_fallback["available"] is False
        assert res_no_fallback["reason"] == "quota_exhausted"


def test_get_two_tier_status_bounds(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # 1. 使用率が 1.0 (100%) の場合（ゼロ除算の回避と exhausted ステータス）
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 1.0
        mock_tracker.get_remaining_requests.return_value = 0
        qm._usage_tracker = mock_tracker
        
        status_exhausted = qm.get_two_tier_status()
        premium_status = status_exhausted["tiers"]["premium"]
        assert premium_status["status"] == "exhausted"
        assert premium_status["preserved"] == 0
        assert premium_status["available_for_use"] == 0

        # 2. 使用率が 0.0 の場合
        mock_tracker.get_usage_ratio.return_value = 0.0
        mock_tracker.get_remaining_requests.return_value = 10
        status_empty = qm.get_two_tier_status()
        premium_status_empty = status_empty["tiers"]["premium"]
        # premium の preserve_ratio は 0.2
        # limit = 10 / (1.0 - 0.0) = 10
        # preserve_count = int(10 * 0.2) = 2
        # available_count = 10 - 2 = 8
        assert premium_status_empty["status"] == "normal"
        assert premium_status_empty["preserved"] == 2
        assert premium_status_empty["available_for_use"] == 8




def test_get_time_until_reset_boundary_times():
    qm = QuotaManager()
    
    # 1. リセット時刻 (15:00 UTC) の直前 (14:59:59 UTC)
    mock_now_before = datetime(2026, 5, 29, 14, 59, 59)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = mock_now_before
        mock_datetime.now.return_value = mock_now_before
        
        info = qm.get_time_until_reset()
        assert info["remaining_hours"] == 0
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is True

    # 2. リセット時刻 (15:00 UTC) の直後 (15:00:01 UTC)
    mock_now_after = datetime(2026, 5, 29, 15, 0, 1)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = mock_now_after
        mock_datetime.now.return_value = mock_now_after
        
        info = qm.get_time_until_reset()
        # 翌日の15:00 UTCになるため、残り23時間59分59秒
        assert info["remaining_hours"] == 23
        assert info["remaining_minutes"] == 59
        assert info["can_wait"] is False


def test_quota_manager_exceptions_and_edge_cases():
    qm = QuotaManager()
    
    # 1. model_tiers が dict ではない場合 (_resolve_tier_config, get_two_tier_status)
    qm._config = {"text_generation": {"tiers": None}}
    model, preserve = qm._resolve_tier_config("premium")
    assert model == get_model("proofreader")
    assert preserve == 0.0
    
    status = qm.get_two_tier_status()
    assert status["tiers"] == {}

    # 2. preferred_tier が存在せず、standard も dict ではない場合
    qm._config = {"text_generation": {"tiers": {"standard": None}}}
    model, preserve = qm._resolve_tier_config("premium")
    assert model == get_model("proofreader")
    assert preserve == 0.0

    # 3. preserve_ratio が int/float ではない場合
    qm._config = {
        "text_generation": {
            "tiers": {
                "standard": {
                    "model": "gemini-2.5-flash",
                    "preserve_ratio": "invalid"
                }
            }
        }
    }
    model, preserve = qm._resolve_tier_config("standard")
    assert model == "gemini-2.5-flash"
    assert preserve == 0.0

    # 4. fallback_chain が dict ではない場合 (_build_preserve_response, _build_exhausted_response)
    qm._config = {
        "text_generation": {
            "tiers": {
                "premium": {
                    "model": "gemini-2.5-pro",
                    "preserve_ratio": 0.2
                }
            },
            "fallback_chain": None
        }
    }
    mock_tracker = MagicMock()
    mock_tracker.get_usage_ratio.return_value = 0.9
    mock_tracker.can_make_request.return_value = True
    mock_tracker.get_remaining_requests.return_value = 3
    qm._usage_tracker = mock_tracker
    
    res = qm._build_preserve_response("gemini-2.5-pro", "premium", allow_fallback=True)
    assert res["model"] is None
    assert res["options"]["fallback"]["available"] is False
    
    mock_tracker.can_make_request.return_value = False
    res_ex = qm._build_exhausted_response("gemini-2.5-pro", allow_fallback=True)
    assert res_ex["model"] is None
    assert res_ex["reason"] == "all_exhausted"

    # 5. usage_tracker.can_make_request で AttributeError が発生する場合
    mock_tracker_attr = MagicMock()
    mock_tracker_attr.can_make_request.side_effect = AttributeError("No attribute")
    qm._usage_tracker = mock_tracker_attr
    qm._config = {
        "text_generation": {
            "fallback_chain": {"gemini-2.5-pro": "gemini-2.5-flash"}
        }
    }
    res_ex_attr = qm._build_exhausted_response("gemini-2.5-pro", allow_fallback=True)
    assert res_ex_attr["reason"] == "all_exhausted"

    # 6. get_model_with_wait_option 内で usage_tracker が required method を持たない場合
    qm._usage_tracker = object()
    qm._config = {
        "text_generation": {
            "tiers": {
                "premium": {
                    "model": "gemini-2.5-pro"
                }
            }
        }
    }
    res_wait = qm.get_model_with_wait_option("premium")
    assert res_wait["available"] is True
    assert res_wait["remaining"] == 999
    assert res_wait["usage_percent"] == 0.0

    # 7. _build_tier_status_info で tier_config が dict ではない場合
    assert qm._build_tier_status_info("premium", None) is None

    # 8. _build_tier_status_info で usage_tracker が AttributeError を投げる場合
    qm._usage_tracker = object()
    res_status = qm._build_tier_status_info("premium", {"model": "gemini-2.5-pro"})
    assert res_status["usage_percent"] == 0.0
    assert res_status["remaining"] == 0

    # 9. _build_tier_status_info で preserve_ratio が int/float ではない場合
    mock_tracker_ok = MagicMock()
    mock_tracker_ok.get_usage_ratio.return_value = 0.5
    mock_tracker_ok.get_remaining_requests.return_value = 10
    qm._usage_tracker = mock_tracker_ok
    res_status_inv = qm._build_tier_status_info("premium", {"model": "gemini-2.5-pro", "preserve_ratio": "invalid"})
    assert res_status_inv["preserved"] == 0


def test_refactored_quota_manager_features(temp_model_config):
    with patch("usage_tracker.quota_manager.CONFIG_PATH", temp_model_config):
        qm = QuotaManager()
        
        # usage_trackerのモック
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.get_remaining_requests.return_value = 8
        qm._usage_tracker = mock_tracker

        # 1. get_all_tiers_status と get_two_tier_status の同等性テスト
        status_all = qm.get_all_tiers_status()
        status_two = qm.get_two_tier_status()
        assert status_all["reset_info"] == status_two["reset_info"]
        assert status_all["tiers"] == status_two["tiers"]
        
        # 2. _build_reset_time_response の直接テスト
        from usage_tracker.quota_manager import JST_OFFSET_HOURS, CAN_WAIT_THRESHOLD_HOURS
        assert JST_OFFSET_HOURS == 9
        assert CAN_WAIT_THRESHOLD_HOURS == 12
        
        now = datetime.now()
        res_reset = qm._build_reset_time_response(now, 5, 30)
        assert res_reset["remaining_hours"] == 5
        assert res_reset["remaining_minutes"] == 30
        assert res_reset["can_wait"] is True
        assert "5時間30分" in res_reset["remaining_display"]

        # 3. get_all_models_status のテスト
        status_models = qm.get_all_models_status()
        assert status_models["tiers"] == status_all["tiers"]


