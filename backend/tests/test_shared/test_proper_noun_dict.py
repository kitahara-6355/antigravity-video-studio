import json
import pytest
from pathlib import Path
import tempfile
import os
from proper_noun_dict import ProperNounDictionary, DictionaryEntry, PendingConfirmation, apply_dictionary, add_proper_noun

def test_proper_noun_dict_lifecycle():
    dict_path = Path(tempfile.mktemp(suffix='.json'))
    assert not dict_path.exists()
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert dict_path.exists()
        assert pnd.auto_learn is True
        assert pnd.learning_threshold == 3
        assert len(pnd.entries) == 0
        assert len(pnd.pending) == 0
        entry = pnd.add_entry('aaa', 'bbb', 'word', 'hint', True)
        assert len(pnd.entries) == 1
        assert entry.incorrect == 'aaa'
        assert entry.correct == 'bbb'
        pnd2 = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd2.entries) == 1
        assert pnd2.entries[0].incorrect == 'aaa'
        text = 'aaa'
        corrected, corrections = pnd2.apply_corrections(text)
        assert corrected == 'bbb'
        assert len(corrections) == 1
        assert corrections[0]['original'] == 'aaa'
        assert pnd2.entries[0].usage_count == 1
        pnd2.suggest_correction('ccc', 'ddd', 'context', 0.9)
        assert len(pnd2.pending) == 1
        assert pnd2.pending[0].occurrences == 1
        pnd2.suggest_correction('ccc', 'ddd', 'context', 0.9)
        assert len(pnd2.pending) == 1
        assert pnd2.pending[0].occurrences == 2
        pnd2.suggest_correction('ccc', 'ddd', 'context', 0.9)
        assert len(pnd2.pending) == 0
        assert len(pnd2.entries) == 2
        assert pnd2.entries[1].incorrect == 'ccc'
        assert pnd2.entries[1].correct == 'ddd'
        removed_id = pnd2.entries[1].id
        assert pnd2.remove_entry(removed_id) is True
        assert len(pnd2.entries) == 1
        assert pnd2.remove_entry('invalid_id') is False
        pnd2.suggest_correction('eee', 'fff', 'context', 0.8)
        assert len(pnd2.pending) == 1
        assert pnd2.confirm_pending('eee', True) is True
        assert len(pnd2.pending) == 0
        assert len(pnd2.entries) == 2
        assert pnd2.entries[1].incorrect == 'eee'
        pnd2.suggest_correction('ggg', 'hhh', 'context', 0.8)
        assert len(pnd2.pending) == 1
        assert pnd2.confirm_pending('ggg', False) is True
        assert len(pnd2.pending) == 0
        assert len(pnd2.entries) == 2
        assert pnd2.confirm_pending('nonexistent', True) is False
        all_entries = pnd2.get_all_entries()
        assert len(all_entries) == 2
        pending_list = pnd2.get_pending()
        assert len(pending_list) == 0
    finally:
        if dict_path.exists():
            os.unlink(dict_path)

def test_load_invalid_json():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write('{invalid json')
        dict_path = Path(f.name)
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd.entries) == 0
    finally:
        os.unlink(f.name)

def test_global_helpers(monkeypatch):
    from proper_noun_dict import proper_noun_dict
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write('{}')
        dict_path = Path(f.name)
    orig_path = proper_noun_dict.dict_path
    try:
        pnd = proper_noun_dict
        pnd.dict_path = dict_path
        pnd.entries = []
        pnd.pending = []
        res = add_proper_noun('iii', 'jjj', 'word')
        assert res['incorrect'] == 'iii'
        text, corrections = apply_dictionary('this is iii')
        assert text == 'this is jjj'
        assert len(corrections) == 1
    finally:
        pnd.dict_path = orig_path
        pnd._load()
        os.unlink(f.name)


