/**
 * PreProductionPlanner.jsx — 企画フェーズUI（タイトル先行制作）
 * 
 * MrBeast流: 撮影前にタイトル→サムネ→CTR予測を実行。
 * CTR基準（4%+）を満たさない企画は早期に没にし、制作コストを節約。
 * 
 * バックエンド: カタログの postYoutubePrePlan
 */
import React, { useState } from 'react';
import { apiFetch } from '../gateway/client.js';


const GENRE_OPTIONS = [
  { value: '', label: '選択してください' },
  { value: 'Vlog', label: '🎥 Vlog' },
  { value: 'Tutorial', label: '📚 チュートリアル' },
  { value: 'Review', label: '🔍 レビュー' },
  { value: 'Gaming', label: '🎮 ゲーム実況' },
  { value: 'Entertainment', label: '🎉 エンタメ' },
  { value: 'News', label: '📰 ニュース解説' },
  { value: 'Cooking', label: '🍳 料理' },
  { value: 'Music', label: '🎵 音楽' },
  { value: 'Other', label: '📌 その他' },
];

export default function PreProductionPlanner() {
  const [topic, setTopic] = useState('');
  const [genre, setGenre] = useState('');
  const [targetAudience, setTargetAudience] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleGenerate = async () => {
    if (!topic.trim()) return;
    setIsLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await apiFetch('postYoutubePrePlan', { body: {
          topic: topic.trim(),
          genre,
          target_audience: targetAudience.trim(),
        } });
      if (!res.ok) throw new Error(`API Error: ${res.status}`);
      const data = await res.json();
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const ctrColor = (ctr) => {
    if (ctr >= 4.0) return '#10B981';
    if (ctr >= 3.0) return '#F59E0B';
    return '#EF4444';
  };

  const styles = {
    container: {
      animation: 'fadeIn 0.3s ease',
    },
    inputGroup: {
      marginBottom: '16px',
    },
    label: {
      display: 'block', fontSize: '0.85rem', fontWeight: 600,
      color: '#475569', marginBottom: '6px',
    },
    input: {
      width: '100%', padding: '12px 16px', borderRadius: '10px',
      border: '1px solid #e2e8f0', fontSize: '0.95rem',
      fontFamily: "'Noto Sans JP', sans-serif",
      transition: 'border-color 0.2s',
      outline: 'none', boxSizing: 'border-box',
    },
    select: {
      width: '100%', padding: '12px 16px', borderRadius: '10px',
      border: '1px solid #e2e8f0', fontSize: '0.95rem',
      fontFamily: "'Noto Sans JP', sans-serif",
      background: 'white', cursor: 'pointer', boxSizing: 'border-box',
    },
    generateBtn: {
      width: '100%', padding: '14px', borderRadius: '12px',
      border: 'none', fontSize: '1rem', fontWeight: 700,
      fontFamily: "'Noto Sans JP', sans-serif",
      background: 'linear-gradient(135deg, #7C3AED, #6D28D9)',
      color: 'white', cursor: 'pointer',
      boxShadow: '0 4px 14px rgba(124,58,237,0.3)',
      transition: 'all 0.2s', marginTop: '8px',
    },
    resultCard: {
      background: '#f8fafc', borderRadius: '16px',
      border: '1px solid #e2e8f0', padding: '24px',
      marginTop: '24px', animation: 'fadeIn 0.4s ease',
    },
    titleRow: {
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 16px', borderRadius: '10px',
      background: 'white', border: '1px solid #f1f5f9',
      marginBottom: '8px', transition: 'all 0.2s',
    },
    ctrBadge: (ctr) => ({
      padding: '4px 12px', borderRadius: '100px',
      fontSize: '0.82rem', fontWeight: 700,
      color: 'white', background: ctrColor(ctr),
      minWidth: '80px', textAlign: 'center',
    }),
    verdictBadge: (verdict) => ({
      padding: '4px 10px', borderRadius: '6px',
      fontSize: '0.78rem', fontWeight: 600,
      background: verdict.includes('GO') ? '#d1fae5' : verdict.includes('要改善') ? '#fef3c7' : '#fee2e2',
      color: verdict.includes('GO') ? '#065f46' : verdict.includes('要改善') ? '#92400e' : '#991b1b',
    }),
    goNoGo: (decision) => ({
      display: 'inline-block', padding: '8px 20px',
      borderRadius: '100px', fontSize: '1.1rem', fontWeight: 800,
      background: decision === 'GO'
        ? 'linear-gradient(135deg, #10B981, #059669)'
        : 'linear-gradient(135deg, #F59E0B, #D97706)',
      color: 'white',
      boxShadow: decision === 'GO'
        ? '0 4px 14px rgba(16,185,129,0.3)'
        : '0 4px 14px rgba(245,158,11,0.3)',
    }),
    thumbnailCard: {
      padding: '12px 16px', borderRadius: '10px',
      background: 'white', border: '1px solid #f1f5f9',
      marginBottom: '8px',
    },
    lessonCard: {
      padding: '10px 14px', borderRadius: '8px',
      background: '#f3f0ff', color: '#6D28D9',
      fontSize: '0.85rem', marginBottom: '6px',
    },
  };

  return (
    <div style={styles.container}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
        💡 企画ラボ
      </h2>
      <p style={{ color: '#64748b', fontSize: '0.9rem', marginBottom: '24px' }}>
        撮影前にタイトル・サムネ・CTR予測を実行。勝てない企画は早めに没にします。
      </p>

      {/* 入力フォーム */}
      <div style={styles.inputGroup}>
        <label style={styles.label}>📝 企画テーマ <span style={{ color: '#EF4444' }}>*</span></label>
        <input
          style={styles.input}
          placeholder="例: 一人キャンプで絶品スモーク料理に挑戦"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onFocus={(e) => e.target.style.borderColor = '#7C3AED'}
          onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
        />
      </div>

      <div style={{ display: 'flex', gap: '12px' }}>
        <div style={{ ...styles.inputGroup, flex: 1 }}>
          <label style={styles.label}>🎬 ジャンル</label>
          <select style={styles.select} value={genre} onChange={(e) => setGenre(e.target.value)}>
            {GENRE_OPTIONS.map(opt => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        <div style={{ ...styles.inputGroup, flex: 1 }}>
          <label style={styles.label}>👥 ターゲット</label>
          <input
            style={styles.input}
            placeholder="例: 20-30代 アウトドア好き"
            value={targetAudience}
            onChange={(e) => setTargetAudience(e.target.value)}
            onFocus={(e) => e.target.style.borderColor = '#7C3AED'}
            onBlur={(e) => e.target.style.borderColor = '#e2e8f0'}
          />
        </div>
      </div>

      <button
        style={{
          ...styles.generateBtn,
          opacity: !topic.trim() || isLoading ? 0.5 : 1,
          cursor: !topic.trim() || isLoading ? 'not-allowed' : 'pointer',
        }}
        onClick={handleGenerate}
        disabled={!topic.trim() || isLoading}
      >
        {isLoading ? '🔄 AIが企画を分析中...' : '🚀 タイトル案を生成する'}
      </button>

      {/* エラー表示 */}
      {error && (
        <div style={{
          marginTop: '16px', padding: '12px 16px', background: '#fee2e2',
          color: '#991b1b', borderRadius: '10px', fontSize: '0.9rem',
        }}>
          ⚠️ {error}
        </div>
      )}

      {/* 結果表示 */}
      {result && (
        <div style={styles.resultCard}>
          {/* GO/NO-GO 判定 */}
          <div style={{ textAlign: 'center', marginBottom: '24px' }}>
            <div style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '8px', fontWeight: 600 }}>
              企画判定
            </div>
            <span style={styles.goNoGo(result.go_nogo)}>
              {result.go_nogo === 'GO' ? '✅ GO — 撮影開始OK' : '⚠️ 要再考'}
            </span>
            <p style={{ color: '#64748b', fontSize: '0.85rem', marginTop: '8px' }}>
              {result.recommendation}
            </p>
          </div>

          {/* タイトル候補 */}
          <div style={{ marginBottom: '20px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px', color: '#1e293b' }}>
              📊 タイトル候補（CTR予測付き）
            </h3>
            {result.title_candidates?.map((t, i) => (
              <div key={i} style={{
                ...styles.titleRow,
                border: t.title === result.best_title ? '2px solid #7C3AED' : '1px solid #f1f5f9',
                background: t.title === result.best_title ? '#faf5ff' : 'white',
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.92rem', fontWeight: t.title === result.best_title ? 700 : 500 }}>
                    {t.title === result.best_title && '⭐ '}{t.title}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                  <span style={styles.ctrBadge(t.predicted_ctr)}>
                    CTR {t.predicted_ctr.toFixed(1)}%
                  </span>
                  <span style={styles.verdictBadge(t.verdict)}>
                    {t.verdict}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* サムネイルコンセプト */}
          {result.thumbnail_concepts?.length > 0 && (
            <div style={{ marginBottom: '20px' }}>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px', color: '#1e293b' }}>
                🖼️ サムネイルコンセプト
              </h3>
              {result.thumbnail_concepts.map((concept, i) => (
                <div key={i} style={styles.thumbnailCard}>
                  <div style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '4px' }}>
                    案{i + 1}: {typeof concept === 'string' ? concept : concept.concept || concept.title || JSON.stringify(concept)}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 過去の学び */}
          {result.past_lessons?.length > 0 && (
            <div>
              <h3 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: '12px', color: '#1e293b' }}>
                📖 過去の学び（フィードバック蒸留）
              </h3>
              {result.past_lessons.map((lesson, i) => (
                <div key={i} style={styles.lessonCard}>
                  💡 {lesson}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
