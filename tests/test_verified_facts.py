import sys

import json

import threading

from pathlib import Path

from datetime import datetime, timedelta

import pytest

from unittest.mock import patch



# backend パス追加

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))



from agents.memory.verified_facts import verified_facts_store, VerifiedFactsStore, VerifiedFact



def test_init_and_load(tmp_path):

    # 1. 空のインデックスのロード

    store = VerifiedFactsStore(tmp_path)

    assert len(store.facts) == 0



    # 2. 既存 of 正しいインデックスのロード

    index_file = tmp_path / "verified_facts_index.json"

    dummy_data = {

        "version": "1.0",

        "last_updated": datetime.now().isoformat(),

        "fact_count": 1,

        "facts": [

            {

                "fact_id": "vf_0001_9999",

                "category": "architecture",

                "content": "This is a fact.",

                "evidence": "Evidence 1",

                "created_at": "2026-05-21T00:00:00",

                "last_verified_at": "2026-05-21T00:00:00",

                "confidence": 1.0,

                "source": "manual",

                "tags": ["tag1"]

            }

        ]

    }

    with open(index_file, "w", encoding="utf-8") as f:

        json.dump(dummy_data, f)

    

    store2 = VerifiedFactsStore(tmp_path)

    assert len(store2.facts) == 1

    assert store2.facts[0].fact_id == "vf_0001_9999"

    assert store2.facts[0].content == "This is a fact."



    # 3. 壊れたインデックスによる例外ハンドリングのロード

    with open(index_file, "w", encoding="utf-8") as f:

        f.write("invalid json")

    

    store3 = VerifiedFactsStore(tmp_path)

    assert len(store3.facts) == 0





