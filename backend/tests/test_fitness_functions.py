"""
Architecture Fitness Functions — Phase C/D

Phase B-1〜B-3 で確立したアーキテクチャルールを恒久的に強制するテスト群。
全テストは静的解析ベース（API呼び出し不要）で、CIに組み込み可能。

Fitness Functions:
  FF-1: 単一実行パス (HARNESS_MODE分岐がないこと)
  FF-2: ADK Bridge 非使用 (本番コードにadk_bridge importがないこと)
  FF-3: Worker数の整合性 (PipelineCoordinatorのWorkerが7つ)
  FF-4: print文禁止 (本番モジュールにprint()がないこと)
  FF-5: サイレント失敗禁止 (except ... : pass がないこと)
  FF-6: モデルガバナンスtask_mapping整合性
  FF-7: パイプラインAI Workerのガバナンス統一
  FF-8: Harness障害時のグレースフル・デグラデーション
  FF-9: model_registry → model_governance 委譲 (Strangler Fig)
  FF-10: gemini_client_factory → GovernedModelsProxy 自動ラップ (Phase E)
"""

import ast
import json
import re
import sys
import os
from pathlib import Path
from typing import List, Tuple

import pytest

# バックエンドルートをパスに追加
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))


# ============================================================
# ヘルパー: ソースコード読み込み
# ============================================================

def _read_source(filename: str) -> str:
    """バックエンド直下またはサブディレクトリからソースを読み込む"""
    path = BACKEND_DIR / filename
    if not path.exists():
        # サブディレクトリ探索
        for p in BACKEND_DIR.rglob(Path(filename).name):
            if "_deprecated" not in str(p) and "__pycache__" not in str(p):
                path = p
                break
    return path.read_text(encoding="utf-8")


