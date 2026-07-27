"""
Improved Theme Text Generator
キャッチーで両者らしさを出したテーマテキスト
"""

import copy
import json
import os
from pathlib import Path

# 改善されたテーマテキスト
IMPROVED_THEMES = {
    "scene01": {
        "themes": [
            {
                "id": "scene01_theme1",
                "original": "対談：手書き文字の価値",
                "improved": "書道家×デザイン書道作家 対談",
                "timing": "0:00-10:00",
                "description": "北原美麗（和歌山の書道家）と山田タロウ（東京のデザイン書道作家）の出会い"
            },
            {
                "id": "scene01_theme2",
                "original": "伝統工芸の未来",
                "improved": "いたちの毛が消える？筆職人の危機",
                "timing": "10:00-20:00",
                "description": "2022年から輸入停止、筆業界の深刻な現状"
            },
            {
                "id": "scene01_theme3",
                "original": "想いを筆で起こす",
                "improved": "文字で伝える、心を書く",
                "timing": "20:00-30:00",
                "description": "手書き文字だから伝わる想いの力"
            }
        ]
    },
    "scene03": {
        "themes": [
            {
                "id": "scene03_theme1",
                "original": "書道家の使命",
                "improved": "書道教室で繋ぐ文字文化",
                "timing": "0:00-3:30",
                "description": "次世代に伝える書道の魅力"
            },
            {
                "id": "scene03_theme2",
                "original": "文字文化の継承",
                "improved": "筆を持つ機会を増やす挑戦",
                "timing": "3:30-7:00",
                "description": "書道人口を増やす具体的な取り組み"
            }
        ]
    },
    "scene04": {
        "themes": [
            {
                "id": "scene04_theme1",
                "original": "筆の話",
                "improved": "コリンスキー筆の真真実",
                "timing": "0:00-2:45",
                "description": "プロが語る筆へのこだわり"
            },
            {
                "id": "scene04_theme2",
                "original": "書道の未来",
                "improved": "書道の未来を若い世代へ",
                "timing": "2:45-5:28",
                "description": "教育を通じた書道文化の継承"
            }
        ]
    }
}


def _resolve_themes_data(themes_data: dict[str, any] | None) -> dict[str, any]:
    """themes_data が None の場合にデフォルトの IMPROVED_THEMES を返すヘルパー"""
    return IMPROVED_THEMES if themes_data is None else themes_data


def _print_themes_table(themes_data: dict[str, any]) -> None:
    """テーマデータをコンソールにテーブル形式で表示"""
    print("\n" + "="*80)
    print("改善されたテーマテキスト一覧")
    print("="*80)
    print(f"{'シーン':<10} {'元のテーマ':<25} {'改善後':<30} {'タイミング'}")
    print("-"*80)
    
    for scene_key, scene_data in themes_data.items():
        scene_name = scene_key.replace("scene", "シーン")
        for theme in scene_data.get("themes", []):
            print(f"{scene_name:<10} {theme['original']:<25} {theme['improved']:<30} {theme['timing']}")
    
    print("="*80)


