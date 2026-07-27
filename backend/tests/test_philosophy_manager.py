"""
PhilosophyManagerのユニットテスト
"""

import pytest
import json
import runpy
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime
from PIL import Image


# パス設定（親ディレクトリがbackendであることを保証）
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from philosophy_manager import PhilosophyManager


@pytest.fixture
def temp_branding_dir(tmp_path):
    """テスト用の一時ディレクトリ構成"""
    branding_dir = tmp_path / "branding"
    branding_dir.mkdir(parents=True, exist_ok=True)
    return branding_dir


def test_init_load_file_not_found(temp_branding_dir):
    """ファイルが存在しない場合の初期化テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        assert pm.evolution_log == {"entries": [], "philosophies": [], "integrated_philosophy": None}


def test_init_load_file_success(temp_branding_dir):
    """ファイルが存在し、正常に読み込める場合のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "entries": [{"session": 1}],
        "philosophies": [{"philosophy": "テスト哲学", "timestamp": "2026-01-01"}],
        "integrated_philosophy": "統合哲学"
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        assert pm.evolution_log["integrated_philosophy"] == "統合哲学"
        assert len(pm.evolution_log["philosophies"]) == 1


def test_save_evolution_log(temp_branding_dir):
    """保存処理のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        pm.evolution_log["integrated_philosophy"] = "保存テストの統合哲学"
        pm._save_evolution_log()
        
        # 実際に保存されたか読み込み確認
        with open(log_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["integrated_philosophy"] == "保存テストの統合哲学"


def test_auto_tag_philosophy():
    """自動タグ付け機能のテスト"""
    pm = PhilosophyManager()
    
    # 登録されているキーワードマッチングのテスト
    assert "技術" in pm.auto_tag_philosophy("自動化されたシステムを使用する")
    assert "協調" in pm.auto_tag_philosophy("チームで連携して進める")
    assert "芸術" in pm.auto_tag_philosophy("美しいデザインを作る")
    assert "その他" in pm.auto_tag_philosophy("無関係な文章です")


def test_tag_all_philosophies(temp_branding_dir):
    """全哲学に対する一括タグ付けテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": [
            {"philosophy": "システム自動化による効率化", "timestamp": "2026-01-01"},
            "文字列だけの古い哲学データ（辞書型ではないためスキップされるはず）",
            {"philosophy": "美しい表現と調和", "timestamp": "2026-01-02"}
        ]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        tagged = pm.tag_all_philosophies()
        
        # 辞書型のデータにはタグが追加されていること
        assert "tags" in tagged[0]
        assert "技術" in tagged[0]["tags"]
        
        # 非辞書型データはタグ付与がスキップされるがそのまま残ること
        assert isinstance(tagged[1], str)
        
        assert "tags" in tagged[2]
        assert "芸術" in tagged[2]["tags"] or "バランス" in tagged[2]["tags"]


