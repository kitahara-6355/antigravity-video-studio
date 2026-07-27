import React, { useEffect, useState } from 'react';
import { Target, Trophy, Flame } from 'lucide-react';

const RivalRadar = ({ rivals, quests, currentSubs }) => {
    if (!rivals || !quests) return null;

    return (
        <div className="rival-radar-container" style={{ marginTop: '20px', padding: '15px', background: 'rgba(0,0,0,0.3)', borderRadius: '12px' }}>
            <h3 style={{ borderBottom: '1px solid #333', paddingBottom: '10px', display: 'flex', alignItems: 'center' }}>
                <Target size={18} style={{ marginRight: '8px', color: '#ff4444' }} />
                ライバル出現 (RIVAL DETECTED)
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', marginTop: '15px' }}>
                {/* Tier 1: Nemesis */}
                {rivals.nemesis && (
                    <div className="rival-card nemesis" style={{ border: '1px solid #ff4444', padding: '10px', borderRadius: '8px', background: 'rgba(255, 68, 68, 0.1)' }}>
                        <div style={{ fontSize: '0.8em', color: '#ff8888', textTransform: 'uppercase' }}>好敵手 (NEMESIS)</div>
                        <div style={{ fontSize: '1.2em', fontWeight: 'bold' }}>{rivals.nemesis.name}</div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '10px' }}>
                            <span>You: {currentSubs}</span>
                            <span style={{ color: '#ff4444' }}>Target: {rivals.nemesis.subs}</span>
                        </div>
                        {quests.find(q => q.type === 'NEMESIS_BATTLE') && (
                            <div style={{ marginTop: '8px', fontSize: '0.9em', color: '#ffd700' }}>
                                <Flame size={14} style={{ display: 'inline' }} /> 差分: {quests.find(q => q.type === 'NEMESIS_BATTLE').gap} 人
                            </div>
                        )}
                        <div className="progress-bar-bg" style={{ height: '6px', background: '#333', borderRadius: '3px', marginTop: '8px' }}>
                            <div
                                className="progress-bar-fill"
                                style={{
                                    height: '100%',
                                    width: `${(currentSubs / rivals.nemesis.subs) * 100}%`,
                                    background: '#ff4444',
                                    borderRadius: '3px'
                                }}
                            />
                        </div>
                    </div>
                )}

                {/* Tier 2: Benchmark */}
                {rivals.benchmark && (
                    <div className="rival-card benchmark" style={{ border: '1px solid #00d4ff', padding: '10px', borderRadius: '8px', background: 'rgba(0, 212, 255, 0.1)' }}>
                        <div style={{ fontSize: '0.8em', color: '#88e4ff', textTransform: 'uppercase' }}>師匠 (BENCHMARK)</div>
                        <div style={{ fontSize: '1.2em', fontWeight: 'bold' }}>{rivals.benchmark.name}</div>
                        <div style={{ marginTop: '5px', fontSize: '0.9em', color: '#aaa' }}>
                            <Trophy size={14} style={{ display: 'inline', marginRight: '4px' }} />
                            目標: {rivals.benchmark.subs.toLocaleString()} 人
                        </div>
                        <div style={{ fontSize: '0.8em', color: '#666', marginTop: '5px' }}>
                            スタイルモデル: {rivals.benchmark.genre}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default RivalRadar;
