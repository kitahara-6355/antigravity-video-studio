import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import TranscriptionStagePanel from './TranscriptionStagePanel';
import ProofreadingStagePanel from './ProofreadingStagePanel';
import SmartCutPanel from './SmartCutPanel';
import QualityGate from './QualityGate';
import AISuggestionCard from './AISuggestionCard';
import YouTubeOptimizerPanel from './YouTubeOptimizerPanel';
import './ProductionPipeline.css';
import { apiFetch, apiSocket, apiUrl, openApiUrl } from '../gateway/client.js';

const POLL_INTERVAL = 5000; // WebSocket接続時はフォールバック用（5秒に延長）
const POLL_INTERVAL_NO_WS = 2000; // WebSocket未接続時は2秒ポーリング

export default function ProductionPipeline({ onClose, onWizardStart }) {
  const [videos, setVideos] = useState([]);
  const [selectedVideos, setSelectedVideos] = useState([]); // 複数選択対応
  const [targetMinutes, setTargetMinutes] = useState(20);
  const [pipelineStatus, setPipelineStatus] = useState(null);
  const [expandedFolders, setExpandedFolders] = useState({});
  const [loading, setLoading] = useState(false);
  const [templateSelected, setTemplateSelected] = useState(null); // null=未確認, true/false
  const [wsConnected, setWsConnected] = useState(false); // WebSocket接続状態
  const [videoMetadata, setVideoMetadata] = useState({}); // path -> metadata
  const [recentVideos, setRecentVideos] = useState([]); // 最近使用した素材
  const [validationErrors, setValidationErrors] = useState({}); // path -> errors
  const [showQualityGate, setShowQualityGate] = useState(false); // O-6: 品質ゲートモーダル
  const [qualityGateData, setQualityGateData] = useState(null); // O-6: 品質ゲートデータ
  const [showSmartCut, setShowSmartCut] = useState(false); // O-4: SmartCutパネル
  const pollingRef = useRef(null);
  const wsRef = useRef(null);
  const wsReconnectTimer = useRef(null);

  // ━━━ O1-CF-05: 最近使用した素材の履歴をlocalStorageから読み込み ━━━
  useEffect(() => {
    try {
      const saved = localStorage.getItem('pipeline_recent_videos');
      if (saved) setRecentVideos(JSON.parse(saved));
    } catch { /* ignore */ }
  }, []);

  const addToRecentVideos = useCallback((videoList) => {
    setRecentVideos(prev => {
      const paths = new Set(videoList.map(v => v.path));
      const updated = [
        ...videoList.map(v => ({ ...v, usedAt: new Date().toISOString() })),
        ...prev.filter(v => !paths.has(v.path)),
      ].slice(0, 20);
      try { localStorage.setItem('pipeline_recent_videos', JSON.stringify(updated)); } catch {}
      return updated;
    });
  }, []);

  // ━━━ O1-CF-02: メタデータ取得 ━━━
  const fetchMetadata = useCallback(async (video) => {
    if (videoMetadata[video.path]) return;
    try {
      const res = await apiFetch('postPipelineVideosMetadata', { body: { video_path: video.path } });
      if (res.ok) {
        const data = await res.json();
        setVideoMetadata(prev => ({ ...prev, [video.path]: data }));
      }
    } catch { /* silent */ }
  }, [videoMetadata]);

  // ━━━ O1-CF-04: ドラッグ&ドロップ ━━━
  const onDrop = useCallback((acceptedFiles) => {
    const newVideos = acceptedFiles
      .filter(f => /\.(mp4|mov|mkv|avi)$/i.test(f.name))
      .map(f => ({
        path: f.path || f.name,
        name: f.name,
        size_mb: Math.round(f.size / 1024 / 1024 * 10) / 10,
        folder: 'ドロップされたファイル',
        dropped: true,
      }));
    if (newVideos.length > 0) {
      setSelectedVideos(prev => [
        ...prev,
        ...newVideos.filter(nv => !prev.some(sv => sv.path === nv.path)),
      ]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    noClick: true,
    accept: { 'video/*': ['.mp4', '.mov', '.mkv', '.avi'] },
  });

  // ━━━ R-1: WebSocket接続 — リアルタイム進捗表示 ━━━
  useEffect(() => {
    let mounted = true;
    let reconnectAttempt = 0;
    const MAX_RECONNECT = 10;
    const RECONNECT_BASE_MS = 1000;

    const connectWebSocket = () => {
      if (!mounted) return;
      try {
        const ws = apiSocket('wsPipeline');
        wsRef.current = ws;

        ws.onopen = () => {
          if (!mounted) return;
          console.log("[Pipeline WS] Connected");
          setWsConnected(true);
          reconnectAttempt = 0;
        };

        ws.onmessage = (event) => {
          if (!mounted) return;
          try {
            const data = JSON.parse(event.data);
            // WebSocketメッセージ種別に応じてステータスを更新
            if (data.type === "pipeline_start") {
              // パイプライン開始 → ステータスをポーリングで取得
              apiFetch('getPipelineStatus')
                .then(r => r.json())
                .then(s => mounted && setPipelineStatus(s))
                .catch(() => {});
            } else if (data.type === "pipeline_complete") {
              // パイプライン完了 → 結果を反映
              if (data.result) {
                setPipelineStatus(prev => ({
                  ...prev,
                  status: data.status || "completed",
                  result: data.result,
                  completed_at: new Date().toISOString(),
                }));
              } else {
                // 結果が無い場合はステータスを取得
                apiFetch('getPipelineStatus')
                  .then(r => r.json())
                  .then(s => mounted && setPipelineStatus(s))
                  .catch(() => {});
              }
            } else if (data.type === "stage_update") {
              // ステージ更新 → 個別ステージを更新
              setPipelineStatus(prev => {
                if (!prev || !prev.stages) return prev;
                const stages = [...prev.stages];
                const idx = data.stage_index ?? data.index;
                if (idx != null && idx >= 0 && idx < stages.length) {
                  stages[idx] = {
                    ...stages[idx],
                    status: data.status || stages[idx].status,
                    detail: data.detail || stages[idx].detail,
                    progress: data.progress ?? stages[idx].progress,
                    data: data.data || stages[idx].data,
                  };
                }
                return { ...prev, stages, current_stage: idx ?? prev.current_stage };
              });
            } else if (data.type === "quality_gate_blocked") {
              // 品質ゲートブロック通知
              setPipelineStatus(prev => ({
                ...prev,
                quality_blocked: true,
                quality_score: data.score,
                quality_feedback: data.feedback,
              }));
            } else if (data.type === "force_render_complete") {
              // 強制レンダリング完了
              setPipelineStatus(prev => ({
                ...prev,
                result: {
                  ...prev?.result,
                  final_path: data.final_path,
                  force_rendered: true,
                },
              }));
            }
          } catch (e) {
            console.warn("[Pipeline WS] Parse error:", e);
          }
        };

        ws.onclose = (event) => {
          if (!mounted) return;
          console.log(`[Pipeline WS] Closed (code=${event.code})`);
          setWsConnected(false);
          wsRef.current = null;
          // 自動再接続（指数バックオフ）
          if (reconnectAttempt < MAX_RECONNECT) {
            const delay = RECONNECT_BASE_MS * Math.pow(1.5, reconnectAttempt);
            reconnectAttempt++;
            console.log(`[Pipeline WS] Reconnecting in ${Math.round(delay)}ms (attempt ${reconnectAttempt}/${MAX_RECONNECT})`);
            wsReconnectTimer.current = setTimeout(connectWebSocket, delay);
          }
        };

        ws.onerror = () => {
          // onclose will fire after onerror, so reconnection is handled there
        };
      } catch (e) {
        console.warn("[Pipeline WS] Connection failed:", e);
        setWsConnected(false);
      }
    };

    connectWebSocket();

    return () => {
      mounted = false;
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (wsReconnectTimer.current) {
        clearTimeout(wsReconnectTimer.current);
      }
    };
  }, []);

  // ━━━ UX-6: テンプレート選択状態を確認 ━━━
  useEffect(() => {
    apiFetch('getV1ThemesCurrentActive')
      .then(res => res.json())
      .then(data => setTemplateSelected(!!data.template))
      .catch(() => setTemplateSelected(false));
  }, []);

  // 動画リスト取得
  useEffect(() => {
    apiFetch('getPipelineVideos')
      .then(res => res.json())
      .then(data => {
        setVideos(data.videos || []);
        const folders = {};
        (data.videos || []).forEach(v => { folders[v.folder] = true; });
        setExpandedFolders(folders);
      })
      .catch(err => console.error("Failed to load videos:", err));
  }, []);

  // 起動時にステータスを取得（再開対応）
  useEffect(() => {
    apiFetch('getPipelineStatus')
      .then(res => res.json())
      .then(data => {
        if (data.status !== "idle") {
          setPipelineStatus(data);
        }
      })
      .catch(() => {});
  }, []);

  // ポーリング（WebSocket接続時は低頻度フォールバック、未接続時は高頻度）
  useEffect(() => {
    if (pipelineStatus?.status === "running") {
      const interval = wsConnected ? POLL_INTERVAL : POLL_INTERVAL_NO_WS;
      pollingRef.current = setInterval(() => {
        apiFetch('getPipelineStatus')
          .then(res => res.json())
          .then(data => setPipelineStatus(data))
          .catch(() => {});
      }, interval);
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [pipelineStatus?.status, wsConnected]);

  // ━━━ UX-4修正: エラーメッセージ日本語化 ━━━
  const friendlyError = (detail) => {
    if (!detail) return "不明なエラーが発生しました";
    if (detail.includes("Internal")) return "サーバー内部エラー。管理者にお知らせください。";
    if (detail.includes("Not Found")) return "指定されたファイルが見つかりません。";
    if (detail.includes("quota")) return "API使用量の上限に達しました。しばらく待ってください。";
    if (detail.includes("timeout")) return "処理がタイムアウトしました。もう一度お試しください。";
    return detail;
  };

  // パイプライン起動（複数動画対応）
  const handleStart = useCallback(async () => {
    if (selectedVideos.length === 0) return;

    // ━━━ UX-2修正: テンプレート選択チェック（警告バナーのみ、ブロックしない） ━━━
    try {
      const tmplCheck = await apiFetch('getV1ThemesCurrentActive');
      const tmplData = await tmplCheck.json();
      setTemplateSelected(!!tmplData.template);
    } catch {}

    // ━━━ O1-CF-03: バリデーション ━━━
    try {
      const valRes = await apiFetch('postPipelineVideosValidate', { body: { video_paths: selectedVideos.map(v => v.path) } });
      if (valRes.ok) {
        const valData = await valRes.json();
        const errs = {};
        valData.results.forEach(r => { if (!r.valid) errs[r.path] = r.errors; });
        setValidationErrors(errs);
        if (valData.invalid > 0) {
          const names = valData.results.filter(r => !r.valid).map(r => r.name).join(', ');
          if (!confirm(`以下のファイルに問題があります:\n${names}\n\n続行しますか？`)) return;
        }
      }
    } catch {}

    // ━━━ O1-CF-05: 履歴記録 ━━━
    addToRecentVideos(selectedVideos);

    setLoading(true);
    try {
      const res = await apiFetch('postPipelineStart', { body: {
          video_paths: selectedVideos.map(v => v.path),
          target_minutes: targetMinutes,
        } });
      const data = await res.json();
      if (res.ok) {
        const statusRes = await apiFetch('getPipelineStatus');
        setPipelineStatus(await statusRes.json());
      } else {
        alert(friendlyError(data.detail));
      }
    } catch (err) {
      alert("サーバーに接続できません。バックエンドが起動しているか確認してください。");
    } finally {
      setLoading(false);
    }
  }, [selectedVideos, targetMinutes, addToRecentVideos]);

  // フォルダ展開/折りたたみ
  const toggleFolder = (folder) => {
    setExpandedFolders(prev => ({ ...prev, [folder]: !prev[folder] }));
  };

  // フォルダ全選択/全解除
  const toggleFolderSelection = (folder, items) => {
    const folderPaths = items.map(v => v.path);
    const allSelected = folderPaths.every(p => selectedVideos.some(sv => sv.path === p));
    
    if (allSelected) {
      // 全解除
      setSelectedVideos(prev => prev.filter(sv => !folderPaths.includes(sv.path)));
    } else {
      // 全選択（すでに選択済みのものを除いて追加）
      const newVideos = items.filter(v => !selectedVideos.some(sv => sv.path === v.path));
      setSelectedVideos(prev => [...prev, ...newVideos]);
    }
  };

  // 個別動画のトグル選択
  const toggleVideoSelection = (video) => {
    setSelectedVideos(prev => {
      const exists = prev.some(sv => sv.path === video.path);
      if (exists) {
        return prev.filter(sv => sv.path !== video.path);
      } else {
        fetchMetadata(video);
        return [...prev, video];
      }
    });
  };

  // 動画をフォルダ別にグループ化
  const groupedVideos = {};
  videos.forEach(v => {
    if (!groupedVideos[v.folder]) groupedVideos[v.folder] = [];
    groupedVideos[v.folder].push(v);
  });

  // ファイルサイズフォーマット
  const formatSize = (mb) => {
    if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
    return `${mb.toFixed(0)} MB`;
  };

  // フォルダ内の全動画が選択済みか？
  const isFolderSelected = (items) => {
    return items.every(v => selectedVideos.some(sv => sv.path === v.path));
  };

  // フォルダ内の一部が選択済みか？
  const isFolderPartial = (items) => {
    const count = items.filter(v => selectedVideos.some(sv => sv.path === v.path)).length;
    return count > 0 && count < items.length;
  };

  // 合計サイズ
  const totalSelectedSize = selectedVideos.reduce((sum, v) => sum + v.size_mb, 0);

  const isRunning = pipelineStatus?.status === "running";
  const isCompleted = pipelineStatus?.status === "completed";
  const hasError = pipelineStatus?.status === "error";

  return (
    <div className="pipeline-overlay" onClick={(e) => { if (e.target === e.currentTarget && !isRunning) onClose(); }}>
      <div className="pipeline-modal">
        {/* Header */}
        <div className="pipeline-header">
          <h2>
            🎬 制作パイプライン
            {isRunning && <span className="pipeline-status-badge running"><span className="pipeline-spinner" /> 実行中</span>}
            {isCompleted && <span className="pipeline-status-badge completed">✅ 完了</span>}
            {hasError && <span className="pipeline-status-badge error">❌ エラー</span>}
            {isRunning && (
              <span
                title={wsConnected ? "リアルタイム更新中 (WebSocket)" : "ポーリング更新中 (2秒間隔)"}
                style={{
                  display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                  background: wsConnected ? '#22c55e' : '#eab308',
                  marginLeft: 8, verticalAlign: 'middle',
                  boxShadow: wsConnected ? '0 0 6px rgba(34,197,94,0.6)' : '0 0 6px rgba(234,179,8,0.4)',
                  animation: wsConnected ? 'none' : 'pulse 2s infinite',
                }}
              />
            )}
          </h2>
          <button className="pipeline-close-btn" onClick={onClose} disabled={isRunning}>
            ✕ 閉じる
          </button>
        </div>

        {/* ━━━ UX-6: テンプレート未選択ガイド ━━━ */}
        {templateSelected === false && !isRunning && (
          <div className="pipeline-template-guide">
            <span>💡</span>
            <div>
              <strong>テンプレートが未選択です</strong>
              <p>テンプレートを選ぶと、プロ品質の字幕ルール・カラーグレーディング・品質チェックが自動適用されます。左メニューの「🎨 テーマ設定」から選択してください。</p>
            </div>
          </div>
        )}

        <div className="pipeline-body" {...getRootProps()} data-testid="pipeline-drop-zone">
          <input {...getInputProps()} />
          {/* D&D オーバーレイ */}
          {isDragActive && (
            <div style={{
              position: 'absolute', inset: 0, zIndex: 100,
              background: 'rgba(139,92,246,0.15)', border: '3px dashed var(--accent-primary)',
              borderRadius: 16, display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '1.2rem', fontWeight: 700, color: 'var(--accent-primary)',
            }}>
              📂 ここにドロップして素材を追加
            </div>
          )}

          {/* 動画選択（パイプライン未実行時のみ表示） */}
          {!pipelineStatus || pipelineStatus.status === "idle" ? (
            <>
              <div className="pipeline-video-selector">
                <h3>📁 RAW動画を選択 <span style={{ fontSize: '0.75rem', color: 'var(--text-light)', fontWeight: 400 }}>フォルダクリックで一括選択 / ドラッグ&amp;ドロップ対応</span></h3>
                <div className="pipeline-video-list" data-testid="video-file-browser">
                  {Object.entries(groupedVideos).map(([folder, items]) => {
                    const folderSel = isFolderSelected(items);
                    const folderPartial = isFolderPartial(items);
                    return (
                      <div key={folder}>
                        <div
                          className={`pipeline-video-item ${folderSel ? 'selected' : ''}`}
                          style={{ 
                            background: folderSel ? 'rgba(139, 92, 246, 0.12)' : 'var(--bg-secondary)', 
                            fontWeight: 600, 
                            fontSize: '0.85rem',
                            cursor: 'pointer',
                          }}
                        >
                          <span 
                            onClick={() => toggleFolder(folder)}
                            style={{ flex: 1 }}
                          >
                            {expandedFolders[folder] ? '📂' : '📁'} {folder}
                          </span>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-light)' }}>
                              {items.length}件
                            </span>
                            <button
                              onClick={(e) => { e.stopPropagation(); toggleFolderSelection(folder, items); }}
                              style={{
                                background: folderSel ? 'var(--accent-primary)' : folderPartial ? 'rgba(139,92,246,0.3)' : 'var(--bg-primary)',
                                color: folderSel ? 'white' : 'var(--text-secondary)',
                                border: `1px solid ${folderSel ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                                borderRadius: 6, padding: '2px 10px', fontSize: '0.72rem', cursor: 'pointer',
                                fontWeight: 600,
                              }}
                            >
                              {folderSel ? '✓ 全選択' : '全選択'}
                            </button>
                          </div>
                        </div>
                        {expandedFolders[folder] && items.map((v, i) => {
                          const isSelected = selectedVideos.some(sv => sv.path === v.path);
                          const meta = videoMetadata[v.path];
                          const hasValErr = validationErrors[v.path];
                          return (
                            <div
                              key={`${folder}-${i}`}
                              className={`pipeline-video-item ${isSelected ? 'selected' : ''} ${hasValErr ? 'validation-error' : ''}`}
                              onClick={() => toggleVideoSelection(v)}
                              style={{ paddingLeft: 32 }}
                              data-testid={`video-item-${v.name}`}
                            >
                              <span className="pipeline-video-name">
                                {isSelected ? '☑' : '☐'} 🎥 {v.name}
                              </span>
                              <div className="pipeline-video-meta" data-testid={`video-meta-${v.name}`}>
                                <span>{formatSize(v.size_mb)}</span>
                                {meta?.probe_success && (
                                  <>
                                    <span style={{ color: 'var(--text-light)', fontSize: '0.72rem' }}>
                                      {meta.duration_display}
                                    </span>
                                    <span style={{ color: 'var(--text-light)', fontSize: '0.72rem' }}>
                                      {meta.resolution}
                                    </span>
                                    <span style={{ color: 'var(--text-light)', fontSize: '0.72rem' }}>
                                      {meta.video_codec}
                                    </span>
                                  </>
                                )}
                              </div>
                              {hasValErr && (
                                <div style={{ fontSize: '0.7rem', color: '#ef4444', marginTop: 2 }}>
                                  ⚠️ {validationErrors[v.path][0]}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    );
                  })}
                  {videos.length === 0 && (
                    <div data-testid="empty-video-message" style={{ padding: 20, textAlign: 'center', color: 'var(--text-light)' }}>
                      📭 動画が見つかりません。vault-assets/raw_videos/ にファイルを配置するか、ここにドラッグ&ドロップしてください。
                    </div>
                  )}
                </div>
              </div>

              {/* ━━━ O1-CF-05: 最近使用した素材の履歴 ━━━ */}
              {recentVideos.length > 0 && videos.length > 0 && (
                <div data-testid="recent-videos-section" style={{
                  marginBottom: 12, padding: '8px 12px',
                  background: 'var(--bg-primary)', borderRadius: 8,
                  fontSize: '0.78rem', color: 'var(--text-secondary)',
                }}>
                  <strong>🕐 最近使用した素材</strong>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                    {recentVideos.slice(0, 5).map((rv, i) => (
                      <button key={i}
                        onClick={() => {
                          const found = videos.find(v => v.path === rv.path);
                          if (found && !selectedVideos.some(sv => sv.path === found.path)) {
                            toggleVideoSelection(found);
                          }
                        }}
                        style={{
                          background: selectedVideos.some(sv => sv.path === rv.path)
                            ? 'rgba(139,92,246,0.15)' : 'var(--bg-secondary)',
                          border: '1px solid var(--border-color)', borderRadius: 6,
                          padding: '2px 8px', fontSize: '0.72rem', cursor: 'pointer',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        🎥 {rv.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* 選択状況サマリ */}
              {selectedVideos.length > 0 && (
                <div style={{ 
                  fontSize: '0.82rem', color: 'var(--accent-primary)', fontWeight: 600,
                  marginBottom: 12, padding: '6px 12px',
                  background: 'rgba(139,92,246,0.06)', borderRadius: 8 
                }}>
                  📹 {selectedVideos.length}本選択中 ({formatSize(totalSelectedSize)})
                  {selectedVideos.length > 1 && ' — 結合して処理されます'}
                </div>
              )}

              <div className="pipeline-controls">
                <div className="pipeline-target-input">
                  <span>目標尺:</span>
                  <input
                    type="number"
                    value={targetMinutes}
                    onChange={e => setTargetMinutes(Number(e.target.value))}
                    min={1}
                    max={120}
                  />
                  <span>分</span>
                </div>
                <button
                  className="pipeline-start-btn"
                  onClick={handleStart}
                  disabled={selectedVideos.length === 0 || loading}
                >
                  {loading ? <span className="pipeline-spinner" /> : '▶'}
                  パイプライン開始 {selectedVideos.length > 0 ? `(${selectedVideos.length}本)` : ''}
                </button>
              </div>
            </>
          ) : null}

          {/* ステージ進捗（パイプライン実行中/完了時） */}
          {pipelineStatus && pipelineStatus.status !== "idle" && (
            <>
              {pipelineStatus.video_path && (
                <div style={{ 
                  fontSize: '0.82rem', color: 'var(--text-secondary)', 
                  marginBottom: 16, padding: '8px 12px',
                  background: 'var(--bg-primary)', borderRadius: 8 
                }}>
                  📹 {pipelineStatus.video_path.split('\\').pop()} — 目標 {pipelineStatus.target_minutes}分
                  {pipelineStatus.video_count > 1 && ` (${pipelineStatus.video_count}本結合)`}
                </div>
              )}

              <div className="pipeline-stages">
                <h3>ステージ進捗</h3>
                {pipelineStatus.stages.map((stage, i) => (
                  <div key={i} className={`pipeline-stage ${stage.status}`}>
                    <div className="pipeline-stage-icon">
                      {stage.status === "completed" ? "✓" : 
                       stage.status === "running" ? <span className="pipeline-spinner" /> :
                       stage.status === "error" ? "✗" : stage.icon}
                    </div>
                    <div className="pipeline-stage-content">
                      <div className="pipeline-stage-name">
                        {stage.icon} {stage.name}
                        {/* 使用モデルバッジ（AI校閲/YouTube最適化など） */}
                        {stage.data?.model_used && (
                          <span style={{
                            marginLeft: 8, fontSize: '0.65rem', padding: '1px 7px',
                            borderRadius: 6, fontWeight: 600, letterSpacing: '-0.02em',
                            background: stage.data.model_used.includes('3-flash') 
                              ? 'rgba(255,215,0,0.15)' 
                              : stage.data.model_used.includes('2.5-flash-lite')
                                ? 'rgba(100,149,237,0.15)'
                                : 'rgba(139,92,246,0.12)',
                            color: stage.data.model_used.includes('3-flash')
                              ? '#b8860b'
                              : stage.data.model_used.includes('2.5-flash-lite')
                                ? '#4169e1'
                                : '#7c3aed',
                            border: `1px solid ${stage.data.model_used.includes('3-flash')
                              ? 'rgba(255,215,0,0.3)'
                              : stage.data.model_used.includes('2.5-flash-lite')
                                ? 'rgba(100,149,237,0.3)'
                                : 'rgba(139,92,246,0.2)'}`,
                          }}>
                            {stage.data.model_used.includes('3-flash') ? '⭐ Premium'
                              : stage.data.model_used.includes('2.5-flash-lite') ? '📦 Batch'
                              : stage.data.model_used.includes('2.5-flash') ? '🔷 Standard'
                              : stage.data.model_used.split('/').pop()}
                          </span>
                        )}
                      </div>
                      {stage.detail && (
                        <div className="pipeline-stage-detail">{stage.detail.replace(/seg$/g, '箇所').replace(/(\d+)seg/g, '$1箇所')}</div>
                      )}
                      {stage.status === "running" && stage.progress >= 0 && (
                        <div className="pipeline-progress-bar-container">
                          <div className="pipeline-progress-bar" style={{ width: `${stage.progress}%` }} />
                          <span className="pipeline-progress-text">{stage.progress}%</span>
                        </div>
                      )}
                    </div>
                    {/* O-2: 文字起こしステージパネル */}
                    {i === 0 && (stage.status === "running" || stage.status === "completed") && (
                      <TranscriptionStagePanel stageData={stage.data} isActive={stage.status === "running"} />
                    )}
                    {/* O-3: AI校閲ステージパネル */}
                    {i === 1 && (stage.status === "running" || stage.status === "completed") && (
                      <ProofreadingStagePanel stageData={stage.data} isActive={stage.status === "running"} />
                    )}
                    {/* O-4: SmartCut構成パネル */}
                    {i === 2 && (stage.status === "running" || stage.status === "completed") && (
                      <div
                        data-testid="smartcut-stage-panel"
                        style={{ marginTop: 8, padding: '8px 0' }}
                      >
                        <button
                          data-testid="open-smartcut-btn"
                          onClick={() => setShowSmartCut(true)}
                          style={{
                            background: 'linear-gradient(135deg, #f472b6, #c084fc)',
                            color: 'white', border: 'none', borderRadius: 8,
                            padding: '8px 16px', fontSize: '0.8rem',
                            cursor: 'pointer', fontWeight: 600,
                            boxShadow: '0 2px 8px rgba(244,114,182,0.3)',
                          }}
                        >
                          ✂️ SmartCut構成を開く
                        </button>
                      </div>
                    )}
                    {/* O-9: YouTube最適化パネル */}
                    {i === 4 && (stage.status === "running" || stage.status === "completed") && (
                      <div
                        data-testid="youtube-optimizer-stage"
                        style={{ marginTop: 8, padding: '4px 0', fontSize: '0.75rem', color: 'var(--text-secondary)' }}
                      >
                        {stage.status === "completed" && stage.data?.titles && (
                          <span>🎯 タイトル案: {stage.data.titles[0]}</span>
                        )}
                      </div>
                    )}
                    {/* O-6: 品質チェックパネル */}
                    {i === 5 && (stage.status === "running" || stage.status === "completed") && (
                      <div
                        data-testid="quality-gate-stage-panel"
                        style={{ marginTop: 8, padding: '8px 0' }}
                      >
                        {stage.status === "completed" && (
                          <button
                            data-testid="open-quality-gate-btn"
                            onClick={async () => {
                              try {
                                const [statusRes, improveRes] = await Promise.all([
                                  apiFetch('getPipelineQualityGateStatus'),
                                  apiFetch('postPipelineQualityGateImprove'),
                                ]);
                                const statusData = statusRes.ok ? await statusRes.json() : {};
                                const improveData = improveRes.ok ? await improveRes.json() : {};
                                setQualityGateData({
                                  is_ready: statusData.passed ?? statusData.overall_score >= 90,
                                  score: statusData.overall_score ?? stage.data?.quality_score ?? 0,
                                  critical_issues: (improveData.suggestions || [])
                                    .filter(s => s.severity === 'critical')
                                    .map(s => s.suggestion),
                                  suggestions: (improveData.suggestions || [])
                                    .filter(s => s.severity !== 'critical')
                                    .map(s => ({
                                      id: s.id || `sug-${Math.random().toString(36).substr(2,6)}`,
                                      text: s.suggestion,
                                      category: s.category,
                                      priority: s.severity || s.priority || 'medium',
                                      estimated_improvement: s.estimated_improvement || '+3-5点',
                                    })),
                                  final_verdict: statusData.passed
                                    ? '品質基準を満たしています。レンダリングに進めます。'
                                    : '品質基準未達です。AI改善提案を確認してください。',
                                });
                                setShowQualityGate(true);
                              } catch (err) {
                                console.error('Quality gate fetch failed:', err);
                                setQualityGateData({
                                  is_ready: false, score: 0,
                                  critical_issues: [], suggestions: [],
                                  final_verdict: '品質データの取得に失敗しました',
                                });
                                setShowQualityGate(true);
                              }
                            }}
                            style={{
                              background: 'linear-gradient(135deg, #10b981, #059669)',
                              color: 'white', border: 'none', borderRadius: 8,
                              padding: '8px 16px', fontSize: '0.8rem',
                              cursor: 'pointer', fontWeight: 600,
                              boxShadow: '0 2px 8px rgba(16,185,129,0.3)',
                            }}
                          >
                            🛡️ 品質レポートを確認
                          </button>
                        )}
                        {stage.status === "running" && (
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                            品質スコアを計算中...
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              {/* 完了結果 */}
              {isCompleted && pipelineStatus.result && (
                <div className="pipeline-result">
                  <h3>🎉 パイプライン完了</h3>
                  
                  {/* 品質スコアバッジ */}
                  {pipelineStatus.result.quality_details && (
                    <div className="pipeline-quality-badge" style={{
                      display: 'flex', alignItems: 'center', gap: 16,
                      padding: '12px 16px', marginBottom: 16,
                      background: pipelineStatus.result.quality_score >= 90 
                        ? 'rgba(34,197,94,0.08)' 
                        : pipelineStatus.result.quality_score >= 80 
                          ? 'rgba(234,179,8,0.08)' 
                          : 'rgba(239,68,68,0.08)',
                      border: `1px solid ${pipelineStatus.result.quality_score >= 90 
                        ? 'rgba(34,197,94,0.3)' 
                        : pipelineStatus.result.quality_score >= 80 
                          ? 'rgba(234,179,8,0.3)' 
                          : 'rgba(239,68,68,0.3)'}`,
                      borderRadius: 12,
                    }}>
                      <div style={{ 
                        fontSize: '2rem', fontWeight: 800, 
                        color: pipelineStatus.result.quality_score >= 90 ? '#22c55e' 
                          : pipelineStatus.result.quality_score >= 80 ? '#eab308' : '#ef4444',
                        lineHeight: 1,
                      }}>
                        {pipelineStatus.result.quality_score}<span style={{ fontSize: '0.9rem' }}>点</span>
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                          品質ゲート {pipelineStatus.result.quality_score >= 80 ? '✅ 合格' : '❌ 不合格'}
                        </div>
                        {/* カテゴリ別ミニバー */}
                        <div style={{ display: 'flex', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                          {(pipelineStatus.result.quality_details.category_report || [])
                            .filter(c => c.score !== null)
                            .map((cat, i) => (
                            <span key={i} style={{
                              fontSize: '0.72rem', padding: '2px 8px',
                              background: cat.score >= 95 ? 'rgba(34,197,94,0.15)' 
                                : cat.score >= 80 ? 'rgba(234,179,8,0.15)' 
                                : 'rgba(239,68,68,0.15)',
                              borderRadius: 6, color: 'var(--text-secondary)',
                            }}>
                              {cat.label} {cat.score}
                            </span>
                          ))}
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          const details = pipelineStatus.result.quality_details;
                          const cats = details?.category_report || [];
                          const fb = details?.feedback || [];
                          const lines = [
                            `品質スコア: ${pipelineStatus.result.quality_score}点 (${pipelineStatus.result.quality_rank})`,
                            '',
                            ...cats.map(c => `${c.label}: ${c.score}点`),
                            '',
                            ...(fb.length > 0 ? ['改善提案:', ...fb.map(f => `  ⚠️ ${f}`)] : ['改善提案なし']),
                          ];
                          alert(lines.join('\n'));
                        }}
                        style={{
                          fontSize: '0.78rem', color: 'var(--accent-primary)',
                          background: 'transparent', padding: '4px 10px',
                          border: '1px solid var(--accent-primary)',
                          borderRadius: 6, whiteSpace: 'nowrap', cursor: 'pointer',
                        }}
                      >
                        📊 詳細レポート
                      </button>
                    </div>
                  )}

                  {/* フィードバック */}
                  {pipelineStatus.result.quality_details?.feedback?.length > 0 && (
                    <div style={{
                      padding: '8px 12px', marginBottom: 12,
                      background: 'rgba(234,179,8,0.06)', borderRadius: 8,
                      fontSize: '0.78rem', color: 'var(--text-secondary)',
                    }}>
                      {pipelineStatus.result.quality_details.feedback.map((fb, i) => (
                        <div key={i} style={{ padding: '2px 0' }}>⚠️ {fb}</div>
                      ))}
                    </div>
                  )}

                  {/* プレビュー動画プレーヤー */}
                  <div style={{
                    marginBottom: 16, borderRadius: 12, overflow: 'hidden',
                    background: '#000', border: '1px solid var(--border-color)',
                  }}>
                    <video
                      controls
                      style={{ width: '100%', maxHeight: 360, display: 'block' }}
                      src={apiUrl('getPipelineStream', { params: { video_type: 'preview' } })}
                      poster=""
                    >
                      お使いのブラウザは動画再生に対応していません
                    </video>
                    <div style={{
                      display: 'flex', justifyContent: 'center', gap: 8, flexWrap: 'wrap',
                      padding: '8px 12px', background: 'var(--bg-primary)',
                    }}>
                      <button
                        onClick={() => apiFetch('getPipelineOpenFolder').catch(() => {})}
                        style={{
                          background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
                          border: '1px solid var(--border-color)', borderRadius: 6,
                          padding: '4px 12px', fontSize: '0.75rem', cursor: 'pointer',
                        }}
                      >
                        📂 出力フォルダ
                      </button>
                      <button
                        onClick={() => openApiUrl('getPipelineStream', { params: { video_type: 'preview' } })}
                        style={{
                          background: 'var(--bg-secondary)', color: 'var(--text-secondary)',
                          border: '1px solid var(--border-color)', borderRadius: 6,
                          padding: '4px 12px', fontSize: '0.75rem', cursor: 'pointer',
                        }}
                      >
                        📥 プレビュー DL
                      </button>
                      <button
                        onClick={() => openApiUrl('getPipelineStream', { params: { video_type: 'final' } })}
                        style={{
                          background: 'var(--accent-primary)', color: 'white',
                          border: 'none', borderRadius: 6,
                          padding: '4px 12px', fontSize: '0.75rem', cursor: 'pointer',
                        }}
                      >
                        📥 最終版 DL
                      </button>
                    </div>
                  </div>

                  <div className="pipeline-result-meta">
                    <span className="pipeline-result-label">セグメント数:</span>
                    <span>{pipelineStatus.result.segments_count}</span>
                    {pipelineStatus.result.metadata?.titles && (
                      <>
                        <span className="pipeline-result-label">タイトル案:</span>
                        <span style={{ fontWeight: 600 }}>{pipelineStatus.result.metadata.titles[0]}</span>
                      </>
                    )}
                    {pipelineStatus.result.metadata?.tags && (
                      <>
                        <span className="pipeline-result-label">タグ ({pipelineStatus.result.metadata.tags.length}個):</span>
                        <span>{pipelineStatus.result.metadata.tags.slice(0, 8).join(', ')}{pipelineStatus.result.metadata.tags.length > 8 ? ' ...' : ''}</span>
                      </>
                    )}
                    {pipelineStatus.result.metadata?.chapters?.length > 0 && (
                      <>
                        <span className="pipeline-result-label">チャプター:</span>
                        <span>{pipelineStatus.result.metadata.chapters.length}個</span>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* エラー表示 */}
              {hasError && (
                <div style={{ 
                  background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
                  borderRadius: 12, padding: 16, marginTop: 16 
                }}>
                  <strong>⚠️ エラー:</strong> {pipelineStatus.error}
                </div>
              )}

              {/* 完了時アクション */}
              {isCompleted && (
                <div style={{ marginTop: 16, textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'center' }}>
                  {onWizardStart && (
                    <button
                      className="pipeline-start-btn"
                      onClick={() => onWizardStart(pipelineStatus.result)}
                      style={{
                        background: 'linear-gradient(135deg, #8b5cf6, #7c3aed)',
                        boxShadow: '0 4px 20px rgba(139,92,246,0.4)',
                        fontSize: '1.05rem',
                        padding: '14px 36px',
                      }}
                    >
                      🧙 仕上げウィザードを開始
                    </button>
                  )}
                  <button
                    className="pipeline-start-btn"
                    onClick={() => setPipelineStatus(null)}
                    style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', boxShadow: 'none' }}
                  >
                    🔄 新しいパイプラインを開始
                  </button>
                </div>
              )}

              {/* エラー時の再実行 */}
              {hasError && (
                <div style={{ marginTop: 16, textAlign: 'center' }}>
                  <button
                    className="pipeline-start-btn"
                    onClick={() => setPipelineStatus(null)}
                    style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', boxShadow: 'none' }}
                  >
                    🔄 新しいパイプラインを開始
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* O-4: SmartCutパネルモーダル */}
      {showSmartCut && (
        <SmartCutPanel
          isOpen={showSmartCut}
          onClose={() => setShowSmartCut(false)}
          segments={pipelineStatus?.result?.segments || pipelineStatus?.stages?.[2]?.data?.segments || []}
          onFinalize={(finalSegments) => {
            console.log('SmartCut finalized:', finalSegments);
            setShowSmartCut(false);
          }}
        />
      )}

      {/* O-6: 品質ゲートモーダル */}
      <QualityGate
        isOpen={showQualityGate}
        onClose={() => setShowQualityGate(false)}
        onConfirm={() => {
          setShowQualityGate(false);
          // レンダリング開始 or 強制書出
          apiFetch('postRenderStart', { body: { force_render: !qualityGateData?.is_ready } }).catch(err => console.error('Render start failed:', err));
        }}
        data={qualityGateData}
      />
    </div>
  );
}
