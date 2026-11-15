# BGM ディレクトリ

最終レンダリング（本線の `render_worker`）は、動画の全体に BGM を小さく敷き、話している間は自動で下げます。
音の組み立ては番組の仕上げ（`backend/program_package/remix.py`）と同じ物です。

## 曲を探す順

1. テンプレートの `branding.bgm_path`
2. このディレクトリの `default_bgm.mp3`（置いてあれば）
3. **曲の台帳** `backend/config/music.json` の `mainline.program` の番組の BGM
   （曲のファイルは環境変数 `AVS_MUSIC_DIR` の場所から、台帳の `file` の名前で探す）

曲そのものはリポジトリに置きません（公開リポジトリのため）。クラウドの作業場では次で持ってきます。

    python -m backend.program_package.music fetch 曲の置き場      # Drive の 20_素材/共通 か 30_AVS_作業/番組資産/曲 から落とす
    export AVS_MUSIC_DIR=曲の置き場

どこにも曲が無ければ、記録に `BGMミキシング(ファイルなし)` が出て、曲なしで書き出します。
入れた曲（どこから・曲名・出どころ）は書き出しの記録 `export.json` の `bgm` に残ります。

## 注意事項

- 出どころ（source）の書いていない曲は台帳から使いません
- 著作権フリーの音源を使用してください