def test_add_fact(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 新規追加

    fact1 = store.add_fact(

        category="architecture",

        content="Antigravity uses Python.",

        evidence="Codebase check",

        source="manual",

        confidence=0.9,

        tags=["python", "lang"]

    )

    

    assert fact1.fact_id.startswith("vf_")

    assert fact1.category == "architecture"

    assert fact1.content == "Antigravity uses Python."

    assert fact1.evidence == "Codebase check"

    assert fact1.confidence == 0.9

    assert fact1.tags == ["python", "lang"]

    assert len(store.facts) == 1

    

    # 重複追加のスキップと更新

    fact2 = store.add_fact(

        category="architecture",

        content="Antigravity uses Python.",

        evidence="Another evidence",

        source="council",

        confidence=0.95,

        tags=["ignored"]

    )

    

    assert len(store.facts) == 1

    assert fact2.fact_id == fact1.fact_id

    assert fact2.confidence == 0.95





def test_get_facts_by_category(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    store.add_fact("architecture", "Fact 1", "Evidence")

    store.add_fact("lesson", "Fact 2", "Evidence")

    store.add_fact("architecture", "Fact 3", "Evidence")

    

    arch_facts = store.get_facts_by_category("architecture")

    assert len(arch_facts) == 2

    assert {f.content for f in arch_facts} == {"Fact 1", "Fact 3"}

    

    lesson_facts = store.get_facts_by_category("lesson")

    assert len(lesson_facts) == 1

    assert lesson_facts[0].content == "Fact 2"

    

    empty_facts = store.get_facts_by_category("preference")

    assert len(empty_facts) == 0





def test_update_fact(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    fact = store.add_fact("architecture", "Fact to update", "Evidence")

    

    # 正常更新

    updated = store.update_fact(fact.fact_id, content="Updated Fact", confidence=0.8)

    assert updated is not None

    assert updated.content == "Updated Fact"

    assert updated.confidence == 0.8

    

    # 存在しないIDの更新

    not_found = store.update_fact("invalid_id", content="No")

    assert not_found is None





def test_remove_fact(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    fact = store.add_fact("architecture", "Fact to delete", "Evidence")

    

    # 正常削除

    res = store.remove_fact(fact.fact_id)

    assert res is True

    assert len(store.facts) == 0

    

    # 存在しないIDの削除

    res2 = store.remove_fact("invalid_id")

    assert res2 is False





def test_get_facts_for_context(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 空の場合

    assert store.get_facts_for_context() == ""

    

    # 通常のコンテキスト

    f1 = store.add_fact("architecture", "Arch fact", "Evidence", confidence=0.9)

    f2 = store.add_fact("lesson", "Lesson fact", "Evidence", confidence=0.7)

    

    context = store.get_facts_for_context()

    assert "## 検証済みファクト（Verified Facts）" in context

    assert "✅ Arch fact" in context

    assert "⚠️ Lesson fact" in context

    

    # トークン制限のプルーニングを検証 (2つのファクトだと約30トークン程度になるため、max_tokens=28 で f2(0.7)が削除される)

    context_pruned = store.get_facts_for_context(max_tokens=28)

    assert "Arch fact" in context_pruned

    assert "Lesson fact" not in context_pruned





def test_get_contradictions(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 矛盾しない

    store.add_fact("architecture", "The system uses FastAPI for API.", "Evidence")

    store.add_fact("architecture", "The database is PostgreSQL for storing data.", "Evidence")

    

    assert len(store.get_contradictions()) == 0

    

    # 矛盾する

    store.add_fact("architecture", "The system uses Flask for API.", "Evidence")

    

    contradictions = store.get_contradictions()

    assert len(contradictions) == 1

    f1, f2 = contradictions[0]

    assert {f1.content, f2.content} == {"The system uses FastAPI for API.", "The system uses Flask for API."}





def test_prune_stale_facts(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 1. 最近のファクト

    f1 = store.add_fact("architecture", "Recent fact", "Evidence")

    

    # 2. 古いファクトを作成し、last_verified_atを直接上書きして保存する (update_factだとlast_verified_atが現在時刻に上書きされるため)

    f2 = store.add_fact("architecture", "Stale fact", "Evidence")

    past_date = (datetime.now() - timedelta(days=40)).isoformat()

    for fact in store.facts:

        if fact.fact_id == f2.fact_id:

            fact.last_verified_at = past_date

    store._save()

    

    # プルーニング実行

    removed = store.prune_stale_facts(max_age_days=30)

    assert removed == 1

    assert len(store.facts) == 1

    assert store.facts[0].content == "Recent fact"





def test_enforce_limits(tmp_path):

    import agents.memory.verified_facts

    

    # オリジナル値を保存

    orig_max_lines = agents.memory.verified_facts.MAX_LINES

    orig_max_size = agents.memory.verified_facts.MAX_SIZE_KB

    

    try:

        # テスト用に制限を小さくする

        agents.memory.verified_facts.MAX_LINES = 45

        store = VerifiedFactsStore(tmp_path)

        

        # 1つ目の高確信度ファクト

        store.add_fact("architecture", "Fact 1", "Evidence", confidence=1.0)

        # 2つ目の低確信度ファクト

        store.add_fact("architecture", "Fact 2", "Evidence", confidence=0.5)

        

        # 3つ目の長いファクトを追加して制限を超えるようにする

        long_content = "Line\n" * 15

        store.add_fact("architecture", long_content, "Evidence", confidence=0.8)

        

        contents = {f.content for f in store.facts}

        assert "Fact 2" not in contents

        assert "Fact 1" in contents

        

        # サイズ制限の検証

        agents.memory.verified_facts.MAX_LINES = 100

        agents.memory.verified_facts.MAX_SIZE_KB = 1.2

        

        store2 = VerifiedFactsStore(tmp_path)

        store2.add_fact("architecture", "Fact A", "Evidence", confidence=1.0)

        store2.add_fact("architecture", "Fact B", "Evidence", confidence=0.4)

        

        huge_content = "X" * 800

        store2.add_fact("architecture", huge_content, "Evidence", confidence=0.9)

        

        contents2 = {f.content for f in store2.facts}

        assert "Fact B" not in contents2

        assert "Fact A" in contents2

        

    finally:

        # 復元

        agents.memory.verified_facts.MAX_LINES = orig_max_lines

        agents.memory.verified_facts.MAX_SIZE_KB = orig_max_size





def test_save_exceptions(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    original_open = open

    def mock_open_err(file, mode="r", *args, **kwargs):

        if "verified_facts_index.json" in str(file) or "VERIFIED_FACTS.md" in str(file):

            raise IOError("Disk Full or Permission Denied")

        return original_open(file, mode, *args, **kwargs)

        

    with patch("builtins.open", side_effect=mock_open_err):

        fact = store.add_fact("architecture", "Exception test", "Evidence")

        assert fact is not None





def test_get_stats(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    store.add_fact("architecture", "Fact 1", "Evidence 1", confidence=1.0)

    store.add_fact("lesson", "Fact 2", "Evidence 2", confidence=0.8)

    

    stats = store.get_stats()

    assert stats["total_facts"] == 2

    assert stats["by_category"]["architecture"] == 1

    assert stats["by_category"]["lesson"] == 1

    assert stats["avg_confidence"] == 0.9

    assert stats["markdown_lines"] > 0

    assert stats["markdown_size_kb"] > 0

    assert stats["contradictions"] == 0





def test_render_markdown_details(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    store.add_fact(

        category="architecture",

        content="Multi-line evidence test",

        evidence="Line 1\nLine 2\r\nLine 3"

    )

    

    md = store._render_markdown()

    assert "Line 1 / Line 2 / Line 3" in md

    

    store.add_fact(

        category="progress",

        content="Finished tasks",

        evidence="CI Test Passed"

    )

    md2 = store._render_markdown()

    assert "## 📈 進捗" in md2

    assert "CI Test Passed" in md2





# ============================================================

# 新規追加テスト: 自己修復・回復性、競合制御の検証

# ============================================================



def test_atomic_save_fallback_on_failure(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    store.add_fact("architecture", "Test Fact", "Evidence")

    

    # 正常に保存されていることを確認

    assert (tmp_path / "verified_facts_index.json").exists()

    assert (tmp_path / "VERIFIED_FACTS.md").exists()

    

    # Path.replace() で例外を発生させ、アトミック書き込み失敗をシミュレート

    original_replace = Path.replace

    def mock_replace(self, target):

        if "verified_facts_index.json" in str(target):

            raise OSError("Simulated replace error")

        return original_replace(self, target)

        

    Path.replace = mock_replace

    try:

        # 内部でOSErrorが発生するが、add_fact の _save 内部でキャッチされるためクラッシュしない

        fact = store.add_fact("architecture", "Another Fact", "Evidence")

        assert fact is not None

    finally:

        Path.replace = original_replace

        

    # JSON保存は失敗したが、元の JSON ファイルが消えずに残っていることを確認

    with open(tmp_path / "verified_facts_index.json", "r", encoding="utf-8") as f:

        data = json.load(f)

    

    # 元の「Test Fact」は残っているはず

    assert len(data["facts"]) == 1

    assert data["facts"][0]["content"] == "Test Fact"





def test_restore_from_markdown_fallback(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    store.add_fact("architecture", "System architecture is microservices.", "Architecture doc")

    store.add_fact("progress", "Sprint 1 finished successfully.", "CI passed")

    

    # 保存されていることを確認

    assert (tmp_path / "verified_facts_index.json").exists()

    

    # JSONインデックスファイルを意図的に破損させる

    with open(tmp_path / "verified_facts_index.json", "w", encoding="utf-8") as f:

        f.write("{invalid json}")

        

    # 新規インスタンスを生成すると、JSON破損から Markdown を自動パースして自己修復・復元される

    new_store = VerifiedFactsStore(tmp_path)

    assert len(new_store.facts) == 2

    

    contents = {f.content for f in new_store.facts}

    assert "System architecture is microservices." in contents

    assert "Sprint 1 finished successfully." in contents

    

    # 根拠もパースされているか確認

    facts_map = {f.content: f for f in new_store.facts}

    assert facts_map["System architecture is microservices."].evidence == "Architecture doc"

    assert facts_map["Sprint 1 finished successfully."].evidence == "CI passed"

    

    # カテゴリも正しくマッピングされているか確認

    assert facts_map["System architecture is microservices."].category == "architecture"

    assert facts_map["Sprint 1 finished successfully."].category == "progress"





def test_concurrent_lock_access(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 並行して複数のスレッドから add_fact を実行し、競合やデッドロックが起きないことを確認

    errors = []

    def add_concurrently(idx):

        try:

            store.add_fact("architecture", f"Fact from thread {idx}", f"Thread {idx} proof")

        except Exception as e:

            errors.append(e)

            

    threads = []

    for i in range(10):

        t = threading.Thread(target=add_concurrently, args=(i,))

        threads.append(t)

        t.start()

        

    for t in threads:

        t.join()

        

    assert len(errors) == 0

    # 10個すべて競合することなく登録されているはず

    assert len(store.facts) == 10





# ============================================================

# 新規追加テスト: 未カバー行の完全網羅（カバレッジ 100% 目標）

# ============================================================



def test_lock_errors(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    

    # 1. mkdir が OSError を投げた場合

    original_mkdir = Path.mkdir

    def mock_mkdir(self, *args, **kwargs):

        raise OSError("Simulated mkdir error")

    

    Path.mkdir = mock_mkdir

    try:

        with patch("time.sleep") as mock_sleep:

            # _lock の中で timeout になり、locked = False で処理が続行される

            with store._lock(timeout_secs=0.1, check_interval=0.01):

                pass

            assert mock_sleep.called

    finally:

        Path.mkdir = original_mkdir



    # 2. rmdir が OSError を投げた場合

    original_rmdir = Path.rmdir

    def mock_rmdir(self, *args, **kwargs):

        raise OSError("Simulated rmdir error")

    

    Path.rmdir = mock_rmdir

    try:

        try:

            with store._lock():

                pass

        except Exception:

            pytest.fail("rmdir exception should be caught inside _lock.__exit__")

    finally:

        Path.rmdir = original_rmdir



def test_pruning_logic_strict(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    store.add_fact("architecture", "Arch fact", "Evidence", confidence=0.9)

    store.add_fact("lesson", "Lesson fact", "Evidence", confidence=0.7)

    

    # max_tokens を調整して、confidenceの低い方がプルーニングされることを検証

    context = store.get_facts_for_context(max_tokens=25)

    assert "Arch fact" in context

    assert "Lesson fact" not in context



def test_save_atomic_unlink_failure(tmp_path):

    store = VerifiedFactsStore(tmp_path)

    original_replace = Path.replace

    original_unlink = Path.unlink

    

    def mock_replace(self, target):

        raise OSError("Simulated replace error")

        

    def mock_unlink(self):

        raise OSError("Simulated unlink error")

        

    Path.replace = mock_replace

    Path.unlink = mock_unlink

    try:

        with pytest.raises(OSError, match="Simulated replace error"):

            store._save_atomic(tmp_path / "test.json", "content")

    finally:

        Path.replace = original_replace

        Path.unlink = original_unlink



def test_restore_from_markdown_error(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    # ファイルを作成しておくことで、exists() チェックを通過させる
    facts_file = tmp_path / "VERIFIED_FACTS.md"
    facts_file.touch()
    
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if "VERIFIED_FACTS.md" in str(file) and "r" in mode:
            raise OSError("Simulated open error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("agents.memory.verified_facts.open", side_effect=mock_open):
        res = store._restore_from_markdown()
        assert res is False

def test_load_without_lock_json_read_error(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    store.add_fact("architecture", "Arch Fact", "Evidence")
    
    original_open = open
    def mock_open(file, mode="r", *args, **kwargs):
        if "verified_facts_index.json" in str(file) and "r" in mode:
            raise OSError("Simulated index read error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("agents.memory.verified_facts.open", side_effect=mock_open):
        store._load_without_lock()
        assert len(store.facts) == 1
        assert store.facts[0].content == "Arch Fact"

def test_load_without_lock_save_after_restore_fail(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    store.add_fact("architecture", "Arch Fact", "Evidence")
    
    with open(tmp_path / "verified_facts_index.json", "w", encoding="utf-8") as f:
        f.write("{invalid json}")
        
    def mock_save_fail(*args, **kwargs):
        raise OSError("Simulated save error")
        
    with patch.object(VerifiedFactsStore, "_save_without_lock", side_effect=mock_save_fail):
        store._load_without_lock()
        assert len(store.facts) == 1
        assert store.facts[0].content == "Arch Fact"

def test_restore_from_markdown_english_categories(tmp_path):
    md_content = """# Verified Facts
## architecture
- **[95%]** English Architecture Fact
  - 根拠: Doc 1

## progress
- **[100%]** English Progress Fact
  - 根拠: Doc 2
"""
    store = VerifiedFactsStore(tmp_path)
    with open(tmp_path / "VERIFIED_FACTS.md", "w", encoding="utf-8") as f:
        f.write(md_content)
        
    res = store._restore_from_markdown()
    assert res is True
    assert len(store.facts) == 2
    
    facts_map = {f.content: f for f in store.facts}
    assert "English Architecture Fact" in facts_map
    assert "English Progress Fact" in facts_map
    assert facts_map["English Architecture Fact"].category == "architecture"
    assert facts_map["English Progress Fact"].category == "progress"

def test_restore_from_markdown_no_facts(tmp_path):
    md_content = """# Verified Facts
## architecture
No facts here
"""
    store = VerifiedFactsStore(tmp_path)
    with open(tmp_path / "VERIFIED_FACTS.md", "w", encoding="utf-8") as f:
        f.write(md_content)
        
    res = store._restore_from_markdown()
    assert res is False

def test_explicit_load(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    store.add_fact("architecture", "Load test fact", "Evidence")
    
    store2 = VerifiedFactsStore(tmp_path)
    store2.facts = []
    
    store2._load()
    assert len(store2.facts) == 1
    assert store2.facts[0].content == "Load test fact"

def test_restore_from_markdown_unknown_categories(tmp_path):
    # 未知のカテゴリを含むMarkdown
    md_content = """# Verified Facts
## custom_category
- **[80%]** Custom category fact
  - 根拠: Custom evidence

## architecture
- **[90%]** Arch fact
  - 根拠: Arch evidence
"""
    store = VerifiedFactsStore(tmp_path)
    with open(tmp_path / "VERIFIED_FACTS.md", "w", encoding="utf-8") as f:
        f.write(md_content)
        
    res = store._restore_from_markdown()
    assert res is True
    assert len(store.facts) == 2
    
    facts_map = {f.content: f for f in store.facts}
    assert "Custom category fact" in facts_map
    assert "Arch fact" in facts_map
    assert facts_map["Custom category fact"].category == "custom_category"
    assert facts_map["Arch fact"].category == "architecture"

    # レンダリング結果で、定義済みカテゴリ(architecture)が先、未知のカテゴリが末尾に来ることを検証
    md_rendered = store._render_markdown()
    assert "## 🏗️ アーキテクチャ" in md_rendered
    assert "## custom_category" in md_rendered
    # architectureの表示位置がcustom_categoryより前であることを確認
    assert md_rendered.index("## 🏗️ アーキテクチャ") < md_rendered.index("## custom_category")


def test_save_without_lock_partial_failure(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    store.add_fact("architecture", "Baseline fact", "Evidence")
    
    original_open = open
    
    # index_path への保存のみ失敗させる
    def mock_open_index_fail(file, mode="r", *args, **kwargs):
        if "verified_facts_index.json" in str(file) and "w" in mode:
            raise OSError("JSON write error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("agents.memory.verified_facts.open", side_effect=mock_open_index_fail):
        # JSON保存でOSErrorが発生するが、内部でキャッチされ、Markdownの保存処理は動くはず
        store._save_without_lock()
        
    # Markdownが正常に更新されたか（または維持されたか）
    assert (tmp_path / "VERIFIED_FACTS.md").exists()
    
    # 逆パターン: Markdown保存のみ失敗させる
    def mock_open_md_fail(file, mode="r", *args, **kwargs):
        if "VERIFIED_FACTS.md" in str(file) and "w" in mode:
            raise OSError("Markdown write error")
        return original_open(file, mode, *args, **kwargs)
        
    with patch("agents.memory.verified_facts.open", side_effect=mock_open_md_fail):
        store._save_without_lock()
        
    # JSONが正常に維持されているか
    assert (tmp_path / "verified_facts_index.json").exists()


def test_load_backward_compatibility(tmp_path):
    # 旧形式のJSON（confidence, source, tagsがない）
    dummy_data = {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "fact_count": 1,
        "facts": [
            {
                "fact_id": "vf_0001_9999",
                "category": "architecture",
                "content": "Legacy Fact content.",
                "evidence": "Legacy Evidence",
                "created_at": "2026-05-21T00:00:00",
                "last_verified_at": "2026-05-21T00:00:00"
            }
        ]
    }
    index_file = tmp_path / "verified_facts_index.json"
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(dummy_data, f)
        
    store = VerifiedFactsStore(tmp_path)
    assert len(store.facts) == 1
    fact = store.facts[0]
    assert fact.content == "Legacy Fact content."
    # デフォルト値で補完されていること
    assert fact.confidence == 1.0
    assert fact.source == ""
    assert fact.tags == []


def test_lock_timeout_simulation(tmp_path):
    store = VerifiedFactsStore(tmp_path)
    
    # 既にロックディレクトリが存在する状態を作る
    lock_dir = tmp_path / "verified_facts.lock"
    lock_dir.mkdir(exist_ok=False)
    
    try:
        executed = False
        # 非常に短いタイムアウトでロック取得を試みる
        # タイムアウトするが、警告ログを出してそのまま処理が実行される
        with store._lock(timeout_secs=0.05, check_interval=0.01):
            # ロックが取れなくてもブロック内部は実行される
            executed = True
            
        assert executed is True
    finally:
        # 後片付け
        if lock_dir.exists():
            lock_dir.rmdir()
