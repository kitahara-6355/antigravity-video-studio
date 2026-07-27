# GEMINI.md — Antigravity Video Automation Pipeline

## 最優先ルール

- 破壊的操作はユーザー承認必須 (Core Rules S9)

- TDD: 1-Test, 1-Implement ループ厳守 (S11)

- デバッグは仮説→ログ→検証のクローズドループ (Manifesto C9)

- 設計判断時は対立仮説を検証 (S13: Opponent Processor)

- ファイルアクセス制限:

  - **Deny**: .env, *.key, vault-assets/raw/*

  - **Ask**: PROJECT_CONSTITUTION.md, VERIFIED_FACTS.md, branding/

## アーキテクチャ参照

- 設計プロトコル: .agent/Anthropic_Core_Rules.md

- ユーザー哲学: .agent/User_Persona_Manifesto.md

- 憲法: backend/branding/PROJECT_CONSTITUTION.md

- 検証済みファクト: backend/agents/memory/VERIFIED_FACTS.md

- 設定マップ: .agent/config_index.json

## 実行前チェック

- pytest backend/tests/test_fitness_functions.py 全PASS必須

- FV検証: /qa-audit §2 参照

- UXストーリーE2E: /qa-audit §3 参照

## UX検証連動 (2026-04-29 制定)

- **ルールブック**: .agent/ux-verification-rulebook.md (全ルールの原典)

- **必須**: UXストーリー更新時はルールブック §3 の6ステップを厳守

- **ラチェット**: 検証項目数/連動率/PASS数の3指標は前回以上であること

- **自動検証**: `pytest tests/test_ux_ratchet.py` — 連動率≥85% + 5層分布 + 項目数保証

- **参照ファイル**:

  - ストーリー定義: `backend/ux_verification/stories/*.json`

  - スナップショット: `backend/ux_verification/snapshots/v*.json`

  - ラチェット機構: `backend/ux_verification/ratchet.py`

## エスカレーション条件 (EP)

- テスト3回連続FAIL → 即停止+レポート

- 3ファイル以上の同時変更 → ユーザーに設計確認

- 憲法/VerifiedFactsとの矛盾検出 → 即停止

- 推測での修正禁止 → 根拠不明なら停止して質問

- **[EBVP] 推測でのテスト結果報告禁止** → 未検証スコープは「未検証」と明示。「可能性があります」等の推測表現は使用禁止

- **[EBVP] ベースライン未照合の非退行主張禁止** → 構造化証拠レポート(EBVP §3.5)を必須添付

- **[EBVP] テスト失敗の暗黙分類禁止** → 全失敗をK(既知)/N(新規)にテスト名レベルで分類。推測による「既知」分類は禁止

## subprocess.Popen モック安全規約 (2026-04-27 制定)

- **原因**: `_run_ffmpeg`等の内部スレッド(`while process.poll() is None`)がMockの`poll()`で無限ループし、テストが永久ハングする

- **必須ルール**:

  1. `poll()` は `return_value=0`（または非None値）で即座に終了コードを返すこと。`side_effect=[None, 0]`は禁止

  2. `readline()` は空文字列 `""` を返すこと（MagicMockデフォルトの自動応答は無限ループの原因）

  3. conftest.py の `safe_popen_mock` fixture を使うこと（安全なデフォルト値が設定済み）

  4. pytest.ini の `timeout = 60` により、万一のハングは60秒で強制終了される

- **参照**: `tests/conftest.py` の `safe_popen_mock` fixture

## 心拍レジリエンス規約 (2026-05-27 制定)

- **原因**: PCリソース逼迫（CPU/メモリ/ディスク飽和）時にFlashセッションの心拍更新が遅延し、Opus側のヘルスチェックが30分閾値で`auto_stop`を発動。セッションは生存しているにも関わらずHub連携が断絶し、成果がロストするインシデントが発生（2026-05-26夜間）
- **必須ルール**:
  1. **自動停止は3段階**: STALE(15-30分)=警告のみ / UNREACHABLE(30-60分)=`heartbeat_warning`フラグ記録だがHub連携維持 / DEAD(60分超)=`stopped`（Hub断絶）
  2. **自動復旧**: `flash_heartbeat()`または`flash_update_heartbeat()`が呼ばれた際、`auto_stop_reason`が設定されていれば自動的に`running`へ復旧する
  3. **タイマー発火時の心拍更新必須**: Flash自走ループのタイマー発火プロンプトには`hub.flash_update_heartbeat()`の実行を**最優先（Step 0）**として含めること
  4. `flash_update_heartbeat()` はバッチカウントを増やさず心拍のみ更新する軽量メソッドであり、バッチ処理の遅延に依存しない独立した心拍更新手段として使用する
- **自動検証**: `pytest backend/tests/test_fitness_functions.py` — 全テストPASS必須
- **参照**: `backend/agents/orchestration/health_check.py` の `_auto_stop_stale_session()`, `backend/agents/orchestration/orchestrator.py` の `flash_update_heartbeat()` / `flash_heartbeat()`

## Flash完遂後リソース解放規約 (2026-05-28 制定)

- **原因**: Flashセッションが全タスクを完遂し`ended`状態になった後も、Antigravity 2プロセス内の残存サブエージェント・バックグラウンドタスク・タイマーがCPUを消費し続け、PCのCPU 80%超が7時間以上継続。Antigravity UIがフリーズし操作不能になるインシデントが2回発生（2026-05-26, 2026-05-28）
- **必須ルール**:
  1. **クリーンシャットダウン義務**: Flashセッション完遂時（`flash_session_end()`呼出後）、以下を**必ず**実行すること:
     - `manage_subagents` → `kill_all`（全サブエージェント停止）
     - `manage_task` → `kill_all`（全バックグラウンドタスク停止）
     - 新規タイマー（`schedule`）の設定を**禁止**
     - ワークスペース閉鎖案内をチャットUIに表示
     - 上記表示後、一切のツール呼び出しを行わず応答を終了
  2. **Opus側の自動案内**: `health_check.py` が `ended` ステータスを検知した際、「Flash側チャットを閉じてください」と自動表示すること
  3. **UIフリーズ復旧手順**: 段階的に以下を実施
     - Step 1: Flash側チャットを閉じる → CPU大幅低下
     - Step 2: 改善しなければ → Antigravityアプリ全体を終了
     - Step 3: 改善しなければ → PC再起動（最終手段）
  4. **generate_flash_prompt.py の完遂プロトコル§6**: Step 4「クリーンシャットダウン」を必須ステップとして含めること
- **参照**: `generate_flash_prompt.py` §6 Step 4, `.agent/workflows/flash-autonomous-entry.md` クリーンシャットダウンセクション, `health_check.py` R7改

## 動的リソース適応型並列制御規約 (2026-06-15 制定)

- **原因**: Flashセッション開設直後にサブエージェント6件が同時起動し、CPU 50-70%・メモリ80%に達してAntigravity UIがフリーズする問題が繰り返し発生（2026-05-26, 2026-05-28, 2026-06-15）。静的な並列数制限はユーザーが望まないため、リソース状態に応じた**動的制御**を採用する
- **設計哲学**: 「静的に制限する」のではなく「リソース状態を見て動的に最大化する」。UIフリーズの閾値を超えそうな場合のみ並列数を一時的に絞り、リソースに余裕がある場合はプロファイル定義の最大並列数で動作する
- **3層防御アーキテクチャ**:
  1. **層1: 段階的ウォームアップ（Graduated Warm-up）**
     - Flashセッション開設後の**最初のバッチのみ**、サブエージェントを**2件ずつ**起動（現在は`batch_size`件同時）
     - 各サブエージェント起動間に**30秒のインターバル**を設定
     - 2バッチ目以降は通常のbatch_size（プロファイル定義値）で起動
     - 設定値: `user_schedule.json` の `warmup_batch_size`（デフォルト: 2）、`warmup_interval_seconds`（デフォルト: 30）
  2. **層2: リアルタイム動的スロットリング（Dynamic Throttling）**
     - `ResourceGovernor.check_host_resources()` の閾値を3段階に拡張:
       - 🟢 NORMAL: CPU<50% AND メモリ<63% → 通常並列数（プロファイル値）
       - 🟡 CAUTION: CPU≥50% OR メモリ≥63% → 新規サブエージェント起動を30秒遅延
       - 🔴 CRITICAL: CPU≥70% OR メモリ≥75% → 新規サブエージェント起動を完全停止、稼働中のサブエージェント完了待ち
     - Flashの`flash-autonomous-entry.md`ワークフロー内で、サブエージェント起動前に`check_host_resources()`を呼び、CRITICALなら起動を保留
     - **静的制限ではない**: リソースに余裕があればプロファイル定義の最大並列数がそのまま適用される
  3. **層3: セッション間リソース分離**
     - OpusのCronヘルスチェックは、Flashセッションが`running`状態の場合、`--update-dashboard`を**2回に1回スキップ**（ダッシュボード更新の負荷軽減）
     - 心拍チェック・ナッジ送信は引き続き毎回実行（安全性維持）
- **改善サイクル（PDCA — 月1回レビュー）**:
  1. **Plan**: 層2の3段階閾値（CPU 50/70%, メモリ 70/80%）を仮設定
  2. **Do**: 1週間の実運用。`resource_state.json` にCPU/メモリのピーク値を記録
  3. **Check**: 月1回、UIフリーズ発生回数（0回が目標）・リソーススロットリング発動回数・平均並列稼働数を分析
  4. **Act**: 分析結果に基づき閾値を調整。UIフリーズ0回＋平均並列数最大化のバランスを探る
- **不整合解消済み（2026-06-22）**: `flash-autonomous-entry.md` の `MAX_PARALLEL=6` 静的制限を、`user_schedule.json` のプロファイル `batch_size` に基づく動的制御に更新済み。GEMINI.md規約のメモリ閾値も実装値（CAUTION=63%, CRITICAL=75%）に統一済み
- **自動検証**: ダッシュボード（②詳細版）の「🛡️ 稼働安定性指標」にリソーススロットリング発動回数・ピークCPU/メモリを追加
- **参照**: `backend/agents/orchestration/resource_governor.py` の `check_host_resources()`, `user_schedule.json` のFlashプロファイル

## ダッシュボードリンク安全規約 (2026-05-26 制定 / 2026-07-26 相対リンクへ改訂)

- **原因**: `get_rel_link()` がスペース(`Human01_Official Artifact`)や日本語文字(`サブエージェント体制報告`)をURLエンコードせずにMarkdownリンクを生成し、リンク切れが発生した
- **2026-07-26 の改訂理由**: 対策として導入した `file:///C:/Users/.../script/video-automation/...` という**生成環境の絶対パス**が、別の環境依存を生んでいた。別チェックアウト（worktree）・CI(Linux)・配布先ではリンクが1本も解決できず、FF-27L が135件全滅した。フォルダを移動しただけでも全リンクが死ぬ。リポジトリ内のファイルは**リポジトリ相対で正確に書ける**ため、相対リンクへ統一する。
- **必須ルール**:
  1. ダッシュボード内の全リンクは `get_rel_link()` 関数を経由して生成すること（直接文字列結合は禁止）
  2. `get_rel_link()` は**リポジトリルート相対**のパスを返すこと。絶対パス・ドライブレター・ホームディレクトリを含めてはならない
  3. `get_rel_link()` は `urllib.parse.quote()` でスペースを `%20`、非ASCII文字を `%E3%82%B5...` 等にエンコードすること（ディレクトリ区切り `/` はエンコードしない）
  4. 書き込み先ファイルの階層に合わせた付け替えは `localize_links(markdown, target_dir)` が行う。README を新たに出力する場合は必ず通すこと
  5. リポジトリ**外**のファイル（Antigravity の brain ディレクトリ等）は相対で書けないため `file:///` にフォールバックする。リポジトリ内のファイルに `file:///` を使ってはならない
  6. 新規レポートファイルを追加する場合、出力先パスを `get_rel_link()` に渡してリンクを生成し、ダッシュボードに反映すること
  7. `generate_dashboard_quick()` はREADME.md書き込み直後に `validate_dashboard_links()` を自動実行すること。リンク切れ検出時は `stderr` に警告を出力し `event_log.jsonl` に記録すること
  8. リンク生成ロジックを変更する場合、変更後に `pytest backend/tests/test_fitness_functions.py::TestFF27DashboardLinkageValidator backend/tests/test_dashboard_relative_links.py` を実行してPASS確認すること（手動確認は不可）
- **自動検知サイクル**: `generate_dashboard_quick()` → README.md書き込み → `validate_dashboard_links()` 即時検証 → リンク切れあれば `event_log.jsonl` に記録 → Opus巡回（5分Cron）でイベント検知・報告
- **自動検証**:
  - `FF-27L` (`test_dashboard_file_links_resolve`) — 全リンクが解決できること
  - `FF-27A` (`test_dashboard_has_no_absolute_paths`) — `file:///` や `C:/Users` が残っていないこと
  - `backend/tests/test_dashboard_relative_links.py` — 相対リンクの生成・付け替え・検証
- **参照**: `backend/agents/orchestration/link_validator.py` の `get_rel_link()` / `localize_links()` / `validate_dashboard_links()`

## ファイルI/O安全規約 (2026-05-05 制定)

- **原因**: PowerShellの`Add-Content`/`Set-Content`はシステムデフォルト(CP932)でファイルを書き込み、UTF-8ファイルを破損する(M3.6 G11-G20で発生)

- **必須ルール**:

  1. UTF-8ファイルへの追記・書込みは**Python経由**で行うこと。`open(path, "a", encoding="utf-8")` を使用

  2. PowerShellの`Add-Content`/`Set-Content`はUTF-8ファイルに対して**使用禁止**

  3. 大規模ファイル(5,000行超)は直接編集不可 → Python appendスクリプトで追記

  4. 出力トークン制限(64K)対策: 1バッチ10-20関数を上限とし、必要に応じてテンプレート関数方式(`make_test()`)で生成スクリプトサイズを削減

  5. 生成に使用した一時スクリプトは実行完了後に必ず削除

- **参照**: `conv_3c7add26_session_report_g11_g20.md.resolved` (CP932汚染の根本原因分析)

## 技術負債台帳規約 (2026-05-10 制定 / VF同型JSON管理化)

- **台帳**: `backend/agents/memory/technical_debt_index.json` (正データ) + `backend/TECHNICAL_DEBT_REGISTRY.md` (自動生成ビュー)

- **API**: `backend/agents/memory/technical_debt.py` — `TechnicalDebtStore` (VF同型)

  - 登録: `store.register_debt(category, file_path, line_number, pattern, ...)`

  - 解消: `store.resolve_debt(debt_id, fixed_by, fix_evidence)`

  - 許容: `store.accept_debt(debt_id, reason)`

- **手動編集禁止**: `TECHNICAL_DEBT_REGISTRY.md` はAPI経由で自動生成。直接編集禁止

- **ラチェット**: `pytest backend/tests/test_fitness_functions.py::TestFF26TechnicalDebtRegistry` — CRITICAL open件数の非増加保証

- **必須ルール**:

  1. 新規 `except Exception` の追加は `register_debt()` API経由で登録**必須**。登録なしの追加は禁止

  2. Router層の `except Exception` には必ず `except HTTPException: raise` を前行に配置

  3. テストでの `status_code in (..., 500)` 許容（TECH_DEBTマーカー）は新規追加**禁止**

  4. 負債発生要因パターン(DP-01〜DP-06)に該当する実装を検出した場合、台帳に記録

  5. 解消時は `resolve_debt(evidence='pytest結果等')` で証拠を必ず記録

## カバレッジ改善規約 (2026-05-13 制定)

- **原因**: Sprint 4.3.3で「85%」定量目標から逆算してテストを設計した結果、「80%を達成するためだけの実装」リスクが発生。compound_debt_zero_analysis (2026-05-10) で確立した「複利的負債ゼロ」原則との乖離を検出。

- **原典**: `coverage_target_validation_report.md` (conv_1987883d)

- **適用範囲**: カバレッジ改善Sprintだけでなく、**全Sprint/Phase設計時**に適用

- **必須ルール**:

  1. カバレッジ改善Sprintの設計時、**数値目標の設定前に**変更マップ分析を実施すること

  2. 未カバー行を以下のA/B/C分類で質的評価すること:

     - **(A) 直接変更**: 次Sprint/Phaseで当該コードを直接変更する → **カバー必須（100%）**

     - **(B) 依存基盤**: 次Sprint/Phaseの新規コードが当該モジュールに依存 → **推奨カバー**

     - **(C) 単純負債**: 変更に無関係 → **TDR登録で管理**（数値%目標の対象外）

  3. カバレッジ改善Sprintの完了条件は以下の3層構造とすること:

     - **必須**: (A)分類行のカバレッジ = 100%（回帰検出能力の保証）

     - **参考**: Combined Branch ≥ N%（定量ゲート、目安値）

     - **記録**: (C)分類行の全件TDR登録（`batch_X_residual`タグ）

  4. 定量目標（85%, 90%等）はA/B/C分類の**結果として達成される参考値**であり、**達成すべき目標として設定してはならない**

  5. **機能Sprint設計時の事前カバー義務**: 新機能/変更を設計する際、変更対象モジュールの現行カバレッジを確認し、

     未カバーの変更予定行がある場合は**機能実装前にカバーテストを設計書に含める**こと（後追いカバレッジSprintを不要にするための予防策）

- **検証タイミング**: カバレッジ改善Sprintの設計書レビュー時（🔴設計モード）

- **違反検出**: Sprint設計書にA/B/C分類表がない場合、エスカレーション条件(EP)に該当

- **参照**: `compound_debt_zero_analysis.md` (conv_ce3d2282), MASTER L1972-1989

## 証拠駆動型検証プロトコル (EBVP, 2026-05-16 制定)

- **原因**: Sprint 4.3.4 Batch 3で「E2E 911 failed → 環境依存の可能性」と推測で記述。

  検証なしにE2Eを除外し、都合の良い結論を導いた。A/B比較で退行0件を事後的に証明したが、

  報告時点では根拠のない推測だった。確証バイアス(Confirmation Bias)の構造的問題。

- **原典**: `evidence_based_verification_protocol.md` (conv_269b38c1)

- **適用範囲**: テスト結果の報告を含む**全セッション報告・完了レポート**

- **必須ルール**:

  1. テスト結果の報告に推測表現（「可能性があります」「と思われます」「おそらく」）を**使用禁止**。

     検証した事実のみ記述すること

  2. 非退行を主張するレポートには**構造化証拠レポート**を必須で含めること。テンプレート:

      ```
      ---
      ### 🙋‍♂️ ユーザー介入見通し
      * **現状**: {Flashセッション状況。例: Flash 50タスク完了 / コンテキスト24% / セッション残容量26タスク}
      * **セッションETA**: {セッション全体の完遂予測。例: 18:55 JST（約30分後）}
      * **🪑 次回着席推奨: {正時マーク} JST** — {理由。例: セッションETA 18:55 → 19:00着席が最適}
        * {アクション。例: 完遂後、新規Flashプロンプトの貼り付けが必要になります}
      * **夜間モード（22:00以降の場合）**: セッション残寿命と夜間デッドタイムの見通しを追記
      ```
   8. ユーザー介入見通しの省略・簡略化は禁止。コンテキスト圧縮後も必ず表示すること
   9. **セッションレベルETA優先の原則**: 介入見通しでは「現バッチETA」ではなく「セッションETA」を主軸に表示すること。ユーザーは1時間に1回の着席を基本としており、バッチ単位の15分刻み予測は不要。`health_check_cron.py` が出力する `📐 セッションETA` と `🪑 次回着席推奨` を必ず転記すること
   10. **正時マーク着席推奨の原則**: `🪑 次回着席推奨` は `health_check_cron.py` が算出した正時（XX:00）をそのまま使用すること。独自に切り上げ・切り下げを行わないこと
  3. テスト失敗が発生した場合、以下のK/N分類を必須で行うこと:

     - **(K) 既知失敗**: `xfail` またはベースラインに記録済み → テスト名で機械的に照合

     - **(N) 新規失敗**: ベースラインに存在しない → **原因調査必須**（推測による「既知」分類は禁止）

  4. テストスコープの一部を未実行とする場合、以下を明示すること:

     - 未実行スコープの名前と件数

     - 未実行の具体的技術的理由（「E2Eだから」は理由として不可）

     - プロダクションコード変更の有無に基づくリスク評価

  5. **暗黙の既知失敗の禁止**: 定常的に失敗するテストは `xfail(reason="具体的原因")` で宣言的に管理。

     `xfail` 登録時は TDR 連携必須。reason に「環境依存」等の曖昧表現は禁止（原因モジュール名を記載）

  6. **ベースラインスナップショット**: Sprint完了時に `regression_baseline.json` を更新。

     FF で known_failures 件数の非増加をラチェット検証

- **自動検知サイクル**: テスト実行 → baseline.json比較 → N/K自動分類 → 構造化レポート生成 → FF非増加チェック

- **違反検出**: セッション報告に構造化証拠レポートがない場合、EP該当

- **既存ルールへの遡及適用**:

  - カバレッジ改善規約: 計測コマンド出力のレポート貼付を追加義務化

  - TDR規約: 新規 `except Exception` の grep 自動検出をFF化検討

  - UX検証連動: xfail 付きテストはラチェットカウントから除外（品質低下の隠蔽防止）

- **参照**: `e2e_regression_verification.md` (conv_269b38c1)

## NHK・一流YouTuber基準品質向上サイクル規約 (2026-05-20 制定)

- **正式規格化**: `nhk_video_standards_report.md` および `youtuber_standards_personas.md` を動画品質の公式品質テンプレート、ペルソナ選定カタログ、およびUAT（受入テスト）の設計根拠とする。

- **品質見直しサイクル**: イテレーション（改善サイクル）実行時、または動画エンコードロジック・字幕生成エンジンの変更時、本規格を満たしているかを自動測定スコアラーで検証する。

- **ラチェットと改訂**: 新たなOSSツール（`auto-editor`, `stable-ts`等）の導入や検証結果に基づき、規格レポート（テンプレート原型）およびペルソナカタログ自体を継続的に見直し、アップグレード（より厳格な基準への改訂）を行う。

## 24時間自律改善サイクル規約 (2026-05-20 制定)

- **憲法参照**: PROJECT_CONSTITUTION.md §26（無限改善サイクル条項）

- **ロードマップ**: MASTER v4.0 Phase 5〜20（711タスク/16フェーズ）

- **デュアルモデル構成**:

  - **Flash層（実行工兵）**: Gemini 3.5 Flash × 30並列。バグ修正/テスト追加/リファクタ/エッジケース/ドキュメント

  - **Opus層（戦略将軍）**: Claude Opus 4.6。5時間サイクルで弱点分析/設計改善/優先度再設定

- **自律判断4レベル**: L1(完全自律) / L2(条件付き=テストPASS必須) / L3(Opus承認) / L4(議長承認)

- **停止条件**: 3テスト連続FAIL / カバレッジ2%低下 / テスト数減少 → 即時停止+レポート

- **品質ゲート5段階**: (1)pytest全PASS (2)カバレッジ非退行 (3)ラチェット全PASS (4)Opus証拠レポート (5)日次RAW E2E

## Flashプロンプト出力形式規約 (2026-05-27 制定)

- **必須ルール**: `generate_flash_prompt.py` の出力をユーザーに提示する際は、**全文を単一のコードブロックで囲み、ワンタッチでクリップボードにコピーできる形式**で出力すること
- **技術的制約**: プロンプト内部に ``` （3バッククォート）のコードブロックが含まれるため、**外側は必ず4つのバッククォート（````markdown ... ````）で囲むこと**。3つのバッククォートで囲むと入れ子が壊れてワンタッチコピーが不可能になる
- 分割出力や、コードブロック外のテキストとしての出力は禁止
- プロンプト前後の説明文は最小限にとどめること（「以下を貼り付けてください」程度）

## テストファイル汚染防止規約 (2026-06-30 制定)

- **原因**: `test_comprehensive_preview.py` がモジュールレベルで `Image.new = _test_image_new` を実行し、pytestのテスト収集時に全テストファイルがインポートされた時点で `PIL.Image.new` がグローバルに上書きされた。この結果、他テストファイルの単一色画像検証が `DID NOT RAISE ValueError` で失敗。単一ファイル実行ではPASS、全体実行ではFAILという再現困難な挙動のため、発見に複数セッションを要した（2026-06-30インシデント）
- **必須ルール**:
  1. テストファイルのモジュールレベル（関数・クラスの外側）でのグローバル状態変更は**禁止**
     - `SomeModule.func = patched_func` → `@pytest.fixture(autouse=True)` に変更し、`yield` 後にオリジナルを復元
     - `sys.modules["xxx"] = mock` → `patch.dict(sys.modules, {...})` を fixture 内で使用
     - `os.environ["KEY"] = "val"` → `monkeypatch.setenv()` または `patch.dict(os.environ, {...})` を fixture 内で使用
  2. テストの PASS/FAIL が実行方法（単一ファイル vs 全体、`--cov` 有無）で変わる場合、**グローバル状態汚染を最優先で疑う**こと。診断手順: `getattr(suspected_func, '__module__', 'N/A')` で関数の出自を確認
  3. モジュールレベルの `MagicMock()` インスタンスをテスト関数のデフォルト引数に使用することは**禁止**（テスト間で `call_count` 等が共有される）
  4. 新規テストファイル作成時、モジュールレベルのコードは**定数定義・import・ヘルパー関数定義**のみ許容。状態変更は fixture に限定
- **自動検証**: `pytest backend/tests/test_fitness_functions.py::TestFF36TestFilePollutionGuard` — AST解析で全テストファイルをスキャンし、モジュールレベルの属性代入・`sys.modules` 代入・`os.environ` 代入を検出
- **参照**: `incident_review.md` (conv_5e4b4846), `backend/tests/test_fitness_functions.py` の `TestFF36TestFilePollutionGuard`

## 繰り返しコマンド実行規約 (2026-05-28 制定)

- **原因**: `schedule`（Cron）や定期タイマーから `python -c "..."` インラインスクリプトを実行すると、コマンド文字列が毎回微妙に異なるためAntigravityの権限承認ダイアログが都度表示され、ユーザー操作が必要になる
- **必須ルール**:
  1. **繰り返し実行されるコマンド**（Cron、タイマー、定期チェック等）では `python -c "..."` インラインスクリプトの使用を**禁止**する
  2. 代わりに**固定のスクリプトファイル**（`.py`）を作成し、常に同一のコマンド文字列で実行すること
  3. コマンド文字列が完全に一致すれば、Antigravityは1回の承認で以降の実行を自動許可する
  4. **単発実行**（デバッグ、調査等）での `python -c` は許可する（繰り返さないため）
  5. 新規Cronジョブを設定する際は、対応するラッパースクリプトの存在を確認すること
- **適用例**:
  - ❌ `schedule` → `run_command python -c "import subprocess; ...health_check.py..."` （毎回承認が必要）
  - ✅ `schedule` → `run_command python backend/agents/orchestration/health_check_cron.py` （1回承認で永続許可）
- **参照**: `backend/agents/orchestration/health_check_cron.py`（Cronヘルスチェック用ラッパー）

## アダプティブ・アーカイブ判定規約 (2026-06-04 制定)

- **原因**: 固定タスク数閾値（`archive_tasks: 80`）ではタスク複雑度の変化に追従できず、セッション容量の70%を無駄にしてユーザーの手動再開設が頻発した。導入当初は80タスクでctx≒100%だったが、リファクタ中心の軽量タスクではctx30%で80タスクに到達しセッションが早期終了
- **廃止**: `archive_tasks`（固定タスク数閾値）は全プロファイル（STANDARD/WEEKEND/NIGHT）から**完全廃止**。`user_schedule.json` および `_DEFAULT_FLASH_PROFILES` から削除済み
- **必須ルール**:
  1. Flashセッションのアーカイブ判定は**コンテキスト消費率予測**を主軸とする（3層構造）:
     - **層1（主軸）**: 直近3バッチの `context_pct_history` 移動平均から次バッチのctx%を予測。`context_target_pct`（デフォルト70%）超過見込みで `warn`
     - **層2（安全弁）**: バッチ数（`archive_batches`）・稼働時間（`archive_hours`）のハードキャップ。フリーズ防止用
     - **層3（学習）**: `flash_session.json` の `context_pct_history` にバッチごとの消費率を記録し、推定精度を向上
  2. `context_target_pct`（デフォルト: 70）と `context_warn_pct`（デフォルト: 60）は `user_schedule.json` のプロファイルで定義。直接コード内にハードコードしないこと
  3. `context_pct_per_batch` はプロファイルごとの推定値（デフォルト: 4%）。セッション開始直後（履歴なし）の初期推定に使用
  4. `archive_urgency` の値は `ok` / `info` / `warn` の3段階。Flash側は `warn` 時のみ完遂プロトコル（§6）を開始
  5. `flash_reports.jsonl` にバッチごとの `context_pct_at_report` と `avg_delta_per_batch` を記録し、セッション横断での分析を可能にすること
  6. ダッシュボードのモードバッジは `ctx目標=N%` 形式で表示（旧: `アーカイブ=Nタスク`）
  7. ヘルスチェック（`health_check.py`）のセッションETA計算は `context_target_pct` ベースで算出。固定タスク数による推定は禁止
- **設定値一覧**:

  | パラメータ | STANDARD | WEEKEND | NIGHT |
  |:---|:---:|:---:|:---:|
  | `context_target_pct` | 70 | 70 | 70 |
  | `context_warn_pct` | 60 | 60 | 60 |
  | `context_pct_per_batch` | 4 | 3 | 2 |
  | `archive_batches` (安全弁) | 30 | 35 | 40 |
  | `archive_hours` (安全弁) | 5 | 6 | 8 |

- **自動検証**: `pytest backend/tests/test_fitness_functions.py` — 全テストPASS必須
- **参照**: `backend/agents/orchestration/orchestrator.py` の `_should_archive()` / `generate_flash_status()`、`backend/agents/orchestration/user_schedule.json`

## Opus Cronハンドラ自動エスカレーション規約 (2026-05-30 制定 / 2026-05-31 多層防御改訂)

- **原因**: Flashセッションがハング（pytestプロセス無応答等）した際、ファイルベースのナッジもAntigravity `send_message` も効かず、ユーザーの手動介入が唯一の復旧手段であることが判明（2026-05-29インシデント x2）。さらに 2026-05-31 に、Opus が AUTO_NUDGE マーカーを検知しても `send_message` を実行せず放置したインシデントが発生
- **多層防御アーキテクチャ**:
  - **層1（Python自動）**: `health_check_cron.py` が `nudge_flash.json` を書き出し。Flashの自前スクリプトが読み取り可能
  - **層2（Opus実行）**: `AUTO_NUDGE_REQUIRED:<conv_id>` マーカー検知時、Opusが `send_message` を実行
  - **層3（ユーザー介入）**: ナッジ2回連続失敗時、具体的な復旧メッセージを含むユーザー介入依頼を表示
- **必須ルール**:
  1. **【最優先】** Cronヘルスチェック出力に `AUTO_NUDGE_REQUIRED:<conv_id>` が含まれる場合、**他のすべての処理に先立ち** `send_message` ツールでFlashに復旧メッセージを送信すること。テキストで「ナッジしました」と報告するだけでは**不可**（ツール呼び出しが必須）
  2. `send_message` の送信先は `<conv_id>` で、メッセージ内容は: 「残りのサブエージェントの完了状況を確認し、完了済みのものは結果を反映、未完了のものは300秒タイマーを設定してください。心拍更新も実行してください。」
  3. Opus側のCronハンドラは、`health_check_cron.py` の出力を**毎回解析**し、以下の段階的アクションを実行すること:
     - **`AUTO_NUDGE_REQUIRED:<conv_id>`** 検知時: **即座に** `send_message` でFlashに復旧要求を送信
     - **心拍25分超** (2回連続STALE): Opusチャット上にユーザーへの介入依頼を**大きく表示**（「🚨 Flashハング検知」）
     - **UNREACHABLE (30分超)**: ウォッチドッグがタスクキューを自動回復済みであることを確認・報告
     - **DEAD (60分超)**: 「新規セッション開設が必要」と表示。Cronの停止を検討
  4. `send_message` でFlashの復旧を**2回試行**しても応答がない場合、3回目以降の送信は見送り、ユーザーへの介入依頼に切り替えること
  5. ユーザーへの介入依頼テキストには、Flashチャットに貼り付けるべき具体的なメッセージを含めること
- **参照**: `backend/agents/orchestration/health_check_cron.py` の `_check_auto_nudge()`, `nudge_flash.json`（ファイルベースナッジ）

## Opusセッションリセット規約 (2026-05-31 制定)

- **原因**: `opus_session.json` の `session_started_at` と `cron_iterations` が旧セッションの累積値のまま残り、新Opusセッションでも `STALE` 警告が毎回表示されるインシデントが発生（2026-05-31 conv_839a39ef）
- **必須ルール**:
  1. **新規Opusセッション開始時**（§0実行時）に `reset_opus_session(conversation_id)` を**必ず**実行し、`opus_session.json` をリセットすること
  2. リセットにより `session_started_at` が現在時刻に、`cron_iterations` が 0 にクリアされる
  3. リセットを忘れた場合、旧セッションの稼働時間（16h超）で `STALE` 偽陽性が発生するため、**セッション冒頭で必ず実行**すること
  4. リセット後、最初のCronで `🟢 FRESH` と表示されることを確認すること
- **実行方法**: `python -c "from backend.agents.orchestration.health_check import reset_opus_session; reset_opus_session('現在のconv_id')"`
- **参照**: `backend/agents/orchestration/health_check.py` の `reset_opus_session()`

## Opusセッション移行・コンパクション検知規約 (2026-06-07 制定)

- **原因**: Opusセッションの移行判定において、稼働時間やCron回数だけでなくコンパクション（コンテキスト圧縮）の発生を自動検知して `STALE`（移行推奨）とする必要があった。しかし、定期的なCron（5分おき）の度にディスク走査（`transcript.jsonl`）を行うとI/O負荷が高まるため、受動的な実行とスキップ制御の分離が必要となった。
- **必須ルール**:
  1. **ディスク走査のオプション化**: `health_check.py` による会話履歴（`transcript.jsonl`）の走査は、`--check-compaction` フラグが明示的に指定された場合のみ実行し、無駄なディスクI/Oを回避すること。
  2. **Cron時の走査スキップ**: 定期Cron（`health_check_cron.py`等による自動実行）の際には、`--check-compaction` を指定せずに実行し、定期的なディスク走査を回避すること。
  3. **チャット入力時の受動検知**: AI（Opus）自身は、対話の開始時やユーザーからのチャット入力時の思考プロセス（Thought）の中で、`--check-compaction` オプション付きのヘルスチェック（または検知ロジック）を実行してコンパクションの有無を確認・保持すること。
  4. **検知状態の永続化**: 一旦検知されたコンパクション状態は `opus_session.json` 内に `compaction_occurred: true` として永続化され、新規セッション移行（リセット）まで強制的に `STALE`（移行推奨）判定を維持すること。
  5. **移行推奨時の出力スキップ禁止**: Opusセッションが `STALE`（移行推奨）の場合は、時間帯やユーザー着席スケジュールに関わらず、動的な出力スキップ（間引き）を一切行わず、毎回のヘルスチェックで必ず即時に警告（移行サジェスト）をチャットUIへ表示すること。
- **自動検証**: `pytest backend/tests/test_health_check_compaction.py` および `pytest backend/tests/test_health_check_cron_compaction.py` — 全テストPASS必須
- **参照**: `backend/agents/orchestration/health_check.py` の `assess_opus_session()` / `run_health_check()`、`backend/agents/orchestration/health_check_cron.py` の `_should_output()`

## Opusプロンプト自動生成抑制規約 (2026-05-31 制定)

- **原因**: Cronヘルスチェックで `COMPLETE` を検知するたびにOpusエージェントが `generate_flash_prompt.py` を自動実行し、ユーザーに不要な「Flash新規開設」案内を3回表示した（2026-05-31 conv_839a39ef）
- **必須ルール**:
  1. Cronヘルスチェックで `COMPLETE` を検知しても、**自動的に `generate_flash_prompt.py` を実行してはならない**
  2. 代わりに以下のガードチェックを実施:
     - `flash_session.json` の `auto_stop_reason` が `new_session_requested` の場合 → 「遷移中」と判断し、プロンプト生成をスキップ
     - 直前30分以内にプロンプトを生成済みの場合 → クールダウン中としてスキップ
  3. COMPLETE が確定した場合も、ユーザーへの案内は「新規Flashプロンプトが必要な場合はお知らせください」にとどめ、自動でプロンプト全文を出力しない
  4. ユーザーが明示的に「プロンプトを生成して」と指示した場合のみ、`generate_flash_prompt.py` を実行する
- **参照**: `backend/agents/orchestration/health_check.py` L966-1001, `generate_flash_prompt.py` のクールダウンチェック

## ユーザー着席スケジュール連動規約 (2026-05-31 制定)

- **スケジュール定義**: `backend/agents/orchestration/user_schedule.json`
- **着席パターン**: 6回/日（定期） + 3回/日（任意） = 9回/日、遵守率70%
- **Cron出力制御**:
  1. `health_check.py` の `main()` は**常に5分間隔で実行**（心拍チェック、ナッジ送信、ダッシュボード更新は継続）
  2. `health_check_cron.py` の**出力のみ**、以下の規則で間引く:
     - ACTIVE + 着席窓: 5分間隔で出力（毎回）
     - ACTIVE + 離席中: 15分間隔で出力（3回に1回）
     - COMPLETE + 着席窓: 10分間隔で出力（2回に1回）
     - COMPLETE + 離席中: 30分間隔で出力（6回に1回）
  3. **UNHEALTHY/DEGRADED 検知時はスキップ禁止**（常に即時出力）
  4. スキップ時は `⏸️ Cron #N スキップ (理由) | 次窓: HH:MM (ラベル)` の1行のみ出力
- **着席推奨**: `recommended_return_jst` は正時丸めではなく、`user_schedule.json` の次の着席窓の開始時刻を使用
- **参照**: `backend/agents/orchestration/user_schedule.json`, `health_check_cron.py` の `_should_output()`

## Flash排他制御安全ガード規約 (2026-05-31 制定)

- **原因**: `generate_flash_prompt.py` が `flash_session.json` の `status` を無条件に `stopped` に書き換え、稼働中のFlashセッションの状態ファイルを矛盾させた（2026-05-31 conv_839a39ef）
- **必須ルール**:
  1. `generate_flash_prompt.py` の排他制御は、`task_queue.json` に `running` ステータスのタスクがある場合、**自動停止をスキップ**すること
  2. `--force` オプションで強制停止は可能（明示的な操作のみ許可）
  3. Flashセッションの停止は、Flash自身が `session_end()` を呼ぶか、ユーザーが明示的に指示した場合のみ行うことを原則とする
- **参照**: `backend/agents/orchestration/generate_flash_prompt.py` の排他制御ブロック

## Cronヘルスチェック結果表示規約 (2026-05-30 制定 / 2026-05-30 表形式改訂)

- **原因**: Cronヘルスチェック結果をOpusが1行サマリーや箇条書きに簡略化し、`health_check_cron.py` が出力する情報の一部が欠落する問題が繰り返し発生。コンテキスト圧縮後に表示形式が劣化する傾向がある
- **必須ルール**:
  1. Cronヘルスチェック結果は**毎回**、`health_check_cron.py` の**全出力情報**を以下の**表形式フォーマット**に変換して表示すること（1行サマリー・箇条書き・情報の省略は禁止）:
     ```
     🟢/🟡/🔴 **HEALTHY/DEGRADED/UNHEALTHY** — Phase {N} / {Milestone} （Cron #{iteration}）

     | 指標 | 値 | 状態 |
     |---|---|---|
     | 心拍鮮度 | {N}分前 | {🟢正常/🟡STALE/🔴UNREACHABLE} |
     | Flash | {pending}待機 / {running}実行中 / {completed}完了 | {🔄稼働中/🏁完遂/⏸停止} |
     | 通算タスク | {累計}件（セッション内: {N}件） | — |
     | Git最新 | `{hash}` ({N}分前) | {🟢整合/⚠️乖離} |
     | ETA | {時刻} JST（約{N}分後） | 残{N}タスク |
     | Opus | {🟢FRESH/🟡AGING/🔴STALE} | {稼働時間}h / Cron {回数}回 |

     {💡 サジェスト行（あれば全て転記）}
     {🚨 要対応行（あれば全て転記 + 具体的アクション指示）}
     ```
  2. **情報の全量転記が義務**: `health_check_cron.py` の stdout に含まれる全ての💡サジェスト行、🚨要対応行、⚠️警告行を**省略せずそのまま**表の下に転記すること。「アクション不要」も含めて必ず表示する
  3. DEGRADED/UNHEALTHY時は表の下に追加で以下を表示:
     - 異常の具体的内容
     - 推奨アクション（ユーザーが実行すべき具体的コマンドやUI操作）
     - ユーザー介入が必要な場合はその旨を明示
  4. **例外**: ユーザーが明示的に「簡易表示にして」と指示した場合のみ、1行サマリーを許可
  5. コンテキスト圧縮後もこの表示形式を維持すること（Cronプロンプトに表示形式の再注入は不要 — 本規約がGEMINI.mdに存在するため自動適用される）
  6. **表形式は義務**。箇条書き形式・罫線形式への退行は禁止。コンテキスト圧縮後も表形式を維持すること
  7. **ユーザー介入見通しの表示は義務**: ヘルスチェック結果を表示するたびに、表・サジェスト行の下に必ず「🙋‍♂️ ユーザー介入見通し」セクションを付記すること。以下の項目を必ず含める:
     - **現状**: Flashセッションの進行状況（完了タスク数・コンテキスト消費率・セッション残容量）を端的に記述
     - **セッションETA**: `health_check_cron.py` の `📐 セッションETA` の値を転記。現バッチETAではなくセッション全体の完遂予測
     - **🪑 次回着席推奨**: `health_check_cron.py` の `🪑 次回着席推奨` の正時（XX:00）を転記
     - **介入不要の場合**: 「当面の介入は不要です。次回Cronで再通知します」と明示的に記述（省略禁止）
     テンプレート:
     ```
     ---
     ### 🙋‍♂️ ユーザー介入見通し
     * **現状**: {Flash Nタスク完了 / コンテキストN% / セッション残容量Nタスク}
     * **セッションETA**: {HH:MM} JST（約{N}分後）
     * **🪑 次回着席推奨: {HH:00} JST** — {理由。例: セッションETA 18:55 → 19:00着席が最適}
       * {アクション。例: 完遂後、新規Flashプロンプトの貼り付けが必要になります}
     * **夜間モード（22:00以降の場合）**: セッション残寿命と夜間デッドタイムの見通しを追記
     ```
   8. ユーザー介入見通しの省略・簡略化は禁止。コンテキスト圧縮後も必ず表示すること
   9. **セッションレベルETA優先の原則**: 介入見通しでは「現バッチETA」ではなく「セッションETA」を主軸に表示すること。ユーザーは1時間に1回の着席を基本としており、バッチ単位の15分刻み予測は不要。`health_check_cron.py` が出力する `📐 セッションETA` と `🪑 次回着席推奨` を必ず転記すること
   10. **正時マーク着席推奨の原則**: `🪑 次回着席推奨` は `health_check_cron.py` が算出した正時（XX:00）をそのまま使用すること。独自に切り上げ・切り下げを行わないこと

## Flashセッション二重稼働防止規約 (2026-05-30 制定)

- **原因**: Opusが`generate_flash_prompt.py`で新規Flashプロンプトを生成した際、旧Flashセッションの停止処理を行わないため、新旧2セッションが同時稼働し`flash_session.json`と`task_queue.json`へのデータ競合・タスク二重実行のリスクがあった
- **必須ルール**:
  1. `generate_flash_prompt.py` は**プロンプト生成前に**旧セッション（`status=running`）を自動停止すること（`status=stopped`, `auto_stop_reason=new_session_requested`）。実装済み
  2. Flashの心拍更新時（`flash_heartbeat()` / `flash_update_heartbeat()`）に `archive_urgency` と `context_consumption_pct` を `flash_session.json` に書き出すこと。実装済み
  3. `health_check.py` は `flash_session.json` の `archive_urgency == "warn"` を検知し、ヘルスチェック出力に「🔴 Flashコンテキスト飽和 — 新規セッション準備推奨」を表示すること。実装済み
  4. 新規Flashセッション開設をユーザーに案内する際は、**旧Flashチャットを先に閉じること**を明示的に案内すること（CPU/メモリ解放のため）
  5. `generate_flash_prompt.py` の排他制御ガードを迂回・無効化することは禁止
- **安全フロー**: Opus Cron検知(archive_urgency=warn) → ユーザーに通知 → generate_flash_prompt.py実行(旧session自動停止) → 旧チャット閉鎖案内 → 新規チャットでプロンプト貼付
- **参照**: `backend/agents/orchestration/generate_flash_prompt.py` の排他制御ガード、`orchestrator.py` のarchive_urgency書出し

## 曖昧入力時の確認プロトコル (Ask User Question)

- ユーザーの指示が曖昧・複数解釈可能な場合、勝手に判断せず必ず質問する

- 質問は選択式（2〜3択）で提示し、各選択肢の影響を簡潔に説明する

- 以下の場面では必ず確認を取る:

  - 設計方針が複数あり得るとき（例: 閾値の数値、アーキテクチャの選択）

  - 変更の影響範囲が不明確なとき

  - ユーザーの意図と異なる解釈をしている可能性があるとき

- 些末な質問（「進めて良いですか？」等）は禁止。判断材料を伴う質問のみ行う

## チャット開始時プロトコル

0.0. **セッション識別（必須・最初のステップ）**:
   - チャットの起動経緯から自分の役割を機械的に判定する:
     - Flash起動プロンプト（`generate_flash_prompt.py` の出力）を貼り付けて開始されたチャット、
       または `flash-autonomous-entry.md` ワークフローが起動されたチャット → **Flash実行セッション**
     - それ以外 → **Opus統括セッション**
     - 判定に迷う場合: チャット履歴に「Flash専用セッション 起動指示プロンプト」の貼り付けがあれば Flash
   - 最初の応答で必ず役割を宣言すること:
     - Opusの場合: 「🎯 本セッション: **Opus統括** として稼働します」
     - Flashの場合: 「🎯 本セッション: **Flash実行** として稼働します」
   - **Opusの場合**: 以下のステップ0〜5を全て実行
   - **Flashの場合**: ステップ0.0→1.6のみ実行し、以降は `FLASH_RULES.md` および起動指示プロンプトに従う
   - **このステップの省略は禁止**。コンテキスト圧縮後も役割を見失わないための防壁である
   - **タイマー/再起動 wakeup 時の例外処理**:
     - サーバー再起動やタイマー（schedule）の wakeup 時、メッセージに `health_check.py` 等の Opus 用のコマンドやダッシュボード更新の指示が含まれていたとしても、あなたが **Flash実行セッション** であれば、絶対にそのコマンドを実行したり、Opus 統括として振る舞ったりしないでください。
     - Flash実行セッションは、自セッションのタスク処理のみに集中する役割です。
     - もし自分がどちらのセッションであるか判断に迷った場合（コンパクション発生後など）は、チャットの過去履歴からユーザーの起動指示（`flash-autonomous-entry.md` の起動、あるいは `Flash専用セッション 起動指示プロンプト`）が存在するかを確認し、存在すれば **Flash実行セッション** として振る舞ってください。

   - **ワークフロー起動時のフェイルセーフ（2026-05-26 制定）**:
     - /flash-autonomous-entry ワークフローが起動された場合、プロジェクトパスに関わらず **Flash実行** として振る舞うこと。ワークフロー起動はセッション識別より優先される。
     - generate_flash_prompt.py が生成したプロンプトに「Flash実行セッション」と明記されている場合も同様にFlash実行として振る舞うこと。
     - **Opus統括プロトコル（health_check.py実行、ダッシュボード更新、Cronジョブ設定）は一切実行しないこと。**
0. KIサマリー（会話冒頭に注入済み）を確認し、関連KIがあればartifactを読む

1. VerifiedFacts(category=progress)を読み、完了済みタスクを把握

1.5. **TDRサマリー確認**: `technical_debt_store.get_summary()` で未解消CRITICAL件数を把握。変更予定ファイルに関連する負債を `get_entries_by_file()` で確認

1.6. **Phase状態確認**: `backend/agents/memory/phase_state.json` を読み、現在Phase/emergency_stop/throttled状態を把握

1.7. **Flash稼働ヘルスチェック（Pull型監視）** [Opus専用]:
   - `python backend/agents/orchestration/health_check.py --update-dashboard` を実行
   - 結果を「🏥 ヘルスチェック」としてユーザーに表示
   - 🔴 UNHEALTHY判定の場合:
     1. `python backend/agents/orchestration/generate_flash_prompt.py` を実行
     2. 出力されたプロンプトをコードブロックでユーザーに提示
     3. 「同一プロジェクト内の新規チャットに貼り付けてください」と案内
     **注意**: `/flash-autonomous-entry` 単体での案内は**禁止**。
     必ず `generate_flash_prompt.py` で生成したプロンプトを使用すること
     （§2-⑤ 自己スコープ制限が含まれているため、コンテキスト汚染を防止する）
     ※ `health_check.py` は UNHEALTHY 時にプロンプトを自動出力するため、
     その出力をそのままユーザーに転記すればよい
   - 🟡 DEGRADED判定の場合: 注意事項をユーザーに報告
   - 🏁 Flashセッション COMPLETE判定の場合:
     UNHEALTHY判定と同じ手順で `generate_flash_prompt.py` のプロンプトを提示し、
     新規Flashセッション開設を案内する
   - ⏳ Flashセッション FINISHING判定の場合: 完遂プロトコル実行を待機
   - このステップは**省略不可**（Flashセッション稼働中は毎回実行）

2. MASTER v4.0を参照し、未完了の次タスクを特定

3. MASTERの記載粒度でモード判定:

   - テスト名+検証基準が1行ずつ定義 → 🟢実装 (Sonnet)

   - ゴール/概要のみ → 🔴設計 (Opus)

   - カバレッジ改善Sprint → 🔴設計必須（A/B/C分類表を含む設計書が前提。カバレッジ改善規約参照）

     ※【重要】🔴設計モードの場合、フォルダの場所を決め打ちせず、最新の `開発推移表_*.md` を検索して該当タスクの詳細設計書（ファイル名）を特定・熟読すること。勝手な推測設計は厳禁。

   - IDR 3ステップ防衛:

     STEP1: 推移表から対象タスクのキーワードで設計書ファイル名を特定→ロード

     STEP2: STEP1ヒットなし → タスク関連キーワードでプロジェクト全体をgrep→最新ファイル優先

     STEP3: STEP1・2とも不発 → ユーザーに報告。推測設計の開始は絶対禁止

3.5. **設計時カバレッジチェック** (全🔴設計モードで実施):

   - 変更対象モジュールの現行カバレッジを `pytest --cov` で計測

   - 変更予定行の未カバー状態を確認

   - 未カバーの変更予定行がある場合、設計書にカバーテストを含める（カバレッジ改善規約 ルール5）

4. モードに応じたブリーフィングを表示:

   - 🔴設計: フルブリーフィング(.agent/workflows/briefing-protocol.md)

     + **セルフチェック項目義務**: 設計書の末尾に「セルフチェック項目」セクションを記載すること。

       項目は憲法/ビジョンとの整合性、MASTER方針との一致、および実装時に機械的に検証可能な基準を含む。

       実装チャットのチェッカー(conftest.py等)はこのセルフチェック項目の機械的実行であり、設計書が親、チェッカーが子の関係。

     + **カバレッジ設計チェック**: セルフチェック項目に以下を含めること:

       □ 変更対象モジュールの現行カバレッジを計測したか

       □ 変更予定行の未カバー箇所を特定したか

       □ 未カバー箇所のテストを設計書に含めたか（または不要と判断した根拠があるか）

   - 🟢実装: 最小指示 → サイレント実行 → 完了/ヘルプレポート

     + **設計書セルフチェック確認**: 実装開始前に設計書の「セルフチェック項目」を読み、チェッカーのルールがセルフチェック項目をカバーしているか確認。不足があればチェッカーにルールを追加してから実装を開始する。

5. チャット完了時: ハンドオフプロトコル(briefing-protocol.md §v1.2)を実行

   + **MASTER連動義務**: 設計書を作成・確定した場合、以下の3点連動を完了すること

     a. MASTER該当Milestoneにテスト名+検証基準+設計書ファイル名を追記

     b. 開発推移表に `[M番号]` タグ付きエントリを追加

     c. ハンドオフプロンプトに設計書パスを明記

   + 3点いずれかが欠落した状態でチャットを終了してはならない

   + **TDRスナップショット更新(L2-4)**: Sprint完了時に `store.create_snapshot(sprint_version)` を実行し、ラチェット基準を更新

   + **報告レポートの原文記録**: ユーザーから報告レポート作成を指示された場合、

     重要な判断・指摘のやり取りはユーザー・AI双方の発言原文を引用して記録すること。

     (会話ログは長文が切り捨てられるため、レポートが唯一の完全記録となる)

   + **Cronベース永続監視（Flash監視）** [Opus専用]:
     Opusセッション開始時に**1回だけ**以下を実行すること:
     1. `manage_task(Action="list")` で既存のCronジョブを確認
     2. 既存のCronジョブがなければ、`schedule` ツールで新規設定:
        - `CronExpression="*/5 * * * *"`（5分ごと）
        - `MaxIterations=288`（24時間分）
        - Promptには「health_check.py --update-dashboard を実行し、結果を表示」を含める
     3. 既存のCronジョブがあれば、重複設定せずスキップ
     - **DurationSeconds（一回限りタイマー）は使用禁止** — 他メッセージ受信で自動キャンセルされるため脆弱
     - CronExpression は自動反復するため、**タイマー再設定は不要**（旧方式との最大の違い）
     - コンパクション後もCronジョブは継続動作する
     - **このステップはセッション開始時に1回のみ実行**（応答終了時の毎回実行は不要）
     - **注意**: このCronジョブはOpus専用。Flashセッションが設定してはならない
   - **send_messageベース即時通知（v2.0.10新機能）** [Opus専用]:
     Flash実行セッションから `[FLASH_SESSION_COMPLETE]` メッセージを受信した場合、以下を即座に実行すること:
     1. `python backend/agents/orchestration/generate_flash_prompt.py` を実行
     2. 出力されたプロンプトを **4バッククォートのコードブロック** でユーザーに提示（Flashプロンプト出力形式規約に従う）
     3. 「🚀 Flash完遂を検知しました。以下のプロンプトを同一プロジェクト内の新規チャットに貼り付けてください」と案内
     4. `flash_session.json` の `opus_conversation_id` を自身の conversation ID で更新（セッション移行時の引き継ぎ用）
     - **注意**: このメッセージはCronジョブとは独立して受信される。Cronジョブは引き続き5分間隔で稼働し、send_messageの受信漏れ時のフォールバックとして機能する

