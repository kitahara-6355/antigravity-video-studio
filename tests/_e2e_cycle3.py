"""サイクル3 E2Eテスト: 自己改善ループ — 速度+品質の同時検証"""
import urllib.request, urllib.error, json, time, sys, http.client, socket, os
from contextlib import closing
from typing import TypedDict, List, Optional
from dataclasses import dataclass

API = "http://localhost:8000"
BASELINE_SCORE = 93  # サイクル2のベースライン
# プロジェクトルートディレクトリの設定
# 環境変数 PROJECT_ROOT が指定されていればそれを使用し、
# 存在しない、または指定されていない場合はデフォルトとしてホスト側のパス（存在すれば）、
# あるいは worktree の親ディレクトリを使用する。
_host_root = r"C:\Users\PC_User\Desktop\script\video-automation"
if os.environ.get("PROJECT_ROOT"):
    PROJECT_ROOT = os.environ["PROJECT_ROOT"]
elif os.path.exists(_host_root):
    PROJECT_ROOT = _host_root
else:
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

DEFAULT_VIDEO_PATHS = [
    os.path.join(PROJECT_ROOT, "vault-assets", "raw_videos", "本番RAW01 対談_山田", "シーン01_前編.mp4"),
    os.path.join(PROJECT_ROOT, "vault-assets", "raw_videos", "本番RAW01 対談_山田", "シーン02_ゲスト書道.mp4"),
    os.path.join(PROJECT_ROOT, "vault-assets", "raw_videos", "本番RAW01 対談_山田", "シーン03_後編01.mp4"),
    os.path.join(PROJECT_ROOT, "vault-assets", "raw_videos", "本番RAW01 対談_山田", "シーン04_後編02.mp4"),
]

def wait_for_server(timeout=60):
    config = E2EConfig(api_url=API, wait_timeout=timeout)
    client = E2EPipelineClient(config)
    return client.wait_for_server(timeout)

def start_pipeline():
    config = E2EConfig(api_url=API)
    client = E2EPipelineClient(config)
    return client.start_pipeline(DEFAULT_VIDEO_PATHS, 20)

def monitor_pipeline(timeout=1800):
    config = E2EConfig(api_url=API, monitor_timeout=timeout)
    client = E2EPipelineClient(config)
    return client.monitor_pipeline(timeout)

