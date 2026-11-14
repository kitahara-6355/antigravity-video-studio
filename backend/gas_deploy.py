"""Apps Script をクラウドから送り込む（PC の clasp の代わり・2026-11-13）。

dev-records 0012「クラウド優先」: Apps Script の送り込みと公開はクラウドの Claude が
Apps Script API で行い、PC の clasp は予備にする。中身は clasp と同じ3つ。

    clasp push               → push    （コードを丸ごと書き換える）
    clasp version            → push が毎回1つ版を作る（変更の記録。説明に git の版を入れる）
    clasp update-deployment  → deploy  （同じ URL のまま、公開を今の版に上げる）

使い方:

    python -m backend.gas_deploy check                 # 鍵の権限だけ見る（外に出ない）
    python -m backend.gas_deploy list                  # 台帳 backend/config/gas_projects.json
    python -m backend.gas_deploy push <名前> [--dry-run]
    python -m backend.gas_deploy deploy <名前> [--dry-run]

鍵は環境変数 `AVS_SCRIPT_TOKEN_JSON`（クラウド）か backend/data/google/token_apps_script.json。
作り方は `python scripts/google_oauth_login.py --script`。鍵はファイルに書き出さない。

歯止め（権限は広く、記録は必ず残す）:

- 手元の appsscript.json が**新しい権限**を求めていたら止める。権限が増えると自動実行が
  「承認が必要」で止まり、人の許可が要るため（0007）。`--allow-new-scopes` で通す
- 送り込むと向こうにしか無いファイルは消える。消えるファイルがあれば止める。
  `--allow-remove` で通す
- 送り込む前の中身は `backend/data/gas_backups/` に控え、送り込んだ後は版を1つ作る。
  Apps Script の「プロジェクト履歴」から戻せる
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from backend.services.google_oauth import (
        SCRIPT_SCOPES,
        SCRIPT_TOKEN_JSON_ENV,
        GoogleAuthError,
        load_credentials,
        read_token_info,
        script_token_path,
        token_scopes,
    )
except ImportError:  # backend/ を直接 sys.path に載せている経路向け
    from services.google_oauth import (  # type: ignore[no-redef]
        SCRIPT_SCOPES,
        SCRIPT_TOKEN_JSON_ENV,
        GoogleAuthError,
        load_credentials,
        read_token_info,
        script_token_path,
        token_scopes,
    )

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "backend" / "config" / "gas_projects.json"
BACKUP_DIR = ROOT / "backend" / "data" / "gas_backups"
API = "https://script.googleapis.com/v1"
LOGIN_HINT = "python scripts/google_oauth_login.py --script（info@kitahara-birei.com で許可）"

_EXT_TYPE = {".js": "SERVER_JS", ".gs": "SERVER_JS", ".html": "HTML"}
_TYPE_EXT = {"SERVER_JS": ".js", "HTML": ".html", "JSON": ".json"}


class GuardError(RuntimeError):
    """歯止めに当たった。Apps Script は何も変えていない。"""


# --- 手元のファイル → Apps Script の形 ---------------------------------------


_MATCH_ALL = {"**", "**/**", "**/*", "*"}


def _match(rel: str, pat: str) -> bool:
    if pat in _MATCH_ALL:
        return True
    cands = {pat, pat[3:] if pat.startswith("**/") else pat}
    return any(fnmatch.fnmatch(rel, c) or ("/" not in c and fnmatch.fnmatch(Path(rel).name, c))
               for c in cands)


def _ignored(rel: str, patterns: Sequence[str]) -> bool:
    """`.claspignore` と同じく上から順に当て、`!` で始まる行は戻す（後の行が勝つ）。"""
    ignored = False
    for pat in patterns:
        neg = pat.startswith("!")
        if _match(rel, pat[1:] if neg else pat):
            ignored = not neg
    return ignored


def read_claspignore(src: Path) -> list[str]:
    f = src / ".claspignore"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


def collect_files(src: Path, include: Sequence[str] | None = None) -> list[dict[str, str]]:
    """clasp push と同じ規則で、手元のフォルダを Apps Script のファイルの並びにする。

    - `.js` `.gs` → SERVER_JS、`.html` → HTML、`appsscript.json` → JSON
    - 名前は拡張子を除いた相対パス（`sub/a.js` → `sub/a`）
    - `.claspignore`・隠しファイル・node_modules は送らない
    - `include` を渡したら、その名前のファイルだけを送る（台帳の include）
    """
    if not (src / "appsscript.json").exists():
        raise GuardError(f"{src} に appsscript.json がありません。送り込むフォルダが違います")
    patterns = read_claspignore(src)
    out: list[dict[str, str]] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src).as_posix()
        if any(part.startswith(".") or part == "node_modules" for part in Path(rel).parts):
            continue
        if include is not None:
            if rel not in include:
                continue
        elif _ignored(rel, patterns):
            continue
        if rel == "appsscript.json":
            out.append({"name": "appsscript", "type": "JSON",
                        "source": path.read_text(encoding="utf-8")})
            continue
        kind = _EXT_TYPE.get(path.suffix)
        if kind is None:
            continue
        out.append({"name": rel[: -len(path.suffix)], "type": kind,
                    "source": path.read_text(encoding="utf-8")})
    return out


def _manifest_scopes(files: Sequence[Mapping[str, Any]]) -> set[str]:
    for f in files:
        if f.get("type") == "JSON" and f.get("name") == "appsscript":
            try:
                return set(json.loads(f.get("source") or "{}").get("oauthScopes") or [])
            except json.JSONDecodeError as e:
                raise GuardError(f"appsscript.json が JSON として読めません（{e.lineno} 行）") from None
    return set()


@dataclass
class Plan:
    """送り込みの前に出す、変わることの一覧。"""

    added: list[str]
    changed: list[str]
    removed: list[str]
    unchanged: list[str]
    new_scopes: list[str]

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.removed)

    def lines(self) -> list[str]:
        out = []
        for label, names in (("足す", self.added), ("変える", self.changed), ("消える", self.removed)):
            if names:
                out.append(f"  {label}: {', '.join(names)}")
        if self.new_scopes:
            out.append(f"  新しい権限: {', '.join(self.new_scopes)}")
        if not out:
            out.append("  変更なし")
        return out


def _key(f: Mapping[str, Any]) -> str:
    return f"{f.get('name')}{_TYPE_EXT.get(str(f.get('type')), '')}"


def plan_push(local: Sequence[Mapping[str, Any]], remote: Sequence[Mapping[str, Any]]) -> Plan:
    lmap = {_key(f): f for f in local}
    rmap = {_key(f): f for f in remote}
    added = sorted(set(lmap) - set(rmap))
    removed = sorted(set(rmap) - set(lmap))
    common = sorted(set(lmap) & set(rmap))
    changed = [k for k in common if (lmap[k].get("source") or "") != (rmap[k].get("source") or "")]
    unchanged = [k for k in common if k not in changed]
    new_scopes = sorted(_manifest_scopes(local) - _manifest_scopes(remote))
    return Plan(added, changed, removed, unchanged, new_scopes)


def check_guards(plan: Plan, *, allow_new_scopes: bool, allow_remove: bool) -> None:
    if plan.new_scopes and not allow_new_scopes:
        raise GuardError(
            "新しい権限を求めています: " + ", ".join(plan.new_scopes) + "\n"
            "送り込むと自動実行が止まり、北原さんの許可が要ります。先に北原さんに伝え、"
            "--allow-new-scopes を付けて送ってください。何も変えていません")
    if plan.removed and not allow_remove:
        raise GuardError(
            "向こうにしか無いファイルが消えます: " + ", ".join(plan.removed) + "\n"
            "消してよければ --allow-remove を付けてください。何も変えていません")


# --- 台帳 ---------------------------------------------------------------------


def load_registry(path: Path = REGISTRY) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {p["name"]: p for p in data["projects"]}


def resolve_source(entry: Mapping[str, Any], root: Path = ROOT) -> Path:
    src = Path(str(entry["source"]))
    return src if src.is_absolute() else root / src


def prebuild(entry: Mapping[str, Any], src: Path) -> None:
    """台帳の prebuild（例 caption-review の build.sh）を送る前に流す。"""
    cmd = entry.get("prebuild")
    if cmd:
        subprocess.run(list(cmd), cwd=src, check=True, capture_output=True, text=True)


def git_label(root: Path = ROOT) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "git 不明"
    return f"git {sha}{'+手元の変更あり' if dirty else ''}"


# --- Apps Script API ------------------------------------------------------------


Requester = Callable[..., Any]


def check_scope(info: Mapping[str, Any]) -> None:
    granted = token_scopes(dict(info))
    missing = set(SCRIPT_SCOPES) - granted
    if missing:
        raise GoogleAuthError(
            f"送り込みの鍵に {', '.join(sorted(missing))} がありません。作り直し: {LOGIN_HINT}")


def build_session() -> Any:
    info, _, _ = read_token_info(SCRIPT_TOKEN_JSON_ENV, script_token_path())
    check_scope(info)
    from google.auth.transport.requests import AuthorizedSession

    credentials = load_credentials(SCRIPT_SCOPES, json_env=SCRIPT_TOKEN_JSON_ENV,
                                   token_file=script_token_path())
    return AuthorizedSession(credentials)


class Client:
    def __init__(self, session: Any):
        self.s = session

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        r = self.s.request(method, f"{API}{path}", json=body, timeout=120)
        if r.status_code >= 400:
            try:
                msg = r.json().get("error", {}).get("message", "")
            except ValueError:
                msg = ""
            raise RuntimeError(f"Apps Script API {method} {path} が {r.status_code}: {msg}")
        return r.json() if r.content else {}

    def get_content(self, script_id: str) -> list[dict[str, Any]]:
        return self._call("GET", f"/projects/{script_id}/content").get("files", [])

    def put_content(self, script_id: str, files: Sequence[Mapping[str, Any]]) -> None:
        self._call("PUT", f"/projects/{script_id}/content", {"files": list(files)})

    def create_version(self, script_id: str, description: str) -> int:
        return int(self._call("POST", f"/projects/{script_id}/versions",
                              {"description": description})["versionNumber"])

    def update_deployment(self, script_id: str, deployment_id: str, version: int,
                          description: str) -> None:
        self._call("PUT", f"/projects/{script_id}/deployments/{deployment_id}",
                   {"deploymentConfig": {"versionNumber": version,
                                         "manifestFileName": "appsscript",
                                         "description": description}})


def _slim(files: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": f.get("name"), "type": f.get("type"), "source": f.get("source", "")}
            for f in files]


def backup(script_id: str, files: Sequence[Mapping[str, Any]], directory: Path = BACKUP_DIR) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = directory / script_id / f"{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"scriptId": script_id, "files": _slim(files)},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def push(client: Client, entry: Mapping[str, Any], *, dry_run: bool = False,
         allow_new_scopes: bool = False, allow_remove: bool = False,
         label: str | None = None, root: Path = ROOT,
         backup_dir: Path = BACKUP_DIR, say: Callable[[str], None] = print) -> int | None:
    """送り込んで版を1つ作る。版の番号を返す（変更なし・dry-run は None）。"""
    script_id = str(entry["scriptId"])
    src = resolve_source(entry, root)
    if not src.is_dir():
        raise GuardError(f"送り込むフォルダがありません: {src}")
    prebuild(entry, src)
    local = collect_files(src, entry.get("include"))
    remote = client.get_content(script_id)
    plan = plan_push(local, remote)
    say(f"{entry['name']}（{script_id}）")
    for line in plan.lines():
        say(line)
    check_guards(plan, allow_new_scopes=allow_new_scopes, allow_remove=allow_remove)
    if dry_run:
        say("  dry-run なので送っていません")
        return None
    if plan.empty:
        say("  変更が無いので送りません")
        return None
    saved = backup(script_id, remote, backup_dir)
    say(f"  送る前の中身を控えた: {saved}")
    client.put_content(script_id, local)
    desc = f"Claude（クラウド）が送り込み・{label or git_label(root)}"
    version = client.create_version(script_id, desc)
    say(f"  送り込み済み。版 {version}（{desc}）")
    return version


def deploy(client: Client, entry: Mapping[str, Any], **kwargs: Any) -> int | None:
    """送り込み、公開（deploymentId）を今の版に上げる。URL は変わらない。"""
    say = kwargs.get("say", print)
    deployment_id = entry.get("deploymentId")
    if not deployment_id:
        raise GuardError(f"{entry['name']} は台帳に deploymentId が無いので公開できません（push だけ使う）")
    version = push(client, entry, **kwargs)
    if version is None:
        return None
    client.update_deployment(str(entry["scriptId"]), str(deployment_id), version,
                             f"版 {version}・Claude（クラウド）")
    say(f"  公開を版 {version} に上げた（URL は同じ）")
    return version


# --- CLI ------------------------------------------------------------------------


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apps Script をクラウドから送り込む（clasp の代わり）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="鍵の権限だけ見る（外に出ない）")
    sub.add_parser("list", help="台帳の一覧")
    for name in ("push", "deploy"):
        s = sub.add_parser(name)
        s.add_argument("project", help="台帳の名前")
        s.add_argument("--dry-run", action="store_true", help="変わることを出すだけ")
        s.add_argument("--allow-new-scopes", action="store_true")
        s.add_argument("--allow-remove", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.cmd == "list":
        for name, e in load_registry().items():
            print(f"{name}\t{e.get('account')}\t{e.get('kind')}\t{e.get('source')}")
        return 0
    if args.cmd == "check":
        try:
            info, source, _ = read_token_info(SCRIPT_TOKEN_JSON_ENV, script_token_path())
            check_scope(info)
        except GoogleAuthError as e:
            print(f"NG: {e}", file=sys.stderr)
            return 1
        print(f"OK: {source} に送り込みの権限があります")
        return 0
    registry = load_registry()
    if args.project not in registry:
        print(f"台帳に {args.project} がありません: {', '.join(registry)}", file=sys.stderr)
        return 2
    entry = registry[args.project]
    if entry.get("account") != "info@kitahara-birei.com":
        print(f"{args.project} は法人の鍵では送れません（{entry.get('account')}）。PC の clasp を使う",
              file=sys.stderr)
        return 2
    try:
        client = Client(build_session())
        fn = deploy if args.cmd == "deploy" else push
        fn(client, entry, dry_run=args.dry_run, allow_new_scopes=args.allow_new_scopes,
           allow_remove=args.allow_remove)
    except (GuardError, GoogleAuthError, RuntimeError) as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
