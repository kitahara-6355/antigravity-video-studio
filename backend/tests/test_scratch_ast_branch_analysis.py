import ast
import tempfile
import pytest
import sys
import runpy
from pathlib import Path

# 同一ディレクトリ内のモジュールを優先インポート
sys.path.insert(0, str(Path(__file__).parent))
try:
    from ast_branch_analysis import BranchCounter, analyze_file, main
except ImportError:
    from tests.scratch.ast_branch_analysis import BranchCounter, analyze_file, main

def test_branch_counter_simple():
    source = """
def simple_func(x):
    if x > 0:
        return 1
    return 0
"""
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    assert len(counter.branches) == 1
    assert counter.branches[0]["scope"] == "simple_func"
    assert counter.branches[0]["branch_count"] == 1

def test_branch_counter_inner_function_no_overlap():
    source = """
def outer_func(x):
    if x > 0:
        def inner_func(y):
            if y > 10:
                return y
            return 0
        return inner_func(x)
    return 0
"""
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    assert len(counter.branches) == 2
    branches_dict = {b["scope"]: b["branch_count"] for b in counter.branches}
    assert branches_dict["outer_func"] == 1
    assert branches_dict["outer_func.inner_func"] == 1

def test_branch_counter_class_methods():
    source = """
class MyClass:
    def method_one(self, x):
        if x:
            return 1
        return 0
    def method_two(self, y):
        for i in range(y):
            if i % 2 == 0:
                print(i)
"""
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    assert len(counter.branches) == 2
    branches_dict = {b["scope"]: b["branch_count"] for b in counter.branches}
    assert branches_dict["MyClass.method_one"] == 1
    assert branches_dict["MyClass.method_two"] == 2

def test_branch_counter_complex_structures():
    source = """
def complex_func(x, y):
    if x and y:
        try:
            val = x / y
        except ZeroDivisionError:
            val = 0
        except TypeError:
            val = -1
        else:
            val = val * 2
    res = 'even' if val % 2 == 0 else 'odd'
    while val < 10:
        val += 1
    return res
"""
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    assert len(counter.branches) == 1
    assert counter.branches[0]["branch_count"] == 7

def test_analyze_file_integration():
    source = """
def dummy():
    if True:
        pass
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write(source)
        temp_path = f.name
    try:
        result = analyze_file(temp_path)
        assert result["lines"] == 4
        assert result["total_branches"] == 1
        assert result["functions"] == ["dummy"]
        assert len(result["branch_details"]) == 1
        assert result["branch_details"][0]["scope"] == "dummy"
        assert result["branch_details"][0]["branch_count"] == 1
    finally:
        Path(temp_path).unlink()

def test_branch_counter_try_star():
    """except* (TryStar) 構文を含むコードの AST 解析のテスト"""
    source = """
def try_star_func():
    try:
        pass
    except* ValueError:
        pass
    except* TypeError:
        pass
"""
    tree = ast.parse(source)
    counter = BranchCounter()
    counter.visit(tree)
    assert len(counter.branches) == 1
    assert counter.branches[0]["branch_count"] == 2

def test_main_function_execution():
    """main() 関数の実行テスト（正常系・異常系・警告系のカバー）"""
    # 1. 存在しないファイルが含まれるケース（警告の出力）
    target_files_with_missing = [
        ("non_existent_file.py", "backend")
    ]
    res_missing = main(backend_dir=Path(__file__).parent, target_files=target_files_with_missing)
    assert res_missing["lines"] == 0
    assert res_missing["branches"] == 0

    # 2. 正常に存在するファイルが含まれるケースの解析（ブランチ数 0 の関数も含めてテスト）
    # dummy_zero_branch はブランチ数が 0 のため、出力部分の 0 branch パスを通る
    source_code = """def dummy():
    if True:
        pass

def dummy_zero_branch():
    pass
