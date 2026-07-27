import React, { useState, useEffect, useRef } from 'react';
import '../App.css';
import './ImageDirector.css'; // Import specific styles

const API_BASE = "http://localhost:8000";

function ImageDirector({ isOpen, onClose, scene, onApplyImage, initialTakes, initialChatHistory, segments }) {
    const [messages, setMessages] = useState([]); // { role: 'user'|'model', parts: [text] } for API
    const [displayMessages, setDisplayMessages] = useState([]); // { sender: 'ai'|'user', text } for UI
    const [input, setInput] = useState("");
    const [isTyping, setIsTyping] = useState(false);
    const [isGeneratingImage, setIsGeneratingImage] = useState(false); // Async Generation State
    const [generatedImages, setGeneratedImages] = useState([]);
    const [selectedImage, setSelectedImage] = useState(null);
    const [currentPrompt, setCurrentPrompt] = useState("");

    const messagesEndRef = useRef(null);
    const pollingRef = useRef(null);

    // Initial Data Load (Effect)
    useEffect(() => {
        if (isOpen && scene) {
            // Construct context from segments
            const fullText = segments ? segments.map(s => s.text).join('\n') : "字幕データなし";
            const contextBlock = `\n\n【参照用: すべての字幕テキスト】\n${fullText}`;

            // Initialize conversation
            // We inject the context block into the FIRST prompt but only show the friendly part in the UI if it's not history.
            // Actually, best practice is to send it as a separate system-like message first?
            // "DirectorBrain" handles simple history. Let's prepend it to the first user message logic.

            const initialPrompt = `シーン「${scene.name}」(${scene.description}) の画像を作りたいです。${contextBlock}`;

            // Restore Chat History or Set Default
            if (initialChatHistory && initialChatHistory.ui) {
                setMessages(initialChatHistory.backend || []);
                setDisplayMessages(initialChatHistory.ui);
            } else {
                // Initialize Backend History with Context
                setMessages([
                    { role: 'user', parts: [initialPrompt] },
                    { role: 'model', parts: [`了解しました。シーン「${scene.name}」ですね。字幕テキスト全体も確認しました。文脈に沿った最適な画像を生成します。`] }
                ]);

                setDisplayMessages([
                    {
                        sender: 'ai',
                        text: `こんにちは！シーン「${scene.name}」の画像を作成します。\nどのようなイメージにしたいですか？（字幕全体の内容は把握しています）`
                    }
                ]);
            }

            // Restore Takes
            const history = [...(initialTakes || [])];
            if (scene.image && !history.includes(scene.image)) {
                history.unshift(scene.image);
            }
            setGeneratedImages(history);

            if (scene.image) {
                setSelectedImage(scene.image);
            } else {
                setSelectedImage(null);
            }

            setCurrentPrompt(`${scene.name}, ${scene.description}`);
            setIsGeneratingImage(false);
        }
    }, [isOpen, scene, initialTakes, initialChatHistory, segments]);

    // Cleanup polling on unmount
    useEffect(() => {
        return () => {
            if (pollingRef.current) clearInterval(pollingRef.current);
        };
    }, []);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [displayMessages]);

    const startPolling = (taskId) => {
        setIsGeneratingImage(true);
        // Clear existing poll if any
        if (pollingRef.current) clearInterval(pollingRef.current);

        pollingRef.current = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/api/director/tasks/${taskId}`);
                if (!res.ok) return;
                const task = await res.json();

                if (task.status === 'completed') {
                    clearInterval(pollingRef.current);
                    const images = task.result.map(b64 => `data:image/jpeg;base64,${b64}`);

                    // Add new images to history (prepend)
                    setGeneratedImages(prev => [...images, ...prev]);

                    setIsGeneratingImage(false);
                    setDisplayMessages(prev => [...prev, { sender: 'ai', text: "候補ができました！いかがですか？" }]);
                } else if (task.status === 'failed') {
                    clearInterval(pollingRef.current);
                    setIsGeneratingImage(false);
                    setDisplayMessages(prev => [...prev, { sender: 'ai', text: `画像生成に失敗しました... (${task.error})` }]);
                }
            } catch (e) {
                console.error("Polling error", e);
            }
        }, 3000);
    };

    const handleSend = async () => {
        if (!input.trim()) return;

        const userText = input;
        setInput("");

        // Update UI immediately (Chat is allowed even during generation!)
        setDisplayMessages(prev => [...prev, { sender: 'user', text: userText }]);
        setCurrentPrompt(prev => `${prev}, ${userText}`);

        // Update History for API
        const newHistory = [...messages, { role: 'user', parts: [userText] }];
        setMessages(newHistory);

        setIsTyping(true);

        try {
            // 1. Chat with Gemini
            const chatRes = await fetch(`${API_BASE}/api/director/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    history: messages,
                    message: userText
                })
            });

            if (!chatRes.ok) throw new Error("Chat API Failed");
            const chatData = await chatRes.json();
            const aiResponse = chatData.text;

            // Update UI with AI Response
            setDisplayMessages(prev => [...prev, { sender: 'ai', text: aiResponse }]);
            setMessages(prev => [...prev, { role: 'model', parts: [aiResponse] }]);

            setIsTyping(false);

            // 2. Trigger Async Image Generation
            setDisplayMessages(prev => [...prev, { sender: 'ai', text: "画像を生成しています... (バックグラウンドで作業中 🎨)" }]);

            const imgRes = await fetch(`${API_BASE}/api/director/generate-image-async`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: `${currentPrompt}, ${userText}` })
            });

            if (!imgRes.ok) throw new Error("Image Gen Start Failed");
            const imgData = await imgRes.json();

            if (imgData.task_id) {
                startPolling(imgData.task_id);
            }

        } catch (e) {
            console.error(e);
            setDisplayMessages(prev => [...prev, { sender: 'ai', text: "すみません、エラーが発生しました。" }]);
            setIsTyping(false);
        }
    };

    const handleApply = () => {
        if (selectedImage) {
            // Return selected image, full takes history, and chat history
            onApplyImage(
                selectedImage,
                generatedImages,
                { backend: messages, ui: displayMessages }
            );
            onClose();
        }
    };

    if (!isOpen) return null;

    return (
        <div className="image-director-overlay">
            <div className="image-director-modal">
                {/* Header */}
                <div className="image-director-header">
                    <div className="header-title">
                        <span className="icon">🍌</span>
                        <div>
                            <h3>Interactive Image Director</h3>
                            <span className="subtitle">Powered by Gemini 3 Pro & Imagen 3</span>
                        </div>
                    </div>
                    <button className="close-btn" onClick={onClose}>×</button>
                </div>

                {/* Content */}
                <div className="image-director-body">
                    {/* Left: Chat */}
                    <div className="chat-section">
                        <div className="messages-area">
                            {displayMessages.map((msg, idx) => (
                                <div key={idx} className={`message-bubble ${msg.sender}`}>
                                    {msg.sender === 'ai' && <div className="avatar">🍌</div>}
                                    <div className="text" style={{ whiteSpace: 'pre-wrap' }}>{msg.text}</div>
                                </div>
                            ))}
                            {isTyping && <div className="message-bubble ai"><div className="avatar">🍌</div><div className="text typing">...</div></div>}
                            <div ref={messagesEndRef} />
                        </div>
                        <div className="input-area">
                            <input
                                type="text"
                                placeholder="例: 「もっと明るく」「サイバーパンク風で」..."
                                value={input}
                                onChange={(e) => setInput(e.target.value)}
                                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                            />
                            <button onClick={handleSend} disabled={isTyping}>送信</button>
                        </div>
                    </div>

                    {/* Right: Preview & Prompt */}
                    <div className="visual-section">
                        <div className="prompt-display">
                            <label>Current Prompt Context:</label>
                            <div className="prompt-box">{currentPrompt}</div>
                        </div>

                        <div className="images-grid">
                            {isGeneratingImage ? (
                                <div className="empty-state" style={{ border: '2px dashed #3b82f6', background: 'rgba(59, 130, 246, 0.1)' }}>
                                    <div className="spinner" style={{ width: 30, height: 30, borderTopColor: '#3b82f6', margin: '0 auto 15px auto' }}></div>
                                    <p>画像を生成中... 🎨<br /><small style={{ opacity: 0.7 }}>チャットを続けても大丈夫です</small></p>
                                </div>
                            ) : generatedImages.length === 0 ? (
                                <div className="empty-state">
                                    <span className="placeholder-icon">🖼️</span>
                                    <p>対話を進めると、ここに画像が生成されます</p>
                                </div>
                            ) : (
                                generatedImages.map((img, idx) => (
                                    <div
                                        key={idx}
                                        className={`image-candidate ${selectedImage === img ? 'selected' : ''}`}
                                        onClick={() => setSelectedImage(img)}
                                    >
                                        <img src={img} alt={`Candidate ${idx}`} />
                                        {selectedImage === img && <div className="check-mark">✔</div>}
                                    </div>
                                ))
                            )}
                        </div>

                        <div className="action-area">
                            <button
                                className="btn-apply"
                                disabled={!selectedImage}
                                onClick={handleApply}
                            >
                                この画像を採用する
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default ImageDirector;
