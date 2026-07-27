---
description: 統合監査（ハーネス実効性30項目 + パイプライン機能差分8項目 + 乖離度チェック24軸）を実行する。工数大タスク完了後や四半期レビュー時に発動。
---

# 統合監査ワークフロー（ハーネス恒常監査 + 乖離度チェック統合版）

> **目的**: ハーネス制度が機能し続けていること＋設計と実装の乖離がないことを一括検証する
> **根拠**: PROJECT_CONSTITUTION §25 + architecture_audit_v2.md + GAP_ANALYSIS_STANDARD.md
> **旧ワークフロー**: `/gap-check`（本ワークフローに統合済み）

---

## 監査の存在目的

本監査制度は、Antigravity の技術憲法（PROJECT_CONSTITUTION.md 全25条）が定めるシステム哲学
——「人智とAIの共鳴による、無限の個人制作エコシステム」——を、コードレベルで永続的に守護するために存在する。

以下の3つの問いに答え続ける：
1. 🛡️ **ガードレールは本当に発火しているか？**（Hook・Governance の空転防止）
2. 📊 **データは本当に流れているか？**（Session・Trace の接続性検証）
3. 🔄 **進化に追従できているか？**（モデル世代交代・SDK更新への対応力）

---

## 発動条件

| トリガー | 実施範囲 | 必須/推奨 |
|:---|:---|:---:|
| **コミット時** | D-01, E-01 | **必須** |
| **デプロイ時** | H-02, C-03, C-07, D-03, D-05 | **必須** |
| **週次** | H-03〜H-06, M-03 | 推奨 |
| **月次** | H-01, M-01〜M-04, C-04, C-05, D-02, D-04, E-02, E-04 | **必須** |
| **四半期** | **全45項目**（ハーネス30 + パイプライン差分8 + ビジネス7） + GAP_ANALYSIS 24軸フル | **必須** |
| **工数「大」タスク完了後** | 全45項目 | **必須** |
| **パイプライン構造変更時** | カテゴリ A + P | **必須** |
| **憲法改正・条項追加時** | カテゴリ A + C + F | **必須** |
| **新モデル導入時** | カテゴリ B + F | **必須** |
| **MARKET_RESEARCH更新時** | カテゴリ G | **必須** |

---

## 実施手順

### Phase 0: ドキュメント精読（準備）

1. 以下のドキュメントを精読し、最新の設計意図を把握する:
   - `backend/branding/PROJECT_CONSTITUTION.md` — 全25条
   - `backend/branding/VISION_JOURNAL.md` — ビジョンと情熱
   - `backend/branding/GAP_ANALYSIS_STANDARD.md` — 24軸チェック基準
   - `docs/USER_MANUAL.md` — UXストーリー（チャンネル主 + 管理者）
   - `docs/MARKET_RESEARCH_POLICY.md` — 業界ギャップ6項目
   - `docs/BACKLOG_MASTER.md` — バックログ進捗

---

### Phase 1: カテゴリ A — ハーネス構造的健全性（6項目）

ハーネス4モジュール（Hook / Session / Governance / ToolRegistry）の構造的な正しさを検証する。

// turbo
2. デュアルパス残存とADKオーケストレーター参照を検索する:
```
grep -rn "HARNESS_MODE\|SequentialAgent\|run_harness_pipeline" backend/routers/ backend/main.py 2>$null; if ($LASTEXITCODE -ne 0) { Write-Output "旧アーキテクチャ参照: 0件 ✅" }
```

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **H-01** | 実行パスの一本化（4層アーキテクチャ準拠） | HARNESS_MODE分岐・ADK SequentialAgent参照を検索 | 旧参照 = 0件 | Anthropic Workflow原則, 改善方針v2 |
| **H-02** | ToolRegistry SSoT | `tool_registry.get_tool()` で全7ツール取得 | 7/7登録済 | 原則3 |
| **H-03** | Hook 発火率 | 監査ログ数 / ツール呼び出し回数 | 100% | 原則6 |
| **H-04** | ガバナンス権限チェック適用率 | `check_permission()` 発火率 | 100% | 原則8 |
| **H-05** | セッション永続化成功率 | `_save_session()` 成功率 | 99%以上 | 原則7 |
| **H-06** | トレーススパン完結率 | `start_span` / `end_span` 対応率 | 100% | 原則2 |

