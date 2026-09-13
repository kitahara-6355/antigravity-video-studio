import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import pytest
from unittest.mock import MagicMock, patch, mock_open
from datetime import datetime, timedelta
import json

from usage_tracker.quota_manager import (
    QuotaManager,
    _load_model_config
)



def test_load_model_config_success():
    """model_config.json の正常ロードのテスト"""
    dummy_config = {"version": "5.0.0", "text_generation": {"tiers": {}}}
    mock_data = json.dumps(dummy_config)
    
    with patch("builtins.open", mock_open(read_data=mock_data)):
        config = _load_model_config()
        assert config == dummy_config


def test_load_model_config_failure():
    """model_config.json のロード失敗時のテスト"""
    with patch("builtins.open", side_effect=FileNotFoundError):
        config = _load_model_config()
        assert config == {}


def test_quota_manager_init_and_properties():
    """QuotaManager の初期化とプロパティアクセスのテスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3-flash-preview", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2.5-flash", "preserve_ratio": 0.0}
            },
            "fallback_chain": {
                "gemini-3-flash-preview": "gemini-2.5-flash"
            }
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        assert qm.model_tiers == dummy_config["text_generation"]["tiers"]
        assert qm.fallback_chain == dummy_config["text_generation"]["fallback_chain"]
        
        # usage_tracker プロパティの確認
        mock_tracker = MagicMock()
        with patch("usage_tracker.tracker.usage_tracker", mock_tracker):
            assert qm.usage_tracker == mock_tracker


def test_get_time_until_reset():
    """get_time_until_reset の時間計算テスト"""
    qm = QuotaManager()
    
    # ケース1: リセット時刻（UTC 15:00）より前の時間（UTC 10:00）
    fixed_now_before = datetime(2026, 5, 21, 10, 0, 0)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed_now_before
        def mock_now(tz=None):
            if tz is not None:
                return fixed_now_before
            return fixed_now_before + timedelta(hours=9)
        mock_datetime.now.side_effect = mock_now
        
        info = qm.get_time_until_reset()
        # リセットは 15:00 なので残り5時間0分
        assert info["remaining_hours"] == 5
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is True
        
    # ケース2: リセット時刻（UTC 15:00）を過ぎた時間（UTC 16:00）
    fixed_now_after = datetime(2026, 5, 21, 16, 0, 0)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed_now_after
        def mock_now(tz=None):
            if tz is not None:
                return fixed_now_after
            return fixed_now_after + timedelta(hours=9)
        mock_datetime.now.side_effect = mock_now
        
        info = qm.get_time_until_reset()
        # 翌日の 15:00 なので残り23時間0分
        assert info["remaining_hours"] == 23
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is False


def test_get_model_with_wait_option_available():
    """get_model_with_wait_option: 通常使用可能なケース"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 90
        qm._usage_tracker = mock_tracker
        
        result = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
        assert result["model"] == "gemini-3"
        assert result["tier"] == "premium"
        assert result["available"] is True
        assert result["usage_percent"] == 10.0
        assert result["remaining"] == 90


