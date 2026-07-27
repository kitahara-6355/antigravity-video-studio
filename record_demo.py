"""
OBS Automated Demo Recording Script
Phase 28 デモ動画の完全自動録画

Requirements:
- OBS Studio 28.0+ (WebSocket内蔵)
- obsws-python
- playwright
"""

import time
import sys
from pathlib import Path

try:
    import obsws_python as obs
    from playwright.sync_api import sync_playwright
except ImportError as e:
    print(f"❌ 必要なパッケージがインストールされていません: {e}")
    print("インストールコマンド: pip install obsws-python playwright")
    print("Playwright初期化: playwright install chromium")
    sys.exit(1)

# 設定
OBS_HOST = 'localhost'
OBS_PORT = 4455
OBS_PASSWORD = ''  # OBS WebSocket設定で確認
OUTPUT_DIR = Path("demos")
OUTPUT_DIR.mkdir(exist_ok=True)

def setup_obs_scene(client):
    """OBS シーンのセットアップ"""
    print("🎬 OBS シーンを設定中...")
    
    # シーン作成（存在しない場合）
    try:
        client.create_scene("Phase28Demo")
    except:
        pass  # 既に存在する場合
    
    # ブラウザソースを追加（画面キャプチャの代わり）
    try:
        client.create_input(
            sceneName="Phase28Demo",
            inputName="BrowserCapture",
            inputKind="monitor_capture",  # ディスプレイキャプチャ
            inputSettings={}
        )
    except:
        pass
    
    # シーンを切り替え
    client.set_current_program_scene("Phase28Demo")
    print("✅ シーン設定完了")

def record_demo():
    """メイン録画処理"""
    print("=" * 60)
    print("Phase 28 デモ動画 自動録画")
    print("=" * 60)
    
    # OBS接続
    print("\n1️⃣ OBS Studio に接続中...")
    try:
        client = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD)
        print("✅ OBS接続成功")
    except Exception as e:
        print(f"❌ OBS接続失敗: {e}")
        print("\n解決方法:")
        print("1. OBS Studio を起動してください")
        print("2. ツール → WebSocketサーバー設定 を開く")
        print("3. 'WebSocketサーバーを有効にする' にチェック")
        print(f"4. サーバーポート: {OBS_PORT}")
        print("5. パスワードを設定した場合、スクリプトのOBS_PASSWORDを更新")
        return False
    
    # シーンセットアップ
    setup_obs_scene(client)
    
    # Playwright起動
    print("\n2️⃣ ブラウザを起動中...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--start-maximized']
        )
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            record_video_dir=str(OUTPUT_DIR)  # バックアップ録画
        )
        page = context.new_page()
        
        # 録画開始
        print("\n3️⃣ 録画開始...")
        output_path = OUTPUT_DIR / f"phase28_demo_{int(time.time())}.mp4"
        try:
            client.start_record()
            print(f"🔴 録画中: {output_path}")
        except Exception as e:
            print(f"⚠️ OBS録画開始エラー（続行します）: {e}")
        
        time.sleep(2)  # 録画安定化
        
        try:
            # デモ実演
            print("\n4️⃣ デモを実演中...")
            
            # ステップ1: ページ遷移
            print("   📍 Phase 28 テストページを開く...")
            page.goto('http://localhost:3000/phase28-test', wait_until='networkidle')
            time.sleep(3)
            
            # ステップ2: プリセット選択
            print("   🎨 Vibrant プリセットを選択...")
            page.click('button:has-text("vibrant")', timeout=5000)
            time.sleep(2)
            
            # ステップ3: プレビュー生成
            print("   ⚙️ Generate Preview をクリック...")
            page.click('button:has-text("Generate Preview")', timeout=5000)
            time.sleep(2)
            
            # ステップ4: 生成完了を待つ
            print("   ⏳ プレビュー生成を待機中（最大30秒）...")
            page.wait_for_selector('video', timeout=30000)
            time.sleep(3)
            
            # ステップ5: 動画再生
            print("   ▶️ 動画を再生...")
            page.click('video')  # 再生ボタンをクリック
            time.sleep(7)  # 字幕が2つ表示されるまで待つ
            
            # ステップ6: 一時停止
            print("   ⏸️ 一時停止...")
            page.click('video')
            time.sleep(2)
            
            print("\n✅ デモ実演完了")
            
        except Exception as e:
            print(f"\n❌ デモ実演エラー: {e}")
            print("スクリーンショットを保存...")
            page.screenshot(path=str(OUTPUT_DIR / "error_screenshot.png"))
        
        finally:
            # 録画停止
            print("\n5️⃣ 録画停止...")
            time.sleep(1)
            try:
                client.stop_record()
                print("⏹️ 録画停止完了")
            except Exception as e:
                print(f"⚠️ 録画停止エラー: {e}")
            
            # ブラウザ終了
            time.sleep(2)
            browser.close()
    
    # 録画ファイル情報取得
    print("\n6️⃣ 録画ファイルを確認中...")
    try:
        status = client.get_record_status()
        if hasattr(status, 'output_path'):
            actual_path = status.output_path
            print(f"✅ 録画完了: {actual_path}")
        else:
            print(f"✅ 録画完了（パス不明、OBS設定を確認してください）")
    except:
        print("✅ 録画完了（ファイルパスは OBS 設定の出力先を確認）")
    
    print("\n" + "=" * 60)
    print("🎉 自動録画が完了しました！")
    print("=" * 60)
    return True

if __name__ == "__main__":
    success = record_demo()
    sys.exit(0 if success else 1)