3. 発見した乖離を深刻度（🔴致命/🟡重大/🟢注意）で分類する。

---

### Phase 2: カテゴリ B — モデルガバナンス（5項目）

§14 AI基盤技術管理、§18 コスト最適化の実効性を検証する。

// turbo
4. モデル直接指定を検索する:
```
python -c "import glob,re; files=[f for f in glob.glob('backend/**/*.py',recursive=True) if 'model_config' not in f and '__pycache__' not in f and 'test_' not in f]; hits=[f for f in files if re.search(r'gemini-|imagen-|veo-',open(f,'r',encoding='utf-8').read())]; print(f'モデル直接指定: {len(hits)}件 {chr(9989) if len(hits)==0 else chr(9888)}')"
```

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **M-01** | モデル直接指定の禁止 | model_config.json 以外でのモデル名直接記述 | 0件 | §14.1.1 |
| **M-02** | deprecated モデルの自動差替 | PreToolUse Hook ログ確認 | 100%差替 | §14.2 |
| **M-03** | 使用量追跡の正確性 | PostToolUse カウント vs daily_usage.json | 誤差 0% | §18.4 |
| **M-04** | フォールバックチェーン動作 | 429/503 時に自動降格 | 成功率 100% | §18.3 |
| **M-05** | 無料枠アラート発動 | 60%/80%/95%/100% 閾値テスト | 全4段階正常 | §18.4 |

---

### Phase 3: カテゴリ C — 憲法準拠・UX保証（7項目）

§7.3 UX最低保証規定 + GAP_ANALYSIS_STANDARD 第1層・第2層の実効性を検証する。

5. **チャンネル主目線**で以下を検証する:
   - C-01: UXストーリー完走率（O-1〜O-12 の各保証項目を実際に操作テスト）
   - C-03: 品質ゲート空転防止（意図的に低品質入力でブロック確認）
   - C-04: RAW素材保護（ストレージガバナンス連動確認）
   - C-05: 議長権限の尊重（ユーザー承認なき処理実行が0件）

6. **管理者目線**で以下を検証する:
   - C-02: UXストーリー完走率（A-1〜A-7 の各保証項目を実際に操作テスト）
   - C-06: ドキュメント同期率（CODE vs 憲法 vs MANUAL の記述一致）
   - C-07: 後退禁止の遵守（前回保証項目が全て動作するか）

| ID | 監査項目 | 合格基準 | 根拠 |
|:---|:---|:---|:---|
| **C-01** | UXストーリー完走率（チャンネル主） | 95%以上 | §7.3.1 |
| **C-02** | UXストーリー完走率（管理者） | 95%以上 | §7.3.2 |
| **C-03** | 品質ゲート空転防止 | ブロック率 100% | §8.2 |
| **C-04** | RAW素材保護 | 削除事故 = 0件 | §11.1 |
| **C-05** | 議長権限の尊重 | 無断実行 = 0件 | §6 |
| **C-06** | ドキュメント同期率 | 90%以上 | §24 |
| **C-07** | 後退禁止の遵守 | 後退 = 0件 | §7.3.3 |

---

### Phase 4: カテゴリ D — テスト・品質保証（5項目）

// turbo
7. 構文チェックを実行する:
```
python -c "import ast; import glob; files=glob.glob('backend/**/*.py', recursive=True); errors=[]; [errors.append(f) if not (lambda f: (ast.parse(open(f,'r',encoding='utf-8').read()),True)[-1])(f) else None for f in files]; print(f'{len(files)} files checked, {len(errors)} errors')"
```

// turbo
8. テストを実行する:
```
python -m pytest backend/harness/ --tb=short -q
```

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **D-01** | ユニットテスト全通過 | `pytest backend/harness/ -q` | 0 failed | §20.4 |
| **D-02** | テストカバレッジ | `pytest --cov=harness` | 60%以上 | §20.4 |
| **D-03** | E2Eパイプラインテスト | Workflow型 `pipeline_coordinator.execute()` 実行（Harness Middleware付き） | 成功率 100% | §20.1, 改善方針v2 |
| **D-04** | テストデータの安全性 | テストコード内の本番キー検索 | 0件 | §19.1 |
| **D-05** | async テスト互換性 | pytest-asyncio 設定確認 | 全通過 | §20 |

---

### Phase 5: カテゴリ E — セキュリティ・プライバシー（4項目）

