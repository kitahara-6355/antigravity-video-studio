import pytest
from backend.agents.orchestration.wave_scheduler import WaveScheduler

def test_wave_scheduler_50_plus_tasks_simulation():
    # 55件のダミータスクを作成
    tasks = [{"id": f"T-{i}", "name": f"Task {i}"} for i in range(55)]
    
    # wave_size = 10 で初期化
    scheduler = WaveScheduler(default_wave_size=10)
    
    # 実行
    waves = scheduler.schedule_waves(tasks)
    
    # 期待される結果:
    # 55件のタスクが wave_size=10 に分割されるため、6つの wave になるはず (10, 10, 10, 10, 10, 5)
    assert len(waves) == 6
    assert len(waves[0]) == 10
    assert len(waves[5]) == 5
    
    # 全てのタスクが重複・漏れなく順序維持されて格納されていることを確認
    flat_tasks = [t for wave in waves for t in wave]
    assert len(flat_tasks) == 55
    assert flat_tasks[0]["id"] == "T-0"
    assert flat_tasks[54]["id"] == "T-54"

def test_wave_scheduler_boundary_exact_multiple():
    # ちょうど 60 件のタスク (wave_size = 20)
    tasks = [{"id": f"T-{i}"} for i in range(60)]
    scheduler = WaveScheduler(default_wave_size=20)
    waves = scheduler.schedule_waves(tasks)
    
    # 期待される結果: 3つの wave に綺麗に等分割 (20, 20, 20)
    assert len(waves) == 3
    assert all(len(w) == 20 for w in waves)

def test_wave_scheduler_invalid_inputs_robustness():
    scheduler = WaveScheduler(default_wave_size=30)
    
    # None入力時のフォールバック (空リスト)
    assert scheduler.schedule_waves(None) == []
    
    # 不適切な型 (文字列、辞書など)
    assert scheduler.schedule_waves("not-an-iterable") == []
    assert scheduler.schedule_waves({"a": 1}) == []