"""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", dir=Path(__file__).parent, delete=False) as f:
        f.write(source_code)
        temp_path = Path(f.name)
    
    try:
        # 相対パスを取得
        rel_path = temp_path.name
        target_files_ok = [
            (rel_path, "backend")
        ]
        res_ok = main(backend_dir=Path(__file__).parent, target_files=target_files_ok)
        assert res_ok["lines"] == 6
        assert res_ok["branches"] == 1
        assert res_ok["classes"] == 0
        assert res_ok["functions"] == 2
    finally:
        temp_path.unlink()

def test_main_function_default_args():
    """main() 関数のデフォルト引数 None, None での実行テスト（分岐網羅用）"""
    res = main()
    assert isinstance(res, dict)

def test_main_script_execution():
    """__name__ == '__main__' のスクリプト実行をカバーするテスト"""
    script_path = Path(__file__).parent / "scratch" / "ast_branch_analysis.py"
    try:
        runpy.run_path(str(script_path), run_name="__main__")
    except SystemExit:
        pass


# ============================================================
# サムネイル生成・品質検証・StageBoundAgent連携テスト
# ============================================================
import json
import asyncio
from PIL import Image
from agents.stage_bound_agent import StageBoundAgent

# 追加インポート
try:
    from ast_branch_analysis import generate_thumbnail, validate_thumbnail, resolve_thumbnail_task
except ImportError:
    from tests.scratch.ast_branch_analysis import generate_thumbnail, validate_thumbnail, resolve_thumbnail_task

def test_generate_and_validate_thumbnail_success(tmp_path):
    output_file = tmp_path / "valid_thumb.png"
    # 1280x720, 16:9 の正常な画像を生成
    generate_thumbnail(output_file, width=1280, height=720, text="Test PNG")
    
    assert output_file.exists()
    
    # 品質検証
    info = validate_thumbnail(output_file)
    assert info["width"] == 1280
    assert info["height"] == 720
    assert info["size_bytes"] > 0
    assert info["size_bytes"] < 4 * 1024 * 1024
    assert info["path"] == str(output_file)

def test_validate_thumbnail_failures(tmp_path):
    # 1. 存在しないファイル
    non_existent = tmp_path / "non_existent.png"
    with pytest.raises(FileNotFoundError):
        validate_thumbnail(non_existent)
        
    # 2. 解像度不足
    low_res_file = tmp_path / "low_res.png"
    generate_thumbnail(low_res_file, width=100, height=100)
    with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
        validate_thumbnail(low_res_file)
        
    # 3. アスペクト比異常
    bad_aspect_file = tmp_path / "bad_aspect.png"
    generate_thumbnail(bad_aspect_file, width=1280, height=1000)
    with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
        validate_thumbnail(bad_aspect_file)
        
    # 4. 破損ファイル (Pillowロード不可)
    corrupted_file = tmp_path / "corrupted.png"
    with open(corrupted_file, "wb") as f:
        f.write(b"not an image file data")
    with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
        validate_thumbnail(corrupted_file)

    # 5. 引数のバリデーション (値が整数ではない)
    with pytest.raises(ValueError, match="Width and height must be integers"):
        generate_thumbnail(tmp_path / "err.png", width="invalid", height=720)
        
    with pytest.raises(ValueError, match="Width and height must be positive integers"):
        generate_thumbnail(tmp_path / "err.png", width=-100, height=720)

def test_validate_thumbnail_file_size(tmp_path, monkeypatch):
    # 4MB以上のファイルをシミュレートするためのモック
    large_file = tmp_path / "large.png"
    generate_thumbnail(large_file, width=1280, height=720)
    
    class MockStat:
        def __init__(self, size, original):
            self.st_size = size
            self.st_mode = original.st_mode
            self.st_mtime = original.st_mtime
            self.st_atime = original.st_atime
            self.st_ctime = original.st_ctime
            
    original_stat = Path.stat
    def mock_stat(self, *args, **kwargs):
        orig = original_stat(self, *args, **kwargs)
        if str(self) == str(large_file):
            return MockStat(5 * 1024 * 1024, orig)
        return orig
        
    monkeypatch.setattr(Path, "stat", mock_stat)
    
    with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
        validate_thumbnail(large_file)

@pytest.mark.asyncio
async def test_resolve_thumbnail_task_stage_bound_agent_integration(tmp_path):
    # StageBoundAgent 用の設定
    db_file = str(tmp_path / "tasks.db")
    agent = StageBoundAgent(stage_name="thumbnail_stage", db_path=db_file, poll_interval=0.02)
    
    # タスク処理用の設定
    agent.output_dir = tmp_path / "output"
    agent.width = 1920
    agent.height = 1080
    agent.text = "Agent Output"
    
    task_id = "task_integration_test_001"
    
    # タスク登録
    await agent.register_task(task_id, initial_status="READY")
    
    # エージェント開始
    async def process_func(t_id):
        return await resolve_thumbnail_task(agent, t_id)
    await agent.start(process_func)
    
    # タスク完了を待つ (タイムアウト 5 秒)
    completed = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        status = await agent.get_task_status(task_id)
        if status == "COMPLETED":
            completed = True
            break
            
    await agent.stop()
    assert completed
    
    # DBから結果を確認
    conn = agent._get_conn()
    cursor = conn.execute("SELECT result, status, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    result_str, status, error = row[0], row[1], row[2]
    conn.close()
    
    assert status == "COMPLETED"
    assert error is None
    
    result_info = json.loads(result_str)
    assert result_info["width"] == 1920
    assert result_info["height"] == 1080
    assert Path(result_info["path"]).exists()

@pytest.mark.asyncio
async def test_stage_bound_agent_retry_on_failure(tmp_path):
    db_file = str(tmp_path / "tasks_retry.db")
    agent = StageBoundAgent(stage_name="retry_stage", db_path=db_file, poll_interval=0.02)
    
    # 意図的に失敗する process_func (例外を投げる)
    call_count = 0
    def failing_process(task_id):
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"Simulated failure {call_count}")
        
    task_id = "retry_task_001"
    # max_retries = 2 で登録
    await agent.register_task(task_id, initial_status="READY", max_retries=2)
    
    await agent.start(failing_process)
    
    # FAILED になるのを待つ
    failed = False
    for _ in range(50):
        await asyncio.sleep(0.1)
        status = await agent.get_task_status(task_id)
        if status == "FAILED":
            failed = True
            break
            
    await agent.stop()
    assert failed
    assert call_count == 3  # 初回(1) + リトライ(2) = 3 回呼び出されるはず
    
    # DB内の結果を検証
    conn = agent._get_conn()
    cursor = conn.execute("SELECT status, retry_count, error FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    status, retry_count, error = row[0], row[1], row[2]
    conn.close()
    
    assert status == "FAILED"
    assert retry_count == 2
    assert "Simulated failure 3" in error


def test_generate_thumbnail_existing_output(tmp_path):
    output_file = tmp_path / "exist_thumb.png"
    # 事前にファイルを作っておく
    output_file.write_text("dummy content", encoding="utf-8")
    assert output_file.exists()
    
    # 既存のファイルを上書きするように generate_thumbnail を呼ぶ
    generate_thumbnail(output_file, width=1280, height=720, text="Overwritten")
    
    assert output_file.exists()
    info = validate_thumbnail(output_file)
    assert info["width"] == 1280
    assert info["height"] == 720


def test_generate_thumbnail_atomic_write_failure_cleanup(tmp_path, monkeypatch):
    from PIL import Image
    output_file = tmp_path / "fail_thumb.png"
    
    # save() が呼ばれたら RuntimeError を発生させる
    def mock_save(*args, **kwargs):
        raise RuntimeError("Simulated save failure")
    
    monkeypatch.setattr(Image.Image, "save", mock_save)
    
    with pytest.raises(RuntimeError, match="Simulated save failure"):
        generate_thumbnail(output_file, width=1280, height=720, text="Should fail")
        
    # temp_path も output_file も存在しないことを確認
    assert not output_file.exists()
    # temp_path は suffix が .[uuid].tmp の形式
    temp_files = list(tmp_path.glob("*.tmp"))
    assert len(temp_files) == 0


def test_generate_thumbnail_atomic_write_failure_cleanup_unlink_error(tmp_path, monkeypatch):
    import pathlib
    output_file = tmp_path / "fail_unlink_thumb.png"
    
    # 2026-07-26: 以前は hasattr(pathlib, "WindowsPath") で分岐していたが、
    # WindowsPath は Linux でもクラスとして存在する（インスタンス化できないだけ）ため
    # Linux でも WindowsPath を選んでしまい、実際に使われる PosixPath に効かなかった。
    # 実際に生成されたオブジェクトの具象クラスを使えば、どちらの環境でも正しい。
    path_class = type(output_file)
    
    # rename() が呼ばれたら RuntimeError を発生させる
    orig_rename = path_class.rename
    def mock_rename(self, *args, **kwargs):
        if ".tmp" in self.name:
            raise RuntimeError("Simulated rename failure")
        return orig_rename(self, *args, **kwargs)
    
    # Path.unlink() が呼ばれたら例外（OSError）を発生させる
    orig_unlink = path_class.unlink
    def mock_unlink(self, *args, **kwargs):
        if ".tmp" in self.name:
            raise OSError("Simulated unlink failure")
        return orig_unlink(self, *args, **kwargs)
    
    monkeypatch.setattr(path_class, "rename", mock_rename)
    monkeypatch.setattr(path_class, "unlink", mock_unlink)
    
    with pytest.raises(RuntimeError, match="Simulated rename failure"):
        generate_thumbnail(output_file, width=1280, height=720, text="Should fail rename and unlink")
        
    assert not output_file.exists()




def test_validate_thumbnail_corrupted_load_failure(tmp_path, monkeypatch):
    from PIL import Image
    output_file = tmp_path / "load_fail_thumb.png"
    generate_thumbnail(output_file, width=1280, height=720)
    
    # load() が呼ばれたら RuntimeError を発生させる
    def mock_load(*args, **kwargs):
        raise RuntimeError("Simulated load failure")
        
    monkeypatch.setattr(Image.Image, "load", mock_load)
    
    with pytest.raises(ValueError, match="Image is corrupted or invalid format: Simulated load failure"):
        validate_thumbnail(output_file)


def test_analyze_file_syntax_error():
    """analyze_file が構文エラーのあるファイルで SyntaxError をスローすることを検証"""
    source = "def invalid_syntax("
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", delete=False) as f:
        f.write(source)
        temp_path = f.name
    try:
        with pytest.raises(SyntaxError):
            analyze_file(temp_path)
    finally:
        Path(temp_path).unlink()


def test_main_handles_faulty_files():
    """main 関数が構文エラーのあるファイルや読み込みエラーのあるファイルを適切にスキップし、正常終了することを検証"""
    source_ok = """def ok_func():
    if True:
        pass
"""
    source_bad = "def invalid_syntax("
    
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", dir=Path(__file__).parent, delete=False) as f_ok:
        f_ok.write(source_ok)
        path_ok = Path(f_ok.name)
        
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", encoding="utf-8", dir=Path(__file__).parent, delete=False) as f_bad:
        f_bad.write(source_bad)
        path_bad = Path(f_bad.name)
        
    try:
        target_files = [
            (path_ok.name, "backend"),
            (path_bad.name, "backend"),
            ("non_existent_file.py", "backend"), # 存在しないファイルも含める
        ]
        
        # main を実行してクラッシュしないことを確認
        res = main(backend_dir=Path(__file__).parent, target_files=target_files)
        
        # 正常なファイルのみが集計されていることを確認
        assert res["lines"] == 3
        assert res["branches"] == 1
    finally:
        if path_ok.exists():
            path_ok.unlink()
        if path_bad.exists():
            path_bad.unlink()


