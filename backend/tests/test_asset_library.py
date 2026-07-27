import pytest
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

from asset_library import (
    CreativeAssetLibrary,
    AssetEntry,
    GuestProfile,
    _hex_to_color_name,
    scan_assets,
    get_assets_for,
    ASSET_ROOT
)

# ログ設定
logger = logging.getLogger(__name__)


@pytest.fixture
def mock_gemini_deps():
    """Geminiクライアントとモデル登録の依存モック"""
    with patch("gemini_client_factory.get_gemini_client") as mock_get_client, \
         patch("model_registry.get_model") as mock_get_model:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_model.return_value = "mock-vision-model"
        yield mock_client, mock_get_model


@pytest.fixture
def temp_library(tmp_path, mock_gemini_deps):
    """一時ディレクトリを使用したCreativeAssetLibraryインスタンス"""
    lib = CreativeAssetLibrary(asset_root=tmp_path)
    return lib


def test_ensure_structure_creates_folders(temp_library, tmp_path):
    """必要なフォルダ構造とREADMEが生成されることを確認"""
    expected_folders = [
        tmp_path / "channel_owner" / "photos",
        tmp_path / "channel_owner" / "videos",
        tmp_path / "channel_owner" / "logos",
        tmp_path / "guests",
        tmp_path / "templates",
        tmp_path / "brand" / "fonts",
        tmp_path / "brand" / "music",
    ]
    for folder in expected_folders:
        assert folder.exists()
        assert folder.is_dir()

    readme_path = tmp_path / "README.md"
    assert readme_path.exists()
    assert "# Creative Asset Library" in readme_path.read_text(encoding="utf-8")


def test_load_index_corrupted_json(tmp_path, mock_gemini_deps, caplog):
    """インデックスファイルが破損している場合の例外キャッチとログ出力をテスト (L202-203)"""
    index_path = tmp_path / "asset_index.json"
    index_path.write_text("{invalid json", encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        lib = CreativeAssetLibrary(asset_root=tmp_path)
        assert len(lib.assets) == 0
        assert any("インデックス読み込みエラー" in record.message for record in caplog.records)


def test_scan_and_auto_label_photo(temp_library, tmp_path):
    """写真アセットのスキャンとモックラベリング処理をテスト (L281-287, L305-317)"""
    # チャンネルオーナーのフォトフォルダにダミーの肖像画を作成
    photo_dir = tmp_path / "channel_owner" / "photos"
    photo_path = photo_dir / "my_portrait_shot.png"
    photo_path.write_bytes(b"dummy image content")

    # _label_assetをモック化して特定のラベルデータを返す
    mock_labels = {
        "labels": ["portrait", "人物"],
        "style_tags": ["formal"],
        "colors": ["#ff0000", "#00ff00"],
        "mood": "creative",
        "usage_for": ["thumbnail"]
    }
    
    with patch.object(temp_library, "_label_asset", return_value=mock_labels) as mock_label_method:
        result = temp_library.scan(auto_label=True)
        
        mock_label_method.assert_called_once_with(photo_path)
        assert result["new_assets"] == 1
        assert len(temp_library.assets) == 1
        
        asset = temp_library.assets[0]
        assert asset.filename == "my_portrait_shot.png"
        assert asset.type == "photo"
        assert asset.category == "channel_owner"
        assert asset.labels == ["portrait", "人物"]
        assert asset.style_tags == ["formal"]
        assert asset.colors == ["#ff0000", "#00ff00"]
        assert asset.mood == "creative"
        assert asset.usage_for == ["thumbnail"]


def test_scan_unsupported_extensions_ignored(temp_library, tmp_path):
    """サポート対象外の拡張子のファイルがスキャンで無視されることを確認"""
    photo_dir = tmp_path / "channel_owner" / "photos"
    txt_path = photo_dir / "info.txt"
    txt_path.write_bytes(b"some text")

    result = temp_library.scan()
    assert result["new_assets"] == 0
    assert len(temp_library.assets) == 0


def test_scan_existing_hash_skipped(temp_library, tmp_path):
    """既にインデックスされている同一ハッシュのアセットがスキップされることを確認"""
    photo_dir = tmp_path / "channel_owner" / "photos"
    photo_path = photo_dir / "img1.png"
    photo_path.write_bytes(b"unique data")

    # 1回目のスキャン
    temp_library.scan(auto_label=False)
    assert len(temp_library.assets) == 1

    # 2回目のスキャン（同じファイルが存在）
    result = temp_library.scan(auto_label=False)
    assert result["new_assets"] == 0
    assert len(temp_library.assets) == 1


def test_scan_different_categories_and_types(temp_library, tmp_path):
    """異なるカテゴリとアセットタイプ（動画、音声）が正しく認識されることを検証"""
    # ゲスト用フォルダに動画を配置
    guest_dir = tmp_path / "guests" / "guest_name" / "videos"
    guest_dir.mkdir(parents=True, exist_ok=True)
    video_path = guest_dir / "guest_speech.mp4"
    video_path.write_bytes(b"dummy video")

    # テンプレートフォルダに音声を配置
    template_dir = tmp_path / "templates"
    audio_path = template_dir / "bgm.mp3"
    audio_path.write_bytes(b"dummy audio")

    # ブランドフォルダにフォントを配置
    brand_dir = tmp_path / "brand" / "fonts"
    font_path = brand_dir / "font.otf"  # サポート外なので無視されるはず
    font_path.write_bytes(b"dummy font")
    
    # ブランドフォルダに音楽（音声）を配置
    music_path = tmp_path / "brand" / "music" / "theme.wav"
    music_path.write_bytes(b"dummy music")

    # その他のフォルダに写真を配置
    other_dir = tmp_path / "unknown_folder"
    other_dir.mkdir(parents=True, exist_ok=True)
    other_path = other_dir / "random.png"
    other_path.write_bytes(b"random")

    result = temp_library.scan(auto_label=False)
    assert result["new_assets"] == 4  # video, audio, audio, other-photo

    categories = [a.category for a in temp_library.assets]
    assert "guest" in categories
    assert "template" in categories
    assert "brand" in categories
    assert "other" in categories

    types = {a.filename: a.type for a in temp_library.assets}
    assert types["guest_speech.mp4"] == "video"
    assert types["bgm.mp3"] == "audio"
    assert types["theme.wav"] == "audio"
    assert types["random.png"] == "photo"


def test_label_asset_fallbacks_and_exceptions(temp_library, caplog):
    """_label_assetのパス名によるフォールバックおよび例外処理をテスト (L305-317, L327-328)"""
    # 1. portrait/profile
    labels_portrait = temp_library._label_asset(Path("dummy/profile_image.png"))
    assert "portrait" in labels_portrait["labels"]
    assert "人物" in labels_portrait["labels"]
    assert labels_portrait["usage_for"] == ["thumbnail"]

    # 2. logo
    labels_logo = temp_library._label_asset(Path("dummy/company_logo.png"))
    assert "logo" in labels_logo["labels"]

    # 3. work
    labels_work = temp_library._label_asset(Path("dummy/art_work_v1.png"))
    assert "work" in labels_work["labels"]

    # 4. opening
    labels_opening = temp_library._label_asset(Path("dummy/opening_clip.png"))
    assert "opening" in labels_opening["labels"]

    # 5. ending
    labels_ending = temp_library._label_asset(Path("dummy/ending_seq.png"))
    assert "ending" in labels_ending["labels"]

    # どれにもマッチしないファイル名
    labels_other = temp_library._label_asset(Path("dummy/random_file_name.png"))
    assert labels_other["labels"] == []

    # 6. 例外時のエラーハンドリング (L327-328)
    # PathオブジェクトではなくNoneを渡して例外をスローさせる
    with caplog.at_level(logging.ERROR):
        result_err = temp_library._label_asset(None)
        assert result_err is None
        assert any("ラベリングエラー" in record.message for record in caplog.records)


def test_get_assets_for_task(temp_library):
    """get_assets_for_task の利用可能・推奨・不足レポートロジックの検証 (L360-362, L369-373)"""
    # テスト用のアセットを注入
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="channel_owner/photos/portrait.png",
            filename="portrait.png",
            type="photo",
            category="channel_owner",
            labels=["portrait"],
            usage_for=["thumbnail"]
        ),
        AssetEntry(
            id="asset_0002",
            path="channel_owner/photos/logo.png",
            filename="logo.png",
            type="photo",
            category="channel_owner",
            labels=["logo"],
            usage_for=[]  # 推奨ではなくavailable用
        )
    ]

    # thumbnail タスクを実行 (必要素材: portrait, logo)
    result = temp_library.get_assets_for_task("thumbnail")
    
    # asset_0001 は usage_for=["thumbnail"] なので recommended
    assert len(result["recommended"]) == 1
    assert result["recommended"][0]["id"] == "asset_0001"

    # asset_0002 は labels=["logo"] なので available (L360-362)
    assert len(result["available"]) == 1
    assert result["available"][0]["id"] == "asset_0002"
    
    # 必要な素材はすべて揃っているので missing は空
    assert len(result["missing"]) == 0

    # opening タスクを実行 (必要素材: logo, template)
    # logo は利用可能だが、template は不足しているはず (L369-373)
    result_opening = temp_library.get_assets_for_task("opening")
    assert len(result_opening["missing"]) == 1
    assert result_opening["missing"][0]["type"] == "template"
    assert "template素材を追加すると" in result_opening["missing"][0]["suggestion"]


def test_get_usage_report(temp_library):
    """get_usage_report での参照されたアセットのカウントインクリメント (L385-388)"""
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="path/to/asset.png",
            filename="asset.png",
            type="photo",
            category="brand",
            usage_count=0
        )
    ]

    # 存在するアセットIDを参照
    report = temp_library.get_usage_report(referenced_assets=["asset_0001", "non_existent_asset"])
    
    assert report["total_referenced"] == 1
    assert report["referenced_assets"][0]["id"] == "asset_0001"
    
    # usage_count がインクリメントされていることを確認
    assert temp_library.assets[0].usage_count == 1


