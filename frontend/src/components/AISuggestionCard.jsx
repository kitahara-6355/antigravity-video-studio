/**
 * AISuggestionCard.jsx — AI改善案の適用・取消UI（U-08）
 *
 * QualityGate の suggestions を「ワンクリック適用」可能にし、
 * 適用済みアクションをUndoスタックで管理する。
 *
 * 使い方:
 *   <AISuggestionCard
 *     suggestions={['冒頭5秒にフックを追加', 'BGM音量を-3dB調整']}
 *     onApply={(suggestion) => applyToTimeline(suggestion)}
 *     onUndo={(suggestion) => revertFromTimeline(suggestion)}
 *   />
 */
import React, { useState, useCallback } from 'react';
import { Wand2, Undo2, Check, ChevronDown, ChevronUp, Sparkles } from 'lucide-react';

const API_BASE = "http://localhost:8000";

const AISuggestionCard = ({ suggestions = [], onApply, onUndo }) => {
    const [appliedItems, setAppliedItems] = useState(new Set());
    const [undoStack, setUndoStack] = useState([]);
    const [expanded, setExpanded] = useState(true);
    const [applying, setApplying] = useState(null);

    const handleApply = useCallback(async (suggestion, index) => {
        if (appliedItems.has(index) || applying !== null) return;

        setApplying(index);

        try {
            // バックエンドに適用通知
            await fetch(`${API_BASE}/api/quality/apply-suggestion`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ suggestion, index }),
            });

            setAppliedItems(prev => new Set([...prev, index]));
            setUndoStack(prev => [...prev, { suggestion, index }]);
            onApply?.(suggestion);
        } catch (err) {
            console.warn('Apply suggestion failed:', err);
            // オフラインでも適用マークする（楽観的更新）
            setAppliedItems(prev => new Set([...prev, index]));
            setUndoStack(prev => [...prev, { suggestion, index }]);
            onApply?.(suggestion);
        } finally {
            setApplying(null);
        }
    }, [appliedItems, applying, onApply]);

    const handleUndo = useCallback(async () => {
        if (undoStack.length === 0) return;

        const last = undoStack[undoStack.length - 1];

        try {
            await fetch(`${API_BASE}/api/quality/undo-suggestion`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ suggestion: last.suggestion, index: last.index }),
            });
        } catch (err) {
            console.warn('Undo sync failed:', err);
        }

        setAppliedItems(prev => {
            const next = new Set(prev);
            next.delete(last.index);
            return next;
        });
        setUndoStack(prev => prev.slice(0, -1));
        onUndo?.(last.suggestion);
    }, [undoStack, onUndo]);

    const handleApplyAll = useCallback(async () => {
        // ローカルで適用済みを追跡（クロージャのstale state回避）
        const alreadyApplied = new Set(appliedItems);
        for (let i = 0; i < suggestions.length; i++) {
            if (!alreadyApplied.has(i)) {
                await handleApply(suggestions[i], i);
                alreadyApplied.add(i);
            }
        }
    }, [suggestions, appliedItems, handleApply]);

    if (!suggestions || suggestions.length === 0) return null;

    const appliedCount = appliedItems.size;
    const totalCount = suggestions.length;

    return (
        <div style={styles.container}>
            {/* ヘッダー */}
            <div style={styles.header} onClick={() => setExpanded(v => !v)}>
                <div style={styles.headerLeft}>
                    <Sparkles size={18} color="#8b5cf6" />
                    <h4 style={styles.title}>AI 改善提案</h4>
                    <span style={styles.badge}>
                        {appliedCount}/{totalCount} 適用済み
                    </span>
                </div>
                <div style={styles.headerRight}>
                    {undoStack.length > 0 && (
                        <button
                            style={styles.undoBtn}
                            onClick={(e) => { e.stopPropagation(); handleUndo(); }}
                            title="元に戻す (Ctrl+Z)"
                        >
                            <Undo2 size={14} />
                            <span>Undo</span>
                        </button>
                    )}
                    {expanded ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                </div>
            </div>

            {/* 提案リスト */}
            {expanded && (
                <div style={styles.list}>
                    {suggestions.map((suggestion, i) => {
                        const isApplied = appliedItems.has(i);
                        const isApplying = applying === i;

                        return (
                            <div
                                key={i}
                                style={{
                                    ...styles.item,
                                    ...(isApplied ? styles.appliedItem : {}),
                                }}
                            >
                                <div style={styles.itemContent}>
                                    <span style={{
                                        ...styles.itemText,
                                        ...(isApplied ? styles.appliedText : {}),
                                    }}>
                                        {suggestion}
                                    </span>
                                </div>
                                <button
                                    style={{
                                        ...styles.applyBtn,
                                        ...(isApplied ? styles.appliedBtn : {}),
                                    }}
                                    onClick={() => handleApply(suggestion, i)}
                                    disabled={isApplied || isApplying}
                                >
                                    {isApplying ? (
                                        <span style={styles.spinner}>⏳</span>
                                    ) : isApplied ? (
                                        <>
                                            <Check size={14} />
                                            <span>適用済み</span>
                                        </>
                                    ) : (
                                        <>
                                            <Wand2 size={14} />
                                            <span>適用</span>
                                        </>
                                    )}
                                </button>
                            </div>
                        );
                    })}

                    {/* 全件適用ボタン */}
                    {appliedCount < totalCount && (
                        <button
                            style={styles.applyAllBtn}
                            onClick={handleApplyAll}
                        >
                            <Wand2 size={16} />
                            <span>全て適用 ({totalCount - appliedCount}件)</span>
                        </button>
                    )}
                </div>
            )}
        </div>
    );
};

