"""
ProductionPipeline — ADK SequentialAgent + LoopAgent

.. deprecated::
    このモジュールは **harness/adk_bridge.py** に統合されました。
    新規開発では `from harness.adk_bridge import run_harness_pipeline` を使用してください。
    ハーネス統合版は以下を自動提供:
      - MCP準拠ツール定義（ToolRegistry）
      - Hook パターン（Pre/Post/Failure）
      - ガバナンス権限チェック
      - セッション永続化・リジューム
      - OpenTelemetry互換トレース

旧設計（後方互換のため維持）:
  - パターンC（チェックポイント通知型）
  - AI がデフォルトを選定して自動続行（auto_pilot_ratio: 0.9 準拠）
  - 各チェックポイントで2分のグレースタイム付き通知
  - 最終承認（⑦）だけは必ず停止（§15 ワンアクション原則）

アーキテクチャ:
  ProductionPipeline (SequentialAgent)
   ├── ① TranscribeAgent     ← whisper_transcriber をラップ
   ├── ② ProofreadAgent      ← ai_proofreader をラップ
   ├── ③ SmartCutAgent        ← smart_cut_engine をラップ (Checkpoint)
   ├── ④⑤⑥ ReviewLoop (LoopAgent)
   │    ├── PreviewAgent      ← progressive_preview をラップ
   │    └── QualityGateAgent  ← director_engine をラップ
   ├── ⑦ RenderAgent          ← video_editor_engine をラップ (必須停止)
   └── ⑧ YouTubeOptAgent     ← youtube ルーター群をラップ
"""

import json
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================
# Claude Code Breakthrough: SelfHealingTool + Verified Facts
# ============================================================
try:
    from agents.self_healing_tool import self_healing
    _SELF_HEALING_AVAILABLE = True
    logger.info('SelfHealingTool integrated')
except ImportError:
    _SELF_HEALING_AVAILABLE = False
    logger.warning('SelfHealingTool not available - fallback mode')


def _wrap_tool(func):
    """SelfHealingToolでラップし、ADKメタデータ(__name__, __doc__)を保持する"""
    if _SELF_HEALING_AVAILABLE:
        wrapped = self_healing.wrap(func)
        # ADK ツール登録時に __name__ と __doc__ を参照するため明示的に保持
        if not hasattr(wrapped, '__name__') or wrapped.__name__ != func.__name__:
            wrapped.__name__ = func.__name__
        if not hasattr(wrapped, '__doc__') or not wrapped.__doc__:
            wrapped.__doc__ = func.__doc__
        return wrapped
    return func


def _get_verified_facts_context() -> str:
    try:
        from agents.memory.verified_facts import verified_facts_store
        ctx = verified_facts_store.get_facts_for_context(max_tokens=500)
        return ctx if ctx else ''
    except (ImportError, Exception):
        return ''


# ============================================================
# ツール定義（既存モジュールの ADK tool ラップ）
# ============================================================


