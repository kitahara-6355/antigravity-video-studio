import os
import shutil

DEFAULT_E2E_DIR = os.environ.get(
    "ANTIGRAVITY_E2E_DIR",
    r"c:\Users\PC_User\Desktop\script\video-automation\backend\tests\e2e"
)

MAPPING = {
    "test_e2e_02_transcription.py": "test_e2e_m36_o2_transcription.py",
    "test_e2e_03_proofreading.py": "test_e2e_m36_o3_proofreading.py",
    "test_e2e_11_preproduction.py": "test_e2e_m36_o11_preproduction_lab.py",
    "test_e2e_a4_quality.py": "test_e2e_m36_a4_quality_assurance.py",
    "test_e2e_a5_incident.py": "test_e2e_m36_a5_incident.py",
    "test_e2e_a6_integration.py": "test_e2e_m36_a6_integration.py",
    "test_e2e_a7_channel.py": "test_e2e_m36_a7_channel_management.py"
}

def migrate(e2e_dir: str) -> None:
    for src_name, dest_name in MAPPING.items():
        src_path = os.path.join(e2e_dir, src_name)
        dest_path = os.path.join(e2e_dir, dest_name)
        
        if os.path.exists(src_path):
            print(f"Migrating {src_name} -> {dest_name}")
            try:
                # UTF-8 で読み込んで UTF-8 で書き出す
                with open(src_path, "r", encoding="utf-8") as f_src:
                    content = f_src.read()
                    
                with open(dest_path, "w", encoding="utf-8") as f_dest:
                    f_dest.write(content)
                    
                print(f"Successfully copied to {dest_name}")
            except Exception as e:
                print(f"Error migrating {src_name} -> {dest_name}: {e}")
        else:
            print(f"Warning: {src_name} does not exist!")

    print("Migration copy completed.")

if __name__ == "__main__":
    migrate(DEFAULT_E2E_DIR)
