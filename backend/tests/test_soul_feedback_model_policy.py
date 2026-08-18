"""演出提案の工程が、段（model_policy）を経由してモデルを決めることを守る。

2026-08-19 の実走で見つけた。`_call_llm_for_suggestions` が
`model="gemini-2.5-flash"` を**直書き**していて、段を一度も見ていなかった。

実走ではこうなった:

    404 NOT_FOUND. This model models/gemini-2.5-flash-lite is no longer
    available to new users. Please update your code to use
    models/gemini-3.5-flash-lite

直書きの `gemini-2.5-flash` が `model_governance` のフォールバック連鎖
（`gemini-2.5-flash` → `gemini-2.5-flash-lite`）に流れ、そこで落ちた。
`model_policy --show` は該当工程を `gemini-3.7-flash` と表示していたのに、
**実際に呼ばれたモデルは表示と違っていた。**

CLAUDE.md が「工程はモデル名ではなく段に紐づける。直書きだと入替のたびに
14工程を書き換えることになり、実際それで `gemini-3-flash-preview` が居座って
腐った」と書いている、まさにその型が現存していた。

ここで守るのは2つ:
  1. 呼び出すモデルを直書きしない（段から解決する）
  2. **見える化が嘘にならないこと** — `model_policy` の表示と実際に呼ぶ
     モデルが一致する。R1-C5 / R1-C6 が要求しているのはこれ
"""

from unittest.mock import MagicMock

from backend import model_policy
from backend.video_pipeline.soul_feedback_engine import SoulFeedbackEngine

# この工程の段。プロンプトが「あなたはプロの映像ディレクター」で始まり、
# 演出・編集の提案を4カテゴリで作るので `director` に対応する。
TASK = "director"


def _captured_model(engine: SoulFeedbackEngine) -> str:
    """_call_llm_for_suggestions が実際に渡すモデル名を取り出す。"""
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text="[]")

    engine._call_llm_for_suggestions(client, "dummy prompt")

    assert client.models.generate_content.called, "generate_content が呼ばれていない"
    return client.models.generate_content.call_args.kwargs["model"]


def test_モデルを直書きしない():
    """段から解決したモデルを使うこと。"""
    used = _captured_model(SoulFeedbackEngine())
    expected = model_policy.resolve(TASK).model

    assert used == expected, (
        f"段が示すのは {expected} なのに {used} を呼んでいる。"
        f"**モデル名を直書きしない** — 段の入替が工程に届かなくなる")


def test_提供終了する2_5系を直に呼ばない():
    """2026-10-16 に終了する 2.5 系を、この経路から直接呼ばない。

    実走で `gemini-2.5-flash-lite` が 404 を返している（新規ユーザーには
    すでに提供されていない）。終了日を待たずに壊れる。
    """
    used = _captured_model(SoulFeedbackEngine())

    assert not used.startswith("gemini-2.5"), (
        f"{used} は 2026-10-16 に提供終了する系統。段から解決すること")


def test_見える化が嘘にならない():
    """**R1-C5 / R1-C6 の本体。**

    `model_policy --show` が示すモデルと、実際に呼ばれるモデルが一致すること。
    ここがずれると、実行記録に残るモデル名が実態と違うものになり、
    「どの工程がどのモデルで動いたか」という見える化そのものが嘘になる。
    """
    shown = model_policy.resolve(TASK)
    used = _captured_model(SoulFeedbackEngine())

    assert used == shown.model, (
        f"表示は {shown.model}（段 {shown.tier} / 根拠 {shown.source}）だが、"
        f"実際に呼ぶのは {used}")


def test_段を上げたら呼ぶモデルも変わる(tmp_path, monkeypatch):
    """昇格が工程に届くこと（直書きだと届かない）。

    CLAUDE.md の「結果に不満なら、すぐグレードアップを指示できる」は、
    段の変更が実際の呼び出しに反映されて初めて成立する。
    """
    monkeypatch.setattr(model_policy, "OVERRIDES_PATH",
                        tmp_path / "overrides.json", raising=False)
    model_policy.load_overrides.cache_clear() if hasattr(
        model_policy.load_overrides, "cache_clear") else None

    before = _captured_model(SoulFeedbackEngine())
    pro_model = model_policy.model_of_tier(model_policy.tier_order()[-1])

    # 段が最上位でないなら、上げたときに呼ぶモデルも変わるはず
    if before != pro_model:
        monkeypatch.setattr(model_policy, "resolve",
                            lambda task: model_policy.Decision(
                                task, pro_model, "pro", "test"))
        after = _captured_model(SoulFeedbackEngine())
        assert after == pro_model, (
            f"段を pro に上げたのに {after} を呼んでいる。"
            f"昇格が工程に届いていない")