def transcribe_video(video_path: str, language: str = "ja") -> str:
    """動画ファイルを文字起こしし、タイムスタンプ付き字幕データを返す。
    
    HR-4修正: インプロセスWhisper → サブプロセス方式に変更
    CTranslate2/CUDA DLL干渉によるクラッシュを根本回避。
    """
    try:
        from subtitle_engine.whisper_subprocess import run_whisper_subprocess
        
        result = run_whisper_subprocess(
            video_path=video_path,
            model_size="large-v3",
            language=language,
        )
        
        if result.get("status") == "success":
            segments = result.get("segments", [])
            logger.info(f"✅ Transcription complete (subprocess): {len(segments)} segments")
            return json.dumps({
                "status": "success",
                "segments_count": len(segments),
                "segments": segments,
            }, ensure_ascii=False)
        else:
            error = result.get("error", "Unknown subprocess error")
            logger.error(f"Transcription subprocess failed: {error}")
            return json.dumps({"status": "error", "error": error})
    except ImportError as e:
        logger.error(f"Import failed during transcription: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Import failed: {e}"})
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode failed in transcription: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"JSON decode failed: {e}"})
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def proofread_subtitles(segments_json: str) -> str:
    """字幕テキストをAI校閲する。"""
    try:
        from subtitle_engine.ai_proofreader import proofread_segments
        
        data = json.loads(segments_json)
        segments = data if isinstance(data, list) else data.get("segments", [])
        
        corrected = proofread_segments(segments)
        
        logger.info(f"✅ Proofreading complete: {len(corrected)} segments")
        return json.dumps({
            "status": "success",
            "segments": corrected,
        }, ensure_ascii=False)
    except ImportError as e:
        logger.error(f"Import failed during proofreading: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Import failed: {e}"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid segments JSON provided for proofreading: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})
    except Exception as e:
        logger.error(f"Proofreading failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def propose_smart_cut(
    segments_json: str, 
    video_path: str, 
    target_minutes: int = 20
) -> str:
    """SmartCut 構成案を生成する。"""
    try:
        data = json.loads(segments_json)
        segments = data if isinstance(data, list) else data.get("segments", [])
        
        if not segments:
            return json.dumps({"status": "error", "error": "No segments provided"})
        
        # 全体の長さから目標尺に応じた構成を計算
        total_duration = max(s.get("sourceEnd", s.get("end", 0)) for s in segments)
        target_sec = target_minutes * 60
        
        # 優先度スコアで上位セグメントを選択（簡易版）
        # 将来: Director Agent が意味的に重要なシーンを選定
        if total_duration <= target_sec:
            selected = segments  # 目標尺以下ならカットなし
        else:
            # 均等にサンプリング（簡易版）
            ratio = target_sec / total_duration
            selected = segments[:int(len(segments) * ratio)]
        
        proposals = {
            "status": "success",
            "proposals": [
                {
                    "name": f"{target_minutes}分版",
                    "target_minutes": target_minutes,
                    "segments": selected,
                    "estimated_duration": sum(
                        s.get("sourceEnd", s.get("end", 0)) - s.get("sourceStart", s.get("start", 0)) 
                        for s in selected
                    ),
                    "is_default": True,
                },
            ],
            "checkpoint": "smartcut_proposal",
            "grace_seconds": 120,
        }
        
        logger.info(f"✅ SmartCut proposal: {len(selected)} segments for {target_minutes}min")
        return json.dumps(proposals, ensure_ascii=False)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid segments JSON for SmartCut: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})
    except KeyError as e:
        logger.error(f"Missing required segment key in SmartCut: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Missing key: {e}"})
    except Exception as e:
        logger.error(f"SmartCut proposal failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def generate_preview(config_json: str) -> str:
    """プレビュー動画を生成する。"""
    try:
        from video_editor_engine import video_editor
        
        config = json.loads(config_json)
        video_path = config.get("video_path", "")
        segments = config.get("segments", [])
        try:
            from safe_io import VAULT_OUTPUTS_DIR
            default_preview_dir = str(VAULT_OUTPUTS_DIR / "preview")
        except ImportError:
            default_preview_dir = "output/preview"
        output_dir = config.get("output_dir", default_preview_dir)
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        preview_path = Path(output_dir) / f"preview_{timestamp}.mp4"
        
        # SmartCut でプレビュー生成
        from smart_cut_engine import render_smart_cut
        success = render_smart_cut(segments, video_path, str(preview_path))
        
        if success:
            logger.info(f"✅ Preview generated: {preview_path}")
            return json.dumps({
                "status": "success",
                "preview_path": str(preview_path),
            })
        else:
            return json.dumps({"status": "error", "error": "Preview generation failed"})
    except ImportError as e:
        logger.error(f"Import failed during preview generation: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Import failed: {e}"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid config JSON for preview: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})
    except FileNotFoundError as e:
        logger.error(f"File/directory not found in preview: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Not found: {e}"})
    except Exception as e:
        logger.error(f"Preview generation failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def check_quality(config_json: str) -> str:
    """品質チェックを実行し、スコアとフィードバックを返す。"""
    try:
        config = json.loads(config_json)
        preview_path = config.get("preview_path", "")
        
        # 基本品質チェック
        score = 85  # ベーススコア
        feedback = []
        
        if not Path(preview_path).exists():
            return json.dumps({
                "status": "error",
                "error": f"Preview not found: {preview_path}"
            })
        
        # ファイルサイズチェック
        file_size = Path(preview_path).stat().st_size
        if file_size < 1024:  # 1KB未満は異常
            score -= 30
            feedback.append("⚠️ ファイルサイズが異常に小さい")
        
        # 将来: Gemini によるフレーム分析、音質チェック等
        
        passed = score >= 80
        
        logger.info(f"Quality Gate: score={score}, passed={passed}")
        return json.dumps({
            "status": "success",
            "score": score,
            "rank": "A" if score >= 90 else "B" if score >= 80 else "C",
            "passed": passed,
            "feedback": feedback,
        })
    except json.JSONDecodeError as e:
        logger.error(f"Invalid config JSON for quality check: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})
    except FileNotFoundError as e:
        logger.error(f"Preview file not found during quality check: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"File not found: {e}"})
    except Exception as e:
        logger.error(f"Quality check failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def render_final(config_json: str) -> str:
    """最終レンダリングを実行する。"""
    try:
        from video_editor_engine import video_editor
        
        config = json.loads(config_json)
        video_path = config.get("video_path", "")
        segments = config.get("segments", [])
        try:
            from safe_io import VAULT_OUTPUTS_DIR
            default_final = str(VAULT_OUTPUTS_DIR / "final" / "final_video.mp4")
        except ImportError:
            default_final = "output/final/final_video.mp4"
        output_path = config.get("output_path", default_final)
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        from smart_cut_engine import render_smart_cut
        success = render_smart_cut(segments, video_path, output_path)
        
        if success:
            logger.info(f"✅ Final render complete: {output_path}")
            return json.dumps({
                "status": "success",
                "output_path": output_path,
                "checkpoint": "final_approval",
                "requires_approval": True,  # §15 ワンアクション原則: ここだけ必須停止
            })
        else:
            return json.dumps({"status": "error", "error": "Final render failed"})
    except ImportError as e:
        logger.error(f"Import failed during final render: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Import failed: {e}"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid config JSON for final render: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON: {e}"})
    except FileNotFoundError as e:
        logger.error(f"File/directory not found in final render: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Not found: {e}"})
    except Exception as e:
        logger.error(f"Final render failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


def generate_youtube_metadata(text: str) -> str:
    """YouTube SEOメタデータを生成する。"""
    try:
        from gemini_client_factory import get_gemini_client
        from google.genai import types
        
        client = get_gemini_client()
        
        prompt = f"""以下の動画字幕テキストから、YouTube投稿用のメタデータを生成してください。

要件:
- タイトルは5案以上（30文字以内、興味を引く表現）
- タグは15-20個（§23.4準拠: 大カテゴリ→小カテゴリ→固有名詞の順）
- 説明文は200-500文字（末尾にハッシュタグ3-5個）
- チャプターは動画の論理的な区切りに基づく

出力形式（JSON）:
{{
  "titles": ["タイトル案1", "タイトル案2", "タイトル案3", "タイトル案4", "タイトル案5"],
  "description": "説明文（200-500文字）\\n\\n#ハッシュタグ1 #ハッシュタグ2",
  "tags": ["大カテゴリタグ", "中カテゴリタグ", "固有名詞タグ", ... （合計15-20個）],
  "chapters": [{{"time": "0:00", "title": "チャプター名"}}, ...]
}}

字幕テキスト（抜粋）:
{text[:3000]}"""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
        metadata = json.loads(response.text)
        logger.info(f"✅ YouTube metadata generated: {len(metadata.get('titles', []))} titles")
        return json.dumps({
            "status": "success",
            "metadata": metadata,
        }, ensure_ascii=False)
    except ImportError as e:
        logger.error(f"Import failed during YouTube metadata generation: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Import failed: {e}"})
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response from Gemini API: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": f"Invalid JSON response: {e}"})
    except Exception as e:
        logger.error(f"YouTube metadata generation failed: {e}", exc_info=True)
        return json.dumps({"status": "error", "error": str(e)})


# ============================================================
# パイプライン構築
# ============================================================

def _create_transcribe_agent(facts_preamble: str):
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="TranscribeAgent",
        instruction="""あなたは音声認識担当です。
        指定された動画ファイルの文字起こしを実行してください。
        transcribe_video ツールを使い、結果をセッションに保存してください。""",
        tools=[_wrap_tool(transcribe_video)],
        description="Stage 1: 音声認識（faster-whisper large-v3）",
    )


def _create_proofread_agent(facts_preamble: str):
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="ProofreadAgent",
        instruction=f"""あなたは校閲担当です。
        前のステージで生成された字幕テキストのAI校閲を実行してください。
        proofread_subtitles ツールを使い、固有名詞修正と文法チェックを行ってください。{facts_preamble}""",
        tools=[_wrap_tool(proofread_subtitles)],
        description="Stage 2: AI校閲（Gemini + 固有名詞辞書）",
    )


def _create_smartcut_agent():
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="SmartCutAgent",
        instruction="""あなたは構成エディターです。
        校閲済み字幕データから SmartCut 構成案を生成してください。
        propose_smart_cut ツールを使い、デフォルト20分版の構成を提案してください。
        
        チェックポイント: この結果はユーザーに通知されます。
        2分のグレースタイム後、変更がなければデフォルト案で自動続行します。""",
        tools=[_wrap_tool(propose_smart_cut)],
        description="Stage 3: SmartCut構成（チェックポイント通知型）",
    )


def _create_preview_agent():
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="PreviewAgent",
        instruction="""あなたはプレビュー担当です。
        確定した構成でプレビュー動画を生成してください。
        generate_preview ツールを使ってください。""",
        tools=[_wrap_tool(generate_preview)],
        description="Stage 4-5: プレビュー生成（FFmpeg + GPU）",
    )


