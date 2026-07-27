import hashlib
import os

def get_sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

path1 = r"C:\Users\PC_User\Desktop\script\video-automation\vault-assets\raw_videos\本番RAW01 対談_山田\シーン01_前編.mp4"
path2 = r"C:\Users\PC_User\Desktop\script\video-automation\backend\temp\final_build\scene01_trimmed.mp4"

print(f"File 1 size: {os.path.getsize(path1)}")
print(f"File 2 size: {os.path.getsize(path2)}")

print("Calculating hash for File 1...")
hash1 = get_sha256(path1)
print(f"File 1 hash: {hash1}")

print("Calculating hash for File 2...")
hash2 = get_sha256(path2)
print(f"File 2 hash: {hash2}")

if hash1 == hash2:
    print("SUCCESS: Files are identical!")
else:
    print("WARNING: Files differ!")
