"""JST 時刻ユーティリティ — ダッシュボードの日付・時刻を実行環境から切り離す

ダッシュボードとレポートの日付は **常に JST** で決まる（規約上 `... JST` と表示し、
ファイル名も `ranking_YYYYMMDD.md` のように JST の日付で付ける）。

`datetime.now()` や `datetime.fromtimestamp()` は **実行環境のローカルタイムゾーン**を使うため、
開発機（JST）では正しく、CI やクラウド実行（UTC）では 9 時間ずれる。ずれると:

  - 同じ JST 日に `ranking_20260726.md` と `ranking_20260725.md` の 2 ファイルが生まれる（重複）
  - 「直近24時間」の集計範囲が環境ごとに変わる（表示揺れ）
  - mtime から起こした日付ラベルが 1 日前後する

そのため、日付・時刻の生成は本モジュールに集約する。

使い分け:
  - 現在時刻            → `now_jst()`
  - epoch/mtime → 日付  → `jst_date(ts)` / `jst_from_timestamp(ts)`
  - 表示用スタンプ      → `jst_stamp()`  ("2026-07-26 05:00 JST")
  - ログ文字列の解釈    → `parse_jst("2026-07-26 05:00 JST")`

なお経過時間の計算（`datetime.now().timestamp() - mtime` など）は naive でも結果が変わらないため、
本モジュールの対象外。
"""

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

_STAMP_FORMAT = "%Y-%m-%d %H:%M JST"


def now_jst() -> datetime:
    """現在時刻を JST の aware datetime で返す。ローカルタイムゾーンに依存しない。"""
    return datetime.now(timezone.utc).astimezone(JST)


def jst_from_timestamp(ts: float) -> datetime:
    """epoch 秒（`os.path.getmtime()` など）を JST の aware datetime に変換する。"""
    return datetime.fromtimestamp(ts, tz=JST)


def to_jst(value=None) -> datetime:
    """datetime / epoch / None を JST の aware datetime に揃える。

    naive datetime は「JST として記録されたもの」とみなす（本プロジェクトのログは JST 表記のため）。
    """
    if value is None:
        return now_jst()
    if isinstance(value, (int, float)):
        return jst_from_timestamp(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=JST)
        return value.astimezone(JST)
    raise TypeError(f"datetime / epoch のいずれかを渡してください: {type(value)!r}")


def jst_date(value=None) -> str:
    """JST の日付文字列 'YYYY-MM-DD'。"""
    return to_jst(value).strftime("%Y-%m-%d")


def jst_compact_date(value=None) -> str:
    """JST の日付文字列 'YYYYMMDD'（ファイル名用）。"""
    return to_jst(value).strftime("%Y%m%d")


def jst_stamp(value=None) -> str:
    """JST の表示用スタンプ 'YYYY-MM-DD HH:MM JST'。"""
    return to_jst(value).strftime(_STAMP_FORMAT)


def parse_jst(text) -> datetime | None:
    """'YYYY-MM-DD HH:MM JST' 形式の文字列を JST の aware datetime に戻す。

    解釈できない場合は None を返す（ログ由来の文字列を扱うため例外は投げない）。
    """
    if not isinstance(text, str):
        return None
    clean = text.replace("JST", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(clean, fmt).replace(tzinfo=JST)
        except ValueError:
            continue
    return None


__all__ = [
    "JST",
    "now_jst",
    "to_jst",
    "jst_from_timestamp",
    "jst_date",
    "jst_compact_date",
    "jst_stamp",
    "parse_jst",
]
