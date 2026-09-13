import React, { useState, useEffect, useCallback } from 'react';
import { Settings, Monitor, Users, Database, Upload, Save, Play, Check, AlertCircle, Loader, Zap, Lightbulb, Radio, Smartphone } from 'lucide-react';
import { useDropzone } from 'react-dropzone';
import PreProductionPlanner from './PreProductionPlanner';
import OperationsDashboard from './OperationsDashboard';
import ShortsGenerator from './ShortsGenerator';
import { apiFetch } from '../gateway/client.js';

export default function SettingsPage({ onClose }) {
    const [activeTab, setActiveTab] = useState('soul');
    const [config, setConfig] = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [successMessage, setSuccessMessage] = useState(null);
    const [errorMessage, setErrorMessage] = useState(null);
    const [identitySaved, setIdentitySaved] = useState(false);

    // Transcription State
    const [isTranscribing, setIsTranscribing] = useState(false);
    const [progress, setProgress] = useState(0);
    const [statusMessage, setStatusMessage] = useState("");

    // Forms
    const [identityForm, setIdentityForm] = useState({ channel_name: '', target_audience: '' });

    useEffect(() => {
        fetchConfig();
    }, []);

    const fetchConfig = () => {
        setLoading(true);
        apiFetch('getSettings')
            .then(res => res.json())
            .then(data => {
                setConfig(data);
                if (data.constitution) {
                    setIdentityForm({
                        channel_name: data.constitution.channel_name || '',
                        target_audience: data.constitution.target_audience || ''
                    });
                }
                setLoading(false);
            })
            .catch(err => {
                console.error("Failed to fetch settings:", err);
                setErrorMessage("設定の読み込みに失敗しました。サーバーを確認してください。");
                setLoading(false);
            });
    };

    // --- Tab 1: Workspace (Video Upload) ---
    const onDrop = useCallback(acceptedFiles => {
        const file = acceptedFiles[0];
        if (!file) return;

        setSaving(true);
        setErrorMessage(null);
        setSuccessMessage(null);

        const formData = new FormData();
        formData.append('file', file);

        apiFetch('postSettingsVideo', { body: formData })
            .then(res => res.json())
            .then(data => {
                setSuccessMessage("動画が正常にアップロードされました！ (Original: " + file.name + ")");
                setTimeout(() => setSuccessMessage(null), 5000);
                setSaving(false);
                fetchConfig(); // Refresh status
            })
            .catch(err => {
                console.error(err);
                setErrorMessage("アップロードに失敗しました。再度お試しください。");
                setSaving(false);
            });
    }, []);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'video/mp4': ['.mp4'] },
        maxFiles: 1
    });

    // --- Tab 2: Identity (Save) ---
    const saveIdentity = () => {
        setSaving(true);
        setErrorMessage(null);
        apiFetch('postSettingsIdentity', { body: identityForm })
            .then(res => res.json())
            .then(data => {
                setSaving(false);
                setIdentitySaved(true);
                setTimeout(() => setIdentitySaved(false), 2000);
            })
            .catch(err => {
                setSaving(false);
                setErrorMessage("保存に失敗しました。");
            });
    };



    // Define checkStatus outside useEffect so it can be reused
    const checkStatus = () => {
        apiFetch('getTranscribeStatus')
            .then(res => res.json())
            .then(data => {
                if (data.status === 'processing' || data.status === 'starting') {
                    setIsTranscribing(true);
                    setProgress(data.progress || 0);
                    setStatusMessage(data.message || "処理中...");
                    // If we just started, we might want to ensure message is visible, 
                    // but handleTranscribe sets it too.
                } else if (data.status === 'completed') {
                    setIsTranscribing(false);
                    setProgress(100);
                    // Prevent infinite success loop if already viewed, but for now simple is fine.
                    // Ideally we only show success if we were previously processing.
                    if (isTranscribing) {
                        setSuccessMessage("字幕生成が完了しました！エディターを起動してください。");
                    }
                } else if (data.status === 'failed') {
                    setIsTranscribing(false);
                    if (isTranscribing) {
                        setErrorMessage("生成に失敗しました: " + data.message);
                    }
                } else {
                    setIsTranscribing(false);
                }
            })
            .catch(err => {
                console.error("Status check failed", err);
            });
    };

    // Poll for status on mount and when transcribing
    useEffect(() => {
        let intervalId;

        // Initial check
        checkStatus();

        // Start polling
        intervalId = setInterval(checkStatus, 3000);

        return () => clearInterval(intervalId);
    }, [isTranscribing]);

    const handleTranscribe = () => {
        setIsTranscribing(true);
        setSuccessMessage(null);
        setErrorMessage(null);

        apiFetch('postTranscribe')
            .then(async res => {
                if (!res.ok) {
                    const text = await res.text();
                    throw new Error(text || res.statusText);
                }
                return res.json();
            })
            .then(data => {
                setSuccessMessage("字幕生成を開始しました！(進捗を追跡中...)");
                // Immediately check status to update UI state
                checkStatus();
            })
            .catch(err => {
                console.error("Transcribe trigger failed", err);
                setErrorMessage("字幕生成の起動に失敗しました: " + err.message);
                setIsTranscribing(false);
            });
    };

    const handleReset = () => {
        if (!window.confirm("【警告】ワークスペースを初期化しますか？\n\n現在の「動画」と「字幕データ」は完全に削除されます。\nこの操作は取り消せません。")) return;

        setSaving(true);
        setErrorMessage(null);
        setSuccessMessage(null);

        apiFetch('postSettingsReset')
            .then(res => res.json())
            .then(data => {
                if (data.status === 'success') {
                    setSuccessMessage("ワークスペースを正常にリセットしました。");
                    fetchConfig();
                } else {
                    // Fallback to data.detail (FastAPI standard) if data.message is missing
                    const msg = data.message || data.detail || "不明なエラー";
                    setErrorMessage("リセット失敗: " + msg);
                }
                setSaving(false);
            })
            .catch(err => {
                setErrorMessage("通信エラーが発生しました。");
                setSaving(false);
            });
    };

    if (loading) {
        return (
            <div className="loading-container fade-in">
                <div className="spinner"></div>
                <p>システム設定を読み込み中...</p>
            </div>
        );
    }

    return (
        <div className="settings-page fade-in" style={{ padding: '2rem', maxWidth: '95%', margin: '0 auto' }}>
            <header className="settings-header" style={{ marginBottom: '1.5rem', borderBottom: '1px solid rgba(0,0,0,0.06)', paddingBottom: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <Settings size={28} color="#64748b" />
                    <div>
                        <h1 style={{ margin: 0, fontSize: '1.6rem', fontWeight: 800, letterSpacing: '-0.02em' }}>システム設定</h1>
                        <p style={{ margin: 0, color: '#64748b', fontSize: '0.9rem' }}>基本設定・ファイル管理・データ入出力</p>
                    </div>
                </div>
                <button
                    onClick={onClose}
                    style={{
                        padding: '10px 24px', background: 'linear-gradient(135deg, #7C3AED, #6D28D9)', color: 'white',
                        border: 'none', borderRadius: '12px', fontSize: '0.95rem', fontWeight: 700, cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: '8px',
                        boxShadow: '0 2px 12px rgba(124,58,237,0.25)', transition: 'all 0.2s ease',
                        fontFamily: 'Noto Sans JP',
                    }}
                >
                    <Monitor size={18} /> エディターを起動
                </button>
            </header>

            {/* Notifications */}
            {successMessage && (
                <div className="fade-in" style={{
                    marginBottom: '1rem', padding: '1rem', background: '#d1fae5', color: '#065f46',
                    borderRadius: '8px', fontWeight: 'bold', border: '1px solid #a7f3d0',
                    display: 'flex', alignItems: 'center', gap: '10px'
                }}>
                    <Check size={20} /> {successMessage}
                </div>
            )}

            {errorMessage && (
                <div className="fade-in" style={{
                    marginBottom: '1rem', padding: '1rem', background: '#fee2e2', color: '#b91c1c',
                    borderRadius: '8px', fontWeight: 'bold', border: '1px solid #fecaca',
                    display: 'flex', alignItems: 'center', gap: '10px'
                }}>
                    <AlertCircle size={20} /> {errorMessage}
                </div>
            )}

            <div className="settings-layout" style={{ display: 'flex', gap: '2rem' }}>
                {/* Sidebar Navigation */}
                <nav className="settings-nav" style={{ width: '250px', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <TabButton active={activeTab === 'soul'} onClick={() => setActiveTab('soul')} icon={<Database size={20} />} label="データ管理" />
                    <TabButton active={activeTab === 'identity'} onClick={() => setActiveTab('identity')} icon={<Users size={20} />} label="ブランド憲法" />
                    <TabButton active={activeTab === 'workspace'} onClick={() => setActiveTab('workspace')} icon={<Monitor size={20} />} label="ワークスペース" />
                    <TabButton active={activeTab === 'preplan'} onClick={() => setActiveTab('preplan')} icon={<Lightbulb size={20} />} label="企画ラボ" />
                    <TabButton active={activeTab === 'ops'} onClick={() => setActiveTab('ops')} icon={<Radio size={20} />} label="運用監視" />
                    <TabButton active={activeTab === 'shorts'} onClick={() => setActiveTab('shorts')} icon={<Smartphone size={20} />} label="Shorts切出し" />
                </nav>

                {/* Main Content Area */}
                <main className="settings-content" style={{ flex: 1, background: '#fff', borderRadius: '12px', padding: '2rem', boxShadow: '0 4px 6px rgba(0,0,0,0.05)', minHeight: '600px' }}>

                    {/* --- TAB 3: DATA MANAGEMENT (Formerly Soul Data) --- */}
                    {activeTab === 'soul' && (
                        <div className="tab-pane fade-in">
                            <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Database /> データ管理</h2>
                            <p style={{ color: '#718096', marginBottom: '1.5rem' }}>
                                魂データ（ユーザーモデル）のインポート・エクスポートを行います。<br />
                                <span style={{ fontSize: '0.9rem', color: '#e53e3e' }}>※ 能力パラメーターやランクの変動履歴などの詳細は「戦略会議室」で確認してください。</span>
                            </p>

                            <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                                {/* Left: Current Brief Status */}
                                <div style={{ flex: 1, minWidth: '300px', background: '#f7fafc', padding: '2rem', borderRadius: '16px', border: '1px solid #e2e8f0' }}>
                                    <h3 style={{ fontSize: '1.2rem', marginBottom: '1rem', color: '#2d3748' }}>現在の登録情報</h3>
                                    <div style={{ marginBottom: '1rem' }}>
                                        <div style={{ fontSize: '0.85rem', color: '#718096' }}>ユーザー名</div>
                                        <div style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>{config?.user_model?.name || "User"}</div>
                                    </div>
                                    <div style={{ marginBottom: '1rem' }}>
                                        <div style={{ fontSize: '0.85rem', color: '#718096' }}>現在のランク</div>
                                        <div style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#3182ce' }}>{config?.user_model?.profiles?.admin?.ranks?.tech_rank?.level || "ランク未設定"}</div>
                                    </div>
                                </div>

                                {/* Right: Actions */}
                                <div style={{ flex: 1, minWidth: '300px', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                    <div style={{ background: '#fff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #cbd5e0', height: '100%' }}>
                                        <h4 style={{ margin: '0 0 1rem' }}>JSONデータの入出力</h4>
                                        <p style={{ fontSize: '0.9rem', color: '#718096', marginBottom: '1.5rem' }}>バックアップや環境移行に使用します。</p>

                                        <button className="card-hover" style={{ width: '100%', padding: '15px', marginBottom: '15px', background: '#fff', border: '2px dashed #cbd5e0', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', color: '#4a5568', fontWeight: 'bold' }}>
                                            <Upload size={20} /> JSONファイルをインポート
                                        </button>
                                        <button className="card-hover" style={{ width: '100%', padding: '15px', background: '#2d3748', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', fontWeight: 'bold', boxShadow: '0 4px 6px rgba(45, 55, 72, 0.2)' }}>
                                            <Check size={20} /> パスポート発行
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* --- TAB 2: IDENTITY --- */}
                    {activeTab === 'identity' && (
                        <div className="tab-pane fade-in">
                            <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Users /> ブランド憲法</h2>
                            <p style={{ color: '#718096', marginBottom: '1.5rem' }}>AIがあなたのブランドをどう認識するか定義します。ここの設定は「戦略」および「演出」エージェントに直結します。</p>

                            <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
                                {/* Left: Forms */}
                                <div style={{ flex: 1, minWidth: '300px' }}>
                                    <div className="form-group" style={{ marginBottom: '1.5rem' }}>
                                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold', color: '#4a5568' }}>チャンネル名 / ハンドル</label>
                                        <input
                                            type="text"
                                            value={identityForm.channel_name}
                                            onChange={e => setIdentityForm({ ...identityForm, channel_name: e.target.value })}
                                            style={{ width: '100%', padding: '12px', fontSize: '1rem', borderRadius: '6px', border: '1px solid #e2e8f0', background: '#f8fafc' }}
                                            placeholder="@YourChannel"
                                        />
                                    </div>

                                    <div className="form-group" style={{ marginBottom: '2rem' }}>
                                        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold', color: '#4a5568' }}>ターゲット視聴者</label>
                                        <input
                                            type="text"
                                            value={identityForm.target_audience}
                                            onChange={e => setIdentityForm({ ...identityForm, target_audience: e.target.value })}
                                            style={{ width: '100%', padding: '12px', fontSize: '1rem', borderRadius: '6px', border: '1px solid #e2e8f0', background: '#f8fafc' }}
                                            placeholder="例: 20代のガジェット好き、忙しい主婦層、など"
                                        />
                                    </div>
                                    <button
                                        id="save-identity-btn"
                                        className="card-hover"
                                        onClick={saveIdentity}
                                        disabled={saving}
                                        style={{
                                            background: identitySaved ? '#059669' : '#10b981',
                                            color: 'white', border: 'none', padding: '12px 30px', borderRadius: '30px',
                                            fontSize: '1rem', fontWeight: 'bold', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px',
                                            boxShadow: '0 4px 6px rgba(16, 185, 129, 0.2)', transition: 'background 0.3s'
                                        }}
                                    >
                                        {saving ? <Loader className="spinner" size={18} /> : <Save size={18} />}
                                        {saving ? "保存中..." : identitySaved ? "保存完了!" : "設定を保存"}
                                    </button>
                                </div>

                                {/* Right: Preview */}
                                <div style={{ flex: 1, minWidth: '300px' }}>
                                    <div className="preview-card" style={{ padding: '2rem', background: '#f0fff4', borderRadius: '12px', border: '1px solid #9ae6b4', height: '100%' }}>
                                        <h4 style={{ margin: '0 0 1rem', display: 'flex', alignItems: 'center', gap: '8px', color: '#276749', fontSize: '1.1rem' }}>
                                            <AlertCircle size={20} /> AI認識プレビュー
                                        </h4>
                                        <p style={{ fontStyle: 'italic', color: '#2f855a', lineHeight: '1.8', fontSize: '1.05rem' }}>
                                            「了解しました。私は<strong>{identityForm.channel_name || "不明なチャンネル"}</strong>の専属スタッフとして振る舞います。<br /><br />
                                            ターゲットである<strong>{identityForm.target_audience || "一般視聴者"}</strong>に刺さるよう、
                                            口調や演出を最適化します。」
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* --- TAB 1: WORKSPACE --- */}
                    {activeTab === 'workspace' && (
                        <div className="tab-pane fade-in">
                            <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Monitor /> 動画ワークスペース</h2>
                            <p style={{ color: '#718096', marginBottom: '1.5rem' }}>編集対象の動画ファイルを管理します。現在のソース: <strong>{config?.video_exists ? (config?.constitution?.video_source_name || "リンク済み") : "未設定"}</strong></p>

                            <div style={{ display: 'flex', gap: '2rem', alignItems: 'stretch' }}>
                                <div {...getRootProps()} className="card-hover" style={{
                                    flex: 2,
                                    border: '3px dashed #cbd5e0',
                                    borderRadius: '12px',
                                    padding: '3rem',
                                    textAlign: 'center',
                                    cursor: 'pointer',
                                    background: isDragActive ? '#f0fff4' : '#fafafa',
                                    transition: 'all 0.2s',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    justifyContent: 'center',
                                    alignItems: 'center'
                                }}>
                                    <input {...getInputProps()} />
                                    {saving ? (
                                        <div style={{ color: '#3182ce', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                                            <div className="spinner" style={{ marginBottom: '1rem' }}></div>
                                            <p>アップロード中...</p>
                                        </div>
                                    ) : (
                                        <>
                                            <Upload size={48} color="#a0aec0" style={{ margin: '0 auto 1rem' }} />
                                            {isDragActive ? (
                                                <p style={{ fontSize: '1.2rem', color: '#10b981', fontWeight: 'bold' }}>ここにMP4ファイルをドロップ...</p>
                                            ) : (
                                                <div>
                                                    <p style={{ fontSize: '1.2rem', fontWeight: 'bold' }}>ここに動画をドラッグ＆ドロップ</p>
                                                    <p style={{ color: '#718096' }}>またはクリックしてファイルを選択 (MP4のみ)</p>
                                                </div>
                                            )}
                                        </>
                                    )}
                                </div>

                                <div style={{ flex: 1, padding: '1.5rem', background: '#ebf8ff', borderRadius: '12px', border: '1px solid #bee3f8', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                                    <h4 style={{ margin: '0 0 1rem', color: '#2c5282' }}>現在のステータス</h4>
                                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                                        <div style={{ width: '80px', height: '80px', background: '#222', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                            <Play color="#fff" size={32} />
                                        </div>
                                        <div>
                                            <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{config?.constitution?.video_source_name || "sample_raw.mp4"}</div>
                                            <div style={{ color: '#4a5568', fontSize: '0.9rem', marginTop: '4px' }}>
                                                {saving ? <span style={{ color: '#3182ce', fontWeight: 'bold' }}>処理中...</span> : "リンク済み・分析準備完了"}
                                            </div>
                                        </div>
                                    </div>
                                    <div style={{ marginTop: '1rem', fontSize: '0.85rem', color: '#718096' }}>
                                        ※ 現在はシングルファイルモードで動作しています。新しいファイルをドロップすると上書きされます。
                                    </div>

                                    <div style={{ marginTop: 'auto', paddingTop: '1rem', borderTop: '1px solid #bee3f8' }}>
                                        <button
                                            onClick={handleTranscribe}
                                            disabled={isTranscribing}
                                            className="card-hover"
                                            style={{
                                                width: '100%', padding: '12px',
                                                background: isTranscribing ? '#cbd5e0' : '#805ad5',
                                                color: 'white', border: 'none', borderRadius: '8px',
                                                fontWeight: 'bold', cursor: isTranscribing ? 'not-allowed' : 'pointer',
                                                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
                                                flexDirection: 'column'
                                            }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                {isTranscribing ? <Loader className="spinner" size={18} /> : <Zap size={18} />}
                                                {isTranscribing ? `解析中... ${progress}%` : "字幕を生成"}
                                            </div>
                                            {isTranscribing && <div style={{ fontSize: '0.8rem', opacity: 0.8 }}>{statusMessage}</div>}
                                        </button>

                                        {isTranscribing && (
                                            <div style={{ width: '100%', height: '6px', background: '#e2e8f0', borderRadius: '3px', marginTop: '10px', overflow: 'hidden' }}>
                                                <div style={{
                                                    width: `${progress}%`,
                                                    height: '100%',
                                                    background: '#805ad5',
                                                    transition: 'width 0.5s ease-out'
                                                }} />
                                            </div>
                                        )}

                                        <p style={{ fontSize: '0.8rem', color: '#805ad5', textAlign: 'center', marginTop: '8px' }}>
                                            ※ 時間がかかります (数分程度)
                                        </p>

                                        <div style={{ marginTop: '2rem', paddingTop: '1rem', borderTop: '1px solid #e2e8f0', textAlign: 'center' }}>
                                            <button
                                                onClick={handleReset}
                                                className="btn-danger-link"
                                                style={{
                                                    background: 'transparent', border: '1px solid #fc8181', color: '#e53e3e',
                                                    padding: '8px 16px', borderRadius: '4px', fontSize: '0.9rem', cursor: 'pointer',
                                                    marginTop: '5px'
                                                }}
                                            >
                                                🗑️ ワークスペースを初期化
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* --- TAB 4: 企画ラボ (Pre-Production Planner) --- */}
                    {activeTab === 'preplan' && (
                        <div className="tab-pane fade-in">
                            <PreProductionPlanner />
                        </div>
                    )}

                    {/* --- TAB 5: 運用監視 (Operations Dashboard) --- */}
                    {activeTab === 'ops' && (
                        <div className="tab-pane fade-in">
                            <OperationsDashboard />
                        </div>
                    )}

                    {/* --- TAB 6: Shorts切出し --- */}
                    {activeTab === 'shorts' && (
                        <div className="tab-pane fade-in">
                            <ShortsGenerator />
                        </div>
                    )}

                </main>
            </div>
        </div>
    );
}

// Sub-component for Tabs
function TabButton({ active, onClick, icon, label }) {
    return (
        <button
            onClick={onClick}
            style={{
                display: 'flex', alignItems: 'center', gap: '10px',
                padding: '12px 16px',
                background: active ? '#f3f0ff' : 'transparent',
                color: active ? '#7C3AED' : '#64748b',
                border: 'none',
                borderRadius: '10px',
                fontWeight: active ? 700 : 500,
                boxShadow: active ? '0 1px 3px rgba(0,0,0,0.04)' : 'none',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.2s',
                borderLeft: active ? '3px solid #7C3AED' : '3px solid transparent',
                fontFamily: 'Noto Sans JP',
                fontSize: '0.9rem',
            }}
        >
            {icon}
            {label}
        </button>
    );
}