def _create_quality_agent(facts_preamble: str):
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="QualityGateAgent",
        instruction=f"""あなたは品質管理担当です。
        プレビュー動画の品質チェックを実行してください。
        check_quality ツールを使い、80点以上なら合格、未満なら修正が必要です。
        
        合格の場合: 「PASSED」と報告
        不合格の場合: 具体的な改善点を報告{facts_preamble}""",
        tools=[_wrap_tool(check_quality)],
        description="Stage 6: 品質チェック（Quality Gate）",
    )


def _create_render_agent():
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="RenderAgent",
        instruction="""あなたはレンダリング担当です。
        品質チェック合格後、最終レンダリングを実行してください。
        render_final ツールを使ってください。
        
        重要: このステージは §15 ワンアクション原則に基づき、
        ユーザーの最終承認が必須です。""",
        tools=[_wrap_tool(render_final)],
        description="Stage 7: 最終レンダリング（要承認）",
    )


def _create_youtube_agent():
    from agents.adk_agent_template import create_agent
    return create_agent(
        name="YouTubeOptAgent",
        instruction="""あなたはYouTube最適化担当です。
        完成した動画の字幕テキストから、YouTube投稿用のメタデータを生成してください。
        generate_youtube_metadata ツールを使い、タイトル5案、説明文、タグ、チャプターを生成してください。""",
        tools=[_wrap_tool(generate_youtube_metadata)],
        description="Stage 8: YouTube最適化（SEO + チャプター）",
    )


