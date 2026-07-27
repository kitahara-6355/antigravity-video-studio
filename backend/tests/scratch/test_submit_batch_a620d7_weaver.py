import sys
import os
import pytest
import builtins
import types
from unittest.mock import MagicMock
from pathlib import Path

# バックエンドの親ディレクトリ（video-automation）を sys.path に追加し、backend.* としてインポートできるようにする
BACKEND_PARENT = Path(__file__).resolve().parent.parent.parent.parent
if str(BACKEND_PARENT) not in sys.path:
    sys.path.insert(0, str(BACKEND_PARENT))

@pytest.fixture
def clean_sys():
    # テスト前の sys.modules と sys.path を退避
    orig_modules = sys.modules.copy()
    orig_path = sys.path.copy()
    
    # テスト対象モジュールがすでにインポートされている場合は削除してクリーンな状態にする
    if "backend.scratch.submit_batch_a620d7_weaver" in sys.modules:
        del sys.modules["backend.scratch.submit_batch_a620d7_weaver"]
        
    yield
    
    # テスト終了後に復元
    sys.modules.clear()
    sys.modules.update(orig_modules)
    sys.path = orig_path

def test_submit_batch_weaver_normal(clean_sys):
    # モックの OrchestrationHub を作成
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_queue_status.return_value = {"batch_id": "test_batch_123"}
    
    # agents.orchestration.orchestrator モジュールをモックとして sys.modules に登録
    mock_orchestrator = types.ModuleType("agents.orchestration.orchestrator")
    mock_orchestrator.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    sys.modules["agents.orchestration.orchestrator"] = mock_orchestrator
    sys.modules["agents.orchestration"] = types.ModuleType("agents.orchestration")
    sys.modules["agents"] = types.ModuleType("agents")
    
    # ライン 7 の `sys.path.insert` 分岐をカバーするため、一時的に sys.path から backend パスを取り除く
    backend_path_str = str(BACKEND_PARENT / "backend")
    # Windows でパスの区切り文字や大文字小文字の違いがあるかもしれないので、正規化して除去
    normalized_backend = os.path.normpath(backend_path_str)
    sys.path = [p for p in sys.path if os.path.normpath(p) != normalized_backend]
    
    # スクリプトを実行（インポート）
    import backend.scratch.submit_batch_a620d7_weaver
    
    # 6つのタスクが mark_task_done されたことを確認
    assert mock_hub_instance.mark_task_done.call_count == 6
    
    # submit_batch_report が期待される引数で呼び出されたことを確認
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "test_batch_123",
        {"passed": 18, "failed": 0, "total": 18}
    )

def test_submit_batch_weaver_missing_batch_id(clean_sys):
    # batch_id が取得できないケースの検証
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_queue_status.return_value = {}  # batch_id キーなし
    
    mock_orchestrator = types.ModuleType("agents.orchestration.orchestrator")
    mock_orchestrator.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    sys.modules["agents.orchestration.orchestrator"] = mock_orchestrator
    sys.modules["agents.orchestration"] = types.ModuleType("agents.orchestration")
    sys.modules["agents"] = types.ModuleType("agents")
    
    import backend.scratch.submit_batch_a620d7_weaver
    
    # デフォルトの batch_a620d7 が使用されることを検証
    mock_hub_instance.submit_batch_report.assert_called_once_with(
        "batch_a620d7",
        {"passed": 18, "failed": 0, "total": 18}
    )

def test_submit_batch_weaver_import_error_fallback(clean_sys):
    # 'agents' からのインポート時に ImportError を発生させ、
    # 'backend.agents' からのインポートにフォールバックするルートの検証
    mock_hub_instance = MagicMock()
    mock_hub_instance.get_queue_status.return_value = {"batch_id": "fallback_batch_id"}
    
    # backend.agents 側のモックを準備
    mock_backend_orchestrator = types.ModuleType("backend.agents.orchestration.orchestrator")
    mock_backend_orchestrator.OrchestrationHub = MagicMock(return_value=mock_hub_instance)
    
    original_import = builtins.__import__
    
    def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
        # 'agents' または 'agents.*' のインポートで ImportError を発生させる
        if name == "agents" or name.startswith("agents."):
            raise ImportError("Simulated import error for test")
        
        # 'backend.agents' の場合はモックを返す
        if name == "backend.agents.orchestration.orchestrator":
            return mock_backend_orchestrator
            
        return original_import(name, globals, locals, fromlist, level)
        
    builtins.__import__ = custom_import
    try:
        import backend.scratch.submit_batch_a620d7_weaver
        
        # 例外処理を通り、backend 側から正しくロードされ実行されたことを確認
        assert mock_hub_instance.mark_task_done.call_count == 6
        mock_hub_instance.submit_batch_report.assert_called_once_with(
            "fallback_batch_id",
            {"passed": 18, "failed": 0, "total": 18}
        )
    finally:
        builtins.__import__ = original_import