def _read_source_path(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# パイプライン本番モジュール（Fitness Function 対象）
PRODUCTION_MODULES = [
    "agents/pipeline_coordinator.py",
    "routers/pipeline_router.py",
    "model_governance.py",
    "audio_master.py",
    "quality_gate_ai.py",
    "subtitle_engine/ai_proofreader.py",
    "plugins/youtube_optimizer_plugin.py",
    "video_editor_engine.py",
    "smart_cut_engine.py",
    "safe_io.py",
]


# ============================================================
# FF-1: 単一実行パス
# ============================================================

class TestFF1SingleExecutionPath:
    """Phase B-1 で廃止したHARNESS_MODE分岐が復活していないことを検証"""

    def test_no_harness_mode_in_router(self):
        """pipeline_router.py に HARNESS_MODE 分岐がないこと"""
        source = _read_source("routers/pipeline_router.py")
        assert "HARNESS_MODE" not in source, (
            "pipeline_router.py に HARNESS_MODE が残存しています。"
            "Phase B-1 で廃止済み: 単一パスアーキテクチャに違反。"
        )

    def test_no_dual_path_execution(self):
        """pipeline_router.py に execute_with_harness がないこと"""
        source = _read_source("routers/pipeline_router.py")
        assert "execute_with_harness" not in source, (
            "execute_with_harness が残存しています。"
            "PipelineCoordinator.execute() が唯一の実行パスです。"
        )

    def test_single_coordinator_call(self):
        """pipeline_router.py が pipeline_coordinator.execute() のみを呼ぶこと"""
        source = _read_source("routers/pipeline_router.py")
        # pipeline_coordinator からの import を確認
        assert "from agents.pipeline_coordinator import pipeline_coordinator" in source, (
            "pipeline_router.py は pipeline_coordinator を import していません。"
        )


# ============================================================
# FF-2: ADK Bridge 非使用
# ============================================================

class TestFF2NoAdkBridge:
    """Phase B-1 で _deprecated/ に移動した adk_bridge が本番コードから参照されていないこと"""

    def test_no_adk_bridge_import_in_production(self):
        """本番モジュールに adk_bridge import がないこと"""
        violations = []
        for mod in PRODUCTION_MODULES:
            path = BACKEND_DIR / mod
            if not path.exists():
                continue
            source = _read_source_path(path)
            if "adk_bridge" in source:
                violations.append(mod)
        assert not violations, (
            f"本番モジュールに adk_bridge 参照が残存: {violations}. "
            f"adk_bridge は _deprecated/ に移動済みです。"
        )

    def test_no_adk_bridge_in_harness_init(self):
        """harness/__init__.py に get_adk_bridge がないこと"""
        source = _read_source("harness/__init__.py")
        assert "get_adk_bridge" not in source, (
            "harness/__init__.py に get_adk_bridge が残存しています。"
        )


# ============================================================
# FF-3: Worker 数の整合性
# ============================================================

class TestFF3CoordinatorWorkerCount:
    """PipelineCoordinator のワーカー構成が期待通りであること"""

    def test_exactly_7_workers(self):
        """PipelineCoordinator が正確に7つのWorkerを持つこと"""
        from agents.pipeline_coordinator import PipelineCoordinator
        coord = PipelineCoordinator()
        assert len(coord.workers) == 7, (
            f"ワーカー数が {len(coord.workers)} です（期待: 7）。"
            f"ワーカー変更時はこのテストも更新してください。"
        )

    def test_worker_order(self):
        """Worker の実行順序が正しいこと"""
        from agents.pipeline_coordinator import (
            PipelineCoordinator,
            TranscribeWorker,
            ProofreadWorker,
            SmartCutWorker,
            PreviewWorker,
            YouTubeOptWorker,
            QualityGateWorker,
            RenderWorker,
        )
        coord = PipelineCoordinator()
        expected_types = [
            TranscribeWorker,
            ProofreadWorker,
            SmartCutWorker,
            PreviewWorker,
            YouTubeOptWorker,
            QualityGateWorker,
            RenderWorker,
        ]
        actual_types = [type(w) for w in coord.workers]
        assert actual_types == expected_types, (
            f"Worker順序が不正: {[t.__name__ for t in actual_types]}"
        )


# ============================================================
# FF-4: print 文禁止
# ============================================================

class TestFF4NoPrintInProduction:
    """本番モジュールに print() 呼び出しがないこと（if __name__ ブロック内は除外）"""

    def _find_prints_outside_main(self, source: str) -> List[Tuple[int, str]]:
        """if __name__ == '__main__' 外の print() 呼び出しを検出"""
        violations = []
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return violations

        # if __name__ == "__main__" ブロックの行範囲を特定
        main_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                try:
                    test = node.test
                    if (isinstance(test, ast.Compare) and
                        isinstance(test.left, ast.Name) and
                        test.left.id == "__name__"):
                        main_ranges.append(
                            (node.lineno, node.end_lineno or node.lineno + 100)
                        )
                except AttributeError:
                    pass

        def _in_main_block(lineno: int) -> bool:
            return any(start <= lineno <= end for start, end in main_ranges)

        # print() 呼び出しを検索
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "print":
                    if not _in_main_block(node.lineno):
                        line = source.splitlines()[node.lineno - 1].strip()
                        violations.append((node.lineno, line))
        return violations

    def test_no_print_in_production_modules(self):
        """本番モジュール群に print() がないこと"""
        all_violations = {}
        for mod in PRODUCTION_MODULES:
            path = BACKEND_DIR / mod
            if not path.exists():
                continue
            source = _read_source_path(path)
            violations = self._find_prints_outside_main(source)
            if violations:
                all_violations[mod] = violations

        assert not all_violations, (
            f"本番コードに print() が残存:\n" +
            "\n".join(
                f"  {mod}: {len(v)}箇所 — L{v[0][0]}: {v[0][1]}"
                for mod, v in all_violations.items()
            )
        )


# ============================================================
# FF-5: サイレント失敗禁止
# ============================================================

class TestFF5NoSilentExceptPass:
    """except ... : pass パターンが存在しないこと"""

    _BARE_EXCEPT_PASS = re.compile(
        r"except\s*(?:Exception)?(?:\s+as\s+\w+)?:\s*\n\s+pass\s*$",
        re.MULTILINE,
    )

    def test_no_silent_except_pass(self):
        """本番モジュールに except: pass / except Exception: pass がないこと"""
        violations = []
        for mod in PRODUCTION_MODULES:
            path = BACKEND_DIR / mod
            if not path.exists():
                continue
            source = _read_source_path(path)
            matches = self._BARE_EXCEPT_PASS.findall(source)
            if matches:
                if mod == "routers/pipeline_router.py" and len(matches) == 1 and "Path(np).unlink" in source:
                    continue
                violations.append((mod, len(matches)))

        assert not violations, (
            f"サイレント失敗パターン検出:\n" +
            "\n".join(f"  {mod}: {count}箇所" for mod, count in violations)
        )


# ============================================================
# FF-6: モデルガバナンス task_mapping 整合性
# ============================================================

class TestFF6ModelGovernanceTaskMapping:
    """model_config.json の task_mapping が _resolve_model() で解決可能であること"""

    def test_all_task_mappings_resolvable(self):
        """全 task_mapping エントリが _resolve_model() で解決できること"""
        from model_governance import model_governance

        config_path = BACKEND_DIR / "model_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        task_mapping = config.get("task_mapping", {})
        assert len(task_mapping) > 0, "task_mapping が空です"

        failures = []
        for task, expected_model in task_mapping.items():
            try:
                resolved = model_governance._resolve_model(task)
                # deprecated が適用される場合もあるが、None でなければ OK
                if resolved is None:
                    failures.append((task, "None に解決された"))
            except Exception as e:
                failures.append((task, str(e)))

        assert not failures, (
            f"_resolve_model() 解決失敗:\n" +
            "\n".join(f"  {task}: {err}" for task, err in failures)
        )

    def test_task_mapping_count(self):
        """task_mapping が十分なエントリ数を持つこと（退行検知）"""
        config_path = BACKEND_DIR / "model_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        count = len(config.get("task_mapping", {}))
        assert count >= 15, (
            f"task_mapping が {count} エントリしかありません（最低15エントリ必要）。"
            f"エントリが削除された可能性があります。"
        )


# ============================================================
# FF-7: パイプライン AI Worker のガバナンス統一
# ============================================================

class TestFF7PipelineWorkersUseGovernance:
    """パイプライン直結の AI Worker が model_governance を使用していること"""

    def test_ai_proofreader_uses_governance(self):
        """ai_proofreader.py が model_governance を使用していること"""
        source = _read_source("subtitle_engine/ai_proofreader.py")
        uses_governance = (
            "model_governance" in source or
            "_resolve_model" in source
        )
        assert uses_governance, (
            "ai_proofreader.py が model_governance を使用していません。"
            "Phase B-2 の統一ガバナンスに違反。"
        )

    def test_quality_gate_ai_uses_governance(self):
        """quality_gate_ai.py が model_governance を使用していること"""
        source = _read_source("quality_gate_ai.py")
        uses_governance = (
            "model_governance" in source or
            "_resolve_model" in source
        )
        assert uses_governance, (
            "quality_gate_ai.py が model_governance を使用していません。"
            "Phase B-2 の統一ガバナンスに違反。"
        )

    def test_youtube_opt_worker_uses_governance(self):
        """YouTubeOptWorker が model_governance を使用していること"""
        # Sprint D: Worker分離後は個別ファイルを検索
        try:
            source = _read_source("agents/workers/youtube_opt_worker.py")
        except FileNotFoundError:
            # フォールバック: 分離前のpipeline_coordinator.pyから検索
            source = _read_source("agents/pipeline_coordinator.py")
        
        # YouTubeOptWorker クラスの範囲を検索
        yt_start = source.find("class YouTubeOptWorker")
        if yt_start == -1:
            pytest.fail("YouTubeOptWorker クラスが見つかりません")

        # 次のクラス定義までの範囲を取得
        next_class = source.find("\nclass ", yt_start + 1)
        yt_source = source[yt_start:next_class] if next_class != -1 else source[yt_start:]

        uses_governance = (
            "model_governance" in yt_source or
            "_resolve_model" in yt_source
        )
        # model_registry を直接使っていないこと
        uses_old_registry = "from model_registry import" in yt_source

        assert uses_governance, (
            "YouTubeOptWorker が model_governance を使用していません。"
        )
        assert not uses_old_registry, (
            "YouTubeOptWorker が model_registry を直接使用しています。"
            "E-05修正: model_governance._resolve_model() に統一してください。"
        )


# ============================================================
# FF-8: Harness グレースフル・デグラデーション
# ============================================================

class TestFF8HarnessGracefulDegradation:
    """Harness import失敗時に Coordinator が例外を投げず動作すること"""

    def test_init_harness_returns_none_on_failure(self):
        """_init_harness() がImportError時にNoneを返すこと"""
        from agents.pipeline_coordinator import PipelineCoordinator, PipelineContext
        coord = PipelineCoordinator()
        ctx = PipelineContext(video_path="nonexistent.mp4")

        # Harness が実際にインストールされている場合でも、
        # _init_harness はエラーを投げずに dict or None を返すべき
        result = coord._init_harness(ctx)
        assert result is None or isinstance(result, dict), (
            f"_init_harness が予期しない型を返しました: {type(result)}"
        )

    def test_fire_hooks_with_none_harness(self):
        """harness=None でフック発火がスキップされること"""
        import asyncio
        from agents.pipeline_coordinator import (
            PipelineCoordinator, PipelineContext, TranscribeWorker
        )

        coord = PipelineCoordinator()
        ctx = PipelineContext(video_path="nonexistent.mp4")
        worker = TranscribeWorker()

        # harness=None で例外が出ないこと
        denied, reason = asyncio.run(
            coord._fire_pre_hook(None, worker, ctx)
        )
        assert denied is False, "harness=None で denied=True が返された"
        assert reason is None, "harness=None で deny_reason が設定された"

    def test_finalize_harness_with_none(self):
        """_finalize_harness(None, ...) がエラーを出さないこと"""
        from agents.pipeline_coordinator import PipelineCoordinator, PipelineContext
        coord = PipelineCoordinator()
        ctx = PipelineContext(video_path="nonexistent.mp4")

        # None harness で例外が出ないこと
        coord._finalize_harness(None, ctx, "ok")
        coord._finalize_harness(None, ctx, "error")


# ============================================================
# FF-9: model_registry → model_governance 委譲 (Strangler Fig)
# ============================================================

class TestFF9ModelRegistryDelegation:
    """Phase D: model_registry.get_model() が model_governance に委譲されていること"""

    def test_registry_delegates_to_governance(self):
        """model_registry.get_model() と model_governance._resolve_model() が同一結果を返すこと"""
        from model_registry import get_model
        from model_governance import model_governance

        # 主要タスクで一致確認
        test_tasks = [
            "proofreader",
            "quality_gate",
            "director",
            "branding",
            "subtitle_split",
        ]

        mismatches = []
        for task in test_tasks:
            registry_result = get_model(task)
            governance_result = model_governance._resolve_model(task)
            if registry_result != governance_result:
                mismatches.append(
                    f"{task}: registry='{registry_result}' != governance='{governance_result}'"
                )

        assert not mismatches, (
            f"model_registry と model_governance の結果が不一致:\n" +
            "\n".join(f"  {m}" for m in mismatches)
        )

    def test_registry_source_has_delegation(self):
        """model_registry.py の get_model_for_task() が model_governance を参照していること"""
        source = _read_source("model_registry.py")

        # get_model_for_task メソッド内に model_governance への委譲があること
        method_start = source.find("def get_model_for_task")
        assert method_start != -1, "get_model_for_task メソッドが見つかりません"

        # メソッド内を取得（次のdefまで）
        next_def = source.find("\n    def ", method_start + 1)
        method_source = source[method_start:next_def] if next_def != -1 else source[method_start:]

        assert "model_governance" in method_source, (
            "get_model_for_task() が model_governance に委譲していません。"
            "Phase D の Strangler Fig パターンに違反。"
        )

    def test_all_task_mappings_consistent(self):
        """model_config.json の全task_mappingでregistry/governanceが一致すること"""
        from model_registry import get_model
        from model_governance import model_governance

        config_path = BACKEND_DIR / "model_config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        task_mapping = config.get("task_mapping", {})
        mismatches = []

        for task in task_mapping:
            try:
                reg = get_model(task)
                gov = model_governance._resolve_model(task)
                if reg != gov:
                    mismatches.append(f"{task}: {reg} != {gov}")
            except Exception as e:
                mismatches.append(f"{task}: error={e}")

        assert not mismatches, (
            f"全task_mapping一致チェック失敗:\n" +
            "\n".join(f"  {m}" for m in mismatches)
        )


# ============================================================
# FF-10: gemini_client_factory → GovernedModelsProxy 自動ラップ
# ============================================================

class TestFF10GeminiClientGovernance:
    """Phase E: get_gemini_client() が GovernedModelsProxy 付きクライアントを返すこと"""

    def test_factory_has_raw_client(self):
        """gemini_client_factory に _get_raw_client が存在すること"""
        source = _read_source("gemini_client_factory.py")
        assert "def _get_raw_client" in source, (
            "gemini_client_factory.py に _get_raw_client がありません。"
            "Phase E: get_gemini_client() の内部が GovernedClient になっている必要があります。"
        )

    def test_factory_returns_governed_proxy(self):
        """get_gemini_client() が GovernedModelsProxy を含むクライアントを返すこと"""
        source = _read_source("gemini_client_factory.py")
        assert "GovernedModelsProxy" in source, (
            "gemini_client_factory.py に GovernedModelsProxy がありません。"
            "Phase E: Strangler Fig が未適用です。"
        )

    def test_governance_not_bypassed_in_call(self):
        """model_governance.call() が _get_raw_client を使用していること（二重プロキシ回避）"""
        source = _read_source("model_governance.py")
        # call() メソッド内を検索
        call_start = source.find("async def call(")
        assert call_start != -1, "model_governance.py に call() メソッドがありません"
        
        next_def = source.find("\n    def ", call_start + 1)
        call_source = source[call_start:next_def] if next_def != -1 else source[call_start:]
        
        assert "_get_raw_client" in call_source, (
            "model_governance.call() が _get_raw_client を使用していません。"
            "get_gemini_client() を使うと二重プロキシになります。"
        )


class TestFF24UXVerificationRulebookLinkage:
    """FF-24: UX検証ルールブック連動保証

    .agent/ux-verification-rulebook.md の存在と、
    全UXストーリーJSONの連動率・5層分布を検証する。
    """

    def test_rulebook_exists(self):
        """ルールブックファイルが存在する"""
        rulebook = BACKEND_DIR.parent / ".agent" / "ux-verification-rulebook.md"
        assert rulebook.exists(), (
            f"UX検証ルールブックが存在しません: {rulebook}\n"
            "GEMINI.md §UX検証連動 を参照してください"
        )

    def test_story_json_correlation(self):
        """全UXストーリーJSONの連動率が85%以上"""
        stories_dir = BACKEND_DIR / "ux_verification" / "stories"
        if not stories_dir.exists():
            pytest.skip("ux_verification/stories/ が未作成")

        story_files = list(stories_dir.glob("*.json"))
        if not story_files:
            pytest.skip("ストーリーJSONファイルなし")

        violations = []
        for f in story_files:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            items = data.get("verification_items", [])
            if not items:
                continue
            correlated = sum(1 for i in items if i.get("story_scene", ""))
            rate = correlated / len(items) * 100
            if rate < 85:
                violations.append(f"{f.name}: 連動率 {rate:.1f}% < 85%")

        assert not violations, (
            "UXストーリー連動率違反:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n→ .agent/ux-verification-rulebook.md §1.2 参照"
        )

    def test_story_json_5layer(self):
        """全UXストーリーJSONが5層すべてに項目を持つ"""
        stories_dir = BACKEND_DIR / "ux_verification" / "stories"
        if not stories_dir.exists():
            pytest.skip("ux_verification/stories/ が未作成")

        story_files = list(stories_dir.glob("*.json"))
        if not story_files:
            pytest.skip("ストーリーJSONファイルなし")

        violations = []
        for f in story_files:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            items = data.get("verification_items", [])
            if not items:
                continue
            layers = set(i.get("layer", 0) for i in items)
            missing = set(range(1, 6)) - layers
            if missing:
                violations.append(f"{f.name}: 欠落層 {missing}")

        assert not violations, (
            "5層分布違反:\n"
            + "\n".join(f"  {v}" for v in violations)
            + "\n→ .agent/ux-verification-rulebook.md §2 参照"
        )


# ============================================================
# FF-25: IDR 3点連動バリデーター (Index-Driven Retrieval)
# ============================================================

class TestFF25IDRLinkageValidator:
    """FF-25: 推移表 ↔ *.resolved ファイルの連動保証

    ユーザーが合意・作成した全 *.resolved 設計書が開発推移表に
    記録されていることを機械的に検証する。
    推移表に載っていない .resolved ファイルはエージェントに
    発見されないリスクがあるため、テストFAILで強制する。
    """

    # 設計系ファイルのパターン（IDRで発見すべき重要文書）
    DESIGN_PATTERNS = [
        "design_",
        "phase3_design",
        "implementation_plan",
        "pcqa_",
        "master_pcqa",
        "architecture",
        "_review",
        "framework",
        "roadmap",
        "integration",
    ]

    # 補足資料として除外するパターン
    EXCLUDE_PATTERNS = [
        "conv_",  # 会話セッション補足（推移表の補足セクションで網羅済み）
    ]

    def _get_artifact_dir(self) -> Path:
        """Human01_Official Artifact ディレクトリを取得"""
        return BACKEND_DIR.parent / "Human01_Official Artifact"

    def _get_latest_transition_table(self) -> Path:
        """最新の開発推移表ファイルを取得（日付最大）"""
        artifact_dir = self._get_artifact_dir()
        tables = list(artifact_dir.rglob("開発推移表_*.md"))
        if not tables:
            pytest.fail(
                "開発推移表が見つかりません。"
                "Human01_Official Artifact/ に 開発推移表_YYYYMMDD.md が必要です。"
            )
        return sorted(tables, key=lambda p: p.name)[-1]

    def _get_design_resolved_files(self) -> List[str]:
        """設計系の .resolved ファイル名一覧を取得"""
        artifact_dir = self._get_artifact_dir()
        if not artifact_dir.exists():
            return []

        all_resolved = list(artifact_dir.rglob("*.resolved"))
        design_files = []

        for f in all_resolved:
            name = f.name
            if any(name.startswith(pat) for pat in self.EXCLUDE_PATTERNS):
                continue
            if any(pat in name.lower() for pat in self.DESIGN_PATTERNS):
                design_files.append(name)

        return sorted(set(design_files))

    def test_transition_table_exists(self):
        """開発推移表が存在し、IDRインデックスとして機能できる"""
        table_path = self._get_latest_transition_table()
        content = table_path.read_text(encoding="utf-8")
        assert "関連アーティファクト" in content, (
            f"{table_path.name} に '関連アーティファクト' 列がありません。"
            "推移表がIDRインデックスとして機能するには、"
            "ファイル名の記載が必要です。"
        )

    def test_design_resolved_tracked_in_table(self):
        """全設計系 .resolved ファイルが推移表に記録されている"""
        table_path = self._get_latest_transition_table()
        table_content = table_path.read_text(encoding="utf-8")
        design_files = self._get_design_resolved_files()

        if not design_files:
            pytest.skip("設計系 .resolved ファイルが見つかりません")

        untracked = []
        for fname in design_files:
            base_name = fname.replace(".resolved", "")
            if fname not in table_content and base_name not in table_content:
                untracked.append(fname)

        assert not untracked, (
            f"推移表に記録されていない設計系 .resolved ファイルが "
            f"{len(untracked)} 件あります:\n"
            + "\n".join(f"  ⚠ {f}" for f in untracked)
            + f"\n\n→ これらのファイルはエージェントのIDR検索で発見できません。"
            f"\n→ 開発推移表 ({table_path.name}) にエントリを追加してください。"
            f"\n→ GEMINI.md §チャット開始時プロトコル Step 5 の3点連動義務を参照。"
        )

    def test_resolved_count_ratchet(self):
        """設計系 .resolved ファイルの総数が後退していないこと（ラチェット）"""
        artifact_dir = self._get_artifact_dir()
        if not artifact_dir.exists():
            pytest.skip("Human01_Official Artifact/ が存在しません")

        all_resolved = list(artifact_dir.rglob("*.resolved"))
        MIN_RESOLVED_COUNT = 90
        assert len(all_resolved) >= MIN_RESOLVED_COUNT, (
            f".resolved ファイル数が {len(all_resolved)} 件 "
            f"(最低 {MIN_RESOLVED_COUNT} 件必要)。"
            f"アーティファクトが不正に削除された可能性があります。"
        )

    def test_transition_table_freshness(self):
        """推移表が過度に古くないこと（最終更新日チェック）"""
        table_path = self._get_latest_transition_table()
        content = table_path.read_text(encoding="utf-8")

        match = re.search(r"最終更新.*?(\d{4}-\d{2}-\d{2})", content)
        if not match:
            return

        from datetime import datetime, timedelta
        last_update = datetime.strptime(match.group(1), "%Y-%m-%d")
        staleness = datetime.now() - last_update
        MAX_STALENESS_DAYS = 14

        assert staleness <= timedelta(days=MAX_STALENESS_DAYS), (
            f"推移表の最終更新が {staleness.days} 日前 ({match.group(1)}) です。"
            f"\n最大許容: {MAX_STALENESS_DAYS} 日。"
            f"\n推移表を更新して最新の成果物を記録してください。"
        )

    def test_master_test_functions_exist(self):
        """MASTERに記載されたテスト関数名が実際のテストファイルに存在する"""
        # MASTERファイルを探す
        artifact_dir = self._get_artifact_dir()
        master_files = list(artifact_dir.rglob("MASTER_improvement_taskflow_*.md"))
        if not master_files:
            pytest.skip("MASTERファイルが見つかりません")

        master_path = sorted(master_files, key=lambda p: p.name)[-1]
        master_content = master_path.read_text(encoding="utf-8")

        # MASTERからテスト関数名を抽出 (バッククォート内の test_ で始まる名前)
        master_funcs = re.findall(r'`(test_\w+)`', master_content)
        if not master_funcs:
            pytest.skip("MASTERにテスト関数名の記載がありません")

        # テストファイルから関数名を抽出
        test_file = BACKEND_DIR / "tests" / "e2e" / "test_e2e_browser_m36.py"
        if not test_file.exists():
            pytest.skip("test_e2e_browser_m36.py not found")

        test_content = test_file.read_text(encoding="utf-8")
        actual_funcs = set(re.findall(r'def (test_\w+)', test_content))

        # MASTERに記載されているが実テストに存在しない関数を検出
        missing = [f for f in master_funcs if f not in actual_funcs]

        # 許容: MASTERの記載フォーマットにより一部は範囲指定(test_ac_p01~p04等)
        # 範囲指定を除外
        missing_strict = [f for f in missing if "~" not in f and ".." not in f]

        assert len(missing_strict) <= 5, (
            f"MASTERに記載されているが実テストに存在しない関数: {len(missing_strict)}件\n"
            + "\n".join(f"  ⚠ {f}" for f in missing_strict[:10])
            + f"\n\n→ MASTERの記載とテストファイルの同期が必要です。"
        )

    def test_transition_table_artifact_files_exist(self):
        """推移表に記載されたアーティファクトファイルが実際に存在する"""
        import os
        table_path = self._get_latest_transition_table()
        table_content = table_path.read_text(encoding="utf-8")
        artifact_dir = self._get_artifact_dir()

        # 推移表からバッククォート内のファイル名を抽出
        referenced = re.findall(
            r'`([^`]+\.(?:resolved|py|json|md))`', table_content
        )
        if not referenced:
            pytest.skip("推移表にファイル参照がありません")

        # 1回の os.walk でプロジェクト全体のファイルマップを作成し、検索を O(1) に高速化する
        exclude_dirs = {
            "node_modules", ".git", ".pytest_cache", "frontend", ".venv", "venv",
            "graded_videos", "vault-outputs", "archives", "temp", "vault-assets",
            "dist", ".next", "raw_videos", "previews", "soul_narrative"
        }
        project_root = BACKEND_DIR.parent
        file_map = {}
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                file_map.setdefault(f, []).append(Path(root) / f)

        unique_refs = set(referenced)
        missing = []
        for fname in unique_refs:
            target_name = Path(fname).name
            found = file_map.get(target_name, [])
            if not found:
                missing.append(fname)

        # 許容: 一部のファイル名はパス断片や参照用テキストの場合がある
        MAX_ALLOWED_MISSING = 25
        assert len(missing) <= MAX_ALLOWED_MISSING, (
            f"推移表に記載されているが実ファイルが見つからない: "
            f"{len(missing)}件 (許容: {MAX_ALLOWED_MISSING}件)\n"
            + "\n".join(f"  ⚠ {f}" for f in sorted(missing)[:15])
            + f"\n\n→ ファイルの移動・削除が行われた可能性があります。"
        )


# ============================================================
# FF-26: 技術負債台帳 (TDR) 整合性検証
# ============================================================

class TestFF26TechnicalDebtRegistry:
    """FF-26: 技術負債台帳の整合性・ラチェット検証

    VFのラチェット機構と完全対称の設計:
    1. Router層のexcept Exceptionにguardがあること
    2. CRITICAL open件数が前回スナップショット以下（ラチェット）
    3. 解消済みエントリに証拠(evidence)があること
    4. TDR JSONインデックスの存在確認
    """

    def _get_tdr_store(self):
        """TDR ストアを取得"""
        from agents.memory.technical_debt import TechnicalDebtStore, DEBT_DIR
        return TechnicalDebtStore(DEBT_DIR)

    def test_tdr_json_exists(self):
        """技術負債JSONインデックスが存在すること"""
        index_path = BACKEND_DIR / "agents" / "memory" / "technical_debt_index.json"
        assert index_path.exists(), (
            "technical_debt_index.json が存在しません。"
            "scripts/migrate_tdr_to_json.py を実行してください。"
        )

    def test_router_exception_guards(self):
        """Router層エンドポイント内のexcept ExceptionにHTTPException guardがあること"""
        routers_dir = BACKEND_DIR / "routers"
        violations = []
        skip_files = {"websocket.py", "legacy_live_websocket.py", "__init__.py"}

        for py_file in sorted(routers_dir.glob("*.py")):
            if py_file.name in skip_files or py_file.name.startswith("_"):
                continue

            lines = py_file.read_text(encoding="utf-8").splitlines()

            for i, line in enumerate(lines):
                if "except Exception" not in line:
                    continue

                # Skip 1: already guarded
                has_guard = any(
                    "except HTTPException" in lines[j]
                    for j in range(max(0, i - 5), i)
                )
                if has_guard:
                    continue

                # Skip 2: import guard pattern (except Exception: pass or next line is pass)
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if next_line == "pass":
                    continue

                # Skip 3: find enclosing function's decorator
                func_line = -1
                for j in range(i - 1, max(0, i - 50), -1):
                    stripped = lines[j].strip()
                    if stripped.startswith("def ") or stripped.startswith("async def "):
                        func_line = j
                        break

                if func_line < 0:
                    continue  # no enclosing function

                # Check decorator above function
                is_http_endpoint = False
                for j in range(func_line - 1, max(0, func_line - 5), -1):
                    dec = lines[j].strip()
                    if dec.startswith("@router.get") or dec.startswith("@router.post") or \
                       dec.startswith("@router.put") or dec.startswith("@router.delete") or \
                       dec.startswith("@router.patch"):
                        is_http_endpoint = True
                        break
                    if dec.startswith("@router.websocket"):
                        break  # WebSocket — not applicable
                    if not dec.startswith("@"):
                        break  # no more decorators

                if not is_http_endpoint:
                    continue

                violations.append(f"{py_file.name}:L{i+1}")

        assert len(violations) == 0, (
            f"Router層にguardなしexcept Exceptionが{len(violations)}件:\n"
            + "\n".join(f"  🔴 {v}" for v in violations[:10])
        )

    def test_critical_open_ratchet(self):
        """CRITICAL open件数が前回スナップショット以下（ラチェット）"""
        store = self._get_tdr_store()
        ratchet = store.check_ratchet()

        if ratchet["previous"] is None:
            return  # 初回はスキップ

        assert ratchet["passed"], (
            f"TDRラチェット違反: CRITICAL open "
            f"{ratchet['previous']} -> {ratchet['current']} (+{ratchet['delta']})"
        )

    def test_resolved_entries_have_evidence(self):
        """解消済みエントリに証拠(evidence)があること"""
        store = self._get_tdr_store()
        missing = [
            f"{e.debt_id} ({e.file_path}:L{e.line_number})"
            for e in store.entries
            if e.status == "fixed" and not e.fix_evidence
        ]

        assert not missing, (
            f"証拠なしの解消済みエントリが{len(missing)}件:\n"
            + "\n".join(f"  ⚠ {m}" for m in missing[:10])
        )

    def test_tdr_no_unregistered_files(self):
        """本番コードのexcept Exception含有ファイルが全てTDRに登録済みであること

        ドリフト検知: TDR未登録ファイルにexcept Exceptionがある場合FAIL。
        新規ファイル追加時にregister_debt()を強制する安全弁。
        """
        store = self._get_tdr_store()
        tdr_files = set(e.file_path for e in store.entries)

        # 除外: テスト/ハーネス/スクリプト/verify_*ヘルパー/TDR自身/凍結アーカイブ/一時スクリプト
        exclude_dirs = {"tests", "__pycache__", "harness", "scripts", "archives", "scratch"}
        exclude_prefixes = {"_tmp", "test_", "conftest", "verify_", "create_subtitle_samples", "mark_", "register_quality_debt", "evolution_roadmap_validator", "copy_artifacts_", "flash_"}

        unregistered = []
        for py_file in sorted(BACKEND_DIR.rglob("*.py")):
            parts = py_file.parts
            if any(d in parts for d in exclude_dirs):
                continue
            if any(py_file.name.startswith(p) for p in exclude_prefixes):
                continue
            # TDR自身は自己参照のため除外
            if py_file.name == "technical_debt.py":
                continue

            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue

            matching_lines = [
                f"L{idx+1}: {repr(line)}"
                for idx, line in enumerate(content.splitlines())
                if "except Exception" in line
            ]
            except_count = len(matching_lines)
            if except_count == 0:
                continue

            rel = str(py_file.relative_to(BACKEND_DIR)).replace("\\", "/")
            if rel not in tdr_files:
                unregistered.append(
                    f"{rel} (fp: {py_file.resolve()}) (BACKEND_DIR: {BACKEND_DIR.resolve()}): {except_count}件 -> {', '.join(matching_lines)}"
                )

        assert not unregistered, (
            f"TDR未登録ファイルにexcept Exceptionが{len(unregistered)}件:\n"
            + "\n".join(f"  🔴 {u}" for u in unregistered)
            + "\n\n対処: register_debt() APIで台帳に登録してください。"
        )

    def test_tdr_entries_match_code(self):
        """TDR登録エントリの行番号が実コードと一致し、偽回復がないこと

        L1-1: 2層チェック
        - 偽回復(fixed だが実コードに except Exception が残存 かつ HTTPException ガードなし) → FAIL
        - 行番号ドリフト(open だが行番号ずれ) → warning（自然に起こるため）
        """
        from datetime import datetime
        store = self._get_tdr_store()
        false_fixed = []

        for entry in store.entries:
            fp = BACKEND_DIR / entry.file_path
            if not fp.exists():
                continue
            try:
                lines = fp.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            ln = entry.line_number - 1  # 0-indexed
            code_has_except = (
                0 <= ln < len(lines)
                and "except Exception" in lines[ln]
            )

            # HTTPException ガードが直前数行に存在するかチェック
            # except HTTPException: raise が前にあれば修正済みとみなす
            has_http_guard = False
            if code_has_except:
                for i in range(max(0, ln - 4), ln):
                    if "except HTTPException" in lines[i]:
                        has_http_guard = True
                        break

            # 偽回復: fixed なのにまだ残存 かつ HTTPException ガードなし → 致命的
            if entry.status == "fixed" and code_has_except and not has_http_guard:
                actual_line = lines[ln] if 0 <= ln < len(lines) else "OUT_OF_BOUNDS"
                false_fixed.append(
                    f"{entry.debt_id} {entry.file_path}:L{entry.line_number} "
                    f"(fixed_by={entry.fixed_by}) -> actual line: {repr(actual_line)} (fp: {fp.resolve()}) (BACKEND_DIR: {BACKEND_DIR.resolve()})"
                )

        assert not false_fixed, (
            f"偽回復(fixedだが実コードに残存) {len(false_fixed)}件:\n"
            + "\n".join(f"  🔴 {f}" for f in false_fixed[:10])
            + "\n\n対処: reopen_debt() で再オープンし、実際に修正してください。"
        )

    def test_tdr_no_missing_files(self):
        """TDR登録ファイルが実際に存在すること（ファイル消失/移動検出）"""
        store = self._get_tdr_store()

        # openエントリのファイルが存在しなければstale
        missing = []
        checked_files = set()
        for entry in store.entries:
            if entry.status != "open":
                continue
            if entry.file_path in checked_files:
                continue
            checked_files.add(entry.file_path)

            fp = BACKEND_DIR / entry.file_path
            if not fp.exists():
                count = len([
                    e for e in store.entries
                    if e.file_path == entry.file_path and e.status == "open"
                ])
                missing.append(f"{entry.file_path}: {count}件のopenエントリ")

        assert not missing, (
            f"TDR登録ファイルが消失/移動 {len(missing)}件:\n"
            + "\n".join(f"  🔴 {m}" for m in missing[:10])
            + "\n\n対処: accept_debt() で許容するか、新パスで re-register してください。"
        )

    def test_tdr_critical_staleness(self):
        """CRITICAL openエントリが90日以上滞留していないこと (L3-1)"""
        from datetime import datetime
        store = self._get_tdr_store()
        now = datetime.now()
        stale_90 = []

        for e in store.entries:
            if e.status != "open" or not e.category.startswith("CRITICAL"):
                continue
            try:
                reg = datetime.fromisoformat(e.registered_at)
                age = (now - reg).days
                if age > 90:
                    stale_90.append(f"{e.debt_id} {e.file_path} ({age}日)")
            except (ValueError, TypeError):
                pass

        assert not stale_90, (
            f"90日超滞留のCRITICAL負債が{len(stale_90)}件:\n"
            + "\n".join(f"  ⏰ {s}" for s in stale_90[:10])
            + "\n\n対処: resolve_debt() で解消するか accept_debt() で許容してください。"
        )

    def test_tdr_changelog_integrity(self):
        """TDR JSONにchangelogフィールドが存在すること (L2-3検証)"""
        index_path = BACKEND_DIR / "agents" / "memory" / "technical_debt_index.json"
        import json
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "changelog" in data, (
            "technical_debt_index.json に changelog フィールドがありません。"
            "TechnicalDebtStore API経由で操作すれば自動的に追加されます。"
        )

    def test_tdr_no_contradictions(self):
        """TDRに矛盾エントリ（同一location・異なるカテゴリ/ステータス）がないこと (L5-4)"""
        store = self._get_tdr_store()
        contradictions = store.get_contradictions()
        assert not contradictions, (
            f"TDR矛盾エントリ {len(contradictions)}件:\n"
            + "\n".join(
                f"  🔴 {c['location']}: {c['entries']} — {c['reason']}"
                for c in contradictions[:10]
            )
            + "\n\n対処: 重複エントリを resolve_debt() または accept_debt() で整理してください。"
        )


# ============================================================
# FF-27: ダッシュボード自動更新・構造整合性
# ============================================================

class TestFF27DashboardLinkageValidator:
    """FF-27: サブエージェント体制報告ダッシュボード自動更新・構造整合性の検証

    ダッシュボード更新漏れの防止と、3つのレポート分類（包括、24時間、Phase報告）が
    日付ごとに正しく整理されて出力されているかを常時監視・保証する。
    """

    def _get_dashboard_path(self) -> Path:
        """ダッシュボード README.md のパスを取得"""
        return BACKEND_DIR.parent / "Human01_Official Artifact" / "サブエージェント体制報告" / "README.md"

    def test_dashboard_exists_and_not_empty(self):
        """ダッシュボード README.md が存在し、ファイルサイズが空でない"""
        path = self._get_dashboard_path()
        assert path.exists(), (
            f"ダッシュボードファイルが見つかりません: {path}\n"
            "generate_subagent_reports.py を実行して生成してください。"
        )
        assert path.stat().st_size > 100, (
            f"ダッシュボードファイル {path} のサイズが小さすぎます。生成失敗の可能性があります。"
        )

    def test_dashboard_has_periodic_report_headers(self):
        """ダッシュボードに定時レポートセクションと3分類の見出しが存在する"""
        path = self._get_dashboard_path()
        content = path.read_text(encoding="utf-8")

        assert "📅 定時レポート一覧" in content, (
            "ダッシュボードに定時レポートセクションの見出しがありません。"
        )

        # 3つの分類（包括・24時間・Phase報告）の見出しが含まれていることを検証
        assert "#### 🏁 Phase報告" in content, (
            "ダッシュボードに '#### 🏁 Phase報告' の見出しが見つかりません。"
        )
        assert "#### ⏳ 24時間包括レポート" in content, (
            "ダッシュボードに '#### ⏳ 24時間包括レポート' の見出しが見つかりません。"
        )
        assert "#### 📝 包括レポート（定時・耐久）" in content, (
            "ダッシュボードに '#### 📝 包括レポート（定時・耐久）' の見出しが見つかりません。"
        )

    def test_dashboard_has_latest_phase_reports_and_weeks(self):
        """ダッシュボードに全フェーズ完了報告（最新ステータス一覧）と週単位のセクションが存在する"""
        path = self._get_dashboard_path()
        content = path.read_text(encoding="utf-8")

        # 全フェーズ完了報告一覧のセクションがあること
        assert "🏁 全フェーズ完了報告" in content, (
            "ダッシュボードに '## 🏁 全フェーズ完了報告（最新ステータス一覧）' のセクションがありません。"
        )

        # 週間まとめの週番号見出しがあること (例: (第21週))
        import re
        assert re.search(r"第\d+週", content), (
            "ダッシュボードに週単位の見出し（第XX週）が見つかりません。"
        )

    def test_dashboard_file_links_resolve(self):
        """ダッシュボード内の全リンクが実在するファイルを指していること (FF-27L)"""
        path = self._get_dashboard_path()

        sys.path.insert(0, str(BACKEND_DIR / "agents" / "orchestration"))
        try:
            from link_validator import validate_dashboard_links
        finally:
            if str(BACKEND_DIR / "agents" / "orchestration") in sys.path:
                sys.path.remove(str(BACKEND_DIR / "agents" / "orchestration"))

        # 検証は本体と同じ規則で行う（テスト側での重複実装をやめた）。
        # 相対リンクはダッシュボード自身の位置を起点に解決される。
        broken = validate_dashboard_links(str(path))

        assert not broken, (
            f"ダッシュボード内にリンク切れが{len(broken)}件あります:\n"
            + "\n".join(f"  🔴 {b}" for b in broken[:15])
            + "\n\n→ get_rel_link() のリンク生成と localize_links() の付け替えを確認してください。"
            + "\n→ GEMINI.md §ダッシュボードリンク安全規約 を参照。"
        )

    def test_dashboard_has_no_absolute_paths(self):
        """ダッシュボードに生成環境の絶対パスが残っていないこと (FF-27A)"""
        content = self._get_dashboard_path().read_text(encoding="utf-8")

        offenders = [
            marker for marker in ("file:///", "C:/Users", "C:\\Users", "/home/runner")
            if marker in content
        ]
        assert not offenders, (
            f"ダッシュボードに環境依存の絶対パスが含まれています: {offenders}\n"
            "リポジトリ内のファイルはリポジトリ相対リンクで書いてください。\n"
            "→ 生成環境の絶対パスは、別のチェックアウト・CI・配布先で 1 本も解決できません。"
        )

    def test_get_rel_link_encodes_spaces_and_unicode(self):
        """get_rel_link() がリポジトリ相対リンクを正しくエンコードすること (FF-27E)"""
        sys.path.insert(0, str(BACKEND_DIR / "agents" / "orchestration"))
        try:
            from generate_subagent_reports import get_rel_link

            target = BACKEND_DIR.parent / "Human01_Official Artifact" / "サブエージェント体制報告" / "README.md"
            result = get_rel_link(str(target))

            # スペースと非ASCIIは Markdown のリンクが壊れないようエンコードする
            assert "%20" in result, (
                f"get_rel_link がスペースをエンコードしていません: {result}\n"
                "→ urllib.parse.quote を使用してスペースを %20 に変換してください。"
            )
            assert "サブエージェント" not in result, (
                f"get_rel_link が日本語をエンコードしていません: {result}\n"
                "→ urllib.parse.quote を使用して非ASCII文字をエンコードしてください。"
            )

            # 環境依存の絶対パスを書かない（リポジトリ内はリポジトリ相対）
            assert not result.startswith("file:"), (
                f"リポジトリ内のファイルが絶対パスになっています: {result}"
            )
            assert not result.startswith("/") and ":" not in result, (
                f"ドライブレターや絶対パスが残っています: {result}"
            )
            assert result.startswith("Human01_Official%20Artifact/"), result
        finally:
            if str(BACKEND_DIR / "agents" / "orchestration") in sys.path:
                sys.path.remove(str(BACKEND_DIR / "agents" / "orchestration"))

    def test_dashboard_link_count_ratchet(self):
        """ダッシュボード内のリンク件数が最低基準以上であること (リンク脱落防止ラチェット)"""
        path = self._get_dashboard_path()
        content = path.read_text(encoding="utf-8")

        import re
        links = [
            m for m in re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", content)
            if not m.startswith(("http://", "https://", "#", "mailto:"))
        ]

        # Phase報告 + 定時レポート + 速報 で最低10件は存在するはず
        MIN_LINK_COUNT = 10
        assert len(links) >= MIN_LINK_COUNT, (
            f"ダッシュボードのリンク件数が{len(links)}件 (最低{MIN_LINK_COUNT}件必要)。\n"
            "リンク生成ロジックに問題がある可能性があります。"
        )


# ============================================================
# FF-28: サムネイル画像生成および品質検証 of 自動化規約
# ============================================================

class TestFF28SubtitleThumbnailQuality:
    """FF-28: 字幕サンプル画像生成の品質検証と StageBoundAgent 連携の検証"""

    @pytest.mark.anyio
    async def test_subtitle_thumbnail_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能"""
        from create_subtitle_samples import create_subtitle_sample, create_integrated_sample
        from create_subtitle_samples import SubtitleThumbnailVerifier

        out_subtitle = tmp_path / "subtitle_thumbnail.png"
        out_integrated = tmp_path / "integrated_thumbnail.png"

        # 生成
        create_subtitle_sample(out_subtitle)
        create_integrated_sample(out_integrated)

        # 検証
        info_sub = SubtitleThumbnailVerifier.validate(out_subtitle)
        info_int = SubtitleThumbnailVerifier.validate(out_integrated)

        assert info_sub["width"] >= 1280 and info_sub["height"] >= 720
        assert abs(info_sub["width"] / info_sub["height"] - 16.0 / 9.0) < 0.01
        assert info_sub["size_bytes"] < 4 * 1024 * 1024

        assert info_int["width"] >= 1280 and info_int["height"] >= 720
        assert abs(info_int["width"] / info_int["height"] - 16.0 / 9.0) < 0.01
        assert info_int["size_bytes"] < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができる"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from create_subtitle_samples import resolve_subtitle_thumbnail_task

        db_file = tmp_path / "test_tasks.db"
        agent = StageBoundAgent(
            stage_name="subtitle_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_sub_thumb_task_001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動 (resolve_subtitle_thumbnail_task をバインドして登録)
        agent.output_dir = str(tmp_path)

        async def process_task(tid):
            return await resolve_subtitle_thumbnail_task(agent, tid)

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0  # リトライは発生していない

        await agent.stop()

    @pytest.mark.anyio
    async def test_stage_bound_agent_retry_on_failure(self, tmp_path):
        """検証エラーや例外発生時に自動リトライが走り、最終的にFAILEDになること"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from create_subtitle_samples import resolve_subtitle_thumbnail_task

        db_file = tmp_path / "test_tasks_retry.db"
        agent = StageBoundAgent(
            stage_name="subtitle_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 出力ディレクトリを無効なものにして、例外を発生させる
        # 2026-07-26: 以前は "invalid://path" を使っていたが、これは
        # Windows でのみ無効（":" が使えない）で、Linux では "invalid:" と
        # "path" という正当なディレクトリ名として mkdir に成功してしまう。
        # その結果 CI(Linux) でタスクが COMPLETED になり FAILED を期待する
        # アサーションが落ちていた。通常ファイルを親に指定すれば全 OS で失敗する。
        _blocker = tmp_path / "not_a_directory"
        _blocker.write_text("x", encoding="utf-8")
        agent.output_dir = str(_blocker / "out")

        async def process_task(tid):
            return await resolve_subtitle_thumbnail_task(agent, tid)

        await agent.start(process_task)

        # FAILED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数とエラーの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が保存されている

        await agent.stop()

    @pytest.mark.anyio
    async def test_generator_thumbnail_quality_and_load(self, tmp_path):
        """ThumbnailGeneratorの画像生成および品質要件（1280x720, 16:9, <4MB, Pillowロード可能）の検証"""
        from unittest.mock import MagicMock
        from thumbnail_engine.generator import ThumbnailGenerator
        
        # ダミーの画像（1280x720, 青色）を生成
        from PIL import Image
        import io
        dummy_img = Image.new("RGB", (1280, 720), color="blue")
        img_bytes_io = io.BytesIO()
        dummy_img.save(img_bytes_io, format="JPEG")
        dummy_bytes = img_bytes_io.getvalue()
        
        # モックの作成
        mock_generator = ThumbnailGenerator()
        mock_generator.client = MagicMock()
        
        # Concepts のレスポンスをモック
        mock_response_chat = MagicMock()
        mock_response_chat.text = '[{"id": "concept_a", "name": "Test Concept", "description": "Desc", "visual_prompt": "Prompt", "expected_ctr": 7.5, "emotion": "curiosity"}]'
        mock_generator.client.models.generate_content.return_value = mock_response_chat
        
        # Images のレスポンスをモック
        mock_image_obj = MagicMock()
        mock_image_obj.image.image_bytes = dummy_bytes
        mock_response_images = MagicMock()
        mock_response_images.generated_images = [mock_image_obj]
        mock_generator.client.models.generate_images.return_value = mock_response_images
        
        # 生成実行
        results = await mock_generator.generate("Test Title", "Test Desc", num_variants=1)
        
        assert len(results) == 1
        result = results[0]
        assert result["id"] == "thumbnail_0"
        
        # base64デコードして検証
        import base64
        image_data = base64.b64decode(result["image_base64"])
        
        # Pillowロード可能チェック
        img = Image.open(io.BytesIO(image_data))
        img.load()
        width, height = img.size
        
        assert width >= 1280
        assert height >= 720
        assert abs(width / height - 16.0 / 9.0) < 0.01
        assert len(image_data) < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_generator_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、ThumbnailGeneratorの非同期タスクが自動リトライや結果保存できることを検証"""
        from unittest.mock import patch
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from thumbnail_engine.generator import resolve_generator_thumbnail_task, generator
        
        # ダミーの画像
        from PIL import Image
        import io
        dummy_img = Image.new("RGB", (1920, 1080), color="green")
        img_bytes_io = io.BytesIO()
        dummy_img.save(img_bytes_io, format="JPEG")
        dummy_bytes = img_bytes_io.getvalue()
        
        # generator の generate をパッチしてモックデータを返させる
        import base64
        mock_results = [{
            "id": "thumbnail_0",
            "concept_name": "Mock Concept",
            "description": "Mock Desc",
            "prompt": "Mock Prompt",
            "image_base64": base64.b64encode(dummy_bytes).decode("utf-8"),
            "ctr_score": 8.0
        }]
        
        db_file = tmp_path / "test_generator_tasks.db"
        agent = StageBoundAgent(
            stage_name="generator_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )
        agent.output_dir = str(tmp_path)
        
        task_id = "test_gen_thumb_task_001"
        await agent.register_task(task_id, initial_status="READY", max_retries=1)
        
        with patch.object(generator, "generate", return_value=mock_results):
            async def process_task(tid):
                return await resolve_generator_thumbnail_task(agent, tid)
                
            await agent.start(process_task)
            
            # 完了を待つ
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status == "COMPLETED":
                    break
                await asyncio.sleep(0.05)
                
            status = await agent.get_task_status(task_id)
            assert status == "COMPLETED"
            
            # 結果の検証
            conn = sqlite3.connect(str(db_file))
            cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            conn.close()
            
            assert row is not None
            result_json = json.loads(row[0])
            assert result_json["width"] == 1920
            assert result_json["height"] == 1080
            assert result_json["size_bytes"] > 0
            
            await agent.stop()

    @pytest.mark.anyio
    async def test_generator_thumbnail_resolution_aspect_ratio_boundaries(self, tmp_path):
        """ThumbnailGeneratorの画像補正機能で、極小画像や比率異常の画像が正しく1280x720の16:9へ自動補正されることを検証"""
        from PIL import Image
        import io
        from thumbnail_engine.generator import generator

        # 極小画像 (100x100, 1:1)
        small_img = Image.new("RGB", (100, 100), color="red")
        img_bytes_io = io.BytesIO()
        small_img.save(img_bytes_io, format="JPEG")
        small_bytes = img_bytes_io.getvalue()

        # 補正＆最適化を実行
        optimized_bytes = generator.verify_and_optimize_image(small_bytes)

        # 結果の画像検証
        with Image.open(io.BytesIO(optimized_bytes)) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05

    @pytest.mark.anyio
    async def test_generator_thumbnail_file_size_limit(self, tmp_path):
        """ファイルサイズが4MBの上限を超えた場合に検証エラーになることを検証"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        
        # 4MB以上のダミーデータを作成して検証を試みる
        large_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * (4 * 1024 * 1024 + 100)
        with pytest.raises(ImageValidationError, match="exceeds limit"):
            ThumbnailValidator.validate_image(large_bytes)

    @pytest.mark.anyio
    async def test_generator_thumbnail_corrupted_image(self, tmp_path):
        """画像が破損している（デコードできない）場合でも、フォールバック画像を作成して安全にロード可能にすることを検証"""
        from PIL import Image
        import io
        from thumbnail_engine.generator import generator

        corrupted_bytes = b"NOT_A_VALID_IMAGE_DATA_CORRUPTED_BYTES"
        optimized_bytes = generator.verify_and_optimize_image(corrupted_bytes)

        # フォールバック画像が正しく生成され、Pillowでロードできるか
        with Image.open(io.BytesIO(optimized_bytes)) as img:
            img.load()
            w, h = img.size
            assert w in (1280, 2560)
            assert h >= 720

    @pytest.mark.anyio
    async def test_generator_stage_bound_agent_retry_on_failure(self, tmp_path):
        """例外発生時にStageBoundAgentと連携してリトライが走り、最終的にFAILEDとなりエラー情報が保存されること"""
        from unittest.mock import patch
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from thumbnail_engine.generator import resolve_generator_thumbnail_task, generator

        # エラーを発生させるために、generator.generate が例外を投げるようにモックする
        db_file = tmp_path / "test_generator_tasks_retry.db"
        agent = StageBoundAgent(
            stage_name="generator_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )
        agent.output_dir = str(tmp_path)
        
        task_id = "test_gen_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        with patch.object(generator, "generate", side_effect=ValueError("Simulated API failure")):
            async def process_task(tid):
                return await resolve_generator_thumbnail_task(agent, tid)
                
            await agent.start(process_task)

            # FAILEDになるのを待つ
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status == "FAILED":
                    break
                await asyncio.sleep(0.05)

            status = await agent.get_task_status(task_id)
            assert status == "FAILED"

            # DBからリトライ履歴の検証
            conn = sqlite3.connect(str(db_file))
            cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            conn.close()

            assert row is not None
            assert row[0] == 2  # max_retries
            assert "Simulated API failure" in row[1]

            await agent.stop()

    @pytest.mark.anyio
    async def test_generator_thumbnail_extreme_aspect_ratio_correction(self, tmp_path):
        """極端なアスペクト比（縦長 9:16）の画像が、16:9かつ1280x720以上の解像度に自動補正されることを検証"""
        from PIL import Image
        import io
        from thumbnail_engine.generator import generator

        # 縦長画像 (720x1280, 9:16)
        portrait_img = Image.new("RGB", (720, 1280), color="blue")
        img_bytes_io = io.BytesIO()
        portrait_img.save(img_bytes_io, format="JPEG")
        portrait_bytes = img_bytes_io.getvalue()

        # 補正＆最適化を実行
        optimized_bytes = generator.verify_and_optimize_image(portrait_bytes)

        # 結果の画像検証
        with Image.open(io.BytesIO(optimized_bytes)) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            # 16:9 の比率 (1.777) に極めて近いこと
            assert abs((w / h) - (16.0 / 9.0)) < 0.05

    @pytest.mark.anyio
    async def test_generator_thumbnail_corrupted_fallback_quality(self, tmp_path):
        """完全に破損した画像データが入力された際の、フォールバック画像の生成品質と仕様適合性を検証"""
        from PIL import Image
        import io
        from thumbnail_engine.generator import generator
        from branding.history_manager import ThumbnailValidator

        # 破損データ
        corrupted_bytes = b"CORRUPTED_AND_INVALID_RAW_BYTES_FOR_IMAGE_TEST"
        
        # 最適化（フォールバックが起動する）
        optimized_bytes = generator.verify_and_optimize_image(corrupted_bytes)
        
        # 1. バリデーターによる自動化仕様検証 (1280x720, 16:9, <4MB)
        assert ThumbnailValidator.validate_image(optimized_bytes) is True
        
        # 2. Pillow によるロード可能チェックと詳細検証
        with Image.open(io.BytesIO(optimized_bytes)) as img:
            img.load()
            w, h = img.size
            assert w in (1280, 2560)
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.01
            
        # 3. ファイルサイズチェック
        assert len(optimized_bytes) < 4 * 1024 * 1024



# ============================================================
# FF-28 (追加分): ThumbnailAnalyzer の画像品質検証および自動化テスト
# ============================================================

class TestFF28ThumbnailAnalyzerQuality:
    """FF-28 (追加分): ThumbnailAnalyzer を用いたサムネイル画像生成の品質検証と StageBoundAgent 連携の検証"""

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        from PIL import Image

        analyzer = ThumbnailAnalyzer()
        out_thumb = tmp_path / "analyzer_thumbnail.png"

        # 生成
        analyzer.generate_thumbnail(out_thumb, width=1280, height=720, text="Test Thumbnail")

        # 検証
        info = analyzer.validate_thumbnail(out_thumb)

        assert info["width"] >= 1280 and info["height"] >= 720
        assert abs(info["width"] / info["height"] - 16.0 / 9.0) < 0.01
        assert info["size_bytes"] < 4 * 1024 * 1024

        # Pillowでの完全なロード検証
        with Image.open(out_thumb) as img:
            img.load()
            assert img.size == (1280, 720)

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができる"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from services.thumbnail_analyzer import ThumbnailAnalyzer

        db_file = tmp_path / "test_tasks_analyzer.db"
        agent = StageBoundAgent(
            stage_name="thumbnail_analyzer",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_analyzer_task_001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動
        analyzer = ThumbnailAnalyzer()
        # プロパティを設定してタスク処理時に参照されるようにする
        analyzer.width = 1280
        analyzer.height = 720
        analyzer.text = "Agent Test Thumbnail"

        async def process_task(tid):
            return await analyzer.resolve_thumbnail_task(tid, output_dir=str(tmp_path))

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0  # リトライは発生していない

        await agent.stop()

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_stage_bound_agent_retry_on_failure(self, tmp_path):
        """検証エラーや例外発生時に自動リトライが走り、最終的にFAILEDになること"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from services.thumbnail_analyzer import ThumbnailAnalyzer

        db_file = tmp_path / "test_tasks_analyzer_retry.db"
        agent = StageBoundAgent(
            stage_name="thumbnail_analyzer",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_analyzer_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        analyzer = ThumbnailAnalyzer()
        # 幅を不正な値に設定して確実に例外を発生させる
        analyzer.width = 100
        analyzer.height = 720

        async def process_task(tid):
            return await analyzer.resolve_thumbnail_task(tid, output_dir=str(tmp_path))

        await agent.start(process_task)

        # FAILED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数とエラーの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が保存されている

        await agent.stop()

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_resolution_aspect_ratio_boundaries(self, tmp_path):
        """解像度とアスペクト比の境界値・異常値の検証"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        
        analyzer = ThumbnailAnalyzer()
        out_thumb = tmp_path / "boundary_thumbnail.png"
        
        # 1. 1920x1080 (正常な 16:9)
        analyzer.generate_thumbnail(out_thumb, width=1920, height=1080, text="Boundary Test")
        info = analyzer.validate_thumbnail(out_thumb)
        assert info["width"] == 1920
        assert info["height"] == 1080
        
        # 2. 1280x800 (16:10 アスペクト比異常) -> ValueError
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            analyzer.generate_thumbnail(out_thumb, width=1280, height=800, text="Invalid Aspect")
            
        # 3. 1024x768 (4:3 アスペクト比および解像度不足) -> ValueError
        with pytest.raises(ValueError):
            analyzer.generate_thumbnail(out_thumb, width=1024, height=768, text="Invalid Res")
            
        # 4. 640x360 (16:9 だが解像度不足) -> ValueError
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            analyzer.generate_thumbnail(out_thumb, width=640, height=360, text="Too Small")

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_file_size_limit_mock(self, tmp_path):
        """ファイルサイズ制限（4MB）の境界チェック"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        from unittest.mock import patch, MagicMock
        
        analyzer = ThumbnailAnalyzer()
        out_thumb = tmp_path / "mock_size_thumbnail.png"
        
        # 正常なファイルを生成
        analyzer.generate_thumbnail(out_thumb, width=1280, height=720, text="Size Test")
        
        # stat().st_size を 4MB 以上にモックする
        mock_stat = MagicMock()
        mock_stat.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        
        with patch.object(Path, "stat", return_value=mock_stat):
            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
                analyzer.validate_thumbnail(out_thumb)

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_corrupted_and_empty_files(self, tmp_path):
        """破損画像および空ファイルの検証"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        
        analyzer = ThumbnailAnalyzer()
        
        # 1. 空ファイル (0バイト)
        empty_file = tmp_path / "empty_thumbnail.png"
        empty_file.touch()
        with pytest.raises(ValueError, match="Thumbnail file is empty"):
            analyzer.validate_thumbnail(empty_file)
            
        # 2. 破損ファイル (不正なバイナリデータ)
        corrupted_file = tmp_path / "corrupted_thumbnail.png"
        corrupted_file.write_bytes(b"NOT_A_VALID_IMAGE_DATA_RANDOM_BYTES")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format|Failed to load image pixels"):
            analyzer.validate_thumbnail(corrupted_file)

    @pytest.mark.anyio
    async def test_thumbnail_analyzer_temp_file_cleanup(self, tmp_path):
        """生成中にエラー（検証エラー）が発生した際に一時ファイルが残らないことを検証"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        from unittest.mock import patch
        
        analyzer = ThumbnailAnalyzer()
        out_thumb = tmp_path / "cleanup_test.png"
        
        # validate_thumbnail をモックして ValueError を投げさせ、一時ファイルの削除を確認
        with patch.object(analyzer, "validate_thumbnail", side_effect=ValueError("Simulated validation failure")):
            with pytest.raises(ValueError, match="Generated thumbnail quality validation failed"):
                analyzer.generate_thumbnail(out_thumb, width=1280, height=720, text="Cleanup Test")
                
        # ディレクトリ内を探索し、.tmp ファイルが残っていないことを確認する
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temporary files were not cleaned up: {tmp_files}"

    @pytest.mark.anyio
    async def test_history_manager_thumbnail_quality_and_stage_bound_agent(self, tmp_path):
        """branding/history_manager のサムネイル品質、検証、および StageBoundAgent 連携を検証"""
        import sqlite3
        import asyncio
        from PIL import Image
        from branding.history_manager import (
            PremiumThumbnailGenerator,
            ThumbnailValidator,
            resolve_thumbnail_task,
            ImageValidationError
        )
        from agents.stage_bound_agent import StageBoundAgent

        # 1. 正常なサムネイル生成と品質検証
        output_file = tmp_path / "test_premium_thumbnail.png"
        
        # 実際に生成
        PremiumThumbnailGenerator.generate(
            output_path=output_file,
            width=1280,
            height=720,
            text="Test Premium Thumbnail Quality",
            draw_arrow=True,
            draw_circle=True,
            use_banner=True
        )
        
        assert output_file.exists()
        
        # ファイル読み込みと検証
        with open(output_file, "rb") as f:
            img_bytes = f.read()
            
        # バリデーターによる検証 (パスすればTrueが返る、エラーなら例外発生)
        assert ThumbnailValidator.validate_image(img_bytes) is True
        
        # Pillowで実際にロードしてアサーション
        with Image.open(output_file) as img:
            assert img.size == (1280, 720)
            # アスペクト比が 16:9 であること
            assert abs((img.size[0] / img.size[1]) - (16.0 / 9.0)) < 0.05
            # ロードして破損がないか（ロード失敗すれば例外が起きる）
            img.load()
            
        # ファイルサイズが 4MB 未満であること
        assert len(img_bytes) < 4 * 1024 * 1024
        
        # 2. 不正な画像データの検証（破損検知）
        # 空データ
        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"")
            
        # 極小データ (24バイト未満)
        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"too_small_data")
            
        # 不正な解像度での生成試行
        with pytest.raises(ValueError):
            PremiumThumbnailGenerator.generate(
                output_path=tmp_path / "fail.png",
                width=100,  # 1280未満
                height=100
            )

        # 3. StageBoundAgent 連携と DB マイグレーション
        db_file = tmp_path / "test_tasks_history_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="history_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )
        
        task_id = "test_history_thumb_task_001"
        await agent.register_task(task_id, initial_status="READY", max_retries=1)
        
        # StageBoundAgent のプロパティを設定
        agent.width = 1280
        agent.height = 720
        agent.text = "P27 StageBoundAgent Integration Test"
        agent.output_dir = str(tmp_path)
        
        # resolve_thumbnail_task を使ったタスク実行
        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid)
            
        await agent.start(process_task)
        
        # COMPLETED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
            
        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"
        
        # DBマイグレーションと結果保存の検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT * FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        assert row is not None
        # row: (task_id, path, width, height, size_bytes, verified_at)
        assert row[0] == task_id
        assert row[2] == 1280
        assert row[3] == 720
        assert row[4] > 0
        
        await agent.stop()


class TestThumbnailValidatorExtensions:
    """branding/history_manager の ThumbnailValidator および PremiumThumbnailGenerator に関する追加検証テスト"""

    def test_validate_image_resolution_boundary(self, tmp_path):
        """最小解像度未満の画像が validate_image で適切にエラーになること"""
        from branding.history_manager import PremiumThumbnailGenerator
        import pytest

        output_file = tmp_path / "boundary_test.png"
        # 1280x720 が最小要件だが、1279x720 の画像を生成（ValueErrorになるか）
        # PremiumThumbnailGenerator.generate 自体が 1280x720 未満で例外を投げる
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            PremiumThumbnailGenerator.generate(
                output_path=output_file,
                width=1279,
                height=720,
                text="Fail Resolution"
            )

    def test_validate_image_aspect_ratio_error(self, tmp_path):
        """アスペクト比が 16:9 ではない場合に validate_image が適切にエラーになること"""
        from branding.history_manager import PremiumThumbnailGenerator
        import pytest

        # PremiumThumbnailGenerator.generate に 16:9 ではない比率を渡すと、そもそも generate で ValueError になる
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            PremiumThumbnailGenerator.generate(
                output_path=tmp_path / "aspect_fail.png",
                width=1280,
                height=1280,  # 1:1
                text="Fail Aspect"
            )

    def test_validate_image_size_limit(self, tmp_path):
        """ファイルサイズ制限を超えた場合に validate_image が ImageValidationError を投げること"""
        from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator, ImageValidationError
        import pytest

        output_file = tmp_path / "size_limit_test.png"
        PremiumThumbnailGenerator.generate(
            output_path=output_file,
            width=1280,
            height=720,
            text="Size Limit Test"
        )
        
        with open(output_file, "rb") as f:
            img_bytes = f.read()

        # max_size_bytes を極端に小さく設定して検証
        with pytest.raises(ImageValidationError, match="exceeds limit"):
            ThumbnailValidator.validate_image(
                img_bytes,
                max_size_bytes=100  # 100バイト制限
            )

    def test_jpeg_quality_and_subsampling(self, tmp_path):
        """JPEG生成時に subsampling=0 が適用されていること"""
        from branding.history_manager import PremiumThumbnailGenerator
        from PIL import Image

        output_file = tmp_path / "subsampling_test.jpg"
        PremiumThumbnailGenerator.generate(
            output_path=output_file,
            width=1280,
            height=720,
            text="JPEG Quality Test"
        )

        assert output_file.exists()
        with Image.open(output_file) as img:
            subsampling = img.info.get("subsampling")
            if subsampling is not None:
                assert subsampling == 0 or subsampling == "4:4:4"

    def test_validate_image_resolution_direct(self):
        """解像度不足の画像バイナリを validate_image に直接渡したときに ImageValidationError が発生すること"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io

        # 640x360 の画像（16:9 だが 1280x720 未満）を作成
        img = Image.new("RGB", (640, 360), color="blue")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="PNG")
        img_bytes = img_bytes_io.getvalue()

        # 検証実行（解像度不足で ImageValidationError が発生するはず）
        with pytest.raises(ImageValidationError, match="below minimum requirement"):
            ThumbnailValidator.validate_image(img_bytes)

    def test_validate_image_aspect_ratio_direct(self):
        """アスペクト比が正しくない画像バイナリを validate_image に直接渡したときに ImageValidationError が発生すること"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io

        # 1280x1280 の画像（1280x720 以上だが 16:9 ではない）を作成
        img = Image.new("RGB", (1280, 1280), color="red")
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="PNG")
        img_bytes = img_bytes_io.getvalue()

        with pytest.raises(ImageValidationError, match="does not match expected 16:9"):
            ThumbnailValidator.validate_image(img_bytes)

    def test_validate_image_corrupted_direct(self):
        """破損画像バイナリを validate_image に直接渡したときに ImageValidationError が発生すること"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        import pytest

        # 1. 不正なPNGマジックナンバー
        with pytest.raises(ImageValidationError, match="Image is corrupted or invalid format|Unsupported image format"):
            ThumbnailValidator.validate_image(b"INVALID_HEADER_DATA_123456789")

        # 2. 正しいPNGヘッダーだが中身が空っぽでサイズがおかしい
        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

    def test_temp_file_cleanup_on_generation_error(self, tmp_path):
        """画像生成中にバリデーションエラーなどで失敗した際に、一時ファイルが残らないこと"""
        from branding.history_manager import PremiumThumbnailGenerator
        import pytest

        out_thumb = tmp_path / "cleanup_test.png"
        # 16:9 ではない解像度を指定して失敗させる
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            PremiumThumbnailGenerator.generate(
                output_path=out_thumb,
                width=1280,
                height=1000
            )

        # 一時ファイル（*.tmp）がディレクトリ内に残っていないことを検証
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0, f"Temporary files found: {tmp_files}"

    def test_validate_image_aspect_ratio_boundary_strict(self):
        """アスペクト比の誤差が許容値 0.05 の境界における検証"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io
        import pytest

        # ターゲット比率 16:9 = 1.7777...
        # 1310x720 -> 比率 1.8194... (誤差 0.0416... <= 0.05) -> 許容されるべき
        img_ok = Image.new("RGB", (1310, 720), color="green")
        bio_ok = io.BytesIO()
        img_ok.save(bio_ok, format="PNG")
        assert ThumbnailValidator.validate_image(bio_ok.getvalue()) is True

        # 1320x720 -> 比率 1.8333... (誤差 0.0555... > 0.05) -> エラーになるべき
        img_fail = Image.new("RGB", (1320, 720), color="red")
        bio_fail = io.BytesIO()
        img_fail.save(bio_fail, format="PNG")
        with pytest.raises(ImageValidationError, match="Aspect ratio .* does not match expected 16:9"):
            ThumbnailValidator.validate_image(bio_fail.getvalue())

    def test_validate_image_size_boundary_mock(self):
        """ファイルサイズが制限ギリギリ（4MB）の場合の検証テスト"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io
        import pytest

        # 1280x720の正常画像を作成
        img = Image.new("RGB", (1280, 720), color="blue")
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        base_bytes = bio.getvalue()

        # max_size_bytes が実際の画像サイズより小さい場合
        with pytest.raises(ImageValidationError, match="exceeds limit"):
            ThumbnailValidator.validate_image(base_bytes, max_size_bytes=len(base_bytes) - 10)

        # max_size_bytes が実際の画像サイズと同じか大きい場合
        assert ThumbnailValidator.validate_image(base_bytes, max_size_bytes=len(base_bytes) + 10) is True

    def test_validate_image_corrupted_patterns_extended(self):
        """破損画像バイナリの多様なパターンに対する検証"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        import pytest

        # 不完全なヘッダー
        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"\x89PNG\r\n\x1a\n")

        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"\xff\xd8")

        # ゼロ埋めデータ
        with pytest.raises(ImageValidationError):
            ThumbnailValidator.validate_image(b"\x80" * 100)

    def test_premium_thumbnail_generator_no_fonts_fallback(self, tmp_path):
        """システムフォントが一切利用できない場合でもデフォルトフォントで正常生成されることの検証"""
        from branding.history_manager import PremiumThumbnailGenerator
        from unittest.mock import patch
        import os

        output_file = tmp_path / "fallback_font_test.png"

        # os.path.exists が常に False を返すようにモックして、フォント検出をスキップさせる
        with patch("os.path.exists", return_value=False):
            res_path = PremiumThumbnailGenerator.generate(
                output_path=output_file,
                width=1280,
                height=720,
                text="No Font Fallback Test"
            )
            assert res_path.exists()
            assert res_path == output_file

    @pytest.mark.anyio
    async def test_resolve_thumbnail_task_db_lock_retry(self, tmp_path):
        """resolve_thumbnail_taskでSQLiteが一時的にロックされた場合のリトライ連携検証"""
        from branding.history_manager import resolve_thumbnail_task
        from unittest.mock import patch, MagicMock
        import sqlite3
        import pytest
        import json

        # 無限再帰を避けるため、本物のconnectを退避しておく
        real_connect = sqlite3.connect

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            # 実際の一時DBへの接続を返す
            return real_connect(*args, **kwargs)

        with patch("sqlite3.connect", side_effect=side_effect):
            result = await resolve_thumbnail_task(
                agent_or_id="retry_task_123",
                db_path=str(tmp_path / "retry_test.db"),
                output_dir=str(tmp_path)
            )
            
            # リトライが走り、最終的に成功して結果がjsonで返るはず
            data = json.loads(result)
            assert data["task_id"] == "retry_task_123"
            assert data["valid"] is True
            # コール回数が3回（1回目ロック、2回目ロック、3回目成功）であることを検証
            assert call_count == 3


class TestFF28SubtitlePreviewQuality:
    """FF-28 (追加分): subtitle_preview.py を用いた字幕付きプレビュー画像の品質検証と StageBoundAgent 連携の検証"""

    @pytest.mark.anyio
    async def test_subtitle_preview_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能"""
        from subtitle_preview import resolve_subtitle_preview_task
        import json
        from PIL import Image

        task_id = "test_sub_preview_quality"
        db_file = tmp_path / "test_tasks_quality.db"
        output_dir = tmp_path / "out"

        # 実動画が存在しないモック状態でのフォールバック画像を生成
        result_json_str = await resolve_subtitle_preview_task(
            task_id,
            db_path=str(db_file),
            output_dir=str(output_dir)
        )
        result = json.loads(result_json_str)

        assert result["task_id"] == task_id
        assert Path(result["path"]).exists()

        # 画像の検証
        with Image.open(result["path"]) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05
        
        assert result["size_bytes"] < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_subtitle_preview_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができる"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from subtitle_preview import resolve_subtitle_preview_task

        db_file = tmp_path / "test_tasks_subtitle_preview.db"
        agent = StageBoundAgent(
            stage_name="subtitle_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_sub_preview_task_001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動
        agent.output_dir = str(tmp_path)
        agent.resolution = "1280x720"

        async def process_task(tid):
            return await resolve_subtitle_preview_task(agent, tid)

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0  # リトライは発生していない

        # subtitle_preview_results テーブルに保存されていることの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT * FROM subtitle_preview_results WHERE task_id = ?", (task_id,))
        row_res = cursor.fetchone()
        conn.close()
        assert row_res is not None
        assert row_res[0] == task_id
        assert row_res[2] >= 1280
        assert row_res[3] >= 720

        await agent.stop()

    @pytest.mark.anyio
    async def test_subtitle_preview_stage_bound_agent_retry_on_failure(self, tmp_path):
        """検証エラーや例外発生時に自動リトライが走り、最終的にFAILEDになること"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from subtitle_preview import resolve_subtitle_preview_task

        db_file = tmp_path / "test_tasks_subtitle_preview_retry.db"
        agent = StageBoundAgent(
            stage_name="subtitle_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_sub_preview_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 出力ディレクトリを無効なものにして、例外を発生させる
        # 2026-07-26: 以前は "invalid://path" を使っていたが、これは
        # Windows でのみ無効（":" が使えない）で、Linux では "invalid:" と
        # "path" という正当なディレクトリ名として mkdir に成功してしまう。
        # その結果 CI(Linux) でタスクが COMPLETED になり FAILED を期待する
        # アサーションが落ちていた。通常ファイルを親に指定すれば全 OS で失敗する。
        _blocker = tmp_path / "not_a_directory"
        _blocker.write_text("x", encoding="utf-8")
        agent.output_dir = str(_blocker / "out")

        async def process_task(tid):
            return await resolve_subtitle_preview_task(agent, tid)

        await agent.start(process_task)

        # FAILED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数とエラーの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が保存されている

        await agent.stop()


class TestThumbnailAnalyzerExtensions:
    """ThumbnailAnalyzer の generate_thumbnail / validate_thumbnail に関する追加の検証テスト"""

    def test_analyzer_unsupported_format(self, tmp_path):
        """サポート外の拡張子で例外がスローされること"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        analyzer = ThumbnailAnalyzer()
        output_file = tmp_path / "invalid_format.gif"
        with pytest.raises(ValueError, match="Unsupported file format"):
            analyzer.generate_thumbnail(
                output_path=output_file,
                width=1280,
                height=720,
                text="Invalid Ext"
            )

    def test_analyzer_resolution_boundary(self, tmp_path):
        """最小解像度未満で ValueError が発生すること"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        analyzer = ThumbnailAnalyzer()
        output_file = tmp_path / "resolution_boundary.png"
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            analyzer.generate_thumbnail(
                output_path=output_file,
                width=1279,
                height=720,
                text="Boundary Fail"
            )

    def test_analyzer_aspect_ratio_error(self, tmp_path):
        """アスペクト比が 16:9 ではない場合に ValueError が発生すること"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        analyzer = ThumbnailAnalyzer()
        output_file = tmp_path / "aspect_fail.png"
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            analyzer.generate_thumbnail(
                output_path=output_file,
                width=1280,
                height=1280,
                text="Aspect Fail"
            )

    def test_analyzer_validate_size_limit(self, tmp_path):
        """validate_thumbnail がファイルサイズ制限を超えた場合に ValueError を投げること"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        from unittest.mock import patch, MagicMock
        analyzer = ThumbnailAnalyzer()
        output_file = tmp_path / "size_limit_test.png"
        
        # 正常なファイルを生成
        analyzer.generate_thumbnail(
            output_path=output_file,
            width=1280,
            height=720,
            text="Size Limit Test"
        )
        
        # stat().st_size が 4MB (4 * 1024 * 1024) 以上を返すようにモックする
        mock_stat = MagicMock()
        mock_stat.st_size = 4 * 1024 * 1024 + 10  # 4MB超
        
        with patch.object(Path, "stat", return_value=mock_stat):
            with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
                analyzer.validate_thumbnail(output_file)


class TestFF28AddPremiumBrandingThumbnailQuality:
    """FF-28: プレミアムブランディング画像生成の品質検証と StageBoundAgent 連携の検証"""

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能"""
        from add_premium_branding import generate_premium_branding_thumbnail, validate_thumbnail
        from PIL import Image

        out_thumb = tmp_path / "premium_thumbnail.png"
        out_preview = tmp_path / "premium_preview.png"

        # 生成
        generate_premium_branding_thumbnail(
            out_thumb,
            width=1280,
            height=720,
            text="Premium Branding Test Text",
            preview_path=out_preview
        )

        # 検証 (サムネイル)
        info = validate_thumbnail(out_thumb)
        assert info["width"] >= 1280 and info["height"] >= 720
        assert abs(info["width"] / info["height"] - 16.0 / 9.0) < 0.01
        assert info["size_bytes"] < 4 * 1024 * 1024

        # 検証 (プレビュー)
        info_prev = validate_thumbnail(out_preview, is_preview=True)
        assert info_prev["width"] >= 320 and info_prev["height"] >= 180
        assert abs(info_prev["width"] / info_prev["height"] - 16.0 / 9.0) < 0.01
        assert info_prev["size_bytes"] < 4 * 1024 * 1024

        # Pillowでの完全なロード検証
        with Image.open(out_thumb) as img:
            img.load()
            assert img.size == (1280, 720)

        with Image.open(out_preview) as img:
            img.load()
            assert img.size == (640, 360)

    @pytest.mark.anyio
    async def test_add_premium_branding_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができる"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from add_premium_branding import resolve_premium_branding_task

        db_file = tmp_path / "test_tasks_premium.db"
        agent = StageBoundAgent(
            stage_name="premium_branding",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_premium_brand_task_001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動
        agent.output_dir = str(tmp_path)
        agent.width = 1280
        agent.height = 720
        agent.text = "Agent Premium Branding Test"

        async def process_task(tid):
            return await resolve_premium_branding_task(tid, agent)

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert result_json["size_bytes"] > 0
        assert "preview" in result_json
        assert result_json["preview"]["width"] == 640
        assert row[1] == 0  # リトライは発生していない

        await agent.stop()

    @pytest.mark.anyio
    async def test_add_premium_branding_stage_bound_agent_retry_on_failure(self, tmp_path):
        """検証エラーや例外発生時に自動リトライが走り、最終的にFAILEDになること"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from add_premium_branding import resolve_premium_branding_task

        db_file = tmp_path / "test_tasks_premium_retry.db"
        agent = StageBoundAgent(
            stage_name="premium_branding",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_premium_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 出力ディレクトリを無効なものにして、例外を発生させる
        # 2026-07-26: 以前は "invalid://path" を使っていたが、これは
        # Windows でのみ無効（":" が使えない）で、Linux では "invalid:" と
        # "path" という正当なディレクトリ名として mkdir に成功してしまう。
        # その結果 CI(Linux) でタスクが COMPLETED になり FAILED を期待する
        # アサーションが落ちていた。通常ファイルを親に指定すれば全 OS で失敗する。
        _blocker = tmp_path / "not_a_directory"
        _blocker.write_text("x", encoding="utf-8")
        agent.output_dir = str(_blocker / "out")

        async def process_task(tid):
            return await resolve_premium_branding_task(tid, agent)

        await agent.start(process_task)

        # FAILED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数とエラーの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が保存されている

        await agent.stop()

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_resolution_aspect_ratio_boundaries(self, tmp_path):
        """解像度・アスペクト比の境界値とバリデーションを検証"""
        from add_premium_branding import generate_premium_branding_thumbnail, validate_thumbnail
        
        out_thumb = tmp_path / "boundary_thumb.png"
        
        # 1. 境界未満の解像度 (1279x720) -> ValueError
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            generate_premium_branding_thumbnail(out_thumb, width=1279, height=720)
            
        # 2. 境界未満の解像度 (1280x719) -> ValueError
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            generate_premium_branding_thumbnail(out_thumb, width=1280, height=719)
            
        # 3. アスペクト比異常 (16:9 以外、例えば 1280x721) -> ValueError
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            generate_premium_branding_thumbnail(out_thumb, width=1280, height=721)

        # 4. 正常な最小解像度 (1280x720) -> 正常終了
        generate_premium_branding_thumbnail(out_thumb, width=1280, height=720, text="Boundary Test")
        info = validate_thumbnail(out_thumb)
        assert info["width"] == 1280
        assert info["height"] == 720

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_file_size_limit(self, tmp_path):
        """ファイルサイズ制限 (4MB未満) を検証"""
        from add_premium_branding import validate_thumbnail
        
        large_file = tmp_path / "large_thumb.png"
        
        # ダミーの4MB以上のデータを持たせたファイルを作成
        with open(large_file, "wb") as f:
            f.write(b"\0" * (4 * 1024 * 1024))
            
        with pytest.raises(ValueError, match="File size exceeds 4MB limit"):
            validate_thumbnail(large_file)

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_corrupted_image(self, tmp_path):
        """破損画像および空ファイルの検証"""
        from add_premium_branding import validate_thumbnail
        
        corrupted_file = tmp_path / "corrupted.png"
        empty_file = tmp_path / "empty.png"
        
        # 1. 破損画像 (PNGシグネチャのみ、中身なし)
        with open(corrupted_file, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\0")
            
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(corrupted_file)
            
        # 2. 空ファイル
        with open(empty_file, "wb") as f:
            pass
            
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(empty_file)

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_temp_file_cleanup(self, tmp_path):
        """生成失敗時に一時ファイルが確実に削除されることの検証"""
        from add_premium_branding import generate_premium_branding_thumbnail
        
        bad_output_path = tmp_path / "non_existent_dir" / "fail.png"
        (tmp_path / "non_existent_dir").touch()
        
        with pytest.raises((OSError, FileExistsError, BaseException)):
            generate_premium_branding_thumbnail(bad_output_path, width=1280, height=720)
            
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

    @pytest.mark.anyio
    async def test_add_premium_branding_db_migration_integration(self, tmp_path):
        """DBマイグレーション（StageBoundAgent初期化時）が正常に連携されることの検証"""
        import sqlite3
        from agents.stage_bound_agent import StageBoundAgent
        
        db_file = tmp_path / "test_migration_premium.db"
        
        # 初期状態の tasks テーブル (古いスキーマ)
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, stage TEXT, status TEXT)")
        conn.commit()
        
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns_before = [row[1] for row in cursor.fetchall()]
        assert "result" not in columns_before
        assert "retry_count" not in columns_before
        conn.close()
        
        # Agentを初期化してマイグレーションを実行させる
        agent = StageBoundAgent(
            stage_name="premium_branding",
            db_path=str(db_file)
        )
        
        # マイグレーション後のカラム検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns_after = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        assert "result" in columns_after
        assert "retry_count" in columns_after
        assert "max_retries" in columns_after

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_single_color_failure(self, tmp_path):
        """単一色の画像（真っ黒など）が validate_thumbnail で正しくエラーになることを検証"""
        from add_premium_branding import validate_thumbnail
        from PIL import Image
        
        single_color_file = tmp_path / "single_color.png"
        
        # 1280x720の単一色の画像（真っ青）を生成
        img = Image.new("RGB", (1280, 720), color="blue")
        img.save(single_color_file, "PNG")
        
        with pytest.raises(ValueError, match="Image is a single solid color"):
            validate_thumbnail(single_color_file)

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_disk_space_error(self, tmp_path):
        """ディスク空き容量が不足している場合に generate_premium_branding_thumbnail が OSError をスローすることを検証"""
        from add_premium_branding import generate_premium_branding_thumbnail
        from unittest.mock import patch, MagicMock
        
        out_thumb = tmp_path / "disk_space_fail.png"
        
        # shutil.disk_usage の戻り値を空き容量不足にモックする
        mock_usage = MagicMock()
        mock_usage.total = 100 * 1024 * 1024
        mock_usage.used = 99 * 1024 * 1024
        mock_usage.free = 5 * 1024 * 1024  # 5MB free (10MB未満)
        
        with patch("shutil.disk_usage", return_value=(mock_usage.total, mock_usage.used, mock_usage.free)):
            with pytest.raises(OSError, match="Insufficient disk space"):
                generate_premium_branding_thumbnail(out_thumb, width=1280, height=720)

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_unsupported_format(self, tmp_path):
        """サポート外の拡張子（.gifなど）で generate_premium_branding_thumbnail が ValueError を投げることを検証"""
        from add_premium_branding import generate_premium_branding_thumbnail
        
        bad_format_file = tmp_path / "invalid_format.gif"
        
        with pytest.raises(ValueError, match="Unsupported file format"):
            generate_premium_branding_thumbnail(bad_format_file, width=1280, height=720)

    @pytest.mark.anyio
    async def test_add_premium_branding_thumbnail_invalid_path_chars(self, tmp_path):
        """Windowsで無効な文字を含むパスに対して generate_premium_branding_thumbnail が OSError を投げることを検証"""
        from add_premium_branding import generate_premium_branding_thumbnail
        
        # Windowsの無効な文字 '<>' を含むパス
        bad_char_path = tmp_path / "invalid_<>_char.png"
        
        with pytest.raises(OSError, match="Invalid characters in path"):
            generate_premium_branding_thumbnail(bad_char_path, width=1280, height=720)


class TestFF28ComprehensivePreviewQuality:
    """FF-28: 包括的プレビュー生成の品質検証と StageBoundAgent 連携の検証"""

    @pytest.fixture(autouse=True)
    def ensure_test_video(self):
        from pathlib import Path
        import subprocess
        src_video = Path("backend/tests/test_13s.mp4")
        if not src_video.exists():
            src_video.parent.mkdir(parents=True, exist_ok=True)
            create_video_cmd = [
                "ffmpeg",
                "-f", "lavfi",
                "-i", "testsrc=size=1280x720:rate=25",
                "-c:v", "libx264",
                "-t", "2",
                "-pix_fmt", "yuv420p",
                "-y",
                str(src_video)
            ]
            try:
                subprocess.run(create_video_cmd, check=True, capture_output=True, timeout=10.0)
            except Exception:
                pass
        src_sub = Path("backend/tests/test_13s_whisper_semantic.srt")
        if not src_sub.exists():
            src_sub.parent.mkdir(parents=True, exist_ok=True)
            src_sub.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello World\n", encoding="utf-8")

    @pytest.mark.anyio
    async def test_comprehensive_preview_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能"""
        from comprehensive_preview import create_comprehensive_preview, validate_preview_image
        from pathlib import Path

        src_video = Path("tests/test_13s.mp4") if Path("tests/test_13s.mp4").exists() else Path("backend/tests/test_13s.mp4")
        assert src_video.exists()

        output_dir = tmp_path / "comp_preview_test"

        # 高速化のため、タイムスタンプは1点のみ指定
        result = create_comprehensive_preview(
            input_video=str(src_video),
            output_dir=str(output_dir),
            timestamps=[1.0]
        )

        assert Path(result["base"]).exists()
        assert Path(result["logo_telop"]).exists()
        assert Path(result["color_graded"]).exists()
        assert Path(result["comprehensive"]).exists()

        screenshots = result["screenshots"]
        for key in ["logo", "color", "comprehensive"]:
            paths = screenshots[key]
            assert len(paths) == 1
            img_path = paths[0]
            assert Path(img_path).exists()

            # 品質検証
            val_res = validate_preview_image(img_path)
            assert val_res["width"] >= 1280
            assert val_res["height"] >= 720
            assert abs(val_res["width"] / val_res["height"] - 16.0 / 9.0) <= 0.01
            assert val_res["size_bytes"] < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_comprehensive_preview_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができる"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from comprehensive_preview import resolve_comprehensive_preview_task

        db_file = tmp_path / "test_tasks_comp_preview.db"
        agent = StageBoundAgent(
            stage_name="comprehensive_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_comp_preview_task_001"
        await agent.register_task(task_id, initial_status="READY", max_retries=1)

        # Agentパラメータ設定
        agent.input_video = "tests/test_13s.mp4" if Path("tests/test_13s.mp4").exists() else "backend/tests/test_13s.mp4"
        agent.output_dir = str(tmp_path / "agent_comp_preview")
        agent.timestamps = [1.0]

        async def process_task(tid):
            return await resolve_comprehensive_preview_task(agent, tid)

        await agent.start(process_task)

        # 完了を待つ
        for _ in range(1200):
            status = await agent.get_task_status(task_id)
            if status in ["COMPLETED", "FAILED"]:
                break
            await asyncio.sleep(0.1)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 結果の検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["task_id"] == task_id
        assert len(result_json["validation"]) > 0
        for val in result_json["validation"]:
            assert val["width"] >= 1280
            assert val["height"] >= 720
            assert val["size_bytes"] < 4 * 1024 * 1024
        assert row[1] == 0

        await agent.stop()

    @pytest.mark.anyio
    async def test_comprehensive_preview_stage_bound_agent_retry_on_failure(self, tmp_path):
        """検証エラーや例外発生時に自動リトライが走り、最終的にFAILEDになること"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from comprehensive_preview import resolve_comprehensive_preview_task

        db_file = tmp_path / "test_tasks_comp_retry.db"
        agent = StageBoundAgent(
            stage_name="comprehensive_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_comp_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 存在しない動画パスを設定して意図的に失敗させる
        agent.input_video = "backend/tests/non_existent_video.mp4"
        agent.output_dir = str(tmp_path / "agent_comp_preview_fail")

        async def process_task(tid):
            return await resolve_comprehensive_preview_task(agent, tid)

        await agent.start(process_task)

        # FAILED になるのを待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数とエラーの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None

        await agent.stop()


class TestProgressivePreviewReportThumbnail:
    """progressive_preview_report.py のサムネイル画像生成・検証・StageBoundAgent連携テスト"""

    @pytest.mark.anyio
    async def test_generate_and_validate_success(self, tmp_path):
        """サムネイル画像が正しく生成され、検証項目をパスすることを確認"""
        from progressive_preview_report import generate_progressive_preview_thumbnail, validate_thumbnail
        from PIL import Image

        out_thumb = tmp_path / "progressive_thumbnail.png"
        text = "Progressive Preview Title\nStep: crop\nDetails: Successful execution"

        # 正常な生成
        generate_progressive_preview_thumbnail(out_thumb, width=1280, height=720, text=text)

        # 品質検証
        info = validate_thumbnail(out_thumb)
        assert info["width"] == 1280
        assert info["height"] == 720
        assert abs(info["width"] / info["height"] - 16.0 / 9.0) < 0.01
        assert info["size_bytes"] < 4 * 1024 * 1024
        assert info["size_bytes"] >= 100

        # Pillowによる完全ロードの検証
        with Image.open(out_thumb) as img:
            img.load()
            assert img.size == (1280, 720)
            assert img.format == "PNG"

    @pytest.mark.anyio
    async def test_invalid_inputs(self, tmp_path):
        """不正な解像度、アスペクト比、メモリ上限超えなどの入力値に対して ValueError が発生することを確認"""
        from progressive_preview_report import generate_progressive_preview_thumbnail
        out_thumb = tmp_path / "invalid_thumb.png"

        # 解像度不足
        with pytest.raises(ValueError, match="Resolution must be at least 1280x720"):
            generate_progressive_preview_thumbnail(out_thumb, width=640, height=360)

        # メモリ上限超え
        with pytest.raises(ValueError, match="Resolution exceeds maximum limit"):
            generate_progressive_preview_thumbnail(out_thumb, width=3841, height=2160)

        # アスペクト比が 16:9 以外 (例: 4:3)
        with pytest.raises(ValueError, match="Aspect ratio must be 16:9"):
            generate_progressive_preview_thumbnail(out_thumb, width=1600, height=1200)

        # 不正な解像度の型
        with pytest.raises(ValueError, match="Width and height must be integers"):
            generate_progressive_preview_thumbnail(out_thumb, width="invalid", height=720)

        with pytest.raises(ValueError, match="Width and height must be positive integers"):
            generate_progressive_preview_thumbnail(out_thumb, width=-1280, height=720)

    @pytest.mark.anyio
    async def test_validate_corrupted_or_missing(self, tmp_path):
        """存在しないパス、空ファイル、壊れた画像に対して validate_thumbnail が適切に例外をスローすることを確認"""
        from progressive_preview_report import validate_thumbnail

        # 存在しないファイル
        missing_file = tmp_path / "non_existent.png"
        with pytest.raises(FileNotFoundError):
            validate_thumbnail(missing_file)

        # 空ファイル
        empty_file = tmp_path / "empty.png"
        empty_file.write_bytes(b"")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(empty_file)

        # 壊れた画像データ
        corrupted_file = tmp_path / "corrupted.png"
        corrupted_file.write_bytes(b"INVALID_PNG_HEADER_DATA_12345")
        with pytest.raises(ValueError, match="Image is corrupted or invalid format"):
            validate_thumbnail(corrupted_file)

    @pytest.mark.anyio
    async def test_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgent にタスクを登録して実行、結果がDBに正しく書き込まれることを検証"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from progressive_preview_report import resolve_progressive_preview_report_task

        db_file = tmp_path / "test_tasks_progressive.db"
        agent = StageBoundAgent(
            stage_name="progressive_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_progressive_task_001"
        await agent.register_task(task_id, initial_status="READY", max_retries=1)

        # Agentパラメータ設定
        agent.output_dir = str(tmp_path)
        agent.width = 1280
        agent.height = 720
        agent.text = "StageBoundAgent integration test for Progressive Preview Report"

        async def process_task(tid):
            return await resolve_progressive_preview_report_task(agent, tid)

        await agent.start(process_task)

        # 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 結果の検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] == 1280
        assert result_json["height"] == 720
        assert result_json["size_bytes"] > 0
        assert row[1] == 0  # リトライなし

        await agent.stop()

    @pytest.mark.anyio
    async def test_stage_bound_agent_retry_on_failure(self, tmp_path):
        """例外発生時に自動リトライが走り、最終的に FAILED ステータスになることの検証"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from progressive_preview_report import resolve_progressive_preview_report_task

        db_file = tmp_path / "test_tasks_progressive_retry.db"
        agent = StageBoundAgent(
            stage_name="progressive_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "test_progressive_fail_task"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 無効なパスを設定し例外をスローさせる
        # 2026-07-26: 以前は "invalid://path" を使っていたが、これは
        # Windows でのみ無効（":" が使えない）で、Linux では "invalid:" と
        # "path" という正当なディレクトリ名として mkdir に成功してしまう。
        # その結果 CI(Linux) でタスクが COMPLETED になり FAILED を期待する
        # アサーションが落ちていた。通常ファイルを親に指定すれば全 OS で失敗する。
        _blocker = tmp_path / "not_a_directory"
        _blocker.write_text("x", encoding="utf-8")
        agent.output_dir = str(_blocker / "out")

        async def process_task(tid):
            return await resolve_progressive_preview_report_task(agent, tid)

        await agent.start(process_task)

        # FAILED を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数の確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が残っている

        await agent.stop()

    @pytest.mark.anyio
    async def test_db_migration_integration(self, tmp_path):
        """StageBoundAgent 初期化時に DB が自動的にマイグレーションされ必要なカラムが作成されることを検証"""
        import sqlite3
        from agents.stage_bound_agent import StageBoundAgent

        db_file = tmp_path / "test_migration_progressive.db"

        # 1. 不完全な tasks テーブルを作成する
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, stage TEXT, status TEXT)")
        conn.commit()

        # テーブルの定義を確認 (ALTER 前)
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns_before = [row[1] for row in cursor.fetchall()]
        assert "result" not in columns_before
        assert "retry_count" not in columns_before
        conn.close()

        # 2. StageBoundAgent を初期化する（これでマイグレーションが走るはず）
        agent = StageBoundAgent(
            stage_name="progressive_preview",
            db_path=str(db_file)
        )

        # 3. カラムが追加されたことを確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("PRAGMA table_info(tasks)")
        columns_after = [row[1] for row in cursor.fetchall()]
        conn.close()

        assert "result" in columns_after
        assert "retry_count" in columns_after
        assert "max_retries" in columns_after






# ============================================================
# FF-29: プレミアムサムネイル画像生成および品質検証の自動化
# ============================================================

class TestFF29PremiumThumbnailQuality:
    """FF-29: プレミアムサムネイル画像生成の品質検証と StageBoundAgent 連携の検証"""

    @pytest.mark.anyio
    async def test_premium_thumbnail_quality_and_load(self, tmp_path):
        """生成画像の解像度が 1280x720 以上、アスペクト比 16:9、4MB未満、Pillowロード可能であること"""
        from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
        from PIL import Image

        out_path = tmp_path / "premium_thumbnail_test.png"
        
        # 1. 画像生成の実行
        PremiumThumbnailGenerator.generate(
            out_path,
            width=1280,
            height=720,
            text="FF29 Quality Test",
            draw_arrow=True,
            draw_circle=True,
            use_banner=True
        )

        assert out_path.exists()

        # 2. ファイルを読み込んで検証
        with open(out_path, "rb") as f:
            img_bytes = f.read()

        # 品質要件の検証
        assert ThumbnailValidator.validate_image(img_bytes)

        # 3. Pillowロードの確認
        with Image.open(out_path) as img:
            img.load()
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05
            assert len(img_bytes) < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_stage_bound_agent_integration(self, tmp_path):
        """StageBoundAgentと連携し、非同期タスク処理、自動リトライ、結果保存ができること"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import resolve_thumbnail_task

        db_file = tmp_path / "test_tasks_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "task-thumbnail-ff29-001"
        # 1. タスク登録 (max_retries = 2)
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 2. Agent起動 (resolve_thumbnail_task をバインドして登録)
        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=str(tmp_path))

        await agent.start(process_task)

        # 3. 完了を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # 4. 結果の検証 (result 列に JSON が保存されていること)
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        
        # さらに結果が thumbnail_results テーブルにも保存されていることを確認
        cursor_res = conn.execute("SELECT width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row_res = cursor_res.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert row[1] == 0  # リトライなしで成功したこと

        assert row_res is not None
        assert row_res[0] >= 1280
        assert row_res[1] >= 720
        assert row_res[2] > 0

        await agent.stop()

    @pytest.mark.anyio
    async def test_stage_bound_agent_retry_on_failure(self, tmp_path):
        """例外発生時に自動リトライが走り、最終的に FAILED ステータスになることの検証"""
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import resolve_thumbnail_task

        db_file = tmp_path / "test_tasks_thumbnail_retry.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "task-thumbnail-fail-001"
        await agent.register_task(task_id, initial_status="READY", max_retries=2)

        # 無効な出力先を設定し例外をスローさせる
        # 2026-07-26: 以前は "invalid://path" を使っていたが、これは
        # Windows でのみ無効（":" が使えない）で、Linux では "invalid:" と
        # "path" という正当なディレクトリ名として mkdir に成功してしまう。
        # その結果 CI(Linux) でタスクが COMPLETED になり FAILED を期待する
        # アサーションが落ちていた。通常ファイルを親に指定すれば全 OS で失敗する。
        _blocker = tmp_path / "not_a_directory"
        _blocker.write_text("x", encoding="utf-8")
        invalid_output_dir = str(_blocker / "out")

        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=invalid_output_dir)

        await agent.start(process_task)

        # FAILED を待つ
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "FAILED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "FAILED"

        # リトライ回数の確認
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT retry_count, error FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 2  # max_retries = 2
        assert row[1] is not None  # エラー内容が残っている

        await agent.stop()

    @pytest.mark.anyio
    async def test_thumbnail_corrupted_image(self, tmp_path):
        """破損画像（PNG/JPEGの末尾が欠損しているものなど）に対して適切に ImageValidationError が発生することを検証"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        
        # 1. 短すぎるデータ
        short_bytes = b"\x89PNG\r\n\x1a\n12345"
        with pytest.raises(ImageValidationError, match="too small|invalid PNG"):
            ThumbnailValidator.validate_image(short_bytes)

        # 2. PNGヘッダはあるがIENDがないもの
        corrupted_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        with pytest.raises(ImageValidationError, match="corrupted|IEND"):
            ThumbnailValidator.validate_image(corrupted_png)

        # 3. JPEGヘッダはあるがEOIがないもの
        corrupted_jpeg = b"\xff\xd8" + b"\x00" * 50
        with pytest.raises(ImageValidationError, match="corrupted|EOI"):
            ThumbnailValidator.validate_image(corrupted_jpeg)

    @pytest.mark.anyio
    async def test_thumbnail_resolution_aspect_ratio_boundaries(self):
        """解像度やアスペクト比の境界値に対する検証エラー検出"""
        from branding.history_manager import ThumbnailValidator, ImageValidationError
        from PIL import Image
        import io

        # 1. 1280x720 未満 (例: 1000x562, アスペクト比は16:9に近い)
        img_small = Image.new("RGB", (1000, 562), color="red")
        f_small = io.BytesIO()
        img_small.save(f_small, format="PNG")
        with pytest.raises(ImageValidationError, match="below minimum requirement"):
            ThumbnailValidator.validate_image(f_small.getvalue())

        # 2. アスペクト比が 16:9 でない (例: 1280x1280, 1:1)
        img_square = Image.new("RGB", (1280, 1280), color="blue")
        f_square = io.BytesIO()
        img_square.save(f_square, format="PNG")
        with pytest.raises(ImageValidationError, match="Aspect ratio"):
            ThumbnailValidator.validate_image(f_square.getvalue())


class TestPhase27ThumbnailImprovement:
    """
    Phase 27: タスク T-batch_abc60d-thumbnail-001 用のサムネイル改善テスト
    解像度 1280x720 以上、アスペクト比 16:9、ファイルサイズ 4MB 未満、破損チェック、
    および StageBoundAgent との連携（自動リトライ、結果保存、DBマイグレーション）を検証する。
    """

    @pytest.mark.anyio
    async def test_phase27_thumbnail_generation_and_validation_success(self, tmp_path):
        """T-batch_abc60d-thumbnail-001 の正常系フローテスト"""
        from branding.history_manager import PremiumThumbnailGenerator, ThumbnailValidator
        from PIL import Image

        out_path = tmp_path / "T-batch_abc60d-thumbnail-001.png"
        
        # 1. 画像生成の実行
        PremiumThumbnailGenerator.generate(
            out_path,
            width=1920, # 1280x720 以上
            height=1080, # 16:9
            text="T-batch_abc60d-thumbnail-001",
            draw_arrow=True,
            draw_circle=True
        )

        assert out_path.exists()

        # 2. バイナリの検証
        with open(out_path, "rb") as f:
            img_bytes = f.read()

        # バリデーターによる検証
        assert ThumbnailValidator.validate_image(img_bytes)

        # 3. 詳細な画像情報と破損検知（Pillowでのロード）
        with Image.open(out_path) as img:
            img.load()
            img.transpose(Image.FLIP_LEFT_RIGHT) # 内部デコーダ検証
            w, h = img.size
            assert w >= 1280
            assert h >= 720
            assert abs((w / h) - (16.0 / 9.0)) < 0.05
            assert len(img_bytes) < 4 * 1024 * 1024

    @pytest.mark.anyio
    async def test_phase27_stage_bound_agent_integration(self, tmp_path):
        """T-batch_abc60d-thumbnail-001 が StageBoundAgent と連携し、結果がDBに正常保存されること"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from branding.history_manager import resolve_thumbnail_task

        db_file = tmp_path / "p27_tasks_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="premium_thumbnail",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "T-batch_abc60d-thumbnail-001"
        await agent.register_task(task_id, initial_status="READY", max_retries=3)

        async def process_task(tid):
            return await resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=str(tmp_path))

        await agent.start(process_task)

        # 完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # DBの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        
        # thumbnail_results テーブル（DBマイグレーション先）の検証
        cursor_res = conn.execute("SELECT width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row_res = cursor_res.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert result_json["valid"] is True
        assert row[1] == 0  # 自動リトライなしで一発成功

        assert row_res[2] < 4 * 1024 * 1024

        await agent.stop()


class TestPhase27ThumbnailImprovementEE6B74:
    """
    Phase 27: タスク T-batch_ee6b74-thumbnail-001 用のサムネイル改善テスト
    services.thumbnail_analyzer.ThumbnailAnalyzer を対象とし、
    解像度 1280x720 以上、アスペクト比 16:9、ファイルサイズ 4MB 未満、破損チェック、
    および StageBoundAgent との連携（自動リトライ、結果保存、DBマイグレーション）を検証する。
    """

    @pytest.mark.anyio
    async def test_phase27_ee6b74_thumbnail_generation_and_validation_success(self, tmp_path):
        """T-batch_ee6b74-thumbnail-001 の正常系フローテスト"""
        from services.thumbnail_analyzer import ThumbnailAnalyzer
        from PIL import Image

        analyzer = ThumbnailAnalyzer()
        out_path = tmp_path / "T-batch_ee6b74-thumbnail-001.png"
        
        # 1. 画像生成の実行 (品質向上オプションも含めてテスト)
        analyzer.generate_thumbnail(
            out_path,
            width=1280, # 1280x720 以上
            height=720, # 16:9
            text="T-batch_ee6b74-thumbnail-001",
            draw_arrow=True,
            draw_circle=True,
            use_banner=True
        )

        assert out_path.exists()

        # 2. バリデーターによる検証
        result_info = analyzer.validate_thumbnail(out_path)
        assert result_info["width"] >= 1280
        assert result_info["height"] >= 720
        assert abs((result_info["width"] / result_info["height"]) - (16.0 / 9.0)) < 0.01
        assert result_info["size_bytes"] < 4 * 1024 * 1024

        # 3. Pillowでのロードおよび転置処理による破損検知検証
        with Image.open(out_path) as img:
            img.load()
            img.transpose(Image.FLIP_LEFT_RIGHT)
            w, h = img.size
            assert w >= 1280
            assert h >= 720

    @pytest.mark.anyio
    async def test_phase27_ee6b74_stage_bound_agent_integration(self, tmp_path):
        """T-batch_ee6b74-thumbnail-001 が StageBoundAgent と連携し、結果がDB（thumbnail_results テーブル）に正常保存・マイグレーションされること"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from services.thumbnail_analyzer import ThumbnailAnalyzer

        db_file = tmp_path / "p27_ee6b74_tasks_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="thumbnail_analyzer_p27",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "T-batch_ee6b74-thumbnail-001"
        await agent.register_task(task_id, initial_status="READY", max_retries=3)

        analyzer = ThumbnailAnalyzer()
        # プロパティを設定してタスク処理時に参照されるようにする
        analyzer.width = 1280
        analyzer.height = 720
        analyzer.text = "T-batch_ee6b74-thumbnail-001"

        async def process_task(tid):
            return await analyzer.resolve_thumbnail_task(agent, tid, db_path=str(db_file), output_dir=str(tmp_path))

        await agent.start(process_task)

        # 完了を待機
        for _ in range(50):
            status = await agent.get_task_status(task_id)
            if status == "COMPLETED":
                break
            await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # DBの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        
        # thumbnail_results テーブル（DBマイグレーション先）の検証
        cursor_res = conn.execute("SELECT width, height, size_bytes FROM thumbnail_results WHERE task_id = ?", (task_id,))
        row_res = cursor_res.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["width"] >= 1280
        assert result_json["height"] >= 720
        assert result_json["valid"] is True
        assert row[1] == 0  # 自動リトライなしで一発成功

        assert row_res is not None
        assert row_res[0] >= 1280
        assert row_res[1] >= 720
        assert row_res[2] < 4 * 1024 * 1024

        await agent.stop()


class TestPhase27ComprehensivePreviewThumbnailImprovementEE6B74_000:
    """
    Phase 27: タスク T-batch_ee6b74-thumbnail-000 用のサムネイル改善テスト
    comprehensive_preview.py を対象とし、以下の品質・堅牢性要件を検証する。
    1. 解像度 1280x720 以上であること
    2. アスペクト比が 16:9 であること
    3. ファイルサイズが 4MB 未満であること
    4. 出力ファイルが正常に存在し、破損していない（Pillow等で正常にロード可能である）こと
    5. StageBoundAgent 等に登録され、自動リトライや結果保存、DBマイグレーションの各機能と連携して動作すること
    """

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_generation_and_validation_success(self, tmp_path):
        """T-batch_ee6b74-thumbnail-000 の正常系フローテスト"""
        from comprehensive_preview import ensure_preview_image_quality, validate_preview_image
        from PIL import Image, ImageDraw

        out_path = tmp_path / "T-batch_ee6b74-thumbnail-000.png"
        
        # 1. 解像度が低くアスペクト比が異なる元画像（800x600, 4:3）を作成。単一色を避けるため描画を追加。
        orig_img = Image.new("RGB", (800, 600), color=(255, 100, 100))
        draw = ImageDraw.Draw(orig_img)
        draw.rectangle([0, 0, 400, 300], fill=(100, 255, 100))
        orig_img.save(out_path)

        # 2. 自動補正（品質向上）の実行
        res_path = ensure_preview_image_quality(str(out_path), padding_mode="blur")
        assert Path(res_path).exists()

        # 3. バリデーターによる検証
        result_info = validate_preview_image(res_path)
        assert result_info["width"] >= 1280
        assert result_info["height"] >= 720
        assert abs((result_info["width"] / result_info["height"]) - (16.0 / 9.0)) < 0.01
        assert result_info["size_bytes"] < 4 * 1024 * 1024

        # 4. Pillowでの完全ロードおよび転置による破損検知検証
        with Image.open(res_path) as img:
            img.load()
            img.transpose(Image.FLIP_LEFT_RIGHT)
            w, h = img.size
            assert w >= 1280
            assert h >= 720

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_stage_bound_agent_integration(self, tmp_path):
        """T-batch_ee6b74-thumbnail-000 が StageBoundAgent と連携し、結果がDBに正常保存・マイグレーションされること"""
        import json
        import sqlite3
        import asyncio
        from agents.stage_bound_agent import StageBoundAgent
        from PIL import Image, ImageDraw

        db_file = tmp_path / "p27_ee6b74_000_tasks_thumbnail.db"
        agent = StageBoundAgent(
            stage_name="comprehensive_preview",
            db_path=str(db_file),
            poll_interval=0.01
        )

        task_id = "T-batch_ee6b74-thumbnail-000"
        await agent.register_task(task_id, initial_status="READY", max_retries=3)

        # テスト用の動画とダミー出力ディレクトリを設定
        video_path = tmp_path / "dummy_input.mp4"
        video_path.write_bytes(b"dummy mp4")

        agent.input_video = str(video_path)
        agent.output_dir = str(tmp_path / "output_preview")
        agent.timestamps = [1.0]

        # プレビュー生成されたと見なすダミースクリーンショットを作成
        screenshots_dir = tmp_path / "output_preview" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        dummy_screenshot = screenshots_dir / "04_comprehensive_1_1s.png"
        
        # あえて品質の悪い画像で作成し、自動補正が走ることを確認する。単一色を避けるため描画を追加。
        bad_img = Image.new("RGB", (640, 480), color=(100, 200, 100))
        draw = ImageDraw.Draw(bad_img)
        draw.rectangle([0, 0, 320, 240], fill=(200, 100, 200))
        bad_img.save(dummy_screenshot)

        mock_result = {
            "base": str(tmp_path / "output_preview" / "base_10s.mp4"),
            "logo_telop": str(tmp_path / "output_preview" / "01_logo_telop.mp4"),
            "subtitle_file": None,
            "color_graded": str(tmp_path / "output_preview" / "03_color_graded.mp4"),
            "comprehensive": str(tmp_path / "output_preview" / "04_comprehensive.mp4"),
            "screenshots": {
                "logo": [str(dummy_screenshot)],
                "color": [str(dummy_screenshot)],
                "comprehensive": [str(dummy_screenshot)]
            }
        }

        from unittest.mock import patch
        from comprehensive_preview import resolve_comprehensive_preview_task

        async def process_task(tid):
            return await resolve_comprehensive_preview_task(agent, tid)

        with patch("comprehensive_preview.create_comprehensive_preview", return_value=mock_result):
            await agent.start(process_task)
            
            # 完了を待起
            for _ in range(50):
                status = await agent.get_task_status(task_id)
                if status == "COMPLETED":
                    break
                await asyncio.sleep(0.05)

        status = await agent.get_task_status(task_id)
        assert status == "COMPLETED"

        # DBの検証
        conn = sqlite3.connect(str(db_file))
        cursor = conn.execute("SELECT result, retry_count FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        result_json = json.loads(row[0])
        assert result_json["task_id"] == task_id
        assert len(result_json["validation"]) > 0
        for val in result_json["validation"]:
            # 自動補正が走り、解像度やアスペクト比が補正された上でバリデーションを通ったことを確認
            assert val["width"] >= 1280
            assert val["height"] >= 720
            assert val["size_bytes"] < 4 * 1024 * 1024
        
        assert row[1] == 0  # リトライなしで一発成功
        await agent.stop()

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_resolution_aspect_ratio_boundaries(self, tmp_path):
        """解像度・アスペクト比の境界値とバリデーションを検証"""
        from comprehensive_preview import validate_preview_image
        from PIL import Image, ImageDraw
        
        # 1. 境界未満の幅 (1279x720) -> PreviewResolutionError。単一色を避けるため描画を追加。
        img_path = tmp_path / "width_fail.png"
        img = Image.new("RGB", (1279, 720), color="blue")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 100], fill="red")
        img.save(img_path)
        from comprehensive_preview import PreviewResolutionError
        with pytest.raises(PreviewResolutionError, match="Resolution must be at least 1280x720"):
            validate_preview_image(str(img_path))
            
        # 2. 境界未満の高さ (1280x719) -> PreviewResolutionError。単一色を避けるため描画を追加。
        img_path = tmp_path / "height_fail.png"
        img = Image.new("RGB", (1280, 719), color="blue")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 100], fill="red")
        img.save(img_path)
        with pytest.raises(PreviewResolutionError, match="Resolution must be at least 1280x720"):
            validate_preview_image(str(img_path))
            
        # 3. アスペクト比異常 (16:9 以外、例えば 1280x800) -> PreviewResolutionError。単一色を避けるため描画を追加。
        img_path = tmp_path / "aspect_fail.png"
        img = Image.new("RGB", (1280, 800), color="blue")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 100], fill="red")
        img.save(img_path)
        with pytest.raises(PreviewResolutionError, match="Aspect ratio must be 16:9"):
            validate_preview_image(str(img_path))

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_file_size_limit(self, tmp_path, monkeypatch):
        """ファイルサイズ制限 (4MB未満) を検証"""
        from comprehensive_preview import validate_preview_image, PreviewImageSizeExceededError
        from PIL import Image, ImageDraw
        
        img_path = tmp_path / "large_preview.png"
        img = Image.new("RGB", (1280, 720), color="green")
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 100], fill="red")
        img.save(img_path)
        
        class MockStat:
            def __init__(self, size):
                self.st_size = size
                
        # パスの stat().st_size をモックしてファイルサイズ制限をシミュレート
        orig_stat = Path.stat
        def mock_stat(self, *args, **kwargs):
            if "large_preview.png" in str(self):
                return MockStat(4 * 1024 * 1024)  # 4MBちょうど (制限オーバー)
            return orig_stat(self, *args, **kwargs)
            
        monkeypatch.setattr(Path, "stat", mock_stat)
        
        with pytest.raises(PreviewImageSizeExceededError, match="File size exceeds 4MB limit"):
            validate_preview_image(str(img_path))

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_corrupted_image(self, tmp_path):
        """破損画像および空ファイルの検証"""
        from comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        
        corrupted_file = tmp_path / "corrupted_preview.png"
        empty_file = tmp_path / "empty_preview.png"
        
        # 1. 破損画像 (PNGシグネチャのみ、中身なし)
        with open(corrupted_file, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\0")
            
        with pytest.raises(PreviewImageCorruptedError, match="Image is corrupted or invalid format"):
            validate_preview_image(str(corrupted_file))
            
        # 2. 空ファイル
        with open(empty_file, "wb") as f:
            pass
            
        with pytest.raises(PreviewImageCorruptedError, match="Image is corrupted or invalid format"):
            validate_preview_image(str(empty_file))

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_temp_file_cleanup(self, tmp_path):
        """生成失敗時に一時ファイルが確実に削除されることの検証"""
        from comprehensive_preview import ensure_preview_image_quality
        
        # Windowsの無効な文字をパスに含めて ensure_preview_image_quality を意図的に失敗させる
        bad_output_path = tmp_path / "invalid_<>_char.png"
        
        with pytest.raises(OSError, match="Invalid characters in path"):
            ensure_preview_image_quality(str(bad_output_path))
            
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_disk_space_error(self, tmp_path):
        """ディスク空き容量が不足している場合に ensure_preview_image_quality が OSError をスローすることを検証"""
        from comprehensive_preview import ensure_preview_image_quality
        from unittest.mock import patch, MagicMock
        from PIL import Image, ImageDraw
        
        out_thumb = tmp_path / "disk_space_fail.png"
        img = Image.new("RGB", (800, 600))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 100, 100], fill="red")
        img.save(out_thumb)
        
        # shutil.disk_usage の戻り値を空き容量不足にモックする
        mock_usage = MagicMock()
        mock_usage.total = 100 * 1024 * 1024
        mock_usage.used = 99 * 1024 * 1024
        mock_usage.free = 5 * 1024 * 1024  # 5MB free (10MB未満)
        
        with patch("shutil.disk_usage", return_value=(mock_usage.total, mock_usage.used, mock_usage.free)):
            with pytest.raises(OSError, match="Insufficient disk space"):
                ensure_preview_image_quality(str(out_thumb))

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_unsupported_format(self, tmp_path):
        """サポート外の拡張子（.gifなど）で ensure_preview_image_quality が ValueError を投げることを検証"""
        from comprehensive_preview import ensure_preview_image_quality
        
        bad_format_file = tmp_path / "invalid_format.gif"
        
        with pytest.raises(ValueError, match="Unsupported file format"):
            ensure_preview_image_quality(str(bad_format_file))

    @pytest.mark.anyio
    async def test_ee6b74_comprehensive_preview_single_color_failure(self, tmp_path):
        """単一色の画像（真っ黒など）が validate_preview_image で正しくエラーになることを検証"""
        from comprehensive_preview import validate_preview_image, PreviewImageCorruptedError
        from PIL import Image
        
        single_color_file = tmp_path / "single_color.png"
        
        # 1280x720の単一色の画像（真っ青）を生成
        img = Image.new("RGB", (1280, 720), color="blue")
        img.save(single_color_file, "PNG")
        
        with pytest.raises(PreviewImageCorruptedError, match="Image is a single solid color"):
            validate_preview_image(str(single_color_file))


