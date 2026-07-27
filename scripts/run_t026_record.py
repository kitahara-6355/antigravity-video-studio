"""T-026: E2E結果をJSON記録 + 前回差分確認"""
import sys
import os
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))

from record_e2e_result import record_result, compare_results

# T-025実行結果
result = {
    "workers": {
        "transcribe": "pass",    # ✅ 36seg, GPU, model=small, 17.9s
        "proofread": "pass",     # ✅ 辞書1件+AI28件=29件修正, 36→65行, 40.7s
        "smartcut": "pass",      # ✅ カット不要（目標5分>実尺2.1分）, 0.0s
        "preview": "pass",       # ✅ 7.2MB生成, 5.3s
        "youtube_opt": "pass",   # ✅ AIタイトル5案/タグ18件, 38.7s
        "quality_gate": "fail",  # ❌ スコア81点(safety_mode_B, 閾値90未満)
        "render": "pass",        # ✅ 5.6MB, safe_mode (品質ゲート非通過でのsafe render)
    },
    "notes": "TV-01 tv01_real_clip.mp4 (3.6MB, 31seg→65seg). quality_gate=81(safety mode B, 閾値90). render=safe_mode",
    "session_id": "40193e23-7210-4a95-ab26-79983dbcd1b5",
    "branch_cov": "37%",
    "video": "tv01_real_clip.mp4",
    "pipeline_final_status": "completed",
    "t025_judgment": "PASS (5/7 pass, 判定基準5/7以上を達成)",
}

# 記録
output_dir = str(__import__('pathlib').Path(__file__).parent.parent / "e2e_results")
filepath = record_result(result, output_dir=output_dir, metadata={
    "phase": "Phase1_M1.2_Sprint1.2.3",
    "task": "T-025/T-026",
    "master_ref": "MASTER_v3.6_L417-426",
    "pytest_status": "20/20 PASS (smoke8 + dataflow12)",
})

# 差分比較
print("\n--- 差分比較 ---")
compare_results(filepath, output_dir=output_dir)
print("\n✅ T-026 完了: E2E結果記録と差分確認を実施しました")
