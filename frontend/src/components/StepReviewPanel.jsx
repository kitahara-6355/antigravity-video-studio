/**
 * StepReviewPanel.jsx — 段階的レビュー体験（U-10）
 *
 * 5段階のステージに沿って、Owner が順序立てて最終チェックを行うUI。
 *
 * ステージ:
 * 1. 字幕チェック — 誤字・表現確認
 * 2. 構成チェック — シーン順序・尺バランス
 * 3. 演出チェック — テロップ・BGM・エフェクト
 * 4. ブランド整合性 — Soul Passport準拠
 * 5. 最終承認 — レンダリング可否判定
 */
import React, { useState, useCallback } from 'react';
import {
    Type, LayoutList, Wand2, Shield, CheckCircle,
    ChevronRight, ChevronLeft, AlertCircle, ThumbsUp
} from 'lucide-react';
import './StepReview.css';
import { apiFetch } from '../gateway/client.js';


const REVIEW_STAGES = [
    {
        id: 'subtitles',
        title: '字幕チェック',
        icon: Type,
        description: '誤字脱字・固有名詞・表現の自然さを確認',
        checkItems: [
            '固有名詞（人名・地名・社名）は正しいですか？',
            '誤字や不自然な表現はありませんか？',
            '字幕のリズム（1行13文字前後）は適切ですか？',
        ],
    },
    {
        id: 'structure',
        title: '構成チェック',
        icon: LayoutList,
        description: 'シーンの順序・尺のバランスを確認',
        checkItems: [
            '冒頭のフック（最初15秒）は引きがありますか？',
            '中盤にダレる区間はありませんか？',
            '目標尺に対して過不足はありませんか？',
        ],
    },
    {
        id: 'effects',
        title: '演出チェック',
        icon: Wand2,
        description: 'テロップ・BGM・エフェクトの適切さを確認',
        checkItems: [
            'テロップのタイミングと内容は適切ですか？',
            'BGMの音量バランスは良いですか？',
            'エフェクトが過剰ではありませんか？',
        ],
    },
    {
        id: 'brand',
        title: 'ブランド整合性',
        icon: Shield,
        description: 'チャンネルのトーン＆マナーに沿っているか確認',
        checkItems: [
            'チャンネルのトーンに合った表現ですか？',
            'NG ワードは含まれていませんか？',
            'サムネイルとの整合性は取れていますか？',
        ],
    },
    {
        id: 'final',
        title: '最終承認',
        icon: CheckCircle,
        description: 'すべての確認を完了し、レンダリングを承認',
        checkItems: [
            '全体を通して違和感はありませんか？',
            'このままレンダリングして問題ありませんか？',
        ],
    },
];

