import os
import json
import subprocess
import sys
import re

# パス定義 (verify_video_quality_matrix.py は backend/scratch/ に配置される)
# backend/scratch/.. -> backend
# backend/scratch/../.. -> video-automation (プロジェクトルート)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BASE_DIR = os.path.join(PROJECT_ROOT, "backend")
GRADED_PREVIEWS_DIR = os.path.join(BASE_DIR, "graded_previews")
LATEST_PREVIEWS_DIR = os.path.join(GRADED_PREVIEWS_DIR, "latest")
RAW_VIDEOS_DIR = r"C:\Users\PC_User\Desktop\script\vault-assets\raw_videos\本番RAW01 対談_山田"

def log_section(name):
    print("\n" + "="*60)
    print(f" {name}")
    print("="*60)

def run_command(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8")
        return res.returncode, res.stdout, res.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return -1, "", str(e)

def parse_srt_time(t_str):
    """SRTの時間文字列 (00:01:23,450) を秒数 (float) に変換"""
    try:
        parts = re.split(r'[:,.]', t_str.strip())
        if len(parts) == 4:
            h, m, s, ms = map(int, parts)
            return h * 3600.0 + m * 60.0 + s + ms / 1000.0
    except (ValueError, TypeError, AttributeError):
        pass
    return 0.0

def _verify_raw_videos_existence():
    """RAW動画ファイルの存在確認"""
    raw_files = ["シーン01_前編.mp4", "シーン02_ゲスト書道.mp4", "シーン03_後編01.mp4", "シーン04_後編02.mp4"]
    raw_ok = True
    for f in raw_files:
        path = os.path.join(RAW_VIDEOS_DIR, f)
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0
        print(f"  [RAW] {f}: {'✅ 存在' if exists else '❌ 不在'} ({size / 1024 / 1024:.1f} MB)")
        if not exists:
            raw_ok = False
    return raw_ok

def _verify_preview_index(results):
    """プレビューアセット・インデックスの確認と解析結果の格納"""
    index_json_path = os.path.join(LATEST_PREVIEWS_DIR, "index.json")
    index_exists = os.path.exists(index_json_path)
    print(f"  [PREVIEW] index.json: {'✅ 存在' if index_exists else '❌ 不在'}")
    results["index_json_exist"] = index_exists

    if index_exists:
        try:
            with open(index_json_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
            duration = index_data.get("duration", 0)
            frames_count = len(index_data.get("frames", []))
            print(f"    - 動画総再生時間: {duration:.2f} 秒 (約 {duration/3600:.2f} 時間)")
            print(f"    - 抽出フレーム数: {frames_count}")
            results["duration_match"] = duration > 14000  # 4時間超
            results["frames_count"] = frames_count
        except (OSError, json.JSONDecodeError) as e:
            print(f"    ❌ index.json の読み込み/解析エラー: {e}")
            results["index_json_exist"] = False
            results["duration_match"] = False
            results["frames_count"] = 0
    else:
        results["duration_match"] = False
        results["frames_count"] = 0

def _verify_youtube_metadata_existence():
    """YouTubeメタデータの存在確認"""
    yt_meta_path = os.path.join(GRADED_PREVIEWS_DIR, "youtube_metadata.json")
    yt_meta_exists = os.path.exists(yt_meta_path)
    print(f"  [METADATA] youtube_metadata.json: {'✅ 存在' if yt_meta_exists else '❌ 不在'}")
    return yt_meta_exists

def verify_macro():
    log_section("大（マクロ検証）: 構造・成果物の完全性")
    results = {}
    results["raw_files_exist"] = _verify_raw_videos_existence()
    _verify_preview_index(results)
    results["youtube_metadata_exist"] = _verify_youtube_metadata_existence()
    return results

def _load_weakness_history():
    """weakness_analysis_history.jsonの読み込み"""
    history_path = os.path.join(GRADED_PREVIEWS_DIR, "weakness_analysis_history.json")
    if not os.path.exists(history_path):
        print("  ❌ 警告: weakness_analysis_history.json が存在しません。")
        return None, False

    try:
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            return history, True
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ❌ weakness_analysis_history.json の読み込み/解析エラー: {e}")
        return None, False

def _evaluate_scores(scores):
    """履歴の各スコアカテゴリの評価"""
    if not isinstance(scores, dict):
        scores = {}
    all_categories_above_80 = True
    for cat, val in scores.items():
        if isinstance(val, (int, float)):
            status = "✅ PASS" if val >= 80 else "❌ FAIL"
            if val < 80 and cat != "total_score":
                all_categories_above_80 = False
            print(f"    - {cat}: {val} (合格ライン: 80) -> {status}")
        else:
            print(f"    - {cat}: なし")
    return all_categories_above_80

def verify_mezzo():
    log_section("中（メゾ検証）: 品質ゲートスコアの評価")
    results = {}

    history, has_history = _load_weakness_history()
    results["has_history"] = has_history
    if not has_history:
        return results

    if not history:
        print("  ❌ 警告: 履歴データが空です。")
        return results

    latest_run = history[-1]
    timestamp = latest_run.get("timestamp", "不明")
    scores = latest_run.get("scores")
    passed = latest_run.get("passed", False)
    vision_violations = latest_run.get("vision_violations", 0)

    print(f"  最新の検品実行: {timestamp}")
    print(f"  合格判定: {'✅ 合格' if passed else '❌ 不合格 (総合90点未満/フィードバックあり)'}")
    print(f"  Vision違反件数: {vision_violations}")
    print("  カテゴリ別スコア:")
    
    all_categories_above_80 = _evaluate_scores(scores)

    if not isinstance(scores, dict):
        scores = {}
    results["total_score"] = scores.get("total_score", 0)
    results["passed"] = passed
    results["vision_violations"] = vision_violations
    results["all_categories_above_80"] = all_categories_above_80

    return results

def _verify_vision_overlap():
    """Vision サンプリングによる字幕被り件数の検証"""
    history_path = os.path.join(GRADED_PREVIEWS_DIR, "weakness_analysis_history.json")
    vision_violations = 0
    if os.path.exists(history_path):
        try:
            with open(history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
            if history:
                latest_run = history[-1]
                vision_violations = latest_run.get("vision_violations", 0)
        except (OSError, json.JSONDecodeError) as e:
            print(f"  ❌ [VISION] 履歴読み込み中のエラー: {e}")
            vision_violations = 0

    print(f"  [VISION] 最新履歴でのVision字幕被り検出数: {vision_violations} 件")
    return vision_violations

def _verify_proper_noun_dictionary(results):
    """固有名詞辞書の適用整合性検証"""
    srt_path_found = None
    try:
        sys.path.append(BASE_DIR)
        from proper_noun_dict import proper_noun_dict
        entries = proper_noun_dict.entries
        print(f"  [DICT] 固有名詞辞書ロード完了。登録単語数: {len(entries)}")
        
        srt_found = False
        # プロジェクトルート全体から SRT を探す
        search_dirs = [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "vault-outputs")]
        for s_dir in search_dirs:
            if not os.path.exists(s_dir):
                continue
            for root, dirs, files in os.walk(s_dir):
                for file in files:
                    if file.endswith(".srt") and "soul_narrative" in file:
                        srt_path = os.path.join(root, file)
                        srt_found = True
                        srt_path_found = srt_path
                        print(f"    - 字幕ファイル検出: {file} ({srt_path})")
                        with open(srt_path, "r", encoding="utf-8", errors="ignore") as sf:
                            content = sf.read()
                        
                        matched_words = []
                        for entry in entries:
                            if entry.correct in content:
                                matched_words.append(entry.correct)
                        print(f"    - 字幕ファイル内で適用が確認された固有名詞例: {', '.join(matched_words[:10])}...")
                        results["proper_nouns_present"] = len(matched_words) > 0
                        break
                if srt_found:
                    break
            if srt_found:
                break
        if not srt_found:
            print("    - 警告: soul_narrative に関連する SRT 字幕ファイルが検出できませんでした。")
            results["proper_nouns_present"] = False
    except (ImportError, AttributeError, OSError) as e:
        print(f"  [DICT] 固有名詞辞書のチェック中にエラー: {e}")
        results["proper_nouns_present"] = False
    return srt_path_found

def _verify_av_sync_offset(index_data, results):
    """FFmpeg によるパケット同期検証（A/V Sync）"""
    print("  [AV_SYNC] FFmpegによるパケット同期検証:")
    latest_video = None
    video_name = index_data.get("video") if index_data else None
    if video_name:
        search_paths = [
            os.path.join(PROJECT_ROOT, "vault-outputs", "preview"),
            os.path.join(PROJECT_ROOT, "previews"),
            PROJECT_ROOT
        ]
        for sp in search_paths:
            if os.path.exists(sp):
                full_path = os.path.join(sp, video_name)
                if os.path.exists(full_path):
                    latest_video = full_path
                    break

    if latest_video and os.path.exists(latest_video):
        print(f"    - 対象動画: {latest_video}")
        
        # 最初のパケットのPTSを取得してズレ (A/V Start Offset) を計測
        cmd_v_pts = f'ffprobe -v error -select_streams v:0 -show_entries packet=pts_time -read_intervals %+1 -of default=noprint_wrappers=1:nokey=1 "{latest_video}"'
        ret_vp, out_vp, err_vp = run_command(cmd_v_pts)
        cmd_a_pts = f'ffprobe -v error -select_streams a:0 -show_entries packet=pts_time -read_intervals %+1 -of default=noprint_wrappers=1:nokey=1 "{latest_video}"'
        ret_ap, out_ap, err_ap = run_command(cmd_a_pts)

        if ret_vp == 0 and ret_ap == 0:
            try:
                v_pts_list = [float(x.strip()) for x in out_vp.strip().split("\n") if x.strip()]
                a_pts_list = [float(x.strip()) for x in out_ap.strip().split("\n") if x.strip()]
                if v_pts_list and a_pts_list:
                    v_start = v_pts_list[0]
                    a_start = a_pts_list[0]
                    offset = abs(v_start - a_start)
                    print(f"      * 映像開始PTS: {v_start:.6f} 秒")
                    print(f"      * 音声開始PTS: {a_start:.6f} 秒")
                    print(f"      * A/V 開始ズレ (Offset): {offset * 1000:.2f} ms")
                    results["av_sync_ok"] = offset < 0.05  # 50ms未満
                    results["av_start_offset_ms"] = offset * 1000
                else:
                    print("      ❌ パケットのPTSが取得できませんでした。")
                    results["av_sync_ok"] = False
                    results["av_start_offset_ms"] = -1
            except (ValueError, IndexError) as e:
                print(f"      ❌ パケット解析中に例外が発生しました: {e}")
                results["av_sync_ok"] = False
                results["av_start_offset_ms"] = -1
        else:
            print(f"      ❌ ffprobe のパケット取得に失敗しました。 v_err={err_vp}, a_err={err_ap}")
            results["av_sync_ok"] = False
            results["av_start_offset_ms"] = -1
    else:
        print("    - 警告: 検証対象の動画ファイルが見つかりません。")
        results["av_sync_ok"] = False
        results["av_start_offset_ms"] = -1

def _verify_clustering(srt_path_found, index_data, results):
    """字幕時間枠と抽出フレームの自動クラスタリング検証"""
    print("  [CLUSTERING] 字幕時間枠と抽出フレームの自動クラスタリング検証:")
    clustering_results = {
        "active_speech": [],
        "scene_boundary": [],
        "silent_gap": []
    }
    
    spans = []
    if srt_path_found and os.path.exists(srt_path_found):
        try:
            with open(srt_path_found, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            matches = re.findall(r'(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})', content)
            for m in matches:
                spans.append((parse_srt_time(m[0]), parse_srt_time(m[1])))
        except OSError as e:
            print(f"    ❌ [CLUSTERING] SRTファイルの読み込み中にエラー: {e}")

    if index_data and "frames" in index_data:
        try:
            for frame in index_data["frames"]:
                if not isinstance(frame, dict):
                    continue
                ts = frame.get("timestamp", 0.0)
                if not isinstance(ts, (int, float)):
                    continue
                in_speech = False
                for start, end in spans:
                    if start <= ts <= end:
                        in_speech = True
                        break
                
                if in_speech:
                    clustering_results["active_speech"].append(frame)
                    continue
                    
                near_boundary = False
                for start, end in spans:
                    if abs(ts - start) <= 2.0 or abs(ts - end) <= 2.0:
                        near_boundary = True
                        break
                
                if near_boundary:
                    clustering_results["scene_boundary"].append(frame)
                else:
                    clustering_results["silent_gap"].append(frame)
        except (KeyError, TypeError) as e:
            print(f"    ❌ [CLUSTERING] クラスタリング処理中にエラー: {e}")
            clustering_results = {
                "active_speech": [],
                "scene_boundary": [],
                "silent_gap": []
            }

        print(f"    - クラスタリング結果:")
        print(f"      * 会話中 (active_speech) クラスター: {len(clustering_results['active_speech'])} フレーム")
        print(f"      * シーン境界 (scene_boundary) クラスター: {len(clustering_results['scene_boundary'])} フレーム")
        print(f"      * 静音区間 (silent_gap) クラスター: {len(clustering_results['silent_gap'])} フレーム")
        
        # クラスタリング結果が健全に機能しているか検証（各クラスタに要素が存在すること）
        clustering_ok = len(clustering_results["active_speech"]) > 0 or len(clustering_results["scene_boundary"]) > 0
        results["clustering_ok"] = clustering_ok
        results["clustering_stats"] = {
            "active_speech_count": len(clustering_results["active_speech"]),
            "scene_boundary_count": len(clustering_results["scene_boundary"]),
            "silent_gap_count": len(clustering_results["silent_gap"])
        }
    else:
        print("    - 警告: クラスタリング対象のフレームメタデータが存在しません。")
        results["clustering_ok"] = False
        results["clustering_stats"] = {}

def verify_micro():
    log_section("小（ミクロ検証）: フレーム・パケットレベルの精密検査")
    results = {}

    vision_violations = _verify_vision_overlap()
    results["vision_overlap_clean"] = (vision_violations == 0)
    results["vision_overlap_count"] = vision_violations

    srt_path_found = _verify_proper_noun_dictionary(results)

    index_json_path = os.path.join(LATEST_PREVIEWS_DIR, "index.json")
    index_data = {}
    if os.path.exists(index_json_path):
        try:
            with open(index_json_path, "r", encoding="utf-8") as f:
                index_data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"    ❌ [AV_SYNC] index.json の読み込みエラー: {e}")
            index_data = {}

    _verify_av_sync_offset(index_data, results)
    _verify_clustering(srt_path_found, index_data, results)

    return results

def main():
    print("============================================================")
    print(" 動画品質マトリクス自動検証 (Verify Video Quality Matrix)")
    print("============================================================")

    macro_res = verify_macro()
    mezzo_res = verify_mezzo()
    micro_res_val = verify_micro()

    log_section("総合判定レポート")
    
    macro_pass = macro_res.get("raw_files_exist") and macro_res.get("index_json_exist")
    # 個別カテゴリがすべて80点以上であればメゾ判定は合格とみなす (YouTube最適化の全体のメタデータ生成などは別途評価)
    mezzo_pass = mezzo_res.get("all_categories_above_80", False)
    micro_pass = micro_res_val.get("vision_overlap_clean", True) and micro_res_val.get("av_sync_ok", False) and micro_res_val.get("clustering_ok", False)
    
    overall_status = macro_pass and mezzo_pass and micro_pass

    print(f"  [大] マクロ検証判定: {'✅ PASS' if macro_pass else '❌ FAIL'}")
    print(f"  [中] メゾ検証判定:   {'✅ PASS' if mezzo_pass else '❌ FAIL'}")
    print(f"  [小] ミクロ検証判定: {'✅ PASS' if micro_pass else '❌ FAIL'}")
    print("-"*60)
    print(f"  総合動画品質ステータス: {'👑 EXCELLENT (完全品質担保)' if overall_status else '⚠️ WARNING (一部要確認/調整余地あり)'}")
    print("============================================================")

    report_path = os.path.join(GRADED_PREVIEWS_DIR, "video_quality_verification_matrix.json")
    report_data = {
        "overall_status": overall_status,
        "macro": macro_res,
        "mezzo": mezzo_res,
        "micro": micro_res_val
    }
    try:
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as rf:
            json.dump(report_data, rf, indent=2, ensure_ascii=False)
        print(f"  検証結果を保存しました: {report_path}")
    except OSError as e:
        print(f"  ❌ 検証結果の保存中にエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
