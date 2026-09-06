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
        # **直書きの既定値に逃げない**（R1.5-C6）。2026-08-28 まで
        # gemini-2.5-flash を直書きしており、2026-10-16 に提供終了する
        # **この経路が返すのは工程別のモデルではなく既定モデル**
        from model_policy import default_model
        assert director_engine.get_model("director") == default_model()
        assert not director_engine.get_model("director").startswith("gemini-2.5")

    # テスト後にインポート状態をクリーンアップ
    if 'director_engine' in sys.modules:
        del sys.modules['director_engine']
