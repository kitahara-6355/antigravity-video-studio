# Flash タスク最適化ガイドライン

Flashがタスクを生成・実行する際の共通ルール。
全フェーズ共通で適用される。

---

## 1. タイムアウト防止テンプレート

### 大型モジュール（500行超）の場合
```
❌ 悪い例: {target_module} 全体をリファクタリングせよ
✅ 良い例: {target_module} の {target_function} (L{start}-L{end}) をリファクタリングせよ
```

**ルール**:
- 1タスクで変更対象は **3関数以内** に限定
- 行範囲を明示: `L{start}-L{end}`
- 500行超のモジュールは **必ず** 対象関数を指定

### subprocess を含むモジュールの場合
```
テスト作成時は以下のモックパターンを必ず使用:
- subprocess.Popen: poll()=0, readline()="", communicate=("","")
- conftest.py の safe_popen_mock fixture を使用
- テストタイムアウト: 60秒（pytest.ini 準拠）
```

---

## 2. テスト数ブーストテンプレート (parametrize活用)

### 基本パターン
```python
@pytest.mark.parametrize("input_val,expected", [
    ("正常入力1", "期待値1"),
    ("正常入力2", "期待値2"),
    ("空文字列", None),
    ("特殊文字!@#", "エスケープ済み"),
    ("超長文字列" * 100, "切り詰め済み"),
    (None, ValueError),
])
def test_{function_name}_parametrized(input_val, expected):
    ...
```

**ルール**:
- 1つの `@parametrize` で **6-10ケース** を含める
- 必ず含めるべきケース: 正常系2+, 境界値2+, 異常系2+
- テスト関数名に `_parametrized` サフィックスを付ける

### 効率計算
- 1テスト関数 × 8パラメータ = **8テストケース** としてカウント
- 50テスト関数 × 8パラメータ = **400テストケース**
- Phase 34-40 で 6フェーズ × 70テスト関数 × 6パラメータ = **2,520テストケース** → Phase 40ゲート(2500)達成

---

## 3. カバレッジ効率テンプレート

### A/B/C分類に基づく優先度
```
A分類（変更対象モジュール）: 100%カバー必須
B分類（依存基盤モジュール）: 推奨カバー（70%以上）
C分類（無関係モジュール）: TDR登録で管理
```

### エラーパスのカバレッジ
```python
# except ブロックのテスト: side_effect でエラーを注入
with patch("module.function", side_effect=ValueError("test")):
    result = target_function()
    assert result is None  # エラーハンドリング確認
```

---

## 4. テストフィクスチャ配置ルール

| Phase | フィクスチャ | パス |
|-------|------------|------|
| 37 | SRTファイル（5パターン） | `tests/fixtures/subtitles/` |
| 39 | テスト動画（3本） | `tests/fixtures/raw_videos/` |
| 40 | 24h運用テストシナリオ | `tests/fixtures/autonomous/` |

---

## 5. TDR登録テンプレート

新規モジュールに `except Exception` を追加した場合:
```python
from backend.agents.memory.technical_debt import TechnicalDebtStore
store = TechnicalDebtStore()
store.register_debt(
    category="ACCEPTED_SAFETY",
    file_path="<BACKEND_DIR相対パス>",  # 例: "video_pipeline/new_module.py"
    line_number=<行番号>,
    pattern="except Exception",
    cause_pattern="DP-02",
    fix_pattern="Replace with specific exceptions",
    registered_by="flash_phase_N"
)
```

**重要**: `file_path` は `backend/` を含めず、`BACKEND_DIR` からの相対パスで登録すること。
