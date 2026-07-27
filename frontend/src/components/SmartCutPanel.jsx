/**
 * SmartCutPanel.jsx - スマートカットUI
 * 
 * 機能:
 * - 動的尺調整（15/30/45/60分）
 * - 固定シーン管理
 * - AI推奨構成表示
 * - 全候補ビューア
 */
import React, { useState, useEffect, useCallback } from 'react';
import './SmartCut.css';

const API_BASE = "http://localhost:8000";

const SmartCutPanel = ({ isOpen, onClose, segments, onFinalize }) => {
    const [targetDuration, setTargetDuration] = useState(15);
    const [recommendation, setRecommendation] = useState(null);
    const [lockedSegments, setLockedSegments] = useState([]);
    const [allCandidates, setAllCandidates] = useState({ highlights: [], chapters: [] });
    const [loading, setLoading] = useState(false);
    const [showAllCandidates, setShowAllCandidates] = useState(false);
    const [candidateType, setCandidateType] = useState('highlights');

    // 初期化
    useEffect(() => {
        if (isOpen && segments?.length > 0) {
            initSmartCut();
        }
    }, [isOpen, segments]);

    const initSmartCut = async () => {
        setLoading(true);
        try {
            const response = await fetch(`${API_BASE}/api/smartcut/init`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    segments: segments || [],
                    opening_duration: 10,
                    ending_duration: 20
                })
            });

            if (response.ok) {
                const data = await response.json();
                setRecommendation(data.recommendation);
                setLockedSegments(data.recommendation.locked_segments || []);

                // 全候補を取得
                const candResponse = await fetch(`${API_BASE}/api/smartcut/all-candidates`);
                if (candResponse.ok) {
                    const candData = await candResponse.json();
                    setAllCandidates(candData.candidates);
                }
            }
        } catch (error) {
            console.error('SmartCut init failed:', error);
        } finally {
            setLoading(false);
        }
    };

    // 尺変更
    const handleDurationChange = async (minutes) => {
        setTargetDuration(minutes);
        setLoading(true);

        try {
            const response = await fetch(`${API_BASE}/api/smartcut/recommend`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_duration_minutes: minutes })
            });

            if (response.ok) {
                const data = await response.json();
                setRecommendation(data.recommendation);
            }
        } catch (error) {
            console.error('Recommendation failed:', error);
        } finally {
            setLoading(false);
        }
    };

    // シーン固定
    const handleLockSegment = async (highlight) => {
        try {
            const response = await fetch(`${API_BASE}/api/smartcut/lock`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    segment_id: `locked_${Date.now()}`,
                    title: highlight.text_snippet?.substring(0, 30) || 'シーン',
                    start_time: highlight.timestamp || 0,
                    end_time: (highlight.timestamp || 0) + 30,
                    reason: "ユーザーが固定"
                })
            });

            if (response.ok) {
                const data = await response.json();
                setLockedSegments(data.locked_segments);
                setRecommendation(data.recommendation);
            }
        } catch (error) {
            console.error('Lock failed:', error);
        }
    };

    // 固定解除
    const handleUnlockSegment = async (segmentId) => {
        try {
            const response = await fetch(`${API_BASE}/api/smartcut/unlock`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ segment_id: segmentId })
            });

            if (response.ok) {
                const data = await response.json();
                setLockedSegments(data.locked_segments);
                setRecommendation(data.recommendation);
            }
        } catch (error) {
            console.error('Unlock failed:', error);
        }
    };

    // 確定
    const handleFinalize = async () => {
        try {
            const response = await fetch(`${API_BASE}/api/smartcut/finalize`, {
                method: 'POST'
            });

            if (response.ok) {
                const data = await response.json();
                onFinalize?.(data.finalized);
                onClose();
            }
        } catch (error) {
            console.error('Finalize failed:', error);
        }
    };

    // 時間フォーマット
    const formatTime = (seconds) => {
        const mins = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${mins}:${secs.toString().padStart(2, '0')}`;
    };

    if (!isOpen) return null;

    const durations = [15, 30, 45, 60];
    const progressPercent = recommendation
        ? (recommendation.estimated_output_seconds / (targetDuration * 60)) * 100
        : 0;

    return (
        <div className="smartcut-overlay">
            <div className="smartcut-panel">
                <div className="smartcut-header">
                    <h2>🎬 スマートカット</h2>
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>

                <div className="smartcut-content">
                    {loading ? (
                        <div className="loading-state">
                            <div className="spinner"></div>
                            <p>構成を計算中...</p>
                        </div>
                    ) : (
                        <>
                            {/* U-07: 尺選択スライダー */}
                            <div className="duration-selector">
                                <label>目標尺: <strong>{targetDuration}分</strong></label>
                                <div className="duration-slider-container">
                                    <input
                                        type="range"
                                        className="duration-slider"
                                        min={5}
                                        max={90}
                                        step={1}
                                        value={targetDuration}
                                        onChange={(e) => {
                                            const v = parseInt(e.target.value);
                                            setTargetDuration(v);
                                        }}
                                        onMouseUp={() => handleDurationChange(targetDuration)}
                                        onTouchEnd={() => handleDurationChange(targetDuration)}
                                        style={{
                                            background: `linear-gradient(to right, #6366f1 0%, #8b5cf6 ${((targetDuration - 5) / 85) * 100}%, rgba(255,255,255,0.1) ${((targetDuration - 5) / 85) * 100}%)`
                                        }}
                                    />
                                    <div className="slider-labels">
                                        <span>5分</span>
                                        <span>30分</span>
                                        <span>60分</span>
                                        <span>90分</span>
                                    </div>
                                </div>
                                <div className="duration-presets">
                                    {durations.map(d => (
                                        <button
                                            key={d}
                                            className={`duration-btn ${targetDuration === d ? 'active' : ''}`}
                                            onClick={() => handleDurationChange(d)}
                                        >
                                            {d}分
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* 進捗バー */}
                            <div className="output-progress">
                                <div className="progress-label">
                                    <span>推定出力: {recommendation?.estimated_output_str || '--:--'}</span>
                                    <span>{targetDuration}分目標</span>
                                </div>
                                <div className="progress-bar">
                                    <div
                                        className="progress-fill"
                                        style={{ width: `${Math.min(progressPercent, 100)}%` }}
                                    />
                                </div>
                            </div>

                            {/* AI推奨構成 */}
                            <div className="recommendation-section">
                                <h3>📊 AI推奨構成</h3>
                                <div className="segment-list">
                                    {recommendation?.recommended_segments?.map((seg, i) => (
                                        <div key={seg.id} className="segment-item">
                                            <span className="segment-time">
                                                {formatTime(seg.start_time)}
                                            </span>
                                            <span className="segment-title">{seg.title}</span>
                                            <span className="segment-duration">
                                                ({formatTime(seg.duration)})
                                            </span>
                                            <span className="segment-score">
                                                スコア: {seg.score}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            </div>

                            {/* 固定シーン */}
                            <div className="locked-section">
                                <h3>🔒 固定シーン ({lockedSegments.length}件)</h3>
                                <div className="locked-list">
                                    {lockedSegments.map((seg) => (
                                        <div key={seg.id} className="locked-item">
                                            <span className="locked-icon">🔒</span>
                                            <span className="locked-title">{seg.title}</span>
                                            <span className="locked-time">
                                                ({formatTime(seg.start_time)} - {formatTime(seg.end_time)})
                                            </span>
                                            <button
                                                className="unlock-btn"
                                                onClick={() => handleUnlockSegment(seg.id)}
                                            >
                                                解除
                                            </button>
                                        </div>
                                    ))}
                                    {lockedSegments.length === 0 && (
                                        <p className="empty-message">
                                            固定シーンはありません。下の候補から追加できます。
                                        </p>
                                    )}
                                </div>
                            </div>

                            {/* 全候補ビューア */}
                            <div className="candidates-section">
                                <div className="candidates-header">
                                    <h3>📋 全候補</h3>
                                    <div className="candidate-tabs">
                                        <button
                                            className={candidateType === 'highlights' ? 'active' : ''}
                                            onClick={() => { setCandidateType('highlights'); setShowAllCandidates(true); }}
                                        >
                                            ハイライト ({allCandidates.highlights?.length || 0})
                                        </button>
                                        <button
                                            className={candidateType === 'chapters' ? 'active' : ''}
                                            onClick={() => { setCandidateType('chapters'); setShowAllCandidates(true); }}
                                        >
                                            チャプター ({allCandidates.chapters?.length || 0})
                                        </button>
                                    </div>
                                </div>

                                {showAllCandidates && (
                                    <div className="candidates-list">
                                        {(candidateType === 'highlights' ? allCandidates.highlights : allCandidates.chapters)
                                            ?.slice(0, 20)
                                            .map((item, i) => (
                                                <div key={i} className="candidate-item">
                                                    <span className="candidate-time">
                                                        {formatTime(item.timestamp || 0)}
                                                    </span>
                                                    <span className="candidate-type">
                                                        [{item.type || 'other'}]
                                                    </span>
                                                    <span className="candidate-text">
                                                        {item.text_snippet || item.title || '-'}
                                                    </span>
                                                    <button
                                                        className="lock-btn"
                                                        onClick={() => handleLockSegment(item)}
                                                    >
                                                        🔒 固定
                                                    </button>
                                                </div>
                                            ))}
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </div>

                <div className="smartcut-footer">
                    <div className="footer-info">
                        <span>OP: {recommendation?.opening_duration || 10}秒</span>
                        <span>ED: {recommendation?.ending_duration || 20}秒</span>
                        <span>フェード: {recommendation?.fade_count || 0}回</span>
                    </div>
                    <div className="footer-actions">
                        <button className="btn-secondary" onClick={onClose}>
                            キャンセル
                        </button>
                        <button className="btn-primary" onClick={handleFinalize}>
                            ✅ 最終確定
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SmartCutPanel;
