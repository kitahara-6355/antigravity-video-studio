"""アカウントの点検（R1）。**エラー本文の読み違えを固定する。**

一次情報がプロキシで遮断されているので、法人／個人の違いは**叩いて確かめる**
しかない。そのとき効くのは「返ってきたエラーを正しく読めること」で、ここを
外すと「無料枠が無い」と「レート上限に当たった」を取り違える。

守りたい性質は3つ:

1. エラー本文から**状況を言い分けられる**（課金要求／管理者ブロック／レート上限）
2. **読めなかったものを『問題なし』にしない**（unknown は成功ではない）
3. **キーそのものを出力しない**
"""
from __future__ import annotations

import pytest

from backend import verify_account
from backend.verify_account import diagnose, masked_key


# --- 1. 状況を言い分ける ------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    # 法人アカウントで AI Studio が管理コンソールで OFF のとき
    ("403 SERVICE_DISABLED: Generative Language API has not been used",
     "ai_studio_blocked"),
    ("API_KEY_SERVICE_BLOCKED", "ai_studio_blocked"),
    # 無料枠の対象外で、課金の有効化を求められたとき
    ("400 FAILED_PRECONDITION: billing to be enabled", "billing_required"),
    # 枠はあるが使い切っているとき
    ("429 RESOURCE_EXHAUSTED: Quota exceeded", "quota_exhausted"),
    ("rate limit exceeded", "quota_exhausted"),
    # 権限・キー
    ("403 PERMISSION_DENIED", "permission_denied"),
    ("400 API key not valid", "invalid_key"),
])
def test_the_error_is_classified(text, expected):
    assert diagnose(text)[0] == expected


def test_billing_required_is_not_confused_with_a_rate_limit():
    """**ここを取り違えると構成の判断を誤る。**

    「無料枠が無い（課金しろ）」と「無料枠はあるが使い切った」は、
    アカウントを選び直すかどうかの分かれ目になる。
    """
    billing = diagnose("FAILED_PRECONDITION: billing to be enabled")[0]
    quota = diagnose("429 RESOURCE_EXHAUSTED: Quota exceeded")[0]

    assert billing != quota


def test_every_diagnosis_explains_what_to_do():
    """種別だけ出しても動けない。**次の一手まで書く。**"""
    for needles, _kind, explanation in verify_account.DIAGNOSES:
        assert needles
        assert len(explanation) > 20


# --- 2. 読めなかったものを緑にしない ------------------------------------------


def test_an_unreadable_error_is_unknown_not_success():
    kind, explanation = diagnose("何かよく分からないことが起きました")

    assert kind == "unknown"
    assert "判定できません" in explanation


def test_an_empty_error_is_not_treated_as_success():
    assert diagnose("")[0] == "unknown"


# --- 3. キーを出力しない ------------------------------------------------------


def test_the_key_is_never_printed_in_full(monkeypatch):
    """**画面にもログにも実キーを出さない。** 出どころが分かる分だけ見せる。"""
    secret = "AIzaSyDUMMYKEYVALUE1234567890abcdef"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)

    shown = masked_key()

    assert secret not in shown
    assert shown.startswith("AIzaSy")
    assert str(len(secret)) in shown


def test_a_missing_key_is_reported_as_such(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    assert masked_key() == "(未設定)"


def test_a_dummy_key_is_shown_as_is(monkeypatch):
    """CI のダミーは秘密ではない。隠すと逆に分かりにくい。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy_key_for_ci")

    assert masked_key() == "dummy_key_for_ci"


# --- 出力 ---------------------------------------------------------------------


def test_a_dummy_key_stops_before_calling_anything(monkeypatch, capsys):
    """**ダミーキーで実測したふりをしない。** exit 1 で止める。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy_key_for_ci")

    code = verify_account.main([])

    assert code == 1
    assert "実測できません" in capsys.readouterr().out


def test_the_probe_is_opt_in(monkeypatch, capsys):
    """**課金しうる呼び出しは既定で行わない**（憲法第3条）。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_looks_real_enough")
    monkeypatch.setattr(verify_account.model_policy, "live_model_ids",
                        lambda: ({"gemini-3.6-flash"}, ""))
    called = []
    monkeypatch.setattr(verify_account, "probe_generate",
                        lambda model: called.append(model) or (True, ""))

    verify_account.main([])

    assert called == []
    assert "--probe" in capsys.readouterr().out


def test_the_probe_runs_when_asked(monkeypatch, capsys):
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_looks_real_enough")
    monkeypatch.setattr(verify_account.model_policy, "live_model_ids",
                        lambda: ({"gemini-3.6-flash"}, ""))
    called = []
    monkeypatch.setattr(verify_account, "probe_generate",
                        lambda model: (called.append(model), (True, ""))[1])

    verify_account.main(["--probe"])

    assert called == ["gemini-3.6-flash"]
    assert "無料枠の証拠" in capsys.readouterr().out


def test_a_missing_ladder_model_fails_the_check(monkeypatch, capsys):
    """段のモデルが実在しなければ exit 1（R1-C7 と同じ判定）。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_looks_real_enough")
    monkeypatch.setattr(verify_account.model_policy, "live_model_ids",
                        lambda: ({"gemini-3.6-flash"}, ""))

    code = verify_account.main([])

    assert code == 1
    assert "実在しない段があります" in capsys.readouterr().out


def test_a_blocked_api_is_reported_with_the_remedy(monkeypatch, capsys):
    """**法人アカウント特有の詰まり方**を、そう名指しする。"""
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza_looks_real_enough")
    monkeypatch.setattr(
        verify_account.model_policy, "live_model_ids",
        lambda: (set(), "403 SERVICE_DISABLED: has not been used"))

    code = verify_account.main([])
    out = capsys.readouterr().out

    assert code == 1
    assert "管理コンソール" in out
