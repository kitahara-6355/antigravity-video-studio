#!/usr/bin/env python3
"""CI(Linux) でのみ失敗するテストの原因を特定するための診断出力。

## なぜ必要か

開発機は Windows、CI は Linux。ローカルで 3,719 passed / 0 failed のスイートが
CI では 34 件失敗する。うち以下の14件はローカルで再現できないため、
ログからの推測で直すと誤りを埋め込むリスクが高い。

  tests/test_antigravity_pipeline_chaos.py  … 10件
      assert 'completed' == 'failed' / Failed: DID NOT RAISE
  backend/tests/test_memory_distillation.py … 4件
      AssertionError: False is not true（assertLogs の内容不一致）

推測ではなく事実を取るため、CI 上で実際の解決先・実際のログ内容を出力する。

## 使い方

    python scripts/diagnose_linux_failures.py

診断が目的なので常に終了コード 0 を返す（CI を止めない）。
原因が判明したら、このスクリプトは削除してよい。
"""

from __future__ import annotations

import io
import logging
import os
import platform
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(1, str(ROOT))


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def show_env() -> None:
    section("実行環境")
    print(f"  platform : {platform.platform()}")
    print(f"  python   : {sys.version.split()[0]}")
    print(f"  cwd      : {os.getcwd()}")
    print("  sys.path の先頭5件:")
    for p in sys.path[:5]:
        print(f"    {p}")


def show_module_resolution() -> None:
    """chaos テストが patch 対象にしているモジュールの解決先を出す。

    patch("proper_noun_dict.apply_dictionary") が効かない場合、
    パイプラインが別の経路で同名モジュールを掴んでいる可能性がある。
    """
    section("chaos テストの patch 対象モジュールの解決先")
    targets = [
        "proper_noun_dict",
        "telop_proposal_engine",
        "semantic_store",
        "gemini_client_factory",
        "model_registry",
    ]
    for name in targets:
        try:
            mod = __import__(name)
            print(f"  {name:24s} → {getattr(mod, '__file__', '(組み込み)')}")
        except Exception as e:
            print(f"  {name:24s} → ❌ {type(e).__name__}: {e}")


def show_pipeline_binding() -> None:
    """AntigravityPipeline が patch 対象と同じモジュールオブジェクトを見ているか。

    別オブジェクトを掴んでいると patch が効かず、
    「例外を注入したのに phase が completed になる」という症状になる。
    """
    section("AntigravityPipeline のモジュール束縛")
    try:
        import backend.antigravity_pipeline as ap
        print(f"  antigravity_pipeline : {ap.__file__}")
        for name in ("proper_noun_dict", "telop_proposal_engine", "semantic_store"):
            bound = getattr(ap, name, None)
            if bound is None:
                print(f"  {name:24s} → モジュール属性として保持していない"
                      f"（呼び出し時に import している可能性）")
            else:
                same = sys.modules.get(name) is bound
                print(f"  {name:24s} → {getattr(bound, '__file__', '?')}")
                print(f"  {'':24s}   sys.modules と同一オブジェクト: {same}")
    except Exception:
        print("  ❌ import に失敗:")
        traceback.print_exc(limit=4)


def show_distiller_logs() -> None:
    """memory_distiller が実際に出すログを確認する。

    テストは "Gemini client is not initialized" を期待しているが、
    CI では一致せず assertTrue(any(...)) が False になっている。
    実際に何が出るのかを見る。
    """
    section("memory_distiller の実ログ出力")
    logger_name = "agents.orchestration.memory_distiller"
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    lg = logging.getLogger(logger_name)
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    try:
        from unittest.mock import patch as _patch
        with _patch("agents.orchestration.memory_distiller.get_gemini_client",
                    return_value=None):
            from agents.orchestration.memory_distiller import MemoryDistiller
            d = MemoryDistiller()
            print(f"  client が None か: {d.client is None}")
            result = d.distill_agent_memory("diagnostic_agent", force=True, max_lessons=5)
            print(f"  distill_agent_memory の戻り値: {result!r}")
    except Exception:
        print("  ❌ 実行中に例外:")
        traceback.print_exc(limit=6)
    finally:
        lg.removeHandler(handler)

    out = buf.getvalue()
    print("  --- 実際に出力されたログ ---")
    if out.strip():
        for line in out.strip().splitlines():
            print(f"    {line}")
    else:
        print("    (ログ出力なし)")
    print(f"  期待している文字列 'Gemini client is not initialized' を含むか: "
          f"{'Gemini client is not initialized' in out}")


def show_patch_effectiveness() -> None:
    """chaos テストの patch が実際に効くかを直接確かめる。

    CI では `assert 192 == 0` のように「例外を注入したのに実データが返る」
    症状が出ている。これは patch 対象と本体が別オブジェクトを見ていることを示す。
    どの経路でモジュールが二重に読まれているのかを特定する。
    """
    section("chaos テストの patch が効くか（直接検証）")
    try:
        from unittest.mock import patch as _patch
        import backend.antigravity_pipeline as ap
        from proper_noun_dict import proper_noun_dict as inst_toplevel

        # パイプライン本体が status 取得時に参照するインスタンス
        inst_in_module = getattr(ap, "proper_noun_dict", None)
        print(f"  test 側の instance id : {id(inst_toplevel)}")
        print(f"  pipeline 側の instance: {id(inst_in_module)}")
        print(f"  同一オブジェクトか     : {inst_toplevel is inst_in_module}")

        print("\n  sys.modules 内の proper_noun_dict 系エントリ:")
        for k, v in sorted(sys.modules.items()):
            if "proper_noun_dict" in k:
                print(f"    {k:44s} → {getattr(v, '__file__', '?')}")

        pipeline = ap.AntigravityPipeline()
        before = pipeline.get_pipeline_status().get("proper_noun_entries")
        with _patch.object(inst_toplevel, "get_all_entries",
                           side_effect=OSError("Database locked")):
            after = pipeline.get_pipeline_status().get("proper_noun_entries")
        print(f"\n  patch なし proper_noun_entries: {before}")
        print(f"  patch あり proper_noun_entries: {after}  （期待値 0）")
        print(f"  patch は有効か: {after == 0}")
    except Exception:
        print("  ❌ 実行中に例外:")
        traceback.print_exc(limit=6)


def main() -> int:
    show_env()
    show_module_resolution()
    show_pipeline_binding()
    show_patch_effectiveness()
    show_distiller_logs()
    print("\n診断完了（このスクリプトは CI を止めない）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
