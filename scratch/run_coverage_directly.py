import coverage
import os
import sys

# 重複インポートと ValueError を防ぐため、sys.path を backend ディレクトリのみに制限し、親ディレクトリを除去
backend_dir = r"c:\Users\PC_User\Desktop\script\video-automation\backend"
project_root = r"c:\Users\PC_User\Desktop\script\video-automation"
def _norm(p):
    return os.path.normcase(os.path.abspath(p))

sys.path = [p for p in sys.path if _norm(p) not in (_norm(backend_dir), _norm(project_root))]
sys.path.insert(0, backend_dir)

import pydantic.root_model

cov = coverage.Coverage(
    source=["routers/approval_router"],
    branch=True
)
cov.start()

import pytest

print("Starting pytest inside python...")
# pytest.main を実行。--noconftest を指定してハングを防止
exit_code = pytest.main([
    "--noconftest",
    "-p", "no:cov",  # 重複計測を防ぐため pytest-cov は無効化
    "-v",
    r"c:\Users\PC_User\Desktop\script\video-automation\backend\tests\test_approval_router.py"
])

cov.stop()
cov.save()

print("Pytest Exit Code:", exit_code)
print("=== COVERAGE REPORT ===")
cov.report(show_missing=True)