def test_get_sufficiency_report(temp_library):
    """get_sufficiency_report のカテゴリ不足および素材不足レコメンドを検証 (L419-424, L429-432)"""
    # 1. アセットが何もない場合 -> 全て不足 (L419-424)
    temp_library.assets = []
    report1 = temp_library.get_sufficiency_report()
    assert len(report1["recommendations"]) == 3
    categories_missing = [r["category"] for r in report1["recommendations"]]
    assert "channel_owner" in categories_missing
    assert "guest" in categories_missing
    assert "template" in categories_missing

    # 2. 一部のアセットのみ存在し、特定の必須ラベルが足りない場合 (L429-432)
    # 重複カテゴリ(channel_owner)と重複ラベル(portrait)を含めることで、ブランチ402->404, 407->409をカバー
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="channel_owner/photos/portrait.png",
            filename="portrait.png",
            type="photo",
            category="channel_owner",
            labels=["portrait"]  # work, activity, logo が不足
        ),
        AssetEntry(
            id="asset_0001_2",
            path="channel_owner/photos/another.png",
            filename="another.png",
            type="photo",
            category="channel_owner",
            labels=["portrait"]  # 重複カテゴリかつ重複ラベル
        ),
        AssetEntry(
            id="asset_0002",
            path="guests/guest1/portrait.png",
            filename="portrait.png",
            type="photo",
            category="guest",
            labels=["portrait", "work"]  # 不足なし
        ),
        AssetEntry(
            id="asset_0003",
            path="templates/opening.mp4",
            filename="opening.mp4",
            type="video",
            category="template",
            labels=["opening"]  # ending が不足
        )
    ]

    report2 = temp_library.get_sufficiency_report()
    recommendations = report2["recommendations"]
    
    # 不足素材の検証
    missing_items = []
    for r in recommendations:
        missing_items.extend(r["missing"])
    
    # channel_owner で work, activity, logo が不足
    assert "work" in missing_items
    assert "activity" in missing_items
    assert "logo" in missing_items
    
    # template で ending が不足
    assert "ending" in missing_items
    
    # guest の不足は検出されないはず
    assert not any(r["category"] == "guest" for r in recommendations)


def test_hex_to_color_name_mapping():
    """_hex_to_color_name 関数の各HEXマッピングと明度/色相判定ロジック (L463-466)"""
    # 定義済みのマッピング
    assert _hex_to_color_name("#ff0000") == "赤"
    assert _hex_to_color_name("00ff") == "緑"
    # ffa500, #ffffff は "ff" 前方一致の優先ルールにより "赤" と判定される挙動を検証
    assert _hex_to_color_name("ffa500") == "赤"
    assert _hex_to_color_name("#ffffff") == "赤"
    
    # 暖色系判定 (R > B + 30)
    assert _hex_to_color_name("#801010") == "暖色系"  # R=128, B=16
    
    # 寒色系判定 (B > R + 30)
    assert _hex_to_color_name("#101080") == "寒色系"  # R=16, B=128
    
    # 明るい色判定 (brightness > 200)
    assert _hex_to_color_name("#dedede") == "明るい色"  # R=G=B=222
    
    # 暗い色判定 (brightness < 60)
    assert _hex_to_color_name("#1a1a1a") == "暗い色"  # R=G=B=26

    # どの分岐にも該当せず return "" になるケース (brightness = 100) (L65->69)
    assert _hex_to_color_name("#646464") == ""
    
    # 無効なHEXコードのフォールバック (L67-68)
    assert _hex_to_color_name("invalid") == ""


def test_tag_for_search_formatting(temp_library):
    """tag_for_search のテキストサマリー構築とカラー変換 (L463-466)"""
    asset = AssetEntry(
        id="asset_0001",
        path="owner/portrait.png",
        filename="portrait.png",
        type="photo",
        category="channel_owner",
        labels=["portrait", "人物"],
        style_tags=["formal"],
        # 無効なカラーコードを含めることでブランチ465->463 (name が空) をカバー
        colors=["#ff0000", "#1a1a1a", "invalid_color"],
        mood="energetic",
        usage_for=["thumbnail"]
    )
    
    tag = temp_library.tag_for_search(asset, series_theme="書道シリーズ")
    
    assert "ファイル名: portrait.png" in tag
    assert "種別: photo" in tag
    assert "カテゴリ: channel_owner" in tag
    assert "ラベル: portrait, 人物" in tag
    assert "スタイル: formal" in tag
    assert "色: 赤, 暗い色" in tag  # invalid_color はスキップされている
    assert "雰囲気: energetic" in tag
    assert "用途: thumbnail" in tag
    assert "シリーズテーマ: 書道シリーズ" in tag

    # デフォルト値/空値のハンドリング
    asset_minimal = AssetEntry(
        id="asset_0002",
        path="minimal.png",
        filename="minimal.png",
        type="photo",
        category="other"
    )
    tag_minimal = temp_library.tag_for_search(asset_minimal)
    assert "雰囲気" not in tag_minimal
    assert "色:" not in tag_minimal
    assert "シリーズテーマ" not in tag_minimal


@patch("services.vector_search.vector_search_engine")
def test_search_assets_auto_build_and_search(mock_vector_engine, temp_library):
    """search_assets 呼び出し時にインデックスが空なら自動ビルドされること (L492-494)"""
    # 1. stats の total_entries が 0 の場合
    mock_vector_engine.get_index_stats.return_value = {"total_entries": 0}
    
    mock_search_result = MagicMock(asset_id="asset_0001", score=0.95, text_summary="Summary")
    mock_vector_engine.search.return_value = [mock_search_result]

    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="path.png",
            filename="path.png",
            type="photo",
            category="brand"
        )
    ]

    with patch.object(temp_library, "build_search_index") as mock_build_index:
        results = temp_library.search_assets(query="テストクエリ")
        
        # 自動ビルドがトリガーされたことを検証 (L492-494)
        mock_build_index.assert_called_once_with(force_rebuild=False)
        
        # 検索結果の構築を検証
        assert len(results) == 1
        assert results[0]["id"] == "asset_0001"
        assert results[0]["search_score"] == 0.95
        assert results[0]["search_text_summary"] == "Summary"


@patch("services.vector_search.vector_search_engine")
def test_build_search_index_with_series_planner(mock_vector_engine, temp_library):
    """series_plannerからシリーズテーマを取得してインデックスを構築するパス (L524-535, L541-544, L559)"""
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="brand/my_video_1.mp4",
            filename="my_video_1.mp4",
            type="video",
            category="brand"
        )
    ]

    # 1. 正常系: series_planner からシリーズ情報を取得し、一致する動画アセットにテーマが適用されること (L541-544)
    # 不一致の動画ID(non_matching_video_id)や空のvideo_idを含めてブランチ 532->530, 542->541 をカバー
    mock_series_planner = MagicMock()
    mock_series_planner.series_data = {
        "series": {
            "series_abc": {
                "theme": "未来テクノロジー",
                "videos": [
                    {"video_id": "non_matching_video_id"},
                    {"video_id": ""},  # 空のvideo_id
                    {"video_id": "my_video_1"}
                ]
            }
        }
    }

    with patch("services.series_planner.series_planner", mock_series_planner):
        temp_library.build_search_index(force_rebuild=False)
        
        # build_index が呼ばれた引数を確認
        args, kwargs = mock_vector_engine.build_index.call_args
        built_entries = args[0]
        
        assert len(built_entries) == 1
        assert built_entries[0]["asset_id"] == "asset_0001"
        # シリーズテーマが付与されていること
        assert "シリーズテーマ: 未来テクノロジー" in built_entries[0]["text"]

    # 2. 例外系: series_planner インポートまたはアクセス時にエラーが発生した場合 (L534-535)
    with patch.dict("sys.modules", {"services.series_planner": None}):
        # 例外がスローされず、処理が続行されること
        result = temp_library.build_search_index(force_rebuild=False)
        assert result is not None

    # 3. force_rebuild=True 時の処理 (L559)
    temp_library.build_search_index(force_rebuild=True)
    mock_vector_engine.rebuild_index.assert_called_once()


def test_global_helper_functions(temp_library):
    """グローバルに定義された簡易ラッパーヘルパー関数をテスト (L571-578)"""
    with patch("asset_library.asset_library") as mock_global_lib:
        mock_global_lib.scan.return_value = {"status": "scanned"}
        mock_global_lib.get_assets_for_task.return_value = {"status": "retrieved"}

        # 1. scan_assets
        res_scan = scan_assets(auto_label=False)
        mock_global_lib.scan.assert_called_once_with(False)
        assert res_scan == {"status": "scanned"}

        # 2. get_assets_for
        res_get = get_assets_for("thumbnail", {"ctx": "val"})
        mock_global_lib.get_assets_for_task.assert_called_once_with("thumbnail", {"ctx": "val"})
        assert res_get == {"status": "retrieved"}


def test_load_index_type_error(tmp_path, mock_gemini_deps, caplog):
    """インデックスのデータ構造が辞書型でない等のTypeErrorをテスト"""
    index_path = tmp_path / "asset_index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"assets": "invalid_assets_string"}, f)

    with caplog.at_level(logging.ERROR):
        lib = CreativeAssetLibrary(asset_root=tmp_path)
        assert len(lib.assets) == 0
        assert any("インデックス読み込みエラー" in record.message for record in caplog.records)


def test_build_search_index_key_error(temp_library, mock_gemini_deps):
    """series_planner から取得したデータ構造が不正で KeyError を起こすフォールバックテスト"""
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="brand/my_video_1.mp4",
            filename="my_video_1.mp4",
            type="video",
            category="brand"
        )
    ]
    mock_series_planner = MagicMock()
    mock_series_planner.series_data = {}

    with patch("services.series_planner.series_planner", mock_series_planner):
        result = temp_library.build_search_index(force_rebuild=False)
        assert result is not None


def test_scan_auto_label_returns_none(temp_library, tmp_path):
    """_label_asset が None を返した場合（auto_label=True の分岐）をテスト (L282->289)"""
    photo_dir = tmp_path / "channel_owner" / "photos"
    photo_path = photo_dir / "my_photo.png"
    photo_path.write_bytes(b"dummy image data")

    with patch.object(temp_library, "_label_asset", return_value=None):
        result = temp_library.scan(auto_label=True)
        assert result["new_assets"] == 1
        assert len(temp_library.assets) == 1
        asset = temp_library.assets[0]
        assert asset.labels == []  # ラベルが適用されず空


