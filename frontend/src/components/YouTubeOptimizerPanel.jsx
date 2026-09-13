/**
 * YouTubeOptimizerPanel.jsx - YouTube最適化統合パネル
 * 
 * youtube_uiux_expert_review.md 準拠:
 * - フック分析ダッシュボード
 * - A/Bサムネイルパネル
 * - SEOメタデータエディタ
 * - ハイライトタイムライン
 */
import React, { useState, useEffect } from 'react';
import './YouTubeOptimizer.css';
import { apiFetch } from '../gateway/client.js';


// === サブコンポーネント ===

/**
 * フック分析ダッシュボード
 */
const HookAnalysisDashboard = ({ hookData, onReanalyze, onAIImprove }) => {
    if (!hookData) return null;

    const getScoreColor = (score) => {
        if (score >= 80) return '#22c55e';
        if (score >= 60) return '#eab308';
        return '#ef4444';
    };

    return (
        <div className="hook-dashboard">
            <h3>🎣 フック分析（冒頭5秒）</h3>

            <div className="hook-score-container">
                <div className="hook-score-circle" style={{
                    borderColor: getScoreColor(hookData.score)
                }}>
                    <span className="hook-score-value">{Math.round(hookData.score)}</span>
                    <span className="hook-score-label">/100</span>
                </div>

                <div className="hook-details">
                    <div className="hook-type">
                        <span className="label">タイプ:</span>
                        <span className="value badge">{hookData.attention_grabber}</span>
                    </div>
                    <div className="hook-impact">
                        <span className="label">視聴維持への影響:</span>
                        <span className="value">{hookData.predicted_retention_impact}</span>
                    </div>
                </div>
            </div>

            <div className="hook-text-preview">
                <h4>冒頭テキスト:</h4>
                <p className="preview-text">"{hookData.first_5_seconds_text}"</p>
            </div>

            {hookData.improvement_suggestions?.length > 0 && (
                <div className="hook-suggestions">
                    <h4>💡 改善提案:</h4>
                    <ul>
                        {hookData.improvement_suggestions.map((suggestion, i) => (
                            <li key={i}>{suggestion}</li>
                        ))}
                    </ul>
                </div>
            )}

            <div className="hook-actions">
                <button className="btn-secondary" onClick={onReanalyze}>🔄 再分析</button>
                <button className="btn-primary" onClick={onAIImprove}>🤖 AIに改善案を依頼</button>
            </div>
        </div>
    );
};

// 案の見出し。`String.fromCharCode` は「合成された URL」の禁止に
// 引っかかる形なので使わない。**禁止の側を緩めずコードを直す** —
// 誤検出を消すために禁止を狭めたら、実際に検出が1つ減っていた
// （gate-verifier 1回目の反例 A1）。
const CANDIDATE_LABELS = ['A', 'B', 'C', 'D', 'E', 'F'];

/**
 * サムネイルA/Bテストパネル
 */
