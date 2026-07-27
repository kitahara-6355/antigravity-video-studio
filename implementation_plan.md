# 実施計画書 (Implementation Plan) - T-batch_2011eb-ds-ds-raw-s9-97fe

## 1. 目的
`backend/video_pipeline/thumbnail_generator.py` に対する十分なテストを追加し、設計仕様（正常系、フレーム抽出、テキストオーバーレイ、Pillow未インストール時のフォールバック、FFmpeg実行テスト、safe_popen_mockテスト）をすべて満たすことを検証します。

## 2. 対象要件とテスト設計
1. **正常系テスト**:
   - `generate` が成功した際に `ThumbnailResult.success=True` を返すことを確認します。
   - タイトルがある場合にテキストオーバーレイが正しく実行され、タイトルがない場合にオーバーレイなしの画像が生成されることを検証します。
2. **フレーム抽出検証**:
   - `_extract_frame` が正しく呼び出され、JPEG画像が指定パスに生成されることを確認します。
3. **テキストオーバーレイ検証**:
   - タイトル文字列がある場合、ベース画像（JPEG）に対してPillowを使ってテキストが重ね合わされることを確認します。
4. **Pillow未インストール時のフォールバック**:
   - Pillowが無い環境（インポートエラー）を模倣した際に、`_add_text_overlay` は何もせず元のフレーム抽出画像をそのまま返し、`generate` が正常に成功することを確認します。
5. **FFmpeg実行テスト (`@pytest.mark.slow`)**:
   - 実際のFFmpegバイナリを呼び出し、ダミー動画ファイルから実際にJPEG画像を生成するテスト。
6. **Popen安全モックテスト**:
   - `conftest.py` に定義されている `safe_popen_mock` フィクスチャを使用し、実際のFFmpegコマンドを叩かずに `subprocess.Popen` をモックするテスト。
7. **パラメータ化テスト**:
   - `@pytest.mark.parametrize` により、正常系2ケース以上、境界値2ケース以上、異常系2ケース以上の合計6〜10ケースを検証します。
     - **正常系**: (1) タイトルあり/Pillowあり、(2) タイトルなし/Pillowあり、(3) タイトルあり/Pillowなし
     - **境界値**: (4) 空タイトル、(5) 極端に長いタイトル、(6) 動画時間(duration)が極端に長い/短いケース
     - **異常系**: (7) 動画ファイルが存在しない、(8) ffprobeエラー（デフォルト10秒フォールバック）、(9) ffmpeg抽出エラー (CalledProcessError)

## 3. 作業内容
1. `backend/tests/test_video_pipeline_thumbnail.py` を新規作成します。
2. パラメータ化されたテスト、Popenモックテスト、slow実機テストを記述します。
3. `pytest backend/tests/test_video_pipeline_thumbnail.py` を実行してすべて PASS することを確認します。
4. ※ 変更ファイルはテストコードのみ（1ファイル）とし、プロダクションコードに変更を加えない場合は3ファイル/3関数の制限を安全にクリアします。もしプロダクションコードの修正が必要になった場合でも、最小限（3関数以内）の変更に留めます。新規の `except Exception` が発生した場合はTDR（Technical Debt Registry）に登録します。

## 4. 影響範囲
- `backend/tests/test_video_pipeline_thumbnail.py` (新規テストファイル)
- `implementation_plan.md` (本計画書)
