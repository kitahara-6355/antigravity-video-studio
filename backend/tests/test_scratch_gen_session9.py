import json
import sys
import runpy
from pathlib import Path
from unittest.mock import patch

def test_gen_session9_execution(tmp_path):
    project_root = Path(__file__).parent.parent.parent.resolve()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    real_backend = project_root / 'backend'
    
    temp_backend = tmp_path / 'backend'
    temp_stories = temp_backend / 'ux_verification' / 'stories'
    temp_snapshots = temp_backend / 'ux_verification' / 'snapshots'
    temp_stories.mkdir(parents=True, exist_ok=True)
    temp_snapshots.mkdir(parents=True, exist_ok=True)

    original_write_text = Path.write_text
    original_read_text = Path.read_text
    original_glob = Path.glob

    def redirect_path(path_obj):
        try:
            resolved_path = path_obj.resolve()
            resolved_real_backend = real_backend.resolve()
            if resolved_real_backend in resolved_path.parents or resolved_path == resolved_real_backend:
                rel = resolved_path.relative_to(resolved_real_backend)
                redirected = temp_backend / rel
                redirected.parent.mkdir(parents=True, exist_ok=True)
                return redirected
        except Exception:
            pass
        return path_obj

    def mock_write_text(self, data, *args, **kwargs):
        target = redirect_path(self)
        return original_write_text(target, data, *args, **kwargs)

    def mock_read_text(self, *args, **kwargs):
        target = redirect_path(self)
        return original_read_text(target, *args, **kwargs)

    def mock_glob(self, pattern, *args, **kwargs):
        target = redirect_path(self)
        return original_glob(target, pattern, *args, **kwargs)

    # 1. まず普通に import してカバレッジエンジンにモジュールを認識させる
    import backend.scripts.gen_session9 as gen_session9

    # 重複インポートの警告を防ぐために sys.modules から削除
    sys.modules.pop('backend.scripts.gen_session9', None)

    # 2. パッチを適用して runpy.run_module で __main__ ブロックを実行
    with patch.object(Path, 'write_text', mock_write_text), \
         patch.object(Path, 'read_text', mock_read_text), \
         patch.object(Path, 'glob', mock_glob):
        
        runpy.run_module('backend.scripts.gen_session9', run_name='__main__')

    # 一時ディレクトリに正しく書き出されたか検証
    o10_file = temp_stories / 'o10_theme_selector.json'
    o11_file = temp_stories / 'o11_preproduction_lab.json'
    o12_file = temp_stories / 'o12_soul_evolution.json'
    snap_file = temp_snapshots / 'v6.0.json'

    assert o10_file.exists()
    assert o11_file.exists()
    assert o12_file.exists()
    assert snap_file.exists()

    with open(o10_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert data['ux_id'] == 'O-10'
        assert len(data['verification_items']) == 50

    with open(o11_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert data['ux_id'] == 'O-11'
        assert len(data['verification_items']) == 50

    with open(o12_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        assert data['ux_id'] == 'O-12'
        assert len(data['verification_items']) == 55

    with open(snap_file, 'r', encoding='utf-8') as f:
        snap_data = json.load(f)
        assert snap_data['version'] == 'v6.0'
        assert len(snap_data['items']) > 0
        for item in snap_data['items']:
            assert item['passed'] is True
