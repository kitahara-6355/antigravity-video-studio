import pytest
import json
from pathlib import Path
from datetime import datetime
from backend.ux_verification.snapshot import (
    VerificationItem,
    UXVerificationSnapshot,
    SnapshotStore
)

def test_verification_item():
    """VerificationItem の初期化とプロパティの動作検証"""
    item = VerificationItem(
        id="O2-L1-01",
        ux_story="O-2",
        layer=1,
        description="Whisperモデルセレクトボックスが存在する",
        story_scene="S1",
        test_method="dom_exists",
        passed=True,
        evidence="Found element"
    )
    assert item.id == "O2-L1-01"
    assert item.ux_story == "O-2"
    assert item.layer == 1
    assert item.description == "Whisperモデルセレクトボックスが存在する"
    assert item.story_scene == "S1"
    assert item.test_method == "dom_exists"
    assert item.passed is True
    assert item.evidence == "Found element"


def test_snapshot_compute_aggregates_empty():
    """UXVerificationSnapshot.compute_aggregates の空リスト時の挙動検証（ゼロ除算回避など）"""
    snapshot = UXVerificationSnapshot(version="v1.0.0", items=[])
    snapshot.compute_aggregates()
    
    assert snapshot.total_items == 0
    assert snapshot.pass_items == 0
    assert snapshot.fail_items == 0
    assert snapshot.skip_items == 0
    assert snapshot.fulfillment_rate == 0.0
    assert snapshot.correlation_rate == 0.0
    assert snapshot.story_scenes_total == 0
    assert snapshot.story_scenes_covered == 0
    assert snapshot.items_per_story == {}
    assert snapshot.pass_per_story == {}
    assert snapshot.layer_distribution == {}


def test_snapshot_compute_aggregates_mixed():
    """UXVerificationSnapshot.compute_aggregates の多様な items に対する集計ロジック検証"""
    items = [
        # O-2 Story
        {
            "id": "O2-L1-01",
            "ux_story": "O-2",
            "layer": 1,
            "description": "Item 1",
            "story_scene": "S1",
            "test_method": "dom_exists",
            "passed": True,
            "evidence": "OK"
        },
        {
            "id": "O2-L1-02",
            "ux_story": "O-2",
            "layer": 2,
            "description": "Item 2",
            "story_scene": "S1", # 同一ストーリーの同一シーン
            "test_method": "visual_check",
            "passed": False,
            "evidence": "NG"
        },
        # O-3 Story
        {
            "id": "O3-L3-01",
            "ux_story": "O-3",
            "layer": 3,
            "description": "Item 3",
            "story_scene": "S2",
            "test_method": "interaction",
            "passed": None, # Skip
            "evidence": ""
        },
        {
            "id": "O3-L4-01",
            "ux_story": "O-3",
            "layer": 4,
            "description": "Item 4",
            "story_scene": "", # 連動なし（story_scene 空）
            "test_method": "e2e",
            "passed": True,
            "evidence": "OK"
        }
    ]

    snapshot = UXVerificationSnapshot(version="v1.0.0", items=items)
    snapshot.compute_aggregates()

    assert snapshot.total_items == 4
    assert snapshot.pass_items == 2 # 1番目と4番目
    assert snapshot.fail_items == 1 # 2番目
    assert snapshot.skip_items == 1 # 3番目

    # fulfillment_rate: 2 / 4 * 100 = 50.0
    assert snapshot.fulfillment_rate == 50.0

    # correlation_rate: story_scene が存在する項目は 1, 2, 3 の計3つ。 3 / 4 * 100 = 75.0
    assert snapshot.correlation_rate == 75.0

    # items_per_story
    assert snapshot.items_per_story == {"O-2": 2, "O-3": 2}
    
    # pass_per_story
    assert snapshot.pass_per_story == {"O-2": 1, "O-3": 1}

    # layer_distribution (L1: 1, L2: 1, L3: 1, L4: 1)
    assert snapshot.layer_distribution == {"L1": 1, "L2": 1, "L3": 1, "L4": 1}

    # story_scenes_total & story_scenes_covered
    # 全シーンキー: "O-2:S1", "O-3:S2" の2つ。
    # カバーされたシーン（passed=True が含まれるシーン）: "O-2:S1" (O2-L1-01がTrue) のみ。（"O-3:S2" は passed=None、4番目はsceneが空なので除外）
    # よって total=2, covered=1
    assert snapshot.story_scenes_total == 2
    assert snapshot.story_scenes_covered == 1


def test_snapshot_store_default_dir():
    """SnapshotStore を引数なしで初期化した際のデフォルトディレクトリ挙動検証"""
    store = SnapshotStore()
    assert store.dir.name == "snapshots"
    assert store.dir.exists()


def test_snapshot_store_save_and_load(tmp_path):
    """SnapshotStore の save と load メソッドの正常系とエッジケースの検証"""
    store = SnapshotStore(snapshots_dir=tmp_path)
    
    # テスト用スナップショット作成 (timestamp は意図的に空にして自動設定を検証)
    snapshot = UXVerificationSnapshot(
        version="v9.9.9",
        items=[
            {
                "id": "T1",
                "ux_story": "O-1",
                "layer": 1,
                "description": "Test",
                "story_scene": "S1",
                "test_method": "dom_exists",
                "passed": True
            }
        ]
    )
    
    # 保存
    save_path = store.save(snapshot)
    
    assert save_path.exists()
    assert save_path.name == "v9.9.9.json"
    assert snapshot.timestamp != "" # 自動でタイムスタンプが設定されていること
    
    # 再ロード
    loaded = store.load("v9.9.9")
    assert loaded is not None
    assert loaded.version == "v9.9.9"
    assert loaded.timestamp == snapshot.timestamp
    assert len(loaded.items) == 1
    assert loaded.items[0]["id"] == "T1"
    assert loaded.total_items == 1
    assert loaded.pass_items == 1
    
    # 存在しないバージョンのロード
    assert store.load("v0.0.0-non-existent") is None


