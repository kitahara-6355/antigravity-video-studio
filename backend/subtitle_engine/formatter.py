"""
Subtitle Formatter
字幕ファイル形式の変換（VTT, SRT）
"""

from typing import List, Dict
from datetime import timedelta


class SubtitleFormatter:
    """字幕フォーマット変換クラス"""
    @staticmethod
    def _validate_subtitles(subtitles: list) -> None:
        if subtitles is None:
            raise TypeError("subtitles list cannot be None")
        if not isinstance(subtitles, list):
            raise TypeError(f"subtitles must be a list, got {type(subtitles).__name__}")
        for i, sub in enumerate(subtitles, 1):
            if not isinstance(sub, dict):
                raise TypeError(f"Subtitle segment must be a dict, got {type(sub).__name__} in segment {i}")
            for key in ("start", "end", "text"):
                if key not in sub:
                    raise KeyError(key)
            start, end, text = sub["start"], sub["end"], sub["text"]
            if start is None or end is None:
                raise TypeError(f"Subtitle timing cannot be None in segment {i}")
            if not isinstance(start, (int, float)) or isinstance(start, bool):
                raise TypeError(f"Subtitle start time must be a number, got {type(start).__name__} in segment {i}")
            if not isinstance(end, (int, float)) or isinstance(end, bool):
                raise TypeError(f"Subtitle end time must be a number, got {type(end).__name__} in segment {i}")
            if start < 0 or end < 0:
                raise ValueError(f"Subtitle timing must be non-negative in segment {i}")
            if start > end:
                raise ValueError(f"Subtitle start time ({start}) cannot be greater than end time ({end}) in segment {i}")
            if text is None:
                raise TypeError(f"Subtitle text cannot be None in segment {i}")
            if not isinstance(text, str):
                raise TypeError(f"Subtitle text must be a string, got {type(text).__name__} in segment {i}")

    
    @staticmethod
    def to_vtt(subtitles: List[Dict]) -> str:
        """
        WebVTT形式に変換
        
        Args:
            subtitles: 字幕セグメントのリスト
        
        Returns:
            WebVTT形式の文字列
        """
        SubtitleFormatter._validate_subtitles(subtitles)
        vtt = "WEBVTT\n\n"
        
        for i, sub in enumerate(subtitles, 1):
            start = SubtitleFormatter._format_time_vtt(sub["start"])
            end = SubtitleFormatter._format_time_vtt(sub["end"])
            text = sub["text"]
            
            vtt += f"{i}\n"
            vtt += f"{start} --> {end}\n"
            vtt += f"{text}\n\n"
        
        return vtt
    
    @staticmethod
    def to_srt(subtitles: List[Dict]) -> str:
        """
        SRT形式に変換
        
        Args:
            subtitles: 字幕セグメントのリスト
        
        Returns:
            SRT形式の文字列
        """
        SubtitleFormatter._validate_subtitles(subtitles)
        srt = ""
        
        for i, sub in enumerate(subtitles, 1):
            start = SubtitleFormatter._format_time_srt(sub["start"])
            end = SubtitleFormatter._format_time_srt(sub["end"])
            text = sub["text"]
            
            srt += f"{i}\n"
            srt += f"{start} --> {end}\n"
            srt += f"{text}\n\n"
        
        return srt
    
    @staticmethod
    def _format_time_vtt(seconds: float) -> str:
        """VTT形式の時間フォーマット (HH:MM:SS.mmm)"""
        td = timedelta(seconds=seconds)
        hours = int(td.total_seconds()) // 3600
        minutes = (int(td.total_seconds()) % 3600) // 60
        secs = td.total_seconds() % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    
    @staticmethod
    def _format_time_srt(seconds: float) -> str:
        """SRT形式の時間フォーマット (HH:MM:SS,mmm)"""
        vtt_time = SubtitleFormatter._format_time_vtt(seconds)
        return vtt_time.replace('.', ',')
