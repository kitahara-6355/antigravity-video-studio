import json
import os
import logging

logger = logging.getLogger(__name__)

class ContextResolver:
    """
    Subtitles and Video specifics resolver for AI context.
    Translates raw data into high-level strategic summaries.
    """
    
    @staticmethod
    def resolve_subtitles(file_path: str) -> str:
        """
        Reads subtitle JSON and returns a joined text string.
        """
        try:
            if not isinstance(file_path, (str, bytes, os.PathLike)):
                logger.warning(f"Subtitle file invalid path type: {type(file_path)}")
                return "No subtitle data available."
            if not os.path.exists(file_path):
                logger.warning(f"Subtitle file not found at {file_path}")
                return "No subtitle data available."
            
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                logger.error(f"Subtitle data is not a list: {type(data)}")
                return f"Error loading subtitles: Subtitle data is not a list: {type(data)}"
            
            # segments_a_plus_plus.json format: list of objects with "text"
            text_segments = []
            for seg in data:
                if isinstance(seg, dict):
                    val = seg.get('text')
                    if val is not None:
                        text_segments.append(str(val))
                    else:
                        text_segments.append("")
                else:
                    logger.warning(f"Skipping non-dict segment in subtitles: {seg}")
            
            full_text = " ".join(text_segments)
            return full_text
        except json.JSONDecodeError as e:
            logger.error(f"Subtitle JSON format invalid: {e}", exc_info=True)
            return f"Error loading subtitles: {e}"
        except UnicodeDecodeError as e:
            logger.error(f"Subtitle file encoding error: {e}", exc_info=True)
            return f"Error loading subtitles: {e}"
        except OSError as e:
            logger.error(f"Subtitle file access error: {e}", exc_info=True)
            return f"Error loading subtitles: {e}"
        except (TypeError, ValueError) as e:
            logger.error(f"Subtitle structure conversion error: {e}", exc_info=True)
            return f"Error loading subtitles: {e}"
        except (RuntimeError, AttributeError) as e:
            logger.error(f"Subtitle processing runtime error: {e}", exc_info=True)
            return f"Error loading subtitles: {e}"

    @staticmethod
    def get_deep_context_block(subtitles_path: str, vision: str = "", max_length: int = 10000) -> str:
        """
        Constructs the DEEP CONTEXT block for AI prompts.
        """
        subtitles = ContextResolver.resolve_subtitles(subtitles_path)
        
        # Truncate if too long
        if len(subtitles) > max_length:
            subtitles = subtitles[:max_length] + "... (truncated)"
            
        context = f"""
## 🕯️ DEEP CONTEXT: CURRENT VIDEO SOUL
- **Vision/Commitment**: "{vision if vision else 'No specific vision provided for this session.'}"
- **Full Transcribed Content**:
---
{subtitles}
---
"""
        return context
