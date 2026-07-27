# 改善タスク積み上げ — improvement_backlog.md

| ID | フェーズ | 改善内容 | 優先度 | 影響範囲 | 状態 |
|:---|:---|:---|:---|:---|:---:|
| IMP-001 | Phase 1 | ウィザードのステップ切替アニメーション（スライドトランジション） | 低 | 局所 | ✅ |
| IMP-002 | Phase 1 | ウィザード状態のlocalStorage永続化（ブラウザリロード対応） | 中 | コンポーネント | ✅ |
| IMP-003 | Phase 2 | QualityGateWorkerのcategory_reportフォールバック | 中 | コンポーネント | ✅ |
| IMP-004 | Phase 3 | StepReviewPanelの自動チェックアニメーション | 低 | 局所 | ✅ |
| IMP-005 | Phase 4 | ウィザード完了後のレンダリングAPI呼び出し | 高 | コンポーネント | ✅ |
| IMP-006 | 全体 | DirectorBriefing内SmartCut/YouTubeの二重配置整理 | 中 | 全体 | ✅ |
| IMP-007 | 全体 | サムネイル分析のGemini Vision API対応 | 中 | コンポーネント | ✅ |
| IMP-008 | 全体 | 投稿スケジュールのユーザー目標頻度設定UI | 中 | コンポーネント | ✅ |
| IMP-009 | Harness | ADK再配置 — SequentialAgentオーケストレーター廃止、ステージ内部エージェント化を将来検討 | 高 | 全体 | 🔜 Phase B-1 |
| IMP-010 | Harness | Evaluator に Gemini API 動的品質評価ロジック追加 | 中 | コンポーネント | 未着手 |
| IMP-011 | 憲法 §10 | 段階的レビュー統合 — チャンネル主⇔AIの承認フローの完全自動化 | 低 | 全体 | 未着手 |
| IMP-012 | 憲法 §22 | 国際化対応 — 多言語字幕・多言語UI基盤 | 低 | 全体 | 未着手 |
| IMP-013 | 監査 D-02 | Harness テストカバレッジ 60%→80%（test_smoke/test_e2e の pytest 統合） | 中 | テスト | 未着手 |
| IMP-014 | Harness | **4層分離アーキテクチャ実装**（Anthropic Workflow + Harness Middleware + Google API Gateway） | **最高** | **全体** | 🔜 Phase B |
| IMP-015 | Harness | **Architecture Fitness Function 8本構築**（bare-except/print/デュアルパス/Context分断 等の自動検出） | 高 | テスト | 🔜 Phase C |

## 完了率

**8/15 (53%)** — Phase B-1（4層アーキテクチャ実装）が最優先。Anthropic設計×Google APIデュアルベンダー戦略承認済み（2026-04-13）

