"""
AI機能実動作テスト
google-genai SDK + .env からAPIキー読み込み
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv

# .envからAPIキーを読み込み
env_path = Path(__file__).parent / "backend" / ".env"
load_dotenv(env_path)

print(f"API Key loaded: {'Yes' if os.getenv('GOOGLE_API_KEY') else 'No'}")

# テスト用字幕データ
TEST_SRT_CONTENT = """
1
00:00:00,000 --> 00:00:04,000
こんにちは、初夏の北原美麗です。

2
00:00:04,000 --> 00:00:12,000
本日は、書道家の久北博之先生にお越しいただきました。

3
00:00:12,000 --> 00:00:20,000
先生は株式会社、角シアター代表、久北デザイン書道局主催、
そして一般社団法人、日本デザイン書道作家協会の理事長でいらっしゃいまして、
"""


def test_ai():
    """AI機能テスト"""
    print("=" * 60)
    print("AI機能実動作テスト（google-genai SDK）")
    print("=" * 60)
    
    from google import genai
    
    # APIキーで初期化
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY が設定されていません")
        return
    
    client = genai.Client(api_key=api_key)
    
    # Phase 4: AI字幕確認テスト
    print("\n📋 Phase 4: AI字幕確認テスト")
    print("-" * 40)
    
    prompt = f"""
以下の字幕から、確認が必要な箇所（固有名詞、専門用語等）を特定してください。

## 字幕
{TEST_SRT_CONTENT}

## 出力（JSON形式）
```json
[{{"timestamp": "00:01:30", "original_text": "テキスト", "concern": "理由", "category": "proper_noun", "suggestion": "修正案"}}]
```
"""
    
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt
        )
        
        print(f"✅ AI応答受信: {len(response.text)} chars")
        
        # JSONをパース
        text = response.text
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            json_str = text[start:end].strip()
            items = json.loads(json_str)
            print(f"✅ 検出された確認項目: {len(items)} 件")
            
            for i, item in enumerate(items[:3], 1):
                print(f"  [{i}] {item.get('timestamp', 'N/A')}: {item.get('original_text', '')[:20]}...")
                print(f"      懸念: {item.get('concern', '')}")
        
    except Exception as e:
        print(f"❌ エラー: {type(e).__name__}: {e}")
    
    # Phase 5: テロップ提案テスト
    print("\n📋 Phase 5: テロップ提案テスト")
    print("-" * 40)
    
    prompt2 = f"""
以下の字幕から、テロップ表示に適した箇所を抽出してください。

## 字幕
{TEST_SRT_CONTENT}

## 出力（JSON形式）
```json
[{{"timestamp": "00:00:30", "text": "テロップ文字", "reason": "理由"}}]
```
"""
    
    try:
        response2 = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt2
        )
        
        print(f"✅ AI応答受信: {len(response2.text)} chars")
        
        text2 = response2.text
        if "```json" in text2:
            start = text2.find("```json") + 7
            end = text2.find("```", start)
            json_str = text2[start:end].strip()
            suggestions = json.loads(json_str)
            print(f"✅ 提案されたテロップ: {len(suggestions)} 件")
            
            for i, s in enumerate(suggestions[:3], 1):
                print(f"  [{i}] {s.get('timestamp', 'N/A')}: {s.get('text', '')}")
        
    except Exception as e:
        print(f"❌ エラー: {type(e).__name__}: {e}")
    
    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)


if __name__ == "__main__":
    test_ai()
