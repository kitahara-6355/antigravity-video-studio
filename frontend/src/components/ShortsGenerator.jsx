/**
 * ShortsGenerator.jsx — Shorts切り出し + 縦型レンダリングUI
 *
 * 本編の字幕セグメントからShorts候補を自動抽出し、
 * 選択した候補を9:16（1080x1920）でレンダリング:
 * - フック部分（冒頭15秒）
 * - ハイライト部分（感嘆詞検出）
 * - まとめ部分（終盤20%）
 *
 * バックエンド: カタログの postShortsCandidates（候補抽出）と
 *   postShortsRender（縦型レンダリング）
 */
import React, { useState } from 'react';
import { apiFetch } from '../gateway/client.js';


const STRATEGY_LABELS = {
  hook_clip: { icon: '🎣', label: 'フック切り出し', color: '#7C3AED' },
  highlight: { icon: '⚡', label: 'ハイライト', color: '#F59E0B' },
  conclusion: { icon: '🎯', label: 'まとめ', color: '#10B981' },
};

export default function ShortsGenerator({ segments = [], videoDuration = 0, videoPath = '' }) {
  const [candidates, setCandidates] = useState([]);
  const [shortsSpec, setShortsSpec] = useState(null);
  const [ctaTemplates, setCtaTemplates] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedIds, setSelectedIds] = useState(new Set());

  // レンダリング状態
  const [renderStatus, setRenderStatus] = useState({}); // { candidateId: { status, result } }
  const [isRendering, setIsRendering] = useState(false);

  const handleExtract = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiFetch('postShortsCandidates', { body: {
          segments: segments,
          video_duration_sec: videoDuration || 300,
          video_id: 'current',
        } });
      if (!res.ok) throw new Error(`API Error: ${res.status}`);
      const data = await res.json();
      setCandidates(data.candidates || []);
      setShortsSpec(data.shorts_spec || null);
      setCtaTemplates(data.cta_templates || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // 選択した候補を縦型レンダリング
  const handleRenderSelected = async () => {
    if (selectedIds.size === 0 || !videoPath) return;
    setIsRendering(true);
    setError(null);

    const selected = candidates.filter(c => selectedIds.has(c.id));

    for (const candidate of selected) {
      setRenderStatus(prev => ({
        ...prev,
        [candidate.id]: { status: 'rendering', result: null }
      }));

      try {
        const res = await apiFetch('postShortsRender', { body: {
            video_path: videoPath,
            start_sec: candidate.start_sec,
            end_sec: candidate.end_sec,
            subtitle_text: candidate.preview_text?.slice(0, 50) || null,
          } });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        const result = await res.json();
        setRenderStatus(prev => ({
          ...prev,
          [candidate.id]: { status: 'done', result }
        }));
      } catch (err) {
        setRenderStatus(prev => ({
          ...prev,
          [candidate.id]: { status: 'error', result: { error: err.message } }
        }));
      }
    }

    setIsRendering(false);
  };

  const toggleSelect = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const formatTime = (sec) => {
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  const completedCount = Object.values(renderStatus).filter(r => r.status === 'done').length;
  const errorCount = Object.values(renderStatus).filter(r => r.status === 'error').length;

  const s = {
    container: { animation: 'fadeIn 0.3s ease' },
    card: {
      background: 'white', borderRadius: '14px', padding: '16px 20px',
      border: '1px solid #e2e8f0', marginBottom: '10px',
      cursor: 'pointer', transition: 'all 0.2s',
    },
    specBadge: {
      display: 'inline-block', padding: '4px 10px', borderRadius: '6px',
      fontSize: '0.78rem', fontWeight: 600, marginRight: '6px',
      background: '#f3f0ff', color: '#7C3AED',
    },
    strategyBadge: (strategy) => {
      const info = STRATEGY_LABELS[strategy] || { icon: '📌', label: strategy, color: '#64748b' };
      return {
        display: 'inline-flex', alignItems: 'center', gap: '4px',
        padding: '3px 10px', borderRadius: '100px',
        fontSize: '0.78rem', fontWeight: 600,
        background: `${info.color}15`, color: info.color,
      };
    },
    extractBtn: {
      width: '100%', padding: '14px', borderRadius: '12px',
      border: 'none', fontSize: '1rem', fontWeight: 700,
      fontFamily: "'Noto Sans JP', sans-serif",
      background: 'linear-gradient(135deg, #EC4899, #DB2777)',
      color: 'white', cursor: 'pointer',
      boxShadow: '0 4px 14px rgba(236,72,153,0.3)',
      transition: 'all 0.2s',
    },
    renderBtn: {
      width: '100%', padding: '14px', borderRadius: '12px',
      border: 'none', fontSize: '1rem', fontWeight: 700,
      fontFamily: "'Noto Sans JP', sans-serif",
      background: 'linear-gradient(135deg, #7C3AED, #5B21B6)',
      color: 'white', cursor: 'pointer',
      boxShadow: '0 4px 14px rgba(124,58,237,0.3)',
      transition: 'all 0.2s', marginTop: '12px',
    },
    renderResult: {
      marginTop: '6px', padding: '8px 12px', borderRadius: '8px',
      fontSize: '0.82rem',
    },
  };

  return (
    <div style={s.container}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
        📱 Shorts切り出し + レンダリング
      </h2>
      <p style={{ color: '#64748b', fontSize: '0.9rem', marginBottom: '20px' }}>
        本編からショート動画候補を自動検出。選択した候補を縦型（9:16）でレンダリング。
      </p>

      {/* 仕様表示 */}
      {shortsSpec && (
        <div style={{ marginBottom: '16px', display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <span style={s.specBadge}>📐 {shortsSpec.aspect_ratio}</span>
          <span style={s.specBadge}>📺 {shortsSpec.resolution}</span>
          <span style={s.specBadge}>⏱️ 最大{shortsSpec.max_duration_sec}秒</span>
        </div>
      )}

      {/* 抽出ボタン */}
      <button
        style={{
          ...s.extractBtn,
          opacity: isLoading ? 0.6 : 1,
          cursor: isLoading ? 'not-allowed' : 'pointer',
        }}
        onClick={handleExtract}
        disabled={isLoading}
      >
        {isLoading ? '🔄 AI分析中...' : '📱 Shorts候補を抽出する'}
      </button>

      {/* エラー */}
      {error && (
        <div style={{
          marginTop: '12px', padding: '12px', background: '#fee2e2',
          color: '#991b1b', borderRadius: '10px', fontSize: '0.9rem',
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* 候補一覧 */}
      {candidates.length > 0 && (
        <div style={{ marginTop: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, color: '#1e293b', margin: 0 }}>
              🎬 検出された候補（{candidates.length}件）
            </h3>
            {selectedIds.size > 0 && (
              <span style={{
                padding: '4px 12px', borderRadius: '100px',
                fontSize: '0.82rem', fontWeight: 700,
                background: '#d1fae5', color: '#065f46',
              }}>
                {selectedIds.size}件選択中
              </span>
            )}
          </div>

          {candidates.map((c) => {
            const info = STRATEGY_LABELS[c.strategy] || { icon: '📌', label: c.strategy, color: '#64748b' };
            const isSelected = selectedIds.has(c.id);
            const rs = renderStatus[c.id];

            return (
              <div key={c.id}>
                <div
                  onClick={() => toggleSelect(c.id)}
                  style={{
                    ...s.card,
                    borderColor: isSelected ? '#7C3AED' : '#e2e8f0',
                    borderWidth: isSelected ? '2px' : '1px',
                    background: isSelected ? '#faf5ff' : 'white',
                    marginBottom: rs ? '4px' : '10px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                        <span style={{ fontSize: '1.2rem' }}>{info.icon}</span>
                        <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{c.title}</span>
                        <span style={s.strategyBadge(c.strategy)}>{info.label}</span>
                      </div>
                      <div style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '6px' }}>
                        ⏱️ {formatTime(c.start_sec)} → {formatTime(c.end_sec)}（{c.duration_sec}秒）
                      </div>
                      {c.preview_text && (
                        <div style={{
                          fontSize: '0.82rem', color: '#94a3b8',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          maxWidth: '400px',
                        }}>
                          💬 {c.preview_text}
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: '12px' }}>
                      <div style={{
                        width: '28px', height: '28px', borderRadius: '8px',
                        border: `2px solid ${isSelected ? '#7C3AED' : '#d1d5db'}`,
                        background: isSelected ? '#7C3AED' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: 'white', fontSize: '0.8rem', fontWeight: 700,
                        transition: 'all 0.2s',
                      }}>
                        {isSelected && '✓'}
                      </div>
                      <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginTop: '6px' }}>
                        {c.estimated_views_boost && c.estimated_views_boost.split('→')[0]}
                      </div>
                    </div>
                  </div>
                </div>

                {/* レンダリング結果 */}
                {rs && (
                  <div style={{
                    ...s.renderResult,
                    background: rs.status === 'done' ? '#f0fdf4' : rs.status === 'error' ? '#fef2f2' : '#eff6ff',
                    color: rs.status === 'done' ? '#166534' : rs.status === 'error' ? '#991b1b' : '#1e40af',
                    border: `1px solid ${rs.status === 'done' ? '#bbf7d0' : rs.status === 'error' ? '#fecaca' : '#bfdbfe'}`,
                    marginBottom: '10px',
                  }}>
                    {rs.status === 'rendering' && '🔄 レンダリング中...'}
                    {rs.status === 'done' && (
                      <>
                        ✅ 完了 — {rs.result.size_mb}MB | {rs.result.resolution} | {rs.result.duration_sec}秒
                        <div style={{ fontSize: '0.75rem', marginTop: '4px', color: '#64748b' }}>
                          📁 {rs.result.path}
                        </div>
                      </>
                    )}
                    {rs.status === 'error' && `❌ 失敗: ${rs.result?.error}`}
                  </div>
                )}
              </div>
            );
          })}

          {/* レンダリング実行ボタン */}
          {selectedIds.size > 0 && (
            <button
              style={{
                ...s.renderBtn,
                opacity: isRendering || !videoPath ? 0.6 : 1,
                cursor: isRendering || !videoPath ? 'not-allowed' : 'pointer',
              }}
              onClick={handleRenderSelected}
              disabled={isRendering || !videoPath}
            >
              {isRendering
                ? `🔄 レンダリング中... (${completedCount}/${selectedIds.size})`
                : `🎬 ${selectedIds.size}件をShorts（9:16）でレンダリング`}
            </button>
          )}

          {/* レンダリング完了サマリー */}
          {completedCount > 0 && !isRendering && (
            <div style={{
              marginTop: '12px', padding: '12px 16px', borderRadius: '10px',
              background: 'linear-gradient(135deg, #f0fdf4, #ecfdf5)',
              border: '1px solid #86efac',
              fontSize: '0.9rem', color: '#166534', fontWeight: 600,
            }}>
              🎉 {completedCount}件のShortsレンダリング完了
              {errorCount > 0 && ` （${errorCount}件失敗）`}
            </div>
          )}

          {!videoPath && selectedIds.size > 0 && (
            <div style={{
              marginTop: '8px', padding: '10px 14px', borderRadius: '8px',
              background: '#fefce8', border: '1px solid #fde68a',
              fontSize: '0.85rem', color: '#92400e',
            }}>
              ⚠️ レンダリングには元動画のパスが必要です。パイプラインから起動してください。
            </div>
          )}

          {/* CTA テンプレート */}
          {ctaTemplates.length > 0 && (
            <div style={{ marginTop: '16px' }}>
              <h3 style={{ fontSize: '0.92rem', fontWeight: 700, color: '#1e293b', marginBottom: '8px' }}>
                📢 CTA（本編への誘導）テンプレート
              </h3>
              {ctaTemplates.map((cta, i) => (
                <div key={i} style={{
                  padding: '10px 14px', borderRadius: '8px',
                  background: '#f0fdf4', border: '1px solid #bbf7d0',
                  fontSize: '0.85rem', color: '#166534',
                  marginBottom: '6px',
                }}>
                  <span style={{ fontWeight: 600 }}>{cta.type === 'end_card' ? '🃏 エンドカード' : cta.type === 'pinned_comment' ? '📌 固定コメント' : '📝 説明文'}</span>
                  ：{cta.text}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

