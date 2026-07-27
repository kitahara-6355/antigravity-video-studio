import re
import logging
import math

logger = logging.getLogger(__name__)

def _resolve_target_chars(target_chars):
    """
    Validate and normalize target_chars.
    If target_chars is invalid (not int/float, nan, inf, bool), returns default 13.
    """
    if (not isinstance(target_chars, (int, float)) or 
            isinstance(target_chars, bool) or 
            math.isnan(target_chars) or 
            math.isinf(target_chars)):
        logger.warning(f"Invalid target_chars type or value: {target_chars}. Resetting to default 13.")
        return 13
    return target_chars

def _extract_segment_text(segment):
    """
    Extract and stringify text from segment, returning its length.
    """
    text = segment.get('text', '')
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return len(text)

def _determine_rhythm_status_and_suggestion(text_length, target_chars):
    """
    Determine rhythm status and suggestion based on text length and target_chars.
    """
    status = 'ok'
    if text_length > target_chars + 5: # Tolerance
        status = 'too_long'
    elif text_length < 3 and text_length > 0:
        status = 'too_short'
        
    suggestion = 'split' if status == 'too_long' else 'merge' if status == 'too_short' else None
    return status, suggestion

def _analyze_single_segment(segment, default_index, target_chars):
    """
    Analyze a single segment for rhythm anomalies, with safety wrappers.
    """
    try:
        text_length = _extract_segment_text(segment)
        status, suggestion = _determine_rhythm_status_and_suggestion(text_length, target_chars)
        
        return {
            'index': segment.get('id', default_index),
            'status': status,
            'length': text_length,
            'suggestion': suggestion
        }
    except (TypeError, ValueError, AttributeError, RuntimeError) as e:
        logger.error(f"Error processing segment at index {default_index}: {e}", exc_info=True)
        return {
            'index': segment.get('id', default_index),
            'status': 'error',
            'length': 0,
            'suggestion': None
        }

def analyze_rhythm(segments, target_chars=13):
    """
    Analyze segments for rhythm anomalies.
    Returns a list of anomaly flags corresponding to segments.
    """
    if not isinstance(segments, list):
        logger.warning("Invalid input for analyze_rhythm: segments must be a list")
        return []

    resolved_target_chars = _resolve_target_chars(target_chars)
        
    anomalies = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            logger.warning(f"Segment at index {index} is not a dict: {type(segment)}")
            continue
        anomalies.append(_analyze_single_segment(segment, index, resolved_target_chars))
    return anomalies

def _split_by_japanese_punctuations(text, punctuations):
    """
    Split text by specified punctuation marks.
    """
    if not isinstance(punctuations, str) or not punctuations:
        return [text]
    try:
        return re.split(f"([{punctuations}])", text)
    except re.error as re_err:
        logger.error(f"Regex split failed in semantic_split: {re_err}. Falling back to character list.")
        return [text]

def _reattach_punctuations(parts, punctuations):
    """
    Re-attach punctuation marks to their preceding text chunks.
    """
    chunks = []
    current_chunk = ""
    for part in parts:
        if not part:
            continue
        if part in punctuations:
            current_chunk += part
            chunks.append(current_chunk)
            current_chunk = ""
        else:
            current_chunk = part
    if current_chunk:
        chunks.append(current_chunk)
    return chunks

def _force_split_long_chunks(chunks, target_chars):
    """
    Force split chunks if they are still longer than the target_chars + tolerance.
    """
    final_chunks = []
    for chunk in chunks:
        sub_chunks = [chunk]
        chunk_index = 0
        while chunk_index < len(sub_chunks):
            current_chunk = sub_chunks[chunk_index]
            if len(current_chunk) > target_chars + 5:
                split_index = len(current_chunk) // 2
                if split_index == 0:
                    chunk_index += 1
                    continue
                sub_chunks[chunk_index:chunk_index+1] = [current_chunk[:split_index], current_chunk[split_index:]]
            else:
                chunk_index += 1
        final_chunks.extend(sub_chunks)
    return final_chunks

def semantic_split(text, target_chars=13):
    """
    Split text semantically using simple heuristics (for now).
    Prioritizes punctuation -> particles -> length.
    """
    try:
        if not isinstance(text, str):
            text = str(text) if text is not None else ""

        resolved_target_chars = _resolve_target_chars(target_chars)
        int_target_chars = int(resolved_target_chars)

        if len(text) <= int_target_chars:
            return [text]

        # Create punctuation characters safely without escape issues
        # 、(0x3001), 。(0x3002), ！(0xff01), ？(0xff1f)
        japanese_punctuations = "".join(chr(c) for c in (0x3001, 0x3002, 0xff01, 0xff1f))

        # 1. Split by punctuation
        parts = _split_by_japanese_punctuations(text, japanese_punctuations)

        # Re-attach punctuation
        chunks = _reattach_punctuations(parts, japanese_punctuations)
        
        # 2. Force split if chunks are still too long (Simple fallback)
        return _force_split_long_chunks(chunks, int_target_chars)

    except (TypeError, ValueError, OverflowError, AttributeError, RuntimeError) as e:
        logger.error(f"Unexpected error in semantic_split: {e}", exc_info=True)
        return [text] if text else [""]
