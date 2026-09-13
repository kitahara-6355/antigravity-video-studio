# -*- coding: utf-8 -*-
"""`user_model.json` の `external_status` に印を付ける — **唯一の集約点**（R1.5-C4）。

`branding/user_model.json`（Git 追跡下）の `external_status` には、
過去の `POST /api/analytics/sync` が焼き付けた**作り物のチャンネル統計**が
そのまま残っている。

```
youtube = {"subscribers": 150, "total_views": 4500, "videos": 12,
           "last_updated": "2026-06-28T02:53:11.581892"}
rivals  = {"nemesis": {"name": "TechStarter", "subs": 180, ...},
           "benchmark": {"name": "TechMastery", "subs": 15000, ...}}
quests  = [{"type": "NEMESIS_BATTLE", "target_val": 180, "current_val": 150, ...}]
```

出所は `branding/analytics_manager.py` の `mock_my_stats` と `scout_rivals()`
（`# TODO: Replace with real YouTube API call` のまま）。
**登録者数と総再生数は収益化の到達度そのもの**なので、印が無いと
「登録者 150 人・4,500 回」を実績として読んでしまう。

## なぜ独立したモジュールなのか

6周目・8周目に印を付けたが、**付けた場所が `analytics_manager` の中**だった。
そこを通るのは `POST /api/analytics/sync` を**叩いた後**だけで、
**永続台帳を素で返す読み口には届いていなかった**（gate-verifier 10周目 N-1）。

`evolution_log` でまったく同じことをやって
`backend/evolution_log_marks.py` へ集約したのに、**こちらには同じ手当てを
していなかった。** 読み口は2つある:

| 読み口 | 経路 | 何を返すか |
|---|---|---|
| `GET /api/status` | `routers/trinity.py` → `branding_manager.user_model` | user_model 丸ごと |
| `GET /api/settings` | `routers/legacy_management_router.py` → `settings_manager.get_all_settings()` | 同上を `user_model` キーに包んで |

**10周目が名指ししたのは前者だけ**で、後者は同じクラスの別経路だった
（8周目と同じ轍）。だから経路ごとに塞がず、**外へ出す値を作る一箇所**に置く。

## 保存側は素のまま

`_save_json(USER_MODEL_PATH, ...)` が書くのは `branding_manager.user_model`
そのもので、ここは通らない。**印がファイルへ書き戻ると、次に読んだとき
本物と区別できなくなる**（`evolution_log_marks` と同じ理由）。
そのためどの関数も**元の dict を書き換えず、写しを返す**。
"""

from typing import Any, Dict

# 印そのもの。`is_real` が真の値には付けない
作り物の印 = {
    "is_real": False,
    "data_source": "sample",
    "note": "**YouTube から取得した実績ではありません。**Analytics API に"
            "一度も接続していません。収益化の到達度の判断に使わないでください",
}

# 作り物の統計から機械的に出した数字。実測ではないが、統計そのものでもない
派生の印 = {
    "is_real": False,
    "data_source": "derived",
    "note": "**作り物のチャンネル統計から計算した値です。**"
            "元の登録者数・総再生数が実測ではないので、この差分も実測ではありません",
}

# `external_status` の中で印が要るキー
_統計のキー = ("youtube", "stats")   # dict
_ライバルのキー = ("rivals",)         # dict
_クエストのキー = ("quests",)         # list[dict]


def _本物か(値: Any) -> bool:
    """**fail-closed。** `is_real: True` を明示したものだけ本物とみなす。"""
    return isinstance(値, dict) and 値.get("is_real") is True


def _統計に印(統計: Any) -> Any:
    """チャンネル統計の写しに印を付ける。

    `last_updated` は **None に潰す**。一度も同期していないのに
    `2026-06-28T02:53:11.581892` が入っていると「いま更新した」に見える
    （`analytics_manager.mock_my_stats` で同じ理由から None にしてある。
    永続台帳には**印を付ける前の古い時刻が残っている**）。
    """
    if not isinstance(統計, dict) or _本物か(統計):
        return 統計
    写し = {**統計, **作り物の印}
    if "last_updated" in 写し:
        写し["last_updated"] = None
    return 写し