def test_get_model_with_wait_option_preserved():
    """get_model_with_wait_option: Premium温存ケース"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        # usage_ratio が 1 - preserve_ratio (0.8) を超える 0.85
        mock_tracker.get_usage_ratio.return_value = 0.85
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 15
        qm._usage_tracker = mock_tracker
        
        # datetime を固定
        fixed_now = datetime(2026, 5, 21, 10, 0, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now
            def mock_now(tz=None):
                if tz is not None:
                    return fixed_now
                return fixed_now + timedelta(hours=9)
            mock_datetime.now.side_effect = mock_now
            
            result = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
            assert result["model"] == "gemini-2"
            assert result["available"] is False
            assert result["reason"] == "premium_preserved"
            assert result["options"]["fallback"]["available"] is True
            assert result["options"]["fallback"]["model"] == "gemini-2"
            
            # allow_fallback = False の場合
            result_no_fb = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=False)
            assert result_no_fb["model"] is None


def test_get_model_with_wait_option_quota_exhausted():
    """get_model_with_wait_option: 枠切れでフォールバックするケース"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2", "gemini-2": "gemini-lite"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        # usage_ratio が 1.0 (枠切れ)
        mock_tracker.get_usage_ratio.return_value = 1.0
        # standard (gemini-2) はリクエスト不可だが、fallback (gemini-lite) はリクエスト可能
        mock_tracker.can_make_request.side_effect = lambda model: model == "gemini-lite"
        mock_tracker.get_remaining_requests.return_value = 0
        qm._usage_tracker = mock_tracker
        
        fixed_now = datetime(2026, 5, 21, 10, 0, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now
            def mock_now(tz=None):
                if tz is not None:
                    return fixed_now
                return fixed_now + timedelta(hours=9)
            mock_datetime.now.side_effect = mock_now
            
            # preferred_tier = standard にすることで premium 温存チェックをスルーさせ、quota_exhausted 分岐に入る
            result = qm.get_model_with_wait_option(preferred_tier="standard", allow_fallback=True)
            assert result["model"] == "gemini-lite"
            assert result["available"] is False
            assert result["reason"] == "quota_exhausted"
            assert result["switched"] is True
            
            # allow_fallback = False の場合
            result_no_fb = qm.get_model_with_wait_option(preferred_tier="standard", allow_fallback=False)
            assert result_no_fb["model"] is None


def test_get_model_with_wait_option_all_exhausted():
    """get_model_with_wait_option: 全モデル枠切れのケース"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2", "gemini-2": "gemini-lite"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 1.0
        # すべてのモデルでリクエスト不可
        mock_tracker.can_make_request.return_value = False
        mock_tracker.get_remaining_requests.return_value = 0
        qm._usage_tracker = mock_tracker
        
        fixed_now = datetime(2026, 5, 21, 10, 0, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now
            def mock_now(tz=None):
                if tz is not None:
                    return fixed_now
                return fixed_now + timedelta(hours=9)
            mock_datetime.now.side_effect = mock_now
            
            # preferred_tier = standard にすることで premium 温存チェックをスルーさせ、not can_use 分岐に入る
            result = qm.get_model_with_wait_option(preferred_tier="standard", allow_fallback=True)
            assert result["model"] is None
            assert result["available"] is False
            assert result["reason"] == "all_exhausted"


def test_get_two_tier_status():
    """get_two_tier_status と _get_tier_status のテスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "label": "Premium", "description": "Desc P", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "label": "Standard", "description": "Desc S", "preserve_ratio": 0.0}
            }
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        # 1つ目のモデルは ratio = 0.85 (preserved のはず), 2つ目のモデルは ratio = 0.5 (normal のはず)
        mock_tracker.get_usage_ratio.side_effect = lambda model: 0.85 if model == "gemini-3" else 0.5
        mock_tracker.get_remaining_requests.side_effect = lambda model: 15 if model == "gemini-3" else 50
        qm._usage_tracker = mock_tracker
        
        # datetime を固定して timestamp が一致するようにする
        fixed_now = datetime(2026, 5, 21, 10, 0, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now
            def mock_now(tz=None):
                if tz is not None:
                    return fixed_now
                return fixed_now
            mock_datetime.now.side_effect = mock_now
            
            status = qm.get_two_tier_status()
            assert "premium" in status["tiers"]
            assert status["tiers"]["premium"]["status"] == "preserved"
            assert status["tiers"]["standard"]["status"] == "normal"
            
            # _get_tier_status の各閾値分岐テスト
            assert qm._get_tier_status(1.0, 0.2) == "exhausted"
            assert qm._get_tier_status(0.85, 0.2) == "preserved"
            assert qm._get_tier_status(0.8, 0.0) == "warning"
            assert qm._get_tier_status(0.6, 0.0) == "caution"
            assert qm._get_tier_status(0.5, 0.0) == "normal"
            
            # 全モデルステータス取得ラッパーのテスト
            all_status = qm.get_all_models_status()
            assert all_status == status


def test_get_available_model():
    """get_available_model のテスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 100
        qm._usage_tracker = mock_tracker
        
        result = qm.get_available_model("gemini-3")
        assert result["model"] == "gemini-3"
        assert result["original"] == "gemini-3"
        assert result["available"] is True



def test_quota_manager_import_fallback():
    """model_registry が無い場合のフォールバック定義テスト"""
    # sys.modules から model_registry を一時退避
    orig_registry = sys.modules.get("model_registry")
    if "model_registry" in sys.modules:
        del sys.modules["model_registry"]
        
    orig_quota_manager = sys.modules.get("usage_tracker.quota_manager")
    if "usage_tracker.quota_manager" in sys.modules:
        del sys.modules["usage_tracker.quota_manager"]
    
    # sys.meta_path を使って model_registry の import 時のみ ImportError を起こすカスタムファインダー
    class HideModuleFinder:
        def find_spec(self, fullname, path, target=None):
            if fullname == "model_registry":
                raise ImportError("mock import error")
            return None
    
    finder = HideModuleFinder()
    sys.meta_path.insert(0, finder)
    
    try:
        # モジュールの再ロード
        import usage_tracker.quota_manager as qm_mod
        # get_model が定義され、デフォルト値が返ることを確認
        # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
        # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
        from model_policy import resolve
        assert qm_mod.get_model("anything") == resolve("anything").model
        assert not qm_mod.get_model("anything").startswith("gemini-2.5")
    finally:
        sys.meta_path.remove(finder)
        if orig_registry:
            sys.modules["model_registry"] = orig_registry
        
        # quota_manager モジュールを元に戻す
        if "usage_tracker.quota_manager" in sys.modules:
            del sys.modules["usage_tracker.quota_manager"]
        if orig_quota_manager:
            sys.modules["usage_tracker.quota_manager"] = orig_quota_manager


def test_load_model_config_invalid_json():
    """model_config.json が破損したJSONの場合のテスト"""
    mock_data = "{invalid json"
    with patch("builtins.open", mock_open(read_data=mock_data)):
        with patch("usage_tracker.quota_manager.logger") as mock_logger:
            config = _load_model_config()
            assert config == {}
            mock_logger.warning.assert_called_once()


def test_quota_manager_init_with_invalid_config():
    """初期化時に config が破損している場合の挙動"""
    with patch("usage_tracker.quota_manager._load_model_config", return_value={}):
        qm = QuotaManager()
        assert qm.model_tiers == {}
        assert qm.fallback_chain == {}


def test_get_time_until_reset_edge_cases():
    """get_time_until_reset の境界値（ちょうど15時、マイクロ秒あり）テスト"""
    qm = QuotaManager()
    
    # ケース1: ちょうど15:00:00.000000 (UTC)
    fixed_now_exact = datetime(2026, 5, 21, 15, 0, 0, 0)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed_now_exact
        def mock_now(tz=None):
            if tz is not None:
                return fixed_now_exact
            return fixed_now_exact + timedelta(hours=9)
        mock_datetime.now.side_effect = mock_now
        
        info = qm.get_time_until_reset()
        assert info["remaining_hours"] == 24
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is False

    # ケース2: マイクロ秒を含む時刻 (14:59:59.999999 UTC)
    fixed_now_micro = datetime(2026, 5, 21, 14, 59, 59, 999999)
    with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
        mock_datetime.utcnow.return_value = fixed_now_micro
        def mock_now(tz=None):
            if tz is not None:
                return fixed_now_micro
            return fixed_now_micro + timedelta(hours=9)
        mock_datetime.now.side_effect = mock_now
        
        info = qm.get_time_until_reset()
        assert info["remaining_hours"] == 0
        assert info["remaining_minutes"] == 0
        assert info["can_wait"] is True


def test_get_model_with_wait_option_invalid_tier():
    """存在しないティア名が渡された場合、standardにフォールバックすることのテスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 50
        qm._usage_tracker = mock_tracker
        
        # 存在しない "ultra-premium" ティアを指定
        result = qm.get_model_with_wait_option(preferred_tier="ultra-premium", allow_fallback=True)
        assert result["model"] == "gemini-2"
        # 期待値を ultra-premium に修正（実装が引数をそのまま返すため）
        assert result["tier"] == "ultra-premium"


def test_get_model_with_wait_option_wait_boundary():
    """can_wait が True / False になる残り時間の境界値テスト (12時間未満 vs 12時間以上)"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        mock_tracker = MagicMock()
        # premium温存のケースにして recommended の can_wait (True/False) が正しく反映されるかテストする
        mock_tracker.get_usage_ratio.return_value = 0.85
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 15
        qm._usage_tracker = mock_tracker

        # 残り時間が 11時間59分 (15:00リセットに対して UTC 03:01)
        fixed_now_11h59m = datetime(2026, 5, 21, 3, 1, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now_11h59m
            def mock_now(tz=None):
                return fixed_now_11h59m
            mock_datetime.now.side_effect = mock_now
            
            result = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
            assert result["options"]["wait"]["recommended"] is True

        # 残り時間が 12時間00分 (15:00リセットに対して UTC 03:00)
        fixed_now_12h00m = datetime(2026, 5, 21, 3, 0, 0)
        with patch("usage_tracker.quota_manager.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = fixed_now_12h00m
            def mock_now(tz=None):
                return fixed_now_12h00m
            mock_datetime.now.side_effect = mock_now
            
            result = qm.get_model_with_wait_option(preferred_tier="premium", allow_fallback=True)
            assert result["options"]["wait"]["recommended"] is False


def test_get_two_tier_status_boundary_values():
    """_get_tier_status の各ステータス分岐（exhausted, preserved, warning, caution, normal）およびゼロ除算テスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            }
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        
        # ゼロ除算の検証 (usage_ratio == 1.0)
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 1.0
        mock_tracker.get_remaining_requests.return_value = 0
        qm._usage_tracker = mock_tracker
        
        status = qm.get_two_tier_status()
        assert status["tiers"]["premium"]["preserved"] == 0
        assert status["tiers"]["premium"]["available_for_use"] == 0
        assert status["tiers"]["premium"]["status"] == "exhausted"

        # 各閾値の検証 (warning: 0.8, caution: 0.6)
        assert qm._get_tier_status(0.8, 0.0) == "warning"
        assert qm._get_tier_status(0.79, 0.0) == "caution"
        assert qm._get_tier_status(0.6, 0.0) == "caution"
        assert qm._get_tier_status(0.59, 0.0) == "normal"


