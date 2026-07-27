"""
M2.5: director_engine.py の model_registry インポートエラー時のフォールバック検証テスト
"""

import sys
from unittest.mock import patch

def test_get_model_fallback():
    # model_registry を除外してインポートエラーをシミュレート
    with patch.dict(sys.modules, {'model_registry': None}):
        if 'director_engine' in sys.modules:
            del sys.modules['director_engine']
            
        import director_engine
        
        # フォールバック処理で "gemini-2.5-flash" が返ることを確認
        assert director_engine.get_model("director") == "gemini-2.5-flash"

    # テスト後にインポート状態をクリーンアップ
    if 'director_engine' in sys.modules:
        del sys.modules['director_engine']
