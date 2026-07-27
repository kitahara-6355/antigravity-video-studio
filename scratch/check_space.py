import os
from pathlib import Path

base_dir = Path("C:/Users/PC_User/.gemini/antigravity/brain")
if not base_dir.exists():
    print(f"Directory {base_dir} does not exist.")
    sys.exit(1)

dirs_with_sizes = []
for p in base_dir.iterdir():
    if p.is_dir():
        try:
            total_size = sum(f.stat().st_size for f in p.glob("**/*") if f.is_file())
            dirs_with_sizes.append((p.name, total_size))
        except Exception as e:
            dirs_with_sizes.append((p.name, -1))

dirs_with_sizes.sort(key=lambda x: x[1], reverse=True)
print("Top directories by size in brain folder:")
for name, size in dirs_with_sizes[:20]:
    if size == -1:
        print(f"  {name}: Could not compute size (Permission/Error)")
    else:
        print(f"  {name}: {size / (1024**3):.2f} GB ({size / (1024**2):.2f} MB)")
