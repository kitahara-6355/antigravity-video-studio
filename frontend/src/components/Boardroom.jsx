import React, { useState, useEffect } from 'react';
import { ResponsiveContainer, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from 'recharts';
import { Users, Target, Shield, Zap, RefreshCw, X, AlertCircle } from 'lucide-react';
import CouncilChamber from './CouncilChamber';

export default function Boardroom({ onClose, initialQuery }) {
    const [dashboardData, setDashboardData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Load Dashboard Data (User Model + Analytics)
    useEffect(() => {
        fetch('http://localhost:8000/api/settings')
            .then(res => {
                if (!res.ok) throw new Error("Server Response Error");
                return res.json();
            })
            .then(data => {
                if (data.user_model) {
                    setDashboardData(data.user_model);
                } else {
                    throw new Error("Invalid Data Format");
                }
                setLoading(false);
            })
            .catch(err => {
                console.error("Boardroom Load Error:", err);
                setError("戦略データの取得に失敗しました。バックエンドサーバーが起動しているか確認してください。");
                setLoading(false);
            });
    }, []);

    if (loading) return (
        <div className="loading-container fade-in" style={{ height: '100vh', background: '#f8fafc' }}>
            <div className="spinner"></div>
            <p style={{ fontWeight: 'bold' }}>戦略会議室に入室中...</p>
        </div>
    );

    if (error) return (
        <div className="loading-container fade-in" style={{ height: '100vh', background: 'var(--bg-primary)', color: '#ef4444' }}>
            <AlertCircle size={48} />
            <p style={{ fontWeight: 'bold', marginTop: '1rem' }}>{error}</p>
            <button
                onClick={onClose}
                style={{ padding: '8px 16px', background: '#cbd5e1', borderRadius: '8px', border: 'none', cursor: 'pointer', marginTop: '1rem', color: '#475569', fontWeight: 'bold' }}
            >
                戻る
            </button>
        </div>
    );

    if (!dashboardData) return null;

    const { ranks, external_status } = dashboardData;

    // Radar Data
    const radarData = [
        { subject: 'ビジネス力', A: ranks?.biz_rank?.xp || 10, fullMark: 100 },
        { subject: '技術力', A: ranks?.tech_rank?.xp || 20, fullMark: 100 },
        { subject: 'ブランド力', A: ranks?.brand_rank?.score || 50, fullMark: 100 },
    ];

    return (
        <div className="boardroom-page fade-in" style={{
            background: 'var(--bg-primary)', // みらい議会有りカラー（白基調）
            minHeight: '100vh',
            padding: '2rem',
            position: 'relative',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-body)'
        }}>
            {/* Header */}
            <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
                    <div style={{ background: 'linear-gradient(135deg, #8B5CF6, #EC4899)', padding: '10px', borderRadius: '12px', color: '#ffffff', boxShadow: '0 4px 12px rgba(236, 72, 153, 0.2)' }}>
                        <Shield size={32} />
                    </div>
                    <div>
                        <h1 style={{ margin: 0, fontSize: '1.8rem', color: 'var(--text-primary)', fontFamily: 'var(--font-heading)' }}>戦略会議室 (Strategy Room)</h1>
                        <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Project Antigravity Decision Center</p>
                    </div>
                </div>
                <button onClick={onClose} style={{
                    background: 'var(--bg-panel)', backdropFilter: 'blur(12px)', border: '1px solid var(--border-color)', borderRadius: '8px', padding: '8px 16px', cursor: 'pointer', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px', transition: 'all 0.2s', boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
                }} className="glass-btn hover-glow">
                    <X size={20} /> 閉じる
                </button>
            </header>

            {/* Main Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '2rem', marginBottom: '2rem' }}>

                {/* Left Col: Radar & Status */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                    {/* Radar Card */}
                    <div className="card glass-panel" style={{ background: 'rgba(255,255,255,0.6)', backdropFilter: 'blur(16px)', padding: '2rem', borderRadius: '16px', border: '1px solid var(--border-color)', boxShadow: '0 8px 32px rgba(139, 92, 246, 0.05)' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                            <h3 style={{ margin: 0, fontFamily: 'var(--font-heading)', color: 'var(--text-primary)' }}>クリエイター能力分布</h3>
                            <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                                <Zap size={12} color="#EC4899" /> AI信頼度
                            </span>
                        </div>

                        <div style={{ height: '300px', width: '100%' }}>
                            <ResponsiveContainer width="100%" height="100%">
                                <RadarChart cx="50%" cy="50%" outerRadius="80%" data={radarData}>
                                    <PolarGrid stroke="rgba(139, 92, 246, 0.2)" />
                                    <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--text-secondary)', fontSize: 12, fontWeight: 600 }} />
                                    <PolarRadiusAxis angle={30} domain={[0, 100]} tick={false} axisLine={false} />
                                    <Radar name="Status" dataKey="A" stroke="#8B5CF6" strokeWidth={3} fill="#EC4899" fillOpacity={0.15} />
                                </RadarChart>
                            </ResponsiveContainer>
                        </div>

                        <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid rgba(139, 92, 246, 0.1)' }}>
                            <div style={{ marginBottom: '10px' }}>
                                <strong style={{ fontSize: '1.2rem', color: '#8B5CF6' }}>Level {Math.floor((dashboardData.interaction_history?.total_sessions || 0) / 10) + 1}</strong>
                                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: '5px 0' }}>
                                    信頼度が上がると、より高度な「自動化機能」と「戦略的提案」が解放されます。
                                </p>
                            </div>
                        </div>
                    </div>

                    {/* Current Mission Card */}
                    <div className="card glass-panel" style={{ background: 'linear-gradient(135deg, rgba(139,92,246,0.1) 0%, rgba(236,72,153,0.1) 100%)', backdropFilter: 'blur(16px)', border: '1px solid rgba(236,72,153,0.3)', padding: '2rem', borderRadius: '16px', boxShadow: '0 8px 32px rgba(236, 72, 153, 0.1)' }}>
                        <h3 style={{ margin: '0 0 1rem', display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-heading)', color: '#EC4899' }}>
                            <Target size={20} color="#EC4899" /> 次のミッション
                        </h3>
                        <div style={{ marginBottom: '1rem' }}>
                            <div style={{ fontSize: '0.8rem', color: '#8B5CF6', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 600 }}>{ranks?.tech_rank?.title || "Identify"}</div>
                            <h2 style={{ fontSize: '1.5rem', margin: '5px 0', fontFamily: 'var(--font-heading)', color: 'var(--text-primary)' }}>
                                {ranks?.tech_rank?.next_milestone || "Create your first masterpiece"}
                            </h2>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: '1.6' }}>
                            {dashboardData.ai_notes || "ユーザーは高い志を持っています。効率を重視しつつ、深い論理の学習にも意欲的です。"}
                        </p>
                    </div>
                </div>

                {/* Right Col: Council & Analytics */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>

                    {/* Council Chamber */}
                    <div className="card glass-panel" style={{ background: 'rgba(255,255,255,0.6)', backdropFilter: 'blur(16px)', borderRadius: '16px', border: '1px solid var(--border-color)', boxShadow: '0 8px 32px rgba(139, 92, 246, 0.05)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                        <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border-color)', background: 'rgba(139,92,246,0.02)' }}>
                            <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '10px', fontFamily: 'var(--font-heading)', color: 'var(--text-primary)' }}>
                                <Users size={20} color="#8B5CF6" /> 未来評議会 (Future Council)
                            </h3>
                            <p style={{ margin: '5px 0 0', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                AIエージェントたちがあなたの直近の活動を分析し、方針を議論しています。
                            </p>
                        </div>

                        <div style={{ padding: '0' }}>
                            <CouncilChamber initialQuery={initialQuery} />
                        </div>
                    </div>

                    {/* Rival Radar */}
                    <div className="card glass-panel" style={{ background: 'rgba(255,255,255,0.6)', backdropFilter: 'blur(16px)', border: '1px solid var(--border-color)', padding: '2rem', borderRadius: '16px', color: 'var(--text-primary)', boxShadow: '0 8px 32px rgba(139, 92, 246, 0.05)' }}>
                        <h3 style={{ margin: '0 0 1rem', display: 'flex', alignItems: 'center', gap: '8px', fontFamily: 'var(--font-heading)', color: 'var(--text-primary)' }}>
                            <RefreshCw size={20} color="#EC4899" /> ライバル出現 (RIVAL DETECTED)
                        </h3>
                        <div style={{ display: 'flex', gap: '1rem' }}>
                            <div style={{ flex: 1, background: 'rgba(239, 68, 68, 0.05)', border: '1px solid rgba(239, 68, 68, 0.2)', padding: '1rem', borderRadius: '12px', color: 'var(--text-primary)' }}>
                                <div style={{ fontSize: '0.8rem', color: '#ef4444', fontWeight: 600 }}>好敵手 (NEMESIS)</div>
                                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', fontFamily: 'var(--font-heading)' }}>GadgetReviewer</div>
                                <div style={{ marginTop: '10px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>You: 200 <span style={{ opacity: 0.6 }}>Target: 250</span></div>
                                <div style={{ marginTop: '5px', height: '6px', background: 'rgba(0,0,0,0.05)', borderRadius: '3px' }}>
                                    <div style={{ width: '80%', height: '100%', background: '#ef4444', borderRadius: '3px', boxShadow: '0 0 8px rgba(239,68,68,0.3)' }}></div>
                                </div>
                                <div style={{ fontSize: '0.8rem', marginTop: '5px', color: '#ef4444', fontWeight: 'bold' }}>🔥 差分: 50 人</div>
                            </div>
                            <div style={{ flex: 1, background: 'rgba(56, 189, 248, 0.05)', border: '1px solid rgba(56, 189, 248, 0.2)', padding: '1rem', borderRadius: '12px', color: 'var(--text-primary)' }}>
                                <div style={{ fontSize: '0.8rem', color: '#0ea5e9', fontWeight: 600 }}>師匠 (BENCHMARK)</div>
                                <div style={{ fontSize: '1.2rem', fontWeight: 'bold', fontFamily: 'var(--font-heading)' }}>TechMastery</div>
                                <div style={{ marginTop: '10px', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>目標: 10,000 人</div>
                                <div style={{ fontSize: '0.8rem', marginTop: '5px', color: '#0ea5e9', fontWeight: 'bold' }}>スタイルモデル: Tech</div>
                            </div>
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}