## Flash指示プロンプト生成規約 (2026-05-24 制定) [Opus専用]

- **原因**: 起動指示プロンプトテンプレートが3箇所（GEMINI.md / flash-task-dispatch.md / flash-autonomous-entry.md）に分散し、Opusが毎回「記憶から」プロンプトを組み立てるため、CLI不要/待機可変/自己復旧/タイマー常時表示の要素が漏れる
- **必須ルール**:
  1. Flash起動指示プロンプトは必ず `python backend/agents/orchestration/generate_flash_prompt.py` で生成すること
  2. 生成されたプロンプトをそのまま新規Flashセッションに貼り付ける
  3. Opusが独自にプロンプトを「記憶から」組み立てることを**禁止**（要素漏れの根本原因）
  4. テンプレートの更新が必要な場合は `generate_flash_prompt.py` のソースコードを修正すること（GEMINI.md内のテンプレートは参照専用、コピペ禁止）
- **参照**: `backend/agents/orchestration/generate_flash_prompt.py`

## Flashセッション完遂規約 (2026-05-24 制定)

- **適用対象**: Flashセッション（`generate_flash_prompt.py` §6に詳細手順あり）
- **トリガー**: `get_next_batch()` が空バッチを返した場合（全タスク消化完了）
- **必須3ステップ**:
  1. `hub.flash_session_end()` で `flash_session.json` のステータスを `stopped` に更新
  2. チャットUI上に `🏁 ミッション完遂` ステータスを表示（タスク数・成功率・稼働時間を含む）
  3. `Human01_Official Artifact/受信トレイ/` に最終完了レポートを保存
