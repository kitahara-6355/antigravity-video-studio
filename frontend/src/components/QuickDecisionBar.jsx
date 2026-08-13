/**
 * QuickDecisionBar.jsx — ワンクリック判断UI（U-06）
 *
 * Owner が直感で決定を下す最速UI。
 * 👍 承認 / 🤔 保留 / 👎 却下 をワンタップで完了。
 * レビュー待ちアイテムをキュー表示し、
 * swipe-like なアニメーションで次へ進む。
 */
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { ThumbsUp, ThumbsDown, Pause, ChevronRight, Undo2, Sparkles } from 'lucide-react';
import './QuickDecision.css';
import { apiFetch } from '../api/client.js';


const QuickDecisionBar = ({ items = [], onDecisionComplete, onClose }) => {
    const [queue, setQueue] = useState(items);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [decisions, setDecisions] = useState([]);
    const [animating, setAnimating] = useState(false);
    const [animDirection, setAnimDirection] = useState(null);
    const [undoStack, setUndoStack] = useState([]);
    const cardRef = useRef(null);

    useEffect(() => {
        setQueue(items);
        setCurrentIndex(0);
        setDecisions([]);
        setUndoStack([]);
    }, [items]);

    const currentItem = queue[currentIndex] || null;
    const remaining = queue.length - currentIndex;
    const progress = queue.length > 0
        ? Math.round((currentIndex / queue.length) * 100)
        : 0;

    const handleDecision = useCallback(async (action) => {
        if (animating || !currentItem) return;

        setAnimDirection(action === 'approve' ? 'right' : action === 'reject' ? 'left' : 'up');
        setAnimating(true);

        const decision = {
            item_id: currentItem.id,
            action,
            timestamp: new Date().toISOString(),
        };

        // undo用にスタックに積む
        setUndoStack(prev => [...prev, { index: currentIndex, item: currentItem, decision }]);

        try {
            await apiFetch('postQualityDecisionQuick', { body: decision });
        } catch (err) {
            console.warn('Decision sync failed (offline ok):', err);
        }

        setDecisions(prev => [...prev, decision]);

        // アニメーション後に次へ
        setTimeout(() => {
            setAnimating(false);
            setAnimDirection(null);

            if (currentIndex + 1 >= queue.length) {
                onDecisionComplete?.([...decisions, decision]);
            } else {
                setCurrentIndex(prev => prev + 1);
            }
        }, 300);
    }, [animating, currentItem, currentIndex, queue.length, decisions, onDecisionComplete]);

    const handleUndo = useCallback(() => {
        if (undoStack.length === 0) return;
        const last = undoStack[undoStack.length - 1];
        setUndoStack(prev => prev.slice(0, -1));
        setDecisions(prev => prev.slice(0, -1));
        setCurrentIndex(last.index);
    }, [undoStack]);

    // キーボードショートカット
    useEffect(() => {
        const handler = (e) => {
            // 入力フィールド内では無効化
            const tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

            if (e.key === 'ArrowRight' || e.key === 'j') handleDecision('approve');
            if (e.key === 'ArrowLeft' || e.key === 'k') handleDecision('reject');
            if (e.key === 'ArrowDown' || e.key === ' ') {
                e.preventDefault(); // Space によるページスクロールを防止
                handleDecision('skip');
            }
            if (e.key === 'z' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                handleUndo();
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [handleDecision, handleUndo]);

    if (queue.length === 0) {
        return (
            <div className="quick-decision-bar empty-state">
                <Sparkles size={24} />
                <span>レビュー待ちの項目はありません</span>
            </div>
        );
    }

    if (currentIndex >= queue.length) {
        return (
            <div className="quick-decision-bar completed-state">
                <div className="completed-icon">🎉</div>
                <h3>全{queue.length}件のレビュー完了！</h3>
                <div className="decision-summary">
                    <span className="stat approve">
                        👍 {decisions.filter(d => d.action === 'approve').length}
                    </span>
                    <span className="stat skip">
                        🤔 {decisions.filter(d => d.action === 'skip').length}
                    </span>
                    <span className="stat reject">
                        👎 {decisions.filter(d => d.action === 'reject').length}
                    </span>
                </div>
                <button className="btn-primary" onClick={onClose}>閉じる</button>
            </div>
        );
    }

    return (
        <div className="quick-decision-bar">
            {/* プログレスバー */}
            <div className="decision-progress">
                <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${progress}%` }} />
                </div>
                <span className="progress-text">{currentIndex + 1} / {queue.length}</span>
            </div>

            {/* カード */}
            <div
                ref={cardRef}
                className={`decision-card ${animDirection ? `slide-${animDirection}` : ''}`}
            >
                <div className="card-badge">{currentItem?.type || 'レビュー'}</div>
                <p className="card-content">{currentItem?.text || currentItem?.description}</p>
                {currentItem?.context && (
                    <p className="card-context">{currentItem.context}</p>
                )}
                {currentItem?.preview && (
                    <div className="card-preview">
                        <img src={currentItem.preview} alt="preview" />
                    </div>
                )}
            </div>

            {/* アクションボタン */}
            <div className="decision-actions">
                <button
                    className="action-btn reject"
                    onClick={() => handleDecision('reject')}
                    disabled={animating}
                    title="却下 (←/K)"
                >
                    <ThumbsDown size={24} />
                    <span>却下</span>
                </button>

                <button
                    className="action-btn skip"
                    onClick={() => handleDecision('skip')}
                    disabled={animating}
                    title="保留 (↓/Space)"
                >
                    <Pause size={20} />
                    <span>保留</span>
                </button>

                <button
                    className="action-btn approve"
                    onClick={() => handleDecision('approve')}
                    disabled={animating}
                    title="承認 (→/J)"
                >
                    <ThumbsUp size={24} />
                    <span>承認</span>
                </button>
            </div>

            {/* ツールバー */}
            <div className="decision-toolbar">
                <button
                    className="toolbar-btn"
                    onClick={handleUndo}
                    disabled={undoStack.length === 0}
                    title="元に戻す (Ctrl+Z)"
                >
                    <Undo2 size={16} />
                    <span>戻す</span>
                </button>
                <span className="remaining-badge">
                    残り {remaining} 件
                </span>
                <button className="toolbar-btn" onClick={onClose}>
                    <ChevronRight size={16} />
                    <span>後で</span>
                </button>
            </div>
        </div>
    );
};

export default QuickDecisionBar;
