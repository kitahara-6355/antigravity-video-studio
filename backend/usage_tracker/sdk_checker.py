"""
SDK Compatibility Checker - SDK互換性自動チェック

PROJECT_CONSTITUTION §18 準拠:
- 起動時にSDKで利用可能なモデルを確認
- 非互換モデルを検知して警告
- 自動フォールバック
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path

from typing import Dict, Any, List, Optional, Set
from pathlib import Path
from datetime import datetime
import json
import logging
import asyncio
from PIL import Image, ImageDraw
import uuid

logger = logging.getLogger(__name__)

OUTPUT_DIR = str(_writable_path("backend/temp_thumbnails"))


class SDKCompatibilityChecker:
    """
    SDK互換性チェッカー
    
    起動時と定期的にSDKで利用可能なモデルを確認し、
    model_config.jsonとの互換性をチェックする。
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        # 外部から設定パスを差し替え可能にし、テストの柔軟性を高める
        self._config_path: Path = config_path or (Path(__file__).parent.parent / "model_config.json")
        self._available_models: Set[str] = set()
        self._incompatible_models: List[str] = []
        self._last_check: Optional[str] = None
        self._client: Optional[Any] = None
    
    def _get_genai_client(self) -> Optional[Any]:
        """GenAI クライアントを取得 (リファクタリング前の _get_client のエイリアスも維持)"""
        if self._client is None:
            try:
                from gemini_client_factory import get_gemini_client
                self._client = get_gemini_client()
            except ImportError as e:
                # 具体的例外の捕捉 (TDR TD-573 の部分的な解消)
                logger.error(f"google-genai SDK not installed or missing factory: {e}")
            except Exception as e:
                # 予期せぬ例外の捕捉。ロギングを詳細化してスタックトレースを記録
                logger.exception(f"Failed to initialize GenAI client due to unexpected error: {e}")
        return self._client

    def _get_client(self) -> Optional[Any]:
        """後方互換性のためのエイリアス"""
        return self._get_genai_client()
    
    async def check_compatibility(self) -> Dict[str, Any]:
        """
        SDK互換性をチェック
        
        Returns:
            チェック結果（互換モデル、非互換モデル、警告）
        """
        # 開始時に非互換モデルリストをクリアし、複数回チェック時の累積バグを解消
        self._incompatible_models.clear()

        report = {
            "timestamp": datetime.now().isoformat(),
            "compatible": [],
            "incompatible": [],
            "warnings": [],
            "sdk_version": self._get_sdk_version()
        }
        
        # 利用可能なモデルを取得
        available_models = await self._fetch_available_models()
        
        if not available_models:
            report["warnings"].append("SDKからモデル一覧を取得できませんでした")
            return report
        
        self._available_models = available_models
        
        # model_config.jsonをロード
        model_config = self._load_config()
        if not model_config:
            report["warnings"].append("model_config.jsonを読み込めませんでした")
            return report
        
        # 各モデルの互換性をチェック (関数分割による複雑度の軽減)
        self._assess_all_models_compatibility(model_config, available_models, report)
        
        self._last_check = report["timestamp"]
        
        # ログ出力
        self._log_result(report)
        
        return report

    def _assess_all_models_compatibility(
        self, model_config: Dict[str, Any], available_models: Set[str], report: Dict[str, Any]
    ) -> None:
        """すべてのモデルの互換性を評価する"""
        for model_name, model_info in model_config.get("models", {}).items():
            if model_info.get("status") == "deprecated":
                continue
            self._assess_single_model_compatibility(model_name, model_info, available_models, report)

    def _assess_single_model_compatibility(
        self, model_name: str, model_info: Dict[str, Any], available_models: Set[str], report: Dict[str, Any]
    ) -> None:
        """単一のモデルの互換性を評価し、結果と警告を設定する"""
        if self._is_model_available(model_name, available_models):
            report["compatible"].append({
                "model": model_name,
                "tier": model_info.get("tier"),
                "status": "available"
            })
        else:
            fallback_model = model_info.get("fallback")
            report["incompatible"].append({
                "model": model_name,
                "tier": model_info.get("tier"),
                "fallback": fallback_model,
                "status": "not_available"
            })
            self._incompatible_models.append(model_name)
            self._record_incompatibility_warning(model_name, fallback_model, report)

    def _record_incompatibility_warning(
        self, model_name: str, fallback_model: Optional[str], report: Dict[str, Any]
    ) -> None:
        """非互換モデルに対する警告を生成して追加する"""
        if fallback_model:
            report["warnings"].append(
                f"⚠️ {model_name} はSDKで利用不可。{fallback_model} にフォールバックします。"
            )
        else:
            report["warnings"].append(
                f"🛑 {model_name} はSDKで利用不可。フォールバック先がありません。"
            )
    
    def _normalize_model_name(self, model: Any) -> str:
        """モデル名を取得し正規化（プレフィックスの除去など）"""
        name = getattr(model, 'name', str(model))
        if '/' in name:
            name = name.split('/')[-1]
        return name

    async def _fetch_available_models(self) -> Set[str]:
        """SDKから利用可能なモデル一覧を取得"""
        available_models = set()
        
        client = self._get_genai_client()
        if not client:
            return available_models
        
        try:
            # 同期APIを非同期で実行（lambda式を排除）
            models = await asyncio.to_thread(self._list_models_sync, client)
            
            for model in models:
                available_models.add(self._normalize_model_name(model))
                
        except Exception as e:
            # 例外のロギング強化 (TDR TD-574)。スタックトレースを出力
            logger.exception(f"Failed to fetch available models: {e}")
        
        return available_models

    def _list_models_sync(self, client: Any) -> List[Any]:
        """同期的にモデル一覧を取得してリスト化する"""
        return list(client.models.list())
    
    def _is_model_available(self, model_name: str, available_models: Set[str]) -> bool:
        """モデルが利用可能かチェック（名前のバリエーション対応）"""
        if self._is_exact_match(model_name, available_models):
            return True
        
        if self._is_variant_match(model_name, available_models):
            return True
        
        if self._is_partial_match(model_name, available_models):
            return True
        
        return False

    def _is_exact_match(self, model_name: str, available_models: Set[str]) -> bool:
        """完全一致によるモデル利用可能性チェック"""
        return model_name in available_models

    def _is_variant_match(self, model_name: str, available_models: Set[str]) -> bool:
        """バリエーション（プレフィックス等）によるモデル利用可能性チェック"""
        variants = [
            f"models/{model_name}",
            f"gemini/{model_name}",
            model_name.replace("-", "_"),
        ]
        return any(variant in available_models for variant in variants)

    def _is_partial_match(self, model_name: str, available_models: Set[str]) -> bool:
        """部分一致によるモデル利用可能性チェック"""
        return any(model_name in avail or avail in model_name for avail in available_models)
    
    def _load_config(self) -> Optional[Dict[str, Any]]:
        """model_config.jsonをロード"""
        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError as e:
            # 具体的例外の捕捉 (TDR TD-575)
            logger.error(f"model_config.json file not found at {self._config_path}: {e}")
        except json.JSONDecodeError as e:
            # 具体的例外の捕捉 (TDR TD-575)
            logger.error(f"Failed to decode JSON from model_config.json: {e}")
        except PermissionError as e:
            # 具体的例外の捕捉 (TDR TD-575)
            logger.error(f"Permission denied reading model_config.json: {e}")
        except Exception as e:
            # 予期せぬ例外の捕捉。ロギングを詳細化してスタックトレースを記録
            logger.exception(f"Unexpected error loading model_config.json: {e}")
        return None
    
    def _get_sdk_version(self) -> str:
        """SDKバージョンを取得"""
        try:
            from google import genai
            return getattr(genai, "__version__", "unknown")
        except ImportError as e:
            logger.debug(f"google-genai is not installed: {e}")
            return "not_installed"
        except Exception as e:
            logger.exception(f"Unexpected error getting SDK version: {e}")
            return "unknown"
    
    def _log_result(self, report: Dict[str, Any]) -> None:
        """結果をログ出力"""
        compatible_count = len(report["compatible"])
        incompatible_count = len(report["incompatible"])
        
        if incompatible_count == 0:
            logger.info(
                f"✅ SDK互換性チェック完了: {compatible_count}モデルが利用可能"
            )
        else:
            logger.warning(
                f"⚠️ SDK互換性チェック: {compatible_count}モデル互換, "
                f"{incompatible_count}モデル非互換"
            )
            for warning in report["warnings"]:
                logger.warning(warning)
    
    def _fetch_fallback_model(self, model_name: str) -> Optional[str]:
        """設定ファイルから指定モデルのフォールバック先を取得"""
        model_config = self._load_config()
        if not model_config:
            return None
        return model_config.get("models", {}).get(model_name, {}).get("fallback")

    def get_available_model(self, preferred: str) -> str:
        """
        利用可能なモデルを取得（フォールバック対応）
        """
        if preferred in self._available_models:
            return preferred
        
        if preferred in self._incompatible_models:
            fallback = self._fetch_fallback_model(preferred)
            if fallback and fallback in self._available_models:
                logger.warning(f"Using fallback: {preferred} -> {fallback}")
                return fallback
        
        return preferred  # フォールバックがなければ元のモデルを返す
    
    def is_compatible(self, model_name: str) -> bool:
        """モデルが互換性があるかチェック"""
        return model_name in self._available_models
    
    def get_last_check_time(self) -> Optional[str]:
        """最後のチェック時刻を取得"""
        return self._last_check