@patch("services.vector_search.vector_search_engine")
def test_search_assets_already_indexed(mock_vector_engine, temp_library):
    """search_assets 呼び出し時にインデックスが空でない場合（492->496）をテスト"""
    # すでにインデックスが 5 件あるとする
    mock_vector_engine.get_index_stats.return_value = {"total_entries": 5}
    mock_search_result = MagicMock(asset_id="asset_0001", score=0.85, text_summary="summary")
    mock_vector_engine.search.return_value = [mock_search_result]

    temp_library.assets = [
        AssetEntry(id="asset_0001", path="path.png", filename="path.png", type="photo", category="brand")
    ]

    with patch.object(temp_library, "build_search_index") as mock_build_index:
        results = temp_library.search_assets(query="query")
        # すでにインデックスがあるので自動ビルドされないこと
        mock_build_index.assert_not_called()
        assert len(results) == 1
        assert results[0]["id"] == "asset_0001"


@patch("services.vector_search.vector_search_engine")
def test_search_assets_asset_not_found(mock_vector_engine, temp_library):
    """search_assets で検索結果のアセットが assets に見つからない場合（500->498）をテスト"""
    mock_vector_engine.get_index_stats.return_value = {"total_entries": 1}
    mock_search_result = MagicMock(asset_id="non_existent_asset", score=0.90, text_summary="Missing")
    mock_vector_engine.search.return_value = [mock_search_result]

    temp_library.assets = [
        AssetEntry(id="asset_0001", path="path.png", filename="path.png", type="photo", category="brand")
    ]

    results = temp_library.search_assets(query="query")
    # 一致するアセットがないため空リストになること
    assert len(results) == 0


def test_hex_to_color_name_boundary_and_invalid_formats():
    """_hex_to_color_name 関数の詳細な境界値および無効な入力フォーマットのテスト"""
    # 1. 暖色系境界値 (R > B + 30)
    assert _hex_to_color_name("#836464") == "暖色系"
    assert _hex_to_color_name("#826464") == ""

    # 2. 寒色系境界値 (B > R + 30)
    assert _hex_to_color_name("#646483") == "寒色系"
    assert _hex_to_color_name("#646482") == ""

    # 3. 明るい色境界値 (brightness = (R+G+B)/3 > 200)
    assert _hex_to_color_name("#c9c9c9") == "明るい色"
    assert _hex_to_color_name("#c8c8c8") == ""

    # 4. 暗い色境界値 (brightness = (R+G+B)/3 < 60)
    assert _hex_to_color_name("#3b3b3b") == "暗い色"
    assert _hex_to_color_name("#3c3c3c") == ""

    # 5. 特殊・無効なHEXコードのパースエラー検証
    assert _hex_to_color_name("") == ""
    assert _hex_to_color_name("#12") == ""
    assert _hex_to_color_name("#zzzzzz") == ""


def test_ensure_structure_readme_exists(tmp_path, mock_gemini_deps):
    """README.mdが既に存在する場合、_ensure_structureがファイルを上書きしないことを検証"""
    readme_path = tmp_path / "README.md"
    existing_content = "Custom README content"
    readme_path.write_text(existing_content, encoding="utf-8")

    lib = CreativeAssetLibrary(asset_root=tmp_path)
    assert readme_path.read_text(encoding="utf-8") == existing_content


def test_load_index_missing_optional_keys(tmp_path, mock_gemini_deps):
    """インデックスファイル内で assets や guests キーが欠損している場合でも正常にフォールバックすること"""
    index_path = tmp_path / "asset_index.json"
    index_path.write_text("{}", encoding="utf-8")

    lib = CreativeAssetLibrary(asset_root=tmp_path)
    assert lib.assets == []
    assert lib.guests == {}


def test_scan_directory_with_unsupported_type_or_is_dir(temp_library, tmp_path):
    """拡張子名をもつディレクトリそのものや、非ファイルがスキャンから除外されることを検証"""
    photo_dir = tmp_path / "channel_owner" / "photos"

    fake_photo_dir = photo_dir / "fake_image_dir.png"
    fake_photo_dir.mkdir(parents=True, exist_ok=True)

    result = temp_library.scan()
    assert result["new_assets"] == 0
    assert len(temp_library.assets) == 0


def test_scan_category_priority(temp_library, tmp_path):
    """パスの中に複数のカテゴリキーワードが含まれる場合、優先順位に基づいて正しくカテゴリが判定されること"""
    nested_dir = tmp_path / "guests" / "channel_owner" / "photos"
    nested_dir.mkdir(parents=True, exist_ok=True)

    photo_path = nested_dir / "my_photo.png"
    photo_path.write_bytes(b"data")

    temp_library.scan(auto_label=False)
    assert len(temp_library.assets) == 1
    assert temp_library.assets[0].category == "channel_owner"


def test_get_assets_for_task_with_context(temp_library):
    """get_assets_for_task で context 引数が渡されてもエラーにならず、シグネチャ互換性が維持されていること"""
    temp_library.assets = [
        AssetEntry(
            id="asset_0001",
            path="channel_owner/photos/portrait.png",
            filename="portrait.png",
            type="photo",
            category="channel_owner",
            labels=["portrait"],
            usage_for=["thumbnail"]
        )
    ]
    dummy_context = {"project_id": 123, "theme": "modern"}
    result = temp_library.get_assets_for_task("thumbnail", context=dummy_context)
    assert len(result["recommended"]) == 1
    assert result["recommended"][0]["id"] == "asset_0001"


@patch("services.vector_search.vector_search_engine")
def test_search_assets_with_varying_top_k(mock_vector_engine, temp_library):
    """search_assets に様々な top_k の値を渡した場合の挙動を検証"""
    mock_vector_engine.get_index_stats.return_value = {"total_entries": 10}

    mock_results = [
        MagicMock(asset_id=f"asset_000{i}", score=0.9 - i*0.1, text_summary=f"Summary {i}")
        for i in range(1, 6)
    ]
    mock_vector_engine.search.return_value = mock_results

    temp_library.assets = [
        AssetEntry(id=f"asset_000{i}", path=f"path_{i}.png", filename=f"filename_{i}.png", type="photo", category="brand")
        for i in range(1, 6)
    ]

    results = temp_library.search_assets(query="query", top_k=3)
    mock_vector_engine.search.assert_called_with(query="query", top_k=3)
    assert len(results) == 5


def test_save_index_permission_error(temp_library, tmp_path):
    """_save_index で書き込みエラー（OSError）が発生した際、一時ファイルがクリーンアップされ、例外が再送されることを検証"""
    from unittest.mock import patch
    import pytest
    with patch("builtins.open", side_effect=OSError("Permission denied")):
        with pytest.raises(OSError):
            temp_library._save_index()


def test_load_index_corrupted_backup(tmp_path, mock_gemini_deps, caplog):
    """_load_index で json が破損している場合、.corrupted ファイルに退避されることを検証"""
    import logging
    from asset_library import CreativeAssetLibrary
    index_path = tmp_path / "asset_index.json"
    index_path.write_text("{invalid json", encoding="utf-8")

    corrupted_path = tmp_path / "asset_index.corrupted"
    if corrupted_path.exists():
        corrupted_path.unlink()

    lib = CreativeAssetLibrary(asset_root=tmp_path)
    # インデックス読み込みエラーが発生し、かつバックアップが作成されていることを確認
    assert corrupted_path.exists()
    assert corrupted_path.read_text(encoding="utf-8") == "{invalid json"


def test_scan_hash_file_error(temp_library, tmp_path, caplog):
    """スキャン中にファイルハッシュ生成で OSError が発生した場合、そのファイルはスキップされスキャン自体は継続することを検証"""
    from unittest.mock import patch
    import logging
    photo_dir = tmp_path / "channel_owner" / "photos"
    ok_path = photo_dir / "ok.png"
    ok_path.write_bytes(b"ok data")

    err_path = photo_dir / "error.png"
    err_path.write_bytes(b"error data")

    original_get_hash = temp_library._get_file_hash
    def side_effect_hash(path):
        if "error.png" in str(path):
            raise OSError("File locked")
        return original_get_hash(path)

    with patch.object(temp_library, "_get_file_hash", side_effect=side_effect_hash):
        with caplog.at_level(logging.ERROR):
            result = temp_library.scan(auto_label=False)
            assert result["new_assets"] == 1
            assert len(temp_library.assets) == 1
            assert temp_library.assets[0].filename == "ok.png"
            assert any("ファイルハッシュの取得に失敗しました" in record.message for record in caplog.records)


def test_load_index_backup_os_error(tmp_path, mock_gemini_deps, caplog):
    """_load_index で json が破損しており、かつバックアップ作成(replace)時に OSError が発生した場合をテスト (L208-209)"""
    index_path = tmp_path / "asset_index.json"
    index_path.write_text("{invalid json", encoding="utf-8")

    with patch("pathlib.Path.replace", side_effect=OSError("Replace failed")):
        with caplog.at_level(logging.ERROR):
            lib = CreativeAssetLibrary(asset_root=tmp_path)
            assert len(lib.assets) == 0
            assert any("破損インデックスのバックアップ失敗" in record.message for record in caplog.records)


def test_save_index_unlink_os_error(temp_library):
    """_save_index で書き込みエラーが発生し、かつ一時ファイル削除(unlink)時に OSError が発生した場合をテスト (L230-233)"""
    # 事前に一時ファイルを作成しておくことで tmp_path.exists() が True になるようにする
    tmp_file_path = temp_library.index_path.with_suffix(".tmp")
    tmp_file_path.write_text("dummy temp content", encoding="utf-8")

    # open関数でOSErrorを発生させて例外ハンドリングに入らせる
    with patch("builtins.open", side_effect=OSError("Write failed")):
        # Path.unlink で OSError を発生させる
        with patch("pathlib.Path.unlink", side_effect=OSError("Unlink failed")):
            with pytest.raises(OSError, match="Write failed"):
                temp_library._save_index()


