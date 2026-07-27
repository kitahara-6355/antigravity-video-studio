#!/usr/bin/env python3
"""シークレット混入検出（全テキストファイル対象）。

旧実装（ci.yml インライン）は `*.py` のみを走査し、検出しても `::warning` を
出すだけで失敗しなかった。そのため 2026-07-25 に発見された GitHub PAT の混入
（`.ps1` 2ファイル + `.git/config` 2箇所）を素通りさせていた。

このスクリプトは拡張子を限定せず、検出時は終了コード 1 で失敗する。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / ".github" / "secret-scan-allowlist.txt"

PATTERNS: dict[str, re.Pattern[str]] = {
    "GitHub PAT (classic)": re.compile(r"ghp_[0-9A-Za-z]{36}"),
    "GitHub PAT (fine-grained)": re.compile(r"github_pat_[0-9A-Za-z_]{60,}"),
    "GitHub OAuth token": re.compile(r"gho_[0-9A-Za-z]{36}"),
    "Google API Key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "OpenAI API Key": re.compile(r"sk-[0-9A-Za-z]{48}"),
    "Slack token": re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"),
    "AWS Access Key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "Private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "URL 埋め込み認証": re.compile(r"https://[A-Za-z0-9_\-]{16,}@github\.com"),
}

# 走査から除外するディレクトリ（生成物・依存関係）
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "__pycache__",
    ".pytest_cache", "htmlcov", ".next", "out", "dist", "build",
    "site-packages", "_archives", "archives",
}

# バイナリ拡張子
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svg",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".flac",
    ".zip", ".gz", ".tar", ".7z", ".pdf", ".woff", ".woff2", ".ttf",
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".onnx", ".pt",
}

MAX_BYTES = 2 * 1024 * 1024  # 2MB を超えるファイルは走査しない


def _should_scan(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    try:
        if path.stat().st_size > MAX_BYTES:
            return False
    except OSError:
        return False
    return True


def _load_allowlist() -> set[str]:
    """既知のダミー値を含むファイルのパス一覧。

    許可リストに載せてよいのは「値がダミーであることが明白」なものだけ。
    実在するクレデンシャルをここに載せて回避してはならない。
    """
    if not ALLOWLIST.exists():
        return set()
    entries: set[str] = set()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.add(line.replace("\\", "/"))
    return entries


def _tracked_files() -> list[Path]:
    """Git 追跡下のファイルのみを対象にする。

    リポジトリに実際に入っているものだけを見る。gitignore 済みのローカル
    .env 等を誤検出しないため、かつ CI のチェックアウト内容と一致させるため。
    """
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        capture_output=True, cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print("git ls-files に失敗したため全ファイル走査にフォールバックします")
        return [p for p in ROOT.rglob("*") if p.is_file()]
    names = proc.stdout.decode("utf-8", errors="replace").split("\0")
    return [ROOT / n for n in names if n]


def main() -> int:
    findings: list[str] = []
    scanned = 0
    allowed = _load_allowlist()

    for path in _tracked_files():
        if not path.is_file() or not _should_scan(path):
            continue
        if str(path.relative_to(ROOT)).replace("\\", "/") in allowed:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        scanned += 1
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                rel = path.relative_to(ROOT)
                findings.append(f"{rel}: {label}")
                # 値そのものは絶対に出力しない（ログに残ると二次流出になる）

    print(f"走査対象: {scanned} ファイル")

    if findings:
        print(f"\n🚫 シークレットの疑いを {len(findings)} 件検出しました:")
        for f in sorted(set(findings)):
            print(f"  ::error ::{f}")
        print("\n該当箇所から値を除去し、当該クレデンシャルを必ず失効させてください。")
        return 1

    print("✅ シークレットは検出されませんでした")
    return 0


if __name__ == "__main__":
    sys.exit(main())
