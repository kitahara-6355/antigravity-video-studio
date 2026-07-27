"""
self_improvement_engine.py — 新自己改善サイクル（自律検品）コアエンジン v2.0

品質ゲートプラグイン22種を統合した本格的な弱点分析と、
SmartCut/フック/ラウドネスを含む包括的な自動改善を実行する。

合格基準（憲法§8.2準拠）:
  - 総合スコア 90点以上
  - 全カテゴリ（stability/core/template/broadcast/youtube）80点以上

① プレビュー自動検品（Vision API + ヒューリスティック）
② 22種品質ゲートプラグインによる弱点分析
③ 弱点レポート出力＆履歴積上
④ 自動パラメータ改善（字幕/SmartCut/フック/ラウドネス）
⑤ 改善ループの実行
"""
import os
import sys
import json
import logging
import re
from datetime import datetime
from pathlib import Path

# 具体的な例外クラスのインポート（環境非依存のためのフォールバック付き）
try:
    from google.genai.errors import APIError
except ImportError:
    class APIError(Exception):
        pass

try:
    import httpx
except ImportError:
    class DummyHTTPError(Exception):
        pass
    httpx = type('dummy', (), {'HTTPError': DummyHTTPError})


logger = logging.getLogger(__name__)

# パス設定（動的取得）
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
GRADED_PREVIEWS_DIR = BACKEND_DIR / "graded_previews"
TEMPLATE_CONFIG_PATH = BACKEND_DIR / "template_config.py"
MERGED_DIR = BASE_DIR / "vault-outputs" / "merged"

# 合格基準（憲法§8.2 + Sprint 4.7.1 設計書準拠）
PASS_TOTAL_SCORE = 90       # 総合スコアの合格ライン
PASS_CATEGORY_SCORE = 80    # 各カテゴリの合格ライン


def get_gemini_client():
    """Geminiクライアントを取得"""
    try:
        from gemini_client_factory import get_gemini_client as get_client
        return get_client()
    except ImportError:
        return None


class QualityGateContext:
    """品質ゲートプラグインに渡すコンテキストオブジェクト"""

    def __init__(self, segments=None, selected_segments=None,
                 preview_path=None, metadata=None):
        self.segments = segments or []
        self.selected_segments = selected_segments or []
        self.preview_path = preview_path
        self.metadata = metadata or {}


