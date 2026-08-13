/**
 * ThemeSelector.jsx — テンプレート × テーマ 2階層選択UI（U-13）
 *
 * フロー:
 *   ① テンプレート選択 — 業界水準の制作フォーマットを選ぶ
 *   ② テーマ選択 — 選んだテンプレート内で雰囲気を微調整
 *   ③ 「適用」ボタンで全シーンに一括反映
 */
import React, { useState, useCallback, useEffect } from 'react';
import {
    Palette, Check, Loader2, ChevronRight,
    Sun, Snowflake, Zap, Moon,
    Tv, Film, Mic, Coffee
} from 'lucide-react';
import './ThemeSelector.css';
import { apiFetch } from '../api/client.js';


// テンプレート（レイヤー1: 業界基準）
const TEMPLATE_PRESETS = [
    {
        id: 'nhk_documentary',
        label: '📺 NHKドキュメンタリー風',
        shortLabel: 'NHK',
        description: '正確性・視認性・ユニバーサルデザイン最優先',
        icon: Tv,
        genre: 'ドキュメンタリー・教育・解説',
        highlight: '1秒4文字 / 高コントラスト字幕 / ゆったりペース',
    },
    {
        id: 'mrbeast_entertainment',
        label: '🎬 MrBeastエンタメ風',
        shortLabel: 'MrBeast',
        description: '3秒ルール＋10秒ドーパミンヒット',
        icon: Film,
        genre: 'エンタメ・チャレンジ・バラエティ',
        highlight: '3秒フック / 無音禁止 / CTR 6%目標',
    },
    {
        id: 'hikakin_vlog',
        label: '🎤 HIKAKIN Vlog風',
        shortLabel: 'HIKAKIN',
        description: '親しみやすさ＋テンポの良さ＋丁寧なテロップ',
        icon: Mic,
        genre: 'Vlog・トーク・レビュー',
        highlight: '5秒フック / サイレントファースト / 維持率50%目標',
    },
    {
        id: 'asmr_relaxation',
        label: '🌙 ASMR・リラックス風',
        shortLabel: 'ASMR',
        description: '最小限テロップ。静けさが正義。',
        icon: Coffee,
        genre: 'ASMR・リラクゼーション・睡眠',
        highlight: '沈黙は演出 / 超スロー / 最小限字幕',
    },
];

// テーマ（レイヤー2: 雰囲気調整）
const THEME_PRESETS = [
    {
        id: 'warm', label: '🌅 暖かみ', description: '暖色系。親しみやすく落ち着いた',
        icon: Sun, colors: ['#f59e0b', '#d97706', '#ea580c', '#78350f'],
    },
    {
        id: 'cool', label: '🧊 クール', description: '寒色系。知的で洗練された',
        icon: Snowflake, colors: ['#3b82f6', '#2563eb', '#06b6d4', '#1e3a5f'],
    },
    {
        id: 'energetic', label: '⚡ エネルギー', description: 'ビビッド。活力と勢い',
        icon: Zap, colors: ['#ec4899', '#db2777', '#a855f7', '#831843'],
    },
    {
        id: 'calm', label: '🌙 静寂', description: 'ダークトーン。静かで落ち着いた',
        icon: Moon, colors: ['#6366f1', '#4f46e5', '#8b5cf6', '#312e81'],
    },
];

// テンプレートごとの推奨テーマ
const RECOMMENDED = {
    'nhk_documentary': ['cool', 'calm', 'warm'],
    'mrbeast_entertainment': ['energetic', 'warm', 'cool'],
    'hikakin_vlog': ['warm', 'energetic', 'cool'],
    'asmr_relaxation': ['calm', 'cool'],
};

