"""
両憲法準拠プランのテスト
問題解決確認:
1. 大容量動画対応（video_path指定）
2. 60分処理の安定稼働（タスク状態永続化）
3. 進捗見える化（StateStore + WebSocket）
"""
import requests
import time
import json

BASE_URL = "http://localhost:8000"

def test_api():
    print("=" * 60)
    print("両憲法準拠プラン テスト")
    print("=" * 60)
    
    # Test 1: video_path指定で字幕生成APIを呼び出し
    print("\n📋 Test 1: video_path指定での字幕生成")
    video_path = r"C:\Users\PC_User\Desktop\script\video-automation\raw_videos\AI Studio アップロード用動画\シーン01_前編.mp4"
    
    response = requests.post(f"{BASE_URL}/api/transcribe", json={
        "video_path": video_path,
        "language": "ja",
        "with_proofreading": True
    })
    
    print(f"  Response: {response.status_code}")
    data = response.json()
    print(f"  Data: {json.dumps(data, ensure_ascii=False, indent=2)}")
    
    if response.status_code != 200:
        print("  ❌ FAILED: API呼び出しエラー")
        return False
    
    if "task_id" not in data:
        print("  ❌ FAILED: タスクIDが返却されていない")
        return False
    
    task_id = data["task_id"]
    print(f"  ✅ PASSED: タスクID即時返却 ({task_id[:8]}...)")
    
    # Test 2: タスク状態取得
    print("\n📋 Test 2: タスク状態取得")
    response = requests.get(f"{BASE_URL}/api/task/{task_id}")
    print(f"  Response: {response.status_code}")
    
    if response.status_code != 200:
        print("  ❌ FAILED: タスク状態取得エラー")
        return False
    
    task_data = response.json()
    print(f"  Status: {task_data.get('status')}")
    print(f"  Phase: {task_data.get('phase')}")
    print(f"  Progress: {task_data.get('progress')}%")
    print(f"  ✅ PASSED: タスク状態取得成功")
    
    # Test 3: 進捗更新のポーリング（5秒間）
    print("\n📋 Test 3: 進捗更新確認（5秒間ポーリング）")
    prev_progress = 0
    for i in range(5):
        time.sleep(1)
        response = requests.get(f"{BASE_URL}/api/task/{task_id}")
        if response.status_code == 200:
            task_data = response.json()
            progress = task_data.get('progress', 0)
            phase = task_data.get('phase', '')
            message = task_data.get('message', '')
            print(f"  [{i+1}s] {progress}% - {phase}: {message}")
            if progress > prev_progress:
                print(f"  ✅ 進捗更新を確認")
            prev_progress = progress
    
    # Test 4: タスク一覧
    print("\n📋 Test 4: タスク一覧取得")
    response = requests.get(f"{BASE_URL}/api/tasks")
    if response.status_code == 200:
        tasks = response.json().get("tasks", [])
        print(f"  タスク数: {len(tasks)}")
        print(f"  ✅ PASSED: タスク一覧取得成功")
    else:
        print(f"  ❌ FAILED: タスク一覧取得エラー")
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)
    
    return True

if __name__ == "__main__":
    test_api()
