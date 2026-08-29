# -*- coding: utf-8 -*-
"""`evolution_log.json` の作り物に印を付ける — **唯一の集約点**（R1.5-C4）。

`post_publish_feedbacks` には `YOUTUBE_API_MODE=mock` 時代に
`random.Random(seed)` で組み立てた CTR・維持率・再生数が `actual_*` の名前で
12件焼き付いている（このファイルは Git 追跡下）。書き込みは
`routers/youtube_optimizer._record_post_publish_feedback` で止めたが、
**既にある行は消さずに印を付ける**（記録は残す）。

## なぜ独立したモジュールなのか

6周目の指摘を受けて `branding_manager.get_evolution_log_for_display()` に
印を集約し、その docstring に「読み口が2つあるので印を付ける場所は1つにする」と
書いた。**読み口は3つあった。**

| 読み口 | 経路 |
|---|---|
| `GET /api/evolution` | `routers/trinity.py` |
| `GET /api/director/evolution` | `routers/legacy_director_router.py` |
| **`GET /api/v1/mcp/resources/evolution_log`** | `mcp_server.py` → `api_versioning.py:67` |

3つ目は `branding_manager` を通さず JSON を直接読むので、
`branding_manager` に置いた集約点を**迂回していた**（gate-verifier 7周目 指摘1）。

`mcp_server` は起動を軽く保つために `branding_manager` を import しない。
だから**両方が依存できる、依存を持たない場所**にロジックを置く。
ここに置けば「読み口を1つ増やしたら印も付く」ではなく、
「**印を付けずに読む道が無い**」に近づく。
"""

from typing import Any, Dict

# 印そのもの。`is_real` が真の行には付けない
作り物の印 = {
    "is_real": False,
    "data_source": "sample",
    "note": "**YouTube から取得した実績ではありません。**"
            "YOUTUBE_API_MODE=mock 時代に random で組み立てた値です",
}


def 実績に印を付ける(log: Dict[str, Any]) -> Dict[str, Any]:
    """`post_publish_feedbacks` の各行に出所の印を付けた**写し**を返す。

    - `is_real: True` の行はそのまま（本物の実績）
    - それ以外は作り物とみなす（**fail-closed**）
    - **元の dict は書き換えない。** 保存側が素のまま残るようにするため
      （印がファイルへ書き戻ると、次に読んだとき本物と区別できなくなる）
    """
    if not isinstance(log, dict):
        return log

    行 = log.get("post_publish_feedbacks")
    if not isinstance(行, list):
        return log

    写し = dict(log)
    写し["post_publish_feedbacks"] = [
        fb if fb.get("is_real") is True else {**fb, **作り物の印}
        for fb in 行 if isinstance(fb, dict)
    ]
    return 写し