# ===== メイン =====
def main():
    print("=" * 60, flush=True)
    print("サイクル3 自己改善ループ E2E テスト", flush=True)
    print(f"ベースライン: {BASELINE_SCORE}点, 20分16秒", flush=True)
    print(f"最適化: バッチ200 + 最終レンダbalanced", flush=True)
    print("=" * 60, flush=True)

    print("\n[1] サーバー起動待機...", flush=True)
    if not wait_for_server():
        print("FAIL: サーバータイムアウト")
        sys.exit(1)
    print("  OK", flush=True)

    print("\n[2] パイプライン起動...", flush=True)
    t0 = time.monotonic()
    try:
        result = start_pipeline()
        if not isinstance(result, dict):
            raise ValueError("Pipeline start response is not a dictionary")
    except urllib.error.HTTPError as e:
        try:
            print(f"FAIL: パイプラインの起動に失敗しました (HTTPError {e.code}: {e.reason})", flush=True)
        finally:
            e.close()
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"FAIL: パイプラインの起動に失敗しました (通信エラー: {e.reason})", flush=True)
        sys.exit(1)
    except (TimeoutError, socket.timeout) as e:
        print(f"FAIL: パイプラインの起動に失敗しました (接続タイムアウト: {e})", flush=True)
        sys.exit(1)
    except http.client.HTTPException as e:
        print(f"FAIL: パイプラインの起動に失敗しました (HTTP例外: {e})", flush=True)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"FAIL: レスポンスのJSONパースに失敗しました: {e}", flush=True)
        sys.exit(1)
    except ValueError as e:
        print(f"FAIL: レスポンスデータの検証に失敗しました: {e}", flush=True)
        sys.exit(1)
    except OSError as e:
        print(f"FAIL: OSエラーが発生しました: {e}", flush=True)
        sys.exit(1)

    print(f"  Started: session={result.get('session_id','?')[:8]}", flush=True)

    print("\n[3] パイプライン監視...", flush=True)
    try:
        final = monitor_pipeline()
    except urllib.error.URLError as e:
        print(f"FAIL: パイプライン監視中に通信エラーが発生しました: {e.reason}", flush=True)
        sys.exit(1)
    except (TimeoutError, socket.timeout) as e:
        print(f"FAIL: パイプライン監視中に接続タイムアウトが発生しました: {e}", flush=True)
        sys.exit(1)
    except http.client.HTTPException as e:
        print(f"FAIL: パイプライン監視中にHTTP例外が発生しました: {e}", flush=True)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"FAIL: パイプライン監視レスポンスのJSONパースに失敗しました: {e}", flush=True)
        sys.exit(1)
    except ValueError as e:
        print(f"FAIL: パイプライン監視レスポンス検証に失敗しました: {e}", flush=True)
        sys.exit(1)
    except OSError as e:
        print(f"FAIL: パイプライン監視中にOSエラーが発生しました: {e}", flush=True)
        sys.exit(1)

    if final and isinstance(final, dict) and final.get("status") == "completed":
        total_time = time.monotonic() - t0
        stages = final.get("stages", [])
        
        print(f"\n{'=' * 60}", flush=True)
        print(f"[4] 結果判定", flush=True)
        print(f"{'=' * 60}", flush=True)
        
        # 各ステージの詳細
        score = 0
        for s in stages:
            if not s or not isinstance(s, dict):
                continue
            detail = s.get("detail") or ""
            if not isinstance(detail, str):
                detail = str(detail)
            print(f"  {s.get('icon', '?')} {s.get('name', '?')}: {detail}", flush=True)
            if "スコア" in detail:
                try:
                    score = int(detail.split("スコア:")[1].split("点")[0].strip())
                except (ValueError, IndexError, TypeError) as e:
                    print(f"Warning: スコアのパースに失敗しました ({e}): detail='{detail}'", flush=True)
        
        print(f"\n  ⏱ 処理時間: {total_time:.0f}秒 ({total_time/60:.1f}分)", flush=True)
        print(f"  🎯 品質スコア: {score}点", flush=True)
        print(f"  📊 ベースライン: {BASELINE_SCORE}点", flush=True)
        
        # 品質ゲート判定
        time_pass = total_time <= 600  # 10分以内
        quality_pass = score >= BASELINE_SCORE
        
        print(f"\n  時間(≤10分): {'✅ PASS' if time_pass else '❌ FAIL'} ({total_time:.0f}s)", flush=True)
        print(f"  品質(≥{BASELINE_SCORE}): {'✅ PASS' if quality_pass else '❌ FAIL'} ({score}点)", flush=True)
        
        if time_pass and quality_pass:
            print(f"\n  🏆 自己改善ループ: 目標達成！", flush=True)
        elif quality_pass and not time_pass:
            print(f"\n  🟡 品質OK, 速度未達 → 次の最適化が必要", flush=True)
            sys.exit(1)
        elif not quality_pass:
            print(f"\n  🔴 品質低下 → ロールバックが必要", flush=True)
            sys.exit(1)
    else:
        print(f"\n  ❌ パイプライン失敗またはタイムアウト", flush=True)
        if final and isinstance(final, dict):
            print(f"  Status: {final.get('status')}", flush=True)
            print(f"  Error: {final.get('error')}", flush=True)
        sys.exit(1)

# ===== 大規模変更対策の設計定義 (スタブ) =====

class StageInfo(TypedDict):
    name: str
    status: str
    icon: str
    detail: str

class PipelineStatusResponse(TypedDict, total=False):
    status: str
    error: Optional[str]
    stages: List[StageInfo]

class PipelineStartResponse(TypedDict):
    session_id: str

@dataclass
class E2EConfig:
    api_url: str = "http://localhost:8000"
    baseline_score: int = 93
    wait_timeout: int = 60
    monitor_timeout: int = 1800

