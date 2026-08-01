"""
daemon_manager.py — Windows対応デーモンプロセスマネージャ

Phase 38 コアモジュール。
バックグラウンドプロセスのライフサイクル管理、Watchdogによるクラッシュ検出・自動再起動、
リソース監視（ResourceGovernor統合）、メモリリーク検出、ディスク容量監視を提供する。

使い方:
    from backend.agents.orchestration.daemon_manager import DaemonManager, DaemonConfig
    manager = DaemonManager()
    pid = manager.start()
    status = manager.status()
    manager.stop()
"""

try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import official_artifact_dir as _official_artifact_dir
except ImportError:
    from path_resolver import official_artifact_dir as _official_artifact_dir

import json
import logging
import logging.handlers
import os
import platform
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

# psutil は未インストール環境でもインポートエラーにならないようにする
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    psutil = None  # type: ignore[assignment]
    HAS_PSUTIL = False

# プロジェクトルートのパス解決
_WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent.parent
_ORCHESTRATION_DIR = Path(__file__).resolve().parent
_EVENT_LOG_PATH = (
    _official_artifact_dir() / "サブエージェント体制報告" / "event_log.jsonl"
)

IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# データクラス定義
# ---------------------------------------------------------------------------

@dataclass
class DaemonConfig:
    """デーモンプロセスの設定。

    Attributes:
        pid_file: PIDファイルのパス。
        log_dir: ログ出力先ディレクトリ。
        max_restart_attempts: 自動再起動の最大試行回数。
        restart_backoff_base: Exponential Backoff の基底秒数 (10s→30s→90s)。
        health_check_interval: ヘルスチェックのポーリング間隔（秒）。
        memory_leak_check_interval: メモリリーク検出の計測間隔（秒）。
        memory_leak_threshold: 起動時メモリ使用量に対する閾値倍率（1.5 = 150%）。
        command: 起動するコマンド（省略時はダミー）。
    """
    pid_file: Path = field(
        default_factory=lambda: _WORKSPACE_DIR / "backend" / "tmp" / "daemon.pid"
    )
    log_dir: Path = field(
        default_factory=lambda: _WORKSPACE_DIR / "backend" / "logs"
    )
    max_restart_attempts: int = 3
    restart_backoff_base: float = 10.0
    health_check_interval: int = 5
    memory_leak_check_interval: int = 1800  # 30分
    memory_leak_threshold: float = 1.5  # 起動時の150%
    command: Optional[List[str]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.pid_file, Path):
            raise TypeError("pid_file must be a Path object")
        if not isinstance(self.log_dir, Path):
            raise TypeError("log_dir must be a Path object")
        if not isinstance(self.max_restart_attempts, int) or self.max_restart_attempts < 0:
            raise ValueError("max_restart_attempts must be a non-negative integer")
        if not isinstance(self.restart_backoff_base, (int, float)) or self.restart_backoff_base <= 0:
            raise ValueError("restart_backoff_base must be a positive number")
        if not isinstance(self.health_check_interval, int) or self.health_check_interval <= 0:
            raise ValueError("health_check_interval must be a positive integer")
        if not isinstance(self.memory_leak_check_interval, int) or self.memory_leak_check_interval <= 0:
            raise ValueError("memory_leak_check_interval must be a positive integer")
        if not isinstance(self.memory_leak_threshold, (int, float)) or self.memory_leak_threshold <= 0:
            raise ValueError("memory_leak_threshold must be a positive number")



@dataclass
class DaemonStatus:
    """デーモンプロセスの現在ステータス。

    Attributes:
        running: プロセスが稼働中か。
        pid: プロセスID（未稼働時はNone）。
        uptime_seconds: 起動からの経過秒数。
        restart_count: 自動再起動された回数。
        resource_state: リソース状態 (NORMAL/CAUTION/CRITICAL)。
        memory_mb: 現在のプロセスメモリ使用量（MB）。
        cpu_percent: 現在のCPU使用率（%）。
        last_health_check: 最後のヘルスチェック時刻（ISO 8601）。
    """
    running: bool = False
    pid: Optional[int] = None
    uptime_seconds: float = 0.0
    restart_count: int = 0
    resource_state: str = "NORMAL"
    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    last_health_check: Optional[str] = None


# ---------------------------------------------------------------------------
# クラッシュ原因分類
# ---------------------------------------------------------------------------