// turbo
9. APIキーのハードコードを検索する:
```
python -c "import glob,re; files=glob.glob('backend/**/*.py',recursive=True); hits=[f for f in files if 'AIzaSy' in open(f,'r',encoding='utf-8').read()]; print(f'APIキー直接記述: {len(hits)}件 {chr(9989) if len(hits)==0 else chr(9888)}')"
```

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **E-01** | APIキー ハードコード禁止 | `grep "AIzaSy" backend/` | 0件 | §19.1 |
| **E-02** | ログマスキング | トレースログに API キー露出 | 0件 | §19.1 |
| **E-03** | アクセス制御 | localhost 制限確認 | 外部アクセス遮断 | §19.4 |
| **E-04** | セッションデータ保護 | `cleanup_old_sessions()` 動作 | 30日で自動削除 | §19.2 |

---

### Phase 6: カテゴリ F — 進化対応力（3項目）

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **F-01** | SDK互換性チェック | 最新SDK で全モデル利用可能か | 0件(またはFB済) | §14.4 |
| **F-02** | 新モデル追加手順 | config追加→パイプライン貫通 | 設定変更のみ | §14.1 |
| **F-03** | 憲法条項カバレッジ | §1-25 の対応実装存在 | 未実装 = 0 | §25 |

---

### Phase 7: カテゴリ G — ビジネス収益性（7項目）

> 旧 `/gap-check` の第3層（B-1〜B-9）を統合。月30万円チャンネル達成基準で検証する。
> 詳細基準は `GAP_ANALYSIS_STANDARD.md` 第3層を参照。

10. **ビジネス目線**で以下を検証する:
    - G-01: タイトル先行制作（企画→タイトル→CTR予測→撮影の順序が実装されているか）
    - G-02: 公開後PDCAループ（フィードバックデータが次の制作に還流するか）
    - G-03: ショート動画戦略（Shorts量産によるチャンネル発見性向上の基盤）
    - G-04: リテンション制御（Retention Mapがパイプラインに組み込まれているか）
    - G-05: サムネイル最適化（顔検出・可読性・コントラスト分析）
    - G-06: A/Bテスト自動化（サムネ・タイトルの最適化ループ）
    - G-07: ブランド一貫性（視覚的統一感の維持・管理機能）

| ID | 監査項目 | チェック方法 | 合格基準 | GAP軸対応 |
|:---|:---|:---|:---|:---|
| **G-01** | タイトル先行制作 | pre-plan API存在確認 | API実装済 | B-1 |
| **G-02** | 公開後PDCAループ | フィードバック→evolution_log 接続 | 接続済 | B-2 |
| **G-03** | ショート動画戦略 | Shorts量産基盤の有無 | 基盤存在 | B-3 |
| **G-04** | リテンション制御 | RetentionMap パイプライン接続 | 接続済 | B-4 |
| **G-05** | サムネイル最適化 | 顔検出・可読性分析の実装 | 実装済 | B-5 |
| **G-06** | A/Bテスト自動化 | 最適化ループの実装 | 実装済 | B-8 |
| **G-07** | ブランド一貫性 | design_tokens.json 適用率 | 100% | B-9 |

---

### Phase 7.5: カテゴリ P — パイプライン機能差分分析（8項目）

> 旧スクリプト（`src/` フォルダ）で実稼働していた自動編集機能が、ハーネス統合版で漏れなく再現されているかを検証する。
> 差分分析の詳細は **Phase 8 の差分分析レポート（別出し）** に記録する。

> [!CAUTION]
> **2層検索原則 (v1.5.0新設)**:
> 機能の有無を検索で判定する際、**呼び出し元（Worker）だけでなく、依存エンジン（呼び出し先モジュール）も必ず検索すること。**
> Worker内で直接実装されず、エンジン側に委譲されている機能を「未実装」と誤判定すると、不要なバックログ積み上げと将来の手戻り極大化を招く。
> 根拠: P-02誤判定事例 — `pipeline_coordinator.py`のみ検索→リトライ未実装と判定、実際は`ai_proofreader.py`にFIX-2A完全実装済み。

// turbo
10.5. テキスト整形の統合確認（2層検索: coordinator + text_formatter）:
```
python -c "import re; files=['backend/agents/pipeline_coordinator.py','backend/subtitle_engine/text_formatter.py']; [print(f'{f}: format_segments found') for f in files if re.search(r'format_segments', open(f,'r',encoding='utf-8').read())]"
```