def build_production_pipeline():
    """
    制作パイプラインを構築する。
    ADK の SequentialAgent + LoopAgent を使用。
    
    Returns:
        SequentialAgent インスタンス（ProductionPipeline）
    """
    try:
        from google.adk.agents import SequentialAgent, LoopAgent
    except ImportError as e:
        logger.error(f"ADK import failed: {e}")
        raise
    
    # --- Verified Facts をプリアンブルとして注入 ---
    facts_preamble = _get_verified_facts_context()
    if facts_preamble:
        facts_preamble = f"\n\n## プロジェクト確定仕様\n{facts_preamble}\n\n"
    else:
        facts_preamble = ""

    # --- ステージエージェント定義 ---
    transcribe_agent = _create_transcribe_agent(facts_preamble)
    proofread_agent = _create_proofread_agent(facts_preamble)
    smartcut_agent = _create_smartcut_agent()
    preview_agent = _create_preview_agent()
    quality_agent = _create_quality_agent(facts_preamble)
    render_agent = _create_render_agent()
    youtube_agent = _create_youtube_agent()
    
    # --- 修正ループ（プレビュー → 品質チェックの反復） ---
    review_loop = LoopAgent(
        name="ReviewLoop",
        sub_agents=[preview_agent, quality_agent],
        max_iterations=3,
    )
    
    # --- メインパイプライン ---
    pipeline = SequentialAgent(
        name="ProductionPipeline",
        sub_agents=[
            transcribe_agent,    # ① 文字起こし
            proofread_agent,     # ② AI校閲
            smartcut_agent,      # ③ 構成決定（チェックポイント）
            review_loop,         # ④⑤⑥ プレビュー＆品質ループ
            render_agent,        # ⑦ レンダリング（要承認）
            youtube_agent,       # ⑧ YouTube最適化
        ],
    )
    
    logger.info("✅ ProductionPipeline built: 8 stages, "
                "including ReviewLoop (max 3 iterations)")
    
    return pipeline


