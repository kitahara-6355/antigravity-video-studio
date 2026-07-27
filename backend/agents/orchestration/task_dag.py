# satisfies: REQ-DAG-01
import collections
from typing import Dict, List, Set, Any, Optional

class TaskDAG:
    """Task DAG (Directed Acyclic Graph) for orchestrating dependent tasks.
    
    Provides dependency tracking, topological sorting, cycle detection,
    and dynamic query of ready-to-run tasks.
    """
    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}  # task_id -> task_data
        self.dependencies: Dict[str, Set[str]] = collections.defaultdict(set)  # task_id -> Set of dependency task_ids
        self.dependents: Dict[str, Set[str]] = collections.defaultdict(set)   # dependency_id -> Set of dependent task_ids

    def add_task(self, task_id: str, task_data: Dict[str, Any], dependencies: List[str] = None) -> None:
        """Adds a task to the DAG with optional dependencies.
        
        Args:
            task_id: Unique identifier for the task.
            task_data: Meta information and instructions.
            dependencies: List of task IDs this task depends on.
        """
        self.tasks[task_id] = task_data
        if "status" not in self.tasks[task_id]:
            self.tasks[task_id]["status"] = "pending"
            
        deps = dependencies or task_data.get("dependencies", [])
        for dep in deps:
            self.dependencies[task_id].add(dep)
            self.dependents[dep].add(task_id)
            
        # Check for cycles immediately
        if self.has_cycle():
            # Rollback change
            for dep in deps:
                self.dependencies[task_id].remove(dep)
                self.dependents[dep].remove(task_id)
            raise ValueError(f"Adding task '{task_id}' introduces a cyclic dependency.")

    def has_cycle(self) -> bool:
        """Detects if there is any cycle in the dependency graph."""
        visited = {}  # 0 = unvisited, 1 = visiting, 2 = visited
        
        def dfs(node: str) -> bool:
            visited[node] = 1
            for dep in self.dependencies.get(node, set()):
                if dep not in self.tasks:
                    continue  # dependency is not a registered task, ignore or treat as resolved
                if visited.get(dep, 0) == 1:
                    return True
                if visited.get(dep, 0) == 0:
                    if dfs(dep):
                        return True
            visited[node] = 2
            return False

        for task_id in self.tasks:
            if visited.get(task_id, 0) == 0:
                if dfs(task_id):
                    return True
        return False

    def mark_task_status(self, task_id: str, status: str) -> None:
        """Updates the status of a task and handles downstream cascading if failed."""
        if task_id not in self.tasks:
            return
        
        self.tasks[task_id]["status"] = status
        
        if status in ("fail", "failed"):
            # Cascade: all downstream dependent tasks are marked as skipped or failed due to dependency failure
            self._cascade_failure(task_id)

    def _cascade_failure(self, task_id: str) -> None:
        queue = list(self.dependents.get(task_id, set()))
        visited = set()
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            if node in self.tasks:
                self.tasks[node]["status"] = "skipped"
                self.tasks[node]["result"] = "skipped_dependency_failed"
                queue.extend(self.dependents.get(node, set()))

    def get_executable_tasks(self) -> List[Dict[str, Any]]:
        """Returns tasks that are ready to run (all dependencies completed successfully)."""
        executable = []
        for task_id, data in self.tasks.items():
            if data.get("status") != "pending":
                continue
            
            # Check dependencies
            deps = self.dependencies.get(task_id, set())
            deps_met = True
            for dep in deps:
                if dep not in self.tasks:
                    # External or missing dependency, assume resolved or ignore
                    continue
                dep_status = self.tasks[dep].get("status")
                if dep_status != "pass" and dep_status != "completed":
                    deps_met = False
                    break
            
            if deps_met:
                executable.append(data)
                
        return executable

    def is_complete(self) -> bool:
        """Returns True if all tasks in the DAG are finished (pass, fail, skipped, etc.)."""
        for data in self.tasks.values():
            status = data.get("status")
            if status in ("pending", "running"):
                return False
        return True

    def topological_sort(self) -> List[str]:
        """Returns task IDs in topologically sorted order."""
        result = []
        visited = set()
        temp_visited = set()

        def visit(node: str):
            if node in visited:
                return
            if node in temp_visited:
                raise ValueError("Cycle detected during sorting.")
            
            temp_visited.add(node)
            for dep in self.dependencies.get(node, set()):
                if dep in self.tasks:
                    visit(dep)
            temp_visited.remove(node)
            visited.add(node)
            result.append(node)

        for task_id in self.tasks:
            visit(task_id)
            
        return result
