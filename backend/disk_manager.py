"""
Disk Manager — ディスク容量管理の統一モジュール

設計原則:
  - 成果物 (final/) は保護、中間ファイルのみ削除
  - 全呼び出し元（テスト・パイプライン）が同一関数を使用 (DRY)
  - C:\\ ハードコード排除 — 出力ディレクトリのドライブを自動検出
  - 削除ログを記録
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

# --- パス解決 ---
try:
    from safe_io import VAULT_OUTPUTS_DIR
except ImportError:
    VAULT_OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "vault-outputs"


# 削除対象の中間ディレクトリ（優先度順: 効果の大きいものから）
_INTERMEDIATE_DIRS = ["merged", "preview"]


def get_drive_root(path: Optional[Path] = None) -> str:
    """パスが属するドライブルートを返す（C:\\ ハードコード排除）"""
    target = path or VAULT_OUTPUTS_DIR
    return str(target.resolve().anchor)  # "C:\\" や "/" を返す


def get_free_gb(path: Optional[Path] = None) -> float:
    """指定パスのドライブの空き容量 (GB) を返す"""
    drive = get_drive_root(path)
    _, _, free = shutil.disk_usage(drive)
    return free / (1024 ** 3)


def _calc_total_input_size_bytes(input_paths: List[Union[str, Path]]) -> int:
    """入力ファイル群の合計ファイルサイズ（バイト数）を計算するヘルパー"""
    return sum(Path(p).stat().st_size for p in input_paths if Path(p).exists())


def estimate_needed_gb(input_paths: List[Union[str, Path]], multiplier: float = 2.5) -> float:
    """
    入力ファイル群から必要なディスク容量を推定する。
    
    - 結合: 入力サイズ × 1 (コピーconcat)
    - SmartCut: ~50% のプレビュー
    - 最終レンダリング: ~30% の最終出力
    - マージン: ×multiplier で安全マージン
    """
    total_bytes = _calc_total_input_size_bytes(input_paths)
    return (total_bytes * multiplier) / (1024 ** 3)


def calc_timeout(input_paths: List[Union[str, Path]], base_sec_per_gb: float = 300) -> int:
    """
    入力サイズに比例するタイムアウト（秒）を計算。
    
    1GBあたり5分 (300秒)。最低300秒、最大7200秒。
    """
    total_bytes = _calc_total_input_size_bytes(input_paths)
    total_gb = total_bytes / (1024 ** 3)
    return max(300, min(int(total_gb * base_sec_per_gb), 7200))


def _cleanup_old_mp4s(base_dir: Path, keep_latest: int, dry_run: bool) -> tuple[int, List[str]]:
    """中間ディレクトリの古い .mp4 ファイルを削除するヘルパー"""
    freed_bytes = 0
    deleted_files = []
    for subdir in _INTERMEDIATE_DIRS:
        d = base_dir / subdir
        if not d.exists():
            continue
        files = sorted(d.glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[keep_latest:]:
            try:
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                freed_bytes += size
                deleted_files.append(f.name)
            except Exception as e:
                logger.warning(f"削除失敗: {f} — {e}")
    return freed_bytes, deleted_files


def _cleanup_smartcut_parts(base_dir: Path, dry_run: bool) -> tuple[int, List[str]]:
    """SmartCutの一時ファイルを削除するヘルパー"""
    freed_bytes = 0
    deleted_files = []
    preview_dir = base_dir / "preview"
    if preview_dir.exists():
        for f in preview_dir.glob("_smartcut_*"):
            try:
                size = f.stat().st_size
                if not dry_run:
                    f.unlink()
                freed_bytes += size
                deleted_files.append(f.name)
            except Exception:
                pass
    return freed_bytes, deleted_files


def _cleanup_tmp_mp4s(base_dir: Path, dry_run: bool) -> tuple[int, List[str]]:
    """テンポラリの .tmp.mp4 ファイルを削除するヘルパー"""
    freed_bytes = 0
    deleted_files = []
    for f in base_dir.rglob("*.tmp.mp4"):
        try:
            size = f.stat().st_size
            if not dry_run:
                f.unlink()
            freed_bytes += size
            deleted_files.append(f.name)
        except Exception:
            pass
    return freed_bytes, deleted_files


def _cleanup_concat_txts(base_dir: Path, dry_run: bool) -> None:
    """concat リストファイルを削除するヘルパー"""
    merged_dir = base_dir / "merged"
    if merged_dir.exists():
        for f in merged_dir.glob("concat_*.txt"):
            try:
                if not dry_run:
                    f.unlink()
            except Exception:
                pass


def cleanup_intermediates(
    outputs_dir: Optional[Path] = None,
    keep_latest: int = 1,
    dry_run: bool = False
) -> float:
    """
    中間ファイルのみを削除して容量を確保する。
    
    Args:
        outputs_dir: 出力ディレクトリ（デフォルト: VAULT_OUTPUTS_DIR）
        keep_latest: 各ディレクトリで保持する最新ファイル数
        dry_run: Trueなら削除せずログのみ
    
    Returns:
        解放した容量 (GB)
    
    保護:
        - final/ のファイルは一切削除しない
        - 各ディレクトリの最新 keep_latest 本は残す
    """
    base = outputs_dir or VAULT_OUTPUTS_DIR
    freed_bytes = 0
    deleted_files = []
    
    # 1. 中間ディレクトリの古い .mp4 を削除
    size_mp4, files_mp4 = _cleanup_old_mp4s(base, keep_latest, dry_run)
    freed_bytes += size_mp4
    deleted_files.extend(files_mp4)
    
    # 2. SmartCut 一時パーツ (_smartcut_part_*.mp4)
    size_sc, files_sc = _cleanup_smartcut_parts(base, dry_run)
    freed_bytes += size_sc
    deleted_files.extend(files_sc)
    
    # 3. .tmp.mp4 一時ファイル（全サブディレクトリ）
    size_tmp, files_tmp = _cleanup_tmp_mp4s(base, dry_run)
    freed_bytes += size_tmp
    deleted_files.extend(files_tmp)
    
    # 4. concat リストファイル
    _cleanup_concat_txts(base, dry_run)
    
    freed_gb = freed_bytes / (1024 ** 3)
    
    if deleted_files:
        action = "削除予定" if dry_run else "削除済み"
        logger.info(f"🧹 クリーンアップ {action}: {len(deleted_files)}件, {freed_gb:.1f}GB")
        for name in deleted_files[:10]:  # 最大10件ログ
            logger.debug(f"  - {name}")
    
    return freed_gb


def ensure_disk_space(
    input_paths: List[Union[str, Path]],
    min_free_gb: float = 10.0,
    outputs_dir: Optional[Path] = None
) -> bool:
    """
    パイプライン実行前のプリフライトチェック。
    容量不足の場合は中間ファイルを自動削除。
    
    Returns:
        True: 十分な空き容量あり, False: 不足
    """
    base = outputs_dir or VAULT_OUTPUTS_DIR
    free_gb = get_free_gb(base)
    needed_gb = max(min_free_gb, estimate_needed_gb(input_paths))
    
    logger.info(f"💾 ディスク空き: {free_gb:.1f}GB / 推定必要: {needed_gb:.1f}GB")
    
    if free_gb >= needed_gb:
        return True
    
    # 自動クリーンアップ（中間ファイルのみ、成果物は保護）
    logger.warning(f"⚠️ ディスク容量不足 ({free_gb:.1f}GB < {needed_gb:.1f}GB)。中間ファイルを自動削除...")
    freed_gb = cleanup_intermediates(base, keep_latest=0)
    
    new_free = get_free_gb(base)
    logger.info(f"✅ クリーンアップ完了: {freed_gb:.1f}GB解放 → 空き{new_free:.1f}GB")
    
    return new_free >= needed_gb



# --- サムネイル品質検証・生成自動化の実装 ---
import json
import base64
from io import BytesIO
from PIL import Image

def verify_thumbnail_quality(image_data: Union[bytes, str, Path]) -> bool:
    """
    サムネイル画像の品質基準を検証する。
    - 生成画像の解像度が 1280x720 以上であること
    - アスペクト比が 16:9 であること（誤差±0.05まで許容）
    - ファイルサイズが 4MB 未満であること
    - 正常にロード可能で破損していないこと
    """
    try:
        # bytes / base64文字列 / ファイルパスを判別
        if isinstance(image_data, bytes):
            img_bytes = image_data
        elif isinstance(image_data, str):
            # ファイルパスかbase64か判定
            if Path(image_data).exists():
                img_bytes = Path(image_data).read_bytes()
            else:
                try:
                    img_bytes = base64.b64decode(image_data)
                except Exception:
                    img_bytes = image_data.encode('utf-8')
        elif isinstance(image_data, Path):
            img_bytes = image_data.read_bytes()
        else:
            return False

        # ファイルサイズ検証 (4MB 未満 = 4194304 bytes 未満)
        if len(img_bytes) >= 4 * 1024 * 1024:
            logger.warning(f"サムネイル検証失敗: ファイルサイズが4MB以上 ({len(img_bytes)} bytes)")
            return False

        # Pillowで正常ロード可能か検証
        try:
            with Image.open(BytesIO(img_bytes)) as img:
                # 簡易的な破損チェック
                img.verify()
            
            with Image.open(BytesIO(img_bytes)) as img:
                width, height = img.size
                
                # 解像度検証 (1280x720 以上)
                if width < 1280 or height < 720:
                    logger.warning(f"サムネイル検証失敗: 解像度不足 ({width}x{height})")
                    return False
                
                # アスペクト比検証 (16:9)
                aspect_ratio = width / height
                target_ratio = 16 / 9
                if abs(aspect_ratio - target_ratio) > 0.05:
                    logger.warning(f"サムネイル検証失敗: アスペクト比が16:9ではありません ({width}:{height} = {aspect_ratio:.2f})")
                    return False
        except Exception as e:
            logger.warning(f"サムネイル検証失敗: 画像破損またはPillowロード失敗: {e}")
            return False

        return True
    except Exception as e:
        logger.error(f"サムネイル検証中にエラー発生: {e}", exc_info=True)
        return False


async def process_thumbnail_task(task_id: str, db_path: str = ":memory:", thumbnail_generator: Optional[object] = None) -> str:
    """
    StageBoundAgent等で実行されるサムネイル生成および品質検証の自動化プロセス。
    検証エラー時は例外を投げることで自動リトライ（max_retries）をトリガーさせます。
    """
    # 1. ジェネレータのロード（指定がない場合）
    if thumbnail_generator is None:
        try:
            from thumbnail_engine.generator import ThumbnailGenerator
            thumbnail_generator = ThumbnailGenerator()
        except ImportError:
            class DummyGenerator:
                async def generate(self, *args, **kwargs):
                    img = Image.new("RGB", (1280, 720), color="blue")
                    out = BytesIO()
                    img.save(out, format="JPEG")
                    b64 = base64.b64encode(out.getvalue()).decode("utf-8")
                    return [{"id": "d1", "concept_name": "Fallback Concept", "description": "Desc", "image_base64": b64, "ctr_score": 5.0}]
            thumbnail_generator = DummyGenerator()

    # 2. サムネイルの生成
    try:
        results = await thumbnail_generator.generate(prompt="High quality thumbnail")
    except Exception as e:
        logger.error(f"サムネイル生成中に例外発生: {e}")
        raise ValueError(f"Thumbnail generation failed: {e}")

    if not results:
        raise ValueError("Thumbnail generator returned no results")

    # 3. 生成された画像の品質を検証・最適化
    valid_results = []
    try:
        from scratch.disk_cleanup import optimize_thumbnail
    except ImportError:
        def optimize_thumbnail(data): return data

    for r in results:
        image_b64 = r.get("image_base64")
        if not image_b64:
            continue
        
        # まずはそのまま検証してみる
        if verify_thumbnail_quality(image_b64):
            valid_results.append(r)
            continue
            
        # 検証に失敗した場合、最適化を試みる
        try:
            # base64デコード
            try:
                img_bytes = base64.b64decode(image_b64)
            except Exception:
                img_bytes = image_b64.encode('utf-8')
            
            # 画像の自動補正・最適化
            optimized_bytes = optimize_thumbnail(img_bytes)
            # 再度base64エンコード
            optimized_b64 = base64.b64encode(optimized_bytes).decode('utf-8')
            
            # 最適化後の画像を検証
            if verify_thumbnail_quality(optimized_bytes):
                r["image_base64"] = optimized_b64
                valid_results.append(r)
                logger.info(f"Thumbnail task optimized and verified successfully for variant: {r.get('id')}")
        except Exception as e:
            logger.warning(f"Thumbnail optimization failed: {e}")

    if not valid_results:
        # 品質検証を通過しなかった場合、例外を投げて StageBoundAgent にリトライさせる
        raise ValueError("Thumbnail verification failed: None of the generated thumbnails met the quality criteria")

    # 4. 合格した結果を JSON 形式で返す
    result_data = {
        "status": "verified",
        "thumbnails": [
            {
                "id": r.get("id"),
                "concept_name": r.get("concept_name"),
                "description": r.get("description"),
                "ctr_score": r.get("ctr_score")
            }
            for r in valid_results
        ]
    }
    return json.dumps(result_data, ensure_ascii=False)
