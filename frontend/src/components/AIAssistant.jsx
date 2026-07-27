import React, { useState, useEffect } from 'react';

// AI Assistant Component
// Provides a persistent "Partner" UI that offers suggestions based on context.
// Props:
// - suggestions: Array of { id, message, type, actionLabel, onAction }
// - onAction: Callback(suggestion) when user accepts
// - onDismiss: Callback(id) when user ignores a suggestion
function AIAssistant({ suggestions, onAction, onDismiss }) {
    // Persistent View: Always open
    return (
        <div className="ai-assistant-container">
            <div className="ai-header">
                <span className="ai-icon">🤖</span>
                <span className="ai-title">AIパートナー</span>
                {suggestions.length > 0 && <span className="ai-badge">{suggestions.length}</span>}
            </div>

            <div className="ai-body">
                {suggestions.length === 0 ? (
                    <div className="ai-empty-state" style={{
                        display: 'flex', flexDirection: 'column', alignItems: 'center',
                        justifyContent: 'center', height: '300px', color: '#718096', textAlign: 'center'
                    }}>
                        <div style={{ fontSize: '3rem', marginBottom: '1rem' }}>✅</div>
                        <h3 style={{ margin: '0 0 10px 0', color: '#2d3748' }}>すべて完了しました！</h3>
                        <p style={{ fontSize: '0.9rem' }}>
                            AIによる品質チェックは<br />
                            クリアされています。<br />
                            素晴らしい動画になりそうです！
                        </p>
                    </div>
                ) : (
                    suggestions.map((suggestion) => (
                        <div key={suggestion.id} className={`suggestion-card ${suggestion.type || 'info'}`}>
                            <div className="suggestion-message">{suggestion.message}</div>
                            {suggestion.context && (
                                <div className="suggestion-context" style={{
                                    fontSize: '0.8rem', color: '#888', background: '#f0f0f0',
                                    padding: '5px', borderRadius: '4px', margin: '5px 0'
                                }}>
                                    "{suggestion.context}"
                                </div>
                            )}
                            <div className="suggestion-actions">
                                {onAction && (
                                    <button
                                        className="btn-primary-small"
                                        onClick={() => onAction(suggestion)}
                                    >
                                        {suggestion.actionLabel || "実行する"}
                                    </button>
                                )}
                                {suggestion.segmentIndex !== undefined && onDismiss && (
                                    <button
                                        className="btn-info-small"
                                        onClick={() => onDismiss('jump', suggestion)}
                                        style={{ background: '#3182ce', color: 'white', marginRight: '5px' }}
                                    >
                                        🔍 確認
                                    </button>
                                )}
                                <button
                                    className="btn-secondary-small"
                                    onClick={() => onDismiss(suggestion.id)}
                                >
                                    無視
                                </button>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}

export default AIAssistant;