class E2EPipelineClient:
    """E2Eテスト用パイプラインクライアント (設計スタブ)
    
    将来的な認証の追加、プロトコルの変更、状態の保持などの大規模変更に備えて、
    共通のインターフェースを提供します。
    """
    def __init__(self, config: E2EConfig) -> None:
        self.config = config

    def wait_for_server(self, timeout: Optional[int] = None) -> bool:
        """サーバーの起動を待機します。"""
        t = timeout if timeout is not None else self.config.wait_timeout
        if t is None:
            t = 60
        if t < 0:
            raise ValueError("Timeout must be non-negative")
        start = time.monotonic()
        while time.monotonic() - start < t:
            try:
                with closing(urllib.request.urlopen(f"{self.config.api_url}/api/pipeline/status", timeout=3)) as resp:
                    return True
            except urllib.error.HTTPError as e:
                body_snippet = ""
                try:
                    with closing(e):
                        body_snippet = e.read().decode("utf-8")[:100]
                except (OSError, UnicodeDecodeError, ValueError, AttributeError, TypeError) as read_err:
                    body_snippet = f"(failed to read body: {read_err})"
                print(f"Server returned HTTPError: {e.code} {e.reason} | Body: {body_snippet}, retrying...", flush=True)
                time.sleep(2)
            except ValueError as e:
                print(f"Invalid URL or configuration error: {e}", flush=True)
                return False
            except (TimeoutError, socket.timeout) as e:
                print(f"Server connection timed out: {e}, retrying...", flush=True)
                time.sleep(2)
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                if "timed out" in str(e) or (isinstance(e, urllib.error.URLError) and isinstance(e.reason, socket.timeout)):
                    print(f"Server connection timed out: {e}, retrying...", flush=True)
                else:
                    print(f"Server connection failed: {e}, retrying...", flush=True)
                time.sleep(2)
        return False

    def start_pipeline(self, video_paths: List[str], target_minutes: int) -> PipelineStartResponse:
        """パイプライン処理を開始します。"""
        body = json.dumps({"video_paths": video_paths, "target_minutes": target_minutes}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config.api_url}/api/pipeline/start",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        try:
            with closing(urllib.request.urlopen(req, timeout=15)) as resp:
                res_data = resp.read()
                if isinstance(res_data, bytes):
                    res_data = res_data.decode("utf-8")
                data = json.loads(res_data)
                if not isinstance(data, dict):
                    raise ValueError("Response data is not a dictionary")
                return data
        except urllib.error.HTTPError as e:
            body_snippet = ""
            try:
                # Do not close the exception object when raising it
                body_snippet = e.read().decode("utf-8")[:200]
            except (OSError, UnicodeDecodeError, ValueError, AttributeError, TypeError) as read_err:
                body_snippet = f"(failed to read body: {read_err})"
            print(f"Server returned HTTPError {e.code}: {e.reason} | Body: {body_snippet}", flush=True)
            raise
        except urllib.error.URLError as e:
            print(f"Connection URLError during start_pipeline: {e.reason}", flush=True)
            raise
        except (TimeoutError, socket.timeout) as e:
            print(f"Connection timeout during start_pipeline: {e}", flush=True)
            raise
        except http.client.HTTPException as e:
            print(f"HTTPException during start_pipeline: {e}", flush=True)
            raise
        except json.JSONDecodeError as e:
            print(f"JSONDecodeError during start_pipeline: {e}", flush=True)
            raise
        except ValueError as e:
            print(f"ValueError during start_pipeline: {e}", flush=True)
            raise
        except OSError as e:
            print(f"OSError during start_pipeline: {e}", flush=True)
            raise

    def monitor_pipeline(self, timeout: Optional[int] = None) -> Optional[PipelineStatusResponse]:
        """パイプラインの進捗を監視し、最終結果を返します。"""
        t = timeout if timeout is not None else self.config.monitor_timeout
        if t is None:
            t = 1800
        if t < 0:
            raise ValueError("Timeout must be non-negative")
        start = time.monotonic()
        last_stage = ""
        consecutive_errors = 0
        max_errors = 5
        while time.monotonic() - start < t:
            time.sleep(10)
            elapsed = int(time.monotonic() - start)
            try:
                with closing(urllib.request.urlopen(f"{self.config.api_url}/api/pipeline/status", timeout=10)) as resp:
                    res_data = resp.read()
                    if isinstance(res_data, bytes):
                        res_data = res_data.decode("utf-8")
                    data = json.loads(res_data)
                    if not isinstance(data, dict):
                        raise ValueError("Response data is not a dictionary")
                    status = data.get("status")
                    stages = data.get("stages")
                    if not isinstance(stages, list):
                        stages = []
                    completed = len([s for s in stages if s and isinstance(s, dict) and s.get("status", "") == "completed"])
                    running = [s for s in stages if s and isinstance(s, dict) and s.get("status", "") == "running"]
                    r = running[0] if running else None
                    current = r.get("name", "") if r else ""
                    
                    # ステージ変更時のみ出力
                    if current != last_stage or status in ("completed", "error"):
                        raw_detail = r.get("detail") if r else ""
                        detail = str(raw_detail) if raw_detail is not None else ""
                        detail = detail[:60]
                        if status == "error" and data.get("error"):
                            err_msg = data.get("error")
                            print(f"[{elapsed:>4}s] {status} | {completed}/7 | {current}: {detail} (Error: {err_msg})", flush=True)
                        else:
                            print(f"[{elapsed:>4}s] {status} | {completed}/7 | {current}: {detail}", flush=True)
                        last_stage = current
                    
                    consecutive_errors = 0
                    
                    if status in ("completed", "error"):
                        return data
            except urllib.error.HTTPError as e:
                consecutive_errors += 1
                body_snippet = ""
                try:
                    with closing(e):
                        body_snippet = e.read().decode("utf-8")[:100]
                except (OSError, UnicodeDecodeError, ValueError, AttributeError, TypeError) as read_err:
                    body_snippet = f"(failed to read body: {read_err})"
                print(f"[{elapsed:>4}s] HTTPError {e.code}: {e.reason} | Body: {body_snippet}", flush=True)
                if consecutive_errors >= max_errors:
                    print(f"[{elapsed:>4}s] 連続エラー数が上限({max_errors})に達したため監視を終了します", flush=True)
                    return None
            except json.JSONDecodeError as e:
                consecutive_errors += 1
                print(f"[{elapsed:>4}s] JSONパース失敗 (APIエラーの可能性があります): {e}", flush=True)
                if consecutive_errors >= max_errors:
                    print(f"[{elapsed:>4}s] 連続エラー数が上限({max_errors})に達したため監視を終了します", flush=True)
                    return None
            except ValueError as e:
                consecutive_errors += 1
                print(f"[{elapsed:>4}s] レスポンスデータ検証失敗 (API仕様変更の可能性があります): {e}", flush=True)
                if consecutive_errors >= max_errors:
                    print(f"[{elapsed:>4}s] 連続エラー数が上限({max_errors})に達したため監視を終了します", flush=True)
                    return None
            except (TimeoutError, socket.timeout) as e:
                consecutive_errors += 1
                print(f"[{elapsed:>4}s] Connection timed out: {e}", flush=True)
                if consecutive_errors >= max_errors:
                    print(f"[{elapsed:>4}s] 連続エラー数が上限({max_errors})に達したため監視を終了します", flush=True)
                    return None
            except (urllib.error.URLError, OSError, http.client.HTTPException) as e:
                consecutive_errors += 1
                if "timed out" in str(e) or (isinstance(e, urllib.error.URLError) and isinstance(e.reason, socket.timeout)):
                    print(f"[{elapsed:>4}s] Connection timed out: {e}", flush=True)
                else:
                    print(f"[{elapsed:>4}s] {e}", flush=True)
                if consecutive_errors >= max_errors:
                    print(f"[{elapsed:>4}s] 連続エラー数が上限({max_errors})に達したため監視を終了します", flush=True)
                    return None
        return None

# ===== Pytest向けテスト関数 =====
def test_wait_for_server_mock_in_module():
    """_e2e_cycle3.pyモジュール自体のwait_for_server動作を検証するテストケース"""
    from unittest.mock import patch, MagicMock
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = MagicMock()
        result = wait_for_server(timeout=1)
        assert result is True

if __name__ == '__main__':  # pragma: no cover
    main()
