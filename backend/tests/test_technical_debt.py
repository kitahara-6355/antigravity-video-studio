import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pytest
from pathlib import Path
from backend.agents.memory.technical_debt import TechnicalDebtStore, TechnicalDebtEntry, CausePattern, DebtChangeRecord

def test_store_initialization(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert store.entries == []
    assert store.cause_patterns == []
    assert store.changelog == []
    assert store.index_path == tmp_path / 'technical_debt_index.json'

def test_crud_operations(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    
    # 正常登録
    entry1 = store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='routers/preview.py',
        line_number=87,
        pattern='except Exception as e:',
        cause_pattern='DP-02',
        fix_pattern='except HTTPException: raise を追加',
        registered_by='sprint_test',
        notes='Notes here',
        tags=['tag1']
    )
    assert entry1.debt_id == 'TD-001'
    assert entry1.status == 'open'
    assert entry1.category == 'CRITICAL_ROUTER'
    assert entry1.notes == 'Notes here'
    assert entry1.tags == ['tag1']
    
    # 重複登録は既存のものを返す
    entry1_dup = store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='routers/preview.py',
        line_number=87,
        pattern='dummy'
    )
    assert entry1_dup.debt_id == 'TD-001'
    
    # 無効カテゴリでの例外
    with pytest.raises(ValueError, match='Invalid category'):
        store.register_debt(category='INVALID', file_path='f.py', line_number=1, pattern='abc')
        
    # ID自動生成のインクリメント
    entry2 = store.register_debt(
        category='IMPORTANT_SERVICE',
        file_path='services/engine.py',
        line_number=10,
        pattern='except Exception:'
    )
    assert entry2.debt_id == 'TD-002'
    
    # 存在しない・無効IDの自動生成フォールバックの確認
    invalid_entry = TechnicalDebtEntry(
        debt_id='TD-XYZ',
        category='MINOR_INFRA',
        file_path='x.py',
        line_number=100,
        pattern='x',
        cause_pattern='',
        fix_pattern='',
        status='open',
        registered_at='2026-05-26T12:00:00',
        registered_by='test'
    )
    store.entries.append(invalid_entry)
    entry3 = store.register_debt(
        category='MINOR_INFRA',
        file_path='y.py',
        line_number=200,
        pattern='y'
    )
    assert entry3.debt_id == 'TD-003'

    # 解消 (resolve_debt)
    resolved = store.resolve_debt('TD-001', fixed_by='sprint_fix', fix_evidence='pytest passed')
    assert resolved is not None
    assert resolved.status == 'fixed'
    assert resolved.fixed_by == 'sprint_fix'
    assert resolved.fix_evidence == 'pytest passed'
    
    # 既に解消済みの警告早期リターン
    resolved_again = store.resolve_debt('TD-001', fixed_by='other', fix_evidence='other')
    assert resolved_again.fixed_by == 'sprint_fix'
    
    # 存在しないIDでのNone
    assert store.resolve_debt('TD-999', fixed_by='x', fix_evidence='y') is None
    
    # 許容 (accept_debt)
    accepted = store.accept_debt('TD-002', reason='Safety net')
    assert accepted is not None
    assert accepted.status == 'accepted'
    assert 'Safety net' in accepted.notes
    
    # 存在しないIDでのNone
    assert store.accept_debt('TD-999', reason='test') is None
    
    # 再オープン (reopen_debt)
    reopened = store.reopen_debt('TD-001', reason='Regression')
    assert reopened is not None
    assert reopened.status == 'open'
    assert reopened.fixed_at is None
    assert reopened.fixed_by is None
    assert 'was fixed by sprint_fix' in reopened.notes
    
    # 存在しないIDでのNone
    assert store.reopen_debt('TD-999', reason='test') is None

    # 各種ゲッターの動作検証
    assert store.get_entry('TD-001').debt_id == 'TD-001'
    assert store.get_entry('TD-999') is None
    
    assert len(store.get_entries_by_file('routers/preview.py')) == 1
    assert len(store.get_entries_by_file('nonexistent.py')) == 0
    
    assert len(store.get_entries_by_category('CRITICAL_ROUTER')) == 1
    assert len(store.get_entries_by_category('INVALID')) == 0
    
    open_entries = store.get_open_entries()
    assert len(open_entries) == 3
    
    assert store.get_critical_open_count() == 1

