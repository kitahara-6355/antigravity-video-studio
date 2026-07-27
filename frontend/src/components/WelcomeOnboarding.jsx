/**
 * WelcomeOnboarding.jsx — 初回オンボーディング画面
 * 
 * みらい議会インスピレーション:
 * - 3ステップの直感ガイド
 * - 温かみのある挨拶
 * - 「とにかく1本作ってみよう」への導線
 */
import React, { useState } from 'react';

const STEPS = [
  {
    icon: '🎬',
    title: 'ようこそ、Antigravityへ',
    description: '動画編集の「重力」から解放される旅が始まります。\nAIがあなたの専属スタッフとして、字幕・演出・品質チェックをすべて担当します。',
    hint: 'あなたの役割は「司令官」。判断だけに集中してください。',
  },
  {
    icon: '📂',
    title: 'ステップ1: 動画をセットする',
    description: '設定ページで動画ファイルをドラッグ＆ドロップするだけ。\nAIが自動で字幕を生成し、編集の準備を整えます。',
    hint: 'MP4ファイルを1つ用意してください。',
  },
  {
    icon: '▶️',
    title: 'ステップ2:「制作する」を押す',
    description: 'ヘッダーの「▶ 制作する」ボタンを押すと、\nAIパイプラインが自動で全工程を処理します。\n完了後、仕上げウィザードが案内します。',
    hint: 'たった1ボタンで、プロ品質の動画が完成します。',
  },
];

export default function WelcomeOnboarding({ onComplete }) {
  const [currentStep, setCurrentStep] = useState(0);
  const step = STEPS[currentStep];
  const isLast = currentStep === STEPS.length - 1;

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'linear-gradient(135deg, #f8f7ff 0%, #f0ecff 50%, #e8f4f8 100%)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: "'Noto Sans JP', sans-serif",
    }}>
      {/* 背景デコレーション */}
      <div style={{
        position: 'absolute', top: '10%', left: '5%', width: '300px', height: '300px',
        background: 'radial-gradient(circle, rgba(124,58,237,0.06) 0%, transparent 70%)',
        borderRadius: '50%', pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', bottom: '15%', right: '10%', width: '200px', height: '200px',
        background: 'radial-gradient(circle, rgba(16,185,129,0.06) 0%, transparent 70%)',
        borderRadius: '50%', pointerEvents: 'none',
      }} />

      <div style={{
        width: '100%', maxWidth: '580px', padding: '48px 40px',
        background: 'white', borderRadius: '24px',
        boxShadow: '0 8px 40px rgba(0,0,0,0.08)',
        textAlign: 'center',
        animation: 'fadeSlideDown 0.5s ease',
      }}>
        {/* ステップインジケーター */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '8px', marginBottom: '32px' }}>
          {STEPS.map((_, i) => (
            <div key={i} style={{
              width: i === currentStep ? '32px' : '8px',
              height: '8px',
              borderRadius: '100px',
              background: i === currentStep ? '#7C3AED' : i < currentStep ? '#10B981' : '#e2e8f0',
              transition: 'all 0.3s ease',
            }} />
          ))}
        </div>

        {/* アイコン */}
        <div style={{
          fontSize: '4rem', marginBottom: '16px',
          animation: 'iconBounceOnboard 0.8s cubic-bezier(0.34, 1.56, 0.64, 1)',
        }}>
          {step.icon}
        </div>

        {/* タイトル */}
        <h1 style={{
          fontSize: '1.5rem', fontWeight: 800, color: '#1e293b',
          marginBottom: '16px', letterSpacing: '-0.02em',
        }}>
          {step.title}
        </h1>

        {/* 説明 */}
        <p style={{
          fontSize: '0.95rem', color: '#64748b', lineHeight: 1.8,
          whiteSpace: 'pre-line', marginBottom: '20px',
          maxWidth: '440px', margin: '0 auto 20px',
        }}>
          {step.description}
        </p>

        {/* ヒント */}
        <div style={{
          display: 'inline-block',
          padding: '8px 16px', borderRadius: '100px',
          background: '#f3f0ff', color: '#7C3AED',
          fontSize: '0.82rem', fontWeight: 600,
          marginBottom: '32px',
        }}>
          💡 {step.hint}
        </div>

        {/* ボタン */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', marginTop: '8px' }}>
          {currentStep > 0 && (
            <button
              onClick={() => setCurrentStep(s => s - 1)}
              style={{
                padding: '12px 24px', borderRadius: '12px',
                border: '1px solid rgba(0,0,0,0.08)',
                background: 'white', color: '#64748b',
                fontWeight: 600, cursor: 'pointer',
                fontSize: '0.9rem', fontFamily: "'Noto Sans JP', sans-serif",
                transition: 'all 0.2s',
              }}
            >
              ← 戻る
            </button>
          )}
          <button
            onClick={() => {
              if (isLast) {
                localStorage.setItem('antigravity_onboarded', 'true');
                onComplete();
              } else {
                setCurrentStep(s => s + 1);
              }
            }}
            style={{
              padding: '12px 32px', borderRadius: '12px',
              border: 'none',
              background: isLast
                ? 'linear-gradient(135deg, #10B981, #059669)'
                : 'linear-gradient(135deg, #7C3AED, #6D28D9)',
              color: 'white', fontWeight: 700, cursor: 'pointer',
              fontSize: '0.95rem', fontFamily: "'Noto Sans JP', sans-serif",
              boxShadow: isLast
                ? '0 4px 16px rgba(16,185,129,0.3)'
                : '0 4px 16px rgba(124,58,237,0.25)',
              transition: 'all 0.2s',
            }}
          >
            {isLast ? '🚀 始めましょう！' : '次へ →'}
          </button>
        </div>

        {/* スキップ */}
        {!isLast && (
          <button
            onClick={() => {
              localStorage.setItem('antigravity_onboarded', 'true');
              onComplete();
            }}
            style={{
              marginTop: '20px', background: 'none', border: 'none',
              color: '#94a3b8', fontSize: '0.8rem', cursor: 'pointer',
              fontFamily: "'Noto Sans JP', sans-serif",
            }}
          >
            スキップして始める
          </button>
        )}
      </div>

      {/* アニメーション用 */}
      <style>{`
        @keyframes iconBounceOnboard {
          0% { opacity: 0; transform: scale(0) rotate(-20deg); }
          50% { transform: scale(1.2) rotate(5deg); }
          100% { opacity: 1; transform: scale(1) rotate(0deg); }
        }
      `}</style>
    </div>
  );
}
