# Subtitle Engine - 字幕・音声認識エンジンモジュール

本ディレクトリは、動画から字幕データを生成するための音声認識（Whisper）、話者分離、AI校閲、および中間処理データ（チェックポイント）のキャッシュ管理を行うモジュール群を格納しています。

## 📁 構成モジュール

- [video_hash.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/video_hash.py): 動画ファイルのハッシュ算出およびチェックポイントパス生成
- [whisper_subprocess.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/whisper_subprocess.py): Whisper音声認識サブプロセスの制御
- [whisper_transcriber.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/whisper_transcriber.py): 音声認識エンジン本体
- [speaker_diarizer.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/speaker_diarizer.py): 話者分離・識別処理
- [ai_proofreader.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/ai_proofreader.py): 生成字幕のAIによる表記揺れ・誤認識の校閲
- [formatter.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/formatter.py) / [text_formatter.py](file:///c:/Users/PC_User/Desktop/script/video-automation/backend/subtitle_engine/text_formatter.py): 字幕テキストのフォーマット整形（改行、文字数調整など）

---

## 🔑 Video Hash ユーティリティ (`video_hash.py`)

`video_hash.py` は、音声認識処理など時間のかかる処理の進捗をキャッシュ（チェックポイント）として追跡・保存するため、動画ファイルごとに一意のハッシュ値を算出する機能を提供します。

### 特徴
- **SHA-256 ハッシュの算出**: 動画ファイルのバイナリデータを高速に走査し、SHA-256ハッシュを計算します。
- **チェックポイントの自動パス解決**: 相対パスの解決を行い、常に一貫した絶対パスベースでキャッシュ（`_whisper_{hash}.jsonl`）の生成先を特定します。
- **安全なバリデーション**: 動画パスの型、ハッシュ長などのパラメータに対して厳格なチェックを行い、不正な入力に対する迅速なエラー返却を行います。

### 主な API

#### `compute_video_hash(video_path: Union[str, Path], length: int = 8) -> str`
動画ファイルの SHA-256 ハッシュ値を算出し、その先頭 `length` 文字（16進数）を返します。
- **引数**:
  - `video_path`: 対象動画ファイルへのパス（`str` または `Path`）。
  - `length`: 抽出する文字数（デフォルトは `8`。最大 `64` 文字）。
- **発生しうる例外**:
  - `TypeError`: パスやハッシュ長の型が不正な場合。
  - `FileNotFoundError`: 指定されたファイルが存在しない場合。
  - `ValueError`: パスが通常ファイルではない場合、またはハッシュ長が 0 以下の場合。
  - `PermissionError`: ファイルの読み込み権限がない場合。
  - `OSError`: その他のディスクI/Oエラーが発生した場合。

#### `get_checkpoint_path(video_path: Union[str, Path]) -> str`
動画ファイルに対応するハッシュ付きチェックポイントのパス文字列（絶対パス）を返します。
- **返却パスの形式**: `{動画のディレクトリ}/_whisper_{hash}.jsonl`
- **使用例**:
  ```python
  from subtitle_engine.video_hash import get_checkpoint_path

  video = "C:/videos/sample.mp4"
  # 「C:/videos/_whisper_ffe49e2f.jsonl」のようなパスが返されます
  checkpoint = get_checkpoint_path(video)
  ```

---

## 🔄 移行に関する注意点
以前のシステムでは、チェックポイントファイル名として固定文字列 `_whisper_segments.jsonl`（`OLD_CHECKPOINT_NAME` 定数に格納）が使用されていました。
現在は、同一ディレクトリで複数の動画が並行処理された際の競合を防ぐため、動画ハッシュ値を用いた動的ファイル名（例: `_whisper_{hash}.jsonl`）が標準となっています。
古いキャッシュデータを明示的にクリアまたは移行する場合は、この仕様変更に留意してください。