def test_contradictions_and_changelog(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    
    # 正常登録
    store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='routers/preview.py',
        line_number=87,
        pattern='except Exception as e:',
        cause_pattern='DP-02',
        fix_pattern='except HTTPException: raise を追加'
    )
    
    # 異なるカテゴリで矛盾
    entry_diff_cat = TechnicalDebtEntry(
        debt_id='TD-002',
        category='MINOR_INFRA',
        file_path='routers/preview.py',
        line_number=87,
        pattern='except Exception as e:',
        cause_pattern='DP-02',
        fix_pattern='',
        status='open',
        registered_at='2026-05-26T12:00:00',
        registered_by='test'
    )
    store.entries.append(entry_diff_cat)
    
    contradictions = store.get_contradictions()
    assert len(contradictions) == 1
    assert '異なるカテゴリ' in contradictions[0]['reason']
    
    # 異なるステータスで矛盾
    store.entries = []
    e1 = store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='routers/preview.py',
        line_number=87,
        pattern='x'
    )
    e2 = TechnicalDebtEntry(
        debt_id='TD-002',
        category='CRITICAL_ROUTER',
        file_path='routers/preview.py',
        line_number=87,
        pattern='x',
        cause_pattern='',
        fix_pattern='',
        status='fixed',
        registered_at='2026-05-26T12:00:00',
        registered_by='test'
    )
    store.entries.append(e2)
    contradictions2 = store.get_contradictions()
    assert len(contradictions2) == 1
    assert '異なるステータス' in contradictions2[0]['reason']
    
    # verify_debt のテスト
    verified = store.verify_debt('TD-001')
    assert verified is not None
    assert verified.last_verified_at is not None
    assert store.verify_debt('TD-999') is None
    
    # changelogの取得テスト
    changelog = store.get_changelog(limit=2)
    assert len(changelog) <= 2
    
    changelog_td001 = store.get_changelog(debt_id='TD-001')
    assert len(changelog_td001) > 0
    assert all(r.debt_id == 'TD-001' for r in changelog_td001)
    
    # 200文字超の切り詰めテスト
    store._add_changelog('test_action', 'TD-001', 'actor', 'open', 'fixed', 'a' * 300)
    assert len(store.changelog[-1].detail) == 200