def _write_json_file(file_path: Path, themes_data: dict[str, any]) -> None:
    """JSONファイルとしてテーマデータを書き出す"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(themes_data, f, ensure_ascii=False, indent=2)


def _resolve_output_file_path(output_file: str | Path | None) -> Path:
    """保存先ファイルのPathオブジェクトを解決する"""
    if output_file is None:
        output_file = os.getenv("IMPROVED_THEMES_OUTPUT_FILE", "backend/temp/improved_themes.json")
    return Path(output_file)


def save_improved_themes(
    themes_data: dict[str, any] | None = None,
    output_file: str | Path | None = None
) -> dict[str, any]:
    """改善されたテーマをJSONで保存"""
    resolved_data = _resolve_themes_data(themes_data)
    output_path = _resolve_output_file_path(output_file)
    
    try:
        _write_json_file(output_path, resolved_data)
    except OSError as e:
        print(f"❌ Error: Failed to save improved themes to {output_path}: {e}")
        raise
        
    print(f"✅ Improved themes saved: {output_path}")
    _print_themes_table(resolved_data)
    
    return resolved_data


def _parse_time_code(time_code: str) -> tuple[int, int, int]:
    """タイムコード文字列を解析して (hours, minutes, seconds) の整数タプルを返す"""
    cleaned_time = time_code.strip()
    if not cleaned_time:
        raise ValueError("Time string cannot be empty")
        
    time_components = cleaned_time.split(":")
    if len(time_components) not in (2, 3):
        raise ValueError(f"Invalid time format (must be M:SS, MM:SS, or H:MM:SS): {time_code}")
        
    try:
        time_values = [int(c) for c in time_components]
    except ValueError:
        raise ValueError(f"Invalid non-integer value in time string: {time_code}")
        
    if len(time_values) == 2:
        return 0, time_values[0], time_values[1]
    return time_values[0], time_values[1], time_values[2]


def _normalize_time_components(hours: int, minutes: int, seconds: int) -> tuple[int, int, int]:
    """秒や分が60以上の場合に上位へ繰り上げて正規化する"""
    overflow_minutes, seconds = divmod(seconds, 60)
    minutes += overflow_minutes
    overflow_hours, minutes = divmod(minutes, 60)
    hours += overflow_hours
    return hours, minutes, seconds


def convert_time_to_srt_format(time_code: str) -> str:
    """タイムコード文字列(M:SS や MM:SS, H:MM:SS)をSRT用(HH:MM:SS,mmm)に変換"""
    hours, minutes, seconds = _parse_time_code(time_code)
    hours, minutes, seconds = _normalize_time_components(hours, minutes, seconds)
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},000"


def _format_srt_block(block_index: int, theme: dict[str, any]) -> list[str] | None:
    """1つのテーマ辞書からSRTブロックの行リストを生成する。不正なタイミングの場合は None を返す"""
    timing = theme.get("timing", "")
    if not isinstance(timing, str):
        raise TypeError("Timing must be a string")
        
    if "-" not in timing:
        return None
        
    start_time_str, end_time_str = timing.split("-", 1)
    try:
        formatted_start_time = convert_time_to_srt_format(start_time_str)
        formatted_end_time = convert_time_to_srt_format(end_time_str)
    except ValueError as e:
        # タイムコード変換エラーの場合は警告を出力してスキップ
        print(f"⚠️ Warning: Skip invalid timing '{timing}' in {theme.get('id')}: {e}")
        return None
        
    return [
        f"{block_index}",
        f"{formatted_start_time} --> {formatted_end_time}",
        f"{theme.get('improved', '')}",
        f"{theme.get('description', '')}",
        ""  # 空行で区切る
    ]


def _generate_srt_content(themes: list[dict[str, any]]) -> str:
    """テーマのリストからSRT字幕形式のテキストコンテンツを生成する"""
    srt_lines = []
    for block_index, theme in enumerate(themes, start=1):
        block = _format_srt_block(block_index, theme)
        if block:
            srt_lines.extend(block)
    return "\n".join(srt_lines)


def _write_srt_file(file_path: Path, content: str) -> None:
    """SRTファイルをディスクに書き出す物理的なI/O処理"""
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _export_scene_themes_as_srt(
    scene_id: str,
    scene_data: dict[str, any],
    output_path: Path
) -> Path | None:
    """単一シーンのテーマをSRTファイルに書き出す。書き出されなかった場合はNoneを返す"""
    themes = scene_data.get("themes", [])
    if not themes:
        return None
        
    srt_file_path = output_path / f"{scene_id}_themes.srt"
    formatted_srt_content = _generate_srt_content(themes)
    
    if not formatted_srt_content:
        return None
        
    try:
        _write_srt_file(srt_file_path, formatted_srt_content)
        print(f"🎬 SRT subtitle exported: {srt_file_path}")
        return srt_file_path
    except OSError as e:
        print(f"❌ Error: Failed to export SRT subtitle to {srt_file_path}: {e}")
        raise


def export_themes_as_srt(
    themes_data: dict[str, any] | None = None,
    output_dir: str | Path = "backend/temp"
) -> list[Path]:
    """テーマデータをSRT字幕ファイル形式で出力"""
    resolved_data = _resolve_themes_data(themes_data)
        
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    generated_files = []
    for scene_id, scene_data in resolved_data.items():
        srt_file_path = _export_scene_themes_as_srt(scene_id, scene_data, output_path)
        if srt_file_path:
            generated_files.append(srt_file_path)
            
    return generated_files


def get_theme_by_id(target_theme_id: str, themes_data: dict[str, any] | None = None) -> dict[str, any] | None:
    """テーマIDに一致するテーマを取得"""
    resolved_data = _resolve_themes_data(themes_data)
        
    for scene_data in resolved_data.values():
        for theme in scene_data.get("themes", []):
            if theme.get("id") == target_theme_id:
                return theme
    return None


def get_themes_by_scene(target_scene_id: str, themes_data: dict[str, any] | None = None) -> list[dict[str, any]]:
    """シーンIDに所属するテーマ一覧を取得"""
    resolved_data = _resolve_themes_data(themes_data)
        
    if target_scene_id in resolved_data:
        return resolved_data[target_scene_id].get("themes", [])
    return []


def _is_theme_matched(theme: dict[str, any], query_lower: str) -> bool:
    """テーマが検索クエリにマッチするかどうかを判定"""
    fields = ["original", "improved", "description"]
    return any(query_lower in theme.get(f, "").lower() for f in fields)


def search_themes(search_query: str, themes_data: dict[str, any] | None = None) -> list[dict[str, any]]:
    """オリジナル、改善テキスト、詳細説明にキーワードが含まれるテーマを検索"""
    resolved_data = _resolve_themes_data(themes_data)
        
    results = []
    query_lower = search_query.lower()
    
    for scene_data in resolved_data.values():
        for theme in scene_data.get("themes", []):
            if _is_theme_matched(theme, query_lower):
                results.append(theme)
    return results


def _update_existing_theme(
    theme: dict[str, any],
    original: str,
    improved: str,
    timing: str,
    description: str
) -> None:
    """既存のテーマ辞書の内容を更新する"""
    theme["original"] = original
    theme["improved"] = improved
    theme["timing"] = timing
    theme["description"] = description


def _add_new_theme(
    themes: list[dict[str, any]],
    theme_id: str,
    original: str,
    improved: str,
    timing: str,
    description: str
) -> None:
    """新規のテーマ辞書を作成してテーマリストに追加する"""
    themes.append({
        "id": theme_id,
        "original": original,
        "improved": improved,
        "timing": timing,
        "description": description
    })


def _generate_theme_id(scene_id: str, themes: list[dict[str, any]]) -> str:
    """テーマIDを自動生成する"""
    return f"{scene_id}_theme{len(themes) + 1}"


def _validate_theme_inputs(
    scene_id: str,
    original: str,
    improved: str,
    timing: str,
    description: str,
    target_theme_id: str | None = None
) -> None:
    """テーマ情報の入力値を検証する"""
    inputs = [
        ("scene_id", scene_id),
        ("original", original),
        ("improved", improved),
        ("timing", timing),
        ("description", description)
    ]
    if target_theme_id is not None:
        inputs.append(("target_theme_id", target_theme_id))

    for name, val in inputs:
        if not isinstance(val, str):
            raise TypeError(f"'{name}' must be a string")
        if not val.strip():
            raise ValueError(f"'{name}' cannot be empty or whitespace only")

    if "-" not in timing:
        raise ValueError(f"Invalid timing format (must contain '-'): {timing}")
        
    start_time_str, end_time_str = timing.split("-", 1)
    try:
        _parse_time_code(start_time_str)
        _parse_time_code(end_time_str)
    except ValueError as e:
        raise ValueError(f"Invalid time format in timing: {timing}. Detail: {e}")


def add_or_update_theme(
    scene_id: str,
    original: str,
    improved: str,
    timing: str,
    description: str,
    target_theme_id: str | None = None,
    themes_data: dict[str, any] | None = None
) -> dict[str, any]:
    """テーマを動的に追加・更新し、更新されたテーマ構造全体を返す"""
    _validate_theme_inputs(scene_id, original, improved, timing, description, target_theme_id)
    resolved_data = _resolve_themes_data(themes_data)
        
    # 元のデータをディープコピーして破壊的変更を避ける
    updated_data = copy.deepcopy(resolved_data)
    
    if scene_id not in updated_data:
        updated_data[scene_id] = {"themes": []}
        
    themes = updated_data[scene_id]["themes"]
    
    # ID指定がない場合は自動生成
    theme_id = target_theme_id if target_theme_id else _generate_theme_id(scene_id, themes)
        
    # 既存のテーマIDがあるか探す
    existing_theme = next((t for t in themes if t.get("id") == theme_id), None)
            
    if existing_theme:
        _update_existing_theme(existing_theme, original, improved, timing, description)
    else:
        _add_new_theme(themes, theme_id, original, improved, timing, description)
        
    return updated_data


if __name__ == "__main__":
    save_improved_themes()
    
    print("\n📝 改善ポイント:")
    print("  ✅ キャッチー: 具体的で興味を引くフレーズ")
    print("  ✅ 両者らしさ: 書道家×デザイン書道作家の組み合わせを明記")
    print("  ✅ 内容の特徴: 対談の核心（筆の危機、文字の力）を表現")
