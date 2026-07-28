import os
import shutil
import time
import stat

# 引数名 brain_dir と衝突するので別名で受ける
from path_resolver import brain_dir as _default_brain_dir

def _handle_remove_readonly(func, path, exc):
    """Handler for shutil.rmtree to resolve read-only files on Windows."""
    try:
        os.chmod(path, stat.S_IWRITE)
        # func が os.unlink または os.rmdir の場合のみ実行し、
        # os.chmod などの複数引数を要する関数での TypeError を防ぐ
        if func in (os.unlink, os.rmdir) or getattr(func, "__name__", None) in ("unlink", "rmdir"):
            func(path)
    except OSError:
        pass

def main(brain_dir=None, active_ids=None, keep_days=1):
    if brain_dir is None:
        brain_dir = str(_default_brain_dir())
        
    if not os.path.exists(brain_dir):
        print(f"Directory not found: {brain_dir}")
        return

    default_active_ids = {
        # 現在のメイン会話ID
        "73fb2ff8-094c-4b1a-ae5d-ce40a3bd0e6e",
        "d0b2e390-7ede-4a78-983c-52d572664a7b",
        "a9736a64-a242-485f-942e-bf8476d21fa6",
        # 親および現在のセッションIDを追加して保護
        "77ce0503-24b7-4abc-9d02-632bb3d9f32b",
        "46a116b2-c7c8-40c4-a93a-9acc1c3d5983",
        # 起動したサブエージェントID
        "6be9231e-8896-4078-9e37-d79c2285968a",
        "525bccc5-6a74-477b-9098-8f87497d0c2e",
        "2854d448-8b2c-47de-9b49-dca852e65d93",
        "f9466c48-a62a-46ab-9299-9f30d5eaf5d3",
        "152395e6-0e38-4ab3-a503-8b0addb2aace",
        "a1055a30-0003-45e1-b92a-152a664111c5"
    }

    if active_ids is None:
        active_ids = set(default_active_ids)
    else:
        active_ids = set(active_ids) | default_active_ids

    # 環境変数から現在の会話IDを動的に取得して追加
    env_conv_id = os.environ.get("CONVERSATION_ID")
    if env_conv_id:
        active_ids.add(env_conv_id)

    # 実行中ファイルのパスから親の会話IDを動的に抽出して保護
    try:
        current_file_path = os.path.abspath(__file__)
        parts = current_file_path.split(os.sep)
        if "brain" in parts:
            brain_index = parts.index("brain")
            if brain_index + 1 < len(parts):
                parent_conv_id = parts[brain_index + 1]
                # 簡易的なUUID形式チェック (8-4-4-4-12)
                if (len(parent_conv_id) == 36 and parent_conv_id.count("-") == 4) or parent_conv_id.startswith("dynamic-mock"):
                    active_ids.add(parent_conv_id)
                    print(f"Dynamically protected parent folder from path: {parent_conv_id}")
    except (ValueError, IndexError):
        pass

    now = time.time()
    keep_seconds = keep_days * 24 * 60 * 60

    print("Starting disk cleanup...")
    deleted_count = 0
    failed_count = 0
    freed_size = 0

    for item in os.listdir(brain_dir):
        item_path = os.path.join(brain_dir, item)
        if not os.path.isdir(item_path):
            continue

        # 除外リストに入っているIDは残す
        if item in active_ids:
            print(f"Skipping active folder: {item}")
            continue

        # 直近の更新フォルダは残す
        try:
            mtime = os.path.getmtime(item_path)
            if now - mtime < keep_seconds:
                print(f"Skipping recently modified folder: {item}")
                continue
        except OSError as e:
            print(f"Skipping folder due to error getting mtime: {item} - {e}")
            continue

        # フォルダサイズを概算 (頑健にサイズを計算)
        folder_size = 0
        try:
            for root, dirs, files in os.walk(item_path):
                for file in files:
                    fp = os.path.join(root, file)
                    try:
                        if os.path.exists(fp):
                            folder_size += os.path.getsize(fp)
                    except OSError:
                        pass
        except OSError as e:
            print(f"Warning: error calculating size for {item} - {e}")
            # サイズ計算に失敗しても削除は続行

        # 削除実行
        try:
            import sys
            if sys.version_info >= (3, 12):
                shutil.rmtree(item_path, onexc=_handle_remove_readonly)
            else:
                shutil.rmtree(item_path, onerror=_handle_remove_readonly)
            # 実際にフォルダが消えたかチェックしてカウント
            if not os.path.exists(item_path):
                print(f"Deleted old folder: {item} (approx. {folder_size / (1024*1024):.1f} MB)")
                deleted_count += 1
                freed_size += folder_size
            else:
                print(f"Failed to delete folder (still exists): {item}")
                failed_count += 1
        except PermissionError as e:
            print(f"Permission error deleting: {item} (might be in use) - {e}")
            failed_count += 1
        except OSError as e:
            print(f"Error deleting: {item} - {e}")
            failed_count += 1

    print("--- Cleanup Summary ---")
    print(f"Successfully deleted: {deleted_count} folders")
    print(f"Failed to delete (in use/other error): {failed_count} folders")
    print(f"Estimated space freed: {freed_size / (1024*1024*1024):.2f} GB")

if __name__ == "__main__":
    main()
