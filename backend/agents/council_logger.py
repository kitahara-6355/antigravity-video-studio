import os
import json
import time
from datetime import datetime

class CouncilSessionLogger:
    """
    Handles the "Lossless Logging" of Council Debates.
    Saves synthesis and stance data for specific sessions.
    """
    def __init__(self, archive_dir="archives/council_logs"):
        if not archive_dir or not isinstance(archive_dir, str) or not archive_dir.strip():
            raise ValueError("archive_dir must be a non-empty string.")
        self.archive_dir = archive_dir
        if not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)
            
    def _get_safe_session_id(self, session_id) -> str:
        """
        Returns a string representation of the session ID suitable for filenames.
        """
        if not session_id:
            return "unknown"
        return str(session_id)

    def _build_log_entry(self, session_id, topic, debate_data: list, synthesis: dict) -> dict:
        """
        Constructs the structured dictionary for the council session log.
        """
        return {
            "session_id": session_id,
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat(),
            "topic": topic,
            "debate_flow": debate_data, # List of Agent Responses
            "synthesis": synthesis
        }

    def _write_log(self, filepath: str, log_entry: dict) -> None:
        """
        Writes the log entry to the specified file path.
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_entry, f, indent=2, ensure_ascii=False)

    def _integrate_with_wagamama(self, wagamama_id: str, topic: str, session_id, filepath: str, synthesis: dict) -> None:
        """
        Attempts to link the council session to the Wagamama Experience Story.
        Does not block core logging if it fails.
        """
        try:
            from backend.wagamama_manager import wagamama_manager
            if not wagamama_id:
                wagamama_id = wagamama_manager.find_matching_story(topic)
            
            if wagamama_id:
                wagamama_manager.link_council_session(wagamama_id, session_id, filepath, synthesis)
        except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
            # WagamamaManager not found, or any error during linkage should not block core logging.
            print(f"⚠️ WagamamaManager integration failed or skipped: {e}")

    def log_session(self, session_id, topic, debate_data: list, synthesis: dict, wagamama_id: str = None):
        """
        Logs a full council session to JSON.
        If wagamama_id is provided, automatically links this council session to the Experience Story.
        If wagamama_id is not provided, attempts to automatically detect a matching story based on the topic.
        """
        safe_session_id_str = self._get_safe_session_id(session_id)
        session_log_entry = self._build_log_entry(session_id, topic, debate_data, synthesis)
        
        log_filename = f"session_{int(time.time())}_{safe_session_id_str[:8]}.json"
        log_filepath = os.path.join(self.archive_dir, log_filename)
        
        try:
            self._write_log(log_filepath, session_log_entry)
            print(f"📄 Council Session Logged: {log_filepath}")
            
            self._integrate_with_wagamama(wagamama_id, topic, session_id, log_filepath, synthesis)
            return log_filepath
        except (OSError, TypeError, ValueError) as e:
            print(f"❌ Failed to log session (data serialisation or disk I/O error): {e}")
            return None

council_logger = CouncilSessionLogger()