def _ライバルに印(ライバル: Any) -> Any:
    """ライバルの写しに印を付ける。`nemesis` / `benchmark` の中身にも付ける。

    外側だけだと、UI が `rivals.nemesis` を取り出して描いた時点で印が消える。
    """
    if not isinstance(ライバル, dict) or _本物か(ライバル):
        return ライバル
    写し = {**ライバル, **作り物の印}
    for キー in ("nemesis", "benchmark"):
        中身 = 写し.get(キー)
        if isinstance(中身, dict) and not _本物か(中身):
            写し[キー] = {**中身, **作り物の印}
    return 写し


def _クエストに印(クエスト: Any) -> Any:
    """クエストは list なので**各行に**印を付ける（`evolution_log_marks` と同じ形）。

    `target_val: 180` / `current_val: 150` は作り物の統計とライバルの差分なので
    `derived`。
    """
    if not isinstance(クエスト, list):
        return クエスト
    return [
        行 if _本物か(行) else {**行, **派生の印}
        for 行 in クエスト if isinstance(行, dict)
    ]


def 外部実績に印を付ける(external_status: Any) -> Any:
    """`external_status` の写しを返す。**元の dict は書き換えない。**"""
    if not isinstance(external_status, dict):
        return external_status

    写し = dict(external_status)
    for キー in _統計のキー:
        if キー in 写し:
            写し[キー] = _統計に印(写し[キー])
    for キー in _ライバルのキー:
        if キー in 写し:
            写し[キー] = _ライバルに印(写し[キー])
    for キー in _クエストのキー:
        if キー in 写し:
            写し[キー] = _クエストに印(写し[キー])
    return 写し


def _事業ランクに印(profiles: Any) -> Any:
    """`profiles.*.ranks.biz_rank` の写しに印を付ける（2026-09-03 ユーザー決定）。

    **`biz_rank` の XP は作り物のチャンネル統計から出ている。**
    `branding_manager.process_analytics_update()` が
    `calculated_xp = int(current_views / 100)` で作っており、
    総再生 4,500（作り物）から **XP 45** になる。それを
    `SoulPassport.jsx` が `XP 45` と**無印で**描いていた
    （R1.5-C4・gate-verifier 15周目の記録）。

    `quests` と同じ **`derived`**（統計そのものではないが、統計から出た値）。

    **`tech_rank` には付けない。** あちらは `ingest_report()` の
    XP 付与から積まれるもので、チャンネル統計から出ていない。
    """
    if not isinstance(profiles, dict):
        return profiles

    写し = dict(profiles)
    for 役割, 中身 in profiles.items():
        if not isinstance(中身, dict):
            continue
        ranks = 中身.get("ranks")
        if not isinstance(ranks, dict):
            continue
        biz = ranks.get("biz_rank")
        if not isinstance(biz, dict) or _本物か(biz):
            continue
        写し[役割] = {**中身, "ranks": {**ranks, "biz_rank": {**biz, **派生の印}}}
    return 写し


def 実績を持つ値に印を付ける(model: Any) -> Any:
    """`user_model` 丸ごとの写しを返す。**外へ出す読み口はこれを通す。**

    印が要るのは2箇所:
      - `external_status`（チャンネル統計・ライバル・クエスト）
      - `profiles.*.ranks.biz_rank`（作り物の総再生から出た XP）
    """
    if not isinstance(model, dict):
        return model
    if "external_status" not in model and "profiles" not in model:
        return model

    写し = dict(model)
    if "external_status" in model:
        写し["external_status"] = 外部実績に印を付ける(model["external_status"])
    if "profiles" in model:
        写し["profiles"] = _事業ランクに印(model["profiles"])
    return 写し
