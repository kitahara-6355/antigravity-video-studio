"""
test_scratch_3tier_fallback_verify.py
"""

import sys
from pathlib import Path

# _test_3tier_fallback.py の 15行目 (sys.path.insert) をカバーするため、
# インポート前に sys.path から BACKEND_DIR を一時的に削除します。
BACKEND_DIR = Path(__file__).parent.parent
ROOT_DIR = BACKEND_DIR.parent

if str(BACKEND_DIR) in sys.path:
    sys.path.remove(str(BACKEND_DIR))

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import backend.tests._test_3tier_fallback as fallback_test

def test_execute_all_fallback_tests():
    test_functions = [
        getattr(fallback_test, name)
        for name in dir(fallback_test)
        if name.startswith("test_") and callable(getattr(fallback_test, name))
    ]
    test_functions.sort(key=lambda f: f.__code__.co_firstlineno)
    assert len(test_functions) > 0
    for test_func in test_functions:
        test_func()