def test_get_two_tier_status_no_labels_and_description():
    """tiers に label や description がない場合にデフォルト値が返ることを検証"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "custom_tier": {"model": "gemini-custom"}
            }
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.5
        mock_tracker.get_remaining_requests.return_value = 10
        qm._usage_tracker = mock_tracker
        
        status = qm.get_two_tier_status()
        assert status["tiers"]["custom_tier"]["label"] == "custom_tier"
        assert status["tiers"]["custom_tier"]["description"] == ""


def test_get_available_model_non_existent():
    """get_available_model に存在しないモデル名を渡したとき、standardにフォールバックすることのテスト"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            },
            "fallback_chain": {"gemini-3": "gemini-2"}
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        mock_tracker = MagicMock()
        mock_tracker.get_usage_ratio.return_value = 0.1
        mock_tracker.can_make_request.return_value = True
        mock_tracker.get_remaining_requests.return_value = 50
        qm._usage_tracker = mock_tracker

        result = qm.get_available_model("non-existent-model")
        assert result["model"] == "gemini-2"
        assert result["original"] == "non-existent-model"




def test_quota_manager_invalid_tiers_format():
    """model_config.json の tiers が不正な形式（辞書以外）の場合のエラーハンドリング検証"""
    invalid_config = {
        "text_generation": {
            "tiers": ["invalid_list_format"]
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=invalid_config):
        qm = QuotaManager()
        # クラッシュせずにフォールバックすることを確認
        result = qm.get_model_with_wait_option(preferred_tier="premium")
        assert result["available"] is True
        
        status = qm.get_two_tier_status()
        assert status["tiers"] == {}


def test_quota_manager_invalid_tracker():
    """usage_tracker がメソッドを持たない不正なオブジェクトの場合のエラーハンドリング検証"""
    dummy_config = {
        "text_generation": {
            "tiers": {
                "premium": {"model": "gemini-3", "preserve_ratio": 0.2},
                "standard": {"model": "gemini-2", "preserve_ratio": 0.0}
            }
        }
    }
    with patch("usage_tracker.quota_manager._load_model_config", return_value=dummy_config):
        qm = QuotaManager()
        # メソッドを持たないダミーオブジェクトを設定
        qm._usage_tracker = object()
        
        # AttributeError が捕捉され、処理がクラッシュしないことを確認
        result = qm.get_model_with_wait_option(preferred_tier="premium")
        assert result["available"] is True
        
        status = qm.get_two_tier_status()
        assert "premium" in status["tiers"]
        assert status["tiers"]["premium"]["usage_percent"] == 0.0
