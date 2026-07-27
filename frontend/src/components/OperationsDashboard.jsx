/**
 * OperationsDashboard.jsx — 運用監視ダッシュボード
 *
 * テレビ局技術部レベルの運用監視:
 * - システムヘルス（バックエンド接続状態）
 * - パイプラインステータス（処理状況）
 * - API使用量（モデル別・使用率・アラート）
 * - やり直し予算（残りリトライ回数）
 */
import React, { useState, useEffect, useCallback } from 'react';

const API_BASE = 'http://localhost:8000';

export default function OperationsDashboard() {
  const [health, setHealth] = useState(null);
  const [pipeline, setPipeline] = useState(null);
  const [usage, setUsage] = useState(null);
  const [retryBudget, setRetryBudget] = useState(null);
  const [governance, setGovernance] = useState(null);
  const [switchHistory, setSwitchHistory] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchAll = useCallback(async () => {
    const results = {};
    try {
      // Health
      const hRes = await fetch(`${API_BASE}/api/dashboard/health`).catch(() => null);
      results.health = hRes?.ok ? await hRes.json() : { status: 'offline' };
    } catch { results.health = { status: 'offline' }; }

    try {
      // Pipeline
      const pRes = await fetch(`${API_BASE}/api/pipeline/status`).catch(() => null);
      results.pipeline = pRes?.ok ? await pRes.json() : null;
    } catch { results.pipeline = null; }

    try {
      // Usage
      const uRes = await fetch(`${API_BASE}/api/usage/dashboard`).catch(() => null);
      results.usage = uRes?.ok ? await uRes.json() : null;
    } catch { results.usage = null; }

    try {
      // Retry Budget
      const rRes = await fetch(`${API_BASE}/api/usage/retry-budget`).catch(() => null);
      results.retryBudget = rRes?.ok ? await rRes.json() : null;
    } catch { results.retryBudget = null; }

    try {
      // Governance (tier status + fallback history)
      const gRes = await fetch(`${API_BASE}/api/usage/governance`).catch(() => null);
      results.governance = gRes?.ok ? await gRes.json() : null;
    } catch { results.governance = null; }

    try {
      // Switch History
      const sRes = await fetch(`${API_BASE}/api/usage/switch-history?limit=5`).catch(() => null);
      results.switchHistory = sRes?.ok ? await sRes.json() : null;
    } catch { results.switchHistory = null; }

    setHealth(results.health);
    setPipeline(results.pipeline);
    setUsage(results.usage);
    setRetryBudget(results.retryBudget);
    setGovernance(results.governance);
    setSwitchHistory(results.switchHistory);
    setLastUpdate(new Date());
    setIsLoading(false);
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15000); // 15秒ごと自動更新
    return () => clearInterval(interval);
  }, [fetchAll]);

  const isOnline = health?.status === 'healthy';

  // スタイル定義
  const s = {
    grid: {
      display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
      gap: '16px', marginBottom: '24px',
    },
    card: {
      background: 'white', borderRadius: '16px', padding: '20px',
      border: '1px solid #e2e8f0',
      boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
      transition: 'all 0.2s',
    },
    cardTitle: {
      fontSize: '0.82rem', fontWeight: 700, color: '#64748b',
      textTransform: 'uppercase', letterSpacing: '0.05em',
      marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px',
    },
    bigValue: {
      fontSize: '2rem', fontWeight: 800, letterSpacing: '-0.02em',
      lineHeight: 1.2,
    },
    subtitle: {
      fontSize: '0.85rem', color: '#94a3b8', marginTop: '4px',
    },
    progressBarOuter: {
      width: '100%', height: '8px', background: '#f1f5f9',
      borderRadius: '100px', overflow: 'hidden', marginTop: '8px',
    },
    alertBanner: (level) => ({
      padding: '10px 16px', borderRadius: '10px', marginBottom: '8px',
      fontSize: '0.88rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px',
      background: level === 'critical' ? '#fee2e2' : level === 'warning' ? '#fef3c7' : '#f0fdf4',
      color: level === 'critical' ? '#991b1b' : level === 'warning' ? '#92400e' : '#166534',
      border: `1px solid ${level === 'critical' ? '#fecaca' : level === 'warning' ? '#fde68a' : '#bbf7d0'}`,
    }),
  };

  const usageColor = (pct) => {
    if (pct >= 90) return '#EF4444';
    if (pct >= 70) return '#F59E0B';
    return '#10B981';
  };

  if (isLoading) {
    return (
      <div style={{ padding: '2rem', textAlign: 'center', color: '#94a3b8' }}>
        <div style={{ fontSize: '2rem', marginBottom: '8px', animation: 'pulse 1.5s infinite' }}>📡</div>
        システム情報を取得中...
      </div>
    );
  }

  return (
    <div style={{ animation: 'fadeIn 0.3s ease' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', margin: 0 }}>
          📡 運用監視
        </h2>
        <button
          onClick={fetchAll}
          style={{
            padding: '6px 14px', borderRadius: '8px', border: '1px solid #e2e8f0',
            background: 'white', color: '#64748b', fontSize: '0.82rem', fontWeight: 600,
            cursor: 'pointer', fontFamily: "'Noto Sans JP', sans-serif",
          }}
        >
          🔄 更新
        </button>
      </div>
      <p style={{ color: '#64748b', fontSize: '0.85rem', marginBottom: '20px' }}>
        最終更新: {lastUpdate ? lastUpdate.toLocaleTimeString('ja-JP') : '—'} ・ 自動更新: 15秒
      </p>

      {/* アラート表示 */}
      {usage?.alerts?.length > 0 && (
        <div style={{ marginBottom: '16px' }}>
          {usage.alerts.map((alert, i) => (
            <div key={i} style={s.alertBanner(alert.level)}>
              {alert.level === 'critical' ? '🚨' : alert.level === 'warning' ? '⚠️' : 'ℹ️'}
              {alert.message}
            </div>
          ))}
        </div>
      )}

      {/* グリッド: ステータスカード */}
      <div style={s.grid}>
        {/* ヘルスカード */}
        <div style={{
          ...s.card,
          borderLeft: `4px solid ${isOnline ? '#10B981' : '#EF4444'}`,
        }}>
          <div style={s.cardTitle}>💚 システム状態</div>
          <div style={{
            ...s.bigValue,
            color: isOnline ? '#10B981' : '#EF4444',
          }}>
            {isOnline ? 'ONLINE' : 'OFFLINE'}
          </div>
          <div style={s.subtitle}>
            {isOnline ? 'バックエンド正常稼働中' : 'バックエンド接続不可'}
          </div>
        </div>

        {/* パイプラインカード */}
        <div style={{
          ...s.card,
          borderLeft: `4px solid ${
            pipeline?.phase === 'idle' ? '#94a3b8'
            : pipeline?.phase === 'processing' ? '#7C3AED'
            : pipeline?.phase === 'error' ? '#EF4444'
            : '#10B981'
          }`,
        }}>
          <div style={s.cardTitle}>⚙️ パイプライン</div>
          <div style={{
            ...s.bigValue,
            color: pipeline?.phase === 'processing' ? '#7C3AED' : '#1e293b',
            fontSize: '1.4rem',
          }}>
            {pipeline?.current_step || pipeline?.phase || '待機中'}
          </div>
          {pipeline?.progress > 0 && pipeline?.phase !== 'idle' && (
            <div style={s.progressBarOuter}>
              <div style={{
                width: `${pipeline.progress}%`, height: '100%',
                background: 'linear-gradient(90deg, #7C3AED, #6D28D9)',
                borderRadius: '100px', transition: 'width 0.5s ease',
              }} />
            </div>
          )}
          <div style={s.subtitle}>
            {pipeline?.progress > 0 ? `進捗: ${pipeline.progress}%` : '処理なし'}
          </div>
        </div>

        {/* やり直し予算カード */}
        <div style={{
          ...s.card,
          borderLeft: `4px solid ${
            retryBudget?.premium?.warning ? '#F59E0B' : '#10B981'
          }`,
        }}>
          <div style={s.cardTitle}>🔄 やり直し予算</div>
          <div style={{ display: 'flex', gap: '20px' }}>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>Premium</div>
              <div style={{
                ...s.bigValue,
                fontSize: '1.6rem',
                color: retryBudget?.premium?.warning ? '#F59E0B' : '#1e293b',
              }}>
                {retryBudget?.premium?.estimated_retries ?? '—'}回
              </div>
            </div>
            <div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600 }}>Standard</div>
              <div style={{ ...s.bigValue, fontSize: '1.6rem', color: '#1e293b' }}>
                {retryBudget?.standard?.estimated_retries ?? '—'}回
              </div>
            </div>
          </div>
          <div style={{ ...s.subtitle, fontSize: '0.8rem' }}>
            {retryBudget?.advice || '—'}
          </div>
        </div>
      </div>

      {/* アクティブモデル（現在のテキスト生成用モデル） */}
      {governance?.tiers && (
        <div style={{ marginBottom: '20px' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px', color: '#1e293b' }}>
            🎯 現在のアクティブモデル
          </h3>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            {Object.entries(governance.tiers).map(([tierName, tier]) => {
              const usageData = governance.usage?.models?.[tier.model] || {};
              const pct = Math.round((usageData.usage_ratio || 0) * 100);
              const isActive = pct < 95;
              const tierColors = {
                premium: { bg: 'rgba(255,215,0,0.08)', border: '#ffd700', icon: '⭐' },
                standard: { bg: 'rgba(139,92,246,0.06)', border: '#7c3aed', icon: '🔷' },
                batch: { bg: 'rgba(100,149,237,0.06)', border: '#6495ed', icon: '📦' },
              };
              const c = tierColors[tierName] || tierColors.standard;
              return (
                <div key={tierName} style={{
                  ...s.card, flex: '1 1 180px', padding: '12px 16px',
                  background: c.bg,
                  border: isActive ? `2px solid ${c.border}` : '2px solid #e2e8f0',
                  opacity: isActive ? 1 : 0.5,
                  position: 'relative',
                }}>
                  {isActive && pct < 95 && (
                    <div style={{
                      position: 'absolute', top: -6, right: -6,
                      background: '#10B981', color: 'white',
                      fontSize: '0.6rem', fontWeight: 800, padding: '1px 6px',
                      borderRadius: 6,
                    }}>ACTIVE</div>
                  )}
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8', fontWeight: 600, marginBottom: 4 }}>
                    {c.icon} {tier.label || tierName}
                  </div>
                  <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#1e293b', marginBottom: 6 }}>
                    {tier.model}
                  </div>
                  <div style={s.progressBarOuter}>
                    <div style={{
                      width: `${Math.min(pct, 100)}%`, height: '100%',
                      borderRadius: '100px', background: usageColor(pct),
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8', marginTop: 4 }}>
                    <span>{usageData.used || 0}/{usageData.limit || '?'}</span>
                    <span style={{ fontWeight: 700, color: usageColor(pct) }}>{pct}%</span>
                  </div>
                </div>
              );
            })}
          </div>
          {/* フォールバックチェーン表示 */}
          {governance.fallback_chain && Object.keys(governance.fallback_chain).length > 0 && (
            <div style={{
              marginTop: 8, padding: '6px 12px', borderRadius: 8,
              background: '#f8fafc', fontSize: '0.75rem', color: '#64748b',
              display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap',
            }}>
              ⛓️ 降格チェーン:
              {Object.entries(governance.fallback_chain).map(([from, to], i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                  <span style={{ fontWeight: 600 }}>{from.split('-').slice(-2).join('-')}</span>
                  {to ? <span>→</span> : <span style={{ color: '#ef4444' }}>→ ✕</span>}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 降格履歴 */}
      {switchHistory?.history?.length > 0 && (
        <div style={{ marginBottom: '20px' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '8px', color: '#1e293b' }}>
            🔄 降格履歴
          </h3>
          {switchHistory.history.map((evt, i) => (
            <div key={i} style={{
              ...s.card, padding: '10px 14px', marginBottom: 6,
              borderLeft: '4px solid #f59e0b',
              fontSize: '0.82rem',
            }}>
              <div style={{ fontWeight: 600, color: '#92400e' }}>
                {evt.original_model} → {evt.fallback_model}
              </div>
              <div style={{ color: '#94a3b8', fontSize: '0.75rem' }}>
                {evt.reason} ・ {evt.task} ・ {new Date(evt.timestamp).toLocaleTimeString('ja-JP')}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* モデル別使用量 */}
      <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px', color: '#1e293b' }}>
        📊 モデル別API使用量
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {usage?.models?.length > 0 ? usage.models
          .filter(model => model.name.startsWith('gemini'))
          .map((model, i) => (
          <div key={i} style={{
            ...s.card,
            padding: '14px 20px',
            display: 'flex', alignItems: 'center', gap: '16px',
            borderLeft: `4px solid ${usageColor(model.usage_percent)}`,
          }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                <span style={{ fontWeight: 700, fontSize: '0.92rem' }}>{model.name}</span>
                <span style={{
                  padding: '2px 8px', borderRadius: '100px', fontSize: '0.7rem',
                  fontWeight: 600, background: '#f3f0ff', color: '#7C3AED',
                }}>
                  {model.tier}
                </span>
                {!model.can_use && (
                  <span style={{
                    padding: '2px 8px', borderRadius: '100px', fontSize: '0.65rem',
                    fontWeight: 700, background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                  }}>
                    枠枯渇
                  </span>
                )}
              </div>
              <div style={s.progressBarOuter}>
                <div style={{
                  width: `${Math.min(model.usage_percent, 100)}%`,
                  height: '100%', borderRadius: '100px',
                  background: usageColor(model.usage_percent),
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>
            <div style={{ textAlign: 'right', minWidth: '120px' }}>
              <div style={{ fontWeight: 700, color: usageColor(model.usage_percent) }}>
                {model.usage_percent}%
              </div>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                {model.used}/{model.limit} 使用
              </div>
            </div>
          </div>
        )) : (
          <div style={{
            ...s.card, padding: '20px', textAlign: 'center', color: '#94a3b8',
          }}>
            使用量データなし（APIが応答していません）
          </div>
        )}
      </div>

      {/* 推奨事項 */}
      {usage?.recommendations?.length > 0 && (
        <div style={{ marginTop: '16px' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '8px', color: '#1e293b' }}>
            💡 最適化の提案
          </h3>
          {usage.recommendations.map((rec, i) => (
            <div key={i} style={{
              padding: '10px 14px', borderRadius: '10px',
              background: '#f3f0ff', color: '#6D28D9',
              fontSize: '0.85rem', marginBottom: '6px',
            }}>
              {rec.type === 'optimization' ? '⚡' : '💡'} {rec.message}
            </div>
          ))}
        </div>
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
