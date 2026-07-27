# satisfies: REQ-DAG-02
import os
import ast
from pathlib import Path
from typing import List, Dict, Any
from .task_dag import TaskDAG
from .ds_task_decomposer import decompose_by_dependency, decompose_large_change_task

class DynamicDecomposer:
    """Dynamic Task Decomposer.
    
    Analyzes task characteristics (such as module dependency depth and expected changes)
    and breaks down single heavy tasks into a TaskDAG structure of micro-tasks.
    """
    def __init__(self, workspace_path: str = None):
        self.workspace_path = workspace_path or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def analyze_dependency(self, target_module: str) -> List[str]:
        """Performs AST analysis on target module to extract import dependency names."""
        if not target_module:
            return []
            
        p = Path(self.workspace_path)
        # Try direct path first, then fallback to backend/ prefix
        target_path = p / target_module
        if not target_path.exists() and not str(target_module).startswith("backend/"):
            target_path = p / "backend" / target_module
            
        if not target_path.exists():
            return []
            
        dependencies = []
        try:
            content = target_path.read_text(encoding="utf-8")
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        dependencies.append(name.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        dependencies.append(node.module)
        except (SyntaxError, OSError, ValueError):
            pass
        return dependencies

    def decompose_task(self, task: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Decomposes a single task if it exceeds complexity thresholds.
        
        Complexity is determined by:
        1. High import dependency (>= 5 dependencies).
        2. Specifically tagged large change task.
        """
        target = task.get("target_module")
        if not target:
            return [task]
            
        deps = self.analyze_dependency(target)
        
        # Check complexity
        is_high_dependency = len(deps) >= 5
        is_large_change = task.get("is_large_change", False) or "large_change" in task.get("group", "")
        
        if is_high_dependency:
            # Use dependency-based decomposition
            return decompose_by_dependency(task, self.workspace_path)
        elif is_large_change:
            # Use large change decomposition
            return decompose_large_change_task(task)
            
        return [task]

    def build_dag_from_tasks(self, tasks: List[Dict[str, Any]]) -> TaskDAG:
        """Decomposes given tasks and structures them into a TaskDAG with sequential dependencies."""
        dag = TaskDAG()
        
        for task in tasks:
            sub_tasks = self.decompose_task(task)
            
            if len(sub_tasks) == 1:
                # Single task, add as is
                dag.add_task(task["id"], task)
            else:
                # Chain dependencies sequentially for the split tasks
                prev_id = None
                for idx, sub_task in enumerate(sub_tasks):
                    sub_id = sub_task["id"]
                    deps = []
                    if prev_id:
                        deps.append(prev_id)
                        
                    # Add original task dependencies if it is the first split task
                    if idx == 0:
                        deps.extend(task.get("dependencies", []))
                        
                    dag.add_task(sub_id, sub_task, dependencies=deps)
                    prev_id = sub_id
                    
        return dag
