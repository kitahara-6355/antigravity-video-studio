import React, { useState, useEffect, useCallback } from 'react';
const API_BASE = "http://localhost:8000";

const TranscriptionStagePanel = ({ stageData, isActive }) => {
  const [models, setModels] = useState([]);
  const [currentModel, setCurrentModel] = useState("medium");
  const [recommended, setRecommended] = useState("medium");
  const [segments, setSegments] = useState([]);
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [status, setStatus] = useState("idle");
  const [errorMessage, setErrorMessage] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState("");

  useEffect(() => {
    fetch(`${API_BASE}/api/pipeline/transcription/models`)
      .then(r => r.json())
      .then(data => {
        setModels(data.models || []);
        setRecommended(data.recommended || "medium");
        setCurrentModel(data.current || "medium");
      }).catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/pipeline/transcription/segments`)
      .then(r => r.json())
      .then(data => setSegments(data.segments || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const poll = setInterval(() => {
      fetch(`${API_BASE}/api/pipeline/transcription/status`)
        .then(r => r.json())
        .then(data => {
          setStatus(data.status); setProgress(data.progress);
          setElapsedSeconds(data.elapsed_seconds);
          if (data.error_message) setErrorMessage(data.error_message);
        }).catch(() => {});
    }, 2000);
    return () => clearInterval(poll);
  }, []);

  const handleModelChange = useCallback(async (modelId) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/transcription/model`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelId }),
      });
      if (res.ok) setCurrentModel(modelId);
    } catch {}
  }, []);

  const startEdit = (seg) => { setEditingId(seg.id); setEditText(seg.text); };

  const saveEdit = async (segId) => {
    try {
      const res = await fetch(`${API_BASE}/api/pipeline/transcription/segments/${segId}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: editText }),
      });
      if (res.ok) {
        setSegments(prev => prev.map(s => s.id === segId ? { ...s, text: editText } : s));
        setEditingId(null);
      }
    } catch {}
  };

  const fmtTime = (sec) => `${Math.floor(sec/60)}:${String(Math.floor(sec%60)).padStart(2,'0')}`;

  return (
    <div data-testid="transcription-stage-panel" style={{ background:'var(--bg-primary,#f8fafc)', borderRadius:12, padding:16, marginTop:12 }}>
      <div style={{ display:'flex', alignItems:'center', gap:12, marginBottom:16 }}>
        <label style={{ fontSize:'0.82rem', fontWeight:600 }}>🎤 Whisperモデル:</label>
        <select data-testid="whisper-model-select" value={currentModel}
          onChange={(e) => handleModelChange(e.target.value)}
          style={{ padding:'6px 12px', borderRadius:8, border:'1px solid var(--border-color,#e2e8f0)', fontSize:'0.82rem', cursor:'pointer' }}>
          {models.map(m => (
            <option key={m.id} value={m.id}>{m.name} ({m.accuracy}) — VRAM {m.vram_gb}GB{m.id === recommended ? ' ★推奨' : ''}</option>
          ))}
        </select>
        {recommended && <span data-testid="whisper-recommended" style={{ fontSize:'0.72rem', padding:'2px 8px', borderRadius:6, background:'rgba(34,197,94,0.1)', color:'#16a34a', fontWeight:600 }}>推奨: {recommended}</span>}
      </div>

      <div data-testid="transcription-progress" style={{ marginBottom:16 }}>
        <div style={{ display:'flex', justifyContent:'space-between', marginBottom:4 }}>
          <span style={{ fontSize:'0.78rem' }}>{status === 'running' ? '文字起こし中...' : status === 'completed' ? '完了' : '待機中'}</span>
          <span data-testid="transcription-elapsed" style={{ fontSize:'0.78rem' }}>経過: {fmtTime(elapsedSeconds)}</span>
        </div>
        <div style={{ height:6, borderRadius:3, background:'#e2e8f0', overflow:'hidden' }}>
          <div data-testid="transcription-progress-bar" style={{ height:'100%', background:'linear-gradient(90deg,#8b5cf6,#6d28d9)', width:`${progress}%`, transition:'width 0.5s' }} />
        </div>
        <span data-testid="transcription-progress-text" style={{ fontSize:'0.72rem' }}>{progress}%</span>
      </div>

      {errorMessage && (
        <div data-testid="transcription-error" style={{ padding:'10px 14px', marginBottom:12, background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.3)', borderRadius:8, fontSize:'0.82rem', color:'#dc2626' }}>
          ⚠️ {errorMessage}
        </div>
      )}

      <div data-testid="segment-list" style={{ maxHeight:400, overflowY:'auto' }}>
        <div style={{ fontSize:'0.78rem', fontWeight:600, marginBottom:8 }}>セグメント一覧 ({segments.length}件)</div>
        {segments.map(seg => (
          <div key={seg.id} data-testid={`segment-item-${seg.id}`} style={{ display:'flex', gap:8, padding:'8px 10px', borderRadius:8, marginBottom:4, borderLeft:'3px solid', borderLeftColor: seg.speaker_id==='speaker_0'?'#8b5cf6':'#3b82f6' }}>
            <div data-testid={`segment-timestamp-${seg.id}`} style={{ minWidth:90, fontSize:'0.72rem', fontFamily:'monospace', color:'#94a3b8' }}>
              {fmtTime(seg.start)} - {fmtTime(seg.end)}
            </div>
            <div data-testid={`speaker-id-${seg.id}`} style={{ minWidth:24, fontSize:'0.65rem', fontWeight:700, color:seg.speaker_id==='speaker_0'?'#8b5cf6':'#3b82f6' }}>
              {seg.speaker_id ? seg.speaker_id.replace('speaker_','S') : ''}
            </div>
            <div style={{ flex:1 }}>
              {editingId === seg.id ? (
                <div style={{ display:'flex', gap:6 }}>
                  <input data-testid="segment-edit-input" type="text" value={editText}
                    onChange={(e) => setEditText(e.target.value)}
                    onKeyDown={(e) => { if(e.key==='Enter') saveEdit(seg.id); if(e.key==='Escape') setEditingId(null); }}
                    autoFocus style={{ flex:1, padding:'4px 8px', borderRadius:6, border:'1px solid #8b5cf6', fontSize:'0.82rem' }} />
                  <button data-testid="segment-edit-save" onClick={() => saveEdit(seg.id)}
                    style={{ padding:'2px 10px', borderRadius:6, border:'none', background:'#8b5cf6', color:'white', fontSize:'0.72rem', cursor:'pointer' }}>保存</button>
                </div>
              ) : (
                <span data-testid={`segment-text-${seg.id}`} onClick={() => startEdit(seg)}
                  style={{ fontSize:'0.82rem', cursor:'pointer' }} title="クリックして編集">{seg.text}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
export default TranscriptionStagePanel;