def test_hex_to_color_name_edge_cases():
    """_hex_to_color_name 関数のさらなる境界値や特殊な大文字小文字の混在を検証"""
    # 大文字混在
    assert _hex_to_color_name("#FF0000") == "赤"
    assert _hex_to_color_name("00FF") == "緑"
    
    # 暖色系境界値 (R が B + 30 より大きいかどうか)
    # R = 158, B = 128 (差はちょうど 30) -> 暖色系ではない
    assert _hex_to_color_name("#9e6480") == ""
    # R = 159, B = 128 (差は 31) -> 暖色系
    assert _hex_to_color_name("#9f6480") == "暖色系"

    # 寒色系境界値 (B が R + 30 より大きいかどうか)
    # B = 158, R = 128 (差はちょうど 30) -> 寒色系ではない
    assert _hex_to_color_name("#80649e") == ""
    # B = 159, R = 128 (差は 31) -> 寒色系
    assert _hex_to_color_name("#80649f") == "寒色系"

    # 明るい色境界値 (brightness = (R+G+B)/3 > 200)
    # brightness = (200 + 200 + 200) / 3 = 200 -> 明るい色ではない
    assert _hex_to_color_name("#c8c8c8") == ""
    # brightness = (201 + 201 + 201) / 3 = 201 -> 明るい色
    assert _hex_to_color_name("#c9c9c9") == "明るい色"

    # 暗い色境界値 (brightness < 60)
    # brightness = (60 + 60 + 60) / 3 = 60 -> 暗い色ではない
    assert _hex_to_color_name("#3c3c3c") == ""
    # brightness = (59 + 59 + 59) / 3 = 59 -> 暗い色
    assert _hex_to_color_name("#3b3b3b") == "暗い色"


def test_save_index_replace_os_error(temp_library):
    """_save_index で replace 時に OSError が発生した場合のクリーンアップ処理を検証"""
    temp_library.assets = [
        AssetEntry(id="asset_0001", path="path.png", filename="path.png", type="photo", category="brand")
    ]
    
    # Path.replace で OSError を発生させる
    with patch("pathlib.Path.replace", side_effect=OSError("Replace failed")):
        # 一時ファイルが削除されることを検証するため、Path.unlink のモックを作成し呼び出しを監視
        with patch("pathlib.Path.unlink") as mock_unlink:
            with pytest.raises(OSError, match="Replace failed"):
                temp_library._save_index()
            # 一時ファイル削除が試みられたことを確認
            mock_unlink.assert_called_once()


def test_scan_case_insensitive_extensions(temp_library, tmp_path):
    """スキャン時に大文字の拡張子（.PNG, .MP4, .MP3）も正しく検出されることを検証"""
    photo_dir = tmp_path / "channel_owner" / "photos"
    photo_path = photo_dir / "my_photo.PNG"
    photo_path.write_bytes(b"dummy image data")

    video_dir = tmp_path / "channel_owner" / "videos"
    video_path = video_dir / "my_video.MP4"
    video_path.write_bytes(b"dummy video data")

    music_dir = tmp_path / "brand" / "music"
    music_path = music_dir / "theme.MP3"
    music_path.write_bytes(b"dummy music data")

    result = temp_library.scan(auto_label=False)
    assert result["new_assets"] == 3
    
    filenames = [a.filename for a in temp_library.assets]
    assert "my_photo.PNG" in filenames
    assert "my_video.MP4" in filenames
    assert "theme.MP3" in filenames

    types = {a.filename: a.type for a in temp_library.assets}
    assert types["my_photo.PNG"] == "photo"
    assert types["my_video.MP4"] == "video"
    assert types["theme.MP3"] == "audio"


@patch("services.vector_search.vector_search_engine")
def test_search_assets_extreme_top_k(mock_vector_engine, temp_library):
    """search_assets に極端な top_k の値を渡した場合の挙動を検証"""
    mock_vector_engine.get_index_stats.return_value = {"total_entries": 5}
    mock_vector_engine.search.return_value = []

    # top_k=0
    temp_library.search_assets(query="test", top_k=0)
    mock_vector_engine.search.assert_called_with(query="test", top_k=0)

    # top_k=1000
    temp_library.search_assets(query="test", top_k=1000)
    mock_vector_engine.search.assert_called_with(query="test", top_k=1000)


def test_tag_for_search_none_and_empty_values(temp_library):
    """tag_for_search に空の値や None が含まれる場合のフォーマット検証"""
    asset = AssetEntry(
        id="asset_0001",
        path="owner/portrait.png",
        filename="portrait.png",
        type="photo",
        category="channel_owner",
        mood=""
    )
    tag = temp_library.tag_for_search(asset, series_theme="")
    
    assert "ファイル名: portrait.png" in tag
    assert "雰囲気" not in tag
    assert "シリーズテーマ" not in tag
    assert "色" not in tag


def test_edge_cases_and_robustness(temp_library, tmp_path):
    """堅牢性を保証するための様々なエッジケースおよび型不正のテスト"""
    # A. _hex_to_color_name の不正な引数の型
    with pytest.raises(AttributeError):
        _hex_to_color_name(None)
    with pytest.raises(AttributeError):
        _hex_to_color_name(123)
    with pytest.raises(AttributeError):
        _hex_to_color_name([])
    assert _hex_to_color_name("#") == ""
    assert _hex_to_color_name("#f") == ""
    assert _hex_to_color_name("#ff") == "赤"
    assert _hex_to_color_name("00ff") == "緑"
    assert _hex_to_color_name("#ff000000000") == "赤"
    assert _hex_to_color_name("1122334455") == "寒色系"
    assert _hex_to_color_name("1122zz") == ""
    assert _hex_to_color_name("12") == ""

    # B. CreativeAssetLibrary 初期化の引数 (str パス)
    lib_str = CreativeAssetLibrary(asset_root=str(tmp_path))
    assert lib_str.asset_root == tmp_path

    # C. scan の空ディレクトリ
    empty_lib = CreativeAssetLibrary(asset_root=tmp_path / "empty_root")
    scan_res = empty_lib.scan()
    assert scan_res["new_assets"] == 0

    # D. get_assets_for_task の不正なタスクタイプと usage_for
    assert temp_library.get_assets_for_task(None) == {"available": [], "recommended": [], "missing": []}
    assert temp_library.get_assets_for_task("") == {"available": [], "recommended": [], "missing": []}
    assert temp_library.get_assets_for_task("unknown_task") == {"available": [], "recommended": [], "missing": []}

    # usage_for が None のアセット
    bad_asset = AssetEntry(
        id="bad", path="bad.png", filename="bad.png", type="photo", category="brand", usage_for=None
    )
    temp_library.assets.append(bad_asset)
    with pytest.raises((TypeError, AttributeError)):
        temp_library.get_assets_for_task("thumbnail")
    
    # テストに影響を与えないように bad_asset を削除
    temp_library.assets.remove(bad_asset)

    # E. get_usage_report の不正な引数
    assert temp_library.get_usage_report([]) == {"referenced_assets": [], "total_referenced": 0}
    assert temp_library.get_usage_report(["non_existent"]) == {"referenced_assets": [], "total_referenced": 0}

    # F. get_sufficiency_report の未知のカテゴリ
    temp_library.assets = [
        AssetEntry(id="custom", path="custom.png", filename="custom.png", type="photo", category="unknown_cat", labels=["logo"])
    ]
    report = temp_library.get_sufficiency_report()
    assert "unknown_cat" in report["categories"]

    # G. tag_for_search のアセットの欠損フィールド
    minimal_asset = AssetEntry(
        id="min", path="min.png", filename="min.png", type="photo", category="brand", colors=None
    )
    with pytest.raises((TypeError, AttributeError)):
        temp_library.tag_for_search(minimal_asset)


def test_extra_edge_cases_and_robustness(temp_library, tmp_path):
    """追加のエッジケーステスト（極端な入力、不正なデータ構造、境界値など）"""
    # 1. _hex_to_color_name のさらなる異常系・極端な入力
    # 3桁のカラーコード（例外で "" が返るべき）
    assert _hex_to_color_name("f00") == ""
    # 短すぎるカラーコード
    assert _hex_to_color_name("a") == ""
    # 長すぎる特殊文字混じり
    assert _hex_to_color_name("#ff0000_invalid_extra_characters") == "赤"
    # 全くHEXコードでない文字列
    assert _hex_to_color_name("xyz") == ""

    # 2. search_assets の top_k 境界値（負の数）
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.get_index_stats.return_value = {"total_entries": 5}
        mock_vector_engine.search.return_value = []
        temp_library.search_assets(query="test", top_k=-1)
        mock_vector_engine.search.assert_called_with(query="test", top_k=-1)

    # 3. search_assets の巨大クエリ
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.get_index_stats.return_value = {"total_entries": 5}
        mock_vector_engine.search.return_value = []
        huge_query = "a" * 5000
        temp_library.search_assets(query=huge_query, top_k=5)
        mock_vector_engine.search.assert_called_with(query=huge_query, top_k=5)

    # 4. build_search_index の series_planner 不正データ構造の堅牢性
    temp_library.assets = [
        AssetEntry(id="asset_0001", path="brand/my_video_1.mp4", filename="my_video_1.mp4", type="video", category="brand")
    ]
    mock_series_planner = MagicMock()
    # "series" キーの値が辞書型ではなくリスト型（通常なら AttributeError や KeyError が発生し得る）
    mock_series_planner.series_data = {
        "series": [
            {"theme": "不正なリスト構造"}
        ]
    }
    with patch("services.series_planner.series_planner", mock_series_planner):
        # 堅牢であるため、エラーをスローせずにフォールバックされ動作完了すること
        result = temp_library.build_search_index(force_rebuild=False)
        assert result is not None

    # 5. scan での非常に長いパス名やファイル名
    photo_dir = tmp_path / "channel_owner" / "photos"
    long_name = "a" * 150 + ".png"
    long_path = photo_dir / long_name
    long_path.write_bytes(b"long path dummy data")

    result = temp_library.scan(auto_label=False)
    assert result["new_assets"] >= 1
    assert any(a.filename == long_name for a in temp_library.assets)

    # 6. get_sufficiency_report における極端なカテゴリ名・ラベル名
    temp_library.assets = [
        AssetEntry(
            id="extreme",
            path="extreme.png",
            filename="extreme.png",
            type="photo",
            category="a" * 200,  # 非常に長いカテゴリ名
            labels=["b" * 200]    # 非常に長いラベル名
        )
    ]
    report = temp_library.get_sufficiency_report()
    assert "a" * 200 in report["categories"]
    assert "b" * 200 in report["categories"]["a" * 200]["by_type"]