const StepReviewPanel = ({ isOpen, onClose, onApprove, reviewData }) => {
    const [currentStage, setCurrentStage] = useState(0);
    const [stageResults, setStageResults] = useState({});
    const [checkStates, setCheckStates] = useState({});
    const [stageNotes, setStageNotes] = useState({});

    // ━━━ D-3修正: category_report からAI自動チェック結果を初期化 ━━━
    const categoryMap = React.useMemo(() => {
        const report = reviewData?.category_report || [];
        const map = {};
        report.forEach(cat => { map[cat.category] = cat; });
        return map;
    }, [reviewData]);

    // category_report → REVIEW_STAGES へのマッピング
    const CATEGORY_TO_STAGE = {
        'core': 'subtitles',       // コア品質 → 字幕チェック
        'template': 'structure',   // テンプレート → 構成チェック
        'broadcast': 'effects',    // 放送品質 → 演出チェック
        'youtube': 'brand',        // YouTube → ブランド
        'accessibility': 'final',  // アクセシビリティ → 最終
    };

    // **AI のスコアで人間のチェック項目を自動 ON にしない**（R1.5-C4・19周目）。
    //
    // ここは以前「初回マウント時に AI スコア 70点以上のステージを自動チェック」して
    // いた。倒していたのは「固有名詞（人名・地名・社名）は正しいですか？」
    // 「誤字や不自然な表現はありませんか？」といった、**人が目で見ないと
    // 答えられない問い**で、AI のカテゴリスコアはその答えになっていない。
    //
    // `isStageComplete()` はこのチェック状態だけを見るので、自動 ON のまま
    // `handleApprove()` が `completed: true` を送り、**誰も見ていないレビューが
    // 「確認済み」として永続化**されていた。これは C4 が言う偽の success そのもの。
    //
    // AI スコアは `getStageScore()` のバッジで別途出しているので、
    // 自動チェックを外してもスコアの情報は画面から失われない。

    // ステージごとのAIスコアバッジを取得
    const getStageScore = (stageId) => {
        const entry = Object.entries(CATEGORY_TO_STAGE).find(([, v]) => v === stageId);
        if (!entry) return null;
        return categoryMap[entry[0]] || null;
    };

    const stage = REVIEW_STAGES[currentStage];
    const totalStages = REVIEW_STAGES.length;

    const isStageComplete = useCallback((stageIndex) => {
        const s = REVIEW_STAGES[stageIndex];
        const checks = checkStates[s.id] || {};
        return s.checkItems.every((_, i) => checks[i] === true);
    }, [checkStates]);

    const completedStages = REVIEW_STAGES.filter((_, i) => isStageComplete(i)).length;
    const allComplete = completedStages === totalStages;

    const toggleCheck = (itemIndex) => {
        setCheckStates(prev => {
            const stageChecks = { ...(prev[stage.id] || {}) };
            stageChecks[itemIndex] = !stageChecks[itemIndex];
            return { ...prev, [stage.id]: stageChecks };
        });
    };

    const handleNext = () => {
        if (currentStage < totalStages - 1) {
            setCurrentStage(prev => prev + 1);
        }
    };

    const handlePrev = () => {
        if (currentStage > 0) {
            setCurrentStage(prev => prev - 1);
        }
    };

    const handleApprove = useCallback(async () => {
        const result = {
            stages: REVIEW_STAGES.map((s, i) => ({
                id: s.id,
                title: s.title,
                completed: isStageComplete(i),
                checks: checkStates[s.id] || {},
                notes: stageNotes[s.id] || '',
            })),
            approved_at: new Date().toISOString(),
        };

        try {
            await apiFetch('postQualityReviewApprove', { body: result });
        } catch (err) {
            console.warn('Review approval sync failed:', err);
        }

        onApprove?.(result);
    }, [isStageComplete, checkStates, stageNotes, onApprove]);

    if (!isOpen) return null;

    return (
        <div className="step-review-overlay">
            <div className="step-review-panel">
                {/* ヘッダー */}
                <div className="step-review-header">
                    <h2>📋 段階的レビュー</h2>
                    <div className="header-progress">
                        {completedStages}/{totalStages} 完了
                    </div>
                    <button className="close-btn" onClick={onClose}>✕</button>
                </div>

                {/* ステージインジケーター */}
                <div className="stage-indicator">
                    {REVIEW_STAGES.map((s, i) => {
                        const Icon = s.icon;
                        const completed = isStageComplete(i);
                        const isCurrent = i === currentStage;

                        return (
                            <button
                                key={s.id}
                                className={`stage-dot ${isCurrent ? 'current' : ''} ${completed ? 'completed' : ''}`}
                                onClick={() => setCurrentStage(i)}
                                title={s.title}
                            >
                                <Icon size={16} />
                                {completed && <span className="check-mark">✓</span>}
                            </button>
                        );
                    })}
                </div>

                {/* ステージコンテンツ */}
                <div className="stage-content">
                    <div className="stage-title-section">
                        <stage.icon size={22} className="stage-icon" />
                        <div>
                            <h3>
                                {stage.title}
                                {(() => {
                                    const scoreData = getStageScore(stage.id);
                                    if (!scoreData || scoreData.score === null) return null;
                                    return (
                                        <span style={{
                                            marginLeft: 10,
                                            fontSize: '0.75rem',
                                            padding: '2px 8px',
                                            borderRadius: 6,
                                            background: scoreData.score >= 70
                                                ? 'rgba(16,185,129,0.15)'
                                                : 'rgba(245,158,11,0.15)',
                                            color: scoreData.score >= 70 ? '#10b981' : '#f59e0b',
                                            fontWeight: 600,
                                        }}>
                                            {scoreData.status} {scoreData.score}点
                                        </span>
                                    );
                                })()}
                            </h3>
                            <p className="stage-desc">{stage.description}</p>
                        </div>
                    </div>

                    <div className="check-list">
                        {stage.checkItems.map((item, i) => {
                            const checked = checkStates[stage.id]?.[i] || false;
                            return (
                                <label
                                    key={i}
                                    className={`check-item ${checked ? 'checked' : ''}`}
                                >
                                    <input
                                        type="checkbox"
                                        checked={checked}
                                        onChange={() => toggleCheck(i)}
                                    />
                                    <span className="check-text">{item}</span>
                                </label>
                            );
                        })}
                    </div>

                    <div className="stage-notes">
                        <textarea
                            placeholder="メモや気になった点を記録..."
                            value={stageNotes[stage.id] || ''}
                            onChange={(e) => setStageNotes(prev => ({
                                ...prev,
                                [stage.id]: e.target.value,
                            }))}
                        />
                    </div>
                </div>

                {/* フッター */}
                <div className="step-review-footer">
                    <button
                        className="btn-nav"
                        onClick={handlePrev}
                        disabled={currentStage === 0}
                    >
                        <ChevronLeft size={16} /> 前へ
                    </button>

                    <div className="footer-center">
                        <span className="stage-counter">
                            {currentStage + 1} / {totalStages}
                        </span>
                    </div>

                    {currentStage < totalStages - 1 ? (
                        <button className="btn-nav primary" onClick={handleNext}>
                            次へ <ChevronRight size={16} />
                        </button>
                    ) : (
                        <button
                            className="btn-approve"
                            onClick={handleApprove}
                            disabled={!allComplete}
                            title={allComplete ? 'レンダリングを承認' : '全チェック項目を完了してください'}
                        >
                            <ThumbsUp size={16} />
                            {allComplete ? '承認してレンダリング' : '全項目を確認してください'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default StepReviewPanel;
