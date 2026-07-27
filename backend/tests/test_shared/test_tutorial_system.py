import pytest
from tutorial_system import Tutorial, TutorialStep

def test_tutorial_step_pydantic():
    step = TutorialStep(
        id="test",
        title="Test Title",
        description="Test Desc",
        action="click",
        target=".btn",
        tooltip="Tooltip",
        completed=False
    )
    assert step.id == "test"
    assert step.completed is False

def test_tutorial_init():
    t = Tutorial()
    assert len(t.steps) == 4
    assert t.steps[0].id == "step1"
    assert t.steps[1].id == "step2"
    assert t.steps[2].id == "step3"
    assert t.steps[3].id == "step4"

def test_get_current_step_uncompleted():
    t = Tutorial()
    current = t.get_current_step()
    assert current.id == "step1"

def test_mark_completed():
    t = Tutorial()
    t.mark_completed("step1")
    assert t.steps[0].completed is True
    assert t.steps[1].completed is False
    
    current = t.get_current_step()
    assert current.id == "step2"

def test_get_progress():
    t = Tutorial()
    progress = t.get_progress()
    assert progress["total"] == 4
    assert progress["completed"] == 0
    assert progress["percentage"] == 0
    
    t.mark_completed("step1")
    progress = t.get_progress()
    assert progress["completed"] == 1
    assert progress["percentage"] == 25
    
    t.mark_completed("step2")
    t.mark_completed("step3")
    t.mark_completed("step4")
    progress = t.get_progress()
    assert progress["completed"] == 4
    assert progress["percentage"] == 100

def test_get_current_step_all_completed():
    t = Tutorial()
    for step in t.steps:
        t.mark_completed(step.id)
    current = t.get_current_step()
    assert current.id == "step4"

def test_get_progress_empty_steps():
    t = Tutorial()
    t.steps = []
    progress = t.get_progress()
    assert progress["total"] == 0
    assert progress["completed"] == 0
    assert progress["percentage"] == 0

def test_get_current_step_empty_steps():
    t = Tutorial()
    t.steps = []
    current = t.get_current_step()
    assert current is None

def test_mark_completed_nonexistent_id():
    t = Tutorial()
    t.mark_completed("invalid_id")
    for step in t.steps:
        assert step.completed is False

def test_tutorial_reset():
    t = Tutorial()
    t.mark_completed("step1")
    assert t.steps[0].completed is True
    t.reset()
    assert t.steps[0].completed is False

def test_tutorial_instance_independence():
    """Verify that multiple Tutorial instances are independent and do not share state."""
    t1 = Tutorial()
    t2 = Tutorial()
    
    # Modify step in t1
    t1.mark_completed("step1")
    assert t1.steps[0].completed is True
    
    # t2 should remain unaffected
    assert t2.steps[0].completed is False
    
    # Check that they have distinct lists and step objects
    assert t1.steps is not t2.steps
    assert t1.steps[0] is not t2.steps[0]

def test_get_current_step_with_gaps():
    """Verify get_current_step when there are completed steps mixed with uncompleted steps."""
    t = Tutorial()
    # Mark step1 and step3 as completed, but leave step2 uncompleted
    t.mark_completed("step1")
    t.mark_completed("step3")
    
    # The current step should be step2 (the first uncompleted step)
    current = t.get_current_step()
    assert current.id == "step2"

def test_tutorial_step_validation_edge_cases():
    """Verify that TutorialStep validates fields correctly even with empty/special strings."""
    step = TutorialStep(
        id="",
        title="!@#$%^&*",
        description="A" * 1000,
        action="",
        target="",
        tooltip=""
    )
    assert step.id == ""
    assert step.title == "!@#$%^&*"
    assert len(step.description) == 1000
    assert step.completed is False