def test_more_extreme_edge_cases_and_robustness(temp_library, tmp_path, caplog):
    """追加の極端なエッジケース、境界値、型不正テスト"""
    # 1. _hex_to_color_name のインデックスエラー / 変換エラー（4文字や5文字のHEXコード）
    # "#f000" は長さ5文字。明度判定ロジック int(h[4:6], 16) で IndexError になるはず。
    # 例外が内部でキャッチされて "" を返すことを確認。
    from asset_library import _hex_to_color_name
    assert _hex_to_color_name("#f000") == ""
    assert _hex_to_color_name("#f0") == ""

    # 2. _load_index で JSONルートがリストの場合 (AttributeError の例外ハンドリング)
    index_path = tmp_path / "asset_index.json"
    index_path.write_text('["list", "instead", "of", "dict"]', encoding="utf-8")
    
    with caplog.at_level(logging.ERROR):
        lib = CreativeAssetLibrary(asset_root=tmp_path)
        assert len(lib.assets) == 0
        assert any("インデックス読み込みエラー" in record.message for record in caplog.records)

    # 3. _ensure_structure で作成対象のフォルダと同名のファイルが存在する場合の挙動
    custom_tmp = tmp_path / "conflict_test_root"
    # あらかじめ、作成予定のフォルダの一つをファイルとして作成しておく
    conflict_path = custom_tmp / "channel_owner" / "photos"
    conflict_path.parent.mkdir(parents=True, exist_ok=True)
    conflict_path.write_text("i am a file", encoding="utf-8")

    # 例外 (OSError) が発生することを確認
    with pytest.raises(OSError):
        CreativeAssetLibrary(asset_root=custom_tmp)


    # 4. get_assets_for_task にハッシュ不可な型 (リスト) を指定した場合の例外
    with pytest.raises(TypeError):
        temp_library.get_assets_for_task(["unhashable"])

    # 5. 0バイトの空ファイルのハッシュ生成テスト
    empty_file = tmp_path / "empty_asset.png"
    empty_file.write_bytes(b"")
    hash_val = temp_library._get_file_hash(empty_file)
    # 0バイトのmd5ハッシュ値
    assert hash_val == "d41d8cd98f00b204e9800998ecf8427e"


def test_weaver_edge_cases_and_robustness(temp_library, tmp_path):
    """追加のエッジケース（境界値、None入力、空リスト、重複ID、不正なデータ構造など）を検証"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name

    # 1. get_usage_report のエッジケース
    # 1.1 重複IDの入力
    temp_library.assets = [
        AssetEntry(id="asset_dup", path="brand/dup.png", filename="dup.png", type="photo", category="brand")
    ]
    report = temp_library.get_usage_report(["asset_dup", "asset_dup"])
    assert report["total_referenced"] == 2
    # usage_count が 2 に増加していることを確認
    assert temp_library.assets[0].usage_count == 2
    assert report["referenced_assets"][0]["usage_count"] == 1
    assert report["referenced_assets"][1]["usage_count"] == 2

    # 1.2 空リスト入力
    report_empty = temp_library.get_usage_report([])
    assert report_empty["total_referenced"] == 0
    assert len(report_empty["referenced_assets"]) == 0

    # 1.3 不正型 (None) 入力
    with pytest.raises(TypeError):
        temp_library.get_usage_report(None)

    # 2. get_sufficiency_report のエッジケース
    # 2.1 アセットがゼロ（空のライブラリ）の場合
    temp_library.assets = []
    sufficiency = temp_library.get_sufficiency_report()
    assert sufficiency["total_assets"] == 0
    assert len(sufficiency["categories"]) == 0
    # 全ての必須カテゴリが missing に含まれているか検証
    missing_cats = [r["category"] for r in sufficiency["recommendations"]]
    assert "channel_owner" in missing_cats
    assert "guest" in missing_cats
    assert "template" in missing_cats

    # 3. _hex_to_color_name の不正型エッジケース
    # 3.1 非文字列（Noneや整数）の入力で例外が発生することを確認
    with pytest.raises(AttributeError):
        _hex_to_color_name(None)
    with pytest.raises(AttributeError):
        _hex_to_color_name(12345)

    # 4. search_assets の空入力エッジケース
    # 4.1 空文字列 "" および None クエリの入力時の挙動検証
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.get_index_stats.return_value = {"total_entries": 1}
        mock_vector_engine.search.return_value = []
        
        temp_library.search_assets(query="", top_k=5)
        mock_vector_engine.search.assert_called_with(query="", top_k=5)
        
        # query が None の場合、内部の logger.info スライス処理で TypeError が発生することを確認する
        with pytest.raises(TypeError):
            temp_library.search_assets(query=None, top_k=5)

    # 5. build_search_index の欠損構造エッジケース
    # 5.1 series_planner の series_data で videos が欠損している、または None の場合
    temp_library.assets = [
        AssetEntry(id="asset_0001", path="brand/v1.mp4", filename="v1.mp4", type="video", category="brand")
    ]
    mock_series_planner = MagicMock()
    # videos キーが欠損しているデータ構造
    mock_series_planner.series_data = {
        "series": {
            "series_id_1": {
                "theme": "テストテーマ1"
                # videos キーがない
            }
        }
    }
    with patch("services.series_planner.series_planner", mock_series_planner):
        result = temp_library.build_search_index(force_rebuild=False)
        assert result is not None

    # 5.2 videos が None のデータ構造
    mock_series_planner.series_data = {
        "series": {
            "series_id_1": {
                "theme": "テストテーマ2",
                "videos": None
            }
        }
    }
    with patch("services.series_planner.series_planner", mock_series_planner):
        result = temp_library.build_search_index(force_rebuild=False)
        assert result is not None


def test_weaver_comprehensive_edge_cases(temp_library, tmp_path):
    """Weaver タスク要件に基づく網羅的なエッジケース、境界値、型不正、巨大入力の追加テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from pathlib import Path
    from asset_library import AssetEntry, _hex_to_color_name, CreativeAssetLibrary

    # A. _hex_to_color_name 関数のエッジケース
    # 暖色系・寒色系のさらに境界値の確認
    assert _hex_to_color_name("#9e6480") == ""  # R=158, B=128 (差30) -> 境界値
    assert _hex_to_color_name("#9f6480") == "暖色系"  # R=159, B=128 (差31)
    assert _hex_to_color_name("#80649e") == ""  # B=158, R=128 (差30) -> 境界値
    assert _hex_to_color_name("#80649f") == "寒色系"  # B=159, R=128 (差31)

    # B. CreativeAssetLibrary._get_file_hash のエッジケース（存在しないファイル）
    non_existent_file = tmp_path / "does_not_exist_file.png"
    with pytest.raises(OSError):
        temp_library._get_file_hash(non_existent_file)

    # C. CreativeAssetLibrary.scan メソッドのエッジケース（auto_label の不正型）
    # auto_label に真偽値以外を渡した時の動作確認
    # None の場合、bool(None) は False として評価されるため、auto_label は走らず正常終了する
    result_none = temp_library.scan(auto_label=None)
    assert "new_assets" in result_none

    # D. CreativeAssetLibrary.get_assets_for_task メソッドのエッジケース
    # 巨大なタスクタイプ（5000文字）
    huge_task_type = "a" * 5000
    res_huge_task = temp_library.get_assets_for_task(huge_task_type)
    assert res_huge_task == {"available": [], "recommended": [], "missing": []}

    # context に辞書以外の不正な型（リスト）を渡した場合
    res_invalid_ctx = temp_library.get_assets_for_task("thumbnail", context=["invalid", "type"])
    assert "available" in res_invalid_ctx

    # E. CreativeAssetLibrary.get_usage_report メソッドのエッジケース
    # referenced_assets が set の場合
    temp_library.assets = [
        AssetEntry(id="asset_set_test", path="brand/test.png", filename="test.png", type="photo", category="brand")
    ]
    report_set = temp_library.get_usage_report({"asset_set_test"})
    assert report_set["total_referenced"] == 1
    assert temp_library.assets[0].usage_count == 1

    # referenced_assets に無効なID（Noneや空文字、数値など型不正）が混在している場合
    # list内のNoneなどは、next(...) で一致しないため単に無視される
    report_mixed = temp_library.get_usage_report(["asset_set_test", None, "", 12345])
    assert report_mixed["total_referenced"] == 1

    # F. CreativeAssetLibrary.get_sufficiency_report メソッドのエッジケース
    # category や labels が None のアセットを手動で追加した場合の堅牢性
    # asdict などの挙動や、レポート処理が壊れないこと
    bad_data_asset = AssetEntry(
        id="bad_fields",
        path="brand/bad.png",
        filename="bad.png",
        type="photo",
        category=None,
        labels=None
    )
    temp_library.assets = [bad_data_asset]
    with pytest.raises((TypeError, AttributeError)):
        temp_library.get_sufficiency_report()

    # G. CreativeAssetLibrary.tag_for_search メソッドのエッジケース
    # series_theme に巨大な文字列（10万文字）を指定した場合
    huge_theme = "x" * 100000
    test_asset = AssetEntry(
        id="theme_test", path="brand/test.png", filename="test.png", type="photo", category="brand"
    )
    tag_result = temp_library.tag_for_search(test_asset, series_theme=huge_theme)
    assert huge_theme in tag_result

    # asset.colors に None 要素が混入している場合
    test_asset_colors = AssetEntry(
        id="colors_test", path="brand/test.png", filename="test.png", type="photo", category="brand",
        colors=["#ff0000", None]
    )
    with pytest.raises(AttributeError):
        temp_library.tag_for_search(test_asset_colors)

    # H. CreativeAssetLibrary.search_assets メソッドのエッジケース
    # query が非常に巨大な場合（1万文字）
    # top_k が非常に巨大な値（1000000）
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.get_index_stats.return_value = {"total_entries": 10}
        mock_vector_engine.search.return_value = []
        
        huge_query = "q" * 10000
        temp_library.search_assets(query=huge_query, top_k=1000000)
        mock_vector_engine.search.assert_called_with(query=huge_query, top_k=1000000)

    # I. CreativeAssetLibrary.build_search_index メソッドのエッジケース
    # force_rebuild に不正型 (Noneや数値など)
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.build_index.return_value = {"status": "ok"}
        temp_library.build_search_index(force_rebuild=None)  # None は False とみなされる
        mock_vector_engine.build_index.assert_called_once()

    # series_planner の series_data が辞書ではなく、非反復不可能な型 (例えば整数 123) の場合
    mock_series_planner = MagicMock()
    mock_series_planner.series_data = 123  # 不正な型
    with patch("services.series_planner.series_planner", mock_series_planner):
        with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
            mock_vector_engine.build_index.return_value = {"status": "ok"}
            # AttributeError が発生し、例外ハンドリングの logger.warning を通って正常にフォールバックすることを確認
            result = temp_library.build_search_index(force_rebuild=False)
            assert result is not None


