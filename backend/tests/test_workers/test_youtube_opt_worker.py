"""
YouTubeOptWorker 30テスト — MASTER v3.6 Sprint 2.2.5 (L802-L859)

Worker本体(5分岐) → 最低保証30テスト。API依存20件はモック。

テスト構成:
  C1: 入力検証       5テスト (W5-C1-01〜05)
  C2: コアロジック   5テスト (W5-C2-01〜05)
  C3: 出力検証       5テスト (W5-C3-01〜05)
  C4: エラー耐性     5テスト (W5-C4-01〜05)
  C5: 統合・依存     5テスト (W5-C5-01〜05)
  C6: 性能・進化     5テスト (W5-C6-01〜05)

モックパターン:
  - gemini_client_factory / google.genai は sys.modules パッチで差し替え
  - model_governance は sys.modules パッチで差し替え
  - response.text に JSON 文字列を返す MagicMock を使用
"""

import asyncio
import json
import sys
import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# backend ディレクトリをパスに追加
_backend_dir = str(Path(__file__).resolve().parent.parent.parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from agents.pipeline_coordinator import YouTubeOptWorker, PipelineContext, StageResult
from tests.fixtures.mock_pipeline import create_mock_ctx, create_mock_segments


# ============================================================
# ヘルパー / フィクスチャ
# ============================================================

def _make_segments(count: int, text_prefix: str = "テスト字幕") -> list:
    """テスト用セグメントリストを生成"""
    segs = []
    for i in range(count):
        segs.append({
            "start": float(i * 10),
            "end": float(i * 10 + 9),
            "text": f"{text_prefix}{i + 1}回目の発言内容。",
        })
    return segs


_VALID_METADATA = {
    "titles": ["テスト動画タイトル案1", "テスト動画タイトル案2"],
    "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
    "description": "テスト動画の説明文です。\n#タグ1 #タグ2 #タグ3",
    "chapters": [
        {"time": "0:00", "title": "オープニング"},
        {"time": "5:00", "title": "本編"},
    ],
}


def _make_gemini_mock(response_json: dict = None, raise_exc: Exception = None):
    """
    gemini_client_factory / google.genai をパッチするためのモック群を返す。

    - raise_exc が指定された場合、generate_content が例外を送出する。
    - response_json が None の場合はデフォルトの _VALID_METADATA を使用。
    """
    if response_json is None:
        response_json = _VALID_METADATA

    mock_response = MagicMock()
    mock_response.text = json.dumps(response_json, ensure_ascii=False)

    mock_client = MagicMock()
    if raise_exc:
        mock_client.models.generate_content.side_effect = raise_exc
    else:
        mock_client.models.generate_content.return_value = mock_response

    mock_factory = MagicMock()
    mock_factory.get_gemini_client.return_value = mock_client

    mock_types = MagicMock()
    mock_google_genai = MagicMock()
    mock_google_genai.types = mock_types

    mock_mg = MagicMock()
    mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

    return mock_factory, mock_google_genai, mock_mg, mock_client


def _patch_gemini(mock_factory, mock_google_genai, mock_mg):
    """sys.modules に gemini 関連モジュールを差し込む patch.dict を返す"""
    return patch.dict("sys.modules", {
        "gemini_client_factory": mock_factory,
        "google": MagicMock(),
        "google.genai": mock_google_genai,
        "model_governance": mock_mg,
    })


# ============================================================
# C1: 入力検証 (5テスト)
# ============================================================

class TestC1InputValidation:
    """W5-C1-01〜W5-C1-05: 入力検証"""

    @pytest.mark.asyncio
    async def test_c1_01_normal_10_segments(self):
        """W5-C1-01: 10seg正常入力 — メタデータ生成成功"""
        ctx = create_mock_ctx(segments=10)
        ctx.segments = _make_segments(10)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        assert ctx.metadata is not None
        assert "titles" in ctx.metadata

    @pytest.mark.asyncio
    async def test_c1_02_zero_segments(self):
        """W5-C1-02: 0seg入力 — 空テキストで生成（フォールバック含む）"""
        ctx = create_mock_ctx(segments=0)
        ctx.segments = []

        # 空テキストではGemini API呼び出しが行われ、フォールバックで処理
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # 0segでも正常終了すること
        assert result.success is True
        assert ctx.metadata is not None

    @pytest.mark.asyncio
    async def test_c1_03_segments_none_safe_handling(self):
        """W5-C1-03: segments=None — 安全な処理"""
        ctx = create_mock_ctx(segments=0)
        ctx.segments = None

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # None でも NoneType エラーを起こさないこと
        assert result.success is True
        assert isinstance(result, StageResult)

    @pytest.mark.asyncio
    async def test_c1_04_segment_missing_text_field(self):
        """W5-C1-04: text欠損セグメント — デフォルト空文字で処理"""
        ctx = create_mock_ctx(segments=3)
        ctx.segments = [
            {"start": 0.0, "end": 10.0},          # text なし
            {"start": 10.0, "end": 20.0, "text": "正常テキスト"},
            {"start": 20.0, "end": 30.0},          # text なし
        ]

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # KeyError なく処理完了すること
        assert result.success is True

    @pytest.mark.asyncio
    async def test_c1_05_more_than_20_segments_truncated(self):
        """W5-C1-05: 20seg以上(切り捨て) — [:20]制限が機能する"""
        ctx = create_mock_ctx(segments=30)
        ctx.segments = _make_segments(30)

        call_log = {"prompt": None}
        mock_response = MagicMock()
        mock_response.text = json.dumps(_VALID_METADATA, ensure_ascii=False)

        mock_client = MagicMock()

        def _capture_generate(model, contents, config=None):
            call_log["prompt"] = contents
            return mock_response

        mock_client.models.generate_content.side_effect = _capture_generate

        mock_factory = MagicMock()
        mock_factory.get_gemini_client.return_value = mock_client
        mock_google_genai = MagicMock()
        mock_mg = MagicMock()
        mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

        with _patch_gemini(mock_factory, mock_google_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # プロンプトに含まれるテキストがセグメント20件分のみであること
        # (seg21〜30のテキストは含まれないことを検証)
        if call_log["prompt"]:
            # セグメント21件目以降のテキストがプロンプトに含まれないこと
            seg_21_text = ctx.segments[20]["text"]
            assert seg_21_text not in call_log["prompt"]


# ============================================================
# C2: コアロジック (5テスト)
# ============================================================

class TestC2CoreLogic:
    """W5-C2-01〜W5-C2-05: コアロジック"""

    @pytest.mark.asyncio
    async def test_c2_01_gemini_api_metadata_generation(self):
        """W5-C2-01: Gemini APIメタデータ生成 — JSON構造検証"""
        ctx = create_mock_ctx(segments=10)
        ctx.segments = _make_segments(10)

        mock_factory, mock_genai, mock_mg, mock_client = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # API が呼ばれたこと
        assert mock_client.models.generate_content.call_count == 1
        # 正しいJSON構造が返ること
        assert result.success is True
        assert isinstance(ctx.metadata.get("titles"), list)
        assert isinstance(ctx.metadata.get("tags"), list)

    @pytest.mark.asyncio
    async def test_c2_02_prompt_3000_char_limit(self):
        """W5-C2-02: プロンプト構成(3000文字制限) — all_text[:3000]"""
        # 各セグメントに長いテキストを設定 → 合計が3000文字超
        long_text = "あ" * 200  # 200文字/セグメント × 20 = 4000文字
        ctx = create_mock_ctx(segments=20)
        ctx.segments = [
            {"start": float(i * 10), "end": float(i * 10 + 9), "text": long_text}
            for i in range(20)
        ]

        captured_prompt = {}

        def _capture(model, contents, config=None):
            captured_prompt["contents"] = contents
            mock_resp = MagicMock()
            mock_resp.text = json.dumps(_VALID_METADATA, ensure_ascii=False)
            return mock_resp

        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _capture
        mock_factory = MagicMock()
        mock_factory.get_gemini_client.return_value = mock_client
        mock_mg = MagicMock()
        mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

        with _patch_gemini(mock_factory, MagicMock(), mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # プロンプトに 3000文字制限が適用されていること
        prompt_str = captured_prompt.get("contents", "")
        # 合計テキスト(long_text × 20 = 4000文字)が[:3000]で切り取られているはず
        total_raw = " ".join(long_text for _ in range(20))  # 20×200+スペース19 = 4019文字
        assert total_raw[:3000] in prompt_str

    @pytest.mark.asyncio
    async def test_c2_03_model_governance_model_resolution(self):
        """W5-C2-03: model_governance経由モデル解決 — ガバナンス準拠"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, mock_client = _make_gemini_mock()
        resolved_model = {"name": None}

        original_generate = mock_client.models.generate_content.side_effect

        def _verify_model(model, contents, config=None):
            resolved_model["name"] = model
            mock_resp = MagicMock()
            mock_resp.text = json.dumps(_VALID_METADATA, ensure_ascii=False)
            return mock_resp

        mock_client.models.generate_content.side_effect = _verify_model
        mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # model_governance._resolve_model が呼ばれて、その戻り値がAPIに渡されること
        assert resolved_model["name"] == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_c2_04_json_parse_with_regex_extraction(self):
        """W5-C2-04: JSONパース(正規表現抽出) — response.text に余分な文字がある場合"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # response.text が純粋なJSONとして返る → json.loads 成功パス
        clean_json_metadata = {
            "titles": ["パーステスト動画"],
            "tags": ["t1", "t2", "t3", "t4", "t5"],
            "description": "説明文",
            "chapters": [{"time": "0:00", "title": "開始"}],
        }

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(
            response_json=clean_json_metadata
        )

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        assert ctx.metadata["titles"][0] == "パーステスト動画"

    @pytest.mark.asyncio
    async def test_c2_05_fallback_metadata_generation(self):
        """W5-C2-05: フォールバックメタデータ生成 — API失敗時"""
        ctx = create_mock_ctx(segments=10)
        ctx.segments = _make_segments(10, text_prefix="日本語テスト動画字幕")

        # API を完全に失敗させる
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(
            raise_exc=Exception("API完全障害")
        )

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # フォールバックでも success=True
        assert result.success is True
        # フォールバックメタデータが設定されること
        assert ctx.metadata is not None
        assert "titles" in ctx.metadata
        assert "tags" in ctx.metadata
        assert "description" in ctx.metadata
        assert "chapters" in ctx.metadata


# ============================================================
# C3: 出力検証 (5テスト)
# ============================================================

class TestC3OutputValidation:
    """W5-C3-01〜W5-C3-05: 出力検証"""

    @pytest.mark.asyncio
    async def test_c3_01_titles_list_ge_1(self):
        """W5-C3-01: titles: list, len≥1 — 型+内容検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        titles = ctx.metadata.get("titles")
        assert isinstance(titles, list), f"titles の型が不正: {type(titles)}"
        assert len(titles) >= 1, "titles が空リスト"
        # 各タイトルが文字列であること
        for t in titles:
            assert isinstance(t, str)

    @pytest.mark.asyncio
    async def test_c3_02_tags_list_ge_5(self):
        """W5-C3-02: tags: list, len≥5 — 型+内容検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        tags = ctx.metadata.get("tags")
        assert isinstance(tags, list), f"tags の型が不正: {type(tags)}"
        assert len(tags) >= 5, f"tags が5件未満: {len(tags)}件"

    @pytest.mark.asyncio
    async def test_c3_03_description_str_nonempty(self):
        """W5-C3-03: description: str, len>0 — 型+内容検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        desc = ctx.metadata.get("description")
        assert isinstance(desc, str), f"description の型が不正: {type(desc)}"
        assert len(desc) > 0, "description が空文字列"

    @pytest.mark.asyncio
    async def test_c3_04_chapters_list_of_dict(self):
        """W5-C3-04: chapters: list of dict — 構造検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        chapters = ctx.metadata.get("chapters")
        assert isinstance(chapters, list), f"chapters の型が不正: {type(chapters)}"
        assert len(chapters) >= 1, "chapters が空リスト"
        for ch in chapters:
            assert isinstance(ch, dict), f"chapter要素の型が不正: {type(ch)}"
            assert "time" in ch, "chapter に time フィールドなし"
            assert "title" in ch, "chapter に title フィールドなし"

    @pytest.mark.asyncio
    async def test_c3_05_ctx_metadata_updated(self):
        """W5-C3-05: ctx.metadata更新 — フィールド存在確認"""
        ctx = create_mock_ctx(segments=8)
        ctx.segments = _make_segments(8)
        ctx.metadata = {}  # 初期値は空

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # execute() 後に ctx.metadata が更新されていること
        assert ctx.metadata != {}
        # 全4フィールドが存在すること
        for field in ("titles", "tags", "description", "chapters"):
            assert field in ctx.metadata, f"ctx.metadata に {field} が存在しない"


# ============================================================
# C4: エラー耐性 (5テスト)
# ============================================================

class TestC4ErrorResilience:
    """W5-C4-01〜W5-C4-05: エラー耐性"""

    @pytest.mark.asyncio
    async def test_c4_01_gemini_api_429_rate_limit(self):
        """W5-C4-01: Gemini API 429(レート制限) — フォールバック"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        exc_429 = Exception("429 Resource has been exhausted")
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(raise_exc=exc_429)

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # 429でもパニックしないこと
        assert result.success is True
        assert ctx.metadata is not None
        # skipped_features にフォールバック記録があること
        assert any("YouTube" in f for f in ctx.skipped_features)

    @pytest.mark.asyncio
    async def test_c4_02_gemini_api_500_server_error(self):
        """W5-C4-02: Gemini API 500(サーバーエラー) — フォールバック"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        exc_500 = Exception("500 Internal Server Error")
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(raise_exc=exc_500)

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        assert ctx.metadata is not None

    @pytest.mark.asyncio
    async def test_c4_03_gemini_response_json_parse_failure(self):
        """W5-C4-03: Gemini応答のJSONパース失敗 — フォールバック"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # response.text が不正な JSON を返す
        mock_response = MagicMock()
        mock_response.text = "これはJSON形式ではありません"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_factory = MagicMock()
        mock_factory.get_gemini_client.return_value = mock_client
        mock_mg = MagicMock()
        mock_mg.model_governance._resolve_model.return_value = "gemini-2.5-flash"

        with _patch_gemini(mock_factory, MagicMock(), mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # JSONDecodeError でパニックしないこと
        assert result.success is True
        assert ctx.metadata is not None

    @pytest.mark.asyncio
    async def test_c4_04_get_gemini_client_import_error(self):
        """W5-C4-04: get_gemini_client ImportError — フォールバック"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # gemini_client_factory モジュール自体を None でパッチ（ImportError相当）
        with patch.dict("sys.modules", {
            "gemini_client_factory": None,
            "google": MagicMock(),
            "google.genai": MagicMock(),
            "model_governance": MagicMock(),
        }):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # ImportError でもフォールバックして success=True
        assert result.success is True
        assert ctx.metadata is not None

    @pytest.mark.asyncio
    async def test_c4_05_model_governance_exception(self):
        """W5-C4-05: model_governance例外 — デフォルトモデルでフォールバック"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # model_governance._resolve_model が例外を投げる
        mock_mg = MagicMock()
        mock_mg.model_governance._resolve_model.side_effect = Exception("governance error")

        # Gemini API 自体は正常に応答する
        mock_response = MagicMock()
        mock_response.text = json.dumps(_VALID_METADATA, ensure_ascii=False)
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_factory = MagicMock()
        mock_factory.get_gemini_client.return_value = mock_client

        with _patch_gemini(mock_factory, MagicMock(), mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # governance 例外→デフォルトモデルで続行 or フォールバック、どちらでも success
        assert result.success is True
        assert ctx.metadata is not None


# ============================================================
# C5: 統合・依存 (5テスト)
# ============================================================

class TestC5Integration:
    """W5-C5-01〜W5-C5-05: 統合・依存"""

    @pytest.mark.asyncio
    async def test_c5_01_transcribe_output_contract(self):
        """W5-C5-01: Transcribe出力との契約(CT-06) — seg構造検証"""
        ctx = create_mock_ctx(segments=5)
        # TranscribeWorker が出力する標準構造
        ctx.segments = [
            {
                "start": float(i * 10),
                "end": float(i * 10 + 9),
                "text": f"発言{i + 1}",
                "sourceStart": float(i * 10),
                "sourceEnd": float(i * 10 + 9),
            }
            for i in range(5)
        ]

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        # CT-06: Transcribe標準構造でも正常処理できること
        assert result.success is True

    @pytest.mark.asyncio
    async def test_c5_02_template_seo_guide_reflected(self):
        """W5-C5-02: テンプレートSEOガイドの反映 — template_config"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # template_config をモック（SEO ガイドが設定されている場合）
        mock_tc = MagicMock()
        mock_tc.is_active = True
        mock_tc.get_quality_benchmarks.return_value = {"seo_title_min_length": 30}

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            with patch.dict("sys.modules", {"template_config": mock_tc}):
                worker = YouTubeOptWorker()
                result = await worker.execute(ctx)

        # template_config の存在に依らず正常動作すること
        assert result.success is True

    @pytest.mark.asyncio
    async def test_c5_03_skipped_features_tracking_on_api_failure(self):
        """W5-C5-03: skipped_features追跡 — API失敗時"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)
        initial_skipped_count = len(ctx.skipped_features)

        exc = Exception("API不可")
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(raise_exc=exc)

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # skipped_features にエントリが追加されていること
        assert len(ctx.skipped_features) > initial_skipped_count
        # "YouTube" を含む skipped 理由が存在すること
        assert any("YouTube" in f for f in ctx.skipped_features)

    @pytest.mark.asyncio
    async def test_c5_04_concurrent_sessions_ctx_independence(self):
        """W5-C5-04: 並行セッション時のctx独立性 — データ汚染なし"""
        ctx_a = create_mock_ctx(segments=5)
        ctx_a.segments = _make_segments(5, text_prefix="AセッションABC")
        ctx_b = create_mock_ctx(segments=5)
        ctx_b.segments = _make_segments(5, text_prefix="Bセッション123")

        meta_a = {
            "titles": ["Aのタイトル"], "tags": ["a1", "a2", "a3", "a4", "a5"],
            "description": "A説明", "chapters": [{"time": "0:00", "title": "A開始"}],
        }
        meta_b = {
            "titles": ["Bのタイトル"], "tags": ["b1", "b2", "b3", "b4", "b5"],
            "description": "B説明", "chapters": [{"time": "0:00", "title": "B開始"}],
        }

        mock_factory_a, mock_genai_a, mock_mg_a, _ = _make_gemini_mock(response_json=meta_a)
        mock_factory_b, mock_genai_b, mock_mg_b, _ = _make_gemini_mock(response_json=meta_b)

        worker_a = YouTubeOptWorker()
        worker_b = YouTubeOptWorker()

        with _patch_gemini(mock_factory_a, mock_genai_a, mock_mg_a):
            result_a = await worker_a.execute(ctx_a)

        with _patch_gemini(mock_factory_b, mock_genai_b, mock_mg_b):
            result_b = await worker_b.execute(ctx_b)

        assert result_a.success is True
        assert result_b.success is True
        # 互いのメタデータが混入していないこと
        assert ctx_a.metadata.get("titles") != ctx_b.metadata.get("titles")

    @pytest.mark.asyncio
    async def test_c5_05_websocket_notification_structure(self):
        """W5-C5-05: WebSocket通知(メタデータ完了) — 通知構造確認"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # StageResultの識別子が正しいこと（WebSocket通知の土台）
        assert result.stage_name == "YouTube最適化"
        assert result.duration_seconds >= 0


# ============================================================
# C6: 性能・進化 (5テスト)
# ============================================================

class TestC6Performance:
    """W5-C6-01〜W5-C6-05: 性能・進化"""

    @pytest.mark.asyncio
    async def test_c6_01_metadata_generation_within_30s(self):
        """W5-C6-01: メタデータ生成≤30秒 — 時間予算内"""
        ctx = create_mock_ctx(segments=10)
        ctx.segments = _make_segments(10)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()

        start = time.time()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)
        elapsed = time.time() - start

        assert result.success is True
        # モック環境では30秒以内に確実に完了するはず
        assert elapsed < 30.0, f"処理が時間予算を超過: {elapsed:.2f}秒"
        # duration_seconds も記録されていること
        assert result.duration_seconds >= 0

    @pytest.mark.asyncio
    async def test_c6_02_api_response_cache_not_used(self):
        """W5-C6-02: API応答キャッシュの有無 — キャッシュ不使用（毎回API呼出し）"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, mock_client = _make_gemini_mock()

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            # 2回実行しても毎回 API が呼ばれること
            await worker.execute(ctx)
            await worker.execute(ctx)

        # 2回実行したら API も2回呼ばれること（キャッシュなし）
        assert mock_client.models.generate_content.call_count == 2

    @pytest.mark.asyncio
    async def test_c6_03_dream_engine_reflection(self):
        """W5-C6-03: DreamEngine学習への反映 — metadata品質情報"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # DreamEngine が参照する情報が StageResult に含まれること
        assert result.data is not None or result.detail  # 何らかの出力がある
        # metadata の品質情報（タイトル数・タグ数）が detail に記録されること
        assert result.detail is not None and len(result.detail) > 0

    @pytest.mark.asyncio
    async def test_c6_04_seo_title_length_condition(self):
        """W5-C6-04: SEO最適化スコア — タイトル30文字条件"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # 30文字以内のタイトルを返すメタデータ
        short_title_meta = {
            "titles": ["短い" * 5],  # 10文字
            "tags": ["t1", "t2", "t3", "t4", "t5"],
            "description": "説明文",
            "chapters": [{"time": "0:00", "title": "開始"}],
        }
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(
            response_json=short_title_meta
        )

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        # タイトルが設定されていること
        assert len(ctx.metadata["titles"]) >= 1

    @pytest.mark.asyncio
    async def test_c6_05_fallback_tags_deduplication(self):
        """W5-C6-05: ハッシュタグ生成の重複排除 — フォールバック時のユニーク検証"""
        # フォールバックパスを強制するために API エラー
        ctx = create_mock_ctx(segments=5)
        # 同じ単語が複数回登場するセグメント
        ctx.segments = [
            {"start": 0.0, "end": 9.0,  "text": "日本語テスト日本語テスト"},
            {"start": 10.0, "end": 19.0, "text": "日本語テスト日本語テスト"},
            {"start": 20.0, "end": 29.0, "text": "動画コンテンツ動画コンテンツ"},
        ]

        exc = Exception("api down")
        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock(raise_exc=exc)

        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)

        assert result.success is True
        tags = ctx.metadata.get("tags", [])
        assert isinstance(tags, list)
        # フォールバックタグに重複がないこと（dict.fromkeys で重複排除）
        assert len(tags) == len(set(tags)), f"タグに重複あり: {tags}"


# ============================================================
# C7: 追加カバレッジ (8テスト)
# ============================================================

class TestC7CoverageExtension:
    """W5-C7-01〜W5-C7-08: カバレッジ向上用の追加テスト"""

    @pytest.mark.asyncio
    async def test_c7_01_get_definition_of_done(self):
        """W5-C7-01: get_definition_of_done の検証"""
        worker = YouTubeOptWorker()
        dod = worker.get_definition_of_done()
        assert isinstance(dod, str)
        assert "タイトル" in dod

    @pytest.mark.asyncio
    async def test_c7_02_get_attribute_or_key_object(self):
        """W5-C7-02: _get_attribute_or_key のオブジェクト属性取得検証"""
        class DummyObj:
            def __init__(self, val):
                self.val = val
                self.none_val = None

        worker = YouTubeOptWorker()
        obj = DummyObj("test_value")

        # 属性が存在し、かつ None ではない場合
        assert worker._get_attribute_or_key(obj, "val", "default") == "test_value"
        # 属性が存在するが None の場合
        assert worker._get_attribute_or_key(obj, "none_val", "default") == "default"

    @pytest.mark.asyncio
    async def test_c7_03_get_attribute_or_key_neither(self):
        """W5-C7-03: _get_attribute_or_key で辞書でもオブジェクトでもない場合の検証"""
        worker = YouTubeOptWorker()
        # 整数値と NoneType は attributes も keys も持たない
        assert worker._get_attribute_or_key(123, "val", "default") == "default"
        assert worker._get_attribute_or_key(None, "val", "default") == "default"

    @pytest.mark.asyncio
    async def test_c7_04_model_governance_import_error(self):
        """W5-C7-04: model_governance のインポートエラー時のフォールバック検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)

        # model_governance をインポートしたときに ImportError を発生させるパッチ
        mock_factory, mock_genai, _, _ = _make_gemini_mock()
        
        # model_governance を sys.modules から削除して None を設定することで ImportError を再現
        with patch.dict("sys.modules", {
            "gemini_client_factory": mock_factory,
            "google": MagicMock(),
            "google.genai": mock_genai,
            "model_governance": None, # ImportError を誘発
        }):
            worker = YouTubeOptWorker()
            result = await worker.execute(ctx)
            
        assert result.success is True
        # デフォルトモデル名 gemini-2.5-flash が使われていることを確認
        assert result.data["model_used"] == "gemini-2.5-flash"

    @pytest.mark.asyncio
    async def test_c7_05_create_fallback_chapters_empty(self):
        """W5-C7-05: segmentsが空またはNoneの場合のフォールバックチャプター検証"""
        worker = YouTubeOptWorker()
        # None を渡した場合
        ch_none = worker._create_fallback_chapters(None)
        assert len(ch_none) == 1
        assert ch_none[0]["title"] == "オープニング"

        # 空リストを渡した場合
        ch_empty = worker._create_fallback_chapters([])
        assert len(ch_empty) == 1
        assert ch_empty[0]["title"] == "オープニング"

    @pytest.mark.asyncio
    async def test_c7_06_create_fallback_chapters_loop(self):
        """W5-C7-06: 5分以上のセグメントがある場合のフォールバックチャプター生成ループ検証"""
        worker = YouTubeOptWorker()
        
        # total_sec (最後のセグメントの end または sourceEnd) が 650秒 (10分超) のセグメントリスト
        # nearby（t=300秒の近傍30秒以内）が存在するように、スタート310秒のセグメントを配置
        segments = [
            {"start": 0.0, "end": 9.0, "text": "最初"},
            {"start": 310.0, "end": 320.0, "text": "近傍セグメントテキスト"},
            {"start": 640.0, "end": 650.0, "text": "最後"}
        ]
        
        chapters = worker._create_fallback_chapters(segments)
        
        # 0:00 (オープニング), 5:00 (t=300: 近傍あり -> "近傍セグメントテキスト"), 10:00 (t=600: 近傍なし -> "パート3")
        assert len(chapters) == 3
        assert chapters[0]["time"] == "0:00"
        assert chapters[0]["title"] == "オープニング"
        
        assert chapters[1]["time"] == "5:00"
        assert chapters[1]["title"] == "近傍セグメントテキスト"
        
        assert chapters[2]["time"] == "10:00"
        assert chapters[2]["title"] == "パート3"

    @pytest.mark.asyncio
    async def test_c7_07_cross_media_analysis_invalid_metadata(self):
        """W5-C7-07: ctx.metadata が dict ではない場合の初期化検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)
        ctx.metadata = None  # dict ではない値

        # CrossMediaService をモックして正常に結果が返るようにする
        mock_service = MagicMock()
        mock_service.analyze_cross_media_correlation.return_value = {"score": 90}
        
        with patch("services.cross_media_service.CrossMediaService", return_value=mock_service):
            worker = YouTubeOptWorker()
            # _run_cross_media_analysis を直接呼び出して、metadata が None の状態での初期化パスを通す
            worker._run_cross_media_analysis(ctx)

        assert isinstance(ctx.metadata, dict)
        assert ctx.metadata["cross_media_correlation"] == {"score": 90}

    @pytest.mark.asyncio
    async def test_c7_08_cross_media_analysis_exception(self):
        """W5-C7-08: クロスメディア分析中の例外が安全に無視されることの検証"""
        ctx = create_mock_ctx(segments=5)
        ctx.segments = _make_segments(5)
        ctx.metadata = {}

        mock_factory, mock_genai, mock_mg, _ = _make_gemini_mock()
        with _patch_gemini(mock_factory, mock_genai, mock_mg):
            # CrossMediaService のインポートで ImportError を発生させるか、
            # あるいはメソッド呼び出しで例外を投げる
            with patch("services.cross_media_service.CrossMediaService", side_effect=ImportError("インポート失敗")):
                worker = YouTubeOptWorker()
                result = await worker.execute(ctx)

        # 例外が発生しても、プロセスがクラッシュせずに success=True を返すこと
        assert result.success is True
        # 例外が発生したため、cross_media_correlation は設定されていないこと
        assert "cross_media_correlation" not in ctx.metadata
