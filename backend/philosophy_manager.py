"""
哲学管理システム（Philosophy Manager）
Phase 30.6 - 哲学の可視化、タグ付け、検索機能

Northern Light 2.0 - Soul Narrative Enhancement
"""
try:  # backend/ を直接 sys.path に載せている経路にも対応する
    from backend.path_resolver import writable_path as _writable_path
except ImportError:
    from path_resolver import writable_path as _writable_path


import json
from pathlib import Path
from datetime import datetime
from typing import List
import logging
from PIL import Image, ImageDraw
import uuid

logger = logging.getLogger(__name__)

BRANDING_DIR = Path(__file__).parent / "branding"
EVOLUTION_LOG_PATH = BRANDING_DIR / "evolution_log.json"


class PhilosophyManager:
    """
    哲学の管理・検索・タグ付け・ダッシュボード機能
    
    機能:
    1. 哲学タグ付け（テーマ別自動分類）
    2. 哲学検索・引用機能
    3. 哲学可視化ダッシュボード（HTML生成）
    """
    
    # 哲学テーマのタグ定義
    PHILOSOPHY_TAGS = {
        "技術": ["技術", "システム", "効率", "自動化", "ツール", "処理"],
        "芸術": ["芸術", "表現", "美", "創造", "デザイン", "ビジュアル"],
        "協調": ["協調", "チーム", "合意", "コラボ", "連携", "共鳴"],
        "成長": ["成長", "進化", "学び", "深化", "発展", "向上"],
        "哲学": ["哲学", "思想", "理念", "信念", "価値", "本質"],
        "バランス": ["バランス", "調和", "融合", "統合", "両立"]
    }
    
    def __init__(self):
        self.evolution_log = self._load_evolution_log()
    
    def _load_evolution_log(self) -> dict:
        """evolution_log.jsonを読み込む"""
        try:
            with open(EVOLUTION_LOG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"entries": [], "philosophies": [], "integrated_philosophy": None}
    
    def _save_evolution_log(self):
        """evolution_log.jsonを保存"""
        with open(EVOLUTION_LOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.evolution_log, f, ensure_ascii=False, indent=2)
    
    # === 🟢 哲学タグ付け機能 ===
    def auto_tag_philosophy(self, philosophy_text: str) -> List[str]:
        """
        哲学テキストからタグを自動抽出
        
        Args:
            philosophy_text: 哲学テキスト
        
        Returns:
            タグ of リスト
        """
        if not isinstance(philosophy_text, str):
            return ["その他"]
            
        tags = []
        for tag, keywords in self.PHILOSOPHY_TAGS.items():
            for keyword in keywords:
                if keyword in philosophy_text:
                    if tag not in tags:
                        tags.append(tag)
                    break
        return tags if tags else ["その他"]
    
    def tag_all_philosophies(self):
        """全哲学にタグを自動付与"""
        philosophies = self.evolution_log.get("philosophies") or []
        if not isinstance(philosophies, list):
            philosophies = []
        
        for philosophy_entry in philosophies:
            if isinstance(philosophy_entry, dict):
                text = philosophy_entry.get("philosophy", "")
                philosophy_entry["tags"] = self.auto_tag_philosophy(text)
        
        self.evolution_log["philosophies"] = philosophies
        self._save_evolution_log()
        logger.info(f"Tagged {len(philosophies)} philosophies")
        return philosophies
    
    # === 🟢 哲学検索・引用機能 ===
    def search_philosophies(
        self, 
        query: str = None,
        tags: List[str] = None,
        limit: int = 10
    ) -> List[dict]:
        """
        哲学を検索
        
        Args:
            query: 検索クエリ（部分一致）
            tags: フィルタするタグ
            limit: 最大結果数
        
        Returns:
            マッチした哲学リスト
        """
        philosophies = self.evolution_log.get("philosophies") or []
        if not isinstance(philosophies, list):
            philosophies = []
        results = []
        
        for philosophy_entry in philosophies:
            if isinstance(philosophy_entry, dict):
                text = philosophy_entry.get("philosophy", "")
                tags_list = philosophy_entry.get("tags") or []
                if not isinstance(tags_list, list):
                    tags_list = []
                
                # クエリによるフィルタ
                if query and query.lower() not in text.lower():
                    continue
                
                # タグによるフィルタ
                if tags:
                    if not any(t in tags_list for t in tags):
                        continue
                
                results.append(philosophy_entry)
        
        return results[:limit]
    
    def cite_philosophy(self, index: int = -1) -> str:
        """
        哲学を引用形式で取得
        
        Args:
            index: 哲学のインデックス（-1で最新）
        
        Returns:
            引用形式のテキスト
        """
        philosophies = self.evolution_log.get("philosophies") or []
        if not isinstance(philosophies, list) or not philosophies:
            return "（哲学履歴なし）"
        
        try:
            if not isinstance(index, int):
                raise TypeError("Index must be an integer")
            philosophy_entry = philosophies[index]
            if isinstance(philosophy_entry, dict):
                text = philosophy_entry.get("philosophy", "")
                timestamp = philosophy_entry.get("timestamp", "不明")
                return f"「{text}」— {timestamp}"
            return f"「{philosophy_entry}」"
        except (IndexError, TypeError):
            return "（該当する哲学なし）"
    
    def get_philosophy_by_tag(self, tag: str) -> List[dict]:
        """タグで哲学を検索"""
        return self.search_philosophies(tags=[tag])
    
    # === 🟡 哲学可視化ダッシュボード ===
    def _prepare_dashboard_data(self) -> dict:
        """ダッシュボード用の各種データを準備する"""
        philosophies = self.evolution_log.get("philosophies") or []
        if not isinstance(philosophies, list):
            philosophies = []
        entries = self.evolution_log.get("entries") or []
        if not isinstance(entries, list):
            entries = []
        integrated = self.evolution_log.get("integrated_philosophy")
        integration_history = self.evolution_log.get("integration_history") or []
        if not isinstance(integration_history, list):
            integration_history = []
        
        # タグ統計
        tag_stats = {}
        for philosophy_entry in philosophies:
            if isinstance(philosophy_entry, dict):
                tags_list = philosophy_entry.get("tags") or []
                if isinstance(tags_list, list):
                    for tag in tags_list:
                        tag_stats[tag] = tag_stats.get(tag, 0) + 1
        
        # タイムラインデータ
        timeline_items = []
        for i, philosophy_entry in enumerate(philosophies):
            if isinstance(philosophy_entry, dict):
                timeline_items.append({
                    "index": i + 1,
                    "philosophy": philosophy_entry.get("philosophy", ""),
                    "timestamp": philosophy_entry.get("timestamp", ""),
                    "tags": philosophy_entry.get("tags", []),
                    "summary": philosophy_entry.get("session_summary", "")
                })
        
        return {
            "philosophies": philosophies,
            "entries": entries,
            "integrated": integrated,
            "integration_history": integration_history,
            "tag_stats": tag_stats,
            "timeline_items": timeline_items
        }

    def _render_dashboard_html(self, data: dict) -> str:
        """準備されたデータからHTML文字列をレンダリングする"""
        philosophies = data["philosophies"]
        entries = data["entries"]
        integrated = data["integrated"]
        integration_history = data["integration_history"]
        tag_stats = data["tag_stats"]
        timeline_items = data["timeline_items"]
        
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>哲学ダッシュボード | Soul Narrative</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        
        h1 {{
            text-align: center;
            font-size: 2.5rem;
            margin-bottom: 30px;
            background: linear-gradient(90deg, #00ff87, #60efff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        
        .stat-card {{
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            padding: 25px;
            text-align: center;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1);
        }}
        
        .stat-value {{
            font-size: 3rem;
            font-weight: bold;
            background: linear-gradient(90deg, #60efff, #00ff87);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .stat-label {{
            font-size: 0.9rem;
            color: #aaa;
            margin-top: 10px;
        }}
        
        .integrated-philosophy {{
            background: linear-gradient(135deg, rgba(0,255,135,0.2), rgba(96,239,255,0.2));
            border-radius: 20px;
            padding: 30px;
            margin-bottom: 40px;
            text-align: center;
            border: 2px solid rgba(0,255,135,0.3);
        }}
        
        .integrated-philosophy h2 {{
            font-size: 1.2rem;
            color: #60efff;
            margin-bottom: 15px;
        }}
        
        .integrated-philosophy .philosophy-text {{
            font-size: 1.5rem;
            font-style: italic;
            line-height: 1.6;
        }}
        
        .tags-section {{
            margin-bottom: 40px;
        }}
        
        .tags-section h2 {{
            font-size: 1.5rem;
            margin-bottom: 20px;
            color: #60efff;
        }}
        
        .tags-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        
        .tag {{
            background: rgba(0,255,135,0.2);
            border: 1px solid rgba(0,255,135,0.5);
            border-radius: 20px;
            padding: 8px 16px;
            font-size: 0.9rem;
        }}
        
        .tag-count {{
            background: rgba(96,239,255,0.3);
            border-radius: 10px;
            padding: 2px 8px;
            margin-left: 8px;
            font-size: 0.8rem;
        }}
        
        .timeline {{
            position: relative;
            padding-left: 30px;
        }}
        
        .timeline::before {{
            content: '';
            position: absolute;
            left: 10px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: linear-gradient(180deg, #00ff87, #60efff);
        }}
        
        .timeline-item {{
            position: relative;
            margin-bottom: 30px;
            padding: 20px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            border-left: 3px solid #00ff87;
        }}
        
        .timeline-item::before {{
            content: '';
            position: absolute;
            left: -25px;
            top: 25px;
            width: 12px;
            height: 12px;
            background: #00ff87;
            border-radius: 50%;
            border: 2px solid #1a1a2e;
        }}
        
        .timeline-number {{
            position: absolute;
            left: -45px;
            top: 20px;
            font-size: 0.8rem;
            color: #60efff;
        }}
        
        .timeline-philosophy {{
            font-size: 1.1rem;
            font-style: italic;
            margin-bottom: 10px;
        }}
        
        .timeline-meta {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.85rem;
            color: #888;
        }}
        
        .timeline-tags {{
            display: flex;
            gap: 5px;
        }}
        
        .timeline-tag {{
            background: rgba(96,239,255,0.2);
            border-radius: 10px;
            padding: 3px 10px;
            font-size: 0.75rem;
        }}
        
        .search-box {{
            margin-bottom: 30px;
        }}
        
        .search-box input {{
            width: 100%;
            padding: 15px 20px;
            border-radius: 30px;
            border: 2px solid rgba(255,255,255,0.2);
            background: rgba(255,255,255,0.1);
            color: #fff;
            font-size: 1rem;
        }}
        
        .search-box input::placeholder {{
            color: #888;
        }}
        
        .search-box input:focus {{
            outline: none;
            border-color: #00ff87;
        }}
        
        footer {{
            text-align: center;
            margin-top: 50px;
            padding: 20px;
            color: #666;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🧠 哲学ダッシュボード</h1>
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-value">{len(philosophies)}</div>
                <div class="stat-label">累積哲学数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(entries)}</div>
                <div class="stat-label">セッション数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(tag_stats)}</div>
                <div class="stat-label">テーマ数</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">{len(integration_history)}</div>
                <div class="stat-label">統合回数</div>
            </div>
        </div>
        
        {"" if not integrated else f'''
        <div class="integrated-philosophy">
            <h2>🎯 統合哲学（Soul Narrative）</h2>
            <div class="philosophy-text">{integrated}</div>
        </div>
        '''}
        
        <div class="tags-section">
            <h2>📊 テーマ別統計</h2>
            <div class="tags-container">
                {"".join([f'<span class="tag">{tag}<span class="tag-count">{count}</span></span>' for tag, count in sorted(tag_stats.items(), key=lambda x: -x[1])])}
            </div>
        </div>
        
        <div class="search-box">
            <input type="text" id="search" placeholder="🔍 哲学を検索..." onkeyup="filterTimeline()">
        </div>
        
        <h2 style="color: #60efff; margin-bottom: 20px;">📜 哲学タイムライン</h2>
        
        <div class="timeline" id="timeline">
            {"".join([f'''
            <div class="timeline-item" data-philosophy="{item['philosophy'].lower()}" data-tags="{' '.join(item['tags']).lower()}">
                <span class="timeline-number">#{item['index']}</span>
                <div class="timeline-philosophy">「{item['philosophy']}」</div>
                <div class="timeline-meta">
                    <span>{item['timestamp']}</span>
                    <div class="timeline-tags">
                        {"".join([f'<span class="timeline-tag">{tag}</span>' for tag in item['tags']])}
                    </div>
                </div>
            </div>
            ''' for item in reversed(timeline_items)])}
        </div>
        
        <footer>
            Northern Light 2.0 - Soul Narrative | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </footer>
    </div>
    
    <script>
        function filterTimeline() {{
            const query = document.getElementById('search').value.toLowerCase();
            const items = document.querySelectorAll('.timeline-item');
            
            items.forEach(item => {{
                const philosophy = item.getAttribute('data-philosophy');
                const tags = item.getAttribute('data-tags');
                
                if (philosophy.includes(query) || tags.includes(query)) {{
                    item.style.display = 'block';
                }} else {{
                    item.style.display = 'none';
                }}
            }});
        }}
    </script>
</body>
</html>"""

    def generate_dashboard_html(self, output_path: str = None) -> str:
        """
        哲学履歴の可視化ダッシュボードをHTML生成
        
        Args:
            output_path: 出力パス（省略時はデフォルト）
        
        Returns:
            生成されたHTMLファイルのパス
        """
        if output_path is None:
            # 生成物なので writable_path 経由にする。`BRANDING_DIR` 直書きだと、
            # __main__ ブロックを runpy で実行するテストが Git 追跡下の
            # backend/branding/philosophy_dashboard.html を上書きしていた
            # （runpy はモジュールを別名前空間で再実行するので、
            # インポート済みモジュールへの patch が効かない）。
            output_path = _writable_path("backend/branding/philosophy_dashboard.html")
        
        data = self._prepare_dashboard_data()
        html = self._render_dashboard_html(data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"Dashboard generated: {output_path}")
        return str(output_path)
    
    def get_dashboard_summary(self) -> dict:
        """ダッシュボード用のサマリーデータを取得"""
        data = self._prepare_dashboard_data()
        return {
            "total_philosophies": len(data["philosophies"]),
            "total_sessions": len(data["entries"]),
            "tag_stats": data["tag_stats"],
            "integrated_philosophy": data["integrated"],
            "latest_philosophy": self.cite_philosophy(-1),
            "integration_count": len(data["integration_history"])
        }

    def generate_philosophy_thumbnail(
        self,
        output_path,
        width: int = 1280,
        height: int = 720,
        text: str = "Philosophy"
    ) -> Path:
        """Pillowを使用して、指定された解像度とテキストでサムネイル画像を生成する"""
        try:
            width = int(width)
            height = int(height)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Width and height must be integers: {e}")
            
        if width <= 0 or height <= 0:
            raise ValueError(f"Width and height must be positive integers. Got {width}x{height}")
            
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 原子的な書き込み (Atomic Write)
        temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            img = Image.new("RGB", (width, height), color=(73, 109, 137))
            d = ImageDraw.Draw(img)
            d.text((10, 10), text, fill=(255, 255, 0))
            img.save(temp_path, "PNG")
            
            if output_path.exists():
                output_path.unlink()
            temp_path.rename(output_path)
        except (OSError, ValueError) as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error(f"Failed to generate philosophy thumbnail atomically: {e}")
            raise
            
        return output_path

    def validate_thumbnail_quality(self, file_path) -> dict:
        """サムネイル画像の品質要件を検証する"""
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
            
        size_bytes = file_path.stat().st_size
        if size_bytes >= 4 * 1024 * 1024:
            raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes")
            
        try:
            with Image.open(file_path) as img:
                img.verify()
        except (OSError, SyntaxError, ValueError) as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        try:
            with Image.open(file_path) as img:
                img.load()
                width, height = img.size
        except (OSError, SyntaxError, ValueError) as e:
            raise ValueError(f"Image is corrupted or invalid format: {e}")
            
        if width < 1280 or height < 720:
            raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
            
        aspect_ratio = width / height
        target_ratio = 16.0 / 9.0
        if abs(aspect_ratio - target_ratio) > 0.01:
            raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
            
        return {
            "path": str(file_path),
            "width": width,
            "height": height,
            "size_bytes": size_bytes
        }

    async def resolve_philosophy_thumbnail_task(self, task_id: str) -> str:
        """StageBoundAgent の process_func として動作する非同期タスク処理"""
        import json
        output_dir = Path(getattr(self, "output_dir", None) or _writable_path("backend/temp_thumbnails"))
        output_path = output_dir / f"{task_id}.png"
        
        width = getattr(self, "width", 1280)
        height = getattr(self, "height", 720)
        text = getattr(self, "text", "Philosophy")
        
        self.generate_philosophy_thumbnail(output_path, width=width, height=height, text=text)
        result_info = self.validate_thumbnail_quality(output_path)
        return json.dumps(result_info)



# グローバルインスタンス
philosophy_manager = PhilosophyManager()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    pm = PhilosophyManager()
    
    # 全哲学にタグを自動付与
    print("=== タグ付け ===")
    tagged = pm.tag_all_philosophies()
    for p in tagged:
        print(f"  「{p.get('philosophy', '')}」 -> {p.get('tags', [])}")
    
    # 検索テスト
    print("\n=== 検索テスト ===")
    results = pm.search_philosophies(query="技術")
    for r in results:
        print(f"  {r.get('philosophy', '')}")
    
    # 引用
    print("\n=== 引用テスト ===")
    print(pm.cite_philosophy(-1))
    
    # ダッシュボード生成
    print("\n=== ダッシュボード生成 ===")
    path = pm.generate_dashboard_html()
    print(f"Generated: {path}")
    
    # サマリー
    print("\n=== サマリー ===")
    summary = pm.get_dashboard_summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