def test_proper_noun_dict_branches():
    from pathlib import Path
    import tempfile
    from proper_noun_dict import ProperNounDictionary

    dict_path = Path(tempfile.mktemp(suffix='.json'))
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        
        # 1. apply_corrections の未カバー分岐 (110->109, 119->123)
        pnd.add_entry('aaa', 'bbb', 'word', 'hint', True)
        corrected, corrections = pnd.apply_corrections('ccc')
        assert corrected == 'ccc'
        assert len(corrections) == 0

        # 2. suggest_correction の未カバー分岐 (175->174)
        pnd.suggest_correction('eee', 'fff', 'context1', 0.8)
        assert len(pnd.pending) == 1
        pnd.suggest_correction('ggg', 'hhh', 'context2', 0.8)
        assert len(pnd.pending) == 2
        assert pnd.pending[0].incorrect == 'eee'
        assert pnd.pending[1].incorrect == 'ggg'

        # 3. confirm_pending の未カバー分岐 (185->184)
        assert pnd.confirm_pending('nonexistent', True) is False
        assert len(pnd.pending) == 2

        # 4. confirm_pendingで final_correct を明示的に指定して承認するケース
        assert pnd.confirm_pending('eee', True, 'final_eee') is True
        assert len(pnd.pending) == 1
        assert pnd.entries[-1].incorrect == 'eee'
        assert pnd.entries[-1].correct == 'final_eee'
        
        # 5. auto_learn=False の場合の suggest_correction
        pnd.auto_learn = False
        pnd.suggest_correction('ggg', 'hhh', 'context2', 0.8)
        pnd.suggest_correction('ggg', 'hhh', 'context2', 0.8)
        assert len(pnd.pending) == 1
        assert pnd.pending[0].incorrect == 'ggg'
        assert pnd.pending[0].occurrences == 3
        
    finally:
        if dict_path.exists():
            os.unlink(dict_path)


def test_proper_noun_dict_specific_exceptions():
    import json
    from proper_noun_dict import ProperNounDictionary
    
    # 1. 破損したJSONによる例外テスト
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write("{invalid json")
        dict_path = Path(f.name)
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd.entries) == 0
    finally:
        os.unlink(f.name)
        
    # 2. スキーマ不一致による例外テスト (TypeError)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        # entries の中に dict_path などの不正なキーや、型が一致しないデータを挿入
        bad_data = {
            "version": "1.0",
            "auto_learn": True,
            "learning_threshold": 3,
            "entries": [{"invalid_field": "data"}],
            "pending_confirmations": []
        }
        json.dump(bad_data, f)
        dict_path = Path(f.name)
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd.entries) == 0
    finally:
        os.unlink(f.name)

    # 3. ファイルアクセスエラー (OSError) による例外テスト
    # ディレクトリをファイルパスとして指定することで、読み込み時に例外を発生させる
    dict_path = Path(tempfile.mkdtemp())
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd.entries) == 0
    finally:
        os.rmdir(dict_path)


def test_proper_noun_dict_id_safety():
    """IDの重複が発生しないことを検証"""
    dict_path = Path(tempfile.mktemp(suffix='.json'))
    try:
        pnd = ProperNounDictionary(dict_path=dict_path)
        # 1. 3つのエントリを追加
        e1 = pnd.add_entry('incorrect1', 'correct1')
        e2 = pnd.add_entry('incorrect2', 'correct2')
        e3 = pnd.add_entry('incorrect3', 'correct3')
        assert e1.id == "pn_001"
        assert e2.id == "pn_002"
        assert e3.id == "pn_003"

        # 2. 真ん中のエントリを削除 (len(entries) が 2 になる)
        assert pnd.remove_entry(e2.id) is True
        assert len(pnd.entries) == 2

        # 3. 新規エントリを追加したときに、IDが pn_003 ではなく pn_004 になることを検証
        e4 = pnd.add_entry('incorrect4', 'correct4')
        assert e4.id == "pn_004"
        assert e4.id != e3.id
    finally:
        if dict_path.exists():
            os.unlink(dict_path)


def test_proper_noun_dict_load_non_dict_json():
    """有効なJSONだが辞書形式ではない（リスト形式等）の場合の堅牢性を検証"""
    # 1. [] を含むファイルを作成
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        f.write("[]")
        dict_path = Path(f.name)
    try:
        # ロード時にクラッシュせず、entriesが空で初期化されること
        pnd = ProperNounDictionary(dict_path=dict_path)
        assert len(pnd.entries) == 0
    finally:
        os.unlink(f.name)
