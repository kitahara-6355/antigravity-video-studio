#!/usr/bin/env bash
# クラウド（Claude Code のコンテナ）で書き出しを PC と同じにする準備。0 円・鍵なし。
#   - ffmpeg 7.1.1（PC と同じ版。conda-forge の gpl 版: libx264・libass・fontconfig 入り）
#   - 字幕の書体 BIZ UDPゴシック（SIL OFL）を backend/data/fonts に
# 使い方: bash scripts/cloud_render_setup.sh [入れる場所]   → 最後に出る export を実行する
# johnvansickle.com と GitHub のリリースはこの環境のプロキシで遮断されているので conda-forge から取る。
set -euo pipefail
DEST="${1:-${TMPDIR:-/tmp}/avs-ffmpeg711}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ ! -x "$DEST/bin/ffmpeg" ]; then
  WORK="$(mktemp -d)"
  curl -sSfL -o "$WORK/mm.tar.bz2" https://conda.anaconda.org/conda-forge/linux-64/micromamba-2.9.0-0.tar.bz2
  tar xjf "$WORK/mm.tar.bz2" -C "$WORK" bin/micromamba
  MAMBA_ROOT_PREFIX="$WORK/mamba" "$WORK/bin/micromamba" create -y -q -p "$DEST" \
    -c conda-forge --override-channels "ffmpeg=7.1.1=gpl*"
  rm -rf "$WORK"
fi
"$DEST/bin/ffmpeg" -hide_banner -version | head -1
(cd "$ROOT" && python3 -m backend.subtitle_font --fetch)
echo "export PATH=\"$DEST/bin:\$PATH\""