def test_tutorial_multi_step_scenario():
    """Verify a complete sequence of user interactions and progress metrics."""
    t = Tutorial()
    assert t.get_progress()["percentage"] == 0
    
    # 1. Complete step1
    t.mark_completed("step1")
    assert t.get_current_step().id == "step2"
    assert t.get_progress()["percentage"] == 25
    
    # 2. Complete step2
    t.mark_completed("step2")
    assert t.get_current_step().id == "step3"
    assert t.get_progress()["percentage"] == 50
    
    # 3. Complete step3
    t.mark_completed("step3")
    assert t.get_current_step().id == "step4"
    assert t.get_progress()["percentage"] == 75
    
    # 4. Complete step4
    t.mark_completed("step4")
    # When all completed, get_current_step should return the last step
    assert t.get_current_step().id == "step4"
    assert t.get_progress()["percentage"] == 100
    
    # 5. Reset
    t.reset()
    assert t.get_current_step().id == "step1"
    assert t.get_progress()["percentage"] == 0
    for step in t.steps:
        assert step.completed is False

def test_mark_completed_duplicate_ids():
    """Verify behavior of mark_completed when steps list contains duplicate step IDs."""
    t = Tutorial()
    # Artificially inject duplicate step
    duplicate_step = TutorialStep(
        id="step1",
        title="Duplicate Step 1",
        description="Duplicate",
        action="click",
        target="",
        tooltip=""
    )
    t.steps.append(duplicate_step)
    
    # There should be two steps with id="step1"
    assert len([s for s in t.steps if s.id == "step1"]) == 2
    
    # Mark step1 completed
    t.mark_completed("step1")
    
    # Since mark_completed breaks on the first match, only the first one should be completed
    assert t.steps[0].completed is True
    assert t.steps[-1].completed is False


def test_global_tutorial_system_instance():
    """Verify the global instance behavior and state management."""
    from tutorial_system import tutorial_system
    
    assert isinstance(tutorial_system, Tutorial)
    assert len(tutorial_system.steps) == 4
    
    # Check initial state
    assert tutorial_system.get_current_step().id == "step1"
    
    try:
        # Mutate global state
        tutorial_system.mark_completed("step1")
        assert tutorial_system.get_current_step().id == "step2"
    finally:
        # Always reset global state to avoid polluting other tests
        tutorial_system.reset()
        assert tutorial_system.get_current_step().id == "step1"

def test_tutorial_step_pydantic_validation():
    """Verify that TutorialStep validation catches missing fields and invalid types."""
    from pydantic import ValidationError
    
    # Missing required field (e.g. id)
    with pytest.raises(ValidationError):
        TutorialStep(
            title="Test",
            description="Test",
            action="click",
            target=".btn",
            tooltip="Tooltip"
        )
        
    # Invalid data type for id (e.g. dict instead of str)
    with pytest.raises(ValidationError):
        TutorialStep(
            id={"invalid": "type"},
            title="Test",
            description="Test",
            action="click",
            target=".btn",
            tooltip="Tooltip"
        )

def test_tutorial_step_serialization():
    """Verify serialization and deserialization of TutorialStep."""
    step = TutorialStep(
        id="step1",
        title="プリセット選択",
        description="カラープリセットを選びましょう",
        action="select",
        target="button",
        tooltip="Cinematic",
        completed=True
    )
    
    # Pydantic v1 / v2 compatibility for dictionary export
    if hasattr(step, "model_dump"):
        data = step.model_dump()
    else:
        data = step.dict()
        
    assert data["id"] == "step1"
    assert data["completed"] is True
    
    # Deserialize
    restored = TutorialStep(**data)
    assert restored.id == "step1"
    assert restored.completed is True
    assert restored.title == "プリセット選択"

def test_tutorial_calculate_percentage():
    """Verify the private helper _calculate_progress_percentage works correctly."""
    t = Tutorial()
    # Test valid calculations
    assert t._calculate_progress_percentage(1, 4) == 25
    assert t._calculate_progress_percentage(3, 4) == 75
    # Edge cases
    assert t._calculate_progress_percentage(0, 4) == 0
    assert t._calculate_progress_percentage(1, 0) == 0
    assert t._calculate_progress_percentage(0, 0) == 0
