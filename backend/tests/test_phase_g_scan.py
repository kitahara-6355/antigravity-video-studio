import asyncio
# -*- coding: utf-8 -*-
import pytest
import os
import sys
import runpy
import ast
from unittest.mock import patch, MagicMock
from pathlib import Path

# パス設定
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# 共通のベースモックヘルパー
def create_base_mocks(tmp_path, custom_files):
    created_files = []
    for fname, content in custom_files.items():
        p = tmp_path / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created_files.append(p)
        
    return created_files

def test_phase_g_scan_execution_issues(tmp_path, capsys):
    # パターン1: 懸念点や例外が発生するケース
    custom_files = {
        "dummy_service.py": "def run():\n    try:\n        print('hello')\n    except:\n        pass\n\nif __name__ == '__main__':\n    print('main')\n", # 65行目をカバー
        "heavy_print.py": "\n".join(["print('test')"] * 6), # 89行目をカバー
        "error_file.py": "def dummy(): pass", # 35-36行目をカバー用
        "pipeline_router.py": "vault-assets path config", # 103-104行目をカバー (残存)
        "quality_gate_plugins.py": "try:\n    pass\nexcept (ImportError, Exception):\n    pass\n", # 111行目をカバー (残存)
        "governance.py": "other logic here", # 123行目をカバー (未追加)
        "audio_master.py": "def duck_bgm():\n    duck_amount = 0.5\n",
        "ProductionPipeline.jsx": "pipeline/report link",
        "archives/old.py": "def old(): pass",
        "test_dummy.py": "def test_x(): pass",    # 20-21, 51-52行目 (test_ 除外) をカバー
        "_private.py": "def _priv(): pass"          # 20-21, 51-52行目 (_ 除外) をカバー
    }
    
    files = create_base_mocks(tmp_path, custom_files)
    
    def mock_rglob(self, *args, **kwargs):
        pattern = args[0] if args else kwargs.get("pattern", "*.py")
        if pattern == "*.py":
            return files
        return []

    def mock_read_text(self, *args, **kwargs):
        p_str = str(self)
        if "error_file.py" in p_str:
            raise OSError("Simulated file read error")  # 35-36行目をカバー
            
        for fname, content in custom_files.items():
            if fname in p_str.replace("\\", "/"):
                return content
                
        p_abs = os.path.abspath(p_str)
        if os.path.exists(p_abs):
            with open(p_abs, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def mock_relative_to(self, *args, **kwargs):
        return Path(self.name)

    # 61-69行目 (AST解析例外) をカバーするための ast.walk モック
    original_walk = ast.walk
    def mock_walk(tree):
        for node in original_walk(tree):
            yield node
        # test属性を持たないダミーの ast.If ノードを追加し、例外を発生させる
        bad_if = ast.If(test=ast.Name(id="dummy", ctx=ast.Load()), body=[], orelse=[])
        del bad_if.test
        yield bad_if

    with patch.object(Path, "rglob", side_effect=mock_rglob, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch.object(ast, "walk", side_effect=mock_walk), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")
    
    captured = capsys.readouterr()
    output = captured.out
    
    assert "N系列: except:pass 残存スキャン" in output
    assert "M系列: print() 残存スキャン" in output
    assert "その他 Tier 0-1 個別チェック" in output
    assert "E-05 vault-assets ハードコード: 残存" in output
    assert "F-03 AIRuleCheck exception握潰し: 残存" in output
    assert "G-01 GovernanceScope SmartCut: 未追加" in output


def test_phase_g_scan_execution_clean(tmp_path, capsys):
    # パターン2: 懸念点が解決されているケースや、別パターンの検証
    custom_files = {
        "dummy_service.py": "def run():\n    try:\n        print('hello')\n    except:\n        pass\n",
        "pipeline_router.py": "no asset path", # 106行目をカバー (解決済み)
        "quality_gate_plugins.py": "try:\n    pass\nexcept ValueError:\n    pass\n", # 112-116行目をカバー (別形式)
        "governance.py": "smartcut logic here", # 121行目をカバー (解決済み)
        "audio_master.py": "def duck_bgm():\n    duck_amount = 0.5\n",
        "ProductionPipeline.jsx": "pipeline/report link"
    }
    
    files = create_base_mocks(tmp_path, custom_files)
    
    def mock_rglob(self, *args, **kwargs):
        pattern = args[0] if args else kwargs.get("pattern", "*.py")
        if pattern == "*.py":
            return files
        return []

    def mock_read_text(self, *args, **kwargs):
        p_str = str(self)
        for fname, content in custom_files.items():
            if fname in p_str.replace("\\", "/"):
                return content
        p_abs = os.path.abspath(p_str)
        if os.path.exists(p_abs):
            with open(p_abs, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def mock_relative_to(self, *args, **kwargs):
        return Path(self.name)

    with patch.object(Path, "rglob", side_effect=mock_rglob, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")
    
    captured = capsys.readouterr()
    output = captured.out
    
    assert "E-05 vault-assets: 解決済み" in output
    assert "F-03 AIRuleCheck: except:pass 1件残存" in output
    assert "G-01 GovernanceScope SmartCut: 解決済み" in output


@pytest.mark.asyncio
async def test_thumbnail_quality_standards(tmp_path):
    """
    サムネイル生成タスクが品質基準を満たし、StageBoundAgent と連携することを確認するテスト
    """
    import json
    from PIL import Image
    from backend.agents.stage_bound_agent import StageBoundAgent, generate_thumbnail, resolve_thumbnail_task
    from backend.tests._phase_g_scan import run_thumbnail_quality_check
    
    db_file = tmp_path / "thumbnail_p27.db"
    output_dir = tmp_path / "thumbnails"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. StageBoundAgent の初期化とDBマイグレーションの暗黙確認
    agent = StageBoundAgent(stage_name="thumbnail", db_path=str(db_file))
    
    # 2. タスク登録 (リトライ数1)
    task_id = "task_p27_thumb"
    await agent.register_task(task_id=task_id, initial_status="READY", max_retries=1)
    
    # 3. 連携コンテキスト定義とタスク解決実行
    class CustomContext:
        def __init__(self, out_dir):
            self.output_dir = out_dir
            self.width = 1280
            self.height = 720
            self.text = "P27 Verification"
            
    ctx = CustomContext(output_dir)
    
    async def process_task(tid):
        return await resolve_thumbnail_task(ctx, tid)
        
    await agent.start(process_task)
    
    # 完了待機
    for _ in range(30):
        await asyncio.sleep(0.1)
        status = await agent.get_task_status(task_id)
        if status in ("COMPLETED", "FAILED"):
            break
            
    await agent.stop()
    
    assert status == "COMPLETED", f"Task execution failed with status: {status}"
    
    # 4. 結果保存とDB連携確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, error, retry_count FROM tasks WHERE id = ?", (task_id,))
    result_str, error, retry_count = cursor.fetchone()
    assert result_str is not None, "Task result should be saved"
    
    result_data = json.loads(result_str)
    img_path = Path(result_data["path"])
    
    # 5. 品質基準の検証 (解像度 >= 1280x720, 16:9, < 4MB, 破損なし)
    check_result = run_thumbnail_quality_check(img_path)
    assert check_result["status"] == "OK"
    assert check_result["width"] >= 1280
    assert check_result["height"] >= 720
    assert abs((check_result["width"] / check_result["height"]) - (16.0 / 9.0)) <= 0.01
    assert check_result["size_bytes"] < 4 * 1024 * 1024


def test_run_thumbnail_quality_check_errors(tmp_path):
    from PIL import Image
    from backend.tests._phase_g_scan import run_thumbnail_quality_check

    # 1. ファイル不在ケース (L154)
    non_existent = tmp_path / "does_not_exist.png"
    with pytest.raises(FileNotFoundError) as exc_info:
        run_thumbnail_quality_check(non_existent)
    assert "Thumbnail file not found" in str(exc_info.value)

    # 2. ファイルサイズ超過ケース (L158)
    large_file = tmp_path / "large_file.png"
    large_file.write_bytes(b"\x00" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError) as exc_info:
        run_thumbnail_quality_check(large_file)
    assert "File size exceeds 4MB limit" in str(exc_info.value)

    # 3. 画像破損ケース (L166-167)
    corrupted_file = tmp_path / "corrupted.png"
    corrupted_file.write_bytes(b"invalid image data that is small")
    with pytest.raises(ValueError) as exc_info:
        run_thumbnail_quality_check(corrupted_file)
    assert "Image is corrupted or invalid" in str(exc_info.value)

    # 4. 解像度不足ケース (L170)
    low_res_file = tmp_path / "low_res.png"
    img = Image.new("RGB", (640, 360))
    img.save(low_res_file, "PNG")
    with pytest.raises(ValueError) as exc_info:
        run_thumbnail_quality_check(low_res_file)
    assert "Resolution must be at least 1280x720" in str(exc_info.value)

    # 5. アスペクト比不正ケース (L174)
    bad_aspect_file = tmp_path / "bad_aspect.png"
    img = Image.new("RGB", (1280, 1280))
    img.save(bad_aspect_file, "PNG")
    with pytest.raises(ValueError) as exc_info:
        run_thumbnail_quality_check(bad_aspect_file)
    assert "Aspect ratio must be 16:9" in str(exc_info.value)


def test_phase_g_scan_edge_cases(tmp_path, capsys):
    # 特定の未カバー分岐をすべてカバーするためのエッジケーステスト
    custom_files = {
        # 1. 86->84: AST上でprint文が検出されるが、実際のファイル内の行数がそれより少ないケース
        "dummy_service.py": "print('hello')",
        
        # 2. 112->119: quality_gate_plugins.py に except も pass も含まれないケース
        "quality_gate_plugins.py": "clean_code = True",
        
        # 3. 127->136: audio_master.py に duck_amount が含まれないケース
        "audio_master.py": "plain_audio_logic = True",
        
        "pipeline_router.py": "no assets here",
        "governance.py": "smartcut = True",
        "ProductionPipeline.jsx": "plain jsx"
    }

    files = create_base_mocks(tmp_path, custom_files)

    def mock_rglob(self, *args, **kwargs):
        pattern = args[0] if args else kwargs.get("pattern", "*.py")
        if pattern == "*.py":
            return files
        return []

    def mock_read_text(self, *args, **kwargs):
        p_str = str(self)
        for fname, content in custom_files.items():
            if fname in p_str.replace("\\", "/"):
                return content
        return ""

    def mock_relative_to(self, *args, **kwargs):
        return Path(self.name)

    # ast.walk をモックして、dummy_service.py の解析時に行数を超える print ノードを偽装
    original_walk = ast.walk
    def mock_walk_edge(tree):
        for node in original_walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                node.lineno = 100
            yield node

    with patch.object(Path, "rglob", side_effect=mock_rglob, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch.object(ast, "walk", side_effect=mock_walk_edge), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")

    # 4. 130->136（duck_amountはあるがdef duck_bgmがない）と、
    # 5. 115->119（exceptはあるが改行passではない）のテスト
    custom_files_2 = {
        "quality_gate_plugins.py": "try:\n    pass\nexcept Exception: pass",
        "audio_master.py": "duck_amount = 0.5\n",
        "pipeline_router.py": "no assets",
        "governance.py": "smartcut = True",
        "ProductionPipeline.jsx": "plain jsx"
    }
    
    files_2 = create_base_mocks(tmp_path, custom_files_2)
    def mock_rglob_2(self, *args, **kwargs):
        if args and args[0] == "*.py":
            return files_2
        return []
    def mock_read_text_2(self, *args, **kwargs):
        p_str = str(self)
        for fname, content in custom_files_2.items():
            if fname in p_str.replace("\\", "/"):
                return content
        return ""

    with patch.object(Path, "rglob", side_effect=mock_rglob_2, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text_2, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")

    # 6. 132->136（sidechaincompressがあり、その前にduck_amountがない）のテスト
    duck_fn_content = (
        "def duck_bgm():\n"
        "    # sidechaincompress があり、その前に duck_amount がない\n"
        "    sidechaincompress = True\n"
        "    duck_amount = 0.5\n"
    )
    custom_files_3 = {
        "audio_master.py": f"duck_amount = 0.5\n{duck_fn_content}",
        "quality_gate_plugins.py": "clean = True",
        "pipeline_router.py": "no assets",
        "governance.py": "smartcut = True",
        "ProductionPipeline.jsx": "plain jsx"
    }
    files_3 = create_base_mocks(tmp_path, custom_files_3)
    def mock_rglob_3(self, *args, **kwargs):
        if args and args[0] == "*.py":
            return files_3
        return []
    def mock_read_text_3(self, *args, **kwargs):
        p_str = str(self)
        for fname, content in custom_files_3.items():
            if fname in p_str.replace("\\", "/"):
                return content
        return ""

    with patch.object(Path, "rglob", side_effect=mock_rglob_3, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text_3, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")


def test_phase_g_scan_exception_handling(tmp_path, capsys):
    # ファイル読み込みやAST解析で例外が発生した際のエラーハンドリングと警告出力の検証
    custom_files = {
        "error_file.py": "dummy",
        "pipeline_router.py": "no assets",
        "governance.py": "smartcut = True",
        "quality_gate_plugins.py": "clean = True",
        "audio_master.py": "plain_audio",
        "ProductionPipeline.jsx": "plain jsx"
    }
    
    files = create_base_mocks(tmp_path, custom_files)
    
    def mock_rglob(self, *args, **kwargs):
        return files

    def mock_read_text(self, *args, **kwargs):
        raise OSError("Simulated read text failure")

    def mock_relative_to(self, *args, **kwargs):
        return Path(self.name)

    with patch.object(Path, "rglob", side_effect=mock_rglob, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch("pathlib.Path.exists", return_value=True):
        
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")
        
    captured = capsys.readouterr()
    output = captured.out
    assert "Warning: Failed to scan" in output



def test_phase_g_scan_specific_exceptions(tmp_path, capsys):
    # OSError, SyntaxError がそれぞれ正しくキャッチされることを検証する
    custom_files = {
        "os_error_file.py": "def f(): pass",  # OSError を発生させる
        "syntax_error_file.py": "def f(;",    # SyntaxError を発生させる
        "pipeline_router.py": "no assets",
        "governance.py": "smartcut = True",
        "quality_gate_plugins.py": "clean = True",
        "audio_master.py": "plain_audio",
        "ProductionPipeline.jsx": "plain jsx"
    }
    files = create_base_mocks(tmp_path, custom_files)
    
    def mock_rglob(self, *args, **kwargs):
        return files
        
    def mock_read_text(self, *args, **kwargs):
        p_str = str(self)
        if "os_error_file.py" in p_str:
            raise OSError("Simulated disk error")
        for fname, content in custom_files.items():
            if fname in p_str.replace("\\", "/"):
                return content
        return ""
        
    def mock_relative_to(self, *args, **kwargs):
        return Path(self.name)
        
    with patch.object(Path, "rglob", side_effect=mock_rglob, autospec=True), \
         patch.object(Path, "read_text", side_effect=mock_read_text, autospec=True), \
         patch.object(Path, "relative_to", side_effect=mock_relative_to, autospec=True), \
         patch("pathlib.Path.exists", return_value=True):
         
        sys.modules.pop("backend.tests._phase_g_scan", None)
        runpy.run_module("backend.tests._phase_g_scan", run_name="__main__")
        
    captured = capsys.readouterr()
    output = captured.out
    
    # os_error_file.py で N-series と M-series 両方で OSError がキャッチされ警告が出ることをアサート
    assert "Warning: Failed to scan" in output
    assert "os_error_file.py for N-series: Simulated disk error" in output
    assert "os_error_file.py for M-series: Simulated disk error" in output
    # syntax_error_file.py で M-series で SyntaxError がキャッチされ警告が出ることをアサート
    assert "syntax_error_file.py for M-series: invalid syntax" in output
