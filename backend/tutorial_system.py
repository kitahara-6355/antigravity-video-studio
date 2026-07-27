"""
Interactive Tutorial System for First-Time Users
Phase 29 - User Onboarding Enhancement
"""

from typing import List, Dict, Optional, Any
from pydantic import BaseModel

class TutorialStep(BaseModel):
    id: str
    title: str
    description: str
    action: str  # e.g., "click", "select", "wait"
    target: str  # CSS selector or element description
    tooltip: str
    completed: bool = False

class Tutorial:
    """First-time user tutorial system"""
    
    def __init__(self):
        self.steps = self._create_default_steps()
    
    def _create_default_steps(self) -> List[TutorialStep]:
        """Initialize tutorial steps for Phase 28 features"""
        return [
            TutorialStep(
                id="step1",
                title="プリセット選択",
                description="まず、動画の雰囲気に合ったカラープリセットを選びましょう",
                action="select",
                target="button[data-preset]",
                tooltip="Cinematic（映画風）、Warm（温かい）などから選べます"
            ),
            TutorialStep(
                id="step2",
                title="プレビュー生成",
                description="「Generate Preview」をクリックして、プレビューを生成します",
                action="click",
                target="button:has-text('Generate Preview')",
                tooltip="約15秒でプレビューが完成します"
            ),
            TutorialStep(
                id="step3",
                title="結果確認",
                description="生成されたプレビューを再生して、仕上がりを確認しましょう",
                action="wait",
                target="video",
                tooltip="字幕、カラー、音質をチェックしてください"
            ),
            TutorialStep(
                id="step4",
                title="完了",
                description="基本的な使い方を学習しました！",
                action="complete",
                target="",
                tooltip="実際のプロジェクトで使ってみましょう"
            )
        ]
    
    def _find_first_uncompleted_step(self) -> Optional[TutorialStep]:
        """Find and return the first step that is not completed"""
        for step in self.steps:
            if not step.completed:
                return step
        return None

    def _get_last_step(self) -> Optional[TutorialStep]:
        """Return the last step in the tutorial"""
        return self.steps[-1]

    def get_current_step(self) -> Optional[TutorialStep]:
        """Get the current uncompleted step"""
        if not self.steps:
            return None
        
        uncompleted_step = self._find_first_uncompleted_step()
        if uncompleted_step is not None:
            return uncompleted_step
                
        return self._get_last_step()
    
    def mark_completed(self, step_id: str):
        """Mark a step as completed"""
        for step in self.steps:
            if step.id == step_id:
                step.completed = True
                break
    
    def _calculate_progress_percentage(self, completed_count: int, total_count: int) -> int:
        """Calculate the progress percentage"""
        if total_count <= 0:
            return 0
        return int((completed_count / total_count) * 100)
    
    def _count_completed_steps(self) -> int:
        """Count the number of completed steps"""
        return sum(1 for step in self.steps if step.completed)

    def get_progress(self) -> Dict[str, Any]:
        """Get tutorial progress metrics"""
        completed = self._count_completed_steps()
        total = len(self.steps)
        percentage = self._calculate_progress_percentage(completed, total)
        return {
            "total": total,
            "completed": completed,
            "percentage": percentage
        }
    
    def reset(self):
        """Reset all steps to uncompleted"""
        for step in self.steps:
            step.completed = False

# Global instance
tutorial_system = Tutorial()