- **「完了しました」だけでループを停止することは禁止**。3ステップ全実行が必須
- **Opus側の検知**: `health_check.py` の `assess_flash_lifecycle()` が `COMPLETE` を返す → 新規Flash開設を検討

## Flashセッション復帰規約 (2026-05-25 制定)

- **原因**: APIレート制限による長時間停止後、チャットUIの「リトライ」ボタンでFlashセッションを復帰させたところ、リトライは直前の1応答を再生成するだけであり、自走ループ（`while True` によるタスク消化サイクル）は再起動されなかった。一方 `tick_loop.py`（外部プロセス）が心拍を更新し続けたため、ヘルスチェックが「心拍正常＝稼働中」と誤認する偽陽性が3時間以上継続した。
- **必須ルール**:
  1. **リトライボタンによるFlashセッション復帰は禁止**。リトライは単発の応答エラー修正用であり、自走ループの再起動には使えない
  2. レート制限・長時間停止・コンパクション等でFlashセッションが停止した場合、**必ず新規チャットを開設**し、`generate_flash_prompt.py` の出力全文を貼り付けること
  3. 旧セッションはアーカイブ可能。未コミットの成果がないことを `flash_session.json` の `tasks_completed_in_session` で確認すること
  4. `tick_loop.py` の外部プロセスは新規セッション開設後もそのまま稼働して問題ない（`flash_session.json` を直接更新するためセッションIDに非依存）