# ============================================================
# 公開 API
# ============================================================

async def run_production_pipeline(
    video_path: str,
    target_minutes: int = 20,
    session_id: Optional[str] = None,
) -> dict:
    """
    ProductionPipeline を実行する非同期エントリポイント。
    
    Args:
        video_path: RAW動画ファイルパス
        target_minutes: 目標尺（分）
        session_id: セッションID（省略時は自動生成）
    
    Returns:
        パイプライン実行結果
    """
    try:
        from google.adk.runners import InMemoryRunner
        from google.adk.agents.run_config import RunConfig
        from google.genai import types as genai_types
    except ImportError as e:
        logger.error(f"google-adk が未インストールです: {e}")
        return {"status": "error", "error": str(e)}
    
    try:
        pipeline = build_production_pipeline()
        
        runner = InMemoryRunner(
            agent=pipeline,
            app_name="antigravity_production",
        )
        
        import uuid
        sid = session_id or str(uuid.uuid4())
        
        # 初期 state にパイプラインコンテキストを設定
        initial_state = {
            "video_path": video_path,
            "target_minutes": target_minutes,
            "pipeline_started_at": datetime.now().isoformat(),
            "stage": "initialized",
        }
        
        session = await runner.session_service.create_session(
            app_name="antigravity_production",
            user_id="pipeline_user",
            session_id=sid,
            state=initial_state,
        )
        
        # パイプライン起動メッセージ
        start_message = (
            f"動画 '{video_path}' の制作パイプラインを開始してください。"
            f"目標尺は{target_minutes}分です。"
        )
        
        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=start_message)],
        )
        
        run_config = RunConfig(max_llm_calls=30)
        
        result_text = ""
        async for event in runner.run_async(
            user_id="pipeline_user",
            session_id=sid,
            new_message=content,
            run_config=run_config,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        result_text += part.text
        
        logger.info(f"✅ ProductionPipeline complete: session_id={sid}")
        return {
            "status": "success",
            "session_id": sid,
            "result": result_text,
        }
    except ValueError as e:
        logger.error(f"Invalid argument in pipeline run: {e}", exc_info=True)
        return {"status": "error", "error": f"Invalid argument: {e}"}
    except Exception as e:
        logger.error(f"ProductionPipeline error: {e}", exc_info=True)
        return {"status": "error", "error": str(e)}
