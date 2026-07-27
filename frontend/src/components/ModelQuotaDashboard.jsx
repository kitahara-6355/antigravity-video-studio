import { useState, useEffect } from 'react';

/**
 * モデル使用量ダッシュボード（2段階方式）
 * 
 * PROJECT_CONSTITUTION §18 準拠:
 * - Premium/Standard 2段階表示
 * - 残り枠可視化
 * - 待機オプション
 * - モデル切換え通知
 */
export default function ModelQuotaDashboard({ onModelSelect }) {
    const [tierStatus, setTierStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [selectedOption, setSelectedOption] = useState(null);

    useEffect(() => {
        fetchTierStatus();
        const interval = setInterval(fetchTierStatus, 30000); // 30秒ごとに更新
        return () => clearInterval(interval);
    }, []);

    const fetchTierStatus = async () => {
        try {
            const response = await fetch('http://localhost:8000/api/usage/two-tier-status');
            const data = await response.json();
            setTierStatus(data);
            setLoading(false);
        } catch (error) {
            console.error('Failed to fetch tier status:', error);
            setLoading(false);
        }
    };

    const handleOptionSelect = async (tier, option) => {
        try {
            const response = await fetch(`http://localhost:8000/api/usage/select-option?tier=${tier}&option=${option}`, {
                method: 'POST'
            });
            const result = await response.json();
            setSelectedOption(result);

            if (onModelSelect && result.model) {
                onModelSelect(result.model, result);
            }
        } catch (error) {
            console.error('Failed to select option:', error);
        }
    };

    if (loading) {
        return <div className="quota-dashboard loading">読み込み中...</div>;
    }

    if (!tierStatus) {
        return <div className="quota-dashboard error">データを取得できませんでした</div>;
    }

    const premium = tierStatus.tiers?.premium;
    const standard = tierStatus.tiers?.standard;
    const resetInfo = tierStatus.reset_info;

    return (
        <div className="quota-dashboard">
            <h3>🎯 モデル使用量</h3>

            {/* リセット時間 */}
            <div className="reset-info">
                <span className="reset-label">リセットまで:</span>
                <span className="reset-time">{resetInfo?.remaining_display || '--'}</span>
            </div>

            {/* 2段階モデル表示 */}
            <div className="tier-cards">
                {/* Premium */}
                <TierCard
                    tier="premium"
                    label="Premium"
                    icon="⭐"
                    data={premium}
                    onSelect={handleOptionSelect}
                />

                {/* Standard */}
                <TierCard
                    tier="standard"
                    label="Standard"
                    icon="📦"
                    data={standard}
                    onSelect={handleOptionSelect}
                />
            </div>

            {/* 選択結果 */}
            {selectedOption && (
                <div className={`selected-option ${selectedOption.action}`}>
                    <span className="option-message">{selectedOption.message}</span>
                    {selectedOption.warning && (
                        <span className="option-warning">⚠️ {selectedOption.warning}</span>
                    )}
                </div>
            )}

            <style>{`
        .quota-dashboard {
          background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
          border-radius: 12px;
          padding: 16px;
          color: #fff;
          font-family: 'Inter', sans-serif;
        }
        
        .quota-dashboard h3 {
          margin: 0 0 12px 0;
          font-size: 14px;
          color: #a0a0a0;
        }
        
        .reset-info {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 8px 12px;
          background: rgba(255, 255, 255, 0.05);
          border-radius: 8px;
          margin-bottom: 12px;
        }
        
        .reset-label {
          color: #888;
          font-size: 12px;
        }
        
        .reset-time {
          font-weight: 600;
          color: #4ecdc4;
        }
        
        .tier-cards {
          display: flex;
          gap: 12px;
        }
        
        .tier-card {
          flex: 1;
          background: rgba(255, 255, 255, 0.05);
          border-radius: 10px;
          padding: 12px;
          border: 1px solid transparent;
          transition: all 0.2s;
        }
        
        .tier-card.premium {
          border-color: rgba(255, 215, 0, 0.3);
        }
        
        .tier-card.standard {
          border-color: rgba(100, 149, 237, 0.3);
        }
        
        .tier-card.warning {
          border-color: rgba(255, 165, 0, 0.5);
        }
        
        .tier-card.exhausted {
          border-color: rgba(255, 69, 0, 0.5);
          opacity: 0.7;
        }
        
        .tier-header {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 8px;
        }
        
        .tier-icon {
          font-size: 16px;
        }
        
        .tier-label {
          font-weight: 600;
          font-size: 13px;
        }
        
        .tier-progress {
          height: 6px;
          background: rgba(255, 255, 255, 0.1);
          border-radius: 3px;
          margin: 8px 0;
          overflow: hidden;
        }
        
        .tier-progress-bar {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s;
        }
        
        .tier-progress-bar.normal {
          background: linear-gradient(90deg, #4ecdc4, #44a08d);
        }
        
        .tier-progress-bar.caution {
          background: linear-gradient(90deg, #f39c12, #e67e22);
        }
        
        .tier-progress-bar.warning {
          background: linear-gradient(90deg, #e74c3c, #c0392b);
        }
        
        .tier-stats {
          display: flex;
          justify-content: space-between;
          font-size: 11px;
          color: #888;
        }
        
        .tier-remaining {
          font-weight: 600;
          color: #fff;
        }
        
        .tier-options {
          display: flex;
          gap: 6px;
          margin-top: 10px;
        }
        
        .tier-option-btn {
          flex: 1;
          padding: 6px 8px;
          border: none;
          border-radius: 6px;
          font-size: 10px;
          cursor: pointer;
          transition: all 0.2s;
        }
        
        .tier-option-btn.wait {
          background: rgba(74, 144, 226, 0.3);
          color: #4a90e2;
        }
        
        .tier-option-btn.fallback {
          background: rgba(241, 196, 15, 0.3);
          color: #f1c40f;
        }
        
        .tier-option-btn.force {
          background: rgba(231, 76, 60, 0.3);
          color: #e74c3c;
        }
        
        .tier-option-btn:hover {
          transform: translateY(-1px);
          filter: brightness(1.1);
        }
        
        .selected-option {
          margin-top: 12px;
          padding: 10px;
          border-radius: 8px;
          font-size: 12px;
        }
        
        .selected-option.wait {
          background: rgba(74, 144, 226, 0.2);
          border: 1px solid rgba(74, 144, 226, 0.4);
        }
        
        .selected-option.fallback {
          background: rgba(241, 196, 15, 0.2);
          border: 1px solid rgba(241, 196, 15, 0.4);
        }
        
        .selected-option.force {
          background: rgba(231, 76, 60, 0.2);
          border: 1px solid rgba(231, 76, 60, 0.4);
        }
        
        .option-warning {
          display: block;
          margin-top: 6px;
          color: #f39c12;
          font-size: 11px;
        }
      `}</style>
        </div>
    );
}

function TierCard({ tier, label, icon, data, onSelect }) {
    if (!data) return null;

    const usagePercent = data.usage_percent || 0;
    const remaining = data.available_for_use || 0;
    const status = data.status || 'normal';

    const getProgressClass = () => {
        if (usagePercent >= 80) return 'warning';
        if (usagePercent >= 60) return 'caution';
        return 'normal';
    };

    return (
        <div className={`tier-card ${tier} ${status}`}>
            <div className="tier-header">
                <span className="tier-icon">{icon}</span>
                <span className="tier-label">{label}</span>
            </div>

            <div className="tier-progress">
                <div
                    className={`tier-progress-bar ${getProgressClass()}`}
                    style={{ width: `${usagePercent}%` }}
                />
            </div>

            <div className="tier-stats">
                <span>使用率: {usagePercent}%</span>
                <span className="tier-remaining">残り: {remaining}</span>
            </div>

            {tier === 'premium' && status !== 'normal' && (
                <div className="tier-options">
                    <button
                        className="tier-option-btn wait"
                        onClick={() => onSelect(tier, 'wait')}
                    >
                        待機
                    </button>
                    <button
                        className="tier-option-btn fallback"
                        onClick={() => onSelect(tier, 'fallback')}
                    >
                        Standard
                    </button>
                    <button
                        className="tier-option-btn force"
                        onClick={() => onSelect(tier, 'force')}
                    >
                        強制
                    </button>
                </div>
            )}
        </div>
    );
}