def test_search_philosophies(temp_branding_dir):
    """検索機能のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": [
            {"philosophy": "技術的な自動化", "tags": ["技術"], "timestamp": "2026-01-01"},
            {"philosophy": "チーム協調と芸術表現", "tags": ["協調", "芸術"], "timestamp": "2026-01-02"},
            {"philosophy": "その他無関係", "tags": ["その他"], "timestamp": "2026-01-03"},
            "文字列データ（スキップされるはず）"
        ]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        
        # クエリ単体検索（大文字小文字無視含む）
        res1 = pm.search_philosophies(query="技術")
        assert len(res1) == 1
        assert res1[0]["philosophy"] == "技術的な自動化"
        
        # タグ単体検索
        res2 = pm.search_philosophies(tags=["芸術"])
        assert len(res2) == 1
        assert res2[0]["philosophy"] == "チーム協調と芸術表現"
        
        # クエリとタグの組み合わせ（マッチする）
        res3 = pm.search_philosophies(query="表現", tags=["芸術"])
        assert len(res3) == 1
        
        # クエリとタグの組み合わせ（マッチしない）
        res4 = pm.search_philosophies(query="自動化", tags=["その他"])
        assert len(res4) == 0
        
        # limit制限の確認
        res_limit = pm.search_philosophies(limit=1)
        assert len(res_limit) == 1
        
        # get_philosophy_by_tagのエイリアステスト
        res_alias = pm.get_philosophy_by_tag("その他")
        assert len(res_alias) == 1
        assert res_alias[0]["philosophy"] == "その他無関係"


def test_cite_philosophy(temp_branding_dir):
    """引用機能のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    
    # 1. 空の時のテスト
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        assert pm.cite_philosophy() == "（哲学履歴なし）"
        
    # 2. 正常な履歴がある時のテスト
    mock_data = {
        "philosophies": [
            {"philosophy": "一番目の哲学", "timestamp": "2026-01-01"},
            {"philosophy": "二番目の哲学", "timestamp": "2026-01-02"},
            "文字列のみの古い哲学"
        ]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        
        # インデックス指定（最初）
        assert pm.cite_philosophy(0) == "「一番目の哲学」— 2026-01-01"
        # 最新（デフォルトは-1なので古い文字列哲学）
        assert pm.cite_philosophy(-1) == "「文字列のみの古い哲学」"
        # 最新の辞書型（-2）
        assert pm.cite_philosophy(-2) == "「二番目の哲学」— 2026-01-02"
        # 範囲外エラー
        assert pm.cite_philosophy(999) == "（該当する哲学なし）"


def test_generate_dashboard_html_and_summary(temp_branding_dir):
    """ダッシュボード生成およびサマリー取得のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "entries": [{"session": 1}, {"session": 2}],
        "philosophies": [
            {"philosophy": "システム自動化の追求", "tags": ["技術"], "timestamp": "2026-01-01", "session_summary": "S1サマリー"},
            {"philosophy": "チームの美意識", "tags": ["芸術", "協調"], "timestamp": "2026-01-02", "session_summary": "S2サマリー"}
        ],
        "integrated_philosophy": "究極の統合哲学",
        "integration_history": [{"integrated_at": "2026-01-02"}]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        
        # サマリー確認
        summary = pm.get_dashboard_summary()
        assert summary["total_philosophies"] == 2
        assert summary["total_sessions"] == 2
        assert summary["tag_stats"]["技術"] == 1
        assert summary["tag_stats"]["芸術"] == 1
        assert summary["integrated_philosophy"] == "究極の統合哲学"
        
        # ダッシュボードHTML生成（カスタムパス）
        out_html = temp_branding_dir / "dashboard.html"
        result_path = pm.generate_dashboard_html(output_path=out_html)
        
        assert Path(result_path).exists()
        with open(result_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        assert "🧠 哲学ダッシュボード" in html_content
        assert "究極の統合哲学" in html_content
        assert "システム自動化の追求" in html_content
        
        # ダッシュボードHTML生成（デフォルトパス - BRANDING_DIRをモックして一時パスへ書き込む）
        with patch("philosophy_manager.BRANDING_DIR", temp_branding_dir):
            default_result_path = pm.generate_dashboard_html()
            assert Path(default_result_path).exists()
            assert Path(default_result_path).name == "philosophy_dashboard.html"


def test_main_block(temp_branding_dir):
    """philosophy_manager.py の __main__ ブロックのテスト（100%カバレッジ用）"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "entries": [{"session": 1}],
        "philosophies": [
            {"philosophy": "技術的なシステム自動化の追求", "tags": ["技術"], "timestamp": "2026-01-01"},
            {"philosophy": "チーム協調の重視", "tags": ["協調"], "timestamp": "2026-01-02"}
        ],
        "integrated_philosophy": "究極の統合哲学",
        "integration_history": [{"integrated_at": "2026-01-02"}]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)

    import builtins
    original_open = builtins.open

    def patched_open(file, *args, **kwargs):
        try:
            file_path = Path(file)
            if file_path.name == "evolution_log.json":
                return original_open(log_path, *args, **kwargs)
        except Exception:
            pass
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", patched_open), \
         patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path), \
         patch("philosophy_manager.BRANDING_DIR", temp_branding_dir):
         
        # モジュールを実行
        module_path = str(Path(__file__).parent.parent / "philosophy_manager.py")
        # 標準出力とエラー出力をモック
        with patch("sys.stdout"), patch("sys.stderr"):
            runpy.run_path(module_path, run_name="__main__")


def test_init_load_invalid_json(temp_branding_dir):
    """壊れたJSONファイルの場合のロードテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("{invalid json...")
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        # 壊れたJSONの時は、デフォルト値にフォールバックすること
        assert pm.evolution_log == {"entries": [], "philosophies": [], "integrated_philosophy": None}


def test_cite_philosophy_invalid_type(temp_branding_dir):
    """cite_philosophyの引数indexに無効な型が指定された場合のテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": [
            {"philosophy": "テスト哲学", "timestamp": "2026-01-01"}
        ]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        # 整数以外が指定されたら、安全に「該当する哲学なし」を返すこと
        assert pm.cite_philosophy("invalid_index") == "（該当する哲学なし）"
        assert pm.cite_philosophy(None) == "（該当する哲学なし）"


