# 設計ドラフト: 技術負債 (TDR) 残り478件の「自律解消」に向けたバッチ処理設計 (IMP-TDR)

## 概要
現在、技術負債台帳 (TDR) に open 状態で記録されている非クリティカル技術負債 478件を、プロダクションコードにデグレードを起こさずに安全かつ迅速に解消させるための「Flash用リファクタリング・ディレクティブ」の設計書ドラフト。

## 主な変更対象
- `backend/agents/memory/technical_debt.py` の `TechnicalDebtStore`
- `backend/agents/orchestration/opus_directive.json` (ブラックリストの自動更新設定)

## セルフチェックリスト / 完了条件
- [ ] 全 478 件のうち、安全に自動解消可能なパターン（DP-01〜DP-06）の自動置換スクリプトの作成
- [ ] 修正モジュールのテストカバレッジが 100% であること
- [ ] `pytest backend/tests/test_fitness_functions.py` が PASS すること
