# -*- coding: utf-8 -*-
"""
report_generator.py — 検証レポート自動生成モジュール

stability_stress_metrics.json および quality_sweep_metrics.json を読み込み、
客観的データに基づいた Markdown レポートを生成・出力する。
"""
import os
import json
import logging
from datetime import datetime
import platform

logger = logging.getLogger(__name__)


def _parse_bool(value) -> bool:
    """様々な型を安全に boolean にパースする。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        val_lower = value.strip().lower()
        if val_lower in ("true", "1", "yes", "on"):
            return True
        if val_lower in ("false", "0", "no", "off"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _sanitize_markdown_cell(value) -> str:
    """Markdownテーブルのセル内に配置される値を安全な文字列にサニタイズする。"""
    if value is None:
        return ""
    # 文字列化し、改行やパイプ文字を無害化する
    s = str(value).replace("|", "\\|").replace("\n", " ").replace("\r", "")
    return s


def load_json_file(file_path: str) -> dict:
    """JSONファイルを安全に読み込む。存在しない、または破損している場合は空辞書を返す。"""
    try:
        if not file_path or not isinstance(file_path, str) or not os.path.exists(file_path):
            logger.warning(f"⚠️ ファイルが存在しないかパスが不正です: {file_path}")
            return {}
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"⚠️ JSONの内容が辞書ではありません: {file_path}")
                return {}
            return data
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as e:
        logger.error(f"❌ JSONファイル読み込み失敗 ({file_path}): {e}")
        return {}


def _parse_execution_time(stability_data: dict, quality_data: dict) -> str:
    """実行時刻を解析し、適切なフォーマットで返す。データがない場合は現在時刻を返す。"""
    if not isinstance(stability_data, dict):
        stability_data = {}
    if not isinstance(quality_data, dict):
        quality_data = {}
    raw_timestamp = quality_data.get("timestamp") or stability_data.get("timestamp")
    if raw_timestamp:
        try:
            parsed_time = datetime.fromisoformat(raw_timestamp).strftime('%Y-%m-%d %H:%M:%S')
            return _sanitize_markdown_cell(parsed_time)
        except (ValueError, TypeError):
            return _sanitize_markdown_cell(raw_timestamp)
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _build_memory_section(stability_data: dict) -> tuple[str, str, bool]:
    """メモリ使用量の推移テーブルと判定結果を構築する。"""
    if not isinstance(stability_data, dict):
        stability_data = {}
    memory_metrics = stability_data.get("memory_metrics")
    if not isinstance(memory_metrics, list):
        memory_metrics = []
        
    memory_table = "| 測定タイミング | メモリ使用量 (MB) |\n|:---|:---:|\n"
    if memory_metrics:
        for idx, metric in enumerate(memory_metrics, 1):
            if not isinstance(metric, dict):
                continue
            raw_time = metric.get("timestamp", f"測定点 {idx}")
            time_str = _sanitize_markdown_cell(raw_time)
            usage = metric.get("usage_mb", 0.0)
            try:
                memory_table += f"| {time_str} | {float(usage):.2f} MB |\n"
            except (ValueError, TypeError):
                usage_str = _sanitize_markdown_cell(usage)
                memory_table += f"| {time_str} | {usage_str} MB (無効な値) |\n"
    else:
        memory_table += "| 記録なし | - |\n"

    memory_leak = stability_data.get("memory_leak_detected", None)
    if memory_leak is None:
        memory_result = "➖ 判定データなし（未検証）"
        memory_passed = False
    else:
        memory_leak_bool = _parse_bool(memory_leak)
        if memory_leak_bool:
            memory_result = "⚠️ 異常（メモリリーク検出）"
            memory_passed = False
        else:
            memory_result = "✅ 正常（メモリリーク未検出）"
            memory_passed = True

    return memory_table, memory_result, memory_passed


def _build_cleanup_section(stability_data: dict) -> tuple[str, str, bool]:
    """ディスククリーンアップの実行レポートと判定結果を構築する。"""
    if not isinstance(stability_data, dict):
        stability_data = {}
    temp_dir_metrics = stability_data.get("temp_dir_metrics")
    if not isinstance(temp_dir_metrics, dict):
        temp_dir_metrics = {}
    initial_size = temp_dir_metrics.get("initial_size_bytes")
    final_size = temp_dir_metrics.get("final_size_bytes")
    cleanup_success = temp_dir_metrics.get("cleanup_success")

    initial_size_val = None
    if initial_size is not None:
        try:
            initial_size_val = int(initial_size)
        except (ValueError, TypeError):
            pass

    final_size_val = None
    if final_size is not None:
        try:
            final_size_val = int(final_size)
        except (ValueError, TypeError):
            pass

    cleanup_success_val = None
    if cleanup_success is not None:
        cleanup_success_val = _parse_bool(cleanup_success)

    cleanup_report = ""
    if initial_size_val is not None and final_size_val is not None:
        cleanup_report = (
            f"- 一時フォルダ初期サイズ: {initial_size_val} バイト\n"
            f"- 一時フォルダ最終サイズ: {final_size_val} バイト\n"
        )
        if cleanup_success_val is True or final_size_val == 0:
            cleanup_result = "✅ クリーンアップ成功（一時ファイルはすべて削除済み）"
            cleanup_passed = True
        else:
            cleanup_result = f"⚠️ クリーンアップ不完全（残存ファイルあり: {final_size_val} バイト）"
            cleanup_passed = False
    else:
        cleanup_report = "- 一時フォルダサイズ情報: 未取得\n"
        cleanup_result = "➖ 判定データなし（未検証）"
        cleanup_passed = False

    return cleanup_report, cleanup_result, cleanup_passed


def _build_ffmpeg_section(stability_data: dict) -> tuple[str, str, bool]:
    """FFmpeg子プロセスの残存状況レポートと判定結果を構築する。"""
    if not isinstance(stability_data, dict):
        stability_data = {}
    ffmpeg_metrics = stability_data.get("ffmpeg_process_metrics")
    if not isinstance(ffmpeg_metrics, dict):
        ffmpeg_metrics = {}
    child_processes = ffmpeg_metrics.get("remaining_child_processes")
    zombies = ffmpeg_metrics.get("zombie_processes")

    child_processes_val = None
    if child_processes is not None:
        try:
            child_processes_val = int(child_processes)
        except (ValueError, TypeError):
            pass

    zombies_val = None
    if zombies is not None:
        try:
            zombies_val = int(zombies)
        except (ValueError, TypeError):
            pass

    ffmpeg_report = ""
    if child_processes_val is not None and zombies_val is not None:
        ffmpeg_report = f"- 残存子プロセス数: {child_processes_val} 件\n- ゾンビプロセス数: {zombies_val} 件\n"
        if child_processes_val == 0 and zombies_val == 0:
            ffmpeg_result = "✅ 正常（残存プロセスなし）"
            ffmpeg_passed = True
        else:
            ffmpeg_result = f"⚠️ 異常（残存プロセスあり: 子={child_processes_val}, ゾンビ={zombies_val}）"
            ffmpeg_passed = False
    else:
        ffmpeg_report = "- プロセス残存情報: 未取得\n"
        ffmpeg_result = "➖ 判定データなし（未検証）"
        ffmpeg_passed = False

    return ffmpeg_report, ffmpeg_result, ffmpeg_passed


def _build_quality_section(quality_data: dict) -> tuple[str, str, str, bool]:
    """自己改善ループにおけるクオリティスコアの推移テーブルと判定結果を構築する。"""
    if not isinstance(quality_data, dict):
        quality_data = {}
    iterations = quality_data.get("iterations")
    if not isinstance(iterations, list):
        iterations = []
        
    quality_table = "| イテレーション | クオリティスコア | 判定 | Vision警告数 |\n|:---:|:---:|:---:|:---:|\n"
    if iterations:
        for it in iterations:
            if not isinstance(it, dict):
                continue
            it_num = it.get("iteration", 0)
            score = it.get("score", 0)
            passed = "合格" if _parse_bool(it.get("passed", False)) else "不合格"
            violations = it.get("vision_violations", 0)
            
            it_num_str = _sanitize_markdown_cell(it_num)
            score_str = _sanitize_markdown_cell(score)
            passed_str = _sanitize_markdown_cell(passed)
            violations_str = _sanitize_markdown_cell(violations)
            quality_table += f"| {it_num_str} | {score_str} 点 | {passed_str} | {violations_str} 件 |\n"
    else:
        quality_table += "| 記録なし | - | - | - |\n"

    final_score = quality_data.get("final_score")
    vision_violations = quality_data.get("vision_violations")
    quality_passed = quality_data.get("passed", False)
    quality_passed_bool = False

    if final_score is not None:
        try:
            final_score_val = float(final_score)
            violations_val = int(vision_violations) if vision_violations is not None else 0
            
            final_score_str = _sanitize_markdown_cell(final_score)
            violations_str = _sanitize_markdown_cell(vision_violations)
            quality_result = f"最終スコア {final_score_str} 点 (Vision警告: {violations_str} 件)"
            
            if _parse_bool(quality_passed) and final_score_val >= 80 and violations_val == 0:
                quality_status = "✅ 合格"
                quality_passed_bool = True
            else:
                quality_status = "⚠️ 不合格"
                quality_passed_bool = False
        except (ValueError, TypeError):
            final_score_str = _sanitize_markdown_cell(final_score)
            violations_str = _sanitize_markdown_cell(vision_violations)
            quality_result = f"品質データ異常 (スコア: {final_score_str}, 警告: {violations_str})"
            quality_status = "⚠️ 不合格"
            quality_passed_bool = False
    else:
        quality_result = "品質判定データなし"
        quality_status = "➖ 未検証"
        quality_passed_bool = False

    return quality_table, quality_status, quality_result, quality_passed_bool


def _build_fact_list(
    stability_data: dict,
    quality_data: dict,
    memory_passed: bool,
    cleanup_passed: bool,
    ffmpeg_passed: bool,
) -> str:
    """検証事実のリストを生成する。"""
    if not isinstance(stability_data, dict):
        stability_data = {}
    if not isinstance(quality_data, dict):
        quality_data = {}
    memory_leak = stability_data.get("memory_leak_detected", None)
    temp_dir_metrics = stability_data.get("temp_dir_metrics")
    if not isinstance(temp_dir_metrics, dict):
        temp_dir_metrics = {}
    initial_size = temp_dir_metrics.get("initial_size_bytes")

    ffmpeg_metrics = stability_data.get("ffmpeg_process_metrics")
    if not isinstance(ffmpeg_metrics, dict):
        ffmpeg_metrics = {}
    child_processes = ffmpeg_metrics.get("remaining_child_processes")

    final_score = quality_data.get("final_score")
    vision_violations = quality_data.get("vision_violations")

    if memory_leak is None:
        memory_leak_str = "未検証"
    else:
        memory_leak_bool = _parse_bool(memory_leak)
        memory_leak_str = "リーク検出あり" if memory_leak_bool else "リーク検出なし"

    cleanup_str = "完了" if cleanup_passed else "未完了" if initial_size is not None else "未検証"
    ffmpeg_str = "0 件" if ffmpeg_passed else "残存あり" if child_processes is not None else "未検証"
    
    final_score_str = _sanitize_markdown_cell(final_score) if final_score is not None else "未計測"
    vision_violations_str = _sanitize_markdown_cell(vision_violations) if vision_violations is not None else "未計測"

    cleanup_str = _sanitize_markdown_cell(cleanup_str)
    ffmpeg_str = _sanitize_markdown_cell(ffmpeg_str)

    return (
        f"1. メモリリーク検知結果: {memory_leak_str}。\n"
        f"2. 一時ファイル削除結果: {cleanup_str}。\n"
        f"3. FFmpeg残存プロセス: {ffmpeg_str}。\n"
        f"4. 自己改善ループ到達品質: 最終スコア {final_score_str} 点、Vision警告 {vision_violations_str} 件。"
    )


def generate_durability_report(stability_path: str, quality_path: str, output_path: str) -> bool:
    """
    メモリ負荷指標と品質チェック指標を読み込み、
    推測表現を一切使わずに事実のみで構成された Markdown レポートを出力する。
    """
    try:
        if not isinstance(stability_path, str) or not isinstance(quality_path, str) or not isinstance(output_path, str):
            logger.error("❌ 引数のパスが文字列ではありません")
            return False

        stability_data = load_json_file(stability_path)
        quality_data = load_json_file(quality_path)

        exec_platform = stability_data.get("platform", f"{platform.system()}-{platform.release()}")
        exec_time = _parse_execution_time(stability_data, quality_data)

        memory_table, memory_result, memory_passed = _build_memory_section(stability_data)
        cleanup_report, cleanup_result, cleanup_passed = _build_cleanup_section(stability_data)
        ffmpeg_report, ffmpeg_result, ffmpeg_passed = _build_ffmpeg_section(stability_data)
        quality_table, quality_status, quality_result, quality_passed_bool = _build_quality_section(quality_data)

        all_passed = memory_passed and cleanup_passed and ffmpeg_passed and quality_passed_bool
        overall_status = "👑 EXCELLENT" if all_passed else "⚠️ WARNING"

        fact_list = _build_fact_list(
            stability_data, quality_data, memory_passed, cleanup_passed, ffmpeg_passed
        )

        report_content = f"""# 新規RAW動画耐久・品質検証レポート

## 1. 検証概要
- **検証日時**: {exec_time}
- **実行プラットフォーム**: {exec_platform}
- **総合判定**: **{overall_status}**

---

## 2. システム負荷・リソース安定性（Stability & Stress）

### 2.1 メモリ使用量推移
{memory_table}
- **判定結果**: {memory_result}

### 2.2 ディスククリーンアップ
{cleanup_report}- **判定結果**: {cleanup_result}

### 2.3 FFmpegプロセス管理
{ffmpeg_report}- **判定結果**: {ffmpeg_result}

---

## 3. 自己改善ループ品質検証（Blind Quality Sweep）

### 3.1 イテレーション別スコア推移
{quality_table}
- **品質判定結果**: {quality_status} ({quality_result})

---

## 4. 検証事実リスト
{fact_list}
"""

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"✅ 検証レポートを生成しました: {output_path}")
        return True
    except OSError as e:
        logger.error(f"❌ 検証レポート書き込み失敗: {e}")
        return False
    except (TypeError, ValueError) as e:
        logger.error(f"❌ 不正なデータ型によるレポート生成失敗: {e}")
        return False
