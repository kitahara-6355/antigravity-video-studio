import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch, apiUrl } from '../api/client.js';

const ProofreadingStagePanel = ({ stageData, isActive }) => {
  const [segments, setSegments] = useState([]);
  const [stats, setStats] = useState({ approved: 0, rejected: 0, pending: 0 });
  const [dictionary, setDictionary] = useState([]);
  const [showDict, setShowDict] = useState(false);
  const [newEntry, setNewEntry] = useState({ incorrect: '', correct: '' });
  const [prProgress, setPrProgress] = useState(0);
  const [skipProofreading, setSkipProofreading] = useState(false);

  const fetchResult = useCallback(() => {
    apiFetch('getPipelineProofreadingResult')
      .then(r => r.json())
      .then(data => {
        setSegments(data.segments || []);
        setStats({ approved: data.approved_count, rejected: data.rejected_count, pending: data.pending_count });
      }).catch(() => {});
  }, []);

  useEffect(() => { fetchResult(); }, [fetchResult]);

  useEffect(() => {
    const poll = setInterval(() => {
      apiFetch('getPipelineProofreadingStatus')
        .then(r => r.json())
        .then(data => { setPrProgress(data.progress); setSkipProofreading(data.skip); })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const fetchDict = useCallback(() => {
    apiFetch('getPipelineDictionary')
      .then(r => r.json())
      .then(data => setDictionary(data.entries || []))
      .catch(() => {});
  }, []);

  const approveSegment = async (id) => {
    await apiFetch('postPipelineProofreadingApprove', { body: { segment_id: id } });
    fetchResult();
  };

  const rejectSegment = async (id) => {
    await apiFetch('postPipelineProofreadingReject', { body: { segment_id: id } });
    fetchResult();
  };

  const approveAll = async () => {
    await apiFetch('postPipelineProofreadingApproveAll');
    fetchResult();
  };

  const rejectAll = async () => {
    await apiFetch('postPipelineProofreadingRejectAll');
    fetchResult();
  };

  const addDictEntry = async () => {
    if (!newEntry.incorrect || !newEntry.correct) return;
    await apiFetch('postPipelineDictionary', { body: newEntry });
    setNewEntry({ incorrect: '', correct: '' });
    fetchDict();
  };

  const deleteDictEntry = async (entryId) => {
    await apiFetch('deletePipelineDictionary', { params: { entry_id: entryId } });
    fetchDict();
  };

  const toggleSkip = async () => {
    const newSkip = !skipProofreading;
    await apiFetch('postPipelineProofreadingSkip', { body: { skip: newSkip } });
    setSkipProofreading(newSkip);
  };

  const fmtTime = (sec) => `${Math.floor(sec/60)}:${String(Math.floor(sec%60)).padStart(2,'0')}`;

  const LINE_LIMIT = 18;

  return (
    <div data-testid="proofreading-stage-panel" style={{ background:'var(--bg-primary,#f8fafc)', borderRadius:12, padding:16, marginTop:12 }}>
      {/* ヘッダー */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:12 }}>
        <div style={{ fontSize:'0.82rem', fontWeight:600 }}>📝 AI校閲結果</div>
        <div style={{ display:'flex', gap:8, alignItems:'center' }}>
          <label data-testid="skip-proofreading-toggle" style={{ display:'flex', alignItems:'center', gap:4, fontSize:'0.72rem', cursor:'pointer' }}>
            <input type="checkbox" checked={skipProofreading} onChange={toggleSkip} />
            校閲スキップ
          </label>
          <button data-testid="approve-all-btn" onClick={approveAll}
            style={{ padding:'4px 12px', borderRadius:6, border:'none', background:'#22c55e', color:'white', fontSize:'0.72rem', cursor:'pointer', fontWeight:600 }}>
            ✓ 全承認
          </button>
          <button data-testid="reject-all-btn" onClick={rejectAll}
            style={{ padding:'4px 12px', borderRadius:6, border:'none', background:'#ef4444', color:'white', fontSize:'0.72rem', cursor:'pointer', fontWeight:600 }}>
            ✗ 全却下
          </button>
          <button onClick={() => { setShowDict(!showDict); if(!showDict) fetchDict(); }}
            style={{ padding:'4px 12px', borderRadius:6, border:'1px solid var(--border-color,#e2e8f0)', background:'transparent', fontSize:'0.72rem', cursor:'pointer' }}>
            📖 辞書 {showDict ? '▲' : '▼'}
          </button>
          <a data-testid="export-srt-btn" href={apiUrl('getPipelineProofreadingExport', { params: { export_format: 'srt' } })}
            style={{ padding:'4px 10px', borderRadius:6, border:'1px solid var(--border-color,#e2e8f0)', fontSize:'0.72rem', textDecoration:'none', color:'inherit' }}>
            📥 SRT
          </a>
          <a data-testid="export-txt-btn" href={apiUrl('getPipelineProofreadingExport', { params: { export_format: 'txt' } })}
            style={{ padding:'4px 10px', borderRadius:6, border:'1px solid var(--border-color,#e2e8f0)', fontSize:'0.72rem', textDecoration:'none', color:'inherit' }}>
            📥 TXT
          </a>
        </div>
      </div>

      {/* 進捗 */}
      <div data-testid="proofreading-progress" style={{ marginBottom:12 }}>
        <div style={{ height:4, borderRadius:2, background:'#e2e8f0', overflow:'hidden' }}>
          <div style={{ height:'100%', background:'#8b5cf6', width:`${prProgress}%`, transition:'width 0.5s' }} />
        </div>
        <div style={{ display:'flex', gap:12, fontSize:'0.72rem', marginTop:4 }}>
          <span style={{ color:'#22c55e' }}>✓ 承認: {stats.approved}</span>
          <span style={{ color:'#ef4444' }}>✗ 却下: {stats.rejected}</span>
          <span style={{ color:'#94a3b8' }}>保留: {stats.pending}</span>
        </div>
      </div>

      {/* 辞書パネル */}
      {showDict && (
        <div data-testid="dictionary-panel" style={{ marginBottom:16, padding:12, background:'rgba(139,92,246,0.04)', borderRadius:8, border:'1px solid rgba(139,92,246,0.15)' }}>
          <div style={{ fontSize:'0.78rem', fontWeight:600, marginBottom:8 }}>📖 固有名詞辞書 ({dictionary.length}件)</div>
          {dictionary.map(e => (
            <div key={e.id} data-testid={`dict-entry-${e.id}`} style={{ display:'flex', gap:8, alignItems:'center', fontSize:'0.75rem', padding:'4px 0' }}>
              <span style={{ textDecoration:'line-through', color:'#ef4444' }}>{e.incorrect}</span>
              <span>→</span>
              <span style={{ color:'#22c55e', fontWeight:600 }}>{e.correct}</span>
              <span style={{ color:'#94a3b8', fontSize:'0.65rem' }}>({e.type})</span>
              <button data-testid={`dict-delete-${e.id}`} onClick={() => deleteDictEntry(e.id)}
                style={{ marginLeft:'auto', padding:'1px 6px', borderRadius:4, border:'1px solid #fca5a5', background:'transparent', color:'#ef4444', fontSize:'0.65rem', cursor:'pointer' }}>✕</button>
            </div>
          ))}
          <div style={{ display:'flex', gap:6, marginTop:8 }}>
            <input data-testid="dict-incorrect-input" placeholder="誤変換" value={newEntry.incorrect}
              onChange={e => setNewEntry(p => ({ ...p, incorrect: e.target.value }))}
              style={{ flex:1, padding:'4px 8px', borderRadius:6, border:'1px solid #e2e8f0', fontSize:'0.75rem' }} />
            <input data-testid="dict-correct-input" placeholder="正しい表記" value={newEntry.correct}
              onChange={e => setNewEntry(p => ({ ...p, correct: e.target.value }))}
              style={{ flex:1, padding:'4px 8px', borderRadius:6, border:'1px solid #e2e8f0', fontSize:'0.75rem' }} />
            <button data-testid="dict-add-btn" onClick={addDictEntry}
              style={{ padding:'4px 12px', borderRadius:6, border:'none', background:'#8b5cf6', color:'white', fontSize:'0.72rem', cursor:'pointer' }}>追加</button>
          </div>
        </div>
      )}

      {/* セグメントdiff一覧 */}
      <div data-testid="proofreading-diff">
        {segments.map(seg => {
          const hasLongLine = (seg.corrected || '').length > LINE_LIMIT;
          return (
            <div key={seg.id} data-testid={`proofread-segment-${seg.id}`}
              style={{ padding:'10px 12px', marginBottom:8, borderRadius:8, background:'var(--bg-secondary,#fff)', border:'1px solid var(--border-color,#e2e8f0)' }}>
              <div style={{ display:'flex', justifyContent:'space-between', marginBottom:6 }}>
                <span style={{ fontSize:'0.72rem', color:'#94a3b8', fontFamily:'monospace' }}>
                  {fmtTime(seg.start)} - {fmtTime(seg.end)}
                </span>
                <span data-testid={`segment-status-${seg.id}`} style={{
                  fontSize:'0.68rem', padding:'1px 8px', borderRadius:4, fontWeight:600,
                  background: seg.status==='approved' ? 'rgba(34,197,94,0.1)' : seg.status==='rejected' ? 'rgba(239,68,68,0.1)' : 'rgba(148,163,184,0.1)',
                  color: seg.status==='approved' ? '#16a34a' : seg.status==='rejected' ? '#dc2626' : '#64748b',
                }}>{seg.status === 'approved' ? '✓承認' : seg.status === 'rejected' ? '✗却下' : '保留'}</span>
              </div>
              {/* 比較ビュー */}
              <div data-testid="proofreading-comparison" style={{ display:'flex', gap:12, marginBottom:6 }}>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:'0.65rem', color:'#94a3b8', marginBottom:2 }}>修正前</div>
                  <div style={{ fontSize:'0.78rem', color:'#64748b', padding:'4px 8px', background:'rgba(239,68,68,0.04)', borderRadius:4, lineHeight:1.6 }}>
                    {seg.original}
                  </div>
                </div>
                <div style={{ flex:1 }}>
                  <div style={{ fontSize:'0.65rem', color:'#94a3b8', marginBottom:2 }}>修正後</div>
                  <div data-testid={`corrected-text-${seg.id}`} style={{
                    fontSize:'0.78rem', padding:'4px 8px', borderRadius:4, lineHeight:1.6,
                    background: hasLongLine ? 'rgba(234,179,8,0.08)' : 'rgba(34,197,94,0.04)',
                    color: 'var(--text-primary,#1e293b)',
                  }}>
                    {(seg.changes || []).map((ch, i) => (
                      <span key={i} data-testid={`diff-mark-${seg.id}-${i}`} style={{
                        background: ch.type==='replace' ? 'rgba(239,68,68,0.15)' : ch.type==='insert' ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.1)',
                        borderRadius: 2, padding: '0 2px',
                        color: ch.type==='replace' ? '#dc2626' : ch.type==='insert' ? '#16a34a' : '#dc2626',
                        fontWeight: 600, marginRight: 4,
                      }}>
                        {ch.type==='replace' ? `${ch.original}→${ch.corrected}` : ch.type==='insert' ? `+${ch.corrected}` : `-${ch.original}`}
                      </span>
                    ))}
                    <span style={{ marginLeft:4 }}>{seg.corrected}</span>
                  </div>
                </div>
              </div>
              {/* 行長警告 */}
              {hasLongLine && (
                <div data-testid={`line-length-warning-${seg.id}`} style={{
                  fontSize:'0.68rem', color:'#d97706', padding:'2px 8px', borderRadius:4,
                  background:'rgba(234,179,8,0.08)', marginBottom:4,
                }}>
                  ⚠️ 18文字超過: {(seg.corrected || '').length}文字
                </div>
              )}
              {/* 承認/却下ボタン */}
              <div style={{ display:'flex', gap:6 }}>
                <button data-testid={`segment-approve-btn-${seg.id}`} onClick={() => approveSegment(seg.id)}
                  disabled={seg.status === 'approved'}
                  style={{ padding:'3px 10px', borderRadius:6, border:'none', background: seg.status==='approved' ? '#d1d5db' : '#22c55e', color:'white', fontSize:'0.72rem', cursor: seg.status==='approved' ? 'default' : 'pointer' }}>
                  ✓ 承認
                </button>
                <button data-testid={`segment-reject-btn-${seg.id}`} onClick={() => rejectSegment(seg.id)}
                  disabled={seg.status === 'rejected'}
                  style={{ padding:'3px 10px', borderRadius:6, border:'none', background: seg.status==='rejected' ? '#d1d5db' : '#ef4444', color:'white', fontSize:'0.72rem', cursor: seg.status==='rejected' ? 'default' : 'pointer' }}>
                  ✗ 却下
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
export default ProofreadingStagePanel;
