import React, { useState, useEffect } from 'react';
import { Shield, Target, Activity, Gavel, HelpCircle, FileText } from 'lucide-react';
import confetti from 'canvas-confetti';

// --- STANCE CARD COMPONENT ---
const StanceCard = ({ response }) => {
    // Color mapping
    const stanceColor = {
        "AGREE": "#10b981", // Green (Prosperity)
        "DISAGREE": "#ef4444", // Red (Passion)
        "NEUTRAL": "#fbbf24", // Yellow (Caution)
    }[response.stance] || "#cbd5e0";

    return (
        <div style={{
            background: 'rgba(255, 255, 255, 0.8)',
            backdropFilter: 'blur(10px)',
            border: `1px solid var(--border-color)`,
            borderLeft: `4px solid ${stanceColor}`,
            borderRadius: '12px',
            padding: '15px',
            marginBottom: '15px',
            position: 'relative',
            boxShadow: '0 4px 6px rgba(0,0,0,0.02)',
            color: 'var(--text-primary)'
        }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ color: response.color, fontWeight: 'bold', display: 'flex', alignItems: 'center' }}>
                    {response.role === 'Data Scientist' && <Activity size={16} style={{ marginRight: 5 }} />}
                    {response.role === 'Creative Director' && <Target size={16} style={{ marginRight: 5 }} />}
                    {response.role === 'Brand Guardian' && <Shield size={16} style={{ marginRight: 5 }} />}
                    {response.agent} <span style={{ fontSize: '0.8em', opacity: 0.7, marginLeft: 5 }}>({response.role})</span>
                </span>
                <span style={{
                    background: stanceColor,
                    color: '#fff',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontSize: '0.8em',
                    fontWeight: 'bold'
                }}>
                    {response.stance}
                </span>
            </div>

            <p style={{ margin: '0', fontSize: '1.05em', fontWeight: '500', lineHeight: '1.6', color: 'var(--text-primary)' }}>{response.detail}</p>

            {response.glossary && response.glossary.length > 0 && (
                <div style={{ marginTop: '12px', fontSize: '0.9em', color: 'var(--text-secondary)', background: 'rgba(139, 92, 246, 0.05)', padding: '8px', borderRadius: '8px' }}>
                    {response.glossary.map((g, i) => (
                        <span key={i} title={g.def} style={{
                            borderBottom: '1px dotted var(--text-secondary)',
                            cursor: 'help',
                            marginRight: '12px',
                            display: 'inline-flex',
                            alignItems: 'center'
                        }}>
                            <HelpCircle size={12} style={{ marginRight: 4 }} /> {g.term}
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
};

// --- MAIN CHAMBER COMPONENT ---
export default function CouncilChamber({ initialQuery }) {
    const [query, setQuery] = useState(initialQuery || "");
    const [status, setStatus] = useState("IDLE"); // IDLE, DEBATING, SYNTHESIZING, WAITING_CHAIRMAN
    const [debateFlow, setDebateFlow] = useState([]);
    const [synthesis, setSynthesis] = useState(null);
    const [sessionId, setSessionId] = useState(null);
    const [hasAutoRun, setHasAutoRun] = useState(false);

    useEffect(() => {
        if (initialQuery && !hasAutoRun) {
            setQuery(initialQuery);
            setHasAutoRun(true);
            setTimeout(() => {
                runDebate(initialQuery);
            }, 500); // Small delay for UI mount
        }
    }, [initialQuery]);

    const runDebate = async (overrideQuery = null) => {
        const q = overrideQuery || query;
        if (!q) return;
        setStatus("DEBATING");
        setDebateFlow([]);
        setSynthesis(null);

        try {
            const res = await fetch(`http://localhost:8000/api/council/session?query=${encodeURIComponent(q)}`, {
                method: 'POST'
            });
            const data = await res.json();

            // Simulating sequential debate for visual effect
            setSessionId(data.session_id);
            const flow = data.debate_flow || [];

            for (let i = 0; i < flow.length; i++) {
                await new Promise(r => setTimeout(r, 800)); // Delay for dramatic effect
                setDebateFlow(prev => [...prev, flow[i]]);
            }

            setStatus("SYNTHESIZING");
            await new Promise(r => setTimeout(r, 1000));
            setSynthesis(data.synthesis);
            setStatus("WAITING_CHAIRMAN");

        } catch (e) {
            console.error(e);
            setStatus("IDLE");
        }
    };

    const handleChairmanAction = async (action) => {
        // alert(`議長決裁: ${action === 'APPROVE' ? '承認' : '却下'}\nセッション: ${sessionId.substring(0,8)}...`);

        try {
            await fetch('http://localhost:8000/api/council/decision', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    outcome: action,
                    debate_flow: debateFlow
                })
            });
            if (action === 'APPROVE') {
                confetti({
                    particleCount: 100,
                    spread: 70,
                    origin: { y: 0.6 },
                    colors: ['#F59E0B', '#EC4899', '#8B5CF6']
                });
                setTimeout(() => setStatus("IDLE"), 2000);
            } else {
                setStatus("IDLE");
            }
        } catch (e) {
            console.error("Failed to teach agents:", e);
            if (action === 'APPROVE') setStatus("IDLE");
        }
    };

    return (
        <div className="council-chamber" style={{ padding: '0', background: 'transparent', color: 'var(--text-primary)', borderRadius: '12px', border: 'none' }}>
            {/* 1. Header (Removed explicitly since it is handled by parent, or kept minimal) */}
            <h2 style={{ borderBottom: '1px solid var(--border-color)', paddingBottom: '15px', margin: '15px', fontFamily: 'var(--font-heading)', color: 'var(--text-primary)', display: 'none' }}>
                <Gavel style={{ marginRight: '10px', color: '#F59E0B' }} />
                未来評議会
            </h2>

            {/* 2. Motion Input (if Idle) */}
            {status === "IDLE" && (
                <div style={{ marginTop: '20px' }}>
                    <p style={{ color: '#4a5568', fontWeight: 'bold' }}>戦略的な問いを入力し、評議会を招集してください：</p>
                    <div style={{ display: 'flex', gap: '10px' }}>
                            <input
                                type="text"
                                value={query}
                                onChange={e => setQuery(e.target.value)}
                                placeholder="例：もっと視聴維持率を上げるには？"
                                style={{
                                    flex: 1,
                                    padding: '12px',
                                    background: 'var(--bg-primary)',
                                    border: '1px solid var(--border-color)',
                                    color: 'var(--text-primary)',
                                    borderRadius: '8px',
                                    fontSize: '1rem',
                                    boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.02)'
                                }}
                            />
                            <button
                                onClick={runDebate}
                                style={{
                                    padding: '12px 24px',
                                    background: 'linear-gradient(135deg, #8B5CF6, #EC4899)',
                                    color: '#fff',
                                    border: 'none',
                                    borderRadius: '8px',
                                    fontWeight: 'bold',
                                    cursor: 'pointer',
                                    boxShadow: '0 4px 12px rgba(236, 72, 153, 0.4)'
                                }}
                            >
                                評議会・招集
                            </button>
                    </div>
                </div>
            )}

            {/* 3. Debate Flow */}
            <div style={{ marginTop: '30px' }}>
                {debateFlow.map((res, idx) => (
                    <StanceCard key={idx} response={res} />
                ))}
            </div>

            {/* 4. Synthesis & Gavel */}
            {status === "WAITING_CHAIRMAN" && synthesis && (
                <div style={{
                    margin: '30px 15px',
                    padding: '25px',
                    background: 'linear-gradient(135deg, rgba(255,255,255,0.1), rgba(255,255,255,0.05))',
                    backdropFilter: 'blur(12px)',
                    border: '1px solid rgba(255,255,255,0.2)',
                    borderRadius: '16px',
                    textAlign: 'center',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.2)'
                }}>
                    <h3 style={{ color: '#F59E0B', fontSize: '0.9em', letterSpacing: '2px', fontFamily: 'var(--font-heading)' }}>NEXUS SYNTHESIS (統合提案)</h3>
                    <p style={{ fontSize: '1.2em', margin: '15px 0', fontWeight: 'bold', color: '#f8fafc' }}>{synthesis.proposal}</p>

                    <div style={{ display: 'flex', justifyContent: 'center', gap: '20px', marginTop: '25px' }}>
                        <button
                            onClick={() => handleChairmanAction('APPROVE')}
                            style={{ background: '#10b981', color: '#fff', border: 'none', padding: '12px 35px', borderRadius: '30px', fontWeight: 'bold', display: 'flex', alignItems: 'center', cursor: 'pointer', boxShadow: '0 4px 10px rgba(16, 185, 129, 0.3)' }}
                        >
                            <Gavel size={18} style={{ marginRight: 5 }} /> 承認 (APPROVE)
                        </button>
                        <button
                            onClick={() => handleChairmanAction('REJECT')}
                            style={{ background: '#fff', color: '#ef4444', border: '1px solid #ef4444', padding: '12px 35px', borderRadius: '30px', fontWeight: 'bold', cursor: 'pointer' }}
                        >
                            却下 (REJECT)
                        </button>
                    </div>
                </div>
            )}

            {status === "DEBATING" && <p style={{ textAlign: 'center', color: '#718096', marginTop: '30px', fontStyle: 'italic' }}>評議会が議論中です...</p>}
        </div>
    );
}
