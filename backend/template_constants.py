"""
template_constants.py — テンプレート設定用の定数定義

template_config.py から静的データを分離し、可読性を向上させる。
"""

PRODUCTION_TEMPLATES = {
    "nhk_documentary": {
        "id": "nhk_documentary",
        "name": "NHKドキュメンタリー",
        "label": "📺 NHKドキュメンタリー風",
        "description": "NHK報道・ドキュメンタリーに準拠した正統派フォーマット。正確性・視認性・ユニバーサルデザインを最優先。",
        "reference": "NHK字幕規格 + 民放連ガイドライン + 放送法基準",
        "target_genre": ["ドキュメンタリー", "教育", "解説", "インタビュー"],
        "subtitle_rules": {
            "chars_per_second": 4,
            "max_chars_per_line": 15,
            "max_lines": 2,
            "lead_frames": 3,
            "trail_frames": 5,
            "min_display_seconds": 1.5,
            "safe_area_margin_percent": 10,
            "font_size_min_px": 16,
            "outline_required": True,
            "accessibility": "ユニバーサルデザイン準拠（高コントラスト、明瞭なフォント）",
        },
        "engagement_rules": {
            "hook_window_seconds": 8,
            "dopamine_interval_seconds": 30,
            "reengagement_mark_seconds": 300,
            "dead_air_max_seconds": 5.0,
            "pacing": "ゆったりと深い語り。急がない。",
            "narration_style": "客観的・第三者視点",
        },
        "quality_benchmarks": {
            "ctr_target_percent": 3.5,
            "retention_target_percent": 45,
            "audio_loudness_lufs": -24,
            "color_grading": "自然な色味。誇張しない。肌色は忠実再現。",
        },
    },
    "mrbeast_entertainment": {
        "id": "mrbeast_entertainment",
        "name": "MrBeastエンタメ",
        "label": "🎬 MrBeastエンタメ風",
        "description": "MrBeast Production Systemに学ぶハイテンポ・高エンゲージメント型。3秒ルール＋10秒ドーパミンヒット。",
        "reference": "MrBeast Production System + YouTube Algorithm 2026",
        "target_genre": ["エンタメ", "チャレンジ", "企画", "バラエティ"],
        "subtitle_rules": {
            "chars_per_second": 4,
            "max_chars_per_line": 15,
            "max_lines": 2,
            "lead_frames": 2,
            "trail_frames": 3,
            "min_display_seconds": 0.8,
            "safe_area_margin_percent": 8,
            "font_size_min_px": 16,
            "outline_required": True,
            "kinetic_typography": True,
            "accessibility": "キネティックタイポグラフィでインパクト重視",
        },
        "engagement_rules": {
            "hook_window_seconds": 3,
            "dopamine_interval_seconds": 8,
            "reengagement_mark_seconds": 120,
            "dead_air_max_seconds": 1.0,
            "pacing": "超ハイテンポ。1秒の無駄もない。",
            "title_first": True,
            "narration_style": "一人称・感情的・テンション高め",
        },
        "quality_benchmarks": {
            "ctr_target_percent": 6.0,
            "retention_target_percent": 55,
            "audio_loudness_lufs": -14,
            "color_grading": "ビビッド＋高コントラスト。サムネ映えする色味。",
        },
    },
    "hikakin_vlog": {
        "id": "hikakin_vlog",
        "name": "HIKAKIN Vlog",
        "label": "🎤 HIKAKIN Vlog風",
        "description": "日本トップYouTuberに学ぶトーク＆Vlogスタイル。親しみやすさ＋テンポの良さ＋丁寧なテロップ。",
        "reference": "HIKAKIN/はじめしゃちょー等の日本トップYouTuber制作手法",
        "target_genre": ["Vlog", "トーク", "商品レビュー", "日常"],
        "subtitle_rules": {
            "chars_per_second": 4,
            "max_chars_per_line": 15,
            "max_lines": 2,
            "lead_frames": 3,
            "trail_frames": 5,
            "min_display_seconds": 1.2,
            "safe_area_margin_percent": 10,
            "font_size_min_px": 16,
            "outline_required": True,
            "emphasis_highlight": True,
            "accessibility": "サイレントファーストデザイン（音声なし視聴対応）",
        },
        "engagement_rules": {
            "hook_window_seconds": 5,
            "dopamine_interval_seconds": 10,
            "reengagement_mark_seconds": 180,
            "dead_air_max_seconds": 2.0,
            "pacing": "テンポよく、でも急ぎすぎない。視聴者との対話感。",
            "narration_style": "一人称・友達口調・リアクション豊か",
        },
        "quality_benchmarks": {
            "ctr_target_percent": 5.0,
            "retention_target_percent": 50,
            "audio_loudness_lufs": -16,
            "color_grading": "明るく自然。肌色を美しく保つ暖色寄り。",
        },
    },
    "asmr_relaxation": {
        "id": "asmr_relaxation",
        "name": "ASMR / リラックス",
        "label": "🌙 ASMR・リラックス風",
        "description": "ASMR・リラクゼーション・睡眠導入系の静寂フォーマット。最小限のテロップ、静けさが正義。",
        "reference": "ASMR専門チャンネル制作基準 + YouTube Audio Quality Guidelines",
        "target_genre": ["ASMR", "リラクゼーション", "睡眠", "環境音"],
        "subtitle_rules": {
            "chars_per_second": 4,
            "max_chars_per_line": 15,
            "max_lines": 1,
            "lead_frames": 4,
            "trail_frames": 8,
            "min_display_seconds": 2.0,
            "safe_area_margin_percent": 12,
            "font_size_min_px": 16,
            "outline_required": False,
            "minimal_telop": True,
            "accessibility": "最小限の字幕。映像と音の没入を妨げない。",
        },
        "engagement_rules": {
            "hook_window_seconds": 10,
            "dopamine_interval_seconds": 60,
            "reengagement_mark_seconds": 600,
            "dead_air_max_seconds": 30.0,
            "pacing": "超スロー。沈黙は演出。急がず、漂うように。",
            "narration_style": "囁き・最小限・ノンバーバル",
        },
        "quality_benchmarks": {
            "ctr_target_percent": 3.0,
            "retention_target_percent": 35,
            "audio_loudness_lufs": -28,
            "color_grading": "ダーク＋ロートーン。ブルーライト軽減を意識。",
        },
    },
}

