import React, { useState, useEffect } from 'react';
import './CollaborativePanel.css';
import { apiFetch } from '../api/client.js';

const CollaborativePanel = ({ isOpen, onClose, currentRole, onRoleChange }) => {
    const [journal, setJournal] = useState("");
    const [newEntry, setNewEntry] = useState("");
    const [suggestions, setSuggestions] = useState([
        { id: "s1", type: "字幕", text: "「皆さんこんにちは！」を「お世話になっております！」に変更しませんか？", status: "pending" },
        { id: "s2", type: "演出", text: "冒頭にキラキラしたエフェクトを追加することを提案します。", status: "pending" }
    ]);
    const [isSubmitting, setIsSubmitting] = useState(false);

    useEffect(() => {
        if (isOpen) {
            fetchJournal();
        }
    }, [isOpen]);

    const fetchJournal = async () => {
        try {
            const res = await apiFetch('getCollaborationJournal');
            const data = await res.json();
            setJournal(data.notes || "履歴はありません。");
        } catch (err) {
            console.error("Journal fetch error:", err);
        }
    };

    const handleAddJournal = async () => {
        if (!newEntry.trim()) return;
        setIsSubmitting(true);
        try {
            const res = await apiFetch('postCollaborationJournal', {
                body: { author: currentRole, content: newEntry }
            });
            if (res.ok) {
                setNewEntry("");
                fetchJournal();
            }
        } catch (err) {
            console.error("Journal save error:", err);
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleFeedback = async (id, action) => {
        try {
            const res = await apiFetch('postCollaborationFeedback', {
                body: {
                    suggestion_id: id,
                    action: action,
                    role: currentRole,
                    comment: ""
                }
            });
            if (res.ok) {
                setSuggestions(prev => prev.filter(s => s.id !== id));
            }
        } catch (err) {
            console.error("Feedback error:", err);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="collab-overlay">
            <div className="collab-modal">
                <header className="collab-header">
                    <h2>🤝 Collaborative Studio</h2>
                    <div className="role-switcher">
                        <button
                            className={currentRole === 'admin' ? 'active' : ''}
                            onClick={() => onRoleChange('admin')}
                        >管理者 (Admin)</button>
                        <button
                            className={currentRole === 'owner' ? 'active' : ''}
                            onClick={() => onRoleChange('owner')}
                        >チャンネル主 (Owner)</button>
                    </div>
                    <button className="close-btn" onClick={onClose}>×</button>
                </header>

                <div className="collab-content">
                    {currentRole === 'owner' ? (
                        <div className="owner-view">
                            <h3>🎬 レビューをお願いします</h3>
                            <p className="owner-intro">AIと管理者が作成した案です。直感で選んでください！</p>
                            <div className="suggestion-list">
                                {suggestions.map(s => (
                                    <div key={s.id} className="suggestion-item">
                                        <span className="badge">{s.type}</span>
                                        <p className="suggestion-text">{s.text}</p>
                                        <div className="feedback-actions">
                                            <button className="action-ok" onClick={() => handleFeedback(s.id, 'approve')}>👍 いいね！</button>
                                            <button className="action-tweak" onClick={() => handleFeedback(s.id, 'tweak')}>🤔 もう一声</button>
                                            <button className="action-no" onClick={() => handleFeedback(s.id, 'reject')}>❌ 却下</button>
                                        </div>
                                    </div>
                                ))}
                                {suggestions.length === 0 && <p className="empty-msg">現在、確認が必要な項目はありません。順調です！</p>}
                            </div>
                        </div>
                    ) : (
                        <div className="admin-view">
                            <h3>📝 プロジェクト・ジャーナル</h3>
                            <div className="journal-history">
                                <pre>{journal}</pre>
                            </div>
                            <div className="journal-input">
                                <textarea
                                    placeholder="二人の合意事項やメモを記録..."
                                    value={newEntry}
                                    onChange={(e) => setNewEntry(e.target.value)}
                                />
                                <button
                                    onClick={handleAddJournal}
                                    disabled={isSubmitting}
                                >
                                    {isSubmitting ? '記録中...' : '決定を記録する'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CollaborativePanel;
