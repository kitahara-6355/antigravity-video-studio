import React, { useState, useEffect } from 'react';
import { BookOpen, Award, Zap, History, Sparkles, X, ChevronRight } from 'lucide-react';

export default function SoulPassport({ onClose }) {
    const [evolutionData, setEvolutionData] = useState(null);
    const [statusData, setStatusData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchData = async () => {
            try {
                // Fetch Evolution Log
                const evoRes = await fetch('http://localhost:8000/api/director/evolution');
                const evoData = await evoRes.json();
                setEvolutionData(evoData);

                // Fetch Trinity Status
                const statusRes = await fetch('http://localhost:8000/api/status');
                const sData = await statusRes.json();
                setStatusData(sData);

                setLoading(false);
            } catch (err) {
                console.error("SoulPassport Load Error:", err);
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) return (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', background: 'var(--color-bg-hover)' }}>
            <div className="spinner"></div>
        </div>
    );

    const entries = evolutionData?.entries || [];
    const philosophy = evolutionData?.philosophy || "哲学を編集中...";
    const profiles = statusData?.profiles || {};
    const admin = profiles.admin || {};
    const owner = profiles.owner || {};
    const collabNotes = statusData?.interaction_history?.collaborative_notes || "共同制作の記録はまだありません。";

    return (
        <div className="soul-passport fade-in" style={{
            background: 'var(--color-bg-panel)',
            height: '100%',
            overflowY: 'auto',
            padding: '2.5rem',
            fontFamily: "'Noto Sans JP', sans-serif",
            color: 'var(--color-text-primary)'
        }}>
            {/* Header */}
            <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '3rem' }}>
                <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-semantic-theme-indigo)', marginBottom: '8px' }}>
                        <Sparkles size={20} />
                        <span style={{ fontSize: '0.9rem', fontWeight: 'bold', letterSpacing: '0.1em' }}>TRINITY SYSTEM 2.0</span>
                    </div>
                    <h1 style={{ margin: 0, fontSize: '2.4rem', fontWeight: 900, letterSpacing: '-0.02em' }}>SOUL PASSPORT</h1>
                    <p style={{ margin: 0, color: 'var(--color-text-secondary)', fontSize: '1.1rem' }}>監督としての歩みと、AIとの共進化の記録</p>
                </div>
                <button onClick={onClose} style={{
                    background: 'var(--color-bg-hover)', border: 'none', padding: '10px', borderRadius: '50%', cursor: 'pointer', color: 'var(--color-text-secondary)'
                }}>
                    <X size={24} />
                </button>
            </header>

            {/* Top Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '2rem', marginBottom: '3rem' }}>

                {/* Philosophy Card */}
                <div style={{
                    background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
                    borderRadius: '24px',
                    padding: '2rem',
                    color: 'white',
                    boxShadow: '0 20px 25px -5px rgba(99, 102, 241, 0.2)'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '1rem', opacity: 0.9 }}>
                        <BookOpen size={20} />
                        <span style={{ fontSize: '0.8rem', fontWeight: 'bold', textTransform: 'uppercase' }}>Director's Philosophy</span>
                    </div>
                    <h2 style={{ margin: 0, fontSize: '1.5rem', lineHeight: '1.4', fontWeight: 700 }}>
                        「{philosophy}」
                    </h2>
                </div>

                {/* Status Card */}
                <div style={{
                    background: 'var(--color-bg-panel)',
                    borderRadius: '24px',
                    padding: '2rem',
                    border: '1px solid #e2e8f0',
                    display: 'flex',
                    flexDirection: 'column',
                    justifyContent: 'center'
                }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                        <div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', fontWeight: 'bold', marginBottom: '4px' }}>ADMIN (TECH)</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div style={{ background: 'var(--color-semantic-theme-indigo-bg)', color: 'var(--color-semantic-theme-indigo-dark)', padding: '4px 12px', borderRadius: '20px', fontSize: '0.9rem', fontWeight: 'bold' }}>
                                    {admin.ranks?.tech_rank?.level || "Apprentice"}
                                </div>
                                <span style={{ fontSize: '0.8rem', color: 'var(--color-text-light)' }}>XP {admin.ranks?.tech_rank?.xp || 0}</span>
                            </div>
                        </div>
                        <div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', fontWeight: 'bold', marginBottom: '4px' }}>OWNER (BIZ)</div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div style={{ background: '#fef3c7', color: '#92400e', padding: '4px 12px', borderRadius: '20px', fontSize: '0.9rem', fontWeight: 'bold' }}>
                                    {owner.ranks?.biz_rank?.level || "Dreamer"}
                                </div>
                                <span style={{ fontSize: '0.8rem', color: 'var(--color-text-light)' }}>XP {owner.ranks?.biz_rank?.xp || 0}</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {/* Narrative Timeline & Journal Side by Side */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '3rem' }}>
                <section>
                    <h3 style={{ fontSize: '1.4rem', marginBottom: '2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <History size={24} color="var(--color-semantic-theme-indigo)" />
                        成長のクロニクル (Evolution Log)
                    </h3>

                    {entries.length === 0 ? (
                        <div style={{ padding: '3rem', textAlign: 'center', background: 'var(--color-bg-hover)', borderRadius: '24px', color: 'var(--color-text-light)' }}>
                            最初の制作記を書き出し中...
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem', borderLeft: '2px solid #e2e8f0', paddingLeft: '2rem', marginLeft: '1rem' }}>
                            {entries.slice().reverse().map((entry, idx) => (
                                <div key={idx} className="evolution-entry" style={{ position: 'relative' }}>
                                    {/* Timeline Dot */}
                                    <div style={{
                                        position: 'absolute',
                                        left: '-2.7rem',
                                        top: '0.5rem',
                                        width: '12px',
                                        height: '12px',
                                        borderRadius: '50%',
                                        background: idx === 0 ? 'var(--color-semantic-theme-indigo)' : 'var(--color-semantic-slider-track)',
                                        border: '4px solid white',
                                        boxShadow: '0 0 0 4px #f1f5f9'
                                    }}></div>

                                    <div style={{ background: '#f8fafc', padding: '1.5rem', borderRadius: '20px', border: '1px solid #f1f5f9' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                            <h4 style={{ margin: 0, fontSize: '1.1rem', color: 'var(--color-text-primary)', fontWeight: 700 }}>{entry.summary}</h4>
                                            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-light)' }}>{new Date(entry.timestamp * 1000).toLocaleDateString()}</span>
                                        </div>
                                        <p style={{ margin: '0 0 1rem', fontSize: '0.95rem', color: 'var(--color-text-secondary)', lineHeight: '1.8' }}>{entry.insight}</p>

                                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                                            {entry.stat_changes?.map((stat, i) => (
                                                <span key={i} style={{ background: 'var(--color-bg-panel)', color: 'var(--color-semantic-theme-indigo)', fontSize: '0.75rem', padding: '2px 10px', borderRadius: '12px', border: '1px solid var(--color-semantic-theme-indigo-bg)' }}>
                                                    {stat}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </section>

                <section>
                    <h3 style={{ fontSize: '1.4rem', marginBottom: '2rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <BookOpen size={24} color="var(--color-semantic-theme-indigo)" />
                        共同制作ジャーナル
                    </h3>
                    <div style={{
                        background: '#f8fafc',
                        padding: '1.5rem',
                        borderRadius: '24px',
                        fontSize: '0.9rem',
                        lineHeight: '1.6',
                        color: 'var(--color-text-secondary)',
                        whiteSpace: 'pre-wrap',
                        maxHeight: '400px',
                        overflowY: 'auto',
                        border: '1px dashed #cbd5e1'
                    }}>
                        {collabNotes}
                    </div>
                </section>
            </div>

            {/* Advice Footer */}
            <div style={{
                marginTop: '4rem',
                padding: '2rem',
                background: '#f1f5f9',
                borderRadius: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
            }}>
                <div>
                    <h4 style={{ margin: '0 0 4px', fontSize: '1rem' }}>今のあなたに最適なトレーニング</h4>
                    <p style={{ margin: 0, color: 'var(--color-text-secondary)', fontSize: '0.9rem' }}>専門家AIたちが「次に目指すべきステップ」を準備しています。</p>
                </div>
                <button style={{
                    background: 'white',
                    border: 'none',
                    padding: '12px 24px',
                    borderRadius: '12px',
                    fontWeight: 'bold',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    cursor: 'pointer',
                    boxShadow: '0 4px 6px -1px rgba(0,0,0,0.05)'
                }}>
                    ボードルームへ <ChevronRight size={18} />
                </button>
            </div>
        </div>
    );
}
