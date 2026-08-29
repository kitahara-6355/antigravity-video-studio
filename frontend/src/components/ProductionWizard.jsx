/**
 * ProductionWizard.jsx — 仕上げウィザード（D-1〜D-7 一括解消）
 *
 * パイプライン完了後、チャンネル主を6ステップで自動案内する。
 * 各ステップは既存コンポーネントを再利用し、WizardContextでデータを流通させる。
 *
 * ステートマシン:
 *   SMARTCUT → THEME → REVIEW → QUALITY → FINAL_CHECK → YOUTUBE → COMPLETE
 */
import React, { useReducer, useCallback, useMemo, useEffect } from 'react';
import SmartCutPanel from './SmartCutPanel';
import ThemeSelector from './ThemeSelector';
import QuickDecisionBar from './QuickDecisionBar';
import QualityGate from './QualityGate';
import StepReviewPanel from './StepReviewPanel';
import YouTubeOptimizerPanel from './YouTubeOptimizerPanel';
import './ProductionWizard.css';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// ステップ定義
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
const STEPS = [
  { id: 'smartcut',    icon: '✂️', label: '尺調整',       skippable: true  },
  { id: 'theme',       icon: '🎨', label: 'テーマ',       skippable: true  },
  { id: 'review',      icon: '⚡', label: 'レビュー',     skippable: false },
  { id: 'quality',     icon: '🛡️', label: '品質ゲート',   skippable: false },
  { id: 'final_check', icon: '✅', label: '最終確認',     skippable: false },
  { id: 'youtube',     icon: '📺', label: 'YouTube',     skippable: true  },
];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// Reducer（ステートマシン）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
const initialState = {
  currentStep: 0,
  stepStatus: STEPS.map(() => 'pending'), // pending | active | completed | skipped
  completed: false,
  // 各ステップで蓄積されるデータ
  smartcutConfig: null,
  themeConfig: null,
  reviewDecisions: [],
  qualityPassed: false,
  finalCheckPassed: false,
  youtubeConfig: null,
  // 子パネルの開閉
  panelOpen: {},
};

function wizardReducer(state, action) {
  switch (action.type) {
    case 'NEXT': {
      const nextStep = state.currentStep + 1;
      const newStatus = [...state.stepStatus];
      newStatus[state.currentStep] = 'completed';
      if (nextStep < STEPS.length) {
        newStatus[nextStep] = 'active';
        return { ...state, currentStep: nextStep, stepStatus: newStatus };
      }
      return { ...state, completed: true, stepStatus: newStatus };
    }
    case 'SKIP': {
      const nextStep = state.currentStep + 1;
      const newStatus = [...state.stepStatus];
      newStatus[state.currentStep] = 'skipped';
      if (nextStep < STEPS.length) {
        newStatus[nextStep] = 'active';
        return { ...state, currentStep: nextStep, stepStatus: newStatus };
      }
      return { ...state, completed: true, stepStatus: newStatus };
    }
    case 'BACK': {
      if (state.currentStep <= 0) return state;
      const prevStep = state.currentStep - 1;
      const newStatus = [...state.stepStatus];
      newStatus[state.currentStep] = 'pending';
      newStatus[prevStep] = 'active';
      return { ...state, currentStep: prevStep, stepStatus: newStatus };
    }
    case 'SET_DATA':
      return { ...state, [action.key]: action.value };
    case 'TOGGLE_PANEL':
      return {
        ...state,
        panelOpen: { ...state.panelOpen, [action.panel]: !state.panelOpen[action.panel] },
      };
    case 'INIT': {
      const newStatus = STEPS.map(() => 'pending');
      newStatus[0] = 'active';
      return { ...initialState, stepStatus: newStatus };
    }
    default:
      return state;
  }
}

// ━━━ IMP-002: localStorage永続化ヘルパー ━━━
const WIZARD_STORAGE_KEY = 'antigravity_wizard_state';

function loadPersistedState() {
  try {
    const saved = localStorage.getItem(WIZARD_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      // 1時間以上前のデータは破棄
      if (parsed._savedAt && Date.now() - parsed._savedAt < 3600000) {
        return parsed;
      }
    }
  } catch {}
  return null;
}