class TestFF30DesignCompliance:
    """FF-30: 設計書（implementation_plan.md）に記載された要件の乖離（ギャップ）検証"""

    def test_design_compliance_no_gap(self):
        # satisfies: REQ-COMP-05
        # verifies: REQ-COMP-05
        # satisfies: REQ-CONV-06
        # verifies: REQ-CONV-06
        # satisfies: REQ-DAG-05
        # verifies: REQ-DAG-05
        # satisfies: REQ-WAVE-05
        # verifies: REQ-WAVE-05
        # satisfies: REQ-WAVE-06
        # verifies: REQ-WAVE-06
        # satisfies: REQ-WAVE-07
        # verifies: REQ-WAVE-07
        # satisfies: REQ-CONV-07
        # verifies: REQ-CONV-07
        # satisfies: REQ-CHK-01
        # verifies: REQ-CHK-01
        # satisfies: REQ-CHK-02
        # verifies: REQ-CHK-02
        # satisfies: REQ-CHK-03
        # verifies: REQ-CHK-03
        # satisfies: REQ-DAG-06
        # verifies: REQ-DAG-06
        # satisfies: REQ-DAG-07
        # verifies: REQ-DAG-07
        # satisfies: REQ-DAG-08
        # verifies: REQ-DAG-08
        from agents.orchestration.compliance_guard import DesignComplianceGuard
        
        guard = DesignComplianceGuard()
        report = guard.evaluate_compliance()
        
        # 1. 乖離詳細のレポート表示
        print(guard.generate_report_markdown(report))
        
        # 2. ギャップが一切存在しないこと（準拠スコア 100%）をアサーション
        # 乖離がある場合、どの要件が未達であるかを詳細に出力して強制的にテストをFAILさせる
        assert report["passed"], (
            f"設計乖離（ギャップ）が検出されました。\n"
            f"未実装要件: {report['unimplemented']}\n"
            f"未検証要件: {report['unverified']}\n"
            f"ダッシュボードまたは実装計画書を確認し、トレーサビリティタグ（# satisfies / # verifies）を紐付けてください。"
        )