def test_snapshot_store_load_with_extra_fields(tmp_path):
    """保存されたJSONにdataclass外の余剰フィールドが含まれる場合のロード検証"""
    store = SnapshotStore(snapshots_dir=tmp_path)
    
    raw_data = {
        "version": "v1.0.0-extra",
        "timestamp": "2026-05-25T12:00:00",
        "items": [],
        "extra_unsupported_field": "some_value" # dataclassにないフィールド
    }
    
    file_path = tmp_path / "v1.0.0-extra.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f)
        
    loaded = store.load("v1.0.0-extra")
    assert loaded is not None
    assert loaded.version == "v1.0.0-extra"
    # dataclass にマッピングされているが、余計な属性は持たないこと
    assert not hasattr(loaded, "extra_unsupported_field")


def test_snapshot_store_load_latest(tmp_path):
    """SnapshotStore.load_latest の挙動検証"""
    store = SnapshotStore(snapshots_dir=tmp_path)
    
    # スナップショットが存在しない場合
    assert store.load_latest() is None
    
    # 複数スナップショットの保存
    snap_v1 = UXVerificationSnapshot(version="v1.0.0", items=[])
    snap_v2 = UXVerificationSnapshot(version="v2.0.0", items=[])
    snap_v1_1 = UXVerificationSnapshot(version="v1.1.0", items=[])
    
    store.save(snap_v1)
    store.save(snap_v2)
    store.save(snap_v1_1)
    
    # 最新（v2.0.0.json が glob でソートしたときに末尾になるはず）
    latest = store.load_latest()
    assert latest is not None
    assert latest.version == "v2.0.0"


def test_snapshot_store_list_versions(tmp_path):
    """SnapshotStore.list_versions の挙動検証"""
    store = SnapshotStore(snapshots_dir=tmp_path)
    
    # 空の場合
    assert store.list_versions() == []
    
    # 複数の json を配置
    snap_v1 = UXVerificationSnapshot(version="v1.0.0", items=[])
    snap_v2 = UXVerificationSnapshot(version="v2.0.0", items=[])
    store.save(snap_v1)
    store.save(snap_v2)
    
    # 無関係なファイルやパターン外のファイルを配置して無視されるか検証
    (tmp_path / "other_file.json").write_text("{}", encoding="utf-8")
    (tmp_path / "v1.0.0.txt").write_text("text", encoding="utf-8")
    
    versions = store.list_versions()
    assert versions == ["v1.0.0", "v2.0.0"]


def test_snapshot_items_class_conversion_and_dict_compatibility():
    """UXVerificationSnapshot.items が VerificationItem インスタンスに変換され、辞書互換アクセスができることの検証"""
    # 辞書のリストで初期化
    snapshot = UXVerificationSnapshot(
        version="v1.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "passed": True},
            {"id": "item2", "ux_story": "O-3", "layer": None, "passed": False} # layerがNoneのエッジケース
        ]
    )
    
    # VerificationItem インスタンスになっていることの検証
    assert len(snapshot.items) == 2
    assert isinstance(snapshot.items[0], VerificationItem)
    assert isinstance(snapshot.items[1], VerificationItem)
    
    # 属性アクセスの検証
    assert snapshot.items[0].id == "item1"
    assert snapshot.items[0].layer == 1
    assert snapshot.items[1].layer == 0  # None が 0 に補完されていること
    
    # 辞書風アクセスの検証
    assert snapshot.items[0].get("id") == "item1"
    assert snapshot.items[0]["id"] == "item1"
    assert "id" in snapshot.items[0]
    
    # compute_aggregates を走らせて LNone が発生せず L0 になることの検証
    snapshot.compute_aggregates()
    assert snapshot.layer_distribution == {"L1": 1, "L0": 1}


def test_snapshot_store_version_ordering_semantic(tmp_path):
    """バージョンソートが辞書順ではなくセマンティックバージョン順に行われるかの検証"""
    store = SnapshotStore(snapshots_dir=tmp_path)
    
    snap1 = UXVerificationSnapshot(version="v1.0.2", items=[])
    snap2 = UXVerificationSnapshot(version="v1.0.10", items=[])
    snap3 = UXVerificationSnapshot(version="v2.0.0", items=[])
    snap4 = UXVerificationSnapshot(version="v10.0.0", items=[])
    
    store.save(snap1)
    store.save(snap2)
    store.save(snap3)
    store.save(snap4)
    
    # バージョン一覧がセマンティック順になっていること
    versions = store.list_versions()
    assert versions == ["v1.0.2", "v1.0.10", "v2.0.0", "v10.0.0"]
    
    # 最新が v10.0.0 であること
    latest = store.load_latest()
    assert latest is not None
    assert latest.version == "v10.0.0"
