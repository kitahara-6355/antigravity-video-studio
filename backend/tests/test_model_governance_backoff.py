"""429/503 に対する同一モデルの指数バックオフ再試行。

2026-08-19 の実走で `soul_feedback` が 503 UNAVAILABLE を受け、**一度も
再試行せずに** 次のモデルへ降格 → 最終的にスタブへ落ちた。一次情報の指示は
「短時間待って再試行」であり、降格は再試行が尽きた後の話。

同時にこれは BAN 回避の実装要件でもある。無制限の再試行や無待機の連打は
自動化された乱用と区別がつかないので、**試行回数に上限があること**と
**待ち時間が指数で伸びること**を固定する。

404（モデル不在）は再試行しない。存在しないモデルを叩き直しても結果は
変わらず、無駄な負荷になるだけ。降格だけが正しい対処。
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from google.genai.errors import APIError
from google.api_core.exceptions import ServiceUnavailable

from backend.model_governance import (
    ModelGovernanceEngine,
    GovernedModelsProxy,
    GovernedAsyncModelsProxy,
)


@pytest.fixture
def engine():
    """シングルトンの設定を退避して、テストごとに独立させる。"""
    eng = ModelGovernanceEngine()
    saved = (
        dict(eng._fallback_chain),
        dict(eng._task_mapping),
        eng.RETRY_DELAY_SECONDS,
        eng.MAX_RETRY_PER_MODEL,
    )
    eng._fallback_chain = {"model-a": "model-b"}
    eng._task_mapping = {}
    eng.RETRY_DELAY_SECONDS = 0.001  # テストを待たせない
    try:
        yield eng
    finally:
        (
            eng._fallback_chain,
            eng._task_mapping,
            eng.RETRY_DELAY_SECONDS,
            eng.MAX_RETRY_PER_MODEL,
        ) = saved


def _api_error(code, message="", details=None):
    payload = {"message": message or str(code)}
    if details is not None:
        payload["details"] = details
    return APIError(code, payload)


# ============================================================
# 判定と待ち時間の計算
# ============================================================

def test_429と503は再試行対象(engine):
    assert engine.is_retryable_error(_api_error(429, "RESOURCE_EXHAUSTED")) is True
    assert engine.is_retryable_error(_api_error(503, "UNAVAILABLE")) is True
    assert engine.is_retryable_error(ServiceUnavailable("overloaded")) is True


def test_404と400は再試行しない(engine):
    """モデル不在も不正リクエストも、待って直るものではない。"""
    assert engine.is_retryable_error(_api_error(404, "NOT_FOUND")) is False
    assert engine.is_retryable_error(_api_error(400, "INVALID_ARGUMENT")) is False


def test_待ち時間は指数で伸びる(engine):
    engine.RETRY_DELAY_SECONDS = 2
    d0 = engine.backoff_delay(0)
    d1 = engine.backoff_delay(1)
    d2 = engine.backoff_delay(2)
    # equal jitter: 各段は [基準/2, 基準] に収まる
    assert 1.0 <= d0 <= 2.0
    assert 2.0 <= d1 <= 4.0
    assert 4.0 <= d2 <= 8.0


def test_待ち時間には上限がある(engine):
    """指数は放っておくと発散する。何時間も寝かせない。"""
    engine.RETRY_DELAY_SECONDS = 2
    assert engine.backoff_delay(30) <= engine.BACKOFF_MAX_SECONDS


def test_待ち時間はジッターで散る(engine):
    """同時に走った複数プロセスが同じ瞬間に再送すると連打と同じになる。"""
    engine.RETRY_DELAY_SECONDS = 2
    values = {engine.backoff_delay(2) for _ in range(50)}
    assert len(values) > 1


def test_サーバーが指定した待ち時間を優先する(engine):
    """RetryInfo が来たら自前の計算より一次情報を採る。"""
    engine.RETRY_DELAY_SECONDS = 2
    err = _api_error(429, "RESOURCE_EXHAUSTED", details=[
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "31s"},
    ])
    assert engine.retry_after_seconds(err) == pytest.approx(31.0)
    assert engine.backoff_delay(0, err) == pytest.approx(31.0)


def test_サーバー指定でも上限は超えない(engine):
    err = _api_error(429, "RESOURCE_EXHAUSTED", details=[
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "3600s"},
    ])
    assert engine.backoff_delay(0, err) <= engine.BACKOFF_MAX_SECONDS


def test_RetryInfoが無ければNone(engine):
    assert engine.retry_after_seconds(_api_error(503, "UNAVAILABLE")) is None


# ============================================================
# 同期プロキシ
# ============================================================

def test_503は同じモデルで再試行してから成功する(engine):
    """降格せずに元のモデルで復帰できること。これが実走で起きなかった。"""
    real = MagicMock()
    calls = []

    def side_effect(*, model, **kwargs):
        calls.append(model)
        if len(calls) < 3:
            raise _api_error(503, "UNAVAILABLE")
        return "ok"

    real.generate_content.side_effect = side_effect
    proxy = GovernedModelsProxy(real, "test")

    assert proxy.generate_content(model="model-a") == "ok"
    assert calls == ["model-a", "model-a", "model-a"], "降格せず同じ段で粘るはず"


def test_再試行の待ち時間が実際に指数で伸びる(engine):
    engine.RETRY_DELAY_SECONDS = 2
    real = MagicMock()
    real.generate_content.side_effect = _api_error(503, "UNAVAILABLE")
    proxy = GovernedModelsProxy(real, "test")

    with patch("backend.model_governance.time.sleep") as slept:
        with pytest.raises(APIError):
            proxy.generate_content(model="model-a")

    waits = [c.args[0] for c in slept.call_args_list]
    # model-a で2回、model-b で2回の再試行 + 降格の間の待ち
    assert len(waits) >= 4
    assert waits[1] > waits[0], f"2回目の待ちが伸びていない: {waits}"


def test_再試行の回数には上限がある(engine):
    """無制限に叩かない。BAN 回避の要件。"""
    real = MagicMock()
    real.generate_content.side_effect = _api_error(503, "UNAVAILABLE")
    proxy = GovernedModelsProxy(real, "test")

    with pytest.raises(APIError):
        proxy.generate_content(model="model-a")

    per_model = engine.MAX_RETRY_PER_MODEL + 1
    assert real.generate_content.call_count == per_model * 2, (
        "チェーン2段 × 各段の試行上限を超えている"
    )


def test_404は再試行せず即座に降格する(engine):
    real = MagicMock()
    calls = []

    def side_effect(*, model, **kwargs):
        calls.append(model)
        if model == "model-a":
            raise _api_error(404, "NOT_FOUND")
        return "ok"

    real.generate_content.side_effect = side_effect
    proxy = GovernedModelsProxy(real, "test")

    assert proxy.generate_content(model="model-a") == "ok"
    assert calls == ["model-a", "model-b"], "存在しないモデルを叩き直している"


def test_再試行が尽きたら次のモデルへ降格する(engine):
    real = MagicMock()
    calls = []

    def side_effect(*, model, **kwargs):
        calls.append(model)
        if model == "model-a":
            raise _api_error(503, "UNAVAILABLE")
        return "ok"

    real.generate_content.side_effect = side_effect
    proxy = GovernedModelsProxy(real, "test")

    assert proxy.generate_content(model="model-a") == "ok"
    assert calls[-1] == "model-b"
    assert calls.count("model-a") == engine.MAX_RETRY_PER_MODEL + 1


def test_embed_contentも同じ段で再試行する(engine):
    real = MagicMock()
    calls = []

    def side_effect(*, model, contents, **kwargs):
        calls.append(model)
        if len(calls) < 3:
            raise _api_error(429, "RESOURCE_EXHAUSTED")
        return "ok"

    real.embed_content.side_effect = side_effect
    proxy = GovernedModelsProxy(real, "test")

    assert proxy.embed_content(model="model-a", contents="hi") == "ok"
    assert calls == ["model-a", "model-a", "model-a"]


def test_再試行はイベントログに残る(engine):
    """見える化。何回粘ったかが後から読めること。"""
    real = MagicMock()
    calls = []

    def side_effect(*, model, **kwargs):
        calls.append(model)
        if len(calls) < 2:
            raise _api_error(503, "UNAVAILABLE")
        return "ok"

    real.generate_content.side_effect = side_effect
    proxy = GovernedModelsProxy(real, "test")
    before = len(engine._event_log)
    proxy.generate_content(model="model-a")

    types = [e["type"] for e in engine._event_log[before:]]
    assert "retry_attempt" in types


# ============================================================
# 非同期プロキシ
# ============================================================

@pytest.mark.asyncio
async def test_非同期でも同じ段で再試行する(engine):
    real = MagicMock()
    calls = []

    async def side_effect(*, model, **kwargs):
        calls.append(model)
        if len(calls) < 3:
            raise _api_error(503, "UNAVAILABLE")
        return "ok"

    real.generate_content = AsyncMock(side_effect=side_effect)
    proxy = GovernedAsyncModelsProxy(real, "test")

    assert await proxy.generate_content(model="model-a") == "ok"
    assert calls == ["model-a", "model-a", "model-a"]


@pytest.mark.asyncio
async def test_非同期_404は再試行しない(engine):
    real = MagicMock()
    calls = []

    async def side_effect(*, model, **kwargs):
        calls.append(model)
        if model == "model-a":
            raise _api_error(404, "NOT_FOUND")
        return "ok"

    real.generate_content = AsyncMock(side_effect=side_effect)
    proxy = GovernedAsyncModelsProxy(real, "test")

    assert await proxy.generate_content(model="model-a") == "ok"
    assert calls == ["model-a", "model-b"]


@pytest.mark.asyncio
async def test_非同期_embed_contentも再試行する(engine):
    real = MagicMock()
    calls = []

    async def side_effect(*, model, contents, **kwargs):
        calls.append(model)
        if len(calls) < 2:
            raise _api_error(429, "RESOURCE_EXHAUSTED")
        return "ok"

    real.embed_content = AsyncMock(side_effect=side_effect)
    proxy = GovernedAsyncModelsProxy(real, "test")

    assert await proxy.embed_content(model="model-a", contents="hi") == "ok"
    assert calls == ["model-a", "model-a"]


# ============================================================
# 統一ゲートウェイ (engine.call)
# ============================================================

@pytest.mark.asyncio
async def test_ゲートウェイも同じ段で再試行する(engine):
    engine._task_mapping = {"t": "model-a"}
    client = MagicMock()
    calls = []
    response = MagicMock()
    response.text = "ok"

    async def side_effect(*, model, **kwargs):
        calls.append(model)
        if len(calls) < 3:
            raise _api_error(503, "UNAVAILABLE")
        return response

    client.aio.models.generate_content = AsyncMock(side_effect=side_effect)

    with patch("gemini_client_factory._get_raw_client", return_value=client):
        assert await engine.call(task="t", prompt="hi") == "ok"
    assert calls == ["model-a", "model-a", "model-a"]


# --- 段に降格先があること -------------------------------------------------------
#
# 2026-08-20 の実走で 2回続けて 503 を踏み、どちらも
# `all models exhausted! chain=gemini-3.7-flash` で終わった。
# **チェーンの長さが 1。** 再試行が尽きても降格する先が無いので、
# soul_feedback は毎回スタブに落ちる。
#
# 原因は `model_config.json` の fallback_chain が**旧世代のまま**だったこと:
#
#     gemini-3-flash-preview → gemini-2.5-flash → gemini-2.5-flash-lite → null
#
# 採用中の P3（3.5-flash-lite / 3.6-flash / 3.7-flash / 3.1-pro-preview）は
# **1つも載っていない。** しかも降格先が 2026-10-16 に終了する 2.5 系。
# 設計意図（Premium → Standard → Batch の順で消費し枯渇時に降格）が
# 実装されていなかった。


def test_採用中の段すべてに降格先がある():
    """**最下段以外は降格できること。** チェーン長 1 は降格先ゼロ。"""
    from backend import model_policy
    from backend.model_governance import ModelGovernanceEngine

    engine = ModelGovernanceEngine()
    engine.reload()
    order = model_policy.tier_order()
    table = model_policy.tiers()

    # `tier_order` は昇順（batch → … → pro）。降格は下向きなので、
    # 降格先が要るのは**最下段以外**＝先頭を除いた全部。
    for tier in order[1:]:
        model = (table.get(tier) or {}).get("model", "")
        if not model:
            continue
        chain = engine.build_fallback_sequence(model)
        assert len(chain) > 1, (
            f"{tier}({model}) に降格先がありません: chain={chain}"
        )


def test_降格先に2_5系を使わない():
    """2026-10-16 に終了する段へ落とすチェーンを残さない。"""
    from backend.model_governance import ModelGovernanceEngine

    engine = ModelGovernanceEngine()
    engine.reload()

    # 出発点が 2.5 系なのは構わない（旧い呼び出し元がそこから始まる）。
    # **降格した先**が 2.5 系だと、終了と同時に死ぬ段へ落とすことになる。
    doomed = sorted({v for v in engine._fallback_chain.values()
                     if v and v.startswith("gemini-2.5")})
    assert doomed == [], f"降格先に 2.5 系が残っています: {doomed}"