const ThumbnailABPanel = ({ thumbnails, selectedId, onSelect, onRegenerate, onCustomEdit, onUpload }) => {
    if (!thumbnails || thumbnails.length === 0) return null;

    return (
        <div className="thumbnail-ab-panel">
            <h3>🖼️ サムネイルA/Bテスト（3案比較）</h3>

            <div className="thumbnail-grid" data-testid="youtube-thumbnail-candidates">
                {thumbnails.map((thumb, i) => (
                    <div
                        key={thumb.id}
                        className={`thumbnail-card ${selectedId === thumb.id ? 'selected' : ''}`}
                        onClick={() => onSelect(thumb.id, i, thumbnails)}
                    >
                        <div className="thumbnail-preview">
                            {thumb.path ? (
                                <img src={thumb.path} alt={`案${i + 1}`} />
                            ) : (
                                <div className="thumbnail-placeholder">
                                    <span>案{CANDIDATE_LABELS[i] ?? i + 1}</span>
                                </div>
                            )}
                        </div>

                        <div className="thumbnail-info">
                            <div className="concept-badge">{thumb.concept}</div>
                            <div className="emotion-target">
                                狙う感情: <span>{thumb.target_emotion}</span>
                            </div>
                            <div className="text-overlay">
                                テキスト: {thumb.text_overlay}
                            </div>
                        </div>

                        <div className="ctr-prediction">
                            <div className="ctr-main">
                                予測CTR: <span className="ctr-value">{thumb.predicted_ctr}%</span>
                            </div>
                            {thumb.ctr_confidence && (
                                <div className="ctr-confidence">
                                    信頼区間: {thumb.ctr_confidence}
                                </div>
                            )}
                            {thumb.ctr_factors && (
                                <div className="ctr-factors">
                                    {thumb.ctr_factors.map((factor, j) => (
                                        <span key={j} className="factor-badge">{factor}</span>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="card-selection">
                            <input
                                type="radio"
                                checked={selectedId === thumb.id}
                                onChange={() => onSelect(thumb.id, i, thumbnails)}
                            />
                            <span>選択</span>
                        </div>
                    </div>
                ))}
            </div>

            <div className="thumbnail-actions">
                <button className="btn-secondary" onClick={onRegenerate}>🔄 再生成</button>
                <button className="btn-secondary" onClick={onCustomEdit}>🎨 カスタム編集</button>
                <button className="btn-primary" onClick={onUpload}>📤 アップロード</button>
            </div>
        </div>
    );
};

/**
 * SEOメタデータエディタ
 */
const SEOMetadataEditor = ({ seoData, onUpdate }) => {
    const [selectedTitleIndex, setSelectedTitleIndex] = useState(0);

    if (!seoData) return null;

    const copyToClipboard = (text) => {
        navigator.clipboard.writeText(text);
        alert('クリップボードにコピーしました');
    };

    return (
        <div className="seo-editor">
            <h3>🔍 SEOメタデータ</h3>

            <div className="seo-section">
                <h4>タイトル候補（クリックで選択）</h4>
                <div className="title-list" data-testid="youtube-title-candidates">
                    {seoData.title_candidates?.map((title, i) => (
                        <div
                            key={i}
                            className={`title-option ${selectedTitleIndex === i ? 'selected' : ''}`}
                            onClick={() => setSelectedTitleIndex(i)}
                        >
                            <input
                                type="radio"
                                checked={selectedTitleIndex === i}
                                onChange={() => setSelectedTitleIndex(i)}
                            />
                            <span className="title-text">{title}</span>
                            <span className="char-count">{title.length}/100</span>
                        </div>
                    ))}
                </div>
            </div>

            <div className="seo-section">
                <h4>説明文</h4>
                <div className="description-container">
                    <textarea
                        className="description-text"
                        data-testid="youtube-description"
                        value={seoData.description}
                        readOnly
                        rows={6}
                    />
                    <div className="description-actions">
                        <button onClick={() => copyToClipboard(seoData.description)}>📋 コピー</button>
                        <span className="char-count">{seoData.description?.length || 0}/5000</span>
                    </div>
                </div>
            </div>

            <div className="seo-section">
                <h4>タグ ({seoData.tags?.length || 0}個)</h4>
                <div className="tags-container" data-testid="youtube-tag-list">
                    {seoData.tags?.map((tag, i) => (
                        <span key={i} className="tag-badge">{tag}</span>
                    ))}
                </div>
            </div>

            <div className="seo-section">
                <h4>ハッシュタグ</h4>
                <div className="hashtags-container" data-testid="youtube-hashtag-list">
                    {seoData.hashtags?.map((tag, i) => (
                        <span key={i} className="hashtag-badge">{tag}</span>
                    ))}
                </div>
            </div>

            <div className="seo-section">
                <h4>チャプター ({seoData.chapters?.length || 0}個)</h4>
                <div className="chapters-container" data-testid="youtube-chapter-list">
                    {seoData.chapters?.map((chapter, i) => (
                        <div key={i} className="chapter-item">
                            <span className="chapter-time">{chapter.time}</span>
                            <span className="chapter-title">{chapter.title}</span>
                        </div>
                    ))}
                </div>
                <button
                    className="btn-copy-chapters"
                    onClick={() => copyToClipboard(
                        seoData.chapters?.map(c => `${c.time} ${c.title}`).join('\n') || ''
                    )}
                >
                    📋 チャプターをコピー
                </button>
            </div>
        </div>
    );
};

/**
 * ハイライトタイムライン
 */
const HighlightTimeline = ({ highlights, duration = 90, onAddToChapter, onAddToShorts }) => {
    if (!highlights || highlights.length === 0) return null;

    const getTypeEmoji = (type) => {
        const emojis = {
            '驚き': '😲',
            '発見': '💡',
            '転換': '🔄',
            '結論': '✅'
        };
        return emojis[type] || '📍';
    };

    const handleAddToChapter = () => {
        if (onAddToChapter) {
            onAddToChapter(highlights);
        } else {
            alert('チャプター追加機能を準備中です。（ハイライトからチャプターマーカーを自動生成します）');
        }
    };

    const handleAddToShorts = () => {
        if (onAddToShorts) {
            onAddToShorts(highlights);
        } else {
            alert('ショート動画候補機能を準備中です。（ハイライト箇所から60秒クリップを自動生成します）');
        }
    };

    return (
        <div className="highlight-timeline">
            <h3>⭐ ハイライト（盛り上がりの山場）</h3>

            <div className="timeline-visual">
                <div className="timeline-bar">
                    {highlights.map((h, i) => (
                        <div
                            key={i}
                            className="timeline-marker"
                            style={{ left: `${(h.timestamp / duration) * 100}%` }}
                            title={`${h.type}: ${h.keyword}`}
                        >
                            <span className="marker-emoji">{getTypeEmoji(h.type)}</span>
                        </div>
                    ))}
                </div>
                <div className="timeline-labels">
                    <span>0:00</span>
                    <span>{Math.floor(duration / 60)}:{String(duration % 60).padStart(2, '0')}</span>
                </div>
            </div>

            <div className="highlights-list">
                <h4>検出されたハイライト ({highlights.length}件)</h4>
                {highlights.map((h, i) => (
                    <div key={i} className="highlight-item">
                        <span className="highlight-time">
                            {Math.floor(h.timestamp / 60)}:{String(Math.floor(h.timestamp % 60)).padStart(2, '0')}
                        </span>
                        <span className="highlight-type badge">{h.type}</span>
                        <span className="highlight-keyword">「{h.keyword}」</span>
                        <span className="highlight-importance">重要度: {h.importance}</span>
                    </div>
                ))}
            </div>

            <div className="highlight-actions">
                <button className="btn-secondary" onClick={handleAddToChapter}>📌 チャプターに追加</button>
                <button className="btn-secondary" onClick={handleAddToShorts}>🎬 ショート動画候補に追加</button>
            </div>
        </div>
    );
};

// === メインコンポーネント ===

const YouTubeOptimizerPanel = ({ isOpen, onClose, segments, topics }) => {
    const [activeTab, setActiveTab] = useState('hook');
    const [optimizationData, setOptimizationData] = useState(null);
    const [selectedThumbnailId, setSelectedThumbnailId] = useState(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        if (isOpen && segments?.length > 0) {
            runOptimization();
        }
    }, [isOpen, segments]);

    const runOptimization = async () => {
        setLoading(true);
        try {
            const response = await apiFetch('postYoutubeOptimize', { body: {
                    segments: segments || [],
                    topics: topics || [],
                    context: { topic: topics?.[0] || '' }
                } });

            if (response.ok) {
                const data = await response.json();
                setOptimizationData(data);
                if (data.thumbnail_candidates?.length > 0) {
                    setSelectedThumbnailId(data.thumbnail_candidates[0].id);
                }
            }
        } catch (error) {
            console.error('YouTube optimization failed:', error);
        } finally {
            setLoading(false);
        }
    };

    // === ハンドラ関数 ===

    // A/Bテスト選択をAPIに記録
    const handleThumbnailSelect = async (thumbId, index, thumbnails) => {
        setSelectedThumbnailId(thumbId);

        try {
            await apiFetch('postThumbnailSelect', { body: {
                    video_id: optimizationData?.task_id || `video_${Date.now()}`,
                    selected_index: index,
                    thumbnail_concepts: thumbnails.map(t => t.concept),
                    predicted_ctrs: thumbnails.map(t => t.predicted_ctr),
                    reason: "ユーザー選択"
                } });
            console.log('Thumbnail selection recorded');
        } catch (error) {
            console.error('Failed to record thumbnail selection:', error);
        }
    };

    // フック再分析
    const handleReanalyze = () => {
        runOptimization();
    };

    // AI改善案依頼
    const handleAIImprove = async () => {
        if (!optimizationData?.hook_analysis) {
            alert('フック分析を先に実行してください');
            return;
        }

        setLoading(true);
        try {
            const response = await apiFetch('postYoutubeImproveHook', { body: {
                    hook_text: optimizationData.hook_analysis.first_5_seconds_text || '',
                    current_score: optimizationData.hook_score || 0,
                    hook_analysis: optimizationData.hook_analysis,
                    video_topic: topics?.[0] || ''
                } });

            if (response.ok) {
                const data = await response.json();
                if (data.improvements && data.improvements.length > 0) {
                    // 改善案選択ダイアログを表示
                    const typeName = { attention: '注意型', emotion: '感情型', curiosity: '好奇心型' };
                    const options = data.improvements.map((imp, i) =>
                        `${i + 1}. 【${typeName[imp.type] || imp.type}】+${imp.expected_score_boost}点\n` +
                        `   「${imp.improved_text}」\n` +
                        `   理由: ${imp.rationale}`
                    ).join('\n\n');

                    const input = prompt(`🤖 AI改善案（3案）\n\n${options}\n\n${data.analysis_summary}\n\n適用する番号を入力してください（1-3）\nキャンセルする場合は空欄のまま`);

                    if (input && input.trim()) {
                        const num = parseInt(input.trim(), 10);
                        if (num >= 1 && num <= data.improvements.length) {
                            const selected = data.improvements[num - 1];
                            // ワンクリック適用
                            const applyRes = await apiFetch('postYoutubeApplyHook', { body: {
                                    task_id: optimizationData?.task_id || `task_${Date.now()}`,
                                    improvement_type: selected.type,
                                    improved_text: selected.improved_text,
                                    original_text: selected.original_text,
                                    expected_score_boost: selected.expected_score_boost
                                } });
                            if (applyRes.ok) {
                                const result = await applyRes.json();
                                alert(`✅ ${result.message}\n\n適用されたテキスト:\n「${selected.improved_text}」`);
                            }
                        }
                    }
                } else {
                    alert('改善案を生成できませんでした');
                }
            } else {
                alert('APIエラーが発生しました');
            }
        } catch (error) {
            console.error('AI improvement failed:', error);
            alert('AI改善案の取得に失敗しました');
        } finally {
            setLoading(false);
        }
    };

    // カスタム編集
    const handleCustomEdit = () => {
        alert('カスタム編集機能を準備中です。（サムネイルのテキストや色を調整できます）');
    };

    // YouTubeアップロード
    const handleUpload = () => {
        alert('YouTube連携は今後の実装予定です。（現在はサムネイル画像をダウンロードして手動アップロードしてください）');
    };

    // 設定保存
    const handleSaveSettings = async () => {
        try {
            const settings = {
                selected_thumbnail_id: selectedThumbnailId,
                seo_metadata: optimizationData?.seo_metadata,
                highlights: optimizationData?.highlights,
                saved_at: new Date().toISOString()
            };
            localStorage.setItem('youtube_optimizer_settings', JSON.stringify(settings));
            alert('設定を保存しました');
        } catch (error) {
            console.error('Failed to save settings:', error);
        }
    };

    if (!isOpen) return null;

    const tabs = [
        { id: 'hook', label: '🎣 フック', component: HookAnalysisDashboard },
        { id: 'thumbnail', label: '🖼️ サムネ', component: ThumbnailABPanel },
        { id: 'seo', label: '🔍 SEO', component: SEOMetadataEditor },
        { id: 'highlight', label: '⭐ 山場', component: HighlightTimeline }
    ];

    // ── 全体スコア（R1.5-C4・19周目） ──
    // 以前ここは **三項の定数だけ**で 4 要素を足していた:
    //   (hook_score || 0)*0.3 + (候補3件以上 ? 100 : 50)*0.3
    //   + (タグ15個以上 ? 100 : 60)*0.2 + (山場3件以上 ? 100 : 50)*0.2
    // どの項も「件数が閾値以上か」しか見ておらず、**その分析が走ったかを
    // 一度も見ていなかった。** サムネ生成が候補を返せなくても 50 点、
    // SEO メタデータが null でも 60 点が付き、フックは未分析でも `|| 0` で
    // 「0 点」という**測定結果の顔**になっていた。取得そのものに失敗して
    // optimizationData が null のときも `: 0` で「全体スコア 0」と出ていた。
    // 結果、**4 要素すべてが未計測でも「全体スコア: 52」**がパネルの
    // ヘッダーに出続け、YouTube 最適化パネルを開いた人はその数字で
    // 最適化の成否を判断していた。
    // 16周目 ProductionPipeline.jsx / 19周目 ProductionWizard.jsx で直したのと同型。
    // **走った要素だけで加重平均を取り、1 つも走っていなければ点を出さない**
    // （null にする。0 や 50 は実際に取りうる点なので印にならない）。
    const 採点要素 = [
        {
            id: 'hook',
            label: 'フック',
            weight: 0.3,
            // フック分析の結果そのものが無ければ分析は走っていない。
            // 点だけがあって分析が無い応答も未計測として扱う
            走った: !!optimizationData?.hook_analysis && typeof optimizationData?.hook_score === 'number',
            採点: () => Math.max(0, Math.min(100, optimizationData.hook_score)),
        },
        {
            id: 'thumbnail',
            label: 'サムネ',
            weight: 0.3,
            // 候補生成は走れば 3 案返る。空配列・非配列は
            // 「生成が走らなかった」であって「0 案という測定結果」ではない
            走った: Array.isArray(optimizationData?.thumbnail_candidates) && optimizationData.thumbnail_candidates.length > 0,
            採点: () => (optimizationData.thumbnail_candidates.length >= 3 ? 100 : 50),
        },
        {
            id: 'seo',
            label: 'SEO',
            weight: 0.2,
            // タグ配列が無ければ「15 個以上か」を判定する材料が無い
            走った: !!optimizationData?.seo_metadata && Array.isArray(optimizationData.seo_metadata.tags),
            採点: () => (optimizationData.seo_metadata.tags.length >= 15 ? 100 : 60),
        },
        {
            id: 'highlight',
            label: '山場',
            weight: 0.2,
            // 山場だけは 0 件が実際の測定結果になりうる（該当キーワード無し）。
            // だから配列が届いていること自体を「走った」の証拠にする
            走った: Array.isArray(optimizationData?.highlights),
            採点: () => (optimizationData.highlights.length >= 3 ? 100 : 50),
        },
    ];

    const 採点できた要素 = 採点要素.filter(e => e.走った);
    const 重みの合計 = 採点できた要素.reduce((acc, e) => acc + e.weight, 0);
    // 1 つも走っていなければ **点を出さない**。ここに 0 を置くと
    // 「採点した結果が 0 点」に見える
    const overallScore = 重みの合計 > 0
        ? 採点できた要素.reduce((acc, e) => acc + e.採点() * e.weight, 0) / 重みの合計
        : null;
    const 全体スコアを採点した = typeof overallScore === 'number';
    const 未計測の要素 = 採点要素.filter(e => !e.走った).map(e => e.label);

    return (
        <div className="youtube-optimizer-overlay">
            <div className="youtube-optimizer-panel">
                <div className="panel-header">
                    <h2>🚀 YouTube Optimizer</h2>
                    <div className="overall-score">
                        {/*
                          走った要素が 1 つも無いときに数字を出さない（R1.5-C4・19周目）。
                          「未計測」と書く。0 を出すと「採点して 0 点だった」に見える
                        */}
                        {全体スコアを採点した ? (
                            <>
                                全体スコア: <span className="score-value" data-testid="youtube-overall-score">{Math.round(overallScore)}</span>
                                {未計測の要素.length > 0 && (
                                    <span
                                        className="score-partial-note"
                                        data-testid="youtube-overall-score-partial"
                                        title={`${未計測の要素.join('・')} は分析が走っていないため、点に含めていません`}
                                    >
                                        （{未計測の要素.join('・')}は未計測）
                                    </span>
                                )}
                            </>
                        ) : (
                            <span
                                className="score-value"
                                data-testid="youtube-overall-score"
                                title="どの要素も分析が走っていないため、点はありません"
                            >
                                全体スコア: 未計測
                            </span>
                        )}
                    </div>
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>

                <div className="tab-bar">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
                            onClick={() => setActiveTab(tab.id)}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>

                <div className="panel-content">
                    {loading ? (
                        <div className="loading-state">
                            <div className="spinner"></div>
                            <p>YouTube最適化を実行中...</p>
                        </div>
                    ) : (
                        <>
                            {activeTab === 'hook' && (
                                <HookAnalysisDashboard
                                    hookData={optimizationData?.hook_analysis}
                                    onReanalyze={handleReanalyze}
                                    onAIImprove={handleAIImprove}
                                />
                            )}
                            {activeTab === 'thumbnail' && (
                                <ThumbnailABPanel
                                    thumbnails={optimizationData?.thumbnail_candidates}
                                    selectedId={selectedThumbnailId}
                                    onSelect={handleThumbnailSelect}
                                    onRegenerate={runOptimization}
                                    onCustomEdit={handleCustomEdit}
                                    onUpload={handleUpload}
                                />
                            )}
                            {activeTab === 'seo' && (
                                <SEOMetadataEditor seoData={optimizationData?.seo_metadata} />
                            )}
                            {activeTab === 'highlight' && (
                                <HighlightTimeline highlights={optimizationData?.highlights} />
                            )}
                        </>
                    )}
                </div>

                <div className="panel-footer">
                    <div className="growth-predictions">
                        <span data-testid="youtube-ctr-prediction">CTR予測: {optimizationData?.thumbnail_candidates?.[0]?.predicted_ctr || '-'}%</span>
                        <span>視聴維持: {optimizationData?.hook_analysis?.predicted_retention_impact?.split(':')[0] || '-'}</span>
                        <span data-testid="youtube-seo-score">SEOスコア: {optimizationData?.seo_metadata?.tags?.length >= 15 ? '良好' : '改善余地あり'}</span>
                    </div>

                    <div className="footer-actions">
                        <button className="btn-secondary" onClick={handleSaveSettings}>💾 設定を保存</button>
                        <button className="btn-primary" onClick={handleUpload}>📤 YouTubeに公開</button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default YouTubeOptimizerPanel;