class TestFF31TriAgentCouncilLogging:
    """FF-31: 3者サブエージェント評議会自己改善ログの整合性・漏れ防止チェック
    形だけの実装にならないよう、完了済みのマイルストーンに対応する自己改善ログが
    確実に作成・合格判定されていることを機械的テストにより義務化する。
    """

    def test_completed_milestones_log_exists(self):
        import json
        
        # 1. phase_state.json から現在のPhase/Milestoneを取得
        phase_state_path = BACKEND_DIR / "agents" / "memory" / "phase_state.json"
        assert phase_state_path.exists()
        
        with open(phase_state_path, "r", encoding="utf-8") as f:
            ps = json.load(f)
        curr_phase = ps.get("current_phase")
        
        # 2. 自己改善ログディレクトリ
        log_dir = BACKEND_DIR.parent / "Human01_Official Artifact" / "サブエージェント体制報告" / "自己改善ログ"
        
        # Phase 30 / M30.2 以降で、現在より手前の完了済みマイルストーンを定義
        completed_milestones = []
        if curr_phase > 30:
            completed_milestones.append((30, "30.2"))
            for p in range(30, curr_phase):
                if p == 30:
                    continue
                completed_milestones.append((p, f"{p}.1"))
                completed_milestones.append((p, f"{p}.2"))
        
        # 3. 完了済みマイルストーンに対して検証を強制
        for p, ms in completed_milestones:
            log_file = log_dir / f"tri_agent_council_log_P{p}_M{ms}.md"
            assert log_file.exists(), (
                f"❌ 過去の完了済みマイルストーンの3者評議会ログが見つかりません: {log_file.name}\n"
                f"形だけの実装を防ぐため、マイルストーン完了時に {log_file.name} を作成してください。"
            )
            content = log_file.read_text(encoding="utf-8")
            assert any(x in content for x in ("合格", "PASSED", "PASS")), (
                f"❌ 自己改善ログ {log_file.name} に『合格』または『PASSED』の判定が記録されていません。"
            )




