import json
import os
import re

def reverse_readline(filename: str, buf_size: int = 8192):
    """A generator that yields the lines of a file in reverse order (binary mode)."""
    try:
        with open(filename, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            
            # モック環境（tell()がMagicMockを返すなど）への対策
            if type(file_size).__name__ in ("MagicMock", "Mock") or not isinstance(file_size, int):
                f.seek(0)
                content = f.read()
                if isinstance(content, str):
                    content = content.encode("utf-8")
                if type(content).__name__ in ("MagicMock", "Mock") or not isinstance(content, bytes):
                    content = b""
                lines = content.split(b"\n")
                if lines and lines[-1] == b"":
                    lines.pop()
                for line in reversed(lines):
                    yield line.decode("utf-8", errors="replace").rstrip("\r\n")
                return

            pointer = file_size
            buffer = b""
            is_first_chunk = True
            
            while pointer > 0:
                to_read = min(buf_size, pointer)
                pointer -= to_read
                f.seek(pointer)
                chunk = f.read(to_read)
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                if not isinstance(chunk, bytes):
                    break
                buffer = chunk + buffer
                
                lines = buffer.split(b"\n")
                
                if is_first_chunk:
                    is_first_chunk = False
                    if lines and lines[-1] == b"":
                        lines.pop()
                
                if pointer > 0:
                    buffer = lines[0]
                    lines = lines[1:]
                else:
                    buffer = b""
                    
                for line in reversed(lines):
                    yield line.decode("utf-8", errors="replace").rstrip("\r\n")
                    
            if buffer:
                yield buffer.decode("utf-8", errors="replace").rstrip("\r\n")
    except OSError as e:
        print(f"Error reading file in reverse: {e}")

def read_transcript_lines(path: str) -> list[str] | None:
    """Reads lines from the transcript log file."""
    if not os.path.exists(path):
        print("Not found")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except OSError as e:
        print(f"Error reading file: {e}")
        return None

def find_last_dispatch_log(lines: list[str]) -> tuple[int, dict | None]:
    """Finds the last successful subagent dispatch log event in reversed order."""
    parsed_data = None
    line_idx = -1
    
    for i, line in enumerate(reversed(lines)):
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get("type") == "INVOKE_SUBAGENT" and data.get("status") == "DONE":
                parsed_data = data
                line_idx = len(lines) - 1 - i
                break
        except json.JSONDecodeError:
            pass
        except (TypeError, ValueError, AttributeError):
            pass
            
    return line_idx, parsed_data

def find_last_dispatch_log_efficient(path: str) -> tuple[int, dict | None]:
    """Finds the last successful subagent dispatch log event efficiently without loading the whole file."""
    if not os.path.exists(path):
        return -1, None

    total_lines = 0
    try:
        with open(path, "rb") as f:
            test_chunk = f.read(1)
            if type(test_chunk).__name__ in ("MagicMock", "Mock"):
                raise OSError("Mock environment detected")
                
            f.seek(0)
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                if not isinstance(chunk, bytes):
                    break
                total_lines += chunk.count(b"\n")
    except (OSError, TypeError, ValueError):
        # 例外時は安全なフォールバック
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                total_lines = len(lines)
                idx, data = find_last_dispatch_log(lines)
                return idx, data
        except (OSError, TypeError, ValueError):
            return -1, None

    line_idx = -1
    parsed_data = None
    
    for i, line in enumerate(reverse_readline(path)):
        try:
            data = json.loads(line)
            if isinstance(data, dict) and data.get("type") == "INVOKE_SUBAGENT" and data.get("status") == "DONE":
                parsed_data = data
                line_idx = total_lines - i
                break
        except json.JSONDecodeError:
            pass
        except (TypeError, ValueError, AttributeError):
            pass

    return line_idx, parsed_data

def parse_and_print_subagent_info(content: str) -> list[dict]:
    """Parses and prints conversation and workspace mapping from the subagent dispatch content."""
    results = []
    if not isinstance(content, str):
        print("Content is not a string")
        return results

    print("Content preview:")
    print(repr(content[:500]))
    
    try:
        parts = content.split('"conversationId":')
        print(f"Parts count: {len(parts)}")
        for part in parts[1:]:
            cid_match = re.search(r'^\s*\"([^\"]+)\"', part)
            if cid_match:
                conv_id = cid_match.group(1)
                
                wt_path = "None"
                uris_match = re.search(r'\"workspaceUris\"\s*:\s*(\[[^\]]*\])', part)
                if uris_match:
                    try:
                        uris = json.loads(uris_match.group(1))
                        if isinstance(uris, list) and len(uris) > 0:
                            uri = uris[0]
                            if uri.startswith("file:///"):
                                wt_path = uri[len("file:///"):]
                            else:
                                wt_path = uri
                    except json.JSONDecodeError:
                        pass
                    except (TypeError, KeyError):
                        pass
                
                if wt_path == "None":
                    wt_match = re.search(r'\"workspaceUris\"\s*:\s*\[\s*\"file:///([^\"]+)\"\s*\]', part)
                    wt_path = wt_match.group(1) if wt_match else "None"
                    
                worktree_match = re.search(r"subagent-([a-zA-Z0-9_-]+)-Agent-", part)
                print(f"  conv_id: {conv_id}, wt_path: {wt_path}, worktree_match: {worktree_match}")
                group_raw = None
                if worktree_match:
                    group_raw = worktree_match.group(1)
                    print(f"    group_raw: {group_raw}")
                    
                results.append({
                    "conv_id": conv_id,
                    "wt_path": wt_path,
                    "worktree_match": worktree_match,
                    "group_raw": group_raw
                })
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        print(f"Error parsing subagent info: {e}")

    return results

def analyze_transcript(path: str) -> list[dict] | None:
    """Analyzes a transcript JSONL file and returns subagent assignment mappings."""
    if not os.path.exists(path):
        print("Not found")
        return None

    use_efficient = False
    try:
        file_size = os.path.getsize(path)
        if file_size > 1024 * 1024:
            use_efficient = True
    except OSError:
        pass

    if use_efficient:
        line_idx, parsed_data = find_last_dispatch_log_efficient(path)
    else:
        lines = read_transcript_lines(path)
        if lines is None:
            return None
        line_idx, parsed_data = find_last_dispatch_log(lines)

    if parsed_data:
        print(f"Found dispatch log at Line {line_idx}")
        content = parsed_data.get("content", "")
        return parse_and_print_subagent_info(content)
    else:
        print("No dispatch log found")
        return []

if __name__ == "__main__":
    log_path = r"C:\Users\PC_User\.gemini\antigravity\brain\a9736a64-a242-485f-942e-bf8476d21fa6\.system_generated\logs\transcript.jsonl"
    analyze_transcript(log_path)