def test_enforce_limits(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    store.MAX_ENTRIES = 5
    
    for i in range(3):
        store.register_debt(
            category='CRITICAL_ROUTER',
            file_path=f'file_{i}.py',
            line_number=10,
            pattern='x'
        )
        
    for i in range(4):
        e = store.register_debt(
            category='MINOR_INFRA',
            file_path=f'fixed_{i}.py',
            line_number=10,
            pattern='x'
        )
        store.resolve_debt(e.debt_id, fixed_by='test', fix_evidence='test')
        
    assert len(store.entries) == 5
    remaining_files = [e.file_path for e in store.entries]
    assert 'fixed_0.py' not in remaining_files
    assert 'fixed_1.py' not in remaining_files
    assert 'fixed_2.py' in remaining_files

def test_cost_and_pattern_analysis(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    
    store.cause_patterns.append(CausePattern(
        pattern_id='DP-01',
        name='Test Pattern',
        cause='cause',
        prevention='prevention',
        scope='scope'
    ))
    
    e1 = store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='f1.py',
        line_number=1,
        pattern='x',
        cause_pattern='DP-01'
    )
    e1.estimated_fix_minutes = 30
    
    store.register_debt(
        category='CRITICAL_ROUTER',
        file_path='f2.py',
        line_number=2,
        pattern='x',
        cause_pattern='DP-01'
    )
    
    cost = store.get_cost_summary()
    assert cost['total_minutes'] == 30
    assert cost['unestimated_count'] == 1
    
    stats = store.get_stats()
    assert stats['total_entries'] == 2
    
    for i in range(10):
        store.register_debt(
            category='MINOR_INFRA',
            file_path=f'file_rec_{i}.py',
            line_number=10,
            pattern='x',
            cause_pattern='DP-01'
        )
    analysis = store.get_pattern_analysis()
    assert 'DP-01' in analysis['recurring_patterns']
    assert '根本原因の対処を推奨' in analysis['recommendation']
    
    summary = store.get_summary()
    assert 'DP-01' in summary['recurring_patterns']
    assert 'cost_hours' in summary

def test_context_and_snapshot(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    store.snapshot_dir = tmp_path / "snapshots"
    
    store.register_debt(category='ACCEPTED_SAFETY', file_path='f1.py', line_number=1, pattern='x')
    store.register_debt(category='CRITICAL_ROUTER', file_path='f2.py', line_number=2, pattern='x')
    store.register_debt(category='MINOR_INFRA', file_path='f3.py', line_number=3, pattern='x')
    store.register_debt(category='IMPORTANT_SERVICE', file_path='f4.py', line_number=4, pattern='x')
    store.register_debt(category='CRITICAL_PHASE4', file_path='f5.py', line_number=5, pattern='x')
    
    context_entries = store.get_entries_for_context(max_entries=3)
    assert len(context_entries) == 3
    assert context_entries[0].file_path == 'f2.py'
    assert context_entries[1].file_path == 'f5.py'
    assert context_entries[2].file_path == 'f4.py'
    
    assert store.get_context_for_file('nonexistent.py') == ''
    context_str = store.get_context_for_file('f2.py')
    assert 'TD-002' in context_str
    
    snapshot_path = store.create_snapshot('1.2.3')
    assert snapshot_path.exists()
    
    latest = store.get_latest_snapshot()
    assert latest['version'] == '1.2.3'
    
    ratchet_res1 = store.check_ratchet()
    assert ratchet_res1['passed'] is True
    
    store.register_debt(category='CRITICAL_ROUTER', file_path='f6.py', line_number=6, pattern='x')
    ratchet_res2 = store.check_ratchet()
    assert ratchet_res2['passed'] is False

def test_load_and_save_errors(tmp_path):
    import json
    index_file = tmp_path / 'technical_debt_index.json'
    incomplete_data = {
        'version': '1.1',
        'entries': [
            {
                'debt_id': 'TD-001',
                'category': 'CRITICAL_ROUTER',
                'file_path': 'f.py',
                'line_number': 1,
                'pattern': 'x',
                'cause_pattern': '',
                'fix_pattern': '',
                'status': 'open',
                'registered_at': '2026-05-26T12:00:00',
                'registered_by': 'test'
            }
        ]
    }
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(incomplete_data, f)
        
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert len(store.entries) == 1
    assert store.entries[0].tags == []
    assert store.entries[0].confidence == 1.0
    assert store.entries[0].estimated_fix_minutes is None
    
    with open(index_file, 'w', encoding='utf-8') as f:
        f.write('{invalid json')
    store_err = TechnicalDebtStore(debt_dir=tmp_path)
    assert len(store_err.entries) == 0
    
    from unittest.mock import patch
    store_save = TechnicalDebtStore(debt_dir=tmp_path)
    store_save.register_debt(category='MINOR_INFRA', file_path='a.py', line_number=1, pattern='x')
    
    with patch('tempfile.mkstemp', side_effect=OSError('Disk Full')):
        store_save._save()
        
    real_open = open
    def side_effect_open(file, *args, **kwargs):
        if 'TECHNICAL_DEBT_REGISTRY' in str(file):
            raise OSError('Markdown write failed')
        return real_open(file, *args, **kwargs)
        
    with patch('builtins.open', side_effect=side_effect_open):
        store_save._save()

def test_contradictions_single_entry(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    assert store.get_contradictions() == []
    
    store.register_debt(category='CRITICAL_ROUTER', file_path='f.py', line_number=1, pattern='x')
    assert store.get_contradictions() == []

def test_no_snapshot(tmp_path):
    store = TechnicalDebtStore(debt_dir=tmp_path)
    store.snapshot_dir = tmp_path / 'custom_snapshots'
    assert store.get_latest_snapshot() is None
    
    store.snapshot_dir.mkdir(parents=True, exist_ok=True)
    assert store.get_latest_snapshot() is None
    
    ratchet = store.check_ratchet()
    assert ratchet['passed'] is True

def test_save_replace_error(tmp_path):
    from unittest.mock import patch
    store = TechnicalDebtStore(debt_dir=tmp_path)
    store.register_debt(category='MINOR_INFRA', file_path='a.py', line_number=1, pattern='x')
    
    with patch('os.replace', side_effect=OSError('Replace failed')):
        store._save()
