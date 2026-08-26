"""
Segments Router - 字幕・セグメント編集関連エンドポイント
"""
from fastapi import APIRouter, Request, UploadFile, HTTPException, Body
import json
from pathlib import Path
import logging
from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["segments"])

# データパス
SEGMENTS_PATH = Path(__file__).parent.parent / "subtitle_result.json"


class SubtitleSegment(BaseModel):
    start: float = Field(..., ge=0, description="開始時間（秒）")
    end: float = Field(..., ge=0, description="終了時間（秒）")
    text: str = Field(..., description="字幕テキスト")

    @model_validator(mode="after")
    def validate_time_range(self) -> "SubtitleSegment":
        import math
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("start and end times must be finite numbers")
        if self.end < self.start:
            raise ValueError("end time must be greater than or equal to start time")
        return self


@router.get("/segments")
async def get_segments():
    """
    現在の字幕データを取得する。
    AIからの解説: これは編集画面の右側に表示される各行のデータ元です。
    """
    try:
        if SEGMENTS_PATH.is_dir():
            logger.warning(f"segments path is a directory: {SEGMENTS_PATH}")
            return []
        if not SEGMENTS_PATH.exists() or SEGMENTS_PATH.stat().st_size == 0:
            return []
        with open(SEGMENTS_PATH, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        
        if not isinstance(raw_data, list):
            logger.error(f"Invalid format in segments file: expected list, got {type(raw_data).__name__}")
            raise HTTPException(status_code=500, detail="Invalid data structure in subtitle_result.json")
            
        validated_data = []
        for item in raw_data:
            if isinstance(item, dict):
                try:
                    validated_data.append(SubtitleSegment(**item).model_dump())
                except ValidationError as ve:
                    logger.warning(f"Skipping invalid segment record in file: {ve}")
            else:
                logger.warning(f"Skipping non-dict segment record in file: {item}")
        return validated_data
    except UnicodeDecodeError as e:
        logger.error(f"Encoding or decode error in segments file: {e}")
        raise HTTPException(status_code=500, detail="Invalid JSON format or encoding error in subtitle_result.json")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in segments file: {e}")
        raise HTTPException(status_code=500, detail="Invalid JSON format in subtitle_result.json")
    except OSError as e:
        logger.error(f"Failed to read segments file: {e}")
        raise HTTPException(status_code=500, detail="Disk read error or permission denied")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_segments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected internal server error")


@router.post("/segments")
async def save_segments(request: Request):
    """
    編集された字幕データを保存する。
    AIからの解説: ユーザーがフォームで修正した内容を、マスターデータとしてJSONに反映します。
    """
    try:
        try:
            data = await request.json()
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON request for segments: {e}")
            raise HTTPException(status_code=400, detail="Malformed JSON payload")
        
        if not isinstance(data, list):
            logger.error(f"Segments data must be a list, received: {type(data).__name__}")
            raise HTTPException(status_code=400, detail="Segments data must be a JSON array")
        
        validated_data = []
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                logger.error(f"Segment item at index {i} is not a dictionary: {type(item).__name__}")
                raise HTTPException(status_code=400, detail=f"Invalid subtitle structure at index {i}: Item must be a JSON object")
            try:
                validated_data.append(SubtitleSegment(**item).model_dump())
            except ValidationError as ve:
                logger.error(f"Validation error in segment at index {i}: {ve}")
                raise HTTPException(status_code=400, detail=f"Invalid subtitle structure at index {i}: {ve}")
        
        # アトミックな書き込みを導入
        import os
        import uuid
        
        temp_dir = SEGMENTS_PATH.parent
        # builtins.openをモックする既存テストが正常に反応するよう、ファイル名に"subtitle_result"を含める
        temp_file_path = temp_dir / f"subtitle_result_temp_{uuid.uuid4().hex}.tmp"
        try:
            try:
                # 親ディレクトリがなければ作成（OSErrorキャッチの対象にする）
                temp_dir.mkdir(parents=True, exist_ok=True)
                with open(temp_file_path, "w", encoding="utf-8") as tmp_f:
                    json.dump(validated_data, tmp_f, ensure_ascii=False, indent=2)
                os.replace(temp_file_path, SEGMENTS_PATH)
            except (TypeError, ValueError) as file_err:
                logger.error(f"Serialization error for segments: {file_err}")
                raise HTTPException(status_code=400, detail=f"Serialization failed: {file_err}")
            except OSError as file_err:
                logger.error(f"Failed to save segments (disk error): {file_err}")
                raise HTTPException(status_code=500, detail="Disk write error or permission denied")
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError as oe:
                    logger.error(f"Failed to remove temporary file {temp_file_path} during cleanup: {oe}")

        return {"status": "saved", "count": len(validated_data)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in save_segments: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected internal server error")


async def _save_upload_file_temp(file: UploadFile) -> str:
    """UploadFileを指定された一時ファイルに保存し、そのパスを返す。途中で失敗した場合はファイルを削除する。"""
    import tempfile
    import os
    filename = file.filename or "temp_upload.tmp"
    suffix = Path(filename).suffix
    tmp_path = None
    success = False
    try:
        # 空のファイルはエラーにする
        chunk_size = 1024 * 1024  # 1MB
        first_chunk = await file.read(chunk_size)
        if not first_chunk:
            raise ValueError("Uploaded file is empty")

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            
            # 最初のチャンクを書き込む
            if isinstance(first_chunk, str):
                tmp.write(first_chunk.encode("utf-8"))
            else:
                tmp.write(first_chunk)

            # メモリ逼迫を防ぐため、チャンク単位で読み書きを行う
            while chunk := await file.read(chunk_size):
                if isinstance(chunk, str):
                    tmp.write(chunk.encode("utf-8"))
                else:
                    tmp.write(chunk)
        success = True
        return tmp_path
    except (OSError, RuntimeError, ValueError) as e:
        logger.error(f"File write failed during temporary save: {e}")
        raise
    finally:
        if not success and tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as oe:
                logger.error(f"Failed to remove incomplete temporary file {tmp_path}: {oe}")


@router.post("/subtitles/transcribe")
async def transcribe_video(file: UploadFile):
    """
    動画をアップロードして字幕を生成
    """
    from subtitle_engine.transcriber import transcriber
    import os
    
    tmp_path = None
    try:
        tmp_path = await _save_upload_file_temp(file)
        # 字幕生成
        result = transcriber.transcribe(tmp_path)
        return result
    except ValueError as e:
        logger.error(f"Invalid input to transcriber: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except (OSError, RuntimeError) as e:
        logger.error(f"Error during video transcription: {e}")
        raise HTTPException(status_code=500, detail="Speech recognition engine error")
    except (TypeError, KeyError, AttributeError) as e:
        logger.error(f"Unexpected structural error during video transcription: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription processing error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in transcribe_video: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected internal server error")
    finally:
        # 一時ファイル削除を優先して実行
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as oe:
                logger.error(f"Failed to remove temporary file {tmp_path}: {oe}")

        if file is not None:
            try:
                await file.close()
            except Exception as e:  # noqa: BLE001
                # **後始末の失敗で結果を上書きしない。**
                # 文字起こしが成功しているのに `close()` の例外が返ると、
                # クライアントには 400/500 が返る。HTTPException もここで止める
                # （2026-08-26: テストは前からこれを主張していたが、
                #   `routers.segments` がモックに差し替わっていて実コードに
                #   届いていなかった）。
                logger.error(f"Failed to close uploaded file: {e}")


def _generate_vtt(subtitles: list) -> str:
    """字幕リストからVTTフォーマットの文字列を生成する"""
    output = "WEBVTT\n\n"
    for sub in subtitles:
        start = _format_time_vtt(sub["start"])
        end = _format_time_vtt(sub["end"])
        output += f"{start} --> {end}\n{sub['text']}\n\n"
    return output


def _generate_srt(subtitles: list) -> str:
    """字幕リストからSRTフォーマットの文字列を生成する"""
    output = ""
    for i, sub in enumerate(subtitles, 1):
        start = _format_time_srt(sub["start"])
        end = _format_time_srt(sub["end"])
        output += f"{i}\n{start} --> {end}\n{sub['text']}\n\n"
    return output


@router.post("/subtitles/export")
async def export_subtitles(format: str, subtitles: list = Body(..., embed=True)):
    """
    字幕を指定形式でエクスポート
    
    Args:
        format: "vtt" or "srt"
        subtitles: 字幕データのリスト
    """
    from fastapi.responses import PlainTextResponse
    
    try:
        if not isinstance(format, str):
            logger.error(f"Invalid format parameter type: {type(format).__name__}")
            raise HTTPException(status_code=400, detail="Format parameter must be a string")
            
        if not isinstance(subtitles, list):
            logger.error(f"Invalid subtitles parameter type: {type(subtitles).__name__}")
            raise HTTPException(status_code=400, detail="Subtitles parameter must be a JSON array")
            
        validated_subtitles = []
        for i, sub in enumerate(subtitles):
            if not isinstance(sub, dict):
                logger.error(f"Subtitle item at index {i} is not a dictionary: {type(sub).__name__}")
                raise HTTPException(status_code=400, detail=f"Invalid subtitle structure at index {i}: Item must be a JSON object")
            try:
                validated_subtitles.append(SubtitleSegment(**sub).model_dump())
            except ValidationError as ve:
                logger.error(f"Validation error in export subtitle at index {i}: {ve}")
                raise HTTPException(status_code=400, detail=f"Invalid subtitle structure at index {i}: {ve}")
        
        fmt_lower = format.lower()
        if fmt_lower == "vtt":
            output = _generate_vtt(validated_subtitles)
            return PlainTextResponse(output, media_type="text/vtt")
        
        elif fmt_lower == "srt":
            output = _generate_srt(validated_subtitles)
            return PlainTextResponse(output, media_type="text/plain")
        
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    except HTTPException:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as e:
        logger.error(f"Failed to export subtitles (format conversion error): {e}")
        raise HTTPException(status_code=400, detail=f"Invalid subtitle structure or format: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in export_subtitles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Unexpected internal server error")


def _format_time_vtt(seconds: float) -> str:
    """VTT形式のタイムスタンプ"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def _format_time_srt(seconds: float) -> str:
    """SRT形式のタイムスタンプ"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