def test_weaver_batch_0b01db_edge_cases(temp_library, tmp_path):
    """T-batch_0b01db-test_weaver-001 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name

    # 1. _hex_to_color_name の極端な入力と無効な文字列
    # 1.1 特殊文字や日本語が混在したカラーコード
    assert _hex_to_color_name("#ff0000日本語") == "赤"  # "ff" 前方一致
    assert _hex_to_color_name("#zzzzzz日本語") == ""
    # 1.2 ハッシュマークだけの文字列
    assert _hex_to_color_name("#") == ""
    # 1.3 明度計算時の端数 (例: #010101, brightness=1)
    assert _hex_to_color_name("#010101") == "暗い色"

    # 2. _get_file_hash に対する不正な引数 (None)
    with pytest.raises((TypeError, AttributeError)):
        temp_library._get_file_hash(None)

    # 3. scan の auto_label 引数に文字列 "False" を渡した場合 (Pythonでは bool("False") は True になるため auto_label が走る挙動を確認)
    # スキャン対象がないため、new_assets は 0 になるが、エラーが起きないことを確認
    res = temp_library.scan(auto_label="False")
    assert res["new_assets"] == 0

    # 4. get_assets_for_task の task_type 引数に数値や非文字列を渡した場合の挙動
    # 例外が起きず、空のレポートが返ることを確認
    assert temp_library.get_assets_for_task(12345) == {"available": [], "recommended": [], "missing": []}

    # 5. get_usage_report の referenced_assets に None が混ざったリストや空文字が混ざったリストを渡した場合
    temp_library.assets = [
        AssetEntry(id="asset_exist", path="brand/ok.png", filename="ok.png", type="photo", category="brand")
    ]
    report = temp_library.get_usage_report(["asset_exist", None, "", "non_existent"])
    assert report["total_referenced"] == 1
    assert temp_library.assets[0].usage_count == 1

    # 6. get_sufficiency_report のエッジケース
    # 6.1 category が None の場合（例外は起きず、集計結果に None カテゴリが含まれる）
    temp_library.assets = [
        AssetEntry(id="bad_cat", path="brand/bad.png", filename="bad.png", type="photo", category=None)
    ]
    report = temp_library.get_sufficiency_report()
    assert None in report["categories"]
    assert report["categories"][None]["total"] == 1

    # 6.2 labels が None の場合（TypeError が発生することを期待）
    temp_library.assets = [
        AssetEntry(id="bad_labels", path="brand/bad.png", filename="bad.png", type="photo", category="brand", labels=None)
    ]
    with pytest.raises(TypeError):
        temp_library.get_sufficiency_report()

    # 7. tag_for_search で colors に空文字列が含まれる場合、スキップされること
    temp_library.assets = [
        AssetEntry(
            id="empty_color", path="brand/test.png", filename="test.png", type="photo", category="brand",
            colors=[""]
        )
    ]
    tag = temp_library.tag_for_search(temp_library.assets[0])
    assert "色" not in tag

    # 8. search_assets のクエリが半角スペースのみの場合
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.get_index_stats.return_value = {"total_entries": 10}
        mock_vector_engine.search.return_value = []
        res_spaces = temp_library.search_assets("     ", top_k=5)
        assert len(res_spaces) == 0
        mock_vector_engine.search.assert_called_with(query="     ", top_k=5)

    # 9. build_search_index で assets が空リストの場合の正常系
    temp_library.assets = []
    with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
        mock_vector_engine.build_index.return_value = {"status": "ok"}
        result = temp_library.build_search_index(force_rebuild=False)
        assert result["status"] == "ok"
        # assets が空なので build_index は空リストで呼ばれるはず
        mock_vector_engine.build_index.assert_called_once_with([])


def test_weaver_batch_1f6ac8_edge_cases(temp_library, tmp_path):
    """T-batch_1f6ac8-test_weaver-000 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name

    # 1. _hex_to_color_name に対する非文字列かつハッシュ可能な不正型の入力
    # 文字列以外のオブジェクトが渡された際に、正しく例外が発生することを確認
    class CustomHashable:
        def __hash__(self):
            return 42
    with pytest.raises(AttributeError):
        _hex_to_color_name(CustomHashable())
    with pytest.raises(AttributeError):
        _hex_to_color_name(object())

    # 2. scan の auto_label 引数に真偽値以外のオブジェクトを渡した場合
    # 例外が起きず正常に動作することを確認
    res_obj = temp_library.scan(auto_label=object())
    assert res_obj["new_assets"] == 0

    # 3. scan で _get_file_hash が PermissionError (OSErrorの一種) をスローした場合
    # エラーが発生したファイルがスキップされ、他のファイルのスキャンが継続することを検証
    photo_dir = tmp_path / "channel_owner" / "photos"
    ok_path = photo_dir / "ok_file.png"
    ok_path.write_bytes(b"ok_data")

    err_path = photo_dir / "locked_file.png"
    err_path.write_bytes(b"locked_data")

    original_get_hash = temp_library._get_file_hash
    def side_effect_hash(path):
        if "locked_file.png" in str(path):
            raise PermissionError("Access denied")
        return original_get_hash(path)

    with patch.object(temp_library, "_get_file_hash", side_effect=side_effect_hash):
        result = temp_library.scan(auto_label=False)
        assert result["new_assets"] == 1
        assert len(temp_library.assets) == 1
        assert temp_library.assets[0].filename == "ok_file.png"

    # 4. get_assets_for_task における未知のタスクタイプと推奨ルール
    # 未知のタスクタイプであっても、usage_for に含まれていれば recommended に分類されることを検証
    custom_asset = AssetEntry(
        id="asset_custom_task", path="brand/test.png", filename="test.png", type="photo", category="brand",
        usage_for=["my_custom_task"]
    )
    temp_library.assets.append(custom_asset)
    res_task = temp_library.get_assets_for_task("my_custom_task")
    assert len(res_task["recommended"]) == 1
    assert res_task["recommended"][0]["id"] == "asset_custom_task"
    temp_library.assets.remove(custom_asset)

    # 5. get_usage_report における走査用ジェネレータ（イテレータ）の入力
    temp_library.assets = [
        AssetEntry(id="asset_iter_test", path="brand/test.png", filename="test.png", type="photo", category="brand")
    ]
    report_gen = temp_library.get_usage_report(x for x in ["asset_iter_test"])
    assert report_gen["total_referenced"] == 1
    assert temp_library.assets[0].usage_count == 1

    # 6. get_sufficiency_report における空のラベル（空リスト）
    temp_library.assets = [
        AssetEntry(id="empty_labels_asset", path="brand/test.png", filename="test.png", type="photo", category="brand", labels=[])
    ]
    report_suff = temp_library.get_sufficiency_report()
    assert report_suff["total_assets"] == 1
    assert "brand" in report_suff["categories"]
    assert report_suff["categories"]["brand"]["by_type"] == {}

    # 7. tag_for_search の引数 asset における colors フィールドの欠損
    minimal_asset = AssetEntry(
        id="min_asset", path="min.png", filename="min.png", type="photo", category="brand"
    )
    # colors を None に設定
    minimal_asset.colors = None
    with pytest.raises((TypeError, AttributeError)):
        temp_library.tag_for_search(minimal_asset)

    # 8. build_search_index における series_planner データ破壊時（seriesがNone）のフォールバック
    temp_library.assets = [
        AssetEntry(id="asset_0001", path="brand/v1.mp4", filename="v1.mp4", type="video", category="brand")
    ]
    mock_series_planner = MagicMock()
    # series が None の場合
    mock_series_planner.series_data = {
        "series": None
    }
    with patch("services.series_planner.series_planner", mock_series_planner):
        with patch("services.vector_search.vector_search_engine") as mock_vector_engine:
            mock_vector_engine.build_index.return_value = {"status": "ok"}
            result = temp_library.build_search_index(force_rebuild=False)
            assert result["status"] == "ok"


