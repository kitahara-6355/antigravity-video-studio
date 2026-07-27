"""Branch complexity measurement per Worker."""
import ast
import os
import logging

# Configure logger
logger = logging.getLogger("measure_branches")

def _is_branch_node(node):
    """Check if the AST node represents a branch."""
    return isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.Assert))

def _is_method_node(node):
    """Check if the AST node represents a method or function definition."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))

def count_branches(path):
    """Count branch complexity and method count for a given file path."""
    if not os.path.exists(path):
        logger.warning("File does not exist: %s", path)
        return 0, 0
    if os.path.isdir(path):
        logger.warning("Path is a directory: %s", path)
        return 0, 0
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content)
        branch_count = 0
        method_count = 0
        for node in ast.walk(tree):
            if _is_branch_node(node):
                branch_count += 1
            elif _is_method_node(node):
                method_count += 1
        return branch_count, method_count
    except (OSError, SyntaxError, ValueError) as e:
        logger.error("Failed to parse branches for %s: %s", path, e)
        return 0, 0

worker_engines = {
    'TranscribeWorker': {
        'worker_branches': 19,
        'engines': [
            ('whisper_subprocess.py', 'backend/subtitle_engine/whisper_subprocess.py'),
            ('whisper_transcriber.py', 'backend/subtitle_engine/whisper_transcriber.py'),
        ]
    },
    'ProofreadWorker': {
        'worker_branches': 10,
        'engines': [
            ('ai_proofreader.py', 'backend/subtitle_engine/ai_proofreader.py'),
            ('text_formatter.py', 'backend/subtitle_engine/text_formatter.py'),
        ]
    },
    'SmartCutWorker': {
        'worker_branches': 8,
        'engines': [
            ('smart_cut_engine.py', 'backend/smart_cut_engine.py'),
        ]
    },
    'PreviewWorker': {
        'worker_branches': 2,
        'engines': [
            ('preview_engine.py', 'backend/preview_engine.py'),
        ]
    },
    'QualityGateWorker': {
        'worker_branches': 4,
        'engines': [
            ('quality_gate_plugins.py', 'backend/quality_gate_plugins.py'),
            ('quality_gate_ai.py', 'backend/quality_gate_ai.py'),
            ('evaluator_optimizer.py', 'backend/harness/evaluator_optimizer.py'),
        ]
    },
    'RenderWorker': {
        'worker_branches': 28,
        'engines': [
            ('video_editor_engine.py', 'backend/video_editor_engine.py'),
            ('audio_master.py', 'backend/audio_master.py'),
        ]
    },
    'YouTubeOptWorker': {
        'worker_branches': 5,
        'engines': []
    },
}

shared_infra = [
    ('PipelineCoordinator(本体)', None, 63),
    ('model_governance.py', 'backend/model_governance.py', None),
    ('hooks.py', 'backend/harness/hooks.py', None),
    ('governance.py', 'backend/harness/governance.py', None),
    ('session_manager.py', 'backend/harness/session_manager.py', None),
    ('progressive_preview.py', 'backend/progressive_preview.py', None),
]

def _process_single_engine(project_root, engine_name, engine_path, seen):
    """Process a single engine and return its branch count, details, and whether it was counted."""
    if not engine_path:
        logger.warning("Engine path is empty for engine: %s", engine_name)
        return 0, f"  {engine_name}: (empty path)"
    full_path = os.path.abspath(os.path.normpath(os.path.join(project_root, engine_path)))
    norm_path = os.path.normcase(full_path)
    if norm_path not in seen:
        seen.add(norm_path)
        branch_count, method_count = count_branches(full_path)
        detail = f"  {engine_name}: {branch_count} branches, {method_count} methods"
        return branch_count, detail
    else:
        detail = f"  {engine_name}: (counted elsewhere)"
        return 0, detail

def measure_worker_branches(project_root, seen):
    """Measure branches for all workers and their engines."""
    worker_total = 0
    details_output = []
    
    for worker_name, worker_data in worker_engines.items():
        worker_branches = worker_data['worker_branches']
        engine_branch_count = 0
        details = []
        for engine_name, engine_path in worker_data['engines']:
            branch_count, detail = _process_single_engine(project_root, engine_name, engine_path, seen)
            engine_branch_count += branch_count
            details.append(detail)
        
        total = worker_branches + engine_branch_count
        worker_total += total
        worker_details = [f"{worker_name}: Worker={worker_branches} + Engines={engine_branch_count} = **{total}**"]
        worker_details.extend(details)
        details_output.append(worker_details)
        
    return worker_total, details_output

def _process_single_shared_infra(project_root, name, path, preset, seen):
    """Process a single shared infrastructure item and return its branch count and detail message."""
    if preset is not None:
        return preset, f"{name}: {preset} branches (pre-counted)"
    
    if not path:
        logger.warning("Shared infra path is empty for: %s", name)
        return 0, f"{name}: (empty path)"
        
    full_path = os.path.abspath(os.path.normpath(os.path.join(project_root, path)))
    norm_path = os.path.normcase(full_path)
    if norm_path not in seen:
        seen.add(norm_path)
        branch_count, method_count = count_branches(full_path)
        detail = f"{name}: {branch_count} branches, {method_count} methods"
        return branch_count, detail
    else:
        detail = f"{name}: (counted elsewhere)"
        return 0, detail

def measure_shared_infra_branches(project_root, seen):
    """Measure branches for shared infrastructure."""
    shared_branch_total = 0
    details_output = []
    for name, path, preset in shared_infra:
        branch_count, detail = _process_single_shared_infra(project_root, name, path, preset, seen)
        shared_branch_total += branch_count
        details_output.append(detail)
        
    return shared_branch_total, details_output

def print_results(worker_total, worker_details, shared_branch_total, shared_details):
    """Print the measured results."""
    print("=== Worker別分岐数（実測） ===\n")
    for details in worker_details:
        for line in details:
            print(line)
        print()
        
    print("=== 共有基盤 ===\n")
    for line in shared_details:
        print(line)
        
    print(f"\n=== 集計 ===")
    print(f"Worker系合計: {worker_total}")
    print(f"共有基盤合計: {shared_branch_total}")
    print(f"総計: {worker_total + shared_branch_total}")

def main():
    """Main execution function."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    seen = set()
    
    worker_total, worker_details = measure_worker_branches(project_root, seen)
    shared_branch_total, shared_details = measure_shared_infra_branches(project_root, seen)
    print_results(worker_total, worker_details, shared_branch_total, shared_details)

if __name__ == '__main__':
    main()