# シングルトンインスタンス
sdk_checker = SDKCompatibilityChecker()


async def run_compatibility_check() -> Dict[str, Any]:
    """互換性チェックを実行"""
    return await sdk_checker.check_compatibility()


def generate_sdk_checker_thumbnail(output_path, width=1280, height=720, text=None):
    """Pillowを使用して、SDK互換性チェッカーのサムネイル画像を生成する"""
    try:
        width = int(width)
        height = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width <= 0 or height <= 0:
        raise ValueError(f"Width and height must be positive integers.")
        
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 描画テキストの準備
    if not text:
        text = f"SDK Compatibility Checker Report\nGenerated at: {datetime.now().isoformat()}"
        
    # 画像生成と描画
    img = _create_thumbnail_image(width, height, text)
    
    # 原子的な書き込み (Atomic Write) の実行
    _save_image_atomically(img, output_path)
        
    return output_path


def _create_thumbnail_image(width: int, height: int, text: str) -> Image.Image:
    """Pillow画像オブジェクトを作成し、テキストを描画する"""
    img = Image.new("RGB", (width, height), color=(30, 45, 30))
    d = ImageDraw.Draw(img)
    d.text((40, 40), text, fill=(255, 255, 255))
    return img


def _save_image_atomically(img: Image.Image, output_path: Path) -> None:
    """一時ファイルを使用して画像を安全かつ原子的に保存する"""
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        img.save(temp_path, "PNG")
        if output_path.exists():
            output_path.unlink()
        temp_path.rename(output_path)
    except (OSError, ValueError) as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise e


