import React, { useState } from 'react';
import ImageDirector from './ImageDirector';
import DirectorBriefing from './DirectorBriefing';

function SceneTimeline({ scenes, audioConfig, segments, onUpdateScene, onUpdateAllScenes, onUndo, canUndo }) {
    const [generating, setGenerating] = useState({}); // { [index]: boolean }
    const [activeSceneIndex, setActiveSceneIndex] = useState(null); // Which scene is being edited
    const [isDirectorOpen, setIsDirectorOpen] = useState(false);
    const [isBriefingOpen, setIsBriefingOpen] = useState(false);

    // Opens the Interactive Image Director
    const openImageDirector = (index) => {
        setActiveSceneIndex(index);
        setIsDirectorOpen(true);
    };

    const handleApplyImage = (imageUrl, allTakes, chatHistory) => {
        if (activeSceneIndex === null) return;

        // Update the scene with the new image, history, and chat context
        const updatedScene = {
            ...scenes[activeSceneIndex],
            image: imageUrl,
            takes: allTakes, // Persist history
            chatHistory: chatHistory // Persist chat context
        };
        onUpdateScene(activeSceneIndex, updatedScene);

        // Close director
        setIsDirectorOpen(false);
        setActiveSceneIndex(null);
    };

    if (!scenes) return null;

    return (
        <div className="scene-timeline-container">
            <div className="scene-timeline-header">
                <h4>シーン構成 (Story Board)</h4>
                {audioConfig && (
                    <div style={{ fontSize: '0.8rem', color: '#999', display: 'flex', alignItems: 'center', gap: '5px' }}>
                        <span>🎵 BGM: {audioConfig.name}</span>
                        <span style={{ background: '#333', padding: '2px 5px', borderRadius: '4px' }}>{audioConfig.style}</span>
                    </div>
                )}

                {/* Director Briefing Button (Unified Chat) */}
                <button
                    className="btn-primary"
                    style={{ marginLeft: '10px', fontSize: '12px', background: '#3b82f6', border: 'none', display: 'flex', alignItems: 'center', gap: '5px' }}
                    onClick={() => setIsBriefingOpen(true)}
                >
                    🎥 全体演出ブリーフィング
                </button>

                <div className="badge-ai" style={{ marginLeft: 'auto' }}>⚡ Nano Banana Pro Active</div>
                <button
                    className="btn-secondary"
                    style={{ marginLeft: '10px', padding: '4px 10px', fontSize: '12px' }}
                    onClick={onUndo}
                    disabled={!canUndo}
                >
                    ↩ 戻す
                </button>
            </div>

            <div className="scene-scroll-area">
                {scenes.map((scene, i) => (
                    <div key={i} className="scene-card">
                        <div className="scene-number">#{i + 1}</div>

                        <div className="scene-visual">
                            {scene.image ? (
                                <img src={scene.image} alt={scene.name} />
                            ) : (
                                <div className="placeholder-visual">
                                    {generating[i] ? (
                                        <div className="generating-overlay">
                                            <div className="spinner"></div>
                                            <span>Creating...</span>
                                        </div>
                                    ) : (
                                        <button
                                            className="generate-btn"
                                            onClick={() => openImageDirector(i)}
                                        >
                                            ✨ AI画像生成
                                        </button>
                                    )}
                                </div>
                            )}

                            {/* Regenerate button (only visible on hover over existing image) */}
                            {scene.image && (
                                <button
                                    className="regenerate-btn"
                                    onClick={() => openImageDirector(i)}
                                >
                                    ↻ 再生成
                                </button>
                            )}
                        </div>

                        <div className="scene-info">
                            <div className="scene-title">{scene.name}</div>
                            <div className="scene-desc-mini">{scene.description}</div>

                            {/* Director's Note & Asset Suggestion */}
                            {scene.rationale && (
                                <div className="scene-rationale" style={{ fontSize: '0.8rem', color: '#aaa', marginTop: '5px', borderTop: '1px solid #333', paddingTop: '5px' }}>
                                    <span style={{ color: '#FCD34D' }}>💡 演出意図:</span> {scene.rationale}
                                </div>
                            )}

                            {scene.source_type === 'USER_ASSET' && (
                                <div className="scene-asset-req" style={{
                                    marginTop: '5px', padding: '5px', borderRadius: '4px',
                                    background: 'rgba(16, 185, 129, 0.1)', border: '1px dashed #10b981', color: '#10b981', fontSize: '0.8rem'
                                }}>
                                    <strong>📂 素材推奨:</strong><br />
                                    {scene.asset_suggestion}
                                    <button style={{ marginTop: '5px', width: '100%', fontSize: '0.75rem', padding: '3px', cursor: 'pointer' }}>
                                        + ファイルを選択
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            {/* Interactive Image Director Modal (Single Scene) */}
            {isDirectorOpen && activeSceneIndex !== null && scenes[activeSceneIndex] && (
                <ImageDirector
                    isOpen={isDirectorOpen}
                    onClose={() => setIsDirectorOpen(false)}
                    scene={scenes[activeSceneIndex]}
                    segments={segments} // Pass full context
                    initialTakes={scenes[activeSceneIndex].takes} // Restore history
                    initialChatHistory={scenes[activeSceneIndex].chatHistory} // Restore chat
                    onApplyImage={handleApplyImage}
                />
            )}

            {/* Unified Director Briefing Modal (All Scenes) */}
            <DirectorBriefing
                isOpen={isBriefingOpen}
                onClose={() => setIsBriefingOpen(false)}
                segments={segments}
                scenes={scenes}
                onUpdateAllScenes={onUpdateAllScenes}
            />
        </div>
    );
}

export default SceneTimeline;