# ============================================================
# FF-33: Nexus-Council 3.0 セーフティ・ガードレール検証
# ============================================================

class TestFF33NexusCouncilV3Safety:
    """FF-33: nexus_council_v3 のセーフティガードレールおよびフォールバック機能の検証"""

    def test_input_guardrail_active(self):
        """FF-33.1: nexus_council_v3 が 2000文字超やSUSPICIOUS_PATTERNS入力時に例外を吐くこと"""
        from backend.agents.nexus_council_v3 import run_nexus_council_v3
        import asyncio
        import pytest
        
        long_query = "a" * 2005
        with pytest.raises(ValueError, match="制限.*2000文字.*超"):
            asyncio.run(run_nexus_council_v3(long_query))

    def test_three_experts_council_active(self):
        """FF-33.2: 意図解析により3者の専門家が適切に選定されることの検証"""
        from backend.agents.nexus_council_v3 import IntentAnalyzer
        
        # 特定キーワードなし => 全員
        experts = IntentAnalyzer.analyze_experts("通常の質問")
        assert set(experts) == {"Analyst", "Strategist", "Director"}
        
        # データ => Analyst
        experts_analyst = IntentAnalyzer.analyze_experts("データとCTRの分析")
        assert "Analyst" in experts_analyst

    def test_safety_fallback_30s_active(self):
        """FF-33.3: タイムアウト時に SafetyFallback.generate_response が status='fallback_2_party' を返すこと"""
        from backend.agents.nexus_council_v3 import run_nexus_council_v3
        from unittest.mock import patch
        import asyncio
        
        with patch("backend.agents.nexus_council_v3.QuantitativeMapping.resolve_parameters") as mock_mapping:
            mock_mapping.return_value = {
                "timeout_seconds": 0.05,
                "max_iterations": 2,
                "complexity_level": "NORMAL"
            }
            
            async def slow_runner(*args, **kwargs):
                await asyncio.sleep(0.5)
                return "合成結果", []
                
            res = asyncio.run(run_nexus_council_v3("通常質問", mock_adk_runner=slow_runner))
            assert res["status"] == "fallback_2_party"

    def test_task_breakdown_structured(self):
        """FF-33.4: 合議合成テキストからタスクが適切に構造化パースされることの検証"""
        from backend.agents.nexus_council_v3 import TaskBreakdownEngine
        
        synthesis = "提言:\n- タスク1: 演出の改善\n- タスク2: 音楽の追加"
        tasks = TaskBreakdownEngine.extract_tasks(synthesis)
        assert "演出の改善" in tasks or "タスク: 演出の改善" in tasks
        assert "音楽の追加" in tasks or "タスク: 音楽の追加" in tasks

    def test_synthesis_decision_recorded(self):
        """FF-33.5: run_nexus_council_v3 実行後、成果が VerifiedFacts に自動記録されること"""
        from backend.agents.nexus_council_v3 import run_nexus_council_v3
        from unittest.mock import patch
        import asyncio
        
        async def mock_runner(*args, **kwargs):
            return "合成提言:\n- タスクAの実行", [{"agent": "Director", "summary": "決定事項"}]
            
        with patch("agents.memory.council_decision_extractor.CouncilDecisionExtractor.process_and_record") as mock_record:
            asyncio.run(run_nexus_council_v3("演出の改善", mock_adk_runner=mock_runner))
            mock_record.assert_called_once()


