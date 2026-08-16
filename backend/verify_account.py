"""アカウントの点検（R1）。**「どのアカウントで何ができるか」を実測で確定させる。**

法人（Workspace）と個人（Gmail）のどちらでキーを発行するかは、外部の事実に
依存する。その事実の一次情報（`ai.google.dev` / `docs.cloud.google.com` /
`blog.google`）は**この実行環境のプロキシで遮断されていて読めない。**

読めないなら**叩いて確かめる。** ドキュメントより実測のほうが強い証拠になる。

## 確定できること

| 命題 | 判定方法 | 課金 |
|---|---|---|
| キーが生きているか | `models.list` | 無料 |
| AI Studio が管理者に止められていないか | `models.list` のエラー本文 | 無料 |
| 段の4モデルが実在するか（R1-C7） | `models.list` と段の突き合わせ | 無料 |
| **無料枠があるか** | 最小の `generate_content` を1回（`--probe`） | 通れば実質0円 |

## 確定できないこと

- **課金が有効なプロジェクトかどうか。** API からは見えない。`--probe` が通った
  のが「無料枠のおかげ」か「課金しているから」かは、**設定した本人にしか分からない**
- **Monthly spend cap が設定されているか。** これも API からは見えない
  （`.claude/budget.json` の `spend_cap_usd` に書いてもらう）

## 使い方

    python -m backend.verify_account            # 無料の点検だけ
    python -m backend.verify_account --probe    # 無料枠の有無まで確かめる
"""
from __future__ import annotations

import argparse
import os

from backend import model_policy

# **最小の呼び出し。** 無料枠の有無を見るだけなので、トークンを使わない。
PROBE_PROMPT = "hi"
PROBE_MAX_TOKENS = 1

# エラー本文から状況を読む。**文言は変わりうるので、複数の手掛かりを見る。**
DIAGNOSES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (("SERVICE_DISABLED", "API_KEY_SERVICE_BLOCKED", "has not been used",
      "is disabled"),
     "ai_studio_blocked",
     "**AI Studio / Generative Language API が有効になっていません。**"
     "Workspace の管理コンソールで『追加サービス』として ON にし、"
     "ドメイン確認を済ませてください（法人アカウント特有の障壁）"),
    (("FAILED_PRECONDITION", "billing", "Billing"),
     "billing_required",
     "**課金の有効化を求められました。無料枠の対象外です。**"
     "このアカウントで Flash を無料で回すことはできません"),
    (("RESOURCE_EXHAUSTED", "429", "quota", "Quota", "rate limit"),
     "quota_exhausted",
     "**枠は割り当たっているが、いまは上限に当たっています。**"
     "無料枠が『無い』のではなく『使い切っている』状態。時間を置いて再実行してください"),
    (("PERMISSION_DENIED", "403"),
     "permission_denied",
     "**権限で弾かれました。** 組織ポリシー、またはキーの API 制限を確認してください"),
    (("API key not valid", "API_KEY_INVALID", "INVALID_ARGUMENT", "400"),
     "invalid_key",
     "**キーが受け付けられませんでした。** backend/.env の GOOGLE_API_KEY を"
     "確認してください（前後の空白・引用符の混入がよくある原因）"),
)


def diagnose(error_text: str) -> tuple[str, str]:
    """エラー本文から状況を読む。**分からなければ『不明』に倒す。**

    Returns:
        (種別, 説明)。種別 "unknown" は「読めなかった」であって「問題なし」ではない。
    """
    for needles, kind, explanation in DIAGNOSES:
        if any(needle in error_text for needle in needles):
            return kind, explanation
    return "unknown", (
        "**エラーの種別を判定できませんでした。**"
        "本文をそのまま読んでください（下に全文を出しています）")