const ThemeSelector = ({ onApply, isOpen = true, onClose, segments = [] }) => {
    const [step, setStep] = useState(1); // 1=テンプレート選択, 2=テーマ選択
    const [selectedTemplate, setSelectedTemplate] = useState(null);
    const [selectedTheme, setSelectedTheme] = useState(null);
    const [applying, setApplying] = useState(false);
    const [applied, setApplied] = useState(false);
    const [recommending, setRecommending] = useState(false);
    const [recommendResult, setRecommendResult] = useState(null);

    const recommended = selectedTemplate
        ? RECOMMENDED[selectedTemplate] || THEME_PRESETS.map(t => t.id)
        : [];

    // ━━━ UX-1修正: AIおまかせ推奨 ━━━
    const handleAutoRecommend = useCallback(async () => {
        setRecommending(true);
        try {
            const res = await apiFetch('postV1ThemesRecommend', { body: { segments, total_duration_seconds: 0 } });
            if (res.ok) {
                const data = await res.json();
                if (data.recommended) {
                    setSelectedTemplate(data.recommended.template_id);
                    setRecommendResult(data.recommended);
                    // 推奨テーマの第1候補を自動選択
                    const recThemes = data.recommended.recommended_themes;
                    if (recThemes && recThemes.length > 0) {
                        setSelectedTheme(recThemes[0]);
                    }
                    setStep(2);
                }
            }
        } catch (err) {
            console.warn('Recommend failed:', err);
        } finally {
            setRecommending(false);
        }
    }, [segments]);

    const handleTemplateSelect = useCallback((templateId) => {
        setSelectedTemplate(templateId);
        setSelectedTheme(null);
        setApplied(false);
        setRecommendResult(null);
        setStep(2); // テーマ選択へ
    }, []);

    const handleThemeSelect = useCallback((themeId) => {
        if (applying) return;
        setSelectedTheme(themeId);
        setApplied(false);
    }, [applying]);

    const handleApply = useCallback(async () => {
        if (!selectedTemplate || !selectedTheme || applying) return;
        setApplying(true);

        try {
            const res = await apiFetch('postV1ThemesApply', { body: {
                    template_id: selectedTemplate,
                    theme_id: selectedTheme,
                } });

            if (res.ok) {
                const data = await res.json();
                setApplied(true);
                onApply?.(data);
            }
        } catch (err) {
            console.warn('Apply failed:', err);
        } finally {
            setApplying(false);
        }
    }, [selectedTemplate, selectedTheme, applying, onApply]);

    const handleBack = () => {
        setStep(1);
        setSelectedTheme(null);
        setApplied(false);
    };

    if (!isOpen) return null;

    const tmplInfo = TEMPLATE_PRESETS.find(t => t.id === selectedTemplate);
    const themeInfo = THEME_PRESETS.find(t => t.id === selectedTheme);

    return (
        <div className="theme-selector-overlay">
            <div className="theme-selector-panel">
                {/* ヘッダー */}
                <div className="theme-selector-header">
                    <div className="header-title">
                        <Palette size={22} className="header-icon" />
                        <div>
                            <h2>{step === 1 ? 'テンプレートを選択' : 'テーマを選択'}</h2>
                            <p>{step === 1
                                ? '業界プロの制作ルールを採用します'
                                : `${tmplInfo?.shortLabel} の雰囲気を調整します`
                            }</p>
                        </div>
                    </div>
                    <div className="header-actions">
                        <div className="step-indicator">
                            <span className={step >= 1 ? 'active' : ''}>①</span>
                            <ChevronRight size={14} />
                            <span className={step >= 2 ? 'active' : ''}>②</span>
                        </div>
                        {onClose && <button className="close-btn" onClick={onClose}>✕</button>}
                    </div>
                </div>

                {/* ステップ1: テンプレート選択 */}
                {step === 1 && (
                    <div className="template-cards">
                        {/* UX-1: AIおまかせボタン */}
                        <button
                            className="template-card ai-recommend-card"
                            onClick={handleAutoRecommend}
                            disabled={recommending}
                        >
                            <div className="template-card-header">
                                <span style={{fontSize: '24px'}}>🤖</span>
                                <span className="template-label">
                                    {recommending ? '分析中...' : 'AIにおまかせ'}
                                </span>
                            </div>
                            <p className="template-desc">
                                素材を分析して最適なテンプレートを自動選択
                            </p>
                            <div className="template-highlight">
                                迷ったらこれ！ワンクリックでプロ品質
                            </div>
                            {recommendResult && (
                                <div className="recommend-result">
                                    ✅ {recommendResult.label} を推奨
                                    <br/>
                                    <small>{recommendResult.reasons?.[0]}</small>
                                </div>
                            )}
                        </button>
                        {TEMPLATE_PRESETS.map(tmpl => {
                            const Icon = tmpl.icon;
                            return (
                                <button
                                    key={tmpl.id}
                                    className={`template-card ${selectedTemplate === tmpl.id ? 'selected' : ''}`}
                                    onClick={() => handleTemplateSelect(tmpl.id)}
                                >
                                    <div className="template-card-header">
                                        <Icon size={24} />
                                        <span className="template-label">{tmpl.label}</span>
                                    </div>
                                    <p className="template-desc">{tmpl.description}</p>
                                    <div className="template-meta">
                                        <span className="genre-tag">{tmpl.genre}</span>
                                    </div>
                                    <div className="template-highlight">{tmpl.highlight}</div>
                                </button>
                            );
                        })}
                    </div>
                )}

                {/* ステップ2: テーマ選択 */}
                {step === 2 && (
                    <>
                        {/* 選択中テンプレートのサマリー */}
                        <div className="selected-template-bar">
                            <span>テンプレート: <b>{tmplInfo?.label}</b></span>
                            <button className="btn-change" onClick={handleBack}>変更</button>
                        </div>

                        <div className="theme-cards">
                            {THEME_PRESETS.map(theme => {
                                const Icon = theme.icon;
                                const isRecommended = recommended.includes(theme.id);
                                const isSelected = selectedTheme === theme.id;

                                return (
                                    <button
                                        key={theme.id}
                                        className={`theme-card ${isSelected ? 'selected' : ''} ${isRecommended ? 'recommended' : ''}`}
                                        onClick={() => handleThemeSelect(theme.id)}
                                    >
                                        {isRecommended && <span className="rec-badge">おすすめ</span>}
                                        <div className="theme-icon-row">
                                            <Icon size={20} />
                                            <span>{theme.label}</span>
                                        </div>
                                        <p>{theme.description}</p>
                                        <div className="color-preview">
                                            {theme.colors.map((c, i) => (
                                                <span key={i} style={{ background: c }} />
                                            ))}
                                        </div>
                                        {isSelected && (
                                            <div className="selection-check"><Check size={14} /></div>
                                        )}
                                    </button>
                                );
                            })}
                        </div>
                    </>
                )}

                {/* フッター */}
                <div className="theme-selector-footer">
                    <div className="footer-hint">
                        {applied
                            ? `✅ ${tmplInfo?.shortLabel} × ${themeInfo?.label} を適用しました`
                            : selectedTemplate && selectedTheme
                                ? `${tmplInfo?.shortLabel} × ${themeInfo?.label} を適用します`
                                : step === 1 ? 'テンプレートを選択してください' : 'テーマを選択してください'
                        }
                    </div>
                    <button
                        className="btn-apply-theme"
                        onClick={handleApply}
                        disabled={!selectedTemplate || !selectedTheme || applying || applied}
                    >
                        {applying ? (
                            <><Loader2 size={16} className="spin" /> 適用中...</>
                        ) : applied ? (
                            <><Check size={16} /> 適用完了</>
                        ) : (
                            <><Palette size={16} /> テンプレート × テーマ を適用</>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default ThemeSelector;
