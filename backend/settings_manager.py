import os
import json
import shutil
import time
import logging

logger = logging.getLogger(__name__)

# Fix import path: branding_manager is in the same directory
try:
    from branding_manager import branding_manager, CONSTITUTION_PATH
except ImportError:
    # Fallback if running from a different context
    from branding.branding_manager import branding_manager, CONSTITUTION_PATH

# Fix VIDEO_SRC_PATH to match main.py (Root SRC, not backend/src)
# backend/settings_manager.py -> backend -> video-automation -> src
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # video-automation root
VIDEO_SRC_PATH = os.path.join(BASE_DIR, "src", "sample_raw.mp4")

class SettingsManager:
    """Manages system settings, video source updates, and workspace reset operations."""

    def _ensure_constitution(self) -> dict:
        """Ensures that the constitution is initialized as a dictionary and returns it."""
        if branding_manager.constitution is None or not isinstance(branding_manager.constitution, dict):
            branding_manager.constitution = {}
        return branding_manager.constitution

    def _safe_delete_file(self, file_path: str) -> None:
        """Deletes a file, or attempts to rename it to a trash path if locked."""
        if not os.path.exists(file_path):
            return
        try:
            os.remove(file_path)
        except PermissionError as e:
            logger.warning(f"File locked, attempting rename to trash: {file_path}. Error: {e}")
            try:
                trash_path = f"{file_path}.trash_{int(time.time())}"
                os.rename(file_path, trash_path)
                logger.info(f"Successfully renamed locked file to trash: {trash_path}")
            except (OSError, RuntimeError) as re:
                logger.error(f"Failed to rename locked file: {file_path}. Error: {re}")
                raise
        except OSError as e:
            logger.error(f"Failed to remove file: {file_path}. Error: {e}")
            raise

    def _handle_error(self, error: Exception) -> dict:
        """Creates a standardized error response dictionary."""
        return {"status": "error", "message": str(error)}

    def get_all_settings(self) -> dict:
        """Returns consolidated settings for the frontend.

        **`user_model` の `external_status` は作り物**（R1.5-C4・10周目 N-1）。
        `GET /api/status` と**同じ台帳を同じ素のまま返していた**ので、
        こちらも `get_user_model_for_display()`（印の集約点）を通す。
        """
        constitution = self._ensure_constitution()
        user_model = branding_manager.get_user_model_for_display()
        if not isinstance(user_model, dict):
            user_model = {}
        return {
            "constitution": constitution,
            "user_model": user_model,
            "video_exists": os.path.exists(VIDEO_SRC_PATH)
        }

    def get_video_source(self) -> str:
        """Returns the absolute path to the current source video."""
        return VIDEO_SRC_PATH

    def update_video_source(self, temp_file_path: str, original_filename: str = None) -> dict:
        """Replaces the source video with a new one."""
        try:
            os.makedirs(os.path.dirname(VIDEO_SRC_PATH), exist_ok=True)
            self._safe_delete_file(VIDEO_SRC_PATH)
            shutil.move(temp_file_path, VIDEO_SRC_PATH)
            
            if original_filename:
                constitution = self._ensure_constitution()
                constitution['video_source_name'] = original_filename
                branding_manager._save_json(CONSTITUTION_PATH, constitution)

            return {
                "status": "success",
                "message": "Video source updated successfully.",
                "filename": original_filename
            }
        except Exception as e:
            logger.error(f"Error updating video source: {e}", exc_info=True)
            return self._handle_error(e)

    def update_identity(self, channel_name: str, target_audience: str) -> dict:
        """Updates the Constitution (Identity)."""
        try:
            constitution = self._ensure_constitution()
            constitution['channel_name'] = channel_name
            constitution['target_audience'] = target_audience
            
            branding_manager._save_json(CONSTITUTION_PATH, constitution)
            return {"status": "success", "message": "Identity updated."}
        except Exception as e:
            logger.error(f"Error updating identity: {e}", exc_info=True)
            return self._handle_error(e)

    def export_soul_passport(self) -> dict:
        """Exports the User Model as a downloadable JSON (Passport).

        **いまは呼び出し元が無い**（本番から到達しない）。それでも印の集約点を
        通すのは、繋いだ瞬間に無印の `external_status` が外へ出るのを防ぐため。
        """
        model = branding_manager.get_user_model_for_display()
        return model if isinstance(model, dict) else {}

    def reset_workspace(self) -> dict:
        """Resets the workspace by clearing video and segments data."""
        try:
            segments_path = os.path.join(BASE_DIR, "src", "segments_a_plus_plus.json")
            
            self._safe_delete_file(VIDEO_SRC_PATH)
            self._safe_delete_file(segments_path)

            constitution = self._ensure_constitution()
            constitution['video_source_name'] = ""
            branding_manager._save_json(CONSTITUTION_PATH, constitution)
            
            status_file_path = os.path.join(BASE_DIR, "src", "transcription_status.json")
            try:
                with open(status_file_path, "w", encoding="utf-8") as f:
                    json.dump({"status": "idle", "message": "Workspace reset"}, f)
            except (OSError, TypeError) as e:
                logger.warning(f"Failed to write workspace reset status: {e}")
            
            return {"status": "success", "message": "Workspace reset complete."}
        except Exception as e:
            logger.error(f"Error resetting workspace: {e}", exc_info=True)
            return self._handle_error(e)

settings_manager = SettingsManager()
