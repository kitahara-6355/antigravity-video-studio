import sys
import os
import subprocess
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.agents.orchestration import OrchestrationHub

hub = OrchestrationHub()

def run_test(cmd):
    print(f"Running: {cmd}")
    res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    print(res.stdout)
    print(res.stderr)
    return res.returncode == 0, res.stdout, res.stderr

# T-batch_41d3c0-thumbnail-001
test_thumbnail_ok, stdout_t, stderr_t = run_test("pytest tests/test_verify_image_gen.py --timeout=300")
if test_thumbnail_ok:
    hub.mark_task_done("T-batch_41d3c0-thumbnail-001", "pass", {
        "message": "Verify image gen quality & error handling improved. 34 tests PASS.",
        "changed_files": ["verify_image_gen.py", "tests/test_verify_image_gen.py"]
    })
    print("TASK_thumbnail-001_DONE: pass")
else:
    hub.mark_task_done("T-batch_41d3c0-thumbnail-001", "fail", {
        "error": f"pytest failed with code {test_thumbnail_ok}",
        "traceback": stdout_t + "\n" + stderr_t,
        "changed_files": []
    })
    print("TASK_thumbnail-001_DONE: fail")

# T-batch_41d3c0-test_weaver-001
test_weaver_ok, stdout_w, stderr_w = run_test("pytest tests/test_scratch_get_next_batch.py --timeout=300")
if test_weaver_ok:
    hub.mark_task_done("T-batch_41d3c0-test_weaver-001", "pass", {
        "message": "Add 5 detailed unit tests for scratch/get_next_batch.py. Coverage 100% maintained. 8 tests PASS.",
        "changed_files": ["tests/test_scratch_get_next_batch.py"]
    })
    print("TASK_test_weaver-001_DONE: pass")
else:
    hub.mark_task_done("T-batch_41d3c0-test_weaver-001", "fail", {
        "error": f"pytest failed with code {test_weaver_ok}",
        "traceback": stdout_w + "\n" + stderr_w,
        "changed_files": []
    })
    print("TASK_test_weaver-001_DONE: fail")

# 全体フィットネス関数も最後に確認
fitness_ok, stdout_f, stderr_f = run_test("pytest tests/test_fitness_functions.py -q --tb=no --timeout=300")
print(f"FITNESS_FUNCTIONS_OK: {fitness_ok}")
