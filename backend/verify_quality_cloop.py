import json
import re
import sys
from pathlib import Path

def parse_srt(srt_path):
    """
    SRT字幕ファイルをパースし、テキストセグメントのリストを返す。
    """
    srt_file = Path(srt_path)
    if not srt_file.exists():
        raise FileNotFoundError(f"SRTファイルが見つかりません: {srt_file}")
        
    try:
        with open(srt_file, 'r', encoding='utf-8-sig') as f:
            content = f.read().replace('\r\n', '\n')
    except UnicodeDecodeError as e:
        raise ValueError(f"SRTファイルのエンコーディングが正しくありません。UTF-8で保存してください: {e}")
    except OSError as e:
        raise OSError(f"SRTファイルの読み込みに失敗しました: {e}")
    
    segments = []
    # 連続する改行による空ブロックを防ぐため、トリムと正規表現での分割を行う
    blocks = re.split(r'\n{2,}', content.strip())
    for block in blocks:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) >= 3:
            # 3行目以降がテキスト（複数行に渡る場合を考慮して結合）
            text = " ".join(lines[2:])
            # 話者名の除去 (例: "北原：", "久喜田：" 等。数字以外の文字の後に全角コロンが続く場合)
            text = re.sub(r'^[^\d：]+：', '', text)
            segments.append(text)
    return segments

def compare_results(json_path, srt_path):
    """
    JSONセグメントとSRTセグメントを比較し、指定のキーワードが含まれるか検証する。
    """
    json_file = Path(json_path)
    if not json_file.exists():
        raise FileNotFoundError(f"JSONファイルが見つかりません: {json_file}")

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
    except UnicodeDecodeError as e:
        raise ValueError(f"JSONファイルのエンコーディングが正しくありません。UTF-8で保存してください: {e}")
    except json.JSONDecodeError as e:
        raise ValueError(f"JSONのデコードに失敗しました: {e}")
    except OSError as e:
        raise OSError(f"JSONファイルの読み込みに失敗しました: {e}")

    if not isinstance(json_data, list):
        raise ValueError("JSONデータのルートはリスト形式である必要があります")
    
    srt_texts = parse_srt(srt_path)
    
    print("--- 比較結果（抜粋） ---")
    print(f"JSONセグメント数: {len(json_data)}")
    print(f"SRTセグメント数: {len(srt_texts)}")
    print("-" * 30)
    
    # 10秒テスト失敗から派生したキーワードのチェック
    targets = ["書家の", "書を通して", "久喜田"]
    
    for i, item in enumerate(json_data[:20]): # 最初の20ノードをチェック
        if not isinstance(item, dict):
            continue
        text = item.get('text', '')
        if not isinstance(text, str):
            text = ''
        print(f"[{i}] {text}")
        for t in targets:
            if t in text:
                print(f"  -> FOUND KEYWORD: {t} (SUCCESS)")
    
    print("-" * 30)
    print("検証完了")

def main():
    """
    メインの実行関数。コマンドライン引数を解析し、JSONとSRTの比較検証を実行する。
    """
    if len(sys.argv) < 3:
        print("使用法: python verify_quality_cloop.py <json_path> <srt_path>", file=sys.stderr)
        sys.exit(1)
        
    try:
        compare_results(sys.argv[1], sys.argv[2])
    except (FileNotFoundError, ValueError, OSError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)
    except (TypeError, KeyError, IndexError, AttributeError) as e:
        print(f"予期しないエラー: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