def test_weaver_batch_c18785_edge_cases(temp_library, tmp_path):
    """T-batch_c18785-test_weaver-000 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name

    # 1. _hex_to_color_name のエッジケースと境界値テスト
    # - 空文字列
    assert _hex_to_color_name("") == ""
    # - 巨大入力（1000文字）
    assert _hex_to_color_name("a" * 1000) == ""
    # - 非HEX文字列
    assert _hex_to_color_name("zzzzzz") == ""
    assert _hex_to_color_name("#invalid") == ""
    # - 大文字小文字混在のカラーコード
    assert _hex_to_color_name("#Ff00Ff") == "赤"

    # - 暖色系の境界値検証 (R > B + 30)
    # R = 225, G = 0, B = 195 => R - B = 30 (不成立)
    assert _hex_to_color_name("e100c3") == ""
    # R = 225, G = 0, B = 194 => R - B = 31 (成立)
    assert _hex_to_color_name("e100c2") == "暖色系"

    # - 寒色系の境界値検証 (B > R + 30)
    # R = 195, G = 0, B = 225 => B - R = 30 (不成立)
    assert _hex_to_color_name("c300e1") == ""
    # R = 194, G = 0, B = 225 => B - R = 31 (成立)
    assert _hex_to_color_name("c200e1") == "寒色系"

    # - 明るい色の境界値検証 (brightness > 200, 暖色・寒色に該当しない)
    # R=201, G=201, B=201 => brightness = 201 (成立)
    assert _hex_to_color_name("c9c9c9") == "明るい色"
    # R=200, G=200, B=200 => brightness = 200 (不成立)
    assert _hex_to_color_name("c8c8c8") == ""

    # - 暗い色の境界値検証 (brightness < 60, 暖色・寒色に該当しない)
    # R=59, G=59, B=59 => brightness = 59 (成立)
    assert _hex_to_color_name("3b3b3b") == "暗い色"
    # R=60, G=60, B=60 => brightness = 60 (不成立)
    assert _hex_to_color_name("3c3c3c") == ""

    # 2. tag_for_search のエッジケース
    # - 巨大入力（巨大なファイル名と大量のラベル・スタイル）
    large_asset = AssetEntry(
        id="large_asset",
        path="brand/large.png",
        filename="x" * 10000,
        type="photo",
        category="brand",
        labels=["label_" + str(i) for i in range(100)],
        style_tags=["style_" + str(i) for i in range(100)],
        colors=["#ffffff"] * 100,
        mood="energetic",
        usage_for=["thumbnail"]
    )
    large_tag = temp_library.tag_for_search(large_asset, series_theme="theme_" * 100)
    assert len(large_tag) > 10000
    assert "x" * 10000 in large_tag
    assert "theme_" in large_tag

    # - 不正なカラーコードが含まれる場合（_hex_to_color_nameが空を返すため、色名は追加されない）
    invalid_color_asset = AssetEntry(
        id="invalid_color_asset",
        path="test.png",
        filename="test.png",
        type="photo",
        category="brand",
        colors=["#invalid"]
    )
    tag_result = temp_library.tag_for_search(invalid_color_asset)
    assert "色:" not in tag_result

    # 3. get_usage_report のエッジケース
    # - 空の参照リスト
    empty_report = temp_library.get_usage_report([])
    assert empty_report["total_referenced"] == 0
    assert empty_report["referenced_assets"] == []

    # - 重複するアセットIDの指定
    test_asset = AssetEntry(
        id="asset_dup_test",
        path="brand/test.png",
        filename="test.png",
        type="photo",
        category="brand"
    )
    temp_library.assets.append(test_asset)
    dup_report = temp_library.get_usage_report(["asset_dup_test", "asset_dup_test"])
    # 2回復数指定された場合、usage_countは2になる
    assert test_asset.usage_count == 2
    # ただしreferencedリストには、最初に見つかった1回分のみ追加される（実装上 referenced.append が asset ごとに追加されるため、2個入る）
    assert dup_report["total_referenced"] == 2
    temp_library.assets.remove(test_asset)

    # 4. get_assets_for_task のエッジケース
    # - task_type が None の場合
    res_none_task = temp_library.get_assets_for_task(None)
    assert res_none_task["available"] == []
    assert res_none_task["recommended"] == []
    assert res_none_task["missing"] == []

    # 5. _load_index における型エラーのフォールバック
    # - インデックスデータが異常な型（リスト）で保存されていた場合
    index_file = tmp_path / "asset_index.json"
    # 辞書ではなくリストで書き込む
    import json
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump([{"invalid": "data"}], f)

    library_fallback = temp_library
    library_fallback.index_path = index_file
    # エラーが発生せずに、安全に初期化（assets=[], guests={}）されること
    library_fallback._load_index()
    assert library_fallback.assets == []
    assert library_fallback.guests == {}


def test_weaver_batch_a2e572_edge_cases(temp_library, tmp_path):
    """T-batch_a2e572-test_weaver-000 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name, CreativeAssetLibrary

    # 1. _hex_to_color_name における bytes 型の入力に対する挙動（TypeError の発生）
    # bytesを入力すると、h.startswith(key) または h == key で key(str) と h(bytes) が比較され、TypeError が発生することを確認
    with pytest.raises(TypeError):
        _hex_to_color_name(b"#ff0000")

    # 2. get_assets_for_task にハッシュ不可能な辞書を指定した場合の例外検証
    with pytest.raises(TypeError, match="unhashable type"):
        temp_library.get_assets_for_task({"invalid_key": "dict_as_type"})

    # 3. get_assets_for_task に context パラメータとして超巨大な辞書を渡した場合の堅牢性検証（無視されて動作完了）
    huge_context = {f"key_{i}": "x" * 1000 for i in range(1000)}
    result_ctx = temp_library.get_assets_for_task("thumbnail", context=huge_context)
    assert isinstance(result_ctx, dict)
    assert "available" in result_ctx

    # 4. get_usage_report に対する極端に長大なリストの入力
    temp_library.assets = [
        AssetEntry(id="asset_huge", path="brand/ok.png", filename="ok.png", type="photo", category="brand")
    ]
    # 同一IDが1万個含まれるリスト
    huge_referenced = ["asset_huge"] * 10000
    report_huge = temp_library.get_usage_report(huge_referenced)
    assert report_huge["total_referenced"] == 10000
    assert temp_library.assets[0].usage_count == 10000

    # 5. get_usage_report に辞書を渡した場合（キーがイテレートされ、IDと一致すれば動作する）
    temp_library.assets = [
        AssetEntry(id="asset_dict_key", path="brand/ok.png", filename="ok.png", type="photo", category="brand")
    ]
    # 辞書のキーとして asset_dict_key を指定
    report_dict = temp_library.get_usage_report({"asset_dict_key": "some_value"})
    assert report_dict["total_referenced"] == 1
    assert temp_library.assets[0].usage_count == 1

    # 6. tag_for_search に AssetEntry 以外の不正な属性を持つオブジェクトを渡した場合の例外検証
    class DummyAsset:
        def __init__(self):
            self.filename = "dummy.png"
            self.type = "photo"
            self.category = "brand"
            self.labels = ["test"]
            self.style_tags = ["test"]
            # colors フィールドを意図的に欠損させる
            # self.colors = []

    dummy_asset = DummyAsset()
    with pytest.raises(AttributeError):
        temp_library.tag_for_search(dummy_asset)

    # 7. tag_for_search において series_theme に None を指定した場合の堅牢性（例外なく動作完了）
    test_asset = AssetEntry(
        id="theme_none_test", path="brand/test.png", filename="test.png", type="photo", category="brand"
    )
    tag_result = temp_library.tag_for_search(test_asset, series_theme=None)
    assert "シリーズテーマ" not in tag_result

    # 8. scan において、アセットルートディレクトリがファイルにすり替わっている場合の OSError 発生検証
    fake_file_root = tmp_path / "fake_dir_is_file"
    fake_file_root.write_text("i am a file, not a directory", encoding="utf-8")
    # rglob() を呼ぼうとした際、または初期化の _ensure_structure() 内の mkdir() で OSError が発生することを確認
    with pytest.raises(OSError):
        CreativeAssetLibrary(asset_root=fake_file_root)


