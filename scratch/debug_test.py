import asyncio
import logging
import sys
sys.path.insert(0, 'backend')

logging.basicConfig(level=logging.INFO)

from agents.stage_bound_agent import StageBoundAgent
from create_subtitle_samples import resolve_subtitle_thumbnail_task
from services.thumbnail_analyzer import ThumbnailAnalyzer

async def test_subtitle_failure():
    print("=== Testing Subtitle Failure ===")
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test.db"
        agent = StageBoundAgent(
            stage_name="subtitle_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )
        
        task_id = "test_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)
        
        # 例外を起こすために無効なパスを設定
        agent.output_dir = "/invalid/path/that/does/not/exist/or/allow/writing"
        
        async def process_task(tid):
            print(f"Executing process_task for {tid}")
            res = await resolve_subtitle_thumbnail_task(agent, tid)
            print(f"process_task completed with: {res}")
            return res
            
        await agent.start(process_task)
        
        # 完了または失敗を待つ
        for _ in range(30):
            status = await agent.get_task_status(task_id)
            print(f"Current status: {status}")
            if status in ["COMPLETED", "FAILED"]:
                break
            await asyncio.sleep(0.1)
            
        status = await agent.get_task_status(task_id)
        print(f"Final status: {status}")
        await agent.stop()

async def test_analyzer_failure():
    print("=== Testing Analyzer Failure ===")
    import tempfile
    from pathlib import Path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_analyzer.db"
        agent = StageBoundAgent(
            stage_name="thumbnail_analyzer",
            db_path=str(db_file),
            poll_interval=0.01
        )
        
        task_id = "test_analyzer_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)
        
        analyzer = ThumbnailAnalyzer()
        analyzer.width = 100
        analyzer.height = 720
        
        async def process_task(tid):
            print(f"Executing analyzer process_task for {tid}")
            res = await analyzer.resolve_thumbnail_task(tid, output_dir=str(tmpdir))
            print(f"analyzer process_task completed with: {res}")
            return res
            
        await agent.start(process_task)
        
        # 完了または失敗を待つ
        for _ in range(30):
            status = await agent.get_task_status(task_id)
            print(f"Current status: {status}")
            if status in ["COMPLETED", "FAILED"]:
                break
            await asyncio.sleep(0.1)
            
        status = await agent.get_task_status(task_id)
        print(f"Final status: {status}")
        await agent.stop()

if __name__ == "__main__":
    asyncio.run(test_subtitle_failure())
    asyncio.run(test_analyzer_failure())