// turbo
10.5.1. AI校閲リトライの統合確認（2層検索: coordinator + ai_proofreader）:
```
python -c "import re; f='backend/subtitle_engine/ai_proofreader.py'; content=open(f,'r',encoding='utf-8').read(); retries=len(re.findall(r'retry|RETRIES',content)); backoff=len(re.findall(r'BACKOFF|backoff',content)); err=len(re.findall(r'429|503|quota',content,re.I)); print(f'ai_proofreader.py: retry={retries} backoff={backoff} error_patterns={err} {chr(9989) if retries>0 and backoff>0 else chr(9888)}')"
```

// turbo
10.6. MoviePy残存参照を検索（コメント除外版）:
```
python -c "
import re, glob
files=[f for f in glob.glob('backend/**/*.py',recursive=True) if '__pycache__' not in f]
code_hits=[]
for f in files:
    for i,line in enumerate(open(f,'r',encoding='utf-8').readlines(),1):
        stripped=line.lstrip()
        if stripped.startswith('#') or stripped.startswith('\"\"\"'): continue
        if re.search(r'import\s+moviepy|from\s+moviepy|MoviePy\s*\(|TextClip\s*\(|ImageClip\s*\(',line):
            code_hits.append(f'{f}:{i}')
print(f'MoviePy実行コード参照: {len(code_hits)}件 {chr(9989) if len(code_hits)==0 else chr(9888)}')
for h in code_hits: print(f'  {h}')
"
```

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **P-01** | テキスト整形ロジック復元 | `format_segments()` が coordinator + text_formatter で呼び出されているか（2層検索） | 呼び出し確認済 | FIX-3A |
| **P-02** | AI校閲リトライ | **`ai_proofreader.py`** に429/503リトライ実装があるか + coordinator側でリトライ統計を受け取るか（2層検索） | リトライ実装済 + 統計伝搬 | FIX-2A |
| **P-03** | 品質ゲート基準調整 | テンプレート未設定時にスコア80点以上取得可能か | >= 80点 | FIX-7A |
| **P-04** | フォント自動縮小 | 長文セグメントが字幕枠を超過しないか | 18文字/行以内 | FIX-3A依存 |
| **P-05** | ロゴ重畳機能 | ロゴオーバーレイが実装されている or 設計文書が存在するか | 実装済 or 設計文書 | FIX-6A |
| **P-06** | BGM統合 | audio_master.py がパイプラインに接続されているか | 接続済 or 設計文書 | FIX-6B |
| **P-07** | 旧スクリプト機能マッピング | 8機能全てがハーネス版で対応済か | 対応率 100% | 差分分析 |
| **P-08** | SmartCut Engine移行 | MoviePy → FFmpeg の完全移行確認（コメント除外検索） | MoviePy実行コード参照 = 0 | 差分分析 |

10.7. 発見した乖離を深刻度（🔴致命/🟡重大/🟢注意）で分類する。


---

### Phase 7.7: カテゴリ V — 自動編集機能実効性検証（12項目）— v1.4.0新設

> 各自動編集機能が「ユーザーが違和感なく継続的に実働できる品質」を満たしているかを検証する。
> 分岐カバレッジ(カテゴリD)とは独立した「実用品質」の監査軸。
> 詳細なFV検証テーブルは `/qa-audit` §2 を参照。

10.8. **自動編集機能ごとの実効性を検証する**:

| ID | 監査項目 | チェック方法 | 合格基準 | 根拠 |
|:---|:---|:---|:---|:---|
| **V-01** | 文字起こし精度 | WER(Word Error Rate)計測 | ≤ 15% (日本語) | §7.3.1 O-2 |
| **V-02** | AI校閲品質 | 過修正(不要修正)率計測 | ≤ 10% | §7.3.1 O-3 |
| **V-03** | SmartCutカット品質 | 重要シーン保持率計測 | ≥ 90% | §7.3.1 O-4 |
| **V-04** | プレビュー画質十分性 | 字幕判読可能性をBrowser確認 | 判読可能 | §9 |
| **V-05** | 品質ゲートスコア信頼性 | 手動評価との相関計測 | ≥ 0.7 | §8.2 |
| **V-06** | レンダリング音声品質 | ラウドネス(LUFS)計測 | -16±2 LUFS | §8.2 |
| **V-07** | YouTubeメタデータ品質 | タイトル長/タグ数/チャプター精度 | 基準値以上 | §7.3.1 O-9 |
| **V-08** | UXストーリー完走率(E2E) | Browser Agent全UXストーリー検証 | 100% PASS | §7.3 |
| **V-09** | UXストーリー更新同期 | USER_MANUAL §3.2との整合 | 乖離0件 | §7.3.3 |
| **V-10** | 設計妥当性レビュー完了 | FV初回合格率+修正イテレーション | FV初回≥70%, 修正≤3回 | v3.5 |
| **V-11** | 差分分析レポート存在 | UXストーリー充足レポート保存確認 | 全機能分存在 | v3.5 |
| **V-12** | 設計見直し判定記録 | Phase完了時のレビュー記録存在 | 全Phase分存在 | v3.5 |