- **ユーザー手順（3ステップ）**:
  1. 旧Flash側チャットを閉じる
  2. 同一プロジェクト内で新しいチャットを開く
  3. `python backend/agents/orchestration/generate_flash_prompt.py` の出力全文を貼り付けて送信
- **参照**: `generate_flash_prompt.py` §4（Flash AIへの即時実行指示）

## 共通処理機構 継続改善規約 (2026-05-26 制定)

- **原因**: ダッシュボード表示・改善サジェスト管理・メトリクス監視が属人的で、セッション間で抜け漏れが発生するリスクがあった
- **目的**: 共通処理機構の品質を定量的に継続監視し、1日サイクルで自動改善提案を生成する

### §1 ダッシュボード3ブロック構成（2026-05-26 確定・ユーザー承認済み）
- **ダッシュボード**: `Human01_Official Artifact/サブエージェント体制報告/README.md`
- **更新トリガー**: OpusのCronジョブ（`*/5 * * * *`）による `health_check.py --update-dashboard` で5分ごとに自動更新
- **データソース**: `flash_reports.jsonl`（原データ）から毎回動的に再計算
- **3ブロック構成（配置順はユーザー承認済み。変更はユーザー承認制）**:
  - **Block 1: Opus戦略情報**（上部・継続議論に必要な情報）:
    1. 📋 アクション提案
    2. 🗺️ ロードマップ現在地（先3Phase計画・鮮度サジェスト含む）
    3. 📐 設計ストック（10個・難易度ランキング・滞留サジェスト含む）
    4. 📋 タスクTOP20（直近24h・重要度順）
    5. 💡 改善提案（1日サイクル）
  - **Block 2: 共通処理機構 安定度モニター**（中部・システム健全性）:
    1. 🛡️ 稼働安定性指標（稼働率・連続HEALTHY・復旧回数）
    2. 📋 不在中イベントタイムライン（24時間・介入タイムロス可視化）
    3. 🔄 並列稼働効率スコア（持続性+並列処理+安定性=100点）
    4. 📊 セッション累計統計
  - **Block 3: Flash/サブエージェント活動記録**（下部・活動記録参照用）:
    1. ⏱️ 時間帯別活動サマリー
    2. 🏅 活動ランキング
    3. 📦 バッチ活動タイムライン
    4. 🔀 Gitコミット
  - **アーカイブ（`<details>`折りたたみ）**: タスク詳細 / 戦略 / TDR / ヘルスチェック生データ / Phase報告 / レポート群 / 改善履歴
