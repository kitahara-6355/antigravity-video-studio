import os
from pathlib import Path

target = Path(r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田")
if target.exists():
    print(f"Directory {target.name} exists. Listing files:")
    for item in target.iterdir():
        print(f" - {item.name}")
else:
    # Let's search for similar directories
    print("Directory not found. Listing parent contents:")
    parent = target.parent
    for item in parent.iterdir():
        print(f" - {item.name}")
