#!/usr/bin/env bash
# 送る前に、画面の本体（../caption_review.html）を Index.html に写す。画面は 1 つの正本で、Artifact でもウェブアプリでも同じ
set -euo pipefail
cd "$(dirname "$0")"
cp ../caption_review.html Index.html
echo "Index.html を作りました。clasp push → clasp update-deployment <id> で同じ URL に出ます"