- **Block 1の項目を削除してはならない**。追加は可。配置順変更はユーザー承認制
- **Block 2の項目を削除してはならない**。安定度情報の欠落は運用障害に直結する

### §1.5 ダッシュボードリンク表示規約（2026-06-15 制定・ユーザー承認済み）
- **チャット上でのリンク表示ルール**: ユーザーが「ダッシュボード」「ダッシュボードを表示して」等のダッシュボード参照を要望した場合、**常に①簡易版ダッシュボード（ルートREADME.md）のリンクのみ**をチャット上に表示すること
- **理由**: ①簡易版ダッシュボード内に②詳細版ダッシュボード（`Human01_Official Artifact/サブエージェント体制報告/README.md`）へのリンクが含まれているため、②のリンクを別途チャット上に表示する必要はない
- **両ダッシュボードの定期更新は独立した義務**: チャット表示の簡略化を理由に②詳細版ダッシュボードの更新を省略・遅延させることは**厳禁**。両ダッシュボードの更新トリガー（5分間隔の`health_check.py --update-dashboard`）は変更しないこと
- **①簡易版**: `README.md`（プロジェクトルート）
- **②詳細版**: `Human01_Official Artifact/サブエージェント体制報告/README.md`

### §2 必須メトリクス（削除禁止）
| メトリクス | 算出元 | 目的 |
|---|---|---|
| 🗺️ ロードマップ | `phase_state.json` | 先3Phase計画維持・鮮度チェック・拡張サジェスト |
| 📐 設計ストック | `design_stock.json` | 10個常備・難易度ランキング・滞留検知・前倒しサジェスト |
| 🛡️ 稼働安定性 | `event_log.jsonl` | 稼働率(24h)・連続HEALTHY・復旧回数 |
| 📋 イベントタイムライン | `event_log.jsonl` | 24時間イベント・介入タイムロス可視化 |
| ⚡ 処理効率 | `flash_reports.jsonl` | タスク/時・バッチ間隔・並列度（1h/6h/24h/通算） |
| 🔄 並列稼働効率スコア | 複合 | 持続性(35)+並列処理(30)+安定性(35)の100点スコア |
| 🏆 ランキングTOP5 | `flash_reports.jsonl` | 出現率・平均処理時間・タスク/時 |
| 📋 タスクTOP20 | `flash_reports.jsonl` | 直近24hの重要度順タスクサマリー |
| 💡 改善提案 | `improvement_analyzer.py` | 1日サイクルの前期比較分析 |
- メトリクスの**算出ロジック変更時**は、変更理由とBefore/Afterをダッシュボード改善履歴に記録すること