// インラインスタイル（CSS-in-JS で他のコンポーネントと衝突を防ぐ）
const styles = {
    container: {
        background: 'rgba(139, 92, 246, 0.08)',
        border: '1px solid rgba(139, 92, 246, 0.2)',
        borderRadius: '12px',
        overflow: 'hidden',
        marginTop: '16px',
    },
    header: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '12px 16px',
        cursor: 'pointer',
        userSelect: 'none',
    },
    headerLeft: {
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
    },
    headerRight: {
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        color: 'rgba(255,255,255,0.5)',
    },
    title: {
        margin: 0,
        fontSize: '14px',
        fontWeight: 600,
        color: 'rgba(255,255,255,0.9)',
    },
    badge: {
        fontSize: '11px',
        background: 'rgba(139, 92, 246, 0.2)',
        color: '#a78bfa',
        padding: '2px 8px',
        borderRadius: '10px',
        fontWeight: 600,
    },
    undoBtn: {
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '4px 10px',
        background: 'rgba(255,255,255,0.08)',
        border: '1px solid rgba(255,255,255,0.15)',
        borderRadius: '6px',
        color: 'rgba(255,255,255,0.6)',
        fontSize: '12px',
        cursor: 'pointer',
    },
    list: {
        padding: '0 16px 16px',
    },
    item: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '10px 12px',
        background: 'rgba(255,255,255,0.03)',
        borderRadius: '8px',
        marginBottom: '8px',
        transition: 'all 0.2s ease',
    },
    appliedItem: {
        background: 'rgba(16, 185, 129, 0.08)',
        borderLeft: '3px solid #10b981',
    },
    itemContent: {
        flex: 1,
        marginRight: '12px',
    },
    itemText: {
        fontSize: '13px',
        color: 'rgba(255,255,255,0.8)',
        lineHeight: 1.5,
    },
    appliedText: {
        color: 'rgba(255,255,255,0.5)',
        textDecoration: 'line-through',
    },
    applyBtn: {
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '6px 14px',
        background: 'rgba(139, 92, 246, 0.2)',
        border: '1px solid rgba(139, 92, 246, 0.3)',
        borderRadius: '8px',
        color: '#a78bfa',
        fontSize: '12px',
        fontWeight: 600,
        cursor: 'pointer',
        transition: 'all 0.2s ease',
        whiteSpace: 'nowrap',
    },
    appliedBtn: {
        background: 'rgba(16, 185, 129, 0.15)',
        borderColor: 'rgba(16, 185, 129, 0.3)',
        color: '#10b981',
        cursor: 'default',
    },
    spinner: {
        animation: 'spin 1s linear infinite',
    },
    applyAllBtn: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '6px',
        width: '100%',
        padding: '10px',
        background: 'linear-gradient(90deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.2))',
        border: '1px solid rgba(139, 92, 246, 0.3)',
        borderRadius: '8px',
        color: '#a78bfa',
        fontSize: '13px',
        fontWeight: 600,
        cursor: 'pointer',
        marginTop: '4px',
        transition: 'all 0.2s ease',
    },
};

export default AISuggestionCard;
