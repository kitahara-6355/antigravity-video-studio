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
    python -m backend.verify_account --projects # 台帳と環境変数の突き合わせ（外に出ない）

## `--projects`（M0・CLAUDE.md「API プロジェクトとキーの管理」）

台帳 `backend/config/api_projects.json`（キー本体は入れない・末尾4文字だけ）と
環境変数の実態を突き合わせ、**食い違いを FAIL で出す**:

- 台帳にないキー（末尾4文字が一致する行が無い）
- 請求先の想定違い（billing: true のキーが無料枠の口 `GOOGLE_API_KEY` に入っている）
- 旧式の変数名（`GEMINI_API_KEY`）
- クラウドのセッションに置いてはいけないキー（`GOOGLE_API_KEY_PRO`）
- 保管（Cloudflare R2）のトークンが揃っていない
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from backend import model_policy

LEDGER_PATH = Path(__file__).resolve().parent / "config" / "api_projects.json"

# クラウドのセッション（Claude Code on the web）にだけある環境変数。
# **値は空のことがある**ので、有無で見る。見つかれば「クラウドに置いてはいけないキー」の検査を有効にする。
CLOUD_MARKERS = ("CCR_SESSION_PROFILE",)

Finding = tuple[str, str]  # ("OK" | "INFO" | "FAIL", 説明)

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


# --- 台帳との突き合わせ（--projects） -----------------------------------------


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def key_suffix(value: str) -> str:
    """**同定に使うのは末尾4文字だけ。** 台帳にも出力にもそれ以上は出さない。"""
    return value[-4:]


def is_cloud_session(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return any(marker in env for marker in CLOUD_MARKERS)


def _is_dummy(value: str) -> bool:
    return value.startswith(("dummy", "test"))


def _check_gemini_keys(env: Mapping[str, str], ledger: dict,
                       cloud: bool) -> Iterable[Finding]:
    projects = ledger.get("projects", [])
    allowed_in_cloud = set(ledger.get("cloud_allowed_env", []))
    for name in sorted({p["env"] for p in projects}):
        rows = [p for p in projects if p["env"] == name]
        value = env.get(name) or ""
        if not value:
            active = [p["id"] for p in rows if p.get("status") == "active"]
            if active:
                yield "FAIL", (f"{name} が未設定（台帳では {', '.join(active)} が "
                               f"active）。.env かクラウドの Secrets に置いてください")
            else:
                yield "INFO", f"{name} は未設定（台帳の {', '.join(p['id'] for p in rows)} は未着手）"
            continue
        if _is_dummy(value):
            yield "FAIL", f"{name} はダミーキー（{value}）。実キーではないので突き合わせできません"
            continue
        if cloud and name not in allowed_in_cloud:
            yield "FAIL", (f"{name} がクラウドのセッションに置かれています。クラウドの Secrets は "
                           f"avs-prod-free のキーと raw の読み取り専用トークンだけ（2026-09-26 ユーザー決定）。"
                           f"環境設定から外してください")
        suffix = key_suffix(value)
        matched = [p for p in rows if p.get("key_suffix") == suffix]
        if not matched:
            yield "FAIL", (f"{name} のキー（末尾 {suffix}）が台帳にない。"
                           f"台帳 {LEDGER_PATH.name} の該当行に key_suffix を書くか、"
                           f"どのプロジェクトのキーか分からなければ使わないでください")
            continue
        for p in matched:
            if p.get("billing") and name == "GOOGLE_API_KEY":
                yield "FAIL", (f"{name} に入っているのは {p['id']}（請求先あり）。"
                               f"無料枠の口に課金するキーを入れると Tier 1 で回ります — 請求先の想定違い")
            else:
                billing = "請求先あり" if p.get("billing") else "請求先なし"
                yield "OK", f"{name} = {p['id']}（末尾 {suffix}・{billing}・{p.get('status', '?')}）"


def _check_deprecated(env: Mapping[str, str], ledger: dict) -> Iterable[Finding]:
    for name in ledger.get("deprecated_env", []):
        if env.get(name):
            yield "FAIL", (f"{name} が設定されています — 旧式の変数名。"
                           f"GOOGLE_API_KEY に一本化してください（CLAUDE.md の未実装項目・変数名の混在が混乱の一因）")


def _check_storage(env: Mapping[str, str], ledger: dict) -> Iterable[Finding]:
    for row in ledger.get("storage", []):
        names = row["env"]
        present = [n for n in names if env.get(n)]
        if not present:
            yield "INFO", f"{row['id']} のトークンは未設定（{row.get('status', '?')}）"
            continue
        missing = [n for n in names if n not in present]
        if missing:
            yield "FAIL", (f"{row['id']} のトークンが揃っていません。"
                           f"不足: {', '.join(missing)}（手順書の Secrets 4つをすべて置く）")
            continue
        suffix = key_suffix(env[row["suffix_env"]])
        if row.get("key_suffix") is None:
            yield "FAIL", (f"{row['id']} のトークン（{row['suffix_env']} 末尾 {suffix}）が台帳に未記載。"
                           f"key_suffix を書いてください")
        elif row["key_suffix"] != suffix:
            yield "FAIL", (f"{row['id']} のトークン（末尾 {suffix}）が台帳（末尾 {row['key_suffix']}）と違う")
        else:
            yield "OK", f"{row['id']} = {row.get('provider', '?')}（末尾 {suffix}・読み取り専用）"


def check_projects(env: Mapping[str, str], ledger: dict, *,
                   cloud: bool) -> list[Finding]:
    """台帳と環境変数を突き合わせる。**外には出ない**（API を叩かない）。"""
    findings: list[Finding] = []
    findings += _check_deprecated(env, ledger)
    findings += _check_gemini_keys(env, ledger, cloud)
    findings += _check_storage(env, ledger)
    return findings


def _format_projects(findings: list[Finding], cloud: bool) -> tuple[str, int]:
    marks = {"OK": "✅", "INFO": "ℹ", "FAIL": "🚫 FAIL"}
    where = "クラウドのセッション" if cloud else "ローカル"
    lines = ["API プロジェクトの台帳との突き合わせ", "",
             f"  台帳: {LEDGER_PATH}", f"  環境: {where}", ""]
    for level, text in findings:
        lines.append(f"  {marks[level]} {text}")
    fails = sum(1 for level, _ in findings if level == "FAIL")
    lines.append("")
    if fails:
        lines.append(f"  🚫 食い違い {fails} 件。直してから先へ進んでください")
        return "\n".join(lines), 1
    lines.append("  ✅ 台帳と実態は一致しています")
    return "\n".join(lines), 0


def main(argv: list[str] | None = None) -> int:
    from backend.cost_guard import load_env
    load_env()
    parser = argparse.ArgumentParser(description="アカウントの点検（R1）")
    parser.add_argument(
        "--probe", action="store_true",
        help="最小の生成を1回だけ実行して、無料枠の有無を確かめる")
    parser.add_argument(
        "--projects", action="store_true",
        help="台帳 backend/config/api_projects.json と環境変数を突き合わせる（外に出ない）")
    args = parser.parse_args(argv)

    if args.projects:
        cloud = is_cloud_session()
        text, code = _format_projects(
            check_projects(os.environ, load_ledger(), cloud=cloud), cloud)
        print(text)
        return code

    text, code = _format(args.probe)
    print(text)
    return code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