10.9. **UXストーリー駆動ブラウザE2E検証を実行する**:

1. UXストーリー(O-1〜O-12)が最新の実装を反映しているか確認
2. UXストーリーからE2Eゴールシートを導出
3. Browser AgentがゴールシートのとおりUIを操作+検証
4. UXストーリー × E2Eゴールの充足マトリクスを更新
5. 未充足UXストーリーがある → 是正アクションに記録
6. **完了判定: 全UXストーリーの全E2Eゴールが PASS**

10.10. **設計妥当性レビュー結果を検証する**:

1. 各Phaseの設計妥当性レビュー記録が存在するか確認
2. 設計見直し判定が「重大」だった場合、改訂計画の存在と承認記録を確認
3. 設計見直し後の再レビュー結果が合格であることを確認

---

### Phase 8: レポート作成

11. 以下のテンプレートに沿ってレポートを作成する:

```markdown
# 統合監査レポート — [日付]

## 点検概要
- 点検トリガー: [コミット / デプロイ / 月次 / 四半期 / 工数大タスク完了]
- 点検対象: [全37項目 / カテゴリX のみ]

## カテゴリ A: ハーネス構造的健全性
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ B: モデルガバナンス
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ C: 憲法準拠・UX保証
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ D: テスト・品質保証
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ E: セキュリティ・プライバシー
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ F: 進化対応力
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ G: ビジネス収益性
| ID | 結果 | 備考 |
|:---|:---:|:---|

## カテゴリ P: パイプライン機能差分
| ID | 結果 | 備考 |
|:---|:---:|:---|

## スコアカード
| 指標 | 前回 | 今回 | 変化 |
|:---|:---:|:---:|:---:|
| 致命的不合格 | | | |
| 重大不合格 | | | |
| ハーネス健全性 | | | |
| パイプライン機能差分 | | | |
| UX完走率 | | | |
| ビジネス達成度 | | | |

## 是正アクション
1. ...
```

11.5. **差分分析レポート（別出し）** を以下のテンプレートで生成する:

> [!IMPORTANT]
> 差分分析レポートは監査レポートとは別ファイルとして生成すること。
> ファイル名: `pipeline_gap_analysis_report_[日付].md`

```markdown
# パイプライン機能差分分析レポート — [日付]

## 分析概要
- 旧スクリプト: `src/` フォルダ + `antigravity_phase18_stable_v1/backend/`
- 現アーキテクチャ: `backend/` (ハーネス統合版)
- 分析トリガー: [監査タイプ]

## ファイルマッピング
| # | 編集機能 | 旧スクリプト | 現ハーネス版 | 判定 |
|---|---|---|---|---|
| 1 | 文字起こし | src/transcribe.py | subtitle_engine/whisper_subprocess.py | ✅/⚠️/❌ |
| 2 | AI校閲 | src/ai_proofreader.py | subtitle_engine/ai_proofreader.py | ✅/⚠️/❌ |
| 3 | テキスト整形 | src/clean_linguistic.py | subtitle_engine/text_formatter.py | ✅/⚠️/❌ |
| 4 | SmartCut構成 | (手動選択) | agents/pipeline_coordinator.py SmartCutWorker | ✅/⚠️/❌ |
| 5 | 動画カット＆字幕 | phase18/smart_cut_engine.py | smart_cut_engine.py | ✅/⚠️/❌ |
| 6 | 字幕レンダリング | src/render_a_plus_plus.py | smart_cut_engine.py _burn_subtitles_ffmpeg() | ✅/⚠️/❌ |
| 7 | 音声マスタリング | (BGMのみ) | audio_master.py | ✅/⚠️/❌ |
| 8 | 最終レンダリング | src/workflow_utils.py | video_editor_engine.py | ✅/⚠️/❌ |

## 機能ごとの詳細差分
### [機能名]
| 項目 | 旧 | 現 |
|---|---|---|

**判定**: ✅/⚠️/❌
**修正アクション**: (該当FIX-ID)

## 修正アクションまとめ
| 優先度 | ID | 修正内容 | 状態 |
|---|---|---|---|

## サマリー
- 対応完了: X/8 機能
- 要修正: X件
- 未対応: X件
```

