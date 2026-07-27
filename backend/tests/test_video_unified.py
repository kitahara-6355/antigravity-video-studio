import sys
import os
import asyncio
import pytest
from unittest.mock import MagicMock
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from archives.unified.video_unified import VideoUnified, VideoProcessPhase, VideoTask


@pytest.fixture
def video_engine():
    engine = VideoUnified()
    yield engine
    # Cleanup
    engine._tasks.clear()
    engine._progress_callbacks.clear()


def test_create_task_limit_memory_leak_prevention(video_engine):
    # Verify MAX_TASKS limit
    video_engine.MAX_TASKS = 10
    
    # Create tasks exceeding the limit
    for i in range(15):
        video_engine.create_task(
            task_id=f"task_{i}",
            video_paths=["test.mp4"],
            output_name=f"output_{i}"
        )
        
    # Ensure task count doesn't exceed MAX_TASKS
    assert len(video_engine._tasks) == 10
    # Old tasks should be deleted
    assert "task_0" not in video_engine._tasks
    assert "task_14" in video_engine._tasks


def test_remove_task_and_clear_completed(video_engine):
    video_engine.create_task(
        task_id="task_1",
        video_paths=["test.mp4"]
    )
    video_engine.create_task(
        task_id="task_2",
        video_paths=["test.mp4"]
    )
    
    # Explicit removal
    assert video_engine.remove_task("task_1") is True
    assert "task_1" not in video_engine._tasks
    assert video_engine.remove_task("task_nonexistent") is False
    
    # Clear completed/error tasks
    task2 = video_engine.get_task("task_2")
    task2.phase = VideoProcessPhase.COMPLETE
    
    deleted_count = video_engine.clear_completed_tasks()
    assert deleted_count == 1
    assert "task_2" not in video_engine._tasks


def test_progress_callback_memory_leak_prevention(video_engine):
    callback_called = []
    
    def my_callback(task):
        callback_called.append(task.task_id)
        
    video_engine.set_progress_callback(my_callback)
    
    # Ensure duplicate callback is prevented
    video_engine.set_progress_callback(my_callback)
    assert len(video_engine._progress_callbacks) == 1
    
    video_engine.create_task("task_callback", ["test.mp4"])
    video_engine.update_progress("task_callback", 50.0)
    assert len(callback_called) == 1
    assert callback_called[0] == "task_callback"
    
    # Remove callback
    video_engine.remove_progress_callback(my_callback)
    assert len(video_engine._progress_callbacks) == 0
    
    # Trigger progress update after removal
    video_engine.update_progress("task_callback", 80.0)
    assert len(callback_called) == 1  # Should not increase


def test_storage_stats_caching(video_engine):
    # First call
    stats1 = video_engine.get_storage_stats()
    
    # Cache should be populated
    assert video_engine._stats_cache is not None
    assert video_engine._stats_cache_time is not None
    
    # Second call should return cached stats
    stats2 = video_engine.get_storage_stats()
    assert stats1 == stats2


@pytest.mark.asyncio
async def test_async_helpers(video_engine):
    # Async wrapper checks
    stats = await video_engine.async_get_storage_stats()
    assert isinstance(stats, dict)
    
    cleanup_result = await video_engine.async_cleanup_old_files(days=7)
    assert isinstance(cleanup_result, dict)
    assert "drafts" in cleanup_result
    assert "previews" in cleanup_result


def test_update_progress_callback_modification_safety(video_engine):
    calls = []
    
    def self_removing_callback(task):
        calls.append(task.task_id)
        video_engine.remove_progress_callback(self_removing_callback)
        
    video_engine.set_progress_callback(self_removing_callback)
    video_engine.create_task("task_test_safety", ["test.mp4"])
    video_engine.update_progress("task_test_safety", 50.0)
    assert len(calls) == 1
    assert len(video_engine._progress_callbacks) == 0


def test_create_task_max_tasks_while_loop(video_engine):
    video_engine.MAX_TASKS = 5
    for i in range(10):
        task = VideoTask(
            task_id=f"huge_{i}",
            video_paths=["test.mp4"],
            output_name=f"out_{i}"
        )
        video_engine._tasks[task.task_id] = task
        
    assert len(video_engine._tasks) == 10
    
    video_engine.create_task("new_task_trigger", ["test.mp4"])
    assert len(video_engine._tasks) == 5
    assert "new_task_trigger" in video_engine._tasks


def test_cleanup_old_files_protection(video_engine, tmp_path):
    import shutil
    from datetime import datetime, timedelta
    
    draft_dir = tmp_path / "drafts"
    preview_dir = tmp_path / "previews"
    draft_dir.mkdir()
    preview_dir.mkdir()
    
    video_engine._draft_dir = draft_dir
    video_engine._preview_dir = preview_dir
    
    normal_file = draft_dir / "old_normal.txt"
    protected_subdir = draft_dir / "raw_videos"
    protected_subdir.mkdir()
    protected_file = protected_subdir / "old_file.txt"
    
    normal_file.write_text("normal", encoding="utf-8")
    protected_file.write_text("protected", encoding="utf-8")
    
    past_time = (datetime.now() - timedelta(days=10)).timestamp()
    os.utime(normal_file, (past_time, past_time))
    os.utime(protected_file, (past_time, past_time))
    
    deleted = video_engine.cleanup_old_files(days=7)
    
    assert normal_file.exists() is False
    assert protected_file.exists() is True
    assert deleted["drafts"] == 1