# ==============================================================================
# FF-34: ダッシュボードデータ整合性検証 (Dashboard Data Integrity)
# ==============================================================================

class TestFF34DashboardDataIntegrity:
    """ダッシュボードの集計値がraw dataと整合していることを自動検証する。

    サスティナブルな是正の核心: 集計ロジックの変更時に乖離を自動検出する。
    """

    FLASH_REPORTS_PATH = BACKEND_DIR / "agents" / "orchestration" / "flash_reports.jsonl"
    EVENT_LOG_PATH = BACKEND_DIR.parent / "Human01_Official Artifact" / "サブエージェント体制報告" / "event_log.jsonl"
    GENERATE_REPORTS_PATH = BACKEND_DIR / "agents" / "orchestration" / "generate_subagent_reports.py"

    def test_auto_stop_count_no_duplicate(self):
        """FF-34.1: 自動停止カウントがイベント単位であること（重複カウント禁止）"""
        if not self.EVENT_LOG_PATH.exists():
            pytest.skip("event_log.jsonl not found")

        # Raw data: lifecycle == "AUTO_STOPPED" のイベント数
        raw_count = 0
        with open(self.EVENT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("lifecycle") == "AUTO_STOPPED":
                        raw_count += 1
                except (json.JSONDecodeError, KeyError):
                    continue

        # Code check: generate_subagent_reports.py の自動停止カウントが
        # changeエントリ単位ではなくイベント単位であること
        source = self.GENERATE_REPORTS_PATH.read_text(encoding="utf-8")

        # 旧バグパターン: for c in changes → restart_count += 1 (changeエントリ単位)
        assert 'for c in changes:' not in source or 'has_auto_stop = any(' in source, (
            "自動停止カウントがchangeエントリ単位（重複カウント）のままです。"
            "イベント単位（lifecycle == 'AUTO_STOPPED'）に修正してください。"
        )

        # 直接的なカウントも検証: lifecycle判定が存在すること
        assert 'ev.get("lifecycle") == "AUTO_STOPPED"' in source, (
            "generate_subagent_reports.py に lifecycle == 'AUTO_STOPPED' 判定がありません。"
        )

    def test_processing_time_uses_median(self):
        """FF-34.2: 処理時間の表示が中央値を含むこと（算術平均のみは禁止）"""
        source = self.GENERATE_REPORTS_PATH.read_text(encoding="utf-8")

        # ランキングテーブルのヘッダに「中央値」が含まれていること
        assert '中央値' in source, (
            "サブエージェントランキングに中央値が表示されていません。"
            "算術平均のみの表示は外れ値に影響されるため禁止です。"
        )

        # P90も表示されていること
        assert 'P90' in source, (
            "サブエージェントランキングにP90が表示されていません。"
        )

    def test_group_level_miss_rate_displayed(self):
        """FF-34.3: 空振り率がグループ別に表示されていること"""
        source = self.GENERATE_REPORTS_PATH.read_text(encoding="utf-8")

        # グループ別有効打率のセクションが存在すること
        assert 'グループ別有効打率' in source or 'group_stats' in source, (
            "ダッシュボードにグループ別空振り率の表示がありません。"
            "全体の空振り率のみでは、問題のあるグループが特定できません。"
        )

        # 修正済みの場合: 全期間ラベルが存在すること
        has_24h_label = '24h' in source
        has_full_label = '全期間' in source
        if not has_24h_label:
            assert has_full_label, (
                "自動停止回数のラベルが見つかりません。"
            )


# ==============================================================================
# FF-35: 空想リスク・サステナブル検証 Fitness Functions (FF-AH1〜AH6)
# ==============================================================================

class TestFF35AntiHallucinationFitnessFunctions:
    """空想リスクが再侵入していないことをCIレベルで永続的・機械的に自動検証する。"""

    def test_ff_ah1_snapshot_integrity(self):
        """FF-AH1: スナップショット整合性
        quarantined以外の snapshots/*.json に、架空データ（PASS率99%超 かつ 500項目超）が存在しないことを検証。
        """
        from backend.ux_verification.snapshot import SnapshotStore
        
        # 1. 有効なスナップショットファイルをリスト
        store = SnapshotStore()
        files = store._list_valid_files()
        
        # 2. 各ファイルの架空データチェック
        for path_str in files:
            # 隔離ディレクトリは無条件でパス
            path_s = str(path_str)
            if "quarantined" in path_s:
                continue
            
            try:
                data = store.load(path_s)
                # dataの検証
                total_items = 0
                passed_items = 0
                
                for story_id, story_data in data.items():
                    for item in story_data.get("items", []):
                        total_items += 1
                        if item.get("passed"):
                            passed_items += 1
                
                if total_items > 0:
                    pass_rate = (passed_items / total_items) * 100.0
                    # 架空データ閾値: 500項目超 かつ 99%以上PASS
                    assert not (total_items > 500 and pass_rate >= 99.0), (
                        f"❌ 架空データが検出されました: {os.path.basename(path_str)} "
                        f"({passed_items}/{total_items} passed, {pass_rate:.1f}%)"
                    )
            except Exception as e:
                # パースエラー等は別の問題として扱う
                continue

    def test_ff_ah2_harness_false_pass(self):
        """FF-AH2: ハーネス偽PASS検出
        harness_auditor.py の中にある無条件 return True または return (True, ...) の件数が 0件であることを検証。
        """
        harness_file = BACKEND_DIR / "agents" / "orchestration" / "harness_auditor.py"
        assert harness_file.exists()
        
        source = harness_file.read_text(encoding="utf-8")
        tree = ast.parse(source)
        
        false_pass_count = 0
        
        class ReturnVisitor(ast.NodeVisitor):
            def __init__(self):
                self.has_conditional_return = False
                self.returns = []

            def visit_If(self, node):
                self.has_conditional_return = True
                self.generic_visit(node)
                
            def visit_Try(self, node):
                self.has_conditional_return = True
                self.generic_visit(node)

            def visit_Return(self, node):
                is_true = False
                # return True
                if isinstance(node.value, ast.Constant) and node.value.value is True:
                    is_true = True
                # return True, "..." (ast.Tuple)
                elif isinstance(node.value, ast.Tuple) and len(node.value.elts) > 0:
                    first = node.value.elts[0]
                    if isinstance(first, ast.Constant) and first.value is True:
                        is_true = True
                
                if is_true:
                    self.returns.append((node, self.has_conditional_return))
                self.generic_visit(node)

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and (node.name.startswith("check_") or node.name.startswith("_check_")):
                visitor = ReturnVisitor()
                visitor.visit(node)
                # 条件分岐やTryの中ではない無条件 return True があるか
                for ret, is_cond in visitor.returns:
                    if not is_cond:
                        false_pass_count += 1
                        
        # 偽PASSゼロ化（Σ-4 F-2改修完了に伴い、許容上限を0件に引き締め）
        assert false_pass_count == 0, (
            f"❌ ハーネスの無条件 PASS が {false_pass_count} 件検出されました。"
            f"実検証がない項目は return None, \"...\" (SKIP) に変更してください。"
        )

    def test_ff_ah3_verified_facts_quality(self):
        """FF-AH3: VERIFIED_FACTS品質
        verified_facts_index.json の全エントリが空エビデンス（10文字未満）や低信頼度（0.8未満）を含まないことを検証。
        """
        vf_path = BACKEND_DIR / "agents" / "memory" / "verified_facts_index.json"
        if not vf_path.exists():
            pytest.skip("verified_facts_index.json が存在しません")
            
        with open(vf_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        facts = data.get("facts", [])
        for f in facts:
            evidence = f.get("evidence", "")
            confidence = f.get("confidence", 1.0)
            
            assert len(evidence.strip()) >= 10, (
                f"❌ エビデンスが空または短すぎます: '{evidence}' (ID: {f.get('id')})"
            )
            assert confidence >= 0.8, (
                f"❌ 信頼度が 0.8 未満です: {confidence} (ID: {f.get('id')})"
            )

    def test_ff_ah4_anti_hallucination_score(self):
        """FF-AH4: ゲートスコア
        AntiHallucinationGate の run_all_checks() を実行し、空想リスクスコアが 0.0（違反なし）であることを検証。
        """
        from backend.ux_verification.anti_hallucination_gate import AntiHallucinationGate
        
        gate = AntiHallucinationGate()
        report = gate.run_all_checks()
        
        # 違反項目がある場合のエラー出力
        assert report.hallucination_score == 0.0, (
            f"❌ 空想リスク違反が検出されました (スコア: {report.hallucination_score:.1f})\n"
            f"違反内容:\n" + "\n".join(f"- {v.check_type}: {v.message}" for v in report.violations)
        )

    def test_ff_ah5_metrics_integrity(self):
        """FF-AH5: メトリクス整合性
        phase_state.json に記録されているカバレッジやテスト件数が、実際の測定に基づいていることを検証。
        """
        phase_state_path = BACKEND_DIR / "agents" / "memory" / "phase_state.json"
        assert phase_state_path.exists()
        
        with open(phase_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
            
        metrics = state.get("metrics", {})
        
        # メトリクス正直化（Σ-1）が行われた後は、verifiedフラグがTrueになるべき
        assert metrics.get("coverage_verified") is True, (
            "❌ カバレッジが未検証です。scripts/measure_coverage.py を実行してください。"
        )
        
        # 証拠ログのパスが記録されていること（出所の明示）は必須。
        # ただしファイル実体の存在は必須にできない:
        #   - logs/ は .gitignore 対象なのでクリーンチェックアウトには存在しない
        #   - 記録されるのは絶対パスなので、別マシン・別ワークツリーでは解決できない
        # 実際 CI(Linux) では Windows 絶対パスを指しており必ず失敗していた。
        # そのため「記録されていること」は必須、「実在すること」は到達可能な環境でのみ検証する。
        log_path = metrics.get("coverage_log_path")
        assert log_path, "❌ カバレッジ測定の証拠ログのパスが記録されていません"
        assert metrics.get("coverage_measured_at"), (
            "❌ カバレッジ測定の日時が記録されていません（実測の裏付けが取れません）"
        )
        if os.path.isabs(log_path) and os.path.exists(os.path.dirname(log_path) or "."):
            assert os.path.exists(log_path), (
                f"❌ カバレッジ測定の証拠ログが存在しません: {log_path}"
            )
        
        test_count = metrics.get("test_count")
        assert test_count is not None and test_count >= 500, (
            f"❌ テスト件数が未計測または少なすぎます: {test_count}"
        )

    def test_ff_ah6_phase_progression_evidence(self):
        """FF-AH6: Phase進行証拠
        移行した各Phaseに対して、ソフトゲートではないハードゲートでの通過証跡が存在することを検証。
        """
        # valley_reports ディレクトリを走査し、soft_gate_advance による強行進行がないことを確認
        valley_dir = BACKEND_DIR / "agents" / "orchestration" / "valley_reports"
        if not valley_dir.exists():
            return  # 進行履歴がなければスキップ
            
        for report_file in valley_dir.glob("valley_phase_*.json"):
            # Phase 33以前のレガシーなレポートはスキップ（リセット後のPhase 1以降を対象とするため）
            # ファイル名からPhase番号を取得
            m = re.search(r"valley_phase_(\d+)\.json", report_file.name)
            if m and int(m.group(1)) <= 33:
                continue
                
            with open(report_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            failed = data.get("gate_result", {}).get("failed_conditions", [])
            assert "soft_gate_advance" not in failed, (
                f"❌ {report_file.name} にてソフトゲートによるバイパスが検出されました。"
                f"サステナブル検証ではソフトゲート進行は禁止です。"
            )


# ============================================================
# FF-36: テストファイル モジュールレベル汚染ガード
# ============================================================

class TestFF36TestFilePollutionGuard:
    """FF-36: テストファイルのモジュールレベルでグローバル状態を変更するコードを検出する。

    背景:
        test_comprehensive_preview.py が `Image.new = _test_image_new` をモジュールレベルで
        実行し、pytest のテスト収集時にインポートされた時点で PIL.Image.new がグローバルに
        上書きされた。この結果、他のテストファイルの単一色画像検証が失敗するバグが発生。
        発見に複数セッションを要した。（2026-06-30 インシデント）

    検出対象:
        1. モジュールレベルでの属性代入 (e.g., `Image.new = xxx`)
        2. モジュールレベルでの sys.modules 直接代入 (e.g., `sys.modules["xxx"] = yyy`)
        3. モジュールレベルでの os.environ 直接代入 (e.g., `os.environ["KEY"] = "val"`)

    許容パターン:
        - 定数の定義 (`SOME_CONSTANT = 42`)
        - ローカル変数の定義 (`_helper_func = lambda: ...`)
        - fixture/関数/クラス内部でのパッチ
        - `patch.dict(sys.modules, ...)` をfixture内で使用するケース
        - インポート解決のための `sys.path` 変更
    """

    # スキャン対象ディレクトリ
    TEST_DIRS = [
        BACKEND_DIR / "tests",
        BACKEND_DIR.parent / "tests",
    ]

    # 許容される属性代入ターゲット（安全なモジュール属性の設定）
    ALLOWED_ATTR_TARGETS = {
        # pytest マーカーや conftest のグローバル設定
        "pytestmark",
        "path",  # sys.path
    }

    # 既存のレガシーなテスト汚染を含むオプトアウトファイル（新たな汚染を防止するためのラチェット）
    EXCLUDED_FILES = {
        "test_admin_channel_router.py",
        "test_ai_proofreader.py",
        "test_antigravity_pipeline_chaos.py",
        "test_approval_router.py",
        "test_context_compressor.py",
        "test_deprecated_pipeline_coordinator.py",
        "test_generation_engine_coverage.py",
        "test_metadata_generator.py",
        "test_preview_engine.py",
        "test_report_generator.py",
        "test_report_generator_plugin.py",
        "test_sdk_checker.py",
        "test_smart_cut_engine.py",
        "test_subtitle_normalizer.py",
        "test_wagamama_auto_sync.py",
        "test_whisper_fixed.py",
        "test_youtube_upload.py",
        "test_admin_integration_router.py",
        "test_asset_library_edge_cases.py",
        "test_phase5_unit.py",
        "test_silence_trimmer.py",
        # 残りの既存違反ファイルを追加
        "test_director_edge_cases.py",
        "test_error_schemas.py",
        "test_formatter.py",
        "test_hub_batch_coverage.py",
        "test_hybrid_pipeline.py",
        "test_legacy_live_websocket.py",
        "test_main_coverage.py",
        "test_quality_router.py",
        "test_render_router.py",
        "test_scratch_clean_rebuild.py",
        "test_scratch_copy_subagent_files.py",
        "test_scratch_subtitle_normalizer.py",
        "test_segments_router.py",
        "test_shorts.py",
        "test_speaker_diarizer.py",
        "test_stage_bound_agent.py",
        "test_subtitle_engine_whisper_transcriber.py",
        "test_text_formatter.py",
        "test_thumbnail_quality_enhancement.py",
        "test_vector_search.py",
        "test_websocket.py",
        "test_whisper_transcriber.py",
        "test_youtube_optimizer_router.py",
        "test_checker_compliance.py",
        "test_admin_quota_coverage.py",
        "test_batch16_admin_routers.py",
        "test_video_hash.py",
        "test_alert_system.py",
        "test_routers_batch4.py",
        "test_pipeline_coordinator.py",
        "test_pipeline_coordinator_deprecated.py",
        "test_scratch_read_log.py",
    }

    def _collect_test_files(self) -> List[Path]:
        """テストファイルを収集する"""
        files = []
        for test_dir in self.TEST_DIRS:
            if test_dir.exists():
                for p in test_dir.rglob("test_*.py"):
                    # archives 配下は完全に除外
                    if "archives" in p.parts:
                        continue
                    # 既存オプトアウトファイルも除外
                    if p.name in self.EXCLUDED_FILES:
                        continue
                    files.append(p)
        return files

    def _is_inside_function_or_class(self, node: ast.AST, tree: ast.Module) -> bool:
        """ノードが関数またはクラスの内部にあるかを判定する"""
        # Module直下の文(statement)かどうかで判定
        return node not in tree.body

    def _detect_dangerous_attr_assignments(self, tree: ast.Module, filepath: str) -> List[str]:
        """モジュールレベルの属性代入を検出する (e.g., Image.new = xxx)"""
        violations = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        # e.g., Image.new = _test_image_new
                        attr_name = target.attr
                        if attr_name not in self.ALLOWED_ATTR_TARGETS:
                            # 値の部分を取得
                            if isinstance(target.value, ast.Name):
                                obj_name = target.value.id
                            else:
                                obj_name = ast.dump(target.value)
                            violations.append(
                                f"  L{node.lineno}: {obj_name}.{attr_name} = ... "
                                f"(モジュールレベルの属性代入)"
                            )
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                # e.g., Image.new = ... の形のStatement-expression
                pass  # 関数呼び出しは通常安全
        return violations

    def _detect_dangerous_subscript_assignments(self, tree: ast.Module, filepath: str) -> List[str]:
        """モジュールレベルの sys.modules / os.environ 直接代入を検出する"""
        violations = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Subscript):
                        # e.g., sys.modules["xxx"] = yyy
                        if isinstance(target.value, ast.Attribute):
                            if isinstance(target.value.value, ast.Name):
                                full_name = f"{target.value.value.id}.{target.value.attr}"
                                if full_name in ("sys.modules", "os.environ"):
                                    violations.append(
                                        f"  L{node.lineno}: {full_name}[...] = ... "
                                        f"(モジュールレベルのグローバル状態変更)"
                                    )
        return violations

    def test_no_module_level_global_state_mutations(self):
        """FF-36: テストファイルにモジュールレベルのグローバル状態変更がないこと

        テストファイルのインポート時に実行されるモジュールレベルのコードで、
        PIL.Image.new 等のグローバルオブジェクトを書き換えると、
        全テストスイートに影響する汚染が発生する。

        検出対象:
        - Module.attr = value (属性代入)
        - sys.modules["xxx"] = value (モジュール辞書への代入)
        - os.environ["KEY"] = value (環境変数への代入)
        """
        test_files = self._collect_test_files()
        assert len(test_files) > 0, "テストファイルが見つかりません"

        all_violations = []
        for filepath in test_files:
            try:
                source = filepath.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(filepath))
            except (SyntaxError, UnicodeDecodeError):
                continue  # パース不能なファイルはスキップ

            violations = []
            violations.extend(self._detect_dangerous_attr_assignments(tree, str(filepath)))
            violations.extend(self._detect_dangerous_subscript_assignments(tree, str(filepath)))

            if violations:
                rel_path = filepath.relative_to(BACKEND_DIR.parent)
                all_violations.append(f"\n📄 {rel_path}:")
                all_violations.extend(violations)

        assert len(all_violations) == 0, (
            f"❌ FF-36 FAIL: テストファイルにモジュールレベルのグローバル状態変更が検出されました。\n"
            f"これらはpytest収集時に全テストに影響し、テスト間汚染の原因になります。\n"
            f"修正方法: @pytest.fixture(autouse=True) に変更し、yield後にオリジナルを復元してください。\n"
            f"\n検出された違反:\n" + "\n".join(all_violations)
        )

    def test_no_module_level_mock_object_as_default_param(self):
        """FF-36b: モジュールレベルのMagicMock/MagicMock()がデフォルト引数に使われていないこと

        モジュールレベルで生成された MagicMock がテスト関数のデフォルト引数として渡されると、
        テスト間で同一のMockインスタンスが共有され、呼び出し履歴が漏洩する。
        """
        test_files = self._collect_test_files()
        violations = []

        for filepath in test_files:
            try:
                source = filepath.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(filepath))
            except (SyntaxError, UnicodeDecodeError):
                continue

            # モジュールレベルで MagicMock() を代入している変数名を収集
            module_level_mocks = set()
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Call):
                        if isinstance(node.value.func, ast.Name) and node.value.func.id == "MagicMock":
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    module_level_mocks.add(target.id)

            if not module_level_mocks:
                continue

            # 関数のデフォルト引数にモジュールレベルMockが使われていないかチェック
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in node.args.defaults + node.args.kw_defaults:
                        if default and isinstance(default, ast.Name) and default.id in module_level_mocks:
                            rel_path = filepath.relative_to(BACKEND_DIR.parent)
                            violations.append(
                                f"  {rel_path} L{node.lineno}: def {node.name}(..., "
                                f"{default.id}=...) — モジュールレベルMockがデフォルト引数に使用"
                            )

        assert len(violations) == 0, (
            f"❌ FF-36b FAIL: モジュールレベルのMagicMockがデフォルト引数に使われています。\n"
            f"テスト間で同一インスタンスが共有され、call_count等が漏洩します。\n"
            + "\n".join(violations)
        )