12. スコアカード（GAP_ANALYSIS_STANDARD §6 の8項目 + ハーネス健全性）を更新する。

### Phase 9: 修正実行

13. 致命的（🔴）→ 重大（🟡）→ 注意（🟢）の順に修正を実行する。

### Phase 10: 検証・合格判定

// turbo
14. 構文チェックを実行する:
```
python -c "import ast; import glob; files=glob.glob('backend/**/*.py', recursive=True); errors=[]; [errors.append(f) if not (lambda f: (ast.parse(open(f,'r',encoding='utf-8').read()),True)[-1])(f) else None for f in files]; print(f'{len(files)} files checked, {len(errors)} errors')"
```

// turbo
15. テストを実行する:
```
python -m pytest backend/harness/ --tb=short -q
```

16. 合格基準を確認する:
    - [ ] 致命的不合格: 0件
    - [ ] 重大不合格: 3件以内
    - [ ] ハーネス健全性スコア（カテゴリA全通過率）: 100%
    - [ ] UXストーリー完走率: 95%以上
    - [ ] 構文チェック: 全ファイルOK
    - [ ] pytest: 全テスト通過

17. 合格した場合、`GAP_ANALYSIS_STANDARD.md` §7 の点検履歴に記録する。

---

## 合格基準

| 指標 | 最低基準 | 推奨基準 |
|:---|:---:|:---:|
| 致命的不合格（Hook空転・権限未チェック・データフロー断絶） | **0件** | 0件 |
| 重大不合格（テスト失敗・ドキュメント乖離・アラート不発動） | 3件以内 | 0件 |
| ハーネス健全性スコア（カテゴリA全通過率） | **100%** | 100% |
| モデルガバナンス適合率（カテゴリB全通過率） | **90%以上** | 100% |
| パイプライン機能差分（カテゴリP対応率） | **75%以上** | 100% |
| UXストーリー完走率 | **95%以上** | 100% |
| ビジネス達成度 | **40%以上** | 80% |
| ドキュメント同期率 | **90%以上** | 100% |

---

## 深刻度分類

| レベル | 表記 | 基準 | 対応期限 |
|:---|:---:|:---|:---|
| **致命的** | 🔴 | Hook空転・ガバナンス無効・セッション消失・データフロー断絶・品質ゲート空転 | **即時修正** |
| **重大** | 🟡 | テスト失敗・ドキュメント乖離・アラート不発動・UX低下 | 次リリースまで |
| **注意** | 🟢 | 軽微な設定漏れ・推奨基準未達・将来機能 | 随時 |

---

## 改定履歴

| バージョン | 日付 | 変更内容 |
|:---|:---|:---|
| 1.0.0 | 2026-04-11 | 初版制定。6カテゴリ・30項目の恒常監査フレームワーク確立 |
| 1.1.0 | 2026-04-11 | `/gap-check` ワークフローを統合。カテゴリ G（ビジネス収益性7項目）追加、合計37項目に拡張。Phase 0（ドキュメント精読）追加 |
| 1.2.0 | 2026-04-13 | カテゴリ P（パイプライン機能差分分析8項目）追加、合計45項目に拡張。Phase 7.5 追加。Phase 8 に差分分析レポート別出し手順を追加 |
| 1.3.0 | 2026-04-13 | Anthropic設計×Google APIアーキテクチャ改善方針v2を反映。H-01をADKオーケストレーター廃止＋4層アーキテクチャ準拠に変更。D-03をWorkflow型パイプライン実行に変更 |
| **1.4.0** | **2026-04-19** | **カテゴリ V（自動編集機能実効性検証12項目）追加、合計57項目に拡張。Phase 7.7 追加。UXストーリー駆動ブラウザE2E + 設計妥当性レビューの監査手順を統合** |