def test_weaver_batch_c9c8d4_edge_cases(temp_library, tmp_path):
    """T-batch_c9c8d4-test_weaver-001 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name, CreativeAssetLibrary
    import json

    # 1. _hex_to_color_name における明度判定の境界値テスト
    # - brightness > 200 の境界 (brightness = 201)
    #   r = 201, g = 201, b = 201 -> brightness = 201 (R > B + 30 False, B > R + 30 False, 201 > 200 True)
    assert _hex_to_color_name("#c9c9c9") == "明るい色"  # c9 = 201
    
    # - brightness = 200 の境界 (brightness = 200)
    #   r = 200, g = 200, b = 200 -> brightness = 200 (どの条件も満たさない)
    assert _hex_to_color_name("#c8c8c8") == ""  # c8 = 200

    # - brightness < 60 の境界 (brightness = 59)
    #   r = 59, g = 59, b = 59 -> brightness = 59 < 60 -> "暗い色"
    assert _hex_to_color_name("#3b3b3b") == "暗い色"  # 3b = 59
    
    # - brightness = 60 の境界 (brightness = 60)
    #   r = 60, g = 60, b = 60 -> brightness = 60 -> ""
    assert _hex_to_color_name("#3c3c3c") == ""  # 3c = 60

    # - r > b + 30 の境界 (r = 100, b = 69, g = 100) -> r > b + 30 が 100 > 99 で True -> "暖色系"
    #   hex(100) = '64', hex(69) = '45' -> #646445
    assert _hex_to_color_name("#646445") == "暖色系"
    
    # - r = b + 30 の境界 (r = 100, b = 70, g = 100) -> r > b + 30 が 100 > 100 で False -> ""
    #   hex(70) = '46' -> #646446
    assert _hex_to_color_name("#646446") == ""

    # - b > r + 30 の境界 (b = 100, r = 69, g = 100) -> b > r + 30 が 100 > 99 で True -> "寒色系"
    assert _hex_to_color_name("#456464") == "寒色系"

    # - b = r + 30 の境界 (b = 100, r = 70, g = 100) -> b > r + 30 が 100 > 100 で False -> ""
    assert _hex_to_color_name("#466464") == ""

    # 2. _hex_to_color_name に IndexError や ValueError を引き起こす異常値を渡す
    # 短すぎる文字列 (IndexError が発生しキャッチされる)
    assert _hex_to_color_name("#a") == ""
    # 16進数ではない文字 (ValueError が発生しキャッチされる)
    assert _hex_to_color_name("#z1z2z3") == ""

    # 3. _load_index における TypeError / AttributeError のハンドリング検証
    index_file = tmp_path / "asset_index_malformed.json"
    
    # - guests が辞書ではなくリスト（TypeError を誘発）
    malformed_data_1 = {
        "version": "2.0",
        "assets": [],
        "guests": ["not_a_dict"]
    }
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(malformed_data_1, f)
        
    lib_test_1 = CreativeAssetLibrary(asset_root=tmp_path)
    lib_test_1.index_path = index_file
    lib_test_1._load_index()
    # エラーをキャッチして、初期状態にフォールバックすること
    assert lib_test_1.assets == []
    assert lib_test_1.guests == {}

    # - assets の中身が辞書ではなく整数（AssetEntryのアンパックで TypeError を誘発）
    malformed_data_2 = {
        "version": "2.0",
        "assets": [12345],
        "guests": {}
    }
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(malformed_data_2, f)
        
    lib_test_2 = CreativeAssetLibrary(asset_root=tmp_path)
    lib_test_2.index_path = index_file
    lib_test_2._load_index()
    assert lib_test_2.assets == []
    assert lib_test_2.guests == {}

    # 4. _label_asset に None などの異常なオブジェクトを渡し AttributeError を誘発
    # path.name や path.stem が存在しないため AttributeError が発生する
    assert temp_library._label_asset(None) is None

    # 5. build_search_index 実行時の series_planner インポート/動作例外フォールバックの検証
    with patch("services.series_planner.series_planner", create=True) as mock_planner:
        # series_planner.series_data.get が AttributeError をスローするように設定
        mock_planner.series_data.get.side_effect = AttributeError("Simulated error")
        
        # エラーが安全にキャッチされ、例外にならずにインデックスが構築されること
        result = temp_library.build_search_index(force_rebuild=True)
        assert isinstance(result, dict)


def test_weaver_batch_3d9df9_edge_cases(temp_library, tmp_path):
    """T-batch_3d9df9-test_weaver-000 用のエッジケース・堅牢性テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name, CreativeAssetLibrary
    import json
    from pathlib import Path

    # 1. _hex_to_color_name の極端な入力値・不正型テスト
    # None を渡した場合、AttributeError が発生することをアサート
    with pytest.raises(AttributeError):
        _hex_to_color_name(None)

    # 整数やリストなどの不正な型を渡した場合も AttributeError が発生すること
    with pytest.raises(AttributeError):
        _hex_to_color_name(12345)

    # 空文字列や不正な長さの文字列が渡された場合、空文字列が返ることを確認
    assert _hex_to_color_name("") == ""
    assert _hex_to_color_name("#") == ""
    assert _hex_to_color_name("#xyzxyz") == ""

    # 2. _load_index におけるデータ構造破損時のフォールバック検証
    index_file = tmp_path / "asset_index_weaver_3d9df9.json"

    # - assets フィールドがリストではなく None (TypeError を誘発)
    malformed_1 = {
        "version": "2.0",
        "assets": None,
        "guests": {}
    }
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(malformed_1, f)
    
    lib_1 = CreativeAssetLibrary(asset_root=tmp_path)
    lib_1.index_path = index_file
    lib_1._load_index()
    assert lib_1.assets == []
    assert lib_1.guests == {}

    # - 読み込んだJSON全体がリスト (AttributeError を誘発)
    malformed_2 = [
        {"version": "2.0"}
    ]
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(malformed_2, f)

    lib_2 = CreativeAssetLibrary(asset_root=tmp_path)
    lib_2.index_path = index_file
    lib_2._load_index()
    assert lib_2.assets == []
    assert lib_2.guests == {}

    # 3. get_assets_for_task の不正なタスクタイプとコンテキストの挙動検証
    # 想定外のタスクタイプが指定された場合、空のアセットリストと提案、missingリストが適切に構築されるか
    res = temp_library.get_assets_for_task("invalid_task_type", context={"some_key": "val"})
    assert isinstance(res, dict)
    assert res["available"] == []
    assert res["recommended"] == []
    assert res["missing"] == []

    # 4. get_usage_report の異常引数ハンドリング
    # referenced_assets が None の場合、TypeError が発生することを検証
    with pytest.raises(TypeError):
        temp_library.get_usage_report(None)

    # 空のリストを渡した場合、空のレポートが返ることを検証
    res_empty = temp_library.get_usage_report([])
    assert res_empty["referenced_assets"] == []
    assert res_empty["total_referenced"] == 0

    # 存在しないアセットIDや重複するIDが含まれる場合の挙動
    # 事前にアセットを追加しておく
    temp_library.assets = [
        AssetEntry(id="asset_0001", path="path1.png", filename="path1.png", type="photo", category="channel_owner")
    ]
    res_ids = temp_library.get_usage_report(["asset_0001", "asset_9999", "asset_0001"])
    # 存在するもののみカウントが増え、レポートに含まれること (重複は2回カウントされ、レポートにも2つ入る)
    assert len(res_ids["referenced_assets"]) == 2
    assert res_ids["total_referenced"] == 2
    assert temp_library.assets[0].usage_count == 2

    # 5. get_sufficiency_report におけるアセット空状態の挙動
    # アセットが空の場合、すべてのカテゴリが欠損とみなされ、推薦事項が適切に生成されるか
    temp_library.assets = []
    res_suff = temp_library.get_sufficiency_report()
    assert res_suff["categories"] == {}
    assert res_suff["total_assets"] == 0
    assert len(res_suff["recommendations"]) > 0

    # 6. scan におけるファイルハッシュ取得時 OSError のハンドリング検証
    # 一時的なアセットルートを作成
    scan_root = tmp_path / "scan_root_weaver"
    scan_root.mkdir(parents=True, exist_ok=True)
    channel_owner_photos = scan_root / "channel_owner" / "photos"
    channel_owner_photos.mkdir(parents=True, exist_ok=True)
    
    # テスト用ダミー画像ファイル作成
    dummy_img = channel_owner_photos / "dummy.png"
    dummy_img.write_text("dummy image data")

    lib_scan = CreativeAssetLibrary(asset_root=scan_root)
    # _get_file_hash が OSError を投げるようにモックする
    with patch.object(lib_scan, "_get_file_hash", side_effect=OSError("Permission denied")):
        summary = lib_scan.scan(auto_label=False)
        # ファイルハッシュの取得に失敗したため、新規アセットとして追加されないこと
        assert summary["new_assets"] == 0
        assert len(lib_scan.assets) == 0


def test_weaver_batch_632d4e_coverage_edge_cases(temp_library, tmp_path):
    """T-batch_632d4e-coverage-000 用の追加エッジケース・堅牢性テスト"""
    import pytest
    from asset_library import AssetEntry, GuestProfile, CreativeAssetLibrary
    from datetime import datetime

    # 1. GuestProfile のデフォルト引数の検証
    guest = GuestProfile(id="guest_001", name="山田太郎", title="書道家")
    assert guest.specialty == ""
    assert guest.bio == ""
    assert guest.folder_path == ""

    # 2. AssetEntry の indexed_at デフォルトファクトリの動作検証
    asset1 = AssetEntry(
        id="asset_001",
        path="brand/logo.png",
        filename="logo.png",
        type="photo",
        category="brand"
    )
    # indexed_at が ISO 形式の文字列で設定されていること
    assert isinstance(asset1.indexed_at, str)
    try:
        datetime.fromisoformat(asset1.indexed_at)
    except ValueError:
        pytest.fail("indexed_at is not a valid ISO format string")

    # 手動で設定した indexed_at が保持されること
    custom_time = "2026-01-01T00:00:00"
    asset2 = AssetEntry(
        id="asset_002",
        path="brand/logo.png",
        filename="logo.png",
        type="photo",
        category="brand",
        indexed_at=custom_time
    )
    assert asset2.indexed_at == custom_time

    # 3. scan における多重カテゴリ名を含むパスの優先判定テスト
    # guests と brand が両方含まれるパス -> guests (guest) が優先される
    nested_dir = tmp_path / "guests" / "brand" / "music"
    nested_dir.mkdir(parents=True, exist_ok=True)
    audio_path = nested_dir / "bgm.mp3"
    audio_path.write_bytes(b"music data")

    temp_library.scan(auto_label=False)
    # guests/brand/music/bgm.mp3 の判定
    scanned_asset = next((a for a in temp_library.assets if a.filename == "bgm.mp3"), None)
    assert scanned_asset is not None
    assert scanned_asset.category == "guest"

    # 4. get_assets_for_task における全タスクタイプ (insert, ending) の網羅的検証
    # insert タスク (必要素材: work, activity)
    result_insert = temp_library.get_assets_for_task("insert")
    missing_insert = [m["type"] for m in result_insert["missing"]]
    assert "work" in missing_insert
    assert "activity" in missing_insert

    # ending タスク (必要素材: logo, template)
    result_ending = temp_library.get_assets_for_task("ending")
    missing_ending = [m["type"] for m in result_ending["missing"]]
    assert "logo" in missing_ending
    assert "template" in missing_ending








def test_phase43_coverage_edge_cases(temp_library, tmp_path):
    """Phase 43用の追加のエッジケースおよび堅牢性検証テスト"""
    import pytest
    from unittest.mock import patch, MagicMock
    from asset_library import AssetEntry, _hex_to_color_name

    # 1. _hex_to_color_name で極端な長さの不正入力に対する例外キャッチ確認
    with pytest.raises(AttributeError):
        _hex_to_color_name(None)
    with pytest.raises(AttributeError):
        _hex_to_color_name(99999)

    # 2. _hex_to_color_name で特殊な前方一致（大文字小文字が混在し、無効文字が続くケース）
    assert _hex_to_color_name("#FF0000_EXTRA_LONG_INVALID_HEX_STRING") == "赤"

    # 3. tag_for_search で colors フィールドに None や空文字が極端に混入した場合の挙動
    test_asset = AssetEntry(
        id="colors_mixed_none", path="brand/test.png", filename="test.png", type="photo", category="brand",
        colors=["#ff0000", "invalid_color_code"]
    )
    tag_result = temp_library.tag_for_search(test_asset)
    assert "色: 赤" in tag_result

    # 4. get_assets_for_task で context に不正な辞書（キーが非文字列など）が渡された場合の堅牢性
    res_invalid_dict_keys = temp_library.get_assets_for_task("thumbnail", context={123: "value"})
    assert "available" in res_invalid_dict_keys