function persistState(state) {
  try {
    localStorage.setItem(WIZARD_STORAGE_KEY, JSON.stringify({
      ...state,
      _savedAt: Date.now(),
    }));
  } catch {}
}

function clearPersistedState() {
  try { localStorage.removeItem(WIZARD_STORAGE_KEY); } catch {}
}

export default function ProductionWizard({ isOpen, onClose, onRender, context }) {
  const [state, dispatch] = useReducer(wizardReducer, initialState, () => {
    // リロード復帰: localStorageから状態を復元
    const persisted = loadPersistedState();
    if (persisted && !persisted.completed) {
      return persisted;
    }
    const s = { ...initialState };
    s.stepStatus = STEPS.map((_, i) => (i === 0 ? 'active' : 'pending'));
    return s;
  });

  // ━━━ IMP-002: 状態変更時に自動保存 ━━━
  useEffect(() => {
    if (state.completed) {
      clearPersistedState();
    } else {
      persistState(state);
    }
  }, [state]);

  // ── コンテキストから展開 ──
  const {
    segments = [],
    // **既定値を 0 にしない**（R1.5-C4・9周目の指摘）。`= 0` だと
    // `typeof quality_score === 'number'` が真になり、下の「未計測」の枝へ
    // **本番から到達できなかった。**0 は実際に取りうる点なので、値では区別できない
    quality_score = null,
    quality_scored = null,
    quality_feedback = [],
    category_report = [],
    metadata = {},
  } = context || {};

  const currentStepDef = STEPS[state.currentStep];

  // ── アクション ──
  const handleNext = useCallback(() => dispatch({ type: 'NEXT' }), []);
  const handleSkip = useCallback(() => dispatch({ type: 'SKIP' }), []);
  const handleBack = useCallback(() => dispatch({ type: 'BACK' }), []);

  // ── レビューアイテム生成（D-2解消） ──
  const reviewItems = useMemo(() => {
    return quality_feedback.map((fb, i) => ({
      id: `qf-${i}`,
      title: fb,
      context: '',
      type: 'warning',
    }));
  }, [quality_feedback]);

  // ── 品質ゲートデータ統合（D-6解消） ──
  // IMP-003: category_reportが空の場合のフォールバック
  const qualityGateData = useMemo(() => {
    // **未計測を「0点」と表示しない**（R1.5-C4）。`|| 0` のせいで、
    // 品質ゲートを一度も通していないセッションが「品質スコア0点」と出ていた。
    // バックエンド側（run_gate / _get_quality_score）で `null` を返すようにしたのと同じ扱い。
    // **旗があれば旗を見る**（R1.5-C4）。バックエンドの `_build_result` が
    // `quality_scored` を載せる。無い応答（古い形）は値で判断する
    const 採点した = quality_scored === null
      ? typeof quality_score === 'number'
      : quality_scored === true;
    const effectiveScore = 採点した ? quality_score : null;
    const effectiveFeedback = quality_feedback.length > 0
      ? quality_feedback
      : (category_report.length > 0
          ? category_report.filter(c => c.score !== null && c.score < 70).map(c => `${c.label}: ${c.status} (${c.score}点)`)
          : []);
    return {
      is_ready: 採点した && effectiveScore >= 80,
      scored: 採点した,
      score: effectiveScore,
      critical_issues: effectiveFeedback.filter((_, i) => i < 3),
      suggestions: [],
      final_verdict: !採点した
        ? '品質スコアは**未計測**です。品質ゲートを通してから判断してください。'
        : effectiveScore >= 80
          ? `品質スコア${effectiveScore}点 — 出力準備完了です。`
          : `品質スコア${effectiveScore}点 — 改善を推奨しますが、強制続行も可能です。`,
    };
    // **旗も依存に入れる**（R1.5-C4・13周目）。入れないと、旗だけが
    // 変わったときに古い判定が残る
  }, [quality_score, quality_scored, quality_feedback, category_report]);

  // ── ステップレビューデータ（D-3解消） ──
  const stepReviewData = useMemo(() => ({
    category_report: category_report,
    segments: segments,
    quality_score: quality_score,
  }), [category_report, segments, quality_score]);

  // ── 完了サマリー ──
  const summary = useMemo(() => {
    const completed = state.stepStatus.filter(s => s === 'completed').length;
    const skipped = state.stepStatus.filter(s => s === 'skipped').length;
    return { completed, skipped, total: STEPS.length };
  }, [state.stepStatus]);

  if (!isOpen) return null;

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // ステップコンテンツ描画
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const renderStepContent = () => {
    if (state.completed) {
      return (
        <div className="wizard-complete" style={{ position: 'relative' }}>
          {/* 🎊 紙吹雪パーティクル */}
          <div className="wizard-confetti">
            {Array.from({ length: 40 }).map((_, i) => {
              const colors = ['#8B5CF6', '#10B981', '#F59E0B', '#EC4899', '#3B82F6', '#EF4444'];
              const shapes = ['circle', 'square'];
              const color = colors[i % colors.length];
              const shape = shapes[i % shapes.length];
              return (
                <div
                  key={i}
                  className="confetti-piece"
                  style={{
                    left: `${Math.random() * 100}%`,
                    background: color,
                    borderRadius: shape === 'circle' ? '50%' : '2px',
                    width: `${6 + Math.random() * 8}px`,
                    height: `${6 + Math.random() * 8}px`,
                    '--delay': `${Math.random() * 0.8}s`,
                    '--duration': `${2 + Math.random() * 2}s`,
                    '--rotation': `${360 + Math.random() * 720}deg`,
                  }}
                />
              );
            })}
          </div>

          <span className="complete-icon complete-icon-bounce">🎉</span>
          <h2>仕上げ完了！</h2>
          <p>全ステップの確認が完了しました。レンダリングを開始できます。</p>
          <div className="wizard-summary-grid">
            <div className="wizard-summary-card">
              <div className="label">完了</div>
              <div className="value score-counter" style={{ color: '#10b981' }}>{summary.completed}</div>
            </div>
            <div className="wizard-summary-card">
              <div className="label">スキップ</div>
              <div className="value score-counter" style={{ color: '#64748b' }}>{summary.skipped}</div>
            </div>
            <div className="wizard-summary-card">
              <div className="label">品質スコア</div>
              <div className="value score-counter" style={{ color: quality_score >= 80 ? '#10b981' : '#f59e0b' }}>
                {quality_score}点
              </div>
            </div>
          </div>
          <button className="wizard-btn wizard-btn-render" onClick={onRender}>
            🎬 レンダリング開始
          </button>
        </div>
      );
    }

    switch (currentStepDef.id) {
      case 'smartcut':
        return (
          <div className="wizard-step-intro">
            <span className="step-icon">✂️</span>
            <h3>尺の微調整</h3>
            <p>
              パイプラインで自動構成済みです。微調整が必要な場合のみ
              SmartCutパネルを開いてください。
            </p>
            {state.panelOpen.smartcut ? (
              <SmartCutPanel
                isOpen={true}
                onClose={() => dispatch({ type: 'TOGGLE_PANEL', panel: 'smartcut' })}
                segments={segments}
                onFinalize={(data) => {
                  dispatch({ type: 'SET_DATA', key: 'smartcutConfig', value: data });
                  dispatch({ type: 'TOGGLE_PANEL', panel: 'smartcut' });
                }}
              />
            ) : (
              <button
                className="wizard-btn"
                style={{
                  marginTop: 20,
                  background: 'rgba(139,92,246,0.1)',
                  border: '1px solid rgba(139,92,246,0.3)',
                  color: '#c4b5fd',
                }}
                onClick={() => dispatch({ type: 'TOGGLE_PANEL', panel: 'smartcut' })}
              >
                ✂️ SmartCutを開く
              </button>
            )}
          </div>
        );

      case 'theme':
        return (
          <ThemeSelector
            isOpen={true}
            onClose={() => {}} // ウィザード内では閉じない
            segments={segments}
            onApply={(config) => {
              dispatch({ type: 'SET_DATA', key: 'themeConfig', value: config });
              handleNext();
            }}
          />
        );

      case 'review':
        return reviewItems.length > 0 ? (
          <QuickDecisionBar
            items={reviewItems}
            onDecisionComplete={(results) => {
              dispatch({ type: 'SET_DATA', key: 'reviewDecisions', value: results });
              handleNext();
            }}
            onClose={() => {}} // ウィザード内では閉じない
          />
        ) : (
          <div className="wizard-step-intro">
            <span className="step-icon">⚡</span>
            <h3>AIレビュー</h3>
            <p>品質チェックで指摘事項がありませんでした。次のステップへ進んでください。</p>
          </div>
        );

      case 'quality':
        return (
          <QualityGate
            isOpen={true}
            onClose={() => {}} // ウィザード内では閉じない
            data={qualityGateData}
            onConfirm={() => {
              dispatch({ type: 'SET_DATA', key: 'qualityPassed', value: true });
              handleNext();
            }}
          />
        );

      case 'final_check':
        return (
          <StepReviewPanel
            isOpen={true}
            onClose={() => {}} // ウィザード内では閉じない
            reviewData={stepReviewData}
            onApprove={() => {
              dispatch({ type: 'SET_DATA', key: 'finalCheckPassed', value: true });
              handleNext();
            }}
          />
        );

      case 'youtube':
        return (
          <div>
            {state.panelOpen.youtube ? (
              <YouTubeOptimizerPanel
                isOpen={true}
                onClose={() => dispatch({ type: 'TOGGLE_PANEL', panel: 'youtube' })}
                segments={segments}
              />
            ) : (
              <div className="wizard-step-intro">
                <span className="step-icon">📺</span>
                <h3>YouTube最適化</h3>
                <p>タイトル案・サムネイル・タグを最終調整します。</p>
                {metadata?.titles && (
                  <p style={{ color: '#c4b5fd', marginTop: 8 }}>
                    推奨タイトル: 「{metadata.titles[0]}」
                  </p>
                )}
                <button
                  className="wizard-btn"
                  style={{
                    marginTop: 20,
                    background: 'rgba(239,68,68,0.1)',
                    border: '1px solid rgba(239,68,68,0.3)',
                    color: '#fca5a5',
                  }}
                  onClick={() => dispatch({ type: 'TOGGLE_PANEL', panel: 'youtube' })}
                >
                  📺 YouTube最適化パネルを開く
                </button>
              </div>
            )}
          </div>
        );

      default:
        return null;
    }
  };

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  // フッターボタンの可否判定
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const canSkip = !state.completed && currentStepDef?.skippable;
  const canBack = !state.completed && state.currentStep > 0;

  // review/quality/final_check は自動遷移なので「次へ」は不要（コンポーネント内でhandleNext）
  const showNextButton = !state.completed && !['review', 'quality', 'final_check'].includes(currentStepDef?.id);

  return (
    <div className="wizard-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="wizard-container" onClick={(e) => e.stopPropagation()}>

        {/* ── Header ── */}
        <div className="wizard-header">
          <div className="wizard-title">
            <span className="wizard-title-icon">🧙</span>
            仕上げウィザード
          </div>
          <button className="wizard-close-btn" onClick={onClose}>
            ✕ 閉じる
          </button>
        </div>

        {/* ── Step Indicator ── */}
        {!state.completed && (
          <div className="wizard-steps">
            {STEPS.map((step, i) => (
              <div key={step.id} className={`wizard-step-item ${i === state.currentStep ? 'is-active' : ''}`}>
                {i > 0 && (
                  <div className={`wizard-step-connector ${
                    state.stepStatus[i - 1] === 'completed' ? 'done' : ''
                  }`} />
                )}
                <div className={`wizard-step-dot ${state.stepStatus[i]}`}>
                  {state.stepStatus[i] === 'completed' ? '✓' :
                   state.stepStatus[i] === 'skipped' ? '–' :
                   step.icon}
                </div>
                <span className="wizard-step-label">{step.label}</span>
              </div>
            ))}
          </div>
        )}

        {/* ── Body ── */}
        <div className="wizard-body">
          {renderStepContent()}
        </div>

        {/* ── Footer ── */}
        {!state.completed && (
          <div className="wizard-footer">
            <div className="wizard-footer-left">
              {canBack && (
                <button className="wizard-btn wizard-btn-back" onClick={handleBack}>
                  ← 戻る
                </button>
              )}
            </div>
            <div className="wizard-footer-right">
              {canSkip && (
                <button className="wizard-btn wizard-btn-skip" onClick={handleSkip}>
                  スキップ →
                </button>
              )}
              {showNextButton && (
                <button className="wizard-btn wizard-btn-next" onClick={handleNext}>
                  次へ →
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
