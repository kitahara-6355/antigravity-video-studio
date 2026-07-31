# satisfies: REQ-WAVE-02
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path
import time
import os
import random
from pathlib import Path
from typing import Dict, Any

class ResourceGovernor:
    """Resource Governor to track API usage and enforce rate limiting (RPM/TPM).
    
    Prevents API 429 errors by throttling requests when approaching quota limits.
    Now persists status into resource_state.json to enable cross-process coordination.
    """
    def __init__(self, max_rpm: int = 15, max_tpm: int = 1000000, threshold_pct: float = 0.8, state_path: str = None):
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.threshold_pct = threshold_pct
        self.state_path = Path(state_path) if state_path else _writable_path("backend/agents/orchestration/resource_state.json")
        self._cached_state = {"request_times": [], "token_usage": []}
        self._last_cpu_time = 0.0
        self._last_cpu_val = 50.0
        self._last_mem_val = 50.0

    def _get_logger(self):
        import logging
        return logging.getLogger(__name__)

    def _load_state_fast(self) -> dict:
        """状態ファイルからロックなしで高速にデータを読み込む (ダーティリードによる高速判定用)"""
        import json
        if not self.state_path.exists():
            return {"request_times": [], "token_usage": []}
        
        # 共有競合エラーに備えて最大3回リトライ
        for i in range(3):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cached_state = data
                        return data
            except (PermissionError, FileNotFoundError, json.JSONDecodeError):
                if i < 2:
                    time.sleep(0.01 * (i + 1))
                continue
            except Exception:
                break
                
        # フォールバックとしてバックアップファイルの読み込みを試す
        bak_path = str(self.state_path) + ".bak"
        if os.path.exists(bak_path):
            for i in range(2):
                try:
                    with open(bak_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, dict):
                            self._cached_state = data
                            return data
                except Exception:
                    if i < 1:
                        time.sleep(0.01)
                    continue

        return getattr(self, "_cached_state", {"request_times": [], "token_usage": []})

    def _load_state(self, timeout: float = 30.0) -> dict:
        """状態ファイルから共有データを読み込む (ロック付き)"""
        from .atomic_io import FileLock, safe_read_json
        lock_path = str(self.state_path) + ".lock"
        try:
            with FileLock(lock_path, timeout=timeout):
                return safe_read_json(str(self.state_path), {"request_times": [], "token_usage": []})
        except TimeoutError:
            # タイムアウト時はハング回避のためダーティリード結果を返す
            self._get_logger().warning(f"[ResourceGovernor] Read lock timeout, fallback to dirty read")
            return self._load_state_fast()

    def _save_state(self, state: dict, timeout: float = 30.0) -> None:
        """状態ファイルに共有データを書き出す (ロック付き)"""
        from .atomic_io import FileLock, atomic_write_json
        lock_path = str(self.state_path) + ".lock"
        try:
            with FileLock(lock_path, timeout=timeout):
                atomic_write_json(str(self.state_path), state)
        except TimeoutError:
            self._get_logger().error(f"[ResourceGovernor] Write lock timeout, state may not be updated")

    def _cleanup_window(self, state: dict, now: float) -> None:
        """Removes logs older than 60 seconds."""
        cutoff = now - 60.0
        state["request_times"] = [t for t in state.get("request_times", []) if t > cutoff]
        state["token_usage"] = [u for u in state.get("token_usage", []) if u[0] > cutoff]

    def get_current_rpm(self) -> int:
        state = self._load_state()
        self._cleanup_window(state, time.time())
        self._save_state(state)
        return len(state["request_times"])

    def get_current_tpm(self) -> int:
        state = self._load_state()
        self._cleanup_window(state, time.time())
        self._save_state(state)
        return sum(u[1] for u in state["token_usage"])

    def record_request(self, tokens_used: int) -> None:
        """Records a request and its token consumption."""
        from .atomic_io import FileLock, safe_read_json, atomic_write_json
        lock_path = str(self.state_path) + ".lock"
        try:
            with FileLock(lock_path, timeout=30.0):
                state = safe_read_json(str(self.state_path), {"request_times": [], "token_usage": []})
                now = time.time()
                self._cleanup_window(state, now)
                
                state.setdefault("request_times", []).append(now)
                state.setdefault("token_usage", []).append((now, tokens_used))
                atomic_write_json(str(self.state_path), state)
        except TimeoutError:
            self._get_logger().error(f"[ResourceGovernor] Timeout recording request, API usage record skipped")

    def should_throttle(self, expected_tokens: int = 0) -> Dict[str, Any]:
        """Determines if the request should be throttled based on limits.
        
        Returns:
            A dict with 'throttle' (bool) and 'delay_seconds' (float).
        """
        # 1. ダブルチェック・ロッキング: ロック無しで高速に判定 (ダーティリードによる簡易判定)
        state = self._load_state_fast()
        now = time.time()
        
        # 簡易クリーンアップ
        cutoff = now - 60.0
        request_times = [t for t in state.get("request_times", []) if t > cutoff]
        token_usage = [u for u in state.get("token_usage", []) if u[0] > cutoff]
        
        current_rpm = len(request_times)
        current_tpm = sum(u[1] for u in token_usage)
        
        rpm_threshold = self.max_rpm * self.threshold_pct
        tpm_threshold = self.max_tpm * self.threshold_pct
        
        # 制限の 80% 未満（十分安全）であれば、ディスクI/Oロックを回避して即座に進行許可
        if current_rpm < rpm_threshold * 0.8 and (current_tpm + expected_tokens) < tpm_threshold * 0.8:
            return {"throttle": False, "delay_seconds": 0.0, "reason": "FastPass"}
            
        # 2. 制限に接近している場合のみ、ロックを取得して厳密に判定・クリーンアップ
        from .atomic_io import FileLock, safe_read_json, atomic_write_json
        lock_path = str(self.state_path) + ".lock"
        
        try:
            with FileLock(lock_path, timeout=30.0):
                state = safe_read_json(str(self.state_path), {"request_times": [], "token_usage": []})
                self._cleanup_window(state, now)
                
                request_times = state.get("request_times", [])
                token_usage = state.get("token_usage", [])
                
                current_rpm = len(request_times)
                current_tpm = sum(u[1] for u in token_usage)
                
                # Check RPM
                if current_rpm >= rpm_threshold:
                    oldest = request_times[0] if request_times else now
                    delay = max(0.1, 60.0 - (now - oldest))
                    return {
                        "throttle": True,
                        "delay_seconds": delay,
                        "reason": f"RPM threshold exceeded: {current_rpm}/{self.max_rpm}"
                    }
                    
                # Check TPM
                if current_tpm + expected_tokens >= tpm_threshold:
                    oldest_token = token_usage[0][0] if token_usage else now
                    delay = max(0.1, 60.0 - (now - oldest_token))
                    return {
                        "throttle": True,
                        "delay_seconds": delay,
                        "reason": f"TPM threshold exceeded: {current_tpm + expected_tokens}/{self.max_tpm}"
                    }
                    
                atomic_write_json(str(self.state_path), state)
                return {"throttle": False, "delay_seconds": 0.0, "reason": "StrictNormal"}
        except TimeoutError:
            self._get_logger().warning(f"[ResourceGovernor] Lock timeout on should_throttle, fallback to fast pass")
            return {"throttle": False, "delay_seconds": 0.0, "reason": "TimeoutFallback"}

    def _load_thresholds(self) -> dict:
        default_thresholds = {
            "caution_cpu": 50.0,
            "caution_mem": 63.0,
            "critical_cpu": 70.0,
            "critical_mem": 75.0,
        }
        sched_path = Path(__file__).parent / "user_schedule.json"
        if sched_path.exists():
            try:
                import json
                with open(sched_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    rg_config = data.get("resource_governor", {})
                    return {
                        "caution_cpu": rg_config.get("caution_cpu", default_thresholds["caution_cpu"]),
                        "caution_mem": rg_config.get("caution_mem", default_thresholds["caution_mem"]),
                        "critical_cpu": rg_config.get("critical_cpu", default_thresholds["critical_cpu"]),
                        "critical_mem": rg_config.get("critical_mem", default_thresholds["critical_mem"]),
                    }
            except Exception:
                pass
        return default_thresholds

    def check_host_resources(self) -> dict:
        """ホストPC of CPU・メモリリソース状況を確認する (1秒キャッシュで同期ブロッキングを回避)"""
        now = time.time()
        thresholds = self._load_thresholds()
        caution_cpu = thresholds["caution_cpu"]
        caution_mem = thresholds["caution_mem"]
        critical_cpu = thresholds["critical_cpu"]
        critical_mem = thresholds["critical_mem"]

        if now - self._last_cpu_time < 1.0:
            cpu_usage = self._last_cpu_val
            mem_usage = self._last_mem_val
        else:
            try:
                import psutil
                # interval=None による非ブロッキング CPU 測定
                cpu_usage = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                mem_usage = mem.percent
                
                self._last_cpu_val = cpu_usage
                self._last_mem_val = mem_usage
                self._last_cpu_time = now
            except ImportError:
                # フォールバック: psutilがない場合は負荷平均またはダミー
                import os
                try:
                    load = os.getloadavg()
                    cpu_usage = load[0] * 10.0  # 簡易換算
                except AttributeError:
                    cpu_usage = 50.0  # ダミー
                mem_usage = 50.0
                self._last_cpu_val = cpu_usage
                self._last_mem_val = mem_usage
                self._last_cpu_time = now
            except Exception:
                # 例外時もキャッシュを使用
                cpu_usage = self._last_cpu_val
                mem_usage = self._last_mem_val

        # リソースレベルの判別
        if cpu_usage >= critical_cpu or mem_usage >= critical_mem:
            level = "CRITICAL"
            throttle_required = True
            delay_seconds = 10.0
        elif cpu_usage >= caution_cpu or mem_usage >= caution_mem:
            level = "CAUTION"
            throttle_required = False
            delay_seconds = 3.0
        else:
            level = "NORMAL"
            throttle_required = False
            delay_seconds = 0.0

        # ピーク値とスロットリング回数を resource_state.json に記録する (ロックあり)
        try:
            state = self._load_state()
            dirty = False
            
            # ピーク値の更新
            if "peak_cpu" not in state or cpu_usage > state.get("peak_cpu", 0.0):
                state["peak_cpu"] = cpu_usage
                dirty = True
            if "peak_mem" not in state or mem_usage > state.get("peak_mem", 0.0):
                state["peak_mem"] = mem_usage
                dirty = True
                
            # スロットリング発生回数のカウント
            if level in ("CAUTION", "CRITICAL"):
                state["throttling_count"] = state.get("throttling_count", 0) + 1
                dirty = True
                
            if dirty:
                self._save_state(state)
        except Exception as e:
            self._get_logger().error(f"[ResourceGovernor] Failed to update resource state metrics: {e}")

        return {
            "cpu_usage": cpu_usage,
            "mem_usage": mem_usage,
            "level": level,
            "throttle_required": throttle_required,
            "delay_seconds": delay_seconds
        }

    def throttle_if_needed(self, expected_tokens: int = 0) -> float:
        """Throttles execution (sleeps) if limits are approached or host resources are high.
        
        Returns:
            The duration of sleep in seconds (0.0 if no throttling occurred).
        """
        # 1. APIトークン・レート制限に基づくスロットリング
        decision = self.should_throttle(expected_tokens)
        api_delay = decision["delay_seconds"] if decision["throttle"] else 0.0
        
        # 2. ホストPCのリソース（CPU/メモリ）に基づくスロットリング
        res = self.check_host_resources()
        resource_delay = res["delay_seconds"]
            
        max_delay = max(api_delay, resource_delay)
        if max_delay > 0.0:
            # ジッター（0.5秒〜2.0秒のランダムな揺らぎ）を追加して群れ行動（Thundering Herd）を回避
            jitter = random.uniform(0.5, 2.0)
            sleep_time = min(10.0, max_delay) + jitter
            time.sleep(sleep_time)
            return sleep_time
            
        return 0.0

    def kill_zombie_test_processes(self, timeout_seconds: float = 180.0) -> int:
        """ハングしたテストプロセス（pytest等）をスキャンし強制終了する。
        
        Returns:
            int: 強制終了したプロセス数
        """
        import psutil
        import time
        
        killed_count = 0
        now = time.time()
        logger = self._get_logger()
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmd = proc.info.get('cmdline') or []
                cmd_str = " ".join(cmd).lower()
                is_pytest = (
                    proc.info['name'] == 'pytest' 
                    or 'pytest' in cmd_str 
                    or ('python' in proc.info['name'] and 'pytest' in cmd_str)
                )
                if is_pytest:
                    elapsed = now - proc.info['create_time']
                    if elapsed > timeout_seconds:
                        pid = proc.info['pid']
                        logger.warning(f"[Watchdog] Detected zombie pytest process PID={pid} running for {elapsed:.1f}s. Terminating...")
                        # 子プロセスも含めて強制終了
                        try:
                            parent = psutil.Process(pid)
                            for child in parent.children(recursive=True):
                                child.kill()
                            parent.kill()
                        except Exception as e:
                            logger.error(f"[Watchdog] Failed to kill process PID={pid}: {e}")
                        killed_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError):
                pass
        
        if killed_count > 0:
            logger.info(f"[Watchdog] Cleaned up {killed_count} zombie pytest processes.")
        return killed_count