def validate_thumbnail(file_path) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    file_path = Path(file_path)
    _validate_file_existence_and_size(file_path)
        
    # 画像の検証と読み込み
    width, height = _validate_image_integrity_and_dimensions(file_path)
    
    # アスペクト比の検証
    _validate_aspect_ratio(width, height)
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": file_path.stat().st_size
    }


def _validate_file_existence_and_size(file_path: Path) -> None:
    """ファイルの存在とサイズ制限を検証する"""
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= 4 * 1024 * 1024:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")


def _validate_image_integrity_and_dimensions(file_path: Path) -> tuple[int, int]:
    """画像の整合性を検証し、解像度を取得する"""
    # 1. 簡易的なverify
    try:
        with Image.open(file_path) as img:
            img.verify()
    except (OSError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知と解像度チェック
    try:
        with Image.open(file_path) as img:
            img.load()  # ピクセルデータのロードを強制
            width, height = img.size
    except (OSError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format: {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    return width, height


def _validate_aspect_ratio(width: int, height: int) -> None:
    """アスペクト比が16:9であることを検証する"""
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01:
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")


async def resolve_sdk_checker_task(task_id: str) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    """
    # 互換性チェックを実行
    checker = SDKCompatibilityChecker()
    results = await checker.check_compatibility()
    
    comp_models = ", ".join([m["model"] for m in results.get("compatible", [])])
    incomp_models = ", ".join(results.get("incompatible", []))
    
    text = (
        f"=== SDK Compatibility Report ===\n"
        f"Timestamp: {results.get('timestamp')}\n"
        f"Compatible Models: {comp_models if comp_models else 'None'}\n"
        f"Incompatible Models: {incomp_models if incomp_models else 'None'}\n"
        f"SDK Version: {results.get('sdk_version')}\n"
    )
        
    output_dir_path = Path(OUTPUT_DIR)
    output_path = output_dir_path / f"{task_id}.png"
    
    generate_sdk_checker_thumbnail(output_path, text=text)
    result_info = validate_thumbnail(output_path)
    
    return json.dumps(result_info)