### §3 1日サイクル改善提案（自動実行・ユーザー承認制）
- **生成器**: `backend/agents/orchestration/improvement_analyzer.py`
- **自動トリガー**: ダッシュボード更新時に前回レポートから1日経過を検出 → 自動生成
- **出力先**: `Human01_Official Artifact/サブエージェント体制報告/改善提案/`
- **レポート内容**: 期間メトリクス比較(1日間) / トレンドスパークライン / 検出パターン(🟢🟡🔴) / エージェント活動分布 / 具体的改善アクション
- **検出パターン6種**:
  1. スループット変化（±10%以上）
  2. 稼働率変化（±5pt以上）
  3. エラー率変化（+1pt以上）
  4. バッチ間隔変化（+20%以上）
  5. エージェント偏り（単一60%超）
  6. セッション不安定（1日で5回超中断）
- **ユーザー承認フロー**: 自動生成 → ダッシュボードにサジェスト表示 → ユーザーがレポート確認 → 採用する提案をOpusに指示 → Opus/Flashが実行
- **サジェスト表示**: 自動生成時にヘルスチェック出力とダッシュボードにサジェストメッセージを表示し、ユーザーに承認を求める
- **レポート保存はラチェット**: 過去レポートの削除は禁止。改善履歴の追跡に必要

