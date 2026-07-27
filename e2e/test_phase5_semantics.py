import asyncio
import os
import sys
from pathlib import Path
from pprint import pprint

# プロジェクトルートのbackendをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

# genai.Client の初期化エラーを防ぐためダミーキーをセット
os.environ["GOOGLE_API_KEY"] = "dummy_for_stub"

from asset_library import asset_library
from services.vector_search import vector_search_engine

def test_vector_search():
    print("=== [テスト 1] STUB モードでの Embeddings ===")
    text1 = "プロフェッショナルな人物写真"
    text2 = "明るいロゴ"

    # APIキーが指定されていないのでSTUBモードの警告が出るはずです
    vec1 = vector_search_engine._get_embedding(text1)
    vec2 = vector_search_engine._get_embedding(text2)
    
    print(f"'{text1}' のベクトル次元: {len(vec1)}")
    print(f"'{text2}' のベクトル次元: {len(vec2)}")
    
    # 全く同じテキストのベクトルは同一であるか？
    vec1_again = vector_search_engine._get_embedding(text1)
    assert vec1 == vec1_again, "同じテキストに対するSTUBベクトルは不一致になってはいけません"

    print("\n=== [テスト 2] asset_library.build_search_index() ===")
    asset_library.assets.clear()
    
    # モックのアセットを追加
    from asset_library import AssetEntry
    asset_library.assets = [
        AssetEntry(id="a001", path="p1.jpg", filename="p1", type="photo", category="channel_owner", labels=["人物", "プロフェッショナル"], mood="professional", usage_for=["thumbnail"]),
        AssetEntry(id="a002", path="p2.png", filename="p2", type="logo", category="brand", labels=["ロゴ"], mood="energetic", usage_for=["opening"]),
        AssetEntry(id="a003", path="v1.mp4", filename="v1", type="video", category="channel_owner", labels=["料理"], mood="warm", usage_for=["insert"])
    ]
    
    print("アセットの内容:")
    for a in asset_library.assets:
        print(f"  - {a.id}: {asset_library.tag_for_search(a)}")
    
    vector_search_engine._index.clear()
    
    result = asset_library.build_search_index()
    print("インデックス構築結果:")
    pprint(result)
    
    print("\n=== [テスト 3] asset_library.search_assets() ===")
    query = "プロフェッショナルの人物" # text1に近いSTUBと仮定するが、今回は文字コード和なので偶然に近いものを返す
    print(f"検索クエリ: '{query}'")
    search_results = asset_library.search_assets(query, top_k=2)
    print("検索結果:")
    for r in search_results:
         print(f"  - [{r['id']}] スコア: {r.get('search_score', 0)}")
         
    print("\n[OK] Core Module Test Passed.")
    
if __name__ == "__main__":
    test_vector_search()