def test_methods_with_missing_keys_or_none(temp_branding_dir):
    """evolution_log内のキーがNoneや欠損している場合の安全動作テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": None,
        "entries": None,
        "integrated_philosophy": None,
        "integration_history": None
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path), \
         patch("philosophy_manager.BRANDING_DIR", temp_branding_dir):
        pm = PhilosophyManager()
        
        # 1. tag_all_philosophies がクラッシュしないこと
        res_tag = pm.tag_all_philosophies()
        assert res_tag == []
        
        # 2. search_philosophies がクラッシュしないこと
        res_search = pm.search_philosophies()
        assert res_search == []
        
        # 3. generate_dashboard_html がクラッシュしないこと
        out_html = temp_branding_dir / "dashboard_none.html"
        result_path = pm.generate_dashboard_html(output_path=out_html)
        assert Path(result_path).exists()
        
        # 4. get_dashboard_summary がクラッシュしないこと
        summary = pm.get_dashboard_summary()
        assert summary["total_philosophies"] == 0
        assert summary["total_sessions"] == 0
        assert summary["integration_count"] == 0


def test_tag_all_philosophies_with_invalid_types(temp_branding_dir):
    """tag_all_philosophiesでの不正な型に対する安全動作テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": "invalid_string_type",
        "entries": 12345,
        "integrated_philosophy": None,
        "integration_history": {"not": "a list"}
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        res_tag = pm.tag_all_philosophies()
        assert res_tag == []


def test_search_philosophies_with_invalid_types(temp_branding_dir):
    """search_philosophiesでの不正な型に対する安全動作テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": "invalid_string_type",
        "entries": 12345,
        "integrated_philosophy": None,
        "integration_history": {"not": "a list"}
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        res_search = pm.search_philosophies()
        assert res_search == []


def test_generate_dashboard_html_with_invalid_types(temp_branding_dir):
    """generate_dashboard_htmlでの不正な型に対する安全動作テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": "invalid_string_type",
        "entries": 12345,
        "integrated_philosophy": None,
        "integration_history": {"not": "a list"}
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path), \
         patch("philosophy_manager.BRANDING_DIR", temp_branding_dir):
        pm = PhilosophyManager()
        out_html = temp_branding_dir / "dashboard_invalid.html"
        result_path = pm.generate_dashboard_html(output_path=out_html)
        assert Path(result_path).exists()


