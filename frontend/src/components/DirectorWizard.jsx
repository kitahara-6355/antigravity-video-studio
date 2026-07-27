import React, { useState } from 'react';

// Director Wizard Component
// Guides user through "Auto-Composition" selection.
// Director Wizard Component
// Guides user through "Auto-Composition" selection.
function DirectorWizard({ isOpen, onClose, onApplyTemplate }) {
    const [step, setStep] = useState(1);
    const [videoType, setVideoType] = useState('');
    const [duration, setDuration] = useState('10min');
    const [vibe, setVibe] = useState('professional'); // professional, fun, emotional
    const [isGenerating, setIsGenerating] = useState(false);
    const [generatedResult, setGeneratedResult] = useState({ scenes: [], audio: null });

    if (!isOpen) return null;

    const handleDiagnose = () => {
        if (!videoType) return;
        setIsGenerating(true);
        // Simulate AI thinking
        setTimeout(() => {
            const result = generateTemplate(videoType, duration, vibe);
            setGeneratedResult(result);
            setIsGenerating(false);
            setStep(2);
        }, 1500);
    };

    const handleApply = () => {
        onApplyTemplate(generatedResult.scenes, generatedResult.audio);
        onClose();
    };

    return (
        <div className="wizard-overlay">
            <div className="wizard-modal">
                <div className="wizard-header">
                    <h3>✨ AI Director Setup</h3>
                    <button className="close-btn" onClick={onClose}>×</button>
                </div>

                {step === 1 && (
                    <div className="wizard-body">
                        <section className="wizard-section">
                            <h4>1. 動画の形式 (Format)</h4>
                            <div className="option-grid">
                                <button
                                    className={`option-card ${videoType === 'interview' ? 'selected' : ''}`}
                                    onClick={() => setVideoType('interview')}
                                >
                                    🎙️ 対談・インタビュー
                                </button>
                                <button
                                    className={`option-card ${videoType === 'commentary' ? 'selected' : ''}`}
                                    onClick={() => setVideoType('commentary')}
                                >
                                    🗣️ 解説・プレゼン
                                </button>
                                <button
                                    className={`option-card ${videoType === 'vlog' ? 'selected' : ''}`}
                                    onClick={() => setVideoType('vlog')}
                                >
                                    📹 Vlog・密着
                                </button>
                            </div>
                        </section>

                        <section className="wizard-section">
                            <h4>2. 長さと雰囲気 (Length & Vibe)</h4>
                            <div className="input-group-row">
                                <div className="input-group">
                                    <label>⏱️ 動画の長さ</label>
                                    <select value={duration} onChange={(e) => setDuration(e.target.value)}>
                                        <option value="5min">ショート (5分以内)</option>
                                        <option value="10min">標準 (10分)</option>
                                        <option value="20min">長尺 (20分以上)</option>
                                    </select>
                                </div>
                                <div className="input-group">
                                    <label>🎵 BGMの雰囲気</label>
                                    <select value={vibe} onChange={(e) => setVibe(e.target.value)}>
                                        <option value="professional">信頼感・プロフェッショナル</option>
                                        <option value="fun">明るい・エンタメ</option>
                                        <option value="emotional">感動・エモーショナル</option>
                                        <option value="chill">落ち着いた・Chill</option>
                                    </select>
                                </div>
                            </div>
                        </section>

                        <div className="wizard-footer">
                            <button
                                className="btn-primary-large"
                                onClick={handleDiagnose}
                                disabled={!videoType || isGenerating}
                            >
                                {isGenerating ? "AIが構成を考え中..." : "AIに構成を提案してもらう"}
                            </button>
                        </div>
                    </div>
                )}

                {step === 2 && (
                    <div className="wizard-body">
                        <h4>AIが提案した構成案</h4>
                        <div className="ai-summary-badge">
                            <span>Format: {videoType}</span>
                            <span>Time: {duration}</span>
                            <span>Audio: {generatedResult.audio?.name || "Auto-Select"}</span>
                        </div>

                        <div className="scenes-preview-list">
                            {generatedResult.scenes.map((scene, idx) => (
                                <div key={idx} className="scene-item">
                                    <span className="scene-time">Scene {idx + 1}</span>
                                    <span className="scene-name">{scene.name}</span>
                                    <span className="scene-desc">{scene.description}</span>
                                </div>
                            ))}
                        </div>

                        <div className="wizard-footer">
                            <button className="btn-secondary" onClick={() => setStep(1)}>戻る</button>
                            <button className="btn-primary-large" onClick={handleApply}>この構成で作成する</button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

// Mock Logic for Template Generation (Phase 3.1)
function generateTemplate(type, duration, vibe) {
    // Select BGM based on vibe
    let bgm = { name: "Default Track", style: "Neutral" };
    if (vibe === 'professional') bgm = { name: "Corporate Vision", style: "Trustworthy" };
    if (vibe === 'fun') bgm = { name: "Happy Days", style: "Upbeat" };
    if (vibe === 'emotional') bgm = { name: "Tears in Rain", style: "Piano" };
    if (vibe === 'chill') bgm = { name: "Lo-Fi Study", style: "Relaxed" };

    let scenes = [];
    if (type === 'interview') {
        scenes = [
            { name: "サムネイル", description: "タイトルと出演者" },
            { name: "チャンネル紹介", description: "5秒ジングル" },
            { name: "対談相手紹介", description: "ゲストのプロフィール表示" },
            { name: "トーク1: テーマ導入", description: "本日の話題について" },
            { name: "活動紹介1", description: "ゲストの普段の活動映像" },
            { name: "場面転換", description: "アイキャッチ" },
            { name: "トーク2: 深掘り", description: "核心に迫るトーク" },
            { name: "活動紹介2", description: "関連する実績や商品" },
            { name: "まとめ・CTA", description: "登録・高評価のお願い" },
            { name: "終了画面", description: "おすすめ動画へのリンク" }
        ];
    } else {
        // Default fallback
        scenes = [
            { name: "オープニング", description: "挨拶" },
            { name: "本編", description: "メインコンテンツ" },
            { name: "エンディング", description: "まとめ" }
        ];
    }

    return { scenes, audio: bgm };
}

export default DirectorWizard;