def masked_key() -> str:
    """**キーそのものは出さない。** 出どころが分かる最小限だけ見せる。"""
    key = os.getenv("GOOGLE_API_KEY") or ""
    if not key:
        return "(未設定)"
    if key == "dummy_key_for_ci" or len(key) < 12:
        return key if key == "dummy_key_for_ci" else "(短すぎます)"
    return f"{key[:6]}…{key[-4:]}（{len(key)} 文字）"


def probe_generate(model: str) -> tuple[bool, str]:
    """最小の生成を1回。**必ず factory 経由で呼ぶ**（cost_guard が計上する）。

    Returns:
        (通ったか, エラー本文)
    """
    from backend.gemini_client_factory import get_gemini_client

    client = get_gemini_client()
    if client is None:
        return False, "クライアントを作れませんでした（GOOGLE_API_KEY 未設定）"
    try:
        client.models.generate_content(
            model=model, contents=PROBE_PROMPT,
            config={"max_output_tokens": PROBE_MAX_TOKENS})
    except Exception as e:  # noqa: BLE001 — 何で落ちても本文を読んで分類する
        return False, f"{type(e).__name__}: {e}"
    return True, ""


def _format(probe: bool) -> tuple[str, int]:
    from backend.cost_guard import is_dummy_key

    lines = ["アカウントの点検", "", f"  キー: {masked_key()}", ""]

    if is_dummy_key():
        lines += [
            "  🚫 **ダミーキーです。実測できません。**",
            "     backend/.env に実キーを置いてから実行してください。",
            "     （キーは私からは読み書きしません）",
        ]
        return "\n".join(lines), 1

    live, why_not = model_policy.live_model_ids()
    if not live:
        kind, explanation = diagnose(why_not)
        lines += [f"  🚫 モデル一覧を取れませんでした（{kind}）",
                  f"     — {explanation}", "", f"     本文: {why_not}"]
        return "\n".join(lines), 1

    lines.append(f"  ✅ モデル一覧を取得できました（{len(live)} 件）")
    lines.append("     → キーは生きていて、AI Studio も止められていません")
    lines.append("")

    table = model_policy.tiers()
    missing = []
    for tier in model_policy.tier_order():
        model = (table.get(tier) or {}).get("model", "")
        mark = "✅" if model in live else "🚫"
        if model not in live:
            missing.append(f"{tier}/{model}")
        lines.append(f"    {mark} {tier:9} {model}")
    lines.append("")
    if missing:
        lines.append(f"  🚫 **実在しない段があります**: {', '.join(missing)}")
        lines.append("     model_config.json を実在する ID に直してください")
    else:
        lines.append("  ✅ 段の4モデルはすべて実在します"
                     "（model_config.json の verified を true にできます）")
    lines.append("")

    if not probe:
        lines.append("  ℹ 無料枠の有無は確かめていません（--probe を付けてください）")
        return "\n".join(lines), 1 if missing else 0

    model = model_policy.model_of_tier("standard")
    ok, error = probe_generate(model)
    if ok:
        lines += [
            f"  ✅ {model} の呼び出しが通りました",
            "",
            "     **課金を有効にしていないプロジェクトなら、これが無料枠の証拠です。**",
            "     課金を有効にしているなら、この1回は実費です（台帳に残っています）:",
            "         python -m backend.cost_guard --status",
        ]
        return "\n".join(lines), 1 if missing else 0

    kind, explanation = diagnose(error)
    lines += [f"  🚫 {model} の呼び出しが通りませんでした（{kind}）",
              f"     — {explanation}", "", f"     本文: {error}"]
    return "\n".join(lines), 1


def main(argv: list[str] | None = None) -> int:
    from backend.cost_guard import load_env
    load_env()
    parser = argparse.ArgumentParser(description="アカウントの点検（R1）")
    parser.add_argument(
        "--probe", action="store_true",
        help="最小の生成を1回だけ実行して、無料枠の有無を確かめる")
    args = parser.parse_args(argv)

    text, code = _format(args.probe)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