def test_get_dashboard_summary_with_invalid_types(temp_branding_dir):
    """get_dashboard_summaryでの不正な型に対する安全動作テスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": "invalid_string_type",
        "entries": 12345,
        "integrated_philosophy": None,
        "integration_history": {"not": "a list"}
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        summary = pm.get_dashboard_summary()
        assert summary["total_philosophies"] == 0
        assert summary["total_sessions"] == 0
        assert summary["integration_count"] == 0


def test_search_philosophies_with_invalid_tags(temp_branding_dir):
    """search_philosophiesで個別哲学のtagsキーが不正な型のときのテスト"""
    log_path = temp_branding_dir / "evolution_log.json"
    mock_data = {
        "philosophies": [
            {"philosophy": "システム自動化", "tags": "invalid_tags_string"}
        ]
    }
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(mock_data, f, ensure_ascii=False)
        
    with patch("philosophy_manager.EVOLUTION_LOG_PATH", log_path):
        pm = PhilosophyManager()
        # tagsがリストでない場合、空リスト扱いとなり検索クエリフィルタ等に影響しないこと
        res = pm.search_philosophies(query="システム")
        assert len(res) == 1
        assert res[0]["philosophy"] == "システム自動化"


def test_auto_tag_philosophy_with_invalid_types():
    """auto_tag_philosophyに不正な型が渡された場合のテスト"""
    pm = PhilosophyManager()
    assert pm.auto_tag_philosophy(None) == ["その他"]
    assert pm.auto_tag_philosophy(12345) == ["その他"]
    assert pm.auto_tag_philosophy([]) == ["その他"]


def test_philosophy_thumbnail_success(tmp_path):
    """正常系: サムネイル画像が正常に生成され、品質検証をパスするケース"""
    pm = PhilosophyManager()
    output_path = tmp_path / "philosophy_thumb.png"
    
    # 1. デフォルト設定での生成
    result_path = pm.generate_philosophy_thumbnail(output_path, text="Test Philosophy")
    assert result_path.exists()
    
    # 2. 品質検証が通ることを確認
    result_info = pm.validate_thumbnail_quality(result_path)
    assert result_info["path"] == str(result_path)
    assert result_info["width"] == 1280
    assert result_info["height"] == 720
    assert result_info["size_bytes"] < 4 * 1024 * 1024
    
    # Pillowでロード可能であることを検証
    with Image.open(result_path) as img:
        img.verify()


def test_philosophy_thumbnail_quality_failures(tmp_path):
    """異常系: 品質検証でエラーが投げられるケース"""
    pm = PhilosophyManager()
    
    # 1. 存在しないファイル
    with pytest.raises(FileNotFoundError):
        pm.validate_thumbnail_quality(tmp_path / "non_existent.png")
        
    # 2. 解像度が低い画像 (例えば 640x360)
    low_res_path = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360), color="blue")
    img.save(low_res_path, format="PNG")
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        pm.validate_thumbnail_quality(low_res_path)
        
    # 3. アスペクト比が正しくない画像 (4:3 解像度 1280x960)
    bad_ratio_path = tmp_path / "bad_ratio.png"
    img = Image.new("RGB", (1280, 960), color="blue")
    img.save(bad_ratio_path, format="PNG")
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        pm.validate_thumbnail_quality(bad_ratio_path)
        
    # 4. ファイルサイズ制限 (4MB以上)
    valid_img_path = tmp_path / "valid_size.png"
    pm.generate_philosophy_thumbnail(valid_img_path)
    with patch("pathlib.Path.stat") as mock_stat:
        mock_stat.return_value.st_size = 5 * 1024 * 1024  # 5MB
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            pm.validate_thumbnail_quality(valid_img_path)
            
    # 5. 引数異常チェック
    with pytest.raises(ValueError, match="Width and height must be integers"):
        pm.generate_philosophy_thumbnail(valid_img_path, width="invalid")
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        pm.generate_philosophy_thumbnail(valid_img_path, width=-100)


def test_stage_bound_agent_integration_philosophy(tmp_path):
    """StageBoundAgentとの連携テスト"""
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "philosophy_agent_test.db"
    output_dir = tmp_path / "thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    pm = PhilosophyManager()
    pm.output_dir = str(output_dir)
    pm.width = 1280
    pm.height = 720
    pm.text = "Philosophy Agent Integration Test"
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "philosophy_thumb_test"
    
    async def run_test():
        # タスクを登録して READY 状態にする
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=2)
        
        # エージェントを起動し、タスク解決処理を開始
        await agent.start(pm.resolve_philosophy_thumbnail_task)
        
        # 完了または失敗まで待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        assert final_status == "COMPLETED"
        
        # 生成された画像が正しく存在し、破損していないか確認
        output_path = output_dir / f"{task_id}.png"
        assert output_path.exists()
        
        result_info = pm.validate_thumbnail_quality(output_path)
        assert result_info["width"] == 1280
        assert result_info["height"] == 720
        assert result_info["size_bytes"] < 4 * 1024 * 1024
        
        # DBへの結果保存とリトライカウント等のメタデータ整合性を確認
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, result_str, retry_count = row
            assert status == "COMPLETED"
            assert retry_count == 0
            
            db_result = json.loads(result_str)
            assert db_result["width"] == 1280
            assert db_result["height"] == 720
            assert "path" in db_result
        finally:
            conn.close()
            
    asyncio.run(run_test())


def test_philosophy_thumbnail_overwrite(tmp_path):
    """既存のサムネイルファイルが存在する場合に上書きされるテスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "thumb_overwrite.png"
    # ダミーファイルを事前作成
    output_path.write_text("dummy content")
    assert output_path.exists()
    
    result_path = pm.generate_philosophy_thumbnail(output_path, text="Overwrite Test")
    assert result_path.exists()
    
    # 正常に画像として読み込めるか検証
    with Image.open(result_path) as img:
        img.verify()