class SelfImprovementEngine:
    """自己改善サイクルエンジン v2.0 — 品質ゲートプラグイン統合版"""

    def __init__(self, artifacts_dir=None, merged_dir=None):
        if artifacts_dir is not None and not isinstance(artifacts_dir, (str, Path)):
            raise TypeError("artifacts_dir must be a string or Path")
        if merged_dir is not None and not isinstance(merged_dir, (str, Path)):
            raise TypeError("merged_dir must be a string or Path")

        # 出力先をプロジェクト内の graded_previews に固定
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else GRADED_PREVIEWS_DIR
        try:
            self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"❌ artifacts_dir の作成に失敗しました: {e}")
            raise
        self.merged_dir = Path(merged_dir) if merged_dir else MERGED_DIR
        self._cached_segments = None

    def clear_cache(self):
        """キャッシュされたセグメントをクリアする"""
        self._cached_segments = None

    def auto_inspect(self) -> list[dict]:
        """① プレビュー報告書の自動確認

        index.json を読み込み、抽出されたプレビュー画像群から Vision API または
        字幕メタデータのヒューリスティックにより字幕やレイアウトをスキャン・検品する。
        """
        # latest ディレクトリの index.json を探す
        index_path = self.artifacts_dir / "latest" / "index.json"
        if not index_path.exists():
            # フォールバック: artifacts_dir 直下
            index_path = self.artifacts_dir / "full_inspection" / "index.json"
        if not index_path.exists():
            logger.warning(f"⚠️ index.json が見つかりません: {index_path}")
            return []

        try:
            with open(index_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"❌ index.json 読み込み失敗: {e}")
            return []

        if not isinstance(index_data, dict):
            logger.error("❌ index.json の形式が正しくありません (辞書型である必要があります)")
            return []

        frames = index_data.get("frames", [])
        if not isinstance(frames, list):
            logger.error("❌ index.json の frames がリスト型ではありません")
            return []

        if not frames:
            return []

        results = []
        client = get_gemini_client()
        img_dir = index_path.parent

        segments = self._load_whisper_segments()
        for frame in frames:
            if not isinstance(frame, dict):
                logger.warning(f"⚠️ frame 要素が辞書型ではありません: {frame}")
                continue

            raw_timestamp = frame.get("timestamp", 0.0)
            try:
                timestamp = float(raw_timestamp)
            except (ValueError, TypeError):
                logger.warning(f"⚠️ timestamp が数値に変換できません: {raw_timestamp}")
                timestamp = 0.0

            img_name = frame.get("path", "")
            if not isinstance(img_name, str):
                img_name = str(img_name)
            img_path = img_dir / img_name

            # 1. ローカルでの静的・ヒューリスティック事前チェック
            whisper_text = ""
            for seg in segments:
                try:
                    seg_start = float(seg.get("start", 0.0))
                except (ValueError, TypeError):
                    seg_start = 0.0
                if abs(seg_start - timestamp) < 1.5:
                    raw_text = seg.get("text", "")
                    whisper_text = str(raw_text) if raw_text is not None else ""
                    break

            local_violations = []
            if whisper_text:
                lines = [t.strip() for t in re.split(r'[、。！？\n]', whisper_text) if t.strip()]
                for line in lines:
                    if len(line) > 15:
                        local_violations.append(f"1行が15文字を超えています ({len(line)}文字) — NHK基準違反。")

            if local_violations:
                logger.info(f"🚫 ローカル静的判定で違反検出 (ts={timestamp}): {local_violations[0]}")
                results.append({
                    "timestamp": timestamp,
                    "subtitle_overlap_detected": True,
                    "subtitle_layout_ok": False,
                    "font_size_appropriate": False,
                    "contrast_ok": True,
                    "improvement_suggestions": " ".join(local_violations)
                })
                continue

            # 2. Vision APIによる実際の画像検品
            # API枠枯渇時は自動的にヒューリスティックにフォールバック
            if client is not None and img_path.exists() and not getattr(self, '_vision_api_exhausted', False):
                try:
                    import base64
                    import time
                    from backend.model_registry import get_model

                    logger.info(f"🔮 Vision API を実行中... (ts={timestamp})")
                    time.sleep(2.0)

                    img_bytes = img_path.read_bytes()
                    mime_type = "image/jpeg"

                    prompt = """
                    **[System Instructions]**
                    あなたは動画検品AIです。このプレビューフレーム画像を分析し、以下のJSON形式でのみ回答してください。
                    評価項目:
                    - subtitle_overlap_detected (true/false): 字幕が話者の顔やロゴ等に被っているか
                    - subtitle_layout_ok (true/false): 字幕の配置（下帯）が適切か
                    - font_size_appropriate (true/false): 字幕のサイズが適切か
                    - contrast_ok (true/false): 字幕の背景帯とのコントラストが十分か
                    - improvement_suggestions (string): 改善案（なしの場合は空文字列）

                    回答形式:
                    {"subtitle_overlap_detected":false,"subtitle_layout_ok":true,"font_size_appropriate":true,"contrast_ok":true,"improvement_suggestions":""}
                    """

                    resolved_model = get_model("quality_gate")
                    response = client.models.generate_content(
                        model=resolved_model,
                        contents=[{
                            "role": "user",
                            "parts": [
                                {"text": prompt},
                                {"inline_data": {
                                    "mime_type": mime_type,
                                    "data": base64.b64encode(img_bytes).decode("utf-8")
                                }}
                            ]
                        }]
                    )

                    text = response.text.strip()
                    if "```" in text:
                        text = text.split("```")[1]
                        if text.startswith("json"):
                            text = text[4:]
                        text = text.strip()

                    res_dict = json.loads(text)
                    if not isinstance(res_dict, dict):
                        raise TypeError("Vision API response is not a JSON object")

                    # 必要なキーの補完ガード
                    required_keys = ["subtitle_overlap_detected", "subtitle_layout_ok", "font_size_appropriate", "contrast_ok", "improvement_suggestions"]
                    for rkey in required_keys:
                        if rkey not in res_dict:
                            if rkey == "improvement_suggestions":
                                res_dict[rkey] = ""
                            else:
                                res_dict[rkey] = True if rkey != "subtitle_overlap_detected" else False

                    res_dict["timestamp"] = timestamp
                    results.append(res_dict)
                    continue
                except (json.JSONDecodeError, TypeError, AttributeError, ValueError, OSError, KeyError) as e:
                    logger.exception(f"⚠️ Vision API 応答解析エラーまたはファイル・キーエラー (timestamp={timestamp})")
                except (APIError, httpx.HTTPError) as e:
                    error_str = str(e)
                    if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                        # API枠枯渇 — 以降の全フレームでVision APIをスキップ
                        self._vision_api_exhausted = True
                        logger.warning(f"⚠️ API枠枯渇を検出。以降はヒューリスティック検品に切り替えます。")
                    else:
                        logger.error(f"⚠️ Vision API 実行エラー (timestamp={timestamp}): {e}")
                        # 技術負債台帳に登録（新規エラーガードのため）
                        try:
                            from backend.agents.memory.technical_debt import TechnicalDebtStore
                            store = TechnicalDebtStore()
                            store.register_debt(
                                category="MINOR_INFRA",
                                file_path="backend/self_improvement_engine.py",
                                line_number=212,
                                pattern="except (APIError, httpx.HTTPError) as e: (Vision API エラーガード)",
                                cause_pattern="DP-01",
                                fix_pattern="より具体的な例外キャッチへのリファクタリング",
                                registered_by="phase_26",
                                notes="Vision API応答処理で発生する具体的な例外を捕捉するためのガード"
                            )
                        except (ImportError, ValueError, OSError, json.JSONDecodeError) as tde:
                            logger.error(f"TechnicalDebtStoreへの登録に失敗: {tde}")


            # フォールバック: メタデータからヒューリスティックに擬似検品結果を生成
            overlap = False
            layout_ok = True
            font_size_ok = True
            contrast_ok = True
            suggestions = []

            if whisper_text:
                lines = whisper_text.split("\n")
                for line in lines:
                    if len(line) > 15:
                        layout_ok = False
                        font_size_ok = False
                        overlap = True
                        suggestions.append("1行が15文字を超えています。")

            results.append({
                "timestamp": timestamp,
                "subtitle_overlap_detected": overlap,
                "subtitle_layout_ok": layout_ok,
                "font_size_appropriate": font_size_ok,
                "contrast_ok": contrast_ok,
                "improvement_suggestions": " ".join(suggestions)
            })

        return results

    def analyze_weaknesses(self, inspect_results: list[dict]) -> dict:
        """② 22種品質ゲートプラグインによる弱点分析

        quality_gate_plugins.py の run_all_plugins() を直接呼び出し、
        全22プラグインのカテゴリ別スコアを取得する。

        合格基準（憲法§8.2準拠）:
          - 総合スコア 90点以上
          - 全カテゴリ 80点以上
        """
        if not isinstance(inspect_results, list):
            logger.warning("⚠️ inspect_results がリスト型ではありません。空リストとして扱います。")
            inspect_results = []

        segments = self._load_whisper_segments()

        # プレビュー動画のパスを取得
        preview_path = self._find_latest_preview()

        # 品質ゲートコンテキストを構築
        metadata = self._load_youtube_metadata()
        if not metadata and segments:
            # メタデータ未生成 → metadata_generator でヒューリスティック生成
            metadata = self._generate_youtube_metadata_fallback(segments)
        ctx = QualityGateContext(
            segments=segments,
            selected_segments=segments,  # SmartCut後はselected = segments
            preview_path=str(preview_path) if preview_path else None,
            metadata=metadata
        )

        # テンプレート設定を読み込む
        template_config = self._load_template_config()

        # 22種品質ゲートプラグインを全実行
        try:
            sys.path.insert(0, str(BACKEND_DIR))
            from quality_gate_plugins import run_all_plugins
        except ImportError as e:
            logger.error(f"❌ 品質ゲートプラグインの読み込みに失敗: {e}")
            # フォールバック: 最低限のスコアを返す
            return self._fallback_analysis(inspect_results, segments)

        try:
            plugin_result = run_all_plugins(ctx, template_config)
        except (ImportError, AttributeError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as e:
            logger.exception("❌ 品質ゲートプラグインの実行中に予期せぬエラーが発生しました")
            return self._fallback_analysis(inspect_results, segments)

        # プラグイン結果をスコア体系に変換
        category_scores = plugin_result.get("category_scores", {})
        final_score = plugin_result.get("final_score", 0)
        feedback = plugin_result.get("feedback", [])
        category_report = plugin_result.get("category_report", [])

        # Vision検品結果からの追加フィードバックと減点
        vision_violations = 0
        vision_deductions = 0
        for res in inspect_results:
            if res.get("subtitle_overlap_detected", False):
                vision_violations += 1
                vision_deductions += 15  # 字幕被りは重大なレイアウト違反として15点減点
                feedback.append(
                    f"🔍 Vision検品 (ts={res.get('timestamp')}): "
                    f"字幕被り検出 - {res.get('improvement_suggestions', '')}"
                )

        # 総合スコアの最終調整（Vision減点を反映）
        final_score = max(0, final_score - vision_deductions)

        # 合格判定
        all_categories_pass = all(
            (score is not None and score >= PASS_CATEGORY_SCORE)
            for score in category_scores.values()
            if score is not None
        )
        total_pass = final_score >= PASS_TOTAL_SCORE

        return {
            "scores": {
                "total_score": final_score,
                "stability": category_scores.get("stability"),
                "core": category_scores.get("core"),
                "template": category_scores.get("template"),
                "broadcast": category_scores.get("broadcast"),
                "youtube": category_scores.get("youtube"),
            },
            "all_categories_pass": all_categories_pass,
            "total_pass": total_pass,
            "passed": all_categories_pass and total_pass and (vision_violations == 0),
            "vision_violations": vision_violations,
            "feedback": feedback,
            "category_report": category_report,
            "plugin_results": plugin_result.get("plugin_results", {}),
        }

    def save_results(self, analysis: dict):
        """③ 弱点レポート出力＆履歴積上"""
        if not isinstance(analysis, dict):
            logger.error("❌ analysis が辞書型ではありません。保存をスキップします。")
            return

        scores = analysis.get("scores")
        if not isinstance(scores, dict):
            logger.error("❌ analysis の scores が辞書型ではありません。保存をスキップします。")
            return

        report_path = self.artifacts_dir / "weakness_analysis_report.md"

        # マークダウンレポート生成
        report_content = f"""# 動画品質 弱点分析レポート v2.0

生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
合格基準: 総合{PASS_TOTAL_SCORE}点以上 + 全カテゴリ{PASS_CATEGORY_SCORE}点以上（憲法§8.2準拠）

## 📊 品質スコア（22種プラグイン統合）

| カテゴリ | スコア | 合格ライン | 判定 |
|:---|:---:|:---:|:---:|
| **🛡️ 安定稼働** | {scores.get('stability', 'N/A')} | {PASS_CATEGORY_SCORE} | {'✅' if scores.get('stability') and scores['stability'] >= PASS_CATEGORY_SCORE else '❌'} |
| **🔧 コア品質** | {scores.get('core', 'N/A')} | {PASS_CATEGORY_SCORE} | {'✅' if scores.get('core') and scores['core'] >= PASS_CATEGORY_SCORE else '❌'} |
| **📺 テンプレート基準** | {scores.get('template', 'N/A')} | {PASS_CATEGORY_SCORE} | {'✅' if scores.get('template') and scores['template'] >= PASS_CATEGORY_SCORE else '❌'} |
| **📡 放送品質** | {scores.get('broadcast', 'N/A')} | {PASS_CATEGORY_SCORE} | {'✅' if scores.get('broadcast') and scores['broadcast'] >= PASS_CATEGORY_SCORE else '❌'} |
| **▶ YouTube最適化** | {scores.get('youtube', 'N/A')} | {PASS_CATEGORY_SCORE} | {'✅' if scores.get('youtube') and scores['youtube'] >= PASS_CATEGORY_SCORE else '❌'} |
| **総合スコア** | **{scores.get('total_score', 0)}** | **{PASS_TOTAL_SCORE}** | **{'🎉 合格' if analysis.get('passed') else '❌ 不合格'}** |

## ❌ 検出された弱点・フィードバック ({len(analysis.get('feedback', []))}件)
"""
        feedback = analysis.get('feedback', [])
        if not feedback:
            report_content += "\n🎉 弱点は検出されませんでした！業界基準を完全に満たしています。\n"
        else:
            for fb in feedback:
                report_content += f"- {fb}\n"

        report_content += "\n## 💡 自動改善推奨アクション\n"

        if scores.get('template') and scores['template'] < PASS_CATEGORY_SCORE:
            report_content += "- 📺 テンプレート基準: 字幕速度・フック強度・維持率の改善が必要\n"
        if scores.get('broadcast') and scores['broadcast'] < PASS_CATEGORY_SCORE:
            report_content += "- 📡 放送品質: ラウドネス・解像度・ビットレートの調整が必要\n"
        if scores.get('youtube') and scores['youtube'] < PASS_CATEGORY_SCORE:
            report_content += "- ▶ YouTube最適化: チャプター・メタデータ・CTR準備の改善が必要\n"

        try:
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report_content)
        except OSError as e:
            logger.error(f"❌ レポートの書き込みに失敗しました ({report_path}): {e}")

        # 履歴JSONへの積上
        history_path = self.artifacts_dir / "weakness_analysis_history.json"
        history = []
        if history_path.exists():
            try:
                with open(history_path, "r", encoding="utf-8") as f:
                    temp_history = json.load(f)
                    if isinstance(temp_history, list):
                        history = temp_history
                    else:
                        logger.warning(f"⚠️ 履歴ファイル {history_path} の形式がリストではありません。新規作成します。")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"⚠️ 履歴読み込み失敗: {e}")

        history.append({
            "timestamp": datetime.now().isoformat(),
            "iteration": len(history) + 1,
            "scores": scores,
            "passed": analysis.get("passed", False),
            "feedback_count": len(feedback),
            "vision_violations": analysis.get("vision_violations", 0),
        })

        try:
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ レポートと履歴の保存完了: iteration {len(history)}")
        except (json.JSONDecodeError, TypeError, OSError) as e:
            logger.error(f"❌ 履歴の保存に失敗しました ({history_path}): {e}")

    def auto_remediate(self, analysis: dict) -> bool:
        """④ 自動パラメータ改善（拡張版）

        分析結果に基づき、以下のパラメータを自律的に書き換えて品質基準に強制適合させる:
          - 字幕（NHK基準: max_chars_per_line, font_size, border_style, alignment）
          - 字幕速度（chars_per_second: セグメント分割の調整）
          - SmartCut（無音区間閾値: silence_threshold）
          - フック強化（冒頭無音カット）
          - ラウドネス（loudnorm ターゲット値）

        改善は「総合スコアが合格ラインを下回っている場合」に発動する。
        カテゴリ単位ではなくプラグイン個別結果を参照するため、
        カテゴリ80点以上でも個別プラグインに問題があれば修正する。
        """
        if not isinstance(analysis, dict):
            logger.error("❌ analysis が辞書型ではありません。自動改善をスキップします。")
            return False

        scores = analysis.get("scores")
        if not isinstance(scores, dict):
            logger.error("❌ scores が辞書型ではありません。自動改善をスキップします。")
            return False

        plugin_results = analysis.get("plugin_results", {})
        if not isinstance(plugin_results, dict):
            plugin_results = {}

        feedback = analysis.get("feedback", [])
        if not isinstance(feedback, list):
            feedback = []

        total_score = scores.get("total_score", 0)
        remediated = False

        # 総合スコアが合格ラインなら改善不要
        if total_score >= PASS_TOTAL_SCORE:
            logger.info(f"✅ 総合スコア {total_score} >= {PASS_TOTAL_SCORE} — 自動改善は不要です。")
            return False

        config_path = TEMPLATE_CONFIG_PATH
        if not config_path.exists():
            logger.warning(f"⚠️ template_config.py が見つかりません: {config_path}")
            return False

        try:
            content = config_path.read_text(encoding="utf-8")
            original_content = content
        except (OSError, ValueError) as e:
            logger.error(f"❌ template_config.py 読み込み失敗: {e}")
            return False

        # 1. 字幕速度超過の修正（最大のボトルネック）
        speed_result = plugin_results.get("subtitle_speed_check", {})
        speed_feedback = speed_result.get("feedback", [])
        if any("字幕速度超過" in fb or "字幕速度注意" in fb for fb in speed_feedback):
            # chars_per_second を制限して、速すぎるセグメントを分割させる
            if '"chars_per_second":' in content:
                content = re.sub(
                    r'"chars_per_second":\s*[\d.]+',
                    '"chars_per_second": 4',
                    content
                )
                logger.info("🔧 chars_per_second → 4 (NHK字幕基準に強制)")
            # max_chars_per_line を厳格化して字幕密度を下げる
            if '"max_chars_per_line":' in content:
                content = re.sub(r'"max_chars_per_line":\s*\d+', '"max_chars_per_line": 13', content)
                logger.info("🔧 max_chars_per_line → 13 (字幕速度低減のため厳格化)")

        # 2. NHK基準・字幕レイアウトの修正
        line_result = plugin_results.get("subtitle_line_check", {})
        line_feedback = line_result.get("feedback", [])
        if any("長い字幕行" in fb for fb in line_feedback):
            if '"max_chars_per_line":' in content:
                content = re.sub(r'"max_chars_per_line":\s*\d+', '"max_chars_per_line": 15', content)
                logger.info("🔧 max_chars_per_line → 15 (NHK基準)")
            if '"font_size_min_px":' in content:
                content = re.sub(r'"font_size_min_px":\s*\d+', '"font_size_min_px": 16', content)
            if '"border_style":' in content:
                content = re.sub(r'"border_style":\s*\d+', '"border_style": 4', content)
            if '"alignment":' in content:
                content = re.sub(r'"alignment":\s*\d+', '"alignment": 2', content)

        # 3. SmartCut無音区間の閾値修正
        dead_air_result = plugin_results.get("dead_air_check", {})
        dead_air_feedback = dead_air_result.get("feedback", [])
        if any("無音区間超過" in fb for fb in dead_air_feedback):
            if '"silence_threshold":' in content:
                content = re.sub(
                    r'"silence_threshold":\s*[\d.]+',
                    '"silence_threshold": 1.5',
                    content
                )
                logger.info("🔧 silence_threshold → 1.5s (無音カット厳格化)")
            if '"dead_air_max_seconds":' in content:
                content = re.sub(
                    r'"dead_air_max_seconds":\s*[\d.]+',
                    '"dead_air_max_seconds": 2.0',
                    content
                )
                logger.info("🔧 dead_air_max_seconds → 2.0s")

        # 4. フック強度の改善
        hook_result = plugin_results.get("hook_strength_check", {})
        hook_details = hook_result.get("details", {})
        hook_score = hook_details.get("hook_score", 100)
        if hook_score < 50:
            if '"hook_window_seconds":' in content:
                content = re.sub(
                    r'"hook_window_seconds":\s*\d+',
                    '"hook_window_seconds": 3',
                    content
                )
                logger.info("🔧 hook_window_seconds → 3 (フック強化)")

        # 5. ラウドネス調整
        loudness_result = plugin_results.get("loudness_check", {})
        loudness_feedback = loudness_result.get("feedback", [])
        if any("音量が小さすぎる" in fb for fb in loudness_feedback):
            if '"target_lufs":' in content:
                content = re.sub(
                    r'"target_lufs":\s*-?\d+',
                    '"target_lufs": -20',
                    content
                )
                logger.info("🔧 target_lufs → -20 (音量UP)")
        elif any("音量が大きすぎる" in fb for fb in loudness_feedback):
            if '"target_lufs":' in content:
                content = re.sub(
                    r'"target_lufs":\s*-?\d+',
                    '"target_lufs": -24',
                    content
                )
                logger.info("🔧 target_lufs → -24 (NHK放送基準)")

        # 変更があれば書き込み
        if content != original_content:
            try:
                config_path.write_text(content, encoding="utf-8")
                logger.info("✅ template_config.py のパラメータ自動改善完了")
                remediated = True
            except OSError as e:
                logger.error(f"❌ template_config.py 書き込み失敗: {e}")

        return remediated

    def run_loop(self, pipeline_callback, max_iterations=5) -> bool:
        """⑤ 改善ループの実行

        合格基準（総合90点 + 全カテゴリ80点）に達するまで
        パイプライン再生成・検品・改善を繰り返す。
        """
        for i in range(max_iterations):
            logger.info(f"\n{'='*70}")
            logger.info(f"🔄 自己改善ループ イテレーション {i+1}/{max_iterations} 開始...")
            logger.info(f"{'='*70}")

            # 各イテレーションの開始時にキャッシュをクリア
            self.clear_cache()

            # 1. パイプライン動画生成
            try:
                success = pipeline_callback()
            except (ImportError, AttributeError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as e:
                logger.exception("❌ パイプライン実行中に例外が発生しました")
                return False

            if not success:
                logger.error("❌ パイプライン実行に失敗しました。")
                return False

            # パイプライン実行後に再度キャッシュをクリア（最新の生成ファイルを取り込むため）
            self.clear_cache()

            # 2. プレビュー画像スキャン (①)
            inspect_results = self.auto_inspect()

            # 3. 22種品質ゲートプラグインによる弱点分析 (②)
            analysis = self.analyze_weaknesses(inspect_results)

            # 4. レポート作成と履歴積上 (③)
            self.save_results(analysis)

            # 5. 合格判定
            scores = analysis["scores"]
            logger.info(f"📊 スコア: 総合={scores.get('total_score', 0)} | "
                        f"安定={scores.get('stability')} | "
                        f"コア={scores.get('core')} | "
                        f"テンプレート={scores.get('template')} | "
                        f"放送={scores.get('broadcast')} | "
                        f"YouTube={scores.get('youtube')}")

            if analysis.get("passed"):
                logger.info(f"🎉 合格基準を達成しました！(Iteration {i+1})")
                logger.info(f"   総合: {scores.get('total_score')}/{PASS_TOTAL_SCORE}")
                return True

            # 6. 未合格なら自動パラメータ修正 (④) を行いループ継続
            logger.info("⚠️ 合格基準に未達。自動改善を実行します...")
            self.auto_remediate(analysis)

        logger.warning(
            f"⚠️ 最大イテレーション数 ({max_iterations}) に達しましたが、"
            f"完全合格には至りませんでした。"
        )
        return False

    # =========================================================
    # プライベートヘルパー
    # =========================================================

    def _load_youtube_metadata(self) -> dict:
        """YouTube用のメタデータを読み込む。
        
        検索順序:
        1. artifacts_dir / youtube_metadata.json
        2. backend/graded_previews/youtube_metadata.json
        3. vault-outputs/preview/metadata.json (auto_full_build出力)
        見つからない場合は空の辞書を返す。
        """
        search_paths = [
            self.artifacts_dir / "youtube_metadata.json",
            BACKEND_DIR / "graded_previews" / "youtube_metadata.json",
            BACKEND_DIR.parent / "vault-outputs" / "preview" / "metadata.json",
        ]
        
        for meta_path in search_paths:
            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # metadata_generator の出力形式を正規化
                    # title(単数) → titles(複数形リスト) に変換
                    if "title" in data and "titles" not in data:
                        data["titles"] = [data["title"]]
                    return data
                except (json.JSONDecodeError, OSError) as e:
                    logger.error(f"⚠️ YouTubeメタデータ読み込み失敗 ({meta_path}): {e}")
        return {}

    def _generate_youtube_metadata_fallback(self, segments: list[dict]) -> dict:
        """Whisperセグメントからメタデータをヒューリスティック生成し、JSONに保存。
        
        metadata_generator.py のロジックを呼び出し、プラグイン互換形式に変換。
        """
        try:
            sys.path.insert(0, str(BACKEND_DIR))
            from metadata_generator import generate_metadata
            
            preview_path = self._find_latest_preview()
            video_path = str(preview_path) if preview_path else ""
            output_dir = self.artifacts_dir
            
            metadata = generate_metadata(segments, video_path, output_dir)
            
            # プラグイン互換形式に正規化
            if "title" in metadata and "titles" not in metadata:
                metadata["titles"] = [metadata["title"]]
            
            # youtube_metadata.json としても保存（次回以降は _load で読める）
            yt_meta_path = output_dir / "youtube_metadata.json"
            with open(yt_meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            logger.info(
                f"✅ YouTubeメタデータ自動生成: "
                f"タイトル{len(metadata.get('titles', []))}案, "
                f"タグ{len(metadata.get('tags', []))}個, "
                f"チャプター{len(metadata.get('chapters', []))}個"
            )
            return metadata
        except (ImportError, AttributeError, ValueError, TypeError, KeyError, OSError, json.JSONDecodeError) as e:
            logger.exception("⚠️ メタデータ自動生成失敗")
            return {}

    def _load_whisper_segments(self) -> list[dict]:
        """最新のWhisperキャッシュセグメントを読み込む（キャッシュ機能付き）"""
        if self._cached_segments is not None:
            return self._cached_segments

        candidates = sorted(
            self.merged_dir.glob("_whisper_*.jsonl"),
            key=lambda p: p.stat().st_mtime
        )
        if not candidates:
            self._cached_segments = []
            return self._cached_segments

        latest = candidates[-1]
        segments = []
        try:
            with open(latest, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            parsed = json.loads(line)
                            if isinstance(parsed, dict):
                                segments.append(parsed)
                            else:
                                logger.warning("⚠️ Whisperキャッシュ行が辞書ではありません")
                        except json.JSONDecodeError as e:
                            logger.warning(f"⚠️ Whisperキャッシュ行の解析失敗 (スキップします): {e}")
        except OSError as e:
            logger.error(f"⚠️ Whisperキャッシュファイルオープン失敗: {e}")

        # format_segments を適用して実際の字幕状態を再現
        try:
            sys.path.insert(0, str(BACKEND_DIR))
            from template_config import template_config
            from subtitle_engine.text_formatter import format_segments
            max_chars = 15
            if template_config is not None:
                try:
                    max_chars = template_config.get_max_chars_per_line()
                except AttributeError:
                    pass
            segments = format_segments(segments, max_chars=max_chars)
        except (ImportError, AttributeError, ValueError, TypeError, KeyError) as e:
            logger.exception("⚠️ セグメント整形適用失敗")

        self._cached_segments = segments
        return segments

    def _find_latest_preview(self) -> Path | None:
        """最新のプレビュー動画ファイルを検索"""
        import glob

        # 1. vault-outputs/preview/ 内の最新
        preview_dir = BASE_DIR / "vault-outputs" / "preview"
        previews = sorted(
            glob.glob(str(preview_dir / "preview_*.mp4"))
        )
        if previews:
            return Path(previews[-1])

        # 2. ルートの soul_narrative_full_v1.mp4
        fallback = BASE_DIR / "soul_narrative_full_v1.mp4"
        if fallback.exists():
            return fallback

        return None

    def _load_template_config(self):
        """テンプレート設定を安全に読み込む"""
        try:
            sys.path.insert(0, str(BACKEND_DIR))
            from template_config import template_config
            return template_config
        except ImportError:
            logger.debug("template_config not available")
            return None

    def _fallback_analysis(self, inspect_results, segments):
        """品質ゲートプラグインが利用不可な場合のフォールバック分析"""
        nhk_violations = 0
        youtuber_violations = 0
        details = []

        for seg in segments:
            raw_text = seg.get("text", "")
            text = str(raw_text) if raw_text is not None else ""
            lines = [t.strip() for t in re.split(r'[、。！？\n]', text) if t.strip()]
            for line in lines:
                if len(line) > 15:
                    nhk_violations += 1
                    details.append(f"NHK基準違反: 「{line}」 ({len(line)}文字)")
                    break

        last_t = 0.0
        for seg in segments:
            start = seg.get("start", 0.0)
            if start - last_t > 10.0:
                youtuber_violations += 1
                details.append(
                    f"YouTuber基準違反: {last_t:.1f}s〜{start:.1f}s の区間で10秒以上の変化なし"
                )
            last_t = seg.get("end", start)

        nhk_score = max(0, 100 - nhk_violations * 10)
        youtuber_score = max(0, 100 - youtuber_violations * 10)
        total_score = int((nhk_score + youtuber_score) / 2)

        return {
            "scores": {
                "total_score": total_score,
                "stability": None,
                "core": None,
                "template": nhk_score,
                "broadcast": None,
                "youtube": youtuber_score,
            },
            "all_categories_pass": False,
            "total_pass": total_score >= PASS_TOTAL_SCORE,
            "passed": False,
            "vision_violations": 0,
            "feedback": details,
            "category_report": [],
            "plugin_results": {},
        }
