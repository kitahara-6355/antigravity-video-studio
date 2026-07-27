"""動画ファイルのハッシュ算出およびチェックポイントパス生成ユーティリティ。

動画ファイルごとに固有のチェックポイントキャッシュパス（中間処理データ）を生成するため、
SHA-256ハッシュを計算し、その先頭N文字（デフォルト8文字）を算出する機能を提供します。
これにより、同一ファイルに対する重複処理を防ぎ、進捗の追跡やレジュームを可能にします。
"""

import hashlib
from pathlib import Path
from typing import BinaryIO, Union


def _validate_video_path_type(path: Union[str, Path]) -> None:
    """動画ファイルパスの型が str または Path であるかを検証します。

    Args:
        path (Union[str, Path]): 検証対象の動画ファイルパス。

    Raises:
        TypeError: パスの型が str または Path のいずれでもない場合に発生します。
    """
    if not isinstance(path, (str, Path)):
        raise TypeError(f"動画ファイルパスは str または Path でなければなりません: {type(path)}")


def _validate_hash_length_param(hash_length: int) -> None:
    """ハッシュの長さパラメータが有効な整数値であるかを検証します。

    Args:
        hash_length (int): 抽出するハッシュ文字列の長さ（正の整数）。

    Raises:
        TypeError: hash_length の型が int ではない場合に発生します。
        ValueError: hash_length が 0 以下の場合に発生します。
    """
    if type(hash_length) is not int:
        raise TypeError(f"ハッシュの長さは整数でなければなりません: {type(hash_length)}")

    if hash_length <= 0:
        raise ValueError(f"ハッシュの長さは正の整数でなければなりません: {hash_length}")


def _validate_hash_inputs(video_path: Union[str, Path], length: int) -> None:
    """入力された動画パスとハッシュ長パラメータのバリデーションをまとめて行います。

    Args:
        video_path (Union[str, Path]): 動画ファイルパス (str または Path)。
        length (int): 抽出するハッシュ文字列の長さ。

    Raises:
        TypeError: パスまたは length の型が正しくない場合に発生します。
        ValueError: length が 0 以下の場合に発生します。
    """
    _validate_video_path_type(video_path)
    _validate_hash_length_param(length)


def _normalize_to_absolute_path(path: Union[str, Path]) -> Path:
    """相対パスや揺らぎを排除するために、パスを解決して絶対パスに正規化します。

    Args:
        path (Union[str, Path]): 対象のファイルパス (str または Path)。

    Returns:
        Path: 絶対パス化された Path オブジェクト。
    """
    return Path(path).resolve()


def _validate_file_exists_and_is_file(file_path: Path) -> None:
    """指定されたパスが存在し、かつ通常のファイルであるかを検証します。

    Args:
        file_path (Path): 検証対象の Path オブジェクト。

    Raises:
        FileNotFoundError: 指定されたパスにファイルが存在しない場合に発生します。
        ValueError: 指定されたパスがファイルではなくディレクトリなどの場合に発生します。
    """
    if not file_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"指定されたパスはファイルではありません: {file_path}")


def _compute_sha256_from_stream(stream: BinaryIO) -> str:
    """バイナリファイルストリームから SHA-256 ハッシュを算出します。

    引数で渡されたストリームを効率的に読み込み、64文字の16進数ハッシュ文字列を生成します。

    Args:
        stream (BinaryIO): 読み込み可能なバイナリファイルオブジェクト。

    Returns:
        str: 算出された SHA-256 ハッシュ（小文字16進数、64文字）。
    """
    sha256 = hashlib.file_digest(stream, "sha256")
    return sha256.hexdigest()


def _read_and_compute_file_sha256(file_path: Path) -> str:
    """指定されたファイルをバイナリ読み込みし、SHA-256 ハッシュ値を算出します。

    Args:
        file_path (Path): 対象ファイルの Path オブジェクト。

    Returns:
        str: 算出された SHA-256 ハッシュ（小文字16進数、64文字）。

    Raises:
        PermissionError: 動画ファイルの読み取り権限がない場合に発生します。
        OSError: 動画ファイルの読み込み中に予期せぬ I/O エラーが発生した場合に発生します。
    """
    try:
        with open(file_path, "rb") as f:
            return _compute_sha256_from_stream(f)
    except PermissionError as e:
        raise PermissionError(f"動画ファイルの読み取り権限がありません: {file_path}") from e
    except OSError as e:
        raise OSError(f"動画ファイルの読み込み中にI/Oエラーが発生しました: {file_path}") from e


def compute_video_hash(video_path: Union[str, Path], length: int = 8) -> str:
    """動画ファイルの SHA-256 ハッシュ値を算出し、先頭から指定された長さの文字列を取得します。

    本関数は、動画ファイルの一意性を判定するために対象ファイルのバイナリデータを走査し、
    SHA-256 ハッシュを求めた後、先頭N文字を切り出します。

    Args:
        video_path (Union[str, Path]): 動画ファイルのパス。
        length (int, optional): 抽出するハッシュ文字列の長さ。デフォルトは 8。最大 64。

    Returns:
        str: SHA-256 ハッシュの先頭N文字（小文字16進数）。

    Raises:
        TypeError: パスまたは length の型が正しくない場合に発生します。
        FileNotFoundError: 動画ファイルが存在しない場合に発生します。
        ValueError: パスがファイルではない場合、または length が 0 以下の場合に発生します。
    """
    _validate_hash_inputs(video_path, length)
    resolved_path = Path(video_path)
    _validate_file_exists_and_is_file(resolved_path)
    hex_digest = _read_and_compute_file_sha256(resolved_path)

    # Pythonのスライスは境界値を超えても安全なため、そのままスライスを適用
    return hex_digest[:length]


def _generate_checkpoint_filename(video_hash: str) -> str:
    """ハッシュ値に対応するチェックポイントのファイル名を生成します。

    Args:
        video_hash (str): 動画ファイルのハッシュ値。

    Returns:
        str: `_whisper_{hash}.jsonl` 形式のファイル名。
    """
    return f"_whisper_{video_hash}.jsonl"


def get_checkpoint_path(video_path: Union[str, Path]) -> str:
    """動画ファイルに対応するハッシュ付きチェックポイントパスを取得します。

    渡された動画ファイルパスを絶対パスに正規化した後、そのハッシュ値を算出し、
    同じディレクトリ内にチェックポイントファイル（`_whisper_{hash}.jsonl`）を配置するためのパスを生成します。

    Args:
        video_path (Union[str, Path]): 対象となる動画ファイルのパス。

    Returns:
        str: 絶対パス化されたディレクトリと `_whisper_{hash}.jsonl` を結合したパス文字列。

    Raises:
        TypeError: パスの型が str または Path ではない場合に発生します。
        FileNotFoundError: 動画ファイルが存在しない場合に発生します。
        ValueError: パスが通常ファイルではない場合に発生します。
    """
    _validate_video_path_type(video_path)
    resolved_path = _normalize_to_absolute_path(video_path)
    video_hash = compute_video_hash(resolved_path)
    return str(resolved_path.parent / _generate_checkpoint_filename(video_hash))


# 旧形式のチェックポイントファイル名。移行期間中の互換性維持やクリーンアップのために定義されています。
OLD_CHECKPOINT_NAME = "_whisper_segments.jsonl"


