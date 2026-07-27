"""
auto_editor_wrapper.py — Auto-Editor CLI Wrapper

S5: SmartCut のベースエンジンとして WyattBlue/auto-editor を呼び出すラッパー。
システムPATH上の実行コマンドまたは `python -m auto_editor` を動的に解決して実行。
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Union, List

logger = logging.getLogger(__name__)


class AutoEditorWrapper:
    """Auto-Editor CLI Wrapper Class.
    
    WyattBlue/auto-editor コマンドを実行し、動画の自動カットを処理します。
    """

    def __init__(self, executable_path: Optional[str] = None):
        """
        Args:
            executable_path: 明示的に指定する auto-editor の実行バイナリパス
        """
        self.executable_path = executable_path

    def _resolve_command(self) -> List[str]:
        """実行コマンドを動的に解決する。
        
        1. 明示的に指定されたパスがある場合はそれを使用
        2. `python -m auto_editor` によるモジュール実行（推奨フォールバック）
        
        Returns:
            List[str]: 実行コマンドのプレフィックス
        """
        if self.executable_path:
            return [self.executable_path]
            
        # python -m auto_editor は最も環境依存リスクが低いためデフォルトで使用
        return ["python", "-m", "auto_editor"]

    def _run_command(self, cmd: List[str]) -> subprocess.CompletedProcess:
        """subprocessを安全に呼び出す。テストでモックしやすいように分離。
        
        Args:
            cmd: 実行コマンドリスト
            
        Returns:
            subprocess.CompletedProcess: 実行結果
        """
        logger.info(f"Executing: {' '.join(cmd)}")
        return subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )

    def run_smart_cut(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        margin: str = "0.2s",
        threshold: float = 0.04,
        silent_speed: float = 99999.0,
        extra_args: Optional[List[str]] = None
    ) -> bool:
        """無音区間の自動ジャンプカットを実行する。
        
        Args:
            input_path: 入力動画ファイルのパス
            output_path: 出力動画ファイルのパス
            margin: カットマージン（例: "0.2s", "6f"）
            threshold: 音声振幅のしきい値 (0.0 〜 1.0)
            silent_speed: 無音区間の再生速度 (デフォルト: 99999.0 = 完全カット)
            extra_args: 追加で渡す任意オプション
            
        Returns:
            bool: 成功した場合は True
            
        Raises:
            FileNotFoundError: 入力ファイルが存在しない場合
            subprocess.CalledProcessError: auto-editorが失敗した場合
        """
        in_path = Path(input_path).resolve()
        out_path = Path(output_path).resolve()

        if not in_path.exists():
            raise FileNotFoundError(f"Input file not found: {in_path}")

        # 出力ディレクトリの作成
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # コマンドの組み立て
        cmd = self._resolve_command()
        cmd.append(str(in_path))
        
        # 編集設定
        cmd.extend(["--edit", f"audio:threshold={threshold}"])
        cmd.extend(["--margin", margin])
        
        # 無音区間のアクション設定
        if silent_speed >= 99999.0:
            cmd.extend(["--when-silent", "cut"])
        else:
            cmd.extend(["--when-silent", f"speed:{silent_speed}"])

        # 出力ファイル設定
        cmd.extend(["--output", str(out_path)])
        
        # その他のオプション
        cmd.append("--no-open")  # 編集完了後にプレイヤーで再生しない
        
        if extra_args:
            cmd.extend(extra_args)

        try:
            result = self._run_command(cmd)
            logger.debug(f"auto-editor stdout: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"auto-editor failed with exit code {e.returncode}")
            logger.error(f"stderr: {e.stderr}")
            raise