### §4 セッション自動停止（稼働率低下対策）
- **トリガー**: `health_check.py` が心拍30分超 + status=running を検出
- **自動アクション**: `flash_session.json` のstatusを `stopped` に変更 + `event_log.jsonl` に `AUTO_STOPPED` イベント記録
- **目的**: ゴースト状態（実際は停止しているのにrunning表示）の即座解消
- **復旧手順**: Flashセッション復帰規約に従い新規セッション開設

### §5 エージェント偏り検知（ワークロード分散）
- **検知条件**: 直近24hで単一エージェントが全タスクの60%超
- **表示**: ダッシュボードのアクション提案に自動表示
- **対応**: Opus Directiveのワークロード配分を調整

### §6 Opusセッション開始時の追加義務
- チャット開始時プロトコル §1.7 でヘルスチェック実行後、以下も確認すること:
  - ダッシュボードLayer 1の改善提案セクションが表示されているか
  - 未承認の改善提案レポートがあればユーザーに提示
  - 並列稼働効率スコアが50未満の場合、改善の優先度を上げるよう提案

- **参照**:
  - `backend/agents/orchestration/generate_subagent_reports.py`
  - `backend/agents/orchestration/improvement_analyzer.py`
  - `backend/agents/orchestration/health_check.py`

## システムステータス即応規約 (2026-05-24 制定) [Opus専用]

- **トリガー**: ユーザーが「システムステータス」「状況は？」「今どうなっている？」等の状態確認を求めた場合
- **必須手順**:
  1. `python backend/agents/orchestration/health_check.py --update-dashboard` を実行
  2. ヘルスチェック結果をそのまま表示（加工・要約不要）
  3. ライフサイクル判定に基づく推奨アクションがあれば追記
- **ユーザーへの追加指示要求は禁止**: この手順で得られる情報で十分。追加質問をせず即座に結果を表示すること
- **詳細はダッシュボードを参照**: 「詳細はダッシュボード (README.md) をご確認ください」と案内

## コンテキスト効率化

- **キャッシュプール型セッション管理 (Antigravity 2.0)**:

  - LLMコンテキストのキャッシュプール化およびサブエージェント連携の高度化により、原則としてセッション切り替え（1チャット=1タスク）は不要。

  - 同一セッション内で設計、実装、検証までをシームレスに継続実行可能。

- **セッション分離の唯一の例外**:

  - 戦略立案・全体統括を行う「Opus専用セッション（本セッション）」と、並列実行・タスク処理を担う「Flash専用セッション（同一プロジェクト内の別チャット）」に分離。

  - 両セッションは「共同処理機構（Orchestration Hub）」を介して、レポート報告ベースの進捗管理および指令連携を行う。

- ファイル参照は5ファイル以下に制限。

- 状態はVerifiedFactsに事実として記録(計画は保存しない)

- VFのprogressはAPI経由で記録（VERIFIED_FACTS.mdの手動編集禁止）

- チケットシステムは廃止。ハンドオフプロンプトで代替

- **大規模テストファイル分割基準**: 1ファイル10,000行 or 150関数超で分割検討。分割単位はE2Eコンポーネント単位。命名: `test_e2e_m36_{component}.py`。conftest.pyチェッカーは共有

- 詳細は .agent/ 配下を参照 (Progressive Disclosure)

## ドキュメント管理 (Human01_Official Artifact)

- ルールファイル: Human01_Official Artifact/推移表管理ルール.md

- 自動整理スクリプト: Human01_Official Artifact/organize_artifacts.ps1

- トリガー: 「整理して」「整理整頓して」「推移表管理ルールに従って」等の指示

- 実行手順: ルールファイル §9 参照。必ずドライラン→承認→本番の2段階で実行

## デュアルモデル（Opus-Flash）間同期監視規約 (2026-05-23 制定)

- **原因**: Milestone M22.4 にて、Flash側は並列タスクとメインマージコミットを完了していたが、Opus側が `git log` を照合せず、一部の status ファイルや heartbeat の遅延のみから「停止（フリーズ）」と推測で誤判断して報告した。また、M22.5 起動時に CLI の心拍起動のみを指示してチャット側の自走ワークフロー実行指示を漏らし、ループが不作動になる事象が発生した。

- **必須ルール**:

  1. **Gitログ最優先照合**: Flashセッションのタスク状態を確認する際、status ファイルの読み込みのみに依存せず、**必ず `git log -n 5` を実行し、Flashの最新完了コミット（`[Flash/...]`）の有無を機械的に照合すること。**

  2. **推測での「フリーズ/未起動」判定禁止**: `flash_session.json` のハートビートタイムスタンプの遅延のみからフリーズを推測して報告することを厳禁とする。

  3. **非同期実行猶予時間の確保**: Flash側のタスク実行が開始された後、テスト実行を考慮して最低 5〜10 分の非同期猶予を持たせること。判断を下す前に必ず `git status` および `git branch -a` で他スレッドの進行状況を調査すること。

  4. **タイムロスゼロ自律レクチャー**: Flashセッションの停止（フリーズ、待機、またはサーバー再起動等によるプロセス停止）を検知し、タスクキューに未完了タスク（Pending）が無くセッションが遊んでいる状況、または手動再起動が必要な状況を検出した場合、Opusはユーザーからの指示を待たず、即座に次の手順と起動指示プロンプトを含む「自走再開レクチャー（起動プロンプト）」をコピペ可能な形式で提示し、タイムロスを最小化すること。

     - **自走再開レクチャーの提示手順**:

       1. ユーザーに対して同一プロジェクト（`c:\Users\PC_User\Desktop\script\video-automation`）内で新規チャットセッションを開始するよう誘導する。

       2. `flash_dispatch_prompt.md` から最新の指示コンテキストをロードし、以下の起動指示プロンプトを提示する。

  5. **起動指示プロンプトのテンプレート適用**: 提示する「自走再開レクチャー（起動指示プロンプト）」には、後述する起動指示プロンプトテンプレートをコピペ可能な形式で提示すること。

  6. **Flashセッション専用自己スコープ制限・表示ルール (2026-05-24 制定)**:
     - Flashセッションは、自身が「並行実行用セッション（Gemini Flash）」であることを常に認識し、表示・監視するステータス範囲を「自身が実行するセッション内（`flash_session.json` に記載されたタスク進捗・ハートビート・バッチ状態）」に厳格に限定しなければならない。
     - 全体統括情報や本家（Opus）側のステータスを自身のコンテキストに読み込む、あるいはそれらを分析・表示して統括ロール（Opus）を誤認することを厳禁とする（役割誤認による対話のハング・拒否を防ぐため）。
     - 初回指示プロンプトテンプレートには、自身のセッション内ステータスの常時表示（タイマー監視）のみを許可する制約を明示的に含めること。

     - **起動指示プロンプトテンプレート**:

       ```markdown

       # Flash専用セッション（Gemini Flash並列実行）起動指示プロンプト

       ## 1. 動作環境と原則

       - **プロジェクトパス**: `c:\Users\PC_User\Desktop\script\video-automation`

       - **最優先ルール**: プロジェクトルートの `GEMINI.md` に必ず従うこと。特に以下を厳守してください：

         - **Antigravity 2.0 セッション管理**: 原則セッション切り替え（1チャット=1タスク）は不要。本セッション（Flash専用）は並列タスク実行と結果報告に特化し、Opus専用セッション（本家）からの指令とレポート報告ベースで連携します。

         - **subprocess.Popen モック安全規約**: 内部スレッドの無限ループを防ぐため、`poll()`は即座に非None値を返し、`readline()`は空文字列を返すこと（`tests/conftest.py` の `safe_popen_mock` を使用）。

         - **ファイルI/O安全規約**: UTF-8ファイルへの書き込み・追記は**Python経由**で行うこと。PowerShellの `Add-Content` / `Set-Content` は使用禁止。

         - **証拠駆動型検証プロトコル (EBVP)**: 完了レポート等に推測表現（「可能性があります」等）は使用禁止。検証した事実のみを記述すること。

          - **自己ステータス監視制限（ハルシネーション防止）**: 本チャット内で進捗を監視・表示する際は、プロジェクト全体の統括ステータスではなく、**あなた自身のセッション（`flash_session.json`）に記載されたタスク進捗・ハートビート・バッチ状態のみ**に限定してください。あなたが全体統括（Opus）セッションであると誤認することを厳禁とします。

       ## 2. 共同処理機構（Orchestration Hub）との連携タスク

       1. **戦略指示（Directive）の読み込みと適用**:

          - `backend/agents/orchestration/opus_directive.json` をロードします。

          - `DirectiveApplicator` を使用して、指示された戦略（優先度・重点対象モジュール）をプロンプトおよびタスク生成ルールにマージしてください。

          - **現在の Opus Directive**:

            [最新の directive ファイルの優先度と戦略メモをここに埋め込む]

       2. **自律バッチ処理サイクル**:

          - 優先度設定に基づき、`backend/agents/orchestration/task_queue.json` から次のタスクバッチをロード、または自動生成します。

          - 割り当てられた各タスクを実行し、結果を `task_queue.json` および `flash_reports.jsonl` に保存します。

          - `pytest backend/tests/test_fitness_functions.py` が 100% PASS することを確認します。

       3. **定期心拍（Heartbeat）の出力**:

          - 5分おきに `flash_session.json` の `last_heartbeat` や `current_activity` を更新してください。

        ## 3. 実行手順

        チャット入力欄に以下の指示を入力して送信し、自走処理本体（タスク消化ループ）を起動してください。

        ```text

        flash-autonomous-entry.md のワークフローを読んで実行してください。

        ```

       ```

  6. **待機・エラー発生時の即時プッシュ通知規約 (2026-05-23 制定)**:

     - Flashセッション側でマージ不整合やスタッシュ競合等の理由により、人間（議長）の指示待ち（`waiting_user`）またはエラーによる停止が発生した場合、Flashエージェントは即座に `backend/agents/orchestration/message_box.jsonl` に高優先度（`MESSAGE_PRIORITY_HIGH`）の「エスカレーション・アラートメッセージ」を書き出さなければならない。

     - 本セッション（Opus）は、チャット開始時プロトコルにおいて、この高優先度メッセージを検出した場合、他のすべての通常の対話や分析に先立ち、最優先で「🔴 警告: Flashセッションが待機中です」という警告アラートと、コピペ可能な復旧用起動指示プロンプトを最速でユーザーに提示しなければならない。