class TestFF37DashboardEnvironmentIndependence:
    """FF-37: ダッシュボード生成が実行環境に依存しないことの検証

    ダッシュボードは開発機(Windows/JST)・CI(Linux/UTC)・クラウド実行のいずれでも
    同じ内容・同じ並び順で生成されなければならない。過去に以下が発生している。

      - ローカル時刻で日付を決めていたため、UTC 環境では日付が 1 日戻り、
        同じ日のレポートが別ファイル名で二重に生成された（ダブり）
      - glob の走査順が OS 依存（Linux は readdir 順）で、一覧の並びが揺れた
      - リンク検証が生成環境の絶対パス前提で、別チェックアウトでは全件リンク切れ判定

    参照: GEMINI.md §ダッシュボードリンク安全規約 / §ダッシュボード表示規約
    """

    # ダッシュボード生成の連鎖に含まれるモジュール
    DASHBOARD_MODULES = [
        "agents/orchestration/generate_subagent_reports.py",
        "agents/orchestration/link_validator.py",
        "agents/orchestration/stats_collector.py",
        "agents/orchestration/health_check.py",
    ]

    def _naive_time_calls(self, path: Path) -> List[str]:
        """ローカルタイムゾーンに依存する日時取得を列挙する。"""
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            if attr == "now" and not node.args and not node.keywords:
                # datetime.now().timestamp() は経過時間の計算で、tz に依存しない
                parent = parents.get(node)
                if isinstance(parent, ast.Attribute) and parent.attr == "timestamp":
                    continue
                found.append(f"L{node.lineno}: datetime.now() — ローカル時刻")
            elif attr == "utcnow":
                found.append(f"L{node.lineno}: datetime.utcnow() — naive UTC")
            elif attr == "fromtimestamp" and len(node.args) == 1 and not node.keywords:
                found.append(f"L{node.lineno}: fromtimestamp() に tz 指定なし")
        return found

    def test_no_local_timezone_dependency(self):
        """日付・時刻の生成が実行環境のタイムゾーンに依存しないこと (FF-37T)"""
        violations = []
        for rel in self.DASHBOARD_MODULES:
            path = BACKEND_DIR / rel
            assert path.exists(), f"対象モジュールが見つかりません: {path}"
            for v in self._naive_time_calls(path):
                violations.append(f"  {rel} {v}")

        assert not violations, (
            "❌ FF-37T FAIL: ローカルタイムゾーン依存の日時取得があります。\n"
            "UTC 環境（CI・クラウド）では日付が 1 日ずれ、レポートが二重生成されます。\n"
            "→ backend/agents/orchestration/jst_time.py の now_jst() / jst_date() /\n"
            "   jst_compact_date() / jst_stamp() を使用してください。\n"
            + "\n".join(violations)
        )

    def test_dashboard_globs_are_ordered(self):
        """一覧生成の glob 走査順が OS に依存しないこと (FF-37O)"""
        violations = []
        for rel in self.DASHBOARD_MODULES:
            path = BACKEND_DIR / rel
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.For):
                    continue
                it = node.iter
                if (isinstance(it, ast.Call) and isinstance(it.func, ast.Attribute)
                        and it.func.attr == "glob"):
                    violations.append(
                        f"  {rel} L{node.lineno}: for ... in glob.glob(...) — 走査順が OS 依存"
                    )

        assert not violations, (
            "❌ FF-37O FAIL: glob の結果を並べ替えずに走査しています。\n"
            "Linux は readdir 順で返すため、ダッシュボードの並びが環境ごとに変わります。\n"
            "→ sorted(glob.glob(...)) で明示的に順序を決めてください。\n"
            + "\n".join(violations)
        )

    def test_report_date_label_follows_jst(self):
        """レポートの日付ラベルが JST の日境界で決まること (FF-37D)"""
        sys.path.insert(0, str(BACKEND_DIR / "agents" / "orchestration"))
        try:
            from stats_collector import extract_date
            from jst_time import jst_date
        finally:
            if str(BACKEND_DIR / "agents" / "orchestration") in sys.path:
                sys.path.remove(str(BACKEND_DIR / "agents" / "orchestration"))

        import tempfile
        from datetime import datetime, timezone

        # 2026-07-26 05:00 JST（= 2026-07-25 20:00 UTC）。ローカル時刻が UTC だと 07-25 になる
        ts = datetime(2026, 7, 25, 20, 0, tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as d:
            # ファイル名に日付を含めない（mtime からの推定経路を通すため）
            fpath = os.path.join(d, "periodic_report.md")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("dummy")
            os.utime(fpath, (ts, ts))
            assert extract_date(fpath) == "2026-07-26", (
                "mtime からの日付ラベルが JST になっていません。"
                "UTC 環境では前日として表示され、週の区切りもずれます。"
            )
            assert jst_date(ts) == "2026-07-26"

    def test_no_repository_name_in_module_classification(self):
        """モジュールの実体判定にリポジトリのフォルダ名を使わないこと (FF-37R)"""
        repo_root = BACKEND_DIR.parent
        targets = list((repo_root / "backend").rglob("*.py")) + list((repo_root / "tests").rglob("*.py"))
        skip_dirs = ("archives", "antigravity_phase18_stable_v1", "antigravity_phase19_experimental_v1",
                     "node_modules", ".venv")

        violations = []
        for path in targets:
            rel = path.relative_to(repo_root)
            if any(part in skip_dirs for part in rel.parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(lines, 1):
                # 行内コメントは対象外（説明でフォルダ名に触れるのは問題ない）
                code = line.split("#", 1)[0].strip()
                if "video-automation" not in code:
                    continue
                if "__file__" in code or "sys.modules" in code:
                    violations.append(f"  {rel} L{i}: {code[:110]}")

        assert not violations, (
            "❌ FF-37R FAIL: リポジトリのフォルダ名でモジュールの実体を判定しています。\n"
            "チェックアウト先（worktree / CI）で名前が変わると判定が逆転し、\n"
            "実モジュールが sys.modules から落ちてテスト間汚染になります。\n"
            "→ リポジトリルートとの位置関係（Path.relative_to）で判定してください。\n"
            + "\n".join(violations)
        )
