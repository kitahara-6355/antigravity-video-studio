import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# パスの設定
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..', '..'))
BACKEND_PATH = os.path.join(PROJECT_ROOT, 'backend')
SCRATCH_PATH = os.path.join(PROJECT_ROOT, 'scratch')

# ルートの scratch ディレクトリを sys.path の先頭に追加
if SCRATCH_PATH not in sys.path:
    sys.path.insert(0, SCRATCH_PATH)
if BACKEND_PATH not in sys.path:
    sys.path.insert(0, BACKEND_PATH)

# fix_tdr モジュールを直接インポート
import fix_tdr


class TestFixTdr(unittest.TestCase):
    def test_fix_orchestrator_paths(self):
        # TechnicalDebtStore のダミーエントリを用意
        mock_entry_1 = MagicMock()
        mock_entry_1.file_path = "agents/orchestration/orchestrator.py"
        mock_entry_2 = MagicMock()
        mock_entry_2.file_path = "backend/agents/orchestration/orchestrator.py"
        
        mock_store = MagicMock()
        mock_store.entries = [mock_entry_1, mock_entry_2]
        
        fixed_count = fix_tdr.fix_orchestrator_paths(mock_store)
        
        self.assertEqual(fixed_count, 1)
        self.assertEqual(mock_entry_1.file_path, "agents/orchestration/orchestrator.py")
        self.assertEqual(mock_entry_2.file_path, "agents/orchestration/orchestrator.py")

    def test_find_except_exception_lines(self):
        # 一時ファイルを作成して except Exception 行をテスト
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write("try:\n    pass\nexcept Exception as e:\n    pass\ntry:\n    pass\nexcept  Exception:\n    pass\n")
            temp_path = f.name
        
        try:
            except_lines = fix_tdr.find_except_exception_lines(temp_path)
            self.assertEqual(except_lines, [3, 7])
        finally:
            os.remove(temp_path)

    def test_find_except_exception_lines_nonexistent_file(self):
        # 存在しないファイルの場合は空リストを返すことを確認
        except_lines = fix_tdr.find_except_exception_lines("nonexistent_file.py")
        self.assertEqual(except_lines, [])

    def test_register_graph_debts(self):
        mock_store = MagicMock()
        fix_tdr.register_graph_debts(mock_store, [10, 20])
        
        self.assertEqual(mock_store.register_debt.call_count, 2)
        mock_store.register_debt.assert_any_call(
            category="MINOR_INFRA",
            file_path="agents/graph.py",
            line_number=10,
            pattern="except Exception (broad catch)",
            cause_pattern="DP-01",
            fix_pattern="具体的例外クラスに限定",
            registered_by="opus_session_p26",
            notes="Flash batch_783b64/ae705b で追加。防御的例外ハンドリング。",
            tags=["flash_batch", "p26"],
        )

    @patch('fix_tdr.TechnicalDebtStore')
    @patch('fix_tdr.fix_orchestrator_paths')
    @patch('fix_tdr.find_except_exception_lines')
    @patch('fix_tdr.register_graph_debts')
    def test_main(self, mock_register, mock_find, mock_fix, mock_store_class):
        mock_store = MagicMock()
        mock_store_class.return_value = mock_store
        mock_find.return_value = [15, 30]
        
        fix_tdr.main()
        
        mock_store_class.assert_called_once()
        mock_fix.assert_called_once_with(mock_store)
        mock_find.assert_called_once()
        mock_register.assert_called_once_with(mock_store, [15, 30])
        mock_store._save.assert_called_once()

    @patch('agents.memory.technical_debt.TechnicalDebtStore')
    def test_script_execution(self, mock_store_class):
        import runpy
        mock_store = MagicMock()
        mock_store_class.return_value = mock_store
        
        with patch('sys.stdout'):
            runpy.run_path(os.path.join(SCRATCH_PATH, 'fix_tdr.py'), run_name='__main__')
            
        mock_store_class.assert_called_once()
        mock_store._save.assert_called_once()