def test_philosophy_thumbnail_atomic_write_failure(tmp_path):
    """アトミック書き込み中に例外が発生した場合のクリーンアップ処理のテスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "thumb_fail.png"
    
    # Image.saveが例外を投げるケース（temp_pathが存在しない場合）
    with patch("PIL.Image.Image.save", side_effect=OSError("Save error")):
        with pytest.raises(OSError, match="Save error"):
            pm.generate_philosophy_thumbnail(output_path)
            
    # 一時ファイルが存在し、かつunlinkが失敗する（例外を投げる）ケース
    # rename時に例外を投げるようにモックすることで、temp_pathが作成された状態で例外処理に入るようにする
    PathClass = type(Path())
    original_unlink = PathClass.unlink
    
    def mock_unlink(self):
        # 一時ファイルに対するunlinkのみ例外を投げる
        if ".tmp" in self.name:
            raise PermissionError("Unlink permission denied")
        return original_unlink(self)
        
    with patch.object(PathClass, "rename", side_effect=OSError("Rename error")), \
         patch.object(PathClass, "unlink", mock_unlink):
        with pytest.raises(OSError, match="Rename error"):
            pm.generate_philosophy_thumbnail(output_path)


def test_validate_thumbnail_quality_verify_failure(tmp_path):
    """validate_thumbnail_qualityでverifyが失敗した場合の例外テスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "verify_fail.png"
    pm.generate_philosophy_thumbnail(output_path)
    
    # Image.openで返されるオブジェクトのverifyをモックする
    mock_img = MagicMock()
    mock_img.verify.side_effect = SyntaxError("Verify error")
    mock_img.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            pm.validate_thumbnail_quality(output_path)


def test_validate_thumbnail_quality_load_failure(tmp_path):
    """validate_thumbnail_qualityでloadが失敗した場合の例外テスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "load_fail.png"
    pm.generate_philosophy_thumbnail(output_path)
    
    # Image.openで返されるオブジェクトのloadをモックする
    mock_img = MagicMock()
    mock_img.load.side_effect = OSError("Load error")
    mock_img.verify.return_value = None  # verify() は例外を投げないようにする
    mock_img.size = (1280, 720)          # サイズの検証を通すため
    mock_img.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            pm.validate_thumbnail_quality(output_path)




def test_stage_bound_agent_integration_philosophy_retry(tmp_path):
    """StageBoundAgentとの連携テスト：リトライ機能の確認"""
    import asyncio
    import sqlite3
    from agents.stage_bound_agent import StageBoundAgent
    
    db_file = tmp_path / "philosophy_agent_retry_test.db"
    
    pm = PhilosophyManager()
    
    # 意図的に例外を発生させるモックを設定
    mock_generate = MagicMock(side_effect=[RuntimeError("Temporary error"), Path("/dummy")])
    pm.generate_philosophy_thumbnail = mock_generate
    # validate_thumbnail_qualityもダミー情報を返すようにモック
    pm.validate_thumbnail_quality = MagicMock(return_value={"width": 1280, "height": 720, "size_bytes": 100, "path": "dummy"})
    
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    task_id = "philosophy_thumb_retry_test"
    
    async def run_test():
        # タスクを登録 (max_retries=1)
        await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
        
        # 1回目の実行では例外が発生し、リトライされて2回目で成功するはず
        await agent.start(pm.resolve_philosophy_thumbnail_task)
        
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status in ("COMPLETED", "FAILED"):
                break
            await asyncio.sleep(0.05)
            
        final_status = await agent.get_task_status(task_id)
        await agent.stop()
        
        # 最終的に成功することを確認
        assert final_status == "COMPLETED"
        assert mock_generate.call_count == 2
        
        # DBにリトライ履歴が記録されているか検証
        conn = sqlite3.connect(str(db_file))
        try:
            cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            assert row is not None
            status, retry_count, error = row
            assert status == "COMPLETED"
            assert retry_count == 1
        finally:
            conn.close()
            
    asyncio.run(run_test())

def test_validate_thumbnail_quality_syntax_error_load(tmp_path):
    """validate_thumbnail_qualityのloadでSyntaxErrorが発生した場合の例外テスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "syntax_fail_load.png"
    pm.generate_philosophy_thumbnail(output_path)
    
    mock_img = MagicMock()
    mock_img.load.side_effect = SyntaxError("Syntax error during load")
    mock_img.verify.return_value = None
    mock_img.size = (1280, 720)
    mock_img.__enter__.return_value = mock_img
    
    with patch("PIL.Image.open", return_value=mock_img):
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            pm.validate_thumbnail_quality(output_path)


def test_generate_philosophy_thumbnail_value_error(tmp_path):
    """generate_philosophy_thumbnailでValueErrorが発生した場合のクリーンアップテスト"""
    pm = PhilosophyManager()
    output_path = tmp_path / "value_fail.png"
    
    with patch("PIL.Image.new", side_effect=ValueError("Invalid image size")):
        with pytest.raises(ValueError, match="Invalid image size"):
            pm.generate_philosophy_thumbnail(output_path)
