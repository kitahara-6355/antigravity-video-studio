import pytest
from pathlib import Path
from backend.ux_verification.snapshot import UXVerificationSnapshot, SnapshotStore

def test_snapshot_store_init_with_dir(tmp_path):
    test_dir = tmp_path / "custom_snapshots"
    store = SnapshotStore(snapshots_dir=test_dir)
    assert store.dir == test_dir
    assert test_dir.exists()

def test_snapshot_store_init_default():
    store = SnapshotStore()
    assert store.dir is not None
    assert store.dir.exists()

def test_snapshot_store_save_and_load(tmp_path):
    store = SnapshotStore(snapshots_dir=tmp_path)
    snapshot = UXVerificationSnapshot(
        version="v2.0.0",
        items=[
            {"id": "item1", "ux_story": "O-2", "layer": 1, "story_scene": "S1", "passed": True}
        ]
    )
    path = store.save(snapshot)
    assert path.exists()
    assert path.name == "v2.0.0.json"
    assert snapshot.timestamp != ""
    assert snapshot.total_items == 1
    assert snapshot.pass_items == 1
    loaded = store.load("v2.0.0")
    assert loaded is not None
    assert loaded.version == "v2.0.0"
    assert len(loaded.items) == 1
    assert loaded.items[0]["id"] == "item1"

def test_snapshot_store_load_nonexistent(tmp_path):
    store = SnapshotStore(snapshots_dir=tmp_path)
    loaded = store.load("nonexistent")
    assert loaded is None

def test_snapshot_store_load_latest_and_list_versions(tmp_path):
    store = SnapshotStore(snapshots_dir=tmp_path)
    assert store.load_latest() is None
    assert store.list_versions() == []
    snap1 = UXVerificationSnapshot(version="v1.0.0", items=[])
    snap2 = UXVerificationSnapshot(version="v1.1.0", items=[])
    snap3 = UXVerificationSnapshot(version="v1.0.5", items=[])
    store.save(snap1)
    store.save(snap2)
    store.save(snap3)
    versions = store.list_versions()
    assert versions == ["v1.0.0", "v1.0.5", "v1.1.0"]
    latest = store.load_latest()
    assert latest is not None
    assert latest.version == "v1.1.0"

def test_snapshot_store_version_ordering_semantic(tmp_path):
    store = SnapshotStore(snapshots_dir=tmp_path)
    snap1 = UXVerificationSnapshot(version="v1.0.2", items=[])
    snap2 = UXVerificationSnapshot(version="v1.0.10", items=[])
    snap3 = UXVerificationSnapshot(version="v2.0.0", items=[])
    snap4 = UXVerificationSnapshot(version="v10.0.0", items=[])
    store.save(snap1)
    store.save(snap2)
    store.save(snap3)
    store.save(snap4)
    versions = store.list_versions()
    assert versions == ["v1.0.2", "v1.0.10", "v2.0.0", "v10.0.0"]
    latest = store.load_latest()
    assert latest is not None
    assert latest.version == "v10.0.0"