## 非同期テストハング回避ルール (2026-05-24 制定)

- **原因**: `pytest.mark.anyio` や `async` を用いて FastAPI のコルーチンを直接テスト内で await すると、イベントループのクリーンアップ不良により pytest プロセスが終了せず、無限にハングする。

- **必須ルール**:

  1. FastAPI のルーター非同期テストは、`pytest.mark.anyio` や `async` による直接 await を原則禁止し、FastAPI の `TestClient` を用いた同期テストに統一すること。

  2. `TestClient` は `BackgroundTasks` をその場で同期的に実行するため、非同期待機ロジックを省略でき、安定したアサーションが行える。

  3. テスト対象内の `time.sleep` などの待機処理は、必ず `patch` でモック化（例: `patch("routers.dashboard_router.time.sleep")`）し、実行時間を0秒にクランプしてテストを瞬時に終了させること。

## 常駐プロセスのチャット内起動禁止ルール (2026-05-24 制定)

- **原因**: `tick_loop.py` などの無限ループ常駐プロセスをチャット内の `run_command`（または `manage_task`）経由でバックグラウンド起動すると、チャットUI上のエージェントが「無限プロセスの終了」を待ち続ける同期ロック（応答ハング）状態になり、チャットをクローズできなくなる。

- **必須ルール**:

  1. `tick_loop.py` などの無限常駐プロセスは、チャット内のツール（`run_command` 等）から起動することを**厳禁**とする。

  2. これらの常駐プロセスは、必ず**ユーザーの外部ターミナル（PowerShell やコマンドプロンプトなど）で独立して起動・バックグラウンド放置**すること。

  3. チャット内で実行して良いコマンドは、`pytest` やビルド等、有限時間で確実に自己終了するものに限定すること。

## 設計ストック管理規約 (2026-05-26 制定)

- **原因**: ロードマップを順に進めるだけではS/A級の高難度タスクが後回しになり、Phase終盤で設計負債が爆発する。また、設計在庫がないとFlashセッションの投入先が枯渇し稼働効率が低下する。
- **目的**: 常時10個の設計ストックを難易度ランキング化し、セッション投入を動的に最適化する

### §1 設計ストック常備義務
- **目標個数**: 常時10個（ダッシュボードで監視）
- **補充範囲**: 先3Phase分のMASTERタスクから補充
- **API**: `backend/agents/orchestration/design_stock.py` — `DesignStockStore`
- **データ**: `backend/agents/orchestration/design_stock.json`（手動編集禁止）

### §2 難易度ランキング体系
| 難易度 | 定義 | 投入先 | 事前要件 |
|:---:|:---|:---:|:---|
| **S** | 演出還流・自律協議体・ビジョンスコアリング | 🧠 Opus必須 | 3大論点チェック + ユーザー合意 |
| **A** | 複雑API設計・新規アーキテクチャ | 🧠 Opus必須 | 3大論点チェック |
| **B** | 新機能実装・設計判断あり | 🧠→⚡ Opus設計→Flash実装 | 設計書完成 |
| **C** | テスト追加・リファクタ・バグ修正 | ⚡ Flash即投入 | なし |

### §3 セッション投入の動的最適化
- **Flash投入**: C級を優先投入。B級は設計完了後に投入
- **Opus投入**: S/A級を議論。ストックの上位（難易度順）から着手
- **並行戦略**: Opusが S/A を議論中に、FlashはC級を並行消化

### §4 高難度タスク前倒しサジェスト（滞留検知）
- **S/Aランク**: 3日以上未進展 → 🔴 自動警告 + 「Opusで議論を前倒し」サジェスト
- **B/Cランク**: 7日以上未進展 → 🟡 警告
- **S/Aランク0件**: 🟡 「高難度タスクを後回しにしていないか確認」サジェスト

### §5 ロードマップ連動（先3Phase計画維持）
- `phase_state.json` に `roadmap_max_phase` と `next_milestones` を維持
- 現在Phase + 先3Phase分のタスクをMASTERから抽出し、設計ストックに補充
- Phase完了時: 次Phaseのタスクを自動で設計ストックに追加補充

### §6 Opusセッション開始時の義務（追加）
- 設計ストック数 ≧ 10 か確認 → 不足時は補充提案
- S/Aランクの滞留タスクがあるか確認 → ある場合は議論を優先
- **参照**: `backend/agents/orchestration/design_stock.py`、下位規約「Opus-Flash設計審査ゲート規約」

## Opus-Flash設計審査ゲートおよび暴走防止規約 (2026-05-24 制定)

- **原因**: 難易度の高いタスク（S〜A級）や演出論を含むタスクについて、事前の設計合意や論点整理が不十分なままFlashセッションに実装を渡すと、LLMの出力揺れやハルシネーションにより、実装が暴走（デグレードの多発、プロンプトの無限調整ループ）するリスクがある。

- **必須ルール**:

  1. **難易度ベースの事前設計義務**: 難易度 **S〜A** (演出還流、自律協議体、ビジョンスコアリング等) に分類されるタスクは、事前に本セッション（Opus）において論点を洗い出し、人間（ユーザー）と設計および境界値（プリセットやマッピングテーブルなど）の合意を完了すること。

  2. **Flashへの引渡し条件（安全弁）**:

     - 設計合意が完了し、`implementation_plan.md` または `temp_master.md` に具体的な「プリセット値」「動作フロー」「セルフチェック項目」が明文化されるまでは、タスクを `task_queue.json` に `status: "running"` で投入することを厳禁とする。

     - 議論が不十分、あるいは方針未決定のタスクは `status: "pending"` （または保留状態）のままロックしなければならない。

  3. **タイムスパン優先度最適化**: 議論や検討が不要で、境界値が確定している単純なタスク（難易度Cクラス、カバレッジ単体テスト等）は、設計並行期間中に先行してFlashセッションへ投入し、並行実装を実行させることで開発効率を最大化する。

  4. **論点解消ルーティン**: 難易度S〜AタスクをFlashへ受け渡す前に、以下の「3大論点チェック」をOpusセッションで実施し、解消したログをVerifiedFactsに記録することを必須ルーティンとする：

     - □ 曖昧な人間の指示（定性表現）からシステム的な物理量（定量）への変換マッピングが定義されているか

     - □ 例外的なエッジケース発生時の安全フォールバック（デフォルト値への回帰）が定義されているか

     - □ 誤出力時にシステム全体を壊さないためのガードレール（バリデーションやゲート）が用意されているか

## Flashセッション常時タイマー監視表示義務 (2026-05-24 制定)
- **原因**: Flashセッション側でバックグラウンド実行中に、UI上にアクティブな監視タスク（タイマー）が見えないと、セッションがハングしているのか、自走が生きているのかが視覚的に判断しづらくなる。
- **必須ルール**:
  1. **常時タイマー設定**: Flashセッションは、タスク処理の待機中、または処理の合間など、回答を出力してターンを終了する際、**必ず `schedule` ツールを呼び出して、タスクの重さや実行予測時間に応じた可変の監視タイマー（60秒〜900秒の間、デフォルト300秒）を設定しなければならない**。
  2. **視覚的生存証明**: これにより、会話中でもタスクを完遂するまで、UI上で監視タスクが常時表示されている状態を維持する。

## ダッシュボード表示規約 (2026-06-14 制定)

- **原因**: README.mdダッシュボードが「Trinity 4.0」時代のまま放置され、Phase 33/Trinity 5.0の実態と完全に乖離。リンク切れや内容の更新漏れが繰り返し発生していた
- **トリガー**: ユーザーが「ダッシュボード」「ダッシュボードを表示」「最新ダッシュボード」等を指示した場合
- **必須ルール**:
  1. **リンク表示義務**: 以下2つのダッシュボードリンクを**必ず**表示すること:
     - プロジェクトREADME: `README.md`（プロジェクトルート直下）
     - 運用ダッシュボード: `Human01_Official Artifact/サブエージェント体制報告/README.md`
  2. **インラインサマリー義務**: `phase_state.json` を読み取り、以下をインラインで表示すること:
     - Phase番号 / Milestone / カバレッジ / テスト数 / CRITICAL負債
     - Flashセッション状態（status / バッチ数 / タスク数）
     - 累計タスク処理数
  3. **鮮度チェック義務**: README.md上のPhase番号と `phase_state.json` のPhase番号を照合し、以下の3段階で判定すること:
     - 🟢 **最新**: Phase番号一致 → リンク表示のみ
     - 🟡 **軽微乖離**: Phase番号一致だがメトリクス（カバレッジ・テスト数等）が変化 → 差分を表示し更新を提案
     - 🔴 **陳腐化**: Phase番号が不一致 or 設計書完了数が乖離 → **README.mdを自動更新**してから表示
  4. **自動更新時の整合性検証**: README.md更新後、`pytest backend/tests/test_fitness_functions.py::TestFF27DashboardLinkageValidator` を実行し、リンク切れがないことを確認すること
  5. **Design Stock連動**: 設計書（DS-xxx）のstatusが `completed` に変わった場合、次回のダッシュボード表示時にREADME.mdの「直近の設計書完了実績」セクションに反映すること
- **禁止事項**:
  - ダッシュボードリンクなしでメトリクスだけ表示すること（リンク表示が主目的）
  - README.mdの手動更新時に `get_rel_link()` を経由せずにリンクを生成すること（ダッシュボードリンク安全規約 2026-05-26 参照）
- **参照**: `README.md`（プロジェクトルート）、`generate_subagent_reports.py` の `generate_dashboard_quick()`, `backend/agents/memory/phase_state.json`