class CrashReason:
    """子プロセスクラッシュの原因分類定数。"""
    OOM = "OOM"
    SEGFAULT = "Segfault"
    UNHANDLED_EXCEPTION = "UnhandledException"
    TIMEOUT = "Timeout"
    UNKNOWN = "Unknown"

    @staticmethod
    def classify(returncode: Optional[int]) -> str:
        """終了コードからクラッシュ原因を推定する。

        Args:
            returncode: プロセスの終了コード。

        Returns:
            クラッシュ原因文字列。
        """
        if returncode is None:
            return CrashReason.TIMEOUT
        # Windows: 負の終了コードはアクセス違反等
        # Unix: -11 = SIGSEGV
        if returncode == -11 or (IS_WINDOWS and returncode == 0xC0000005):
            return CrashReason.SEGFAULT
        # 一般的な OOM killer の終了コード
        if returncode == -9 or returncode == 137:
            return CrashReason.OOM
        if returncode != 0:
            return CrashReason.UNHANDLED_EXCEPTION
        return CrashReason.UNKNOWN


# ---------------------------------------------------------------------------
# JSON Lines ログフォーマッタ
# ---------------------------------------------------------------------------

class _JsonLinesFormatter(logging.Formatter):
    """JSON Lines形式でログレコードをフォーマットする。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Watchdog スレッド
# ---------------------------------------------------------------------------

class WatchdogThread(threading.Thread):
    """子プロセスを監視し、クラッシュ時に自動再起動を試みるデーモンスレッド。

    Exponential Backoff: base → base*3 → base*9 (10s→30s→90s)
    max_restart_attempts 回連続でクラッシュした場合、エスカレーション（ログ + event_log.jsonl記録）。
    """

    def __init__(
        self,
        manager: "DaemonManager",
        check_interval: int = 5,
    ):
        super().__init__(name="DaemonWatchdog", daemon=True)
        self._manager = manager
        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._consecutive_crashes = 0

    def stop(self) -> None:
        """Watchdogスレッドの停止を要求する。"""
        self._stop_event.set()

    def run(self) -> None:
        """メインの監視ループ。"""
        logger = self._manager._get_logger()
        logger.info("Watchdog スレッドを開始しました")

        while not self._stop_event.is_set():
            self._stop_event.wait(self._check_interval)
            if self._stop_event.is_set():
                break

            proc = self._manager._process
            if proc is None:
                continue

            retcode = proc.poll()
            if retcode is not None:
                # プロセスが終了している
                reason = CrashReason.classify(retcode)
                self._consecutive_crashes += 1
                logger.warning(
                    f"子プロセス (PID={proc.pid}) がクラッシュしました: "
                    f"exit_code={retcode}, reason={reason}, "
                    f"consecutive={self._consecutive_crashes}"
                )

                if self._consecutive_crashes >= self._manager._config.max_restart_attempts:
                    self._escalate(reason, retcode)
                    break

                # Exponential Backoff で再起動
                backoff = (
                    self._manager._config.restart_backoff_base
                    * (3 ** (self._consecutive_crashes - 1))
                )
                logger.info(
                    f"自動再起動を {backoff:.1f}秒後 に試行します "
                    f"(試行 {self._consecutive_crashes}/{self._manager._config.max_restart_attempts})"
                )
                self._stop_event.wait(backoff)
                if self._stop_event.is_set():
                    break

                try:
                    self._manager._start_process()
                    self._manager._restart_count += 1
                    logger.info(
                        f"自動再起動に成功しました: PID={self._manager._process.pid}"
                    )
                except Exception as e:
                    logger.error(f"自動再起動に失敗しました: {e}")
                    self._escalate("RestartFailed", None)
                    break
            else:
                # プロセスが正常稼働中 → クラッシュカウンタをリセット
                self._consecutive_crashes = 0

        logger.info("Watchdog スレッドを終了しました")

    def _escalate(self, reason: str, returncode: Optional[int]) -> None:
        """3回連続クラッシュ時のエスカレーション。ログ出力 + event_log.jsonl記録。"""
        logger = self._manager._get_logger()
        msg = (
            f"🔴 エスカレーション: 子プロセスが {self._consecutive_crashes} 回連続でクラッシュしました。"
            f" 原因: {reason}, 最終exit_code: {returncode}"
        )
        logger.critical(msg)

        # event_log.jsonl に記録
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lifecycle": "DAEMON_ESCALATION",
            "health": "🔴 CRITICAL",
            "change": [
                f"daemon_crash: {self._consecutive_crashes}回連続クラッシュ, 原因={reason}",
                f"exit_code={returncode}",
            ],
        }
        try:
            os.makedirs(os.path.dirname(_EVENT_LOG_PATH), exist_ok=True)
            with open(_EVENT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error(f"event_log.jsonl への書き込みに失敗しました: {e}")


# ---------------------------------------------------------------------------
# DaemonManager 本体
# ---------------------------------------------------------------------------

class DaemonManager:
    """Windows対応デーモンプロセスマネージャ。

    - PIDファイルによるプロセス管理（staleチェック付き）
    - Watchdogスレッドによるクラッシュ検出・自動再起動
    - ResourceGovernor統合によるリソース3段階判定
    - メモリリーク検出（30分間隔、3回連続単調増加で警告）
    - ディスク容量監視（空き5GB未満で一時ファイルクリーンアップ）
    - JSON Lines形式ログ（日次ローテーション、7日保持）
    """

    def __init__(self, config: Optional[DaemonConfig] = None):
        """DaemonManagerを初期化する。

        Args:
            config: デーモン設定。省略時はデフォルト値を使用。
        """
        self._config = config or DaemonConfig()
        self._process: Optional[subprocess.Popen] = None
        self._watchdog: Optional[WatchdogThread] = None
        self._start_time: Optional[float] = None
        self._restart_count: int = 0
        self._last_health_check: Optional[str] = None
        self._initial_memory_mb: Optional[float] = None
        self._memory_history: List[float] = []
        self._lock = threading.Lock()
        self._logger: Optional[logging.Logger] = None
        self._resource_governor = None
        self._shutdown_requested = False

        # シグナルハンドラを登録
        self._setup_signal_handlers()

    # -----------------------------------------------------------------------
    # パブリック API
    # -----------------------------------------------------------------------

    def start(self) -> int:
        """デーモンプロセスを開始する。

        既に稼働中の場合は重複プロセスを安全に停止してから起動する。

        Returns:
            起動したプロセスのPID。

        Raises:
            RuntimeError: プロセスの起動に失敗した場合。
        """
        logger = self._get_logger()

        # 重複プロセス検出 & 安全な終了
        self._cleanup_stale_process()

        with self._lock:
            self._start_process()
            pid = self._process.pid
            self._start_time = time.time()
            self._restart_count = 0

            # 起動時メモリを記録（メモリリーク検出のベースライン）
            self._initial_memory_mb = self._get_process_memory_mb()
            self._memory_history = []

            # PIDファイル書き込み
            self._write_pid_file(pid)

            # Watchdog スレッド起動
            self._watchdog = WatchdogThread(
                self, check_interval=self._config.health_check_interval
            )
            self._watchdog.start()

            logger.info(
                f"デーモンプロセスを起動しました: PID={pid}, "
                f"command={self._config.command}"
            )
            return pid

    def stop(self, timeout: int = 30) -> bool:
        """デーモンプロセスを安全に停止する（Graceful Shutdown）。

        Args:
            timeout: 停止までの待機秒数。超過時は強制終了。

        Returns:
            正常に停止できた場合True。
        """
        logger = self._get_logger()
        self._shutdown_requested = True

        # Watchdog停止
        if self._watchdog is not None:
            self._watchdog.stop()
            self._watchdog = None

        with self._lock:
            if self._process is None:
                logger.info("停止対象のプロセスが存在しません")
                self._remove_pid_file()
                return True

            pid = self._process.pid
            logger.info(f"プロセスの停止を開始します: PID={pid}")

            try:
                # Graceful: SIGTERM (Windows では terminate())
                self._process.terminate()
                try:
                    self._process.wait(timeout=timeout)
                    logger.info(f"プロセスが正常に停止しました: PID={pid}")
                except subprocess.TimeoutExpired:
                    # Graceful失敗 → 強制終了
                    logger.warning(
                        f"Graceful shutdown タイムアウト ({timeout}秒)。"
                        f"強制終了します: PID={pid}"
                    )
                    self._process.kill()
                    self._process.wait(timeout=5)
            except OSError as e:
                logger.error(f"プロセス停止中にエラーが発生しました: {e}")
                return False
            finally:
                self._process = None
                self._remove_pid_file()

            return True

    def restart(self) -> int:
        """デーモンプロセスを再起動する。

        Returns:
            再起動後のプロセスPID。
        """
        logger = self._get_logger()
        logger.info("デーモンプロセスの再起動を開始します")
        self.stop()
        self._shutdown_requested = False
        return self.start()

    def status(self) -> DaemonStatus:
        """デーモンプロセスの現在ステータスを取得する。

        Returns:
            DaemonStatus データクラス。
        """
        running = self.is_running()
        pid = self._process.pid if self._process else None
        uptime = time.time() - self._start_time if self._start_time and running else 0.0
        resource_state = self._check_resource_state()
        memory_mb = self._get_process_memory_mb() or 0.0
        cpu_percent = self._get_process_cpu_percent()

        # ヘルスチェック時刻を更新
        now_iso = datetime.now(timezone.utc).isoformat()
        self._last_health_check = now_iso

        # ヘルスチェック結果をログ出力
        health_entry = {
            "status": "ok" if running else "stopped",
            "uptime_seconds": round(uptime, 1),
            "resource_state": resource_state,
        }
        self._get_logger().info(
            f"ヘルスチェック: {json.dumps(health_entry, ensure_ascii=False)}"
        )

        return DaemonStatus(
            running=running,
            pid=pid,
            uptime_seconds=round(uptime, 1),
            restart_count=self._restart_count,
            resource_state=resource_state,
            memory_mb=round(memory_mb, 1),
            cpu_percent=round(cpu_percent, 1),
            last_health_check=now_iso,
        )

    def is_running(self) -> bool:
        """デーモンプロセスが稼働中かどうかを返す。

        Returns:
            稼働中ならTrue。
        """
        if self._process is None:
            return False
        return self._process.poll() is None

    # -----------------------------------------------------------------------
    # リソース管理（ResourceGovernor統合）
    # -----------------------------------------------------------------------

    def check_resource_level(self) -> dict:
        """ResourceGovernor経由でホストリソースレベルを取得する。

        Returns:
            ResourceGovernorの check_host_resources() の結果。
            psutil未インストール時やインポートエラー時はフォールバック値を返す。
        """
        try:
            if self._resource_governor is None:
                from backend.agents.orchestration.resource_governor import ResourceGovernor
                self._resource_governor = ResourceGovernor()
            return self._resource_governor.check_host_resources()
        except Exception:
            return {
                "cpu_usage": 50.0,
                "mem_usage": 50.0,
                "level": "NORMAL",
                "throttle_required": False,
                "delay_seconds": 0.0,
            }

    def check_memory_leak(self) -> Optional[str]:
        """メモリリーク検出。30分ごとのメモリ使用量を記録し、3回連続単調増加で警告する。

        Returns:
            警告メッセージ（リーク検出時）。問題なしならNone。
        """
        current_mb = self._get_process_memory_mb()
        if current_mb is None or self._initial_memory_mb is None:
            return None

        self._memory_history.append(current_mb)

        # 絶対閾値チェック: 起動時の threshold 倍以上
        if current_mb > self._initial_memory_mb * self._config.memory_leak_threshold:
            msg = (
                f"⚠️ メモリ使用量が閾値を超えています: "
                f"現在={current_mb:.1f}MB, "
                f"起動時={self._initial_memory_mb:.1f}MB, "
                f"閾値={self._config.memory_leak_threshold * 100:.0f}%"
            )
            self._get_logger().warning(msg)
            return msg

        # 3回連続単調増加チェック
        if len(self._memory_history) >= 3:
            recent = self._memory_history[-3:]
            if recent[0] < recent[1] < recent[2]:
                msg = (
                    f"⚠️ メモリリーク疑い: 3回連続で単調増加 "
                    f"({recent[0]:.1f}MB → {recent[1]:.1f}MB → {recent[2]:.1f}MB)"
                )
                self._get_logger().warning(msg)
                return msg

        return None

    def check_disk_space(self) -> Optional[str]:
        """ディスク容量監視。空き5GB未満で一時ファイルクリーンアップを試みる。

        Returns:
            警告メッセージ（容量不足時）。問題なしならNone。
        """
        logger = self._get_logger()
        try:
            if HAS_PSUTIL:
                disk = psutil.disk_usage(str(_WORKSPACE_DIR))
                free_gb = disk.free / (1024 ** 3)
            else:
                # psutilなし: shutil.disk_usage でフォールバック
                import shutil
                total, used, free = shutil.disk_usage(str(_WORKSPACE_DIR))
                free_gb = free / (1024 ** 3)

            if free_gb < 5.0:
                msg = f"⚠️ ディスク空き容量不足: {free_gb:.1f}GB (閾値: 5.0GB)"
                logger.warning(msg)
                self._cleanup_temp_files()
                return msg
        except Exception as e:
            logger.error(f"ディスク容量チェックに失敗しました: {e}")
        return None

    # -----------------------------------------------------------------------
    # 内部メソッド: プロセス管理
    # -----------------------------------------------------------------------

    def _start_process(self) -> None:
        """子プロセスを起動する。Windowsでは CREATE_NO_WINDOW フラグを使用。

        Raises:
            RuntimeError: コマンドが未設定の場合。
        """
        cmd = self._config.command
        if cmd is None:
            # コマンド未設定時は Python の無限ループスクリプトをダミーとして使用
            cmd = [
                sys.executable, "-c",
                "import time\nwhile True:\n    time.sleep(1)"
            ]

        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }

        # Windows: CREATE_NO_WINDOW でバックグラウンド起動
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        self._process = subprocess.Popen(cmd, **kwargs)

    def _cleanup_stale_process(self) -> None:
        """PIDファイルを確認し、staleなプロセスがあれば安全に終了する。"""
        logger = self._get_logger()
        pid = self._read_pid_file()
        if pid is None:
            return

        if HAS_PSUTIL and psutil.pid_exists(pid):
            logger.warning(f"既存プロセスを検出しました (PID={pid})。停止を試みます")
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                proc.wait(timeout=10)
                logger.info(f"既存プロセスを停止しました: PID={pid}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as e:
                logger.warning(f"既存プロセス停止中にエラー: {e}")
                try:
                    proc.kill()
                except Exception:
                    pass
        else:
            logger.info(f"PIDファイルは残存していますがプロセスは存在しません (PID={pid})。クリーンアップします")

        self._remove_pid_file()

    def _write_pid_file(self, pid: int) -> None:
        """PIDファイルを書き込む。

        Args:
            pid: 書き込むプロセスID。
        """
        try:
            self._config.pid_file.parent.mkdir(parents=True, exist_ok=True)
            self._config.pid_file.write_text(str(pid), encoding="utf-8")
        except OSError as e:
            self._get_logger().error(f"PIDファイル書き込み失敗: {e}")

    def _read_pid_file(self) -> Optional[int]:
        """PIDファイルからPIDを読み込む。

        Returns:
            PID（ファイルが存在しないか不正なら None）。
        """
        try:
            if self._config.pid_file.exists():
                content = self._config.pid_file.read_text(encoding="utf-8").strip()
                return int(content)
        except (ValueError, OSError):
            pass
        return None

    def _remove_pid_file(self) -> None:
        """PIDファイルを削除する。"""
        try:
            if self._config.pid_file.exists():
                self._config.pid_file.unlink()
        except OSError as e:
            self._get_logger().error(f"PIDファイル削除失敗: {e}")

    # -----------------------------------------------------------------------
    # 内部メソッド: リソース計測
    # -----------------------------------------------------------------------

    def _get_process_memory_mb(self) -> Optional[float]:
        """管理対象プロセスのメモリ使用量をMB単位で取得する。

        Returns:
            メモリ使用量(MB)。取得不能時はNone。
        """
        if not HAS_PSUTIL or self._process is None:
            return None
        try:
            proc = psutil.Process(self._process.pid)
            mem_info = proc.memory_info()
            return mem_info.rss / (1024 * 1024)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _get_process_cpu_percent(self) -> float:
        """管理対象プロセスのCPU使用率を取得する。

        Returns:
            CPU使用率（%）。取得不能時は0.0。
        """
        if not HAS_PSUTIL or self._process is None:
            return 0.0
        try:
            proc = psutil.Process(self._process.pid)
            return proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0

    def _check_resource_state(self) -> str:
        """ResourceGovernor経由でリソース状態を判定する。

        Returns:
            "NORMAL" | "CAUTION" | "CRITICAL"
        """
        try:
            result = self.check_resource_level()
            return result.get("level", "NORMAL")
        except Exception:
            return "NORMAL"

    # -----------------------------------------------------------------------
    # 内部メソッド: ディスク管理
    # -----------------------------------------------------------------------

    def _cleanup_temp_files(self) -> None:
        """一時ファイルのクリーンアップを実行する。"""
        logger = self._get_logger()
        tmp_dir = _WORKSPACE_DIR / "backend" / "tmp"
        if not tmp_dir.exists():
            return

        cleaned_count = 0
        cleaned_bytes = 0
        try:
            for f in tmp_dir.rglob("*"):
                if f.is_file() and f.suffix in (".tmp", ".log", ".bak", ".pyc"):
                    try:
                        size = f.stat().st_size
                        f.unlink()
                        cleaned_count += 1
                        cleaned_bytes += size
                    except OSError:
                        pass
        except Exception as e:
            logger.error(f"一時ファイルクリーンアップ中にエラー: {e}")

        if cleaned_count > 0:
            logger.info(
                f"一時ファイルクリーンアップ完了: "
                f"{cleaned_count}ファイル, {cleaned_bytes / (1024*1024):.1f}MB 解放"
            )

    # -----------------------------------------------------------------------
    # 内部メソッド: シグナルハンドリング
    # -----------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        """シグナルハンドラを登録する。Windows用 SIGBREAK を含む。"""
        try:
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (OSError, ValueError):
            # メインスレッド以外からは登録できない場合がある
            pass

        # Windows固有: SIGBREAK (Ctrl+Break) ハンドリング
        if IS_WINDOWS:
            try:
                signal.signal(signal.SIGBREAK, self._signal_handler)  # type: ignore[attr-defined]
            except (AttributeError, OSError, ValueError):
                pass

    def _signal_handler(self, signum: int, frame) -> None:
        """シグナル受信時のハンドラ。Graceful Shutdownを開始する。

        Args:
            signum: シグナル番号。
            frame: 現在のスタックフレーム。
        """
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        self._get_logger().info(f"シグナル受信: {sig_name}。Graceful Shutdownを開始します")
        self._shutdown_requested = True
        # 別スレッドで stop() を呼ぶ（シグナルハンドラ内での長時間処理を避ける）
        threading.Thread(target=self.stop, daemon=True).start()

    # -----------------------------------------------------------------------
    # 内部メソッド: ログ管理
    # -----------------------------------------------------------------------

    def _get_logger(self) -> logging.Logger:
        """JSON Lines形式の日次ローテーションロガーを取得する。

        Returns:
            設定済みのLogger。
        """
        if self._logger is not None:
            return self._logger

        logger = logging.getLogger("daemon_manager")
        if logger.handlers:
            self._logger = logger
            return logger

        logger.setLevel(logging.DEBUG)

        # ログディレクトリを確保
        log_dir = self._config.log_dir
        log_dir.mkdir(parents=True, exist_ok=True)

        # TimedRotatingFileHandler: 日次、7日保持
        log_file = log_dir / "daemon_manager.log"
        try:
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=str(log_file),
                when="midnight",
                interval=1,
                backupCount=7,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(_JsonLinesFormatter())
            logger.addHandler(file_handler)
        except OSError:
            # ファイルハンドラが作れない場合はスキップ
            pass

        # コンソールハンドラ（DEBUG用）
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
        )
        logger.addHandler(console_handler)

        self._logger = logger
        return logger

    # -----------------------------------------------------------------------
    # コンテキストマネージャ
    # -----------------------------------------------------------------------

    def __enter__(self) -> "DaemonManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def __repr__(self) -> str:
        status = "running" if self.is_running() else "stopped"
        pid = self._process.pid if self._process else None
        return f"<DaemonManager status={status} pid={pid}>"


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== DaemonManager ステータス確認 ===\n")

    config = DaemonConfig()
    manager = DaemonManager(config=config)

    # 現在の環境情報を表示
    print(f"プラットフォーム: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print(f"psutil利用可能: {HAS_PSUTIL}")
    print(f"PIDファイル: {config.pid_file}")
    print(f"ログディレクトリ: {config.log_dir}")
    print()

    # リソース状態
    resource = manager.check_resource_level()
    print(f"リソースレベル: {resource.get('level', 'UNKNOWN')}")
    print(f"  CPU使用率: {resource.get('cpu_usage', 'N/A')}%")
    print(f"  メモリ使用率: {resource.get('mem_usage', 'N/A')}%")
    print()

    # ディスク容量
    disk_warning = manager.check_disk_space()
    if disk_warning:
        print(disk_warning)
    else:
        print("ディスク容量: OK (5GB以上の空きあり)")
    print()

    # ステータスオブジェクトの表示
    st = manager.status()
    print(f"DaemonStatus:")
    print(f"  running: {st.running}")
    print(f"  pid: {st.pid}")
    print(f"  uptime_seconds: {st.uptime_seconds}")
    print(f"  restart_count: {st.restart_count}")
    print(f"  resource_state: {st.resource_state}")
    print(f"  memory_mb: {st.memory_mb}")
    print(f"  cpu_percent: {st.cpu_percent}")
    print(f"  last_health_check: {st.last_health_check}")
