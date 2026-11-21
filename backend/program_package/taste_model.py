"""好みカルテの推定と出題（回をまたいで覚える）。AI を呼ばない・0円。

設計: Claude資料/01_方針と計画「好みカルテ 設計書」（2026-11-15 北原さん承認）。
ページ（info@ の Apps Script）の JavaScript と同じ式をここにも置き、作り物の答えで確かめる。

曲の強さ s_i = w·z_i + e_i。P(a が勝つ) = 1 / (1 + exp(-(s_a - s_b)))。合格ライン s = 0。

- z: 曲の特徴。測る5つ（taste.features）を棚の基準値でそろえ ±2.5 で切った物と、楽器・雰囲気の印（TAGS の8語）
- w: 特徴の好み（事前の幅 0.5）、e: その曲だけの魅力（事前の幅 1.0）。ニュートン法で一度に解く
- 押した物の数え方は ``to_obs``。古い答えは180日で重みが半分、「ためし」の人の答えは数えない

使い方（リポジトリ直下で）::

    python -m backend.program_package.taste_model state --shelf shelf.json --answers 答え.json --topic op
    python -m backend.program_package.taste_model brief --karte backend/config/taste/美麗.json --shelf shelf.json --answers 答え.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np

MEASURED = ("bpm", "brightness", "density", "steadiness", "dynamics_db")
TAGS = ("ピアノ", "和楽器", "弦", "ギター", "打楽器", "静か", "華やか", "壮大")   # 決まった8語。台帳の tags から取る
CLIP = 2.5
PRIOR_W = 0.5
PRIOR_E = 1.0
HALF_LIFE_DAYS = 180
TRIAL_PEOPLE = ("ためし",)
CONFIRMED_START = 0.5          # 「そう」を押した好みの出発点
NO_ASK_DAYS = 90               # 「違う」を押した文は90日聞かない
EARLY_STOP_ROUND = 6           # 6回目以降、1位が2位と3位に直接勝っていれば終わり
PASS_TO_DECIDE = 0.7           # 1位の合格の見込みがこれ以上で「決める」へ
NO_FAVORITE = 0.5              # 1位の合格の見込みがこれ未満なら「本命はいない」
STAGES = ("広く", "しぼる", "決める", "決定")
WORDS = {   # taste.WORDS と同じ言葉（高い側・低い側）。印は「〜の音が入った」「〜な」
    "bpm": ("速め", "ゆっくり"),
    "brightness": ("明るくキラキラした音", "落ち着いた低めの音"),
    "density": ("細かく弾む", "音数が少なくゆったり"),
    "steadiness": ("リズムが途切れず続く", "リズムが止まったり揺れたりする"),
    "dynamics_db": ("盛り上がりの差が大きい", "大きさが一定"),
}
BAR = -1   # 合格ラインを表す相手


def _today() -> date:
    """日本時間の今日（答えの古さを数える基準）。"""
    from datetime import timedelta
    return (datetime.now(UTC) + timedelta(hours=9)).date()


class ModelError(RuntimeError):
    pass


def keys() -> list[str]:
    return list(MEASURED) + [f"tag:{t}" for t in TAGS]


# ---- 特徴をそろえる ----

def baseline(items: list[dict]) -> dict:
    """棚の基準値（測る5つの平均と幅）。棚に曲が増えても、基準値を固定しておけば重みの意味が変わらない。"""
    out = {}
    for k in MEASURED:
        vals = [float(it["features"][k]) for it in items if it.get("features", {}).get(k) is not None]
        if vals:
            sd = float(np.std(vals)) or 1.0
            out[k] = [round(float(np.mean(vals)), 4), round(sd, 4)]
    return out


def matrix(items: list[dict], base: dict) -> np.ndarray:
    """曲 × 特徴の行列 Z。測っていない値は0（平均）、印は有り1・無し0。"""
    z = np.zeros((len(items), len(MEASURED) + len(TAGS)))
    for i, it in enumerate(items):
        f = it.get("features") or {}
        for j, k in enumerate(MEASURED):
            if f.get(k) is not None and k in base:
                m, sd = base[k]
                z[i, j] = max(-CLIP, min(CLIP, (float(f[k]) - m) / sd))
        tags = set(it.get("tags") or [])
        for j, t in enumerate(TAGS):
            z[i, len(MEASURED) + j] = 1.0 if t in tags else 0.0
    return z


# ---- 答えを数える ----

def _age_weight(at: str | None, today: date) -> float:
    if not at:
        return 1.0
    try:
        d = datetime.fromisoformat(str(at).replace("Z", "+00:00")).date()
    except ValueError:
        return 1.0
    return 0.5 ** (max(0, (today - d).days) / HALF_LIFE_DAYS)


def to_obs(ans: dict, idx: dict[str, int], today: date) -> list[tuple[int, int, float]]:
    """答え1件を (勝った方, 負けた方, 重み) の並びにする。BAR は合格ライン。

    - a / b: 選んだ方の1勝
    - both（どちらも好き）: 引き分け、2曲とも合格ラインに半勝
    - neither（どちらも違う）: 引き分け、2曲とも合格ラインに半敗
    - decide（この曲に決める）: その曲が合格ラインに2勝、一緒に出た上位2曲（with）に1勝ずつ
    """
    if (ans.get("who") or "") in TRIAL_PEOPLE:
        return []
    w = _age_weight(ans.get("at"), today)
    pick = ans.get("pick")
    if pick == "decide":
        i = idx.get(ans.get("song"))
        if i is None:
            return []
        out = [(i, BAR, 2.0 * w)]
        out += [(i, idx[o], 1.0 * w) for o in (ans.get("with") or [])[:2] if o in idx and idx[o] != i]
        return out
    a, b = idx.get(ans.get("a")), idx.get(ans.get("b"))
    if a is None or b is None or a == b:
        return []
    if pick == "a":
        return [(a, b, w)]
    if pick == "b":
        return [(b, a, w)]
    if pick == "both":
        return [(a, b, .5 * w), (b, a, .5 * w), (a, BAR, .5 * w), (b, BAR, .5 * w)]
    if pick == "neither":
        return [(a, b, .5 * w), (b, a, .5 * w), (BAR, a, .5 * w), (BAR, b, .5 * w)]
    return []


# ---- 推定 ----

@dataclass
class Posterior:
    ids: list[str]
    mu: np.ndarray        # 曲ごとの強さの平均
    sd: np.ndarray        # その幅
    cov: np.ndarray       # 曲どうしの共分散
    w: np.ndarray         # 特徴の好み
    w_sd: np.ndarray
    theta: np.ndarray
    S: np.ndarray

    def p_pass(self, i: int) -> float:
        """その曲が合格ライン（0）を越える見込み。"""
        return 0.5 * (1 + math.erf(self.mu[i] / (self.sd[i] * math.sqrt(2) + 1e-12)))

    def prospect(self, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """まだ聞いていない曲の見込み（平均 w·z と、好みの不確かさによる幅）。"""
        d = z.shape[1]
        sw = self.S[:d, :d]
        return z @ self.w, np.sqrt(np.einsum("ij,jk,ik->i", z, sw, z))


def _sig(x):
    return 1 / (1 + np.exp(-x))


def fit(z: np.ndarray, obs: list[tuple[int, int, float]], prior_mean_w: np.ndarray | None = None,
        ids: list[str] | None = None) -> Posterior:
    """s = w·z + e をニュートン法で解く（事前は w〜N(m, 0.5²)、e〜N(0, 1²)）。"""
    n, d = z.shape
    p_ = d + n
    prec = np.r_[np.full(d, 1 / PRIOR_W ** 2), np.full(n, 1 / PRIOR_E ** 2)]
    m = np.zeros(p_)
    if prior_mean_w is not None:
        m[:d] = prior_mean_w
    x = np.zeros((len(obs), p_))
    wt = np.zeros(len(obs))
    for k, (i, j, w) in enumerate(obs):
        if i >= 0:
            x[k, :d] += z[i]
            x[k, d + i] += 1
        if j >= 0:
            x[k, :d] -= z[j]
            x[k, d + j] -= 1
        wt[k] = w
    th = m.copy()
    for _ in range(30):
        p = _sig(x @ th)
        g = x.T @ (wt * (1 - p)) - prec * (th - m)
        h = x.T @ (x * (wt * p * (1 - p))[:, None]) + np.diag(prec)
        step = np.linalg.solve(h, g)
        th += step
        if np.abs(step).max() < 1e-8:
            break
    p = _sig(x @ th)
    h = x.T @ (x * (wt * p * (1 - p))[:, None]) + np.diag(prec)
    s = np.linalg.inv(h)
    a = np.hstack([z, np.eye(n)])
    mu = a @ th
    c = a @ s @ a.T
    return Posterior(ids or [str(i) for i in range(n)], mu, np.sqrt(np.clip(np.diag(c), 1e-12, None)), c,
                     th[:d].copy(), np.sqrt(np.diag(s)[:d]), th, s)


def confirmed_prior(karte: dict | None) -> np.ndarray:
    """カルテで「そう」の好みを出発点にする（向きに 0.5）。"""
    m = np.zeros(len(MEASURED) + len(TAGS))
    ks = keys()
    for ln in (karte or {}).get("lines", []):
        if ln.get("status") == "そう" and ln.get("feature") in ks:
            m[ks.index(ln["feature"])] = CONFIRMED_START * (1 if ln.get("direction", "+") == "+" else -1)
    return m


# ---- 次の組 ----

def next_pair(post: Posterior, pack: list[int], heard: set[int], met: set[tuple[int, int]]) -> tuple[int, int]:
    """1回の中の次の2曲。顔見せ（初めての曲を見込み順に隣どうし）→ 詰め（平均＋幅の上位4曲から、
    p(1−p)×差の幅 が最大の組。比べた組は0.3倍）。"""
    mu = post.mu
    unseen = sorted([i for i in pack if i not in heard], key=lambda i: -mu[i])
    if len(unseen) >= 2:
        return unseen[0], unseen[1]
    if len(unseen) == 1:
        a = unseen[0]
        return a, max((i for i in pack if i != a), key=lambda i: mu[i])
    c = post.cov
    top = sorted(pack, key=lambda i: -(mu[i] + post.sd[i]))[:4]
    best, bv = None, -1.0
    for i, j in itertools.combinations(top, 2):
        v = c[i, i] + c[j, j] - 2 * c[i, j]
        p = _sig(mu[i] - mu[j])
        sc = p * (1 - p) * v * (0.3 if (min(i, j), max(i, j)) in met else 1.0)
        if sc > bv:
            bv, best = sc, (i, j)
    return best


def early_stop(post: Posterior, pack: list[int], session: list[tuple[int, int, str]], rnd: int) -> bool:
    """6回目以降、1位が2位と3位に、この回の中で直接勝っていれば終わり。"""
    if rnd < EARLY_STOP_ROUND or len(pack) < 3:
        return False
    order = sorted(pack, key=lambda i: -post.mu[i])
    top = order[0]
    beat = set()
    for a, b, pick in session:
        if pick == "a" and a == top:
            beat.add(b)
        if pick == "b" and b == top:
            beat.add(a)
    return order[1] in beat and order[2] in beat


def narrow_pack(post: Posterior, z: np.ndarray, heard: set[int], m: int = 8, explore: int = 2,
                kappa: float = 2.0, dropped: set[int] | None = None) -> list[int]:
    """「しぼる」の8曲: 前回までの上位2曲＋好みに近い見込みの4曲＋まだ試していない方向の2曲。"""
    dropped = dropped or set()
    anchors = sorted(heard, key=lambda i: -post.mu[i])[:2]
    un = [i for i in range(len(post.ids)) if i not in heard and i not in dropped]
    pm, ps = post.prospect(z)
    near = sorted(un, key=lambda i: -pm[i])[:max(0, m - len(anchors) - explore)]
    rest = [i for i in un if i not in near]
    far = sorted(rest, key=lambda i: -(pm[i] + kappa * ps[i]))[:explore]
    return anchors + near + far


def dropped_songs(post: Posterior, record: dict[int, list[int]]) -> set[int]:
    """落とす曲: 0勝2敗以上か、平均が合格ラインより幅1つ分以上下。record は {曲: [勝ち, 負け]}。"""
    out = {i for i, (wins, losses) in record.items() if wins == 0 and losses >= 2}
    out |= {i for i in record if post.mu[i] + post.sd[i] < 0}
    return out


def stage_after(post: Posterior, z: np.ndarray, heard: set[int], stage: str) -> str:
    """回を終えたあとの段階。広く → しぼる → 決める（決定はページの「この曲に決める」で）。"""
    if stage == "広く":
        return "しぼる"
    if stage == "しぼる":
        top = max(heard, key=lambda i: post.mu[i])
        pm, ps = post.prospect(z)
        beyond = [i for i in range(len(post.ids)) if i not in heard and pm[i] + ps[i] > post.mu[top]]
        return "決める" if post.p_pass(top) >= PASS_TO_DECIDE and not beyond else "しぼる"
    return stage


def summary(post: Posterior, heard: set[int]) -> dict:
    """聞いた曲の順位と合格の見込み。1位の見込みが低ければ「本命はいない」。"""
    order = sorted(heard, key=lambda i: -post.mu[i])
    rows = [{"id": post.ids[i], "mu": round(float(post.mu[i]), 3), "sd": round(float(post.sd[i]), 3),
             "p_pass": round(post.p_pass(i), 3)} for i in order]
    return {"ranking": rows, "no_favorite": bool(rows) and rows[0]["p_pass"] < NO_FAVORITE}


# ---- カルテの文と、Vids の指示文 ----

def statements(post: Posterior, tendencies: list[dict], karte: dict | None, today: date) -> list[dict]:
    """好みの文の候補（未確認）。重みが幅の1.5倍を越え、かつ差のある組4つ以上で7割以上そろった特徴だけ。
    「違う」を押した文は90日聞かない。最大2行（ページの「そう／違う」で押す数）。"""
    ks = keys()
    quiet = set()
    for ln in (karte or {}).get("lines", []):
        if ln.get("status") == "違う" and ln.get("feature"):
            try:
                d = date.fromisoformat(str(ln.get("date"))[:10])
            except ValueError:
                d = today
            if (today - d).days < NO_ASK_DAYS:
                quiet.add((ln["feature"], ln.get("direction", "+")))
    known = {(ln.get("feature"), ln.get("direction", "+")) for ln in (karte or {}).get("lines", [])
             if ln.get("status") in ("そう", "未確認")}
    agree = {t["feature"]: t for t in tendencies}
    out = []
    for j, k in enumerate(MEASURED):
        w, sd = post.w[j], post.w_sd[j]
        if abs(w) <= 1.5 * sd or k not in agree:
            continue
        direction = "+" if w > 0 else "-"
        word = WORDS[k][0 if w > 0 else 1]
        if agree[k]["word"] != word or (k, direction) in quiet or (k, direction) in known:
            continue
        out.append({"feature": ks[j], "direction": direction, "statement": f"{word}曲が好き",
                    "evidence": f"重み {w:.2f}（幅 {sd:.2f}）・差のあった {agree[k]['pairs']} 組のうち "
                                f"{round(agree[k]['share'] * 100)}%", "status": "未確認",
                    "date": today.isoformat(), "weight": abs(w) / sd})
    return [{k: v for k, v in x.items() if k != "weight"} for x in sorted(out, key=lambda x: -x["weight"])[:2]]


BRIEF_HEAD = "番組のはじまり（OP）の曲。10秒あたりで盛り上がる30秒の曲。歌なし。"


def brief(post: Posterior, karte: dict | None, n_core: int = 2) -> list[dict]:
    """Vids で次に作る曲の指示文を3案（芯2・ためし1）。定型文に好みの言葉を入れるだけ（AI なし）。

    芯: 「そう」の好みと、重みのはっきりした特徴を言葉にする。ためし: いちばん分かっていない特徴を逆に振る。
    """
    sure = {}
    for ln in (karte or {}).get("lines", []):
        if ln.get("status") == "そう" and ln.get("feature") in MEASURED:
            sure[ln["feature"]] = ln.get("direction", "+")
    order = sorted(range(len(MEASURED)), key=lambda j: -abs(post.w[j]) / (post.w_sd[j] + 1e-9))
    for j in order:
        k = MEASURED[j]
        if k not in sure and abs(post.w[j]) > post.w_sd[j]:
            sure[k] = "+" if post.w[j] > 0 else "-"
    words = [WORDS[k][0 if d == "+" else 1] for k, d in sure.items()]
    out = []
    for c in range(n_core):
        use = words[c:] + words[:c] if words else []
        out.append({"kind": "芯", "prompt": BRIEF_HEAD + ("".join(f"{w}。" for w in use[:3]) or "落ち着いた和の雰囲気。")})
    unknown = max(range(len(MEASURED)), key=lambda j: post.w_sd[j] - abs(post.w[j]))
    k = MEASURED[unknown]
    flip = WORDS[k][1] if sure.get(k) == "+" else WORDS[k][0]
    out.append({"kind": "ためし", "prompt": BRIEF_HEAD + "".join(f"{w}。" for w in words[:2]) + f"ただし{flip}。"})
    return out


# ---- まとめて使う ----

def state(shelf: dict, answers: list[dict], topic: str, karte: dict | None = None,
          today: date | None = None) -> dict:
    """棚と答え全部から、お題の今（karte_state.json の中身）を作る。"""
    today = today or _today()
    items = [it for it in shelf["songs"] if topic in (it.get("roles") or [topic])]
    if not items:
        raise ModelError(f"お題 {topic} の曲が棚にありません")
    ids = [it["id"] for it in items]
    idx = {k: i for i, k in enumerate(ids)}
    z = matrix(items, shelf.get("baseline") or baseline(items))
    mine = [a for a in answers if a.get("topic", topic) == topic]
    obs = [o for a in mine for o in to_obs(a, idx, today)]
    post = fit(z, obs, confirmed_prior(karte), ids)
    heard = {idx[a[s]] for a in mine if (a.get("who") or "") not in TRIAL_PEOPLE
             for s in ("a", "b", "song") if a.get(s) in idx}
    pm, ps = post.prospect(z)
    return {"topic": topic, "answers": len(obs), "summary": summary(post, heard),
            "unheard": [{"id": ids[i], "mu": round(float(pm[i]), 3), "sd": round(float(ps[i]), 3)}
                        for i in sorted(set(range(len(ids))) - heard, key=lambda i: -pm[i])],
            "weights": {k: [round(float(post.w[j]), 3), round(float(post.w_sd[j]), 3)] for j, k in enumerate(keys())}}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="好みカルテの推定と、Vids の指示文")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("state", "brief"):
        s = sub.add_parser(name)
        s.add_argument("--shelf", required=True)
        s.add_argument("--answers", required=True)
        s.add_argument("--topic", default="op")
        s.add_argument("--karte")
    a = p.parse_args(argv)
    shelf = json.loads(Path(a.shelf).read_text(encoding="utf-8"))
    answers = json.loads(Path(a.answers).read_text(encoding="utf-8"))
    karte = json.loads(Path(a.karte).read_text(encoding="utf-8")) if a.karte else None
    try:
        st = state(shelf, answers, a.topic, karte)
    except ModelError as e:
        print(f"止めました: {e}", file=sys.stderr)
        return 1
    if a.cmd == "state":
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    items = [it for it in shelf["songs"] if a.topic in (it.get("roles") or [a.topic])]
    ids = [it["id"] for it in items]
    z = matrix(items, shelf.get("baseline") or baseline(items))
    idx = {k: i for i, k in enumerate(ids)}
    obs = [o for x in answers for o in to_obs(x, idx, _today())]
    for b in brief(fit(z, obs, confirmed_prior(karte), ids), karte):
        print(f"{b['kind']}: {b['prompt']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