def test_create_task_max_tasks_with_inactive_cleanup(video_engine):
    video_engine.MAX_TASKS = 3
    
    video_engine.create_task("task_complete", ["test.mp4"])
    video_engine.get_task("task_complete").phase = VideoProcessPhase.COMPLETE
    
    video_engine.create_task("task_error", ["test.mp4"])
    video_engine.get_task("task_error").phase = VideoProcessPhase.ERROR
    
    video_engine.create_task("task_running", ["test.mp4"])
    video_engine.get_task("task_running").phase = VideoProcessPhase.EDIT
    
    assert len(video_engine._tasks) == 3
    
    video_engine.create_task("new_task", ["test.mp4"])
    
    assert len(video_engine._tasks) == 3
    assert "task_running" in video_engine._tasks
    assert "new_task" in video_engine._tasks
    assert ("task_complete" not in video_engine._tasks) or ("task_error" not in video_engine._tasks)


def test_set_progress_callback_type_error(video_engine):
    # Verify TypeError is raised when passing non-callable object
    with pytest.raises(TypeError, match="callback must be a callable object"):
        video_engine.set_progress_callback("not_callable")


@pytest.mark.asyncio
async def test_process_video_error_handling(video_engine):
    task_id = "task_error_handling"
    video_engine.create_task(task_id, ["test.mp4"])
    
    # 1. ValueError during video processing
    async def mock_analyze_value_error(task):
        raise ValueError("Invalid video format")
        
    video_engine._analyze_videos = mock_analyze_value_error
    task = await video_engine.process_video(task_id)
    assert task.phase == VideoProcessPhase.ERROR
    assert "ValidationError" in task.error
    assert "Invalid video format" in task.error

    # 2. OSError during video processing
    async def mock_analyze_os_error(task):
        err = OSError("No space left on device")
        err.errno = 28
        err.strerror = "No space left on device"
        raise err
        
    video_engine._analyze_videos = mock_analyze_os_error
    task = await video_engine.process_video(task_id)
    assert task.phase == VideoProcessPhase.ERROR
    assert "IOError" in task.error
    assert "28" in task.error
    assert "No space left on device" in task.error

    # 3. Unexpected Exception during video processing
    async def mock_analyze_unexpected(task):
        raise RuntimeError("Unexpected engine crash")
        
    video_engine._analyze_videos = mock_analyze_unexpected
    task = await video_engine.process_video(task_id)
    assert task.phase == VideoProcessPhase.ERROR
    assert "UnexpectedError" in task.error
    assert "Unexpected engine crash" in task.error


def test_progress_callback_exception_isolation(video_engine):
    calls = []
    
    def bad_callback(task):
        raise RuntimeError("Callback failed")
        
    def good_callback(task):
        calls.append(task.task_id)
        
    video_engine.set_progress_callback(bad_callback)
    video_engine.set_progress_callback(good_callback)
    
    video_engine.create_task("task_isolated", ["test.mp4"])
    # Should not raise exception and good_callback should still be run
    video_engine.update_progress("task_isolated", 50.0)
    
    assert len(calls) == 1
    assert calls[0] == "task_isolated"


@pytest.mark.asyncio
async def test_process_video_success_path(video_engine):
    task_id = "task_success"
    video_engine.create_task(task_id, ["test.mp4"])
    
    # Run process_video and check if it transitions through all phases successfully
    task = await video_engine.process_video(task_id)
    assert task.phase == VideoProcessPhase.COMPLETE
    assert task.progress == 100.0
    assert task.output_path is not None
    assert "output" in task.output_path


@pytest.mark.asyncio
async def test_process_video_nonexistent_task(video_engine):
    with pytest.raises(ValueError, match="Task not found: nonexistent_id"):
        await video_engine.process_video("nonexistent_id")


def test_update_progress_nonexistent_task(video_engine):
    # Should complete without error when task_id doesn't exist
    video_engine.update_progress("nonexistent_id", 50.0)


def test_generate_preview_behaviors(video_engine):
    # Task doesn't exist
    assert video_engine.generate_preview("nonexistent_id") is None
    
    # Task exists but has no video paths
    video_engine.create_task("task_no_videos", [])
    assert video_engine.generate_preview("task_no_videos") is None
    
    # Success path
    video_engine.create_task("task_preview_success", ["test.mp4"])
    preview_path = video_engine.generate_preview("task_preview_success")
    assert preview_path is not None
    assert "task_preview_success_preview.mp4" in preview_path


def test_is_protected_logic(video_engine):
    assert video_engine.is_protected("c:/path/to/raw_videos/video.mp4") is True
    assert video_engine.is_protected("c:/path/to/final_output/video.mp4") is True
    assert video_engine.is_protected("c:/path/to/drafts/video.mp4") is False