MOOD_THEMES = {
    "warm": {
        "id": "warm",
        "label": "🌅 暖かみ",
        "description": "暖色系。親しみやすく落ち着いた雰囲気",
        "mood": "warm",
        "design_tokens": {
            "color_palette": {
                "main": "#f59e0b",
                "sub": "#d97706",
                "accent": "#ea580c",
                "background": "#fffbeb",
                "text": "#78350f",
            },
            "typography": {
                "font_family": "Noto Sans JP",
                "heading_weight": "bold",
                "body_size": "16px",
            },
            "motion": {
                "transition": "ease-out",
                "duration": "0.3s",
            },
        },
    },
    "cool": {
        "id": "cool",
        "label": "🧊 クール",
        "description": "寒色系。知的で洗練された雰囲気",
        "mood": "cool",
        "design_tokens": {
            "color_palette": {
                "main": "#3b82f6",
                "sub": "#2563eb",
                "accent": "#06b6d4",
                "background": "#eff6ff",
                "text": "#1e3a5f",
            },
            "typography": {
                "font_family": "Noto Sans JP",
                "heading_weight": "600",
                "body_size": "15px",
            },
            "motion": {
                "transition": "ease-in-out",
                "duration": "0.25s",
            },
        },
    },
    "energetic": {
        "id": "energetic",
        "label": "⚡ エネルギー",
        "description": "ビビッド。活力と勢いのある雰囲気",
        "mood": "energetic",
        "design_tokens": {
            "color_palette": {
                "main": "#ec4899",
                "sub": "#db2777",
                "accent": "#a855f7",
                "background": "#fdf2f8",
                "text": "#831843",
            },
            "typography": {
                "font_family": "Noto Sans JP",
                "heading_weight": "900",
                "body_size": "17px",
            },
            "motion": {
                "transition": "cubic-bezier(0.34, 1.56, 0.64, 1)",
                "duration": "0.35s",
            },
        },
    },
    "calm": {
        "id": "calm",
        "label": "🌙 静寂",
        "description": "ダークトーン。静かで落ち着いた雰囲気",
        "mood": "elegant",
        "design_tokens": {
            "color_palette": {
                "main": "#6366f1",
                "sub": "#4f46e5",
                "accent": "#8b5cf6",
                "background": "#eef2ff",
                "text": "#312e81",
            },
            "typography": {
                "font_family": "Noto Serif JP",
                "heading_weight": "500",
                "body_size": "15px",
            },
            "motion": {
                "transition": "ease",
                "duration": "0.5s",
            },
        },
    },
}

RECOMMENDED_COMBOS = {
    "nhk_documentary":       ["cool", "calm", "warm"],
    "mrbeast_entertainment": ["energetic", "warm", "cool"],
    "hikakin_vlog":           ["warm", "energetic", "cool"],
    "asmr_relaxation":       ["calm", "cool"],
}

_DEFAULT_SUBTITLE_RULES = {
    "chars_per_second": 4,
    "max_chars_per_line": 15,
    "max_lines": 2,
    "lead_frames": 3,
    "trail_frames": 5,
    "min_display_seconds": 1.2,
    "safe_area_margin_percent": 2,
    "font_size_min_px": 16,
    "outline_required": True,
    "border_style": 4,
    "alignment": 2,
}

_DEFAULT_ENGAGEMENT_RULES = {
    "hook_window_seconds": 5,
    "dopamine_interval_seconds": 10,
    "reengagement_mark_seconds": 180,
    "dead_air_max_seconds": 2.0,
}

_DEFAULT_QUALITY_BENCHMARKS = {
    "ctr_target_percent": 5.0,
    "retention_target_percent": 50,
    "audio_loudness_lufs": -16,
}
