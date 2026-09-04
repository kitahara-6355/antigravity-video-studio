import React from 'react';
import './QualityGate.css';
import { Shield, AlertTriangle, X } from 'lucide-react';
import AISuggestionCard from './AISuggestionCard';

const QualityGate = ({ isOpen, onClose, onConfirm, data }) => {
    if (!isOpen) return null;

    const { is_ready, score, scored, is_real, critical_issues, suggestions, final_verdict } = data || {};

    // **未計測を「不合格」とも「0点」とも描かない**（R1.5-C4・面(b)の掃引）。
    // 供給元は3つあり、いずれも「測ったか」を渡している:
    //   - ProductionPipeline / ProductionWizard … `scored`
    //   - EditorPage（`POST /api/director/verify-quality`）… 失敗時 `score: null` + `is_real: false`
    // **どれも受け取っていなかった**ので、採点が落ちた回まで
    // 「⚠️ 修正を推奨」という**判定**が出ていた（測っていないので判定できない）。
    // `score || '--'` も、実測 0 点を '--' に潰していた。
    const 採点した = scored === undefined
        ? (typeof score === 'number' && is_real !== false)
        : scored === true;

    return (
        <div className="quality-gate-overlay">
            <div className="quality-gate-modal">
                <div className="gate-header">
                    <div className="header-icon">
                        <Shield size={24} color={(採点した && score > 80) ? "#10b981" : "#f59e0b"} />
                    </div>
                    <h3>最終品質検査 (Quality Gate)</h3>
                    <button className="close-btn" onClick={onClose}><X size={20} /></button>
                </div>

                <div className="gate-content">
                    <div className="score-section">
                        <div className="score-circle" style={{ borderColor: (採点した && score > 80) ? '#10b981' : '#f59e0b' }}>
                            <span className="score-value">{採点した ? score : '--'}</span>
                            <span className="score-label">QUALITY SCORE</span>
                        </div>
                        <div className={`verdict-badge ${(採点した && is_ready) ? 'ready' : 'not-ready'}`}>
                            {!採点した
                                ? '⚠️ 未計測'
                                : is_ready ? '✅ 出力準備完了' : '⚠️ 修正を推奨'}
                        </div>
                    </div>

                    <div className="details-section">
                        <div className="verdict-text">
                            <p>{final_verdict || 'AIが構成をスキャンしています...'}</p>
                        </div>

                        {critical_issues && critical_issues.length > 0 && (
                            <div className="issue-box critical">
                                <div className="box-title"><AlertTriangle size={16} /> 修正が必要な項目</div>
                                <ul>
                                    {critical_issues.map((issue, i) => <li key={i}>{issue}</li>)}
                                </ul>
                            </div>
                        )}

                        {suggestions && suggestions.length > 0 && (
                            <AISuggestionCard
                                suggestions={suggestions}
                                onApply={(s) => console.log('Applied:', s)}
                                onUndo={(s) => console.log('Undone:', s)}
                            />
                        )}
                    </div>
                </div>

                <div className="gate-footer">
                    <button className="btn-secondary" onClick={onClose}>
                        戻って修正する
                    </button>
                    <button
                        className={`btn-primary ${!is_ready ? 'warning' : ''}`}
                        onClick={onConfirm}
                    >
                        {is_ready ? '🎬 レンダリング開始' : '⚠️ 強制的に書き出す'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default QualityGate;
