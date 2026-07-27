# 設計ストック: カバレッジ向上 + UXエビデンス獲得 Phase 2 突破計画

## 目標
- カバレッジ: 1.5% → 50%
- UX PASS (エビデンス付き): 0 → 300件

## 優先モジュール群 (カバレッジ寄与が最大のもの)

### Tier 1: コアパイプライン (最大のコード量、最大のカバレッジ寄与)
- [ ] `backend/video_pipeline/smart_cut_engine.py` — SmartCutエンジン本体のユニットテスト
- [ ] `backend/video_pipeline/audio_extractor.py` — 音声抽出のユニットテスト
- [ ] `backend/video_pipeline/subtitle_generator.py` — 字幕生成のユニットテスト
- [ ] `backend/video_pipeline/video_concatenator.py` — 動画結合のユニットテスト
- [ ] `backend/video_pipeline/thumbnail_generator.py` — サムネイル生成のユニットテスト

### Tier 2: エージェント層 (中規模コード量)
- [ ] `backend/agents/director.py` — ディレクターエージェントのユニットテスト
- [ ] `backend/agents/soul_engine.py` — ソウルエンジンのユニットテスト
- [ ] `backend/agents/council/nexus_council.py` — 評議会エンジンのユニットテスト

### Tier 3: ルーター層 (API応答テスト)
- [ ] `backend/routers/pipeline_router.py` — パイプラインAPIのユニットテスト
- [ ] `backend/routers/admin_setup_router.py` — 管理画面APIのユニットテスト

### Tier 4: オーケストレーション層 (自走インフラ)
- [ ] `backend/agents/orchestration/hub_batch.py` — バッチ生成のユニットテスト
- [ ] `backend/agents/orchestration/hub_gate.py` — ゲート判定のユニットテスト

## UXストーリー エビデンス獲得計画
- O-1 (素材選択): L1-L2 の7項目 → API応答テストでエビデンスを記録
- O-2 (文字起こし): L1-L2 の7項目 → Whisperモック + 応答検証でエビデンスを記録
- O-3 (校正): L1-L2 の7項目 → 校正APIの応答検証でエビデンスを記録
- O-4 (SmartCut): L1-L2 の7項目 → エンジン出力の検証でエビデンスを記録
- O-5 (調整): L1-L2 の7項目 → 調整パラメータ検証でエビデンスを記録

## タスク生成ルール
- 各テストは `assert` + `evidence文字列` を必ず含めること
- モックを使う場合でも、プロダクションコードの内部ロジックを実際に通過させること
- テスト成功時に `snapshot.py` の `save()` を通じてエビデンスを記録すること
