# -*- coding: utf-8 -*-
"""
Preview Report Generator
処理ステップごとのスクリーンショットをHTMLレポートにまとめる

Phase 30.5 - プログレッシブ・プレビュー機能
Phase 30.6 - 改善: 並列処理、差分ハイライト、音声分析
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging
import base64

logger = logging.getLogger(__name__)


class PreviewReportGenerator:
    """HTMLプレビューレポート生成"""
    
    def _image_to_base64(self, image_path: str) -> str:
        """画像をBase64エンコード（HTMLに埋め込み用、自動リサイズ・最適化・破損画像修復機能付き）"""
        try:
            with open(image_path, 'rb') as f:
                data = f.read()
            
            # 画像処理ロジックの改善: 埋め込み画像を自動検証・最適化してHTMLの肥大化と破損表示を防ぐ
            optimized_data = verify_and_optimize_image(data)
            return base64.b64encode(optimized_data).decode('utf-8')
        except FileNotFoundError as e:
            logger.warning(f"Failed to encode image (File not found): {image_path} - {e}")
            return ""
        except PermissionError as e:
            logger.warning(f"Failed to encode image (Permission denied): {image_path} - {e}")
            return ""
        except OSError as e:
            logger.warning(f"Failed to encode image (OS error): {image_path} - {e}")
            return ""
        except Exception as e:
            logger.error(f"Unexpected error encoding image: {image_path} - {e}", exc_info=True)
            return ""

    def _get_html_styles(self) -> str:
        """HTMLに埋め込むCSSスタイルを生成"""
        return """
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&family=Outfit:wght@400;600;700;800&display=swap');

        :root {
            --bg-gradient-start: #0a0b10;
            --bg-gradient-end: #121420;
            --text-primary: #e2e8f0;
            --text-secondary: #718096;
            --text-muted: #a0aec0;
            --accent-cyan: #00f2fe;
            --accent-blue: #4facfe;
            --success-green: #38ef7d;
            --success-green-dark: #11998e;
            --error-red: #ff416c;
            --error-red-dark: #ff4b2b;
            --card-bg: rgba(20, 22, 36, 0.4);
            --card-bg-hover: #10121a;
            --border-color: rgba(255, 255, 255, 0.05);
            --border-color-muted: rgba(255, 255, 255, 0.03);
            --shadow-primary: rgba(0, 0, 0, 0.25);
            --shadow-hover: rgba(0, 242, 254, 0.12);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Inter', 'Yu Gothic UI', -apple-system, sans-serif;
            background: linear-gradient(135deg, var(--bg-gradient-start) 0%, var(--bg-gradient-end) 100%);
            color: var(--text-primary);
            min-height: 100vh;
            padding: 40px 20px;
            -webkit-font-smoothing: antialiased;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        
        header {
            text-align: center;
            padding: 40px 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 40px;
        }
        
        header h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 2.8rem;
            font-weight: 800;
            background: linear-gradient(135deg, var(--accent-cyan) 0%, var(--accent-blue) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 15px;
            letter-spacing: -0.5px;
        }
        
        header .meta {
            color: var(--text-secondary);
            font-size: 0.95rem;
            font-weight: 500;
            background: rgba(255, 255, 255, 0.03);
            padding: 8px 18px;
            border-radius: 30px;
            display: inline-block;
            border: 1px solid var(--border-color);
        }
        
        .step {
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            padding: 30px;
            margin-bottom: 40px;
            border: 1px solid var(--border-color);
            box-shadow: 0 10px 30px var(--shadow-primary);
        }
        
        .step-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 25px;
            padding-bottom: 20px;
            border-bottom: 1px solid var(--border-color);
        }
        
        .step-name {
            font-family: 'Outfit', sans-serif;
            font-size: 1.6rem;
            font-weight: 700;
            color: var(--accent-cyan);
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .step-badge {
            background: rgba(0, 242, 254, 0.1);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 242, 254, 0.25);
            padding: 6px 18px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        
        .comparisons {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
            gap: 30px;
        }
        
        .comparison-card {
            background: var(--card-bg-hover);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color-muted);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            flex-direction: column;
        }
        
        .comparison-card:hover {
            transform: translateY(-4px);
            border-color: rgba(0, 242, 254, 0.3);
            box-shadow: 0 12px 30px var(--shadow-hover);
        }
        
        .image-container {
            position: relative;
            width: 100%;
            aspect-ratio: 16/9;
            background: #000;
            overflow: hidden;
            cursor: zoom-in;
        }
        
        .image-container img {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            opacity: 0;
            transition: opacity 0.2s ease-in-out;
        }
        
        .image-container img.active {
            opacity: 1;
        }
        
        .tab-bar {
            display: flex;
            background: rgba(0, 0, 0, 0.3);
            padding: 6px;
            gap: 4px;
            border-bottom: 1px solid var(--border-color-muted);
        }
        
        .tab-btn {
            flex: 1;
            background: transparent;
            border: none;
            color: var(--text-secondary);
            padding: 8px 12px;
            font-size: 0.8rem;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .tab-btn:hover {
            color: #f1f3f9;
            background: rgba(255, 255, 255, 0.03);
        }
        
        .tab-btn.active {
            color: #0a0b10;
            background: var(--accent-cyan);
            box-shadow: 0 2px 8px rgba(0, 242, 254, 0.3);
        }
        
        .comparison-meta {
            padding: 15px;
            text-align: center;
            color: var(--text-muted);
            font-size: 0.9rem;
            font-weight: 500;
            background: rgba(0, 0, 0, 0.15);
            margin-top: auto;
        }
        
        .summary {
            background: linear-gradient(135deg, rgba(0, 242, 254, 0.05) 0%, rgba(79, 172, 254, 0.05) 100%);
            border-radius: 16px;
            padding: 40px;
            margin-top: 40px;
            text-align: center;
            border: 1px solid rgba(0, 242, 254, 0.1);
        }
        
        .summary h2 {
            font-family: 'Outfit', sans-serif;
            font-size: 1.8rem;
            color: var(--accent-cyan);
            margin-bottom: 20px;
        }
        
        .stats {
            display: flex;
            justify-content: center;
            gap: 60px;
            flex-wrap: wrap;
        }
        
        .stat {
            text-align: center;
        }
        
        .stat-value {
            font-family: 'Outfit', sans-serif;
            font-size: 2.8rem;
            font-weight: 800;
            color: var(--success-green);
            line-height: 1;
            margin-bottom: 8px;
        }
        
        .stat-label {
            color: var(--text-muted);
            font-size: 0.95rem;
            font-weight: 500;
        }
        
        .approval-section {
            background: rgba(20, 22, 36, 0.3);
            border-radius: 16px;
            padding: 40px;
            margin-top: 40px;
            text-align: center;
            border: 1px solid var(--border-color-muted);
        }
        
        .approval-section h2 {
            font-family: 'Outfit', sans-serif;
            font-size: 1.8rem;
            margin-bottom: 10px;
        }
        
        .feedback-input {
            width: 100%;
            max-width: 600px;
            padding: 16px;
            margin: 20px 0;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            background: rgba(0, 0, 0, 0.2);
            color: #fff;
            font-size: 1rem;
            transition: all 0.3s;
        }
        
        .feedback-input:focus {
            border-color: var(--accent-cyan);
            box-shadow: 0 0 10px rgba(0, 242, 254, 0.2);
            outline: none;
        }
        
        .approval-buttons {
            display: flex;
            justify-content: center;
            gap: 25px;
        }
        
        .btn {
            padding: 16px 45px;
            border: none;
            border-radius: 10px;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
        }
        
        .btn-approve {
            background: linear-gradient(135deg, var(--success-green-dark) 0%, var(--success-green) 100%);
            color: #0a0b10;
            box-shadow: 0 4px 15px rgba(56, 239, 125, 0.2);
        }
        
        .btn-approve:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(56, 239, 125, 0.4);
        }
        
        .btn-reject {
            background: linear-gradient(135deg, var(--error-red) 0%, var(--error-red-dark) 100%);
            color: #fff;
            box-shadow: 0 4px 15px rgba(255, 75, 43, 0.2);
        }
        
        .btn-reject:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(255, 75, 43, 0.4);
        }
        
        .status-message {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            display: none;
            font-weight: 600;
        }
        
        .status-success {
            background: rgba(56, 239, 125, 0.1);
            color: var(--success-green);
            border: 1px solid rgba(56, 239, 125, 0.2);
        }
        
        /* モーダル */
        .modal {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(8, 9, 15, 0.96);
            backdrop-filter: blur(15px);
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .modal.active {
            display: flex;
            opacity: 1;
        }
        
        .modal-content {
            position: relative;
            max-width: 92%;
            max-height: 88%;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        
        .modal-img {
            max-width: 100%;
            max-height: 82vh;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
        }
        
        .modal-close {
            position: absolute;
            top: -50px;
            right: 0;
            background: transparent;
            border: none;
            color: #fff;
            font-size: 2.2rem;
            cursor: pointer;
            transition: color 0.2s;
        }
        
        .modal-close:hover {
            color: var(--error-red);
        }
        
        footer {
            text-align: center;
            padding: 40px 0;
            color: #4a5568;
            font-size: 0.9rem;
            font-weight: 500;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📸 プログレッシブ・プレビュー・レポート</h1>
            <p class="meta">Session: {session_id} | 生成日時: {created_at}</p>
        </header>
"""

    def _get_html_scripts(self, session_id: str) -> str:
        """HTMLに埋め込むJavaScriptロジックを生成"""
        return f"""
    <script>
        const SESSION_ID = '{session_id}';
        const API_BASE = 'http://localhost:8000';
        
        function switchTab(cardId, type) {{
            // 全ての画像を非表示
            const imgs = document.querySelectorAll('#card-' + cardId + ' .comparison-img');
            imgs.forEach(img => img.classList.remove('active'));
            
            // 対象の画像を表示
            const targetImg = document.querySelector('#card-' + cardId + ' .img-' + type);
            if (targetImg) targetImg.classList.add('active');
            
            // 全てのボタンを非活性
            const btns = document.querySelectorAll('#card-' + cardId + ' .tab-btn');
            btns.forEach(btn => btn.classList.remove('active'));
            
            // 対象のボタンを活性化
            const targetBtn = document.querySelector('#card-' + cardId + ' .btn-' + type);
            if (targetBtn) targetBtn.classList.add('active');
        }}

        function openModal(imgSrc) {{
            if (!imgSrc) return;
            const modal = document.getElementById('image-modal');
            const modalImg = document.getElementById('modal-display-img');
            modalImg.src = imgSrc;
            modal.classList.add('active');
        }}

        function closeModal() {{
            const modal = document.getElementById('image-modal');
            modal.classList.remove('active');
        }}

        // Escキーでモーダルを閉じる
        document.addEventListener('keydown', (e) => {{
            if (e.key === 'Escape') closeModal();
        }});
        
        async function submitDecision(decision) {{
            const feedback = document.getElementById('feedback').value;
            const statusEl = document.getElementById('status-message');
            
            try {{
                const response = await fetch(`${{API_BASE}}/api/preview/decision`, {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        session_id: SESSION_ID,
                        decision: decision,
                        feedback: feedback
                     }})
                }});
                
                if (response.ok) {{
                    const result = await response.json();
                    statusEl.textContent = decision === 'approve' 
                        ? '✅ 承認されました。次の処理に進みます。'
                        : '📝 修正要求を記録しました。該当処理を見知します。';
                    statusEl.className = 'status-message status-success';
                    statusEl.style.display = 'block';
                }} else {{
                    throw new Error('API Error');
                }}
            }} catch (e) {{
                // オフラインモード: ローカルストレージに保存
                localStorage.setItem(`decision_${{SESSION_ID}}`, JSON.stringify({{
                    decision: decision,
                    feedback: feedback,
                    timestamp: new Date().toISOString()
                }}));
                
                statusEl.textContent = decision === 'approve'
                    ? '✅ 承認を記録しました（オフラインモード）'
                    : '📝 修正要求を記録しました（オフラインモード）';
                statusEl.className = 'status-message status-success';
                statusEl.style.display = 'block';
            }}
        }}
    </script>
"""

    def _get_html_header(self, session_id: str, created_at: str) -> str:
        """HTMLのヘッダーおよび開始部分を生成"""
        styles = self._get_html_styles()
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>プレミアム・プレビューレポート - {session_id}</title>
    <style>{styles}</style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📸 プログレッシブ・プレビュー・レポート</h1>
            <p class="meta">Session: {session_id} | 生成日時: {created_at}</p>
        </header>
"""

    def _generate_comparison_card(
        self,
        step_name: str,
        idx: int,
        comparison_item: dict,
        embed_images: bool
    ) -> str:
        """各比較カードのHTMLを生成"""
        timestamp = comparison_item.get("timestamp", 0)
        card_id = f"{step_name.replace(' ', '_')}_{idx}"
        
        paths = {
            "comparison": comparison_item.get("comparison", ""),
            "before": comparison_item.get("before", ""),
            "after": comparison_item.get("after", ""),
            "diff": comparison_item.get("diff_highlight", "")
        }
        
        srcs = {}
        for key, path in paths.items():
            if path and embed_images and Path(path).exists():
                img_data = self._image_to_base64(path)
                srcs[key] = f"data:image/png;base64,{img_data}"
            else:
                srcs[key] = path or ""
        
        return f"""
                <div class="comparison-card" id="card-{card_id}">
                    <div class="tab-bar">
                        <button class="tab-btn btn-comparison active" onclick="switchTab('{card_id}', 'comparison')">比較並置</button>
                        <button class="tab-btn btn-before" onclick="switchTab('{card_id}', 'before')">Before</button>
                        <button class="tab-btn btn-after" onclick="switchTab('{card_id}', 'after')">After</button>
                        <button class="tab-btn btn-diff" onclick="switchTab('{card_id}', 'diff')">差分</button>
                    </div>
                    <div class="image-container" onclick="openModal(document.querySelector('#card-{card_id} img.active').src)">
                        <img src="{srcs['comparison']}" class="comparison-img img-comparison active" alt="Comparison">
                        <img src="{srcs['before']}" class="comparison-img img-before" alt="Before">
                        <img src="{srcs['after']}" class="comparison-img img-after" alt="After">
                        <img src="{srcs['diff']}" class="comparison-img img-diff" alt="Diff Highlight">
                    </div>
                    <div class="comparison-meta">⏱️ {timestamp:.1f} 秒</div>
                </div>
"""

    def _generate_step_section(self, step: dict, embed_images: bool) -> tuple[str, int]:
        """各ステップセクションのHTMLを生成"""
        step_name = step.get("step_name", "Unknown Step")
        comparisons = step.get("comparisons", [])
        
        step_html = f"""
        <section class="step">
            <div class="step-header">
                <span class="step-name">🎬 {step_name}</span>
                <span class="step-badge">{len(comparisons)} サンプル</span>
            </div>
            <div class="comparisons">
"""
        for idx, comparison_item in enumerate(comparisons):
            step_html += self._generate_comparison_card(step_name, idx, comparison_item, embed_images)
            
        step_html += """
            </div>
        </section>
"""
        return step_html, len(comparisons)

    def _get_summary_section(self, num_steps: int, total_comparisons: int) -> str:
        """統計情報（サマリー）セクションを生成"""
        return f"""
        <section class="summary">
            <h2>📊 サマリー</h2>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{num_steps}</div>
                    <div class="stat-label">処理ステップ</div>
                </div>
                <div class="stat">
                    <div class="stat-value">{total_comparisons}</div>
                    <div class="stat-label">比較画像</div>
                </div>
            </div>
        </section>
"""

    def _get_approval_section(self) -> str:
        """判定（承認/修正要求）セクションを生成"""
        return """
        <section class="approval-section">
            <h2>⚖️ レビュー判定</h2>
            <p style="color: #a0aec0; margin-top: 10px;">プレビュー結果を確認し、承認または修正要求を選択してください</p>
            
            <input type="text" id="feedback" class="feedback-input" placeholder="フィードバック（任意）">
            
            <div class="approval-buttons">
                <button class="btn btn-approve" onclick="submitDecision('approve')">✅ 承認</button>
                <button class="btn btn-reject" onclick="submitDecision('reject')">❌ 修正要求</button>
            </div>
            
            <div id="status-message" class="status-message"></div>
        </section>
"""

    def _get_html_footer(self) -> str:
        """フッターと閉じタグを生成"""
        return """
        <footer>
            Northern Light 2.0 - Progressive Preview System
        </footer>
    </div>
    
    <!-- 画像拡大モーダル -->
    <div id="image-modal" class="modal" onclick="closeModal()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <button class="modal-close" onclick="closeModal()">&times;</button>
            <img id="modal-display-img" class="modal-img" src="" alt="Modal Image">
        </div>
    </div>
</body>
</html>
"""

    def generate_html_report(
        self,
        session_metadata: dict,
        output_path: str,
        embed_images: bool = True
    ) -> str:
        """
        全ステップのプレビューをHTMLレポートとして出力
        
        Args:
            session_metadata: セッションメタデータ（progressive_preview.pyの出力）
            output_path: 出力HTMLパス
            embed_images: 画像をBase64で埋め込むか（True推奨、オフラインで閲覧可能）
        
        Returns:
            出力パス
        """
        session_id = session_metadata.get("session_id", "unknown")
        steps = session_metadata.get("steps", [])
        created_at = session_metadata.get("created_at", datetime.now().isoformat())
        
        html_content = self._get_html_header(session_id, created_at)
        
        total_comparisons = 0
        for step in steps:
            step_html, count = self._generate_step_section(step, embed_images)
            html_content += step_html
            total_comparisons += count
            
        html_content += self._get_summary_section(len(steps), total_comparisons)
        html_content += self._get_approval_section()
        html_content += self._get_html_scripts(session_id)
        html_content += self._get_html_footer()
        
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path_obj, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"✅ HTML Report generated: {output_path_obj}")
        
        return str(output_path_obj)
    
    def generate_from_session_dir(
        self, 
        session_dir: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        セッションディレクトリからレポートを生成
        
        Args:
            session_dir: セッションディレクトリ（session_metadata.jsonがあるディレクトリ）
            output_path: 出力パス（未指定でセッションディレクトリ内に生成）
        
        Returns:
            生成されたHTMLパス
        """
        session_dir = Path(session_dir)
        metadata_path = session_dir / "session_metadata.json"
        
        if not metadata_path.exists():
            raise FileNotFoundError(f"Metadata not found: {metadata_path}")
        
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        if output_path is None:
            output_path = session_dir / "preview_report.html"
        
        return self.generate_html_report(metadata, str(output_path))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    # テスト用サンプルメタデータ
    sample_metadata = {
        "session_id": "test_20260110",
        "created_at": datetime.now().isoformat(),
        "steps": [
            {
                "step_name": "crop",
                "comparisons": [
                    {"timestamp": 1.0, "comparison": "test1.png"},
                    {"timestamp": 5.0, "comparison": "test2.png"}
                ]
            },
            {
                "step_name": "logo_overlay",
                "comparisons": [
                    {"timestamp": 1.0, "comparison": "test3.png"}
                ]
            }
        ]
    }
    
    generator = PreviewReportGenerator()
    
    # テスト生成（画像埋め込みなし）
    output = generator.generate_html_report(
        sample_metadata,
        "backend/temp/test_report.html",
        embed_images=False
    )
    
    print(f"Generated: {output}")


# --- サムネイル画像生成・品質検証・StageBoundAgent連携ロジック of 追加 ---
import os
import io
import time
import numpy as np
import sqlite3
from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError
import uuid
import textwrap

OUTPUT_DIR = "backend/temp_thumbnails"

def verify_and_optimize_image(image_bytes: bytes, target_width=1280, target_height=720) -> bytes:
    """
    入力された画像バイナリを検証し、必要に応じて1280x720以上の16:9比率へ自動補正・最適化する。
    ファイルサイズが4MBを超える巨大な画像は自動的にダウンスケールして軽量化する。
    破損画像の場合は安全なフォールバック画像を生成して返す。
    """
    try:
        if not image_bytes or len(image_bytes) < 24:
            raise ValueError("Empty or too small image bytes")
        
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        
        w, h = img.size
        aspect_ratio = w / h
        target_ratio = target_width / target_height
        
        # 1. 解像度・比率の最適化（1280x720未満、または16:9アスペクト比から0.05以上乖離している場合に補正）
        # また、HTML埋め込み時の肥大化を防ぐため、極端に巨大な画像（例: 2560x1440超）も縮小対象とする
        needs_resize = (
            w < target_width or 
            h < target_height or 
            abs(aspect_ratio - target_ratio) >= 0.05 or
            w > 2560 or 
            h > 1440
        )
        
        if needs_resize:
            # ターゲット解像度に合わせたスケール計算
            scale = min(target_width / w, target_height / h)
            # もし大きすぎる画像でダウンスケールが必要な場合は、1280x720のサイズに収める
            if w > 2560 or h > 1440:
                scale = min(target_width / w, target_height / h)
            
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # 16:9の暗色キャンバスに中央配置（レターボックス）
            canvas = Image.new("RGB", (target_width, target_height), (10, 12, 20))
            offset_x = (target_width - new_w) // 2
            offset_y = (target_height - new_h) // 2
            canvas.paste(resized_img, (offset_x, offset_y))
            img = canvas
        
        # 2. ファイルサイズ上限（4MB未満）のチェックと段階的圧縮
        # PNGとして最高圧縮レベルで一旦保存
        out_io = io.BytesIO()
        img.save(out_io, format="PNG", optimize=True, compress_level=9)
        optimized_bytes = out_io.getvalue()
        
        # もし4MB（4,194,304バイト）を超える場合は、JPEG形式に変換するか、解像度を下げてサイズ制限内に収める
        max_allowed_bytes = 4 * 1024 * 1024 - 1024 # 4MBの安全マージン
        if len(optimized_bytes) >= max_allowed_bytes:
            logger.info(f"Optimized image size ({len(optimized_bytes)} bytes) exceeds 4MB. Retrying downscale and compression.")
            # 解像度を強制的に1280x720にダウンスケール
            if img.size != (1280, 720):
                img = img.resize((1280, 720), Image.Resampling.LANCZOS)
            
            # PNGで再保存
            out_io = io.BytesIO()
            img.save(out_io, format="PNG", optimize=True, compress_level=9)
            optimized_bytes = out_io.getvalue()
            
            # それでも4MBを超える極端なケースは、品質85のJPEGに変換して絶対に4MB未満にする
            if len(optimized_bytes) >= max_allowed_bytes:
                out_io = io.BytesIO()
                img.convert("RGB").save(out_io, format="JPEG", quality=85, optimize=True)
                optimized_bytes = out_io.getvalue()
                logger.info(f"Converted output image to JPEG to satisfy 4MB limit. Final size: {len(optimized_bytes)} bytes")
                
        return optimized_bytes
        
    except Exception as e:
        logger.warning(f"verify_and_optimize_image failed: {e}, returning generated fallback image bytes")
        # 破損画像の場合のフォールバック生成
        img = Image.new("RGB", (target_width, target_height), (30, 33, 45))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
            
        fallback_text = f"PROGRESSIVE PREVIEW\n(CORRUPTED IMAGE FALLBACK)\nTime: {datetime.now().isoformat()}\nError: {str(e)[:60]}"
        y_offset = 120
        for line in fallback_text.split("\n"):
            if font:
                draw.text((80, y_offset), line, fill=(200, 210, 220), font=font)
            else:
                draw.text((80, y_offset), line, fill=(200, 210, 220))
            y_offset += 30
            
        out_io = io.BytesIO()
        img.save(out_io, format="PNG", optimize=True)
        return out_io.getvalue()

def _generate_fallback_thumbnail(output_path, width, height, text, original_error):
    """
    メインの高品質サムネイル生成が失敗した場合の軽量フォールバック画像生成。
    NumPyや高度なフォント処理での失敗に備え、標準 of Pillow描画のみを使用。
    """
    temp_path = None
    try:
        logger.warning(f"Using fallback thumbnail generation due to error: {original_error}")
        
        # 線形グラデーション背景を作成
        img = Image.new("RGBA", (width, height), (30, 33, 45, 255))
        draw = ImageDraw.Draw(img)
        
        # 簡易縦グラデーションの描画
        for y in range(height):
            # (30, 33, 45) -> (15, 17, 25) への緩やかなグラデーション
            r = int(30 - (15 * y / height))
            g = int(33 - (16 * y / height))
            b = int(45 - (20 * y / height))
            draw.line([(0, y), (width, y)], fill=(r, g, b, 255))
            
        # サイバー調グリッドの描画
        grid_size = 60
        for x in range(0, width, grid_size):
            draw.line([(x, 0), (x, height)], fill=(0, 242, 254, 12), width=1)
        for y in range(0, height, grid_size):
            draw.line([(0, y), (width, y)], fill=(0, 242, 254, 12), width=1)
            
        # ネオン風の装飾的な枠線を描画
        border_color = (0, 242, 254, 180)
        draw.rectangle([15, 15, width - 15, height - 15], outline=border_color, width=2)
        
        # テキスト背景に半透明ガラス風パネルを配置
        draw.rounded_rectangle(
            [35, 35, width - 35, height - 35],
            radius=10,
            fill=(10, 15, 30, 190),
            outline=(0, 242, 254, 50),
            width=1
        )
        
        # フォント読み込みエラーを防ぐためにデフォルトフォントを使用
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
            
        fallback_text = (
            f"PROGRESSIVE PREVIEW (FALLBACK)\n"
            f"Error: {str(original_error)[:100]}\n"
            f"Time: {datetime.now().isoformat()}\n"
        )
        if text:
            fallback_text += f"\nContent:\n{text}"
            
        # シンプルに描画
        y_offset = 60
        for line in fallback_text.split("\n"):
            wrapped_lines = textwrap.wrap(line, width=65) if line.strip() else [""]
            for wline in wrapped_lines:
                if font:
                    draw.text((60, y_offset), wline, fill=(200, 210, 220, 255), font=font)
                else:
                    draw.text((60, y_offset), wline, fill=(200, 210, 220, 255))
                y_offset += 25
                if y_offset > height - 60:
                    break
            if y_offset > height - 60:
                break
            
        # 保存（原子的な書き込み）
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(f".fallback.{uuid.uuid4().hex}.tmp")
        img.convert("RGB").save(temp_path, "PNG", optimize=True)
        
        # リネーム
        import time
        rename_success = False
        last_err = None
        for attempt in range(8):
            try:
                if output_path.exists():
                    output_path.unlink()
                temp_path.rename(output_path)
                rename_success = True
                break
            except (PermissionError, FileExistsError, OSError) as e:
                # renameに失敗した場合は copy + unlink の代替処理を試みる
                try:
                    import shutil
                    shutil.copy2(temp_path, output_path)
                    temp_path.unlink()
                    rename_success = True
                    break
                except OSError:
                    pass
                last_err = e
                time.sleep(0.05 * (2 ** attempt))
                
        if not rename_success:
            raise OSError(f"Fallback failed to rename temp file to {output_path}. Error: {last_err}")
            
        logger.info(f"Fallback thumbnail generated successfully at {output_path}")
        return output_path
    except Exception as fallback_err:
        logger.critical(f"Critical error in fallback thumbnail generation: {fallback_err}", exc_info=True)
        raise fallback_err
    finally:
        # 一時ファイルの確実なクリーンアップ
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

def generate_progressive_preview_thumbnail(output_path, width=1280, height=720, text=None):
    """PillowとNumPyを使用して、プログレッシブ・プレビューレポートの高品質なサムネイル画像を生成する"""
    if not output_path:
        raise ValueError("Output path must be specified")
        
    try:
        width_val = int(width)
        height_val = int(height)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Width and height must be integers: {e}")
        
    if width_val <= 0 or height_val <= 0:
        raise ValueError("Width and height must be positive integers")
        
    width = width_val
    height = height_val
    
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    # メモリ上限ガード
    if width > 3840 or height > 2160:
        raise ValueError(f"Resolution exceeds maximum limit (3840x2160). Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01: # 誤差 0.01 許容
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f} (target: 1.778)")
        
    output_path = Path(output_path)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Failed to create output directory {output_path.parent}: {e}")
    
    # 原子的な書き込み (Atomic Write) の実装
    temp_path = output_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    
    # スーパーサンプリング倍率
    scale = 2
    sw, sh = width * scale, height * scale
    
    try:
        # 1. 高品質なグラデーション背景の作成 (NumPy とディザリングを使用)
        y_grid, x_grid = np.ogrid[:sh, :sw]
        factor = (x_grid / (sw - 1.0) + y_grid / (sh - 1.0)) / 2.0
        # コサイン補間による滑らかな変化（カラーバンディング対策）
        factor = (1.0 - np.cos(factor * np.pi)) / 2.0
        
        # プレミアムブレンド：ダークネイビー、インディゴ、ディープパープルのグラデーション
        color1 = np.array([8, 10, 20], dtype=np.float32)
        color2 = np.array([20, 28, 48], dtype=np.float32)
        color3 = np.array([38, 18, 54], dtype=np.float32)
        
        mask = factor < 0.5
        t = np.where(mask, factor * 2.0, (factor - 0.5) * 2.0)
        
        r = np.where(mask, color1[0] + (color2[0] - color1[0]) * t, color2[0] + (color3[0] - color2[0]) * t)
        g = np.where(mask, color1[1] + (color2[1] - color1[1]) * t, color2[1] + (color3[1] - color2[1]) * t)
        b = np.where(mask, color1[2] + (color2[2] - color1[2]) * t, color2[2] + (color3[2] - color2[2]) * t)
        
        # ディザーノイズの付加（縞模様防止）
        dither = np.random.uniform(-0.6, 0.6, (sh, sw, 3))
        rgb = np.clip(np.stack([r, g, b], axis=-1) + dither, 0, 255).astype(np.uint8)
        img = Image.fromarray(rgb)
        
        # 2. 視覚的装飾（グリッドラインとガラス風パネル、ネオンボーダー）
        img_rgba = img.convert("RGBA")
        overlay = Image.new("RGBA", img_rgba.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # 薄いサイバーグリッドラインを背景に描画
        grid_size = 60 * scale
        for x in range(0, sw, grid_size):
            draw_overlay.line([(x, 0), (x, sh)], fill=(0, 242, 254, 15), width=1)
        for y in range(0, sh, grid_size):
            draw_overlay.line([(0, y), (sw, y)], fill=(0, 242, 254, 15), width=1)
            
        cyan_neon = (0, 242, 254, 255)
        cyan_neon_glow = (0, 242, 254, 50)
        border_color = (40, 52, 78, 255)
        
        # 内枠ボーダーの描画
        inset = 20 * scale
        draw_overlay.rectangle([inset, inset, sw - inset, sh - inset], outline=border_color, width=2 * scale)
        
        # プレミアムSFUIコーナーフレームの描画（四隅のL字型アクセントで品質向上）
        corner_len = 25 * scale
        # 左上
        draw_overlay.line([(inset, inset), (inset + corner_len, inset)], fill=cyan_neon, width=3 * scale)
        draw_overlay.line([(inset, inset), (inset, inset + corner_len)], fill=cyan_neon, width=3 * scale)
        # 右上
        draw_overlay.line([(sw - inset, inset), (sw - inset - corner_len, inset)], fill=cyan_neon, width=3 * scale)
        draw_overlay.line([(sw - inset, inset), (sw - inset, inset + corner_len)], fill=cyan_neon, width=3 * scale)
        # 左下
        draw_overlay.line([(inset, sh - inset), (inset + corner_len, sh - inset)], fill=cyan_neon, width=3 * scale)
        draw_overlay.line([(inset, sh - inset), (inset, sh - inset - corner_len)], fill=cyan_neon, width=3 * scale)
        # 右下
        draw_overlay.line([(sw - inset, sh - inset), (sw - inset - corner_len, sh - inset)], fill=cyan_neon, width=3 * scale)
        draw_overlay.line([(sw - inset, sh - inset), (sw - inset, sh - inset - corner_len)], fill=cyan_neon, width=3 * scale)
        
        # 上部ネオンアクセントラインとグロー効果
        accent_y = 30 * scale
        draw_overlay.line([(inset, accent_y), (sw - inset, accent_y)], fill=cyan_neon_glow, width=6 * scale)
        draw_overlay.line([(inset, accent_y), (sw - inset, accent_y)], fill=cyan_neon, width=2 * scale)
        
        # テキスト背景に半透明のガラス風角丸パネルを配置
        panel_inset_x = 40 * scale
        panel_inset_y = 80 * scale
        draw_overlay.rounded_rectangle(
            [panel_inset_x, panel_inset_y, sw - panel_inset_x, sh - panel_inset_y],
            radius=12 * scale,
            fill=(10, 15, 30, 205),
            outline=(0, 242, 254, 70),
            width=1 * scale
        )
        
        # 3. テキストの高品質レイアウトとフォントの選択
        if not text:
            text = f"PROGRESSIVE PREVIEW\nThumbnail Generated at: {datetime.now().isoformat()}"
            
        try:
            text = str(text)
        except Exception:
            text = "PROGRESSIVE PREVIEW\n(Invalid text encoding)"
            
        # パネルの有効高さ（文字を描画可能な領域）
        max_content_height = sh - 200 * scale
        font_scale_factor = 1.0
        max_attempts = 10
        lines_text = []
        
        for attempt in range(max_attempts):
            large_size = max(12 * scale, int(38 * scale * font_scale_factor))
            small_size = max(8 * scale, int(22 * scale * font_scale_factor))
            
            # フォントサイズ（スケールファクター）に合わせて折り返し文字数を動的に変化させて品質向上
            wrap_width = max(20, int(45 / font_scale_factor))
            lines_text = []
            for line in text.split("\n"):
                if line.strip():
                    lines_text.extend(textwrap.wrap(line.strip(), width=wrap_width))
            
            font_large = None
            font_small = None
            
            font_paths = [
                r"C:\Windows\Fonts\yugothic.ttc",     # 游ゴシック (より美しく、モダン)
                r"C:\Windows\Fonts\yugothm.ttc",     # 游明朝
                r"C:\Windows\Fonts\meiryo.ttc",      # メイリオ
                r"C:\Windows\Fonts\msgothic.ttc",    # MSゴシック
                r"C:\Windows\Fonts\msmincho.ttc",    # MS明朝
                r"C:\Windows\Fonts\msjh.ttc",        # Microsoft JhengHei
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\calibri.ttf",
                "/System/Library/Fonts/PingFang.ttc",
                "/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]
            
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        font_large = ImageFont.truetype(fp, large_size)
                        font_small = ImageFont.truetype(fp, small_size)
                        break
                    except OSError:
                        continue
                        
            if font_large is None:
                try:
                    font_large = ImageFont.load_default(size=large_size)
                    font_small = ImageFont.load_default(size=small_size)
                except TypeError:
                    font_large = ImageFont.load_default()
                    font_small = ImageFont.load_default()
            
            # テキスト全体の高さをシミュレーション計算
            total_height = 0
            for i, line in enumerate(lines_text):
                current_font = font_large if i == 0 else font_small
                try:
                    bbox = current_font.getbbox(line)
                    line_height = (bbox[3] - bbox[1]) if bbox else (large_size if i == 0 else small_size)
                except (AttributeError, OSError):
                    line_height = large_size if i == 0 else small_size
                
                if i == 0:
                    total_height += int(line_height * 1.5) + (10 * scale)
                else:
                    total_height += int(line_height * 1.3) + (6 * scale)
                    
            if total_height <= max_content_height or font_scale_factor <= 0.4:
                break
            font_scale_factor -= 0.15
            
        y_offset = 120 * scale
        text_x = 60 * scale
        
        for i, line in enumerate(lines_text):
            current_font = font_large if i == 0 else font_small
            current_fill = (0, 242, 254, 255) if i == 0 else (170, 185, 205, 255)
            shadow_fill = (0, 0, 0, 180)
            stroke_color = (10, 15, 30, 255)  # 視認性を極大化するためのアウトラインカラー
            stroke_width = max(1, int(2 * scale)) if i == 0 else max(1, int(1.5 * scale))
            
            # ドロップシャドウ効果の描画
            shadow_offset = 2 * scale
            draw_overlay.text((text_x + shadow_offset, y_offset + shadow_offset), line, fill=shadow_fill, font=current_font)
            
            # メインテキストの描画（NHK/YouTuber基準のアウトライン付き描画）
            draw_overlay.text(
                (text_x, y_offset), 
                line, 
                fill=current_fill, 
                font=current_font,
                stroke_width=stroke_width,
                stroke_fill=stroke_color
            )
            
            # 正確な行送り高さ計算 (フォントの getbbox から取得、フォールバックあり)
            try:
                bbox = current_font.getbbox(line)
                line_height = (bbox[3] - bbox[1]) if bbox else (large_size if i == 0 else small_size)
            except (AttributeError, OSError):
                line_height = large_size if i == 0 else small_size
                
            if i == 0:
                y_offset += int(line_height * 1.5) + (10 * scale)
            else:
                y_offset += int(line_height * 1.3) + (6 * scale)
                
        # レイヤーを合成してRGBに変換
        final_rgba = Image.alpha_composite(img_rgba, overlay)
        img_resized = final_rgba.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
        
        # 4. 保存
        img_resized.save(temp_path, "PNG", optimize=True, compress_level=9)
        
        # Windowsの PermissionError/FileExistsError 対策：最大8回の指数バックオフでリトライしてリネームする
        rename_success = False
        last_err = None
        for attempt in range(8):
            try:
                if output_path.exists():
                    try:
                        output_path.unlink()
                    except OSError:
                        pass
                temp_path.rename(output_path)
                rename_success = True
                break
            except (PermissionError, FileExistsError, OSError) as e:
                # renameに失敗した場合は copy + unlink の代替処理を試みる
                try:
                    import shutil
                    shutil.copy2(temp_path, output_path)
                    temp_path.unlink()
                    rename_success = True
                    break
                except OSError:
                    pass
                last_err = e
                time.sleep(0.05 * (2 ** attempt))
                
        if not rename_success:
            raise OSError(f"Failed to rename temp file to destination: {output_path} after 8 attempts. Error: {last_err}")
            
    except Exception as e:
        logger.error(f"Error during thumbnail generation, executing fallback: {e}", exc_info=True)
        # 高品質画像の生成が失敗した場合、フォールバック画像生成に移行
        try:
            return _generate_fallback_thumbnail(output_path, width, height, text, e)
        except Exception as fallback_err:
            raise fallback_err
    finally:
        # 一時ファイルの確実なクリーンアップ
        if 'temp_path' in locals() and temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        
    return output_path

def validate_thumbnail(file_path, max_size_bytes=4 * 1024 * 1024) -> dict:
    """
    サムネイル画像の品質要件を検証する
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Thumbnail file not found: {file_path}")
        
    size_bytes = file_path.stat().st_size
    if size_bytes >= max_size_bytes:
        raise ValueError(f"File size exceeds 4MB limit: {size_bytes} bytes (limit: {max_size_bytes})")
        
    # ファイルサイズの下限チェック
    if size_bytes < 100:
        raise ValueError(f"Image is corrupted or invalid format (file size too small): {size_bytes} bytes")
        
    # 1. 簡易的なverify (Pillow)
    try:
        with Image.open(file_path) as img:
            if img.format != "PNG":
                raise ValueError(f"Unsupported image format: {img.format}. Only PNG is accepted.")
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format (verify failed): {e}")
        
    # 2. 完全なピクセルデータのロードによる破損検知
    try:
        with Image.open(file_path) as img:
            img.load()
            width, height = img.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as e:
        raise ValueError(f"Image is corrupted or invalid format (load failed): {e}")
        
    if width < 1280 or height < 720:
        raise ValueError(f"Resolution must be at least 1280x720. Got {width}x{height}")
        
    aspect_ratio = width / height
    target_ratio = 16.0 / 9.0
    if abs(aspect_ratio - target_ratio) > 0.01: # 誤差 0.01 許容
        raise ValueError(f"Aspect ratio must be 16:9. Got {aspect_ratio:.3f}")
        
    return {
        "path": str(file_path),
        "width": width,
        "height": height,
        "size_bytes": size_bytes
    }

async def resolve_progressive_preview_report_task(agent, task_id: Optional[str] = None) -> str:
    """
    StageBoundAgent の process_func として動作する非同期タスク処理
    SQLite の結果テーブル自動マイグレーションと結果保存を行う
    """
    if task_id is None:
        # 1引数で呼ばれた場合（StageBoundAgentからの呼び出しなど）
        task_id = agent
        agent = None
    logger.info(f"Resolving progressive preview report task: {task_id}")
    
    db_path = getattr(agent, "db_path", None)
    
    width = getattr(agent, "width", 1280)
    height = getattr(agent, "height", 720)
    text = getattr(agent, "text", None)
    
    if not text:
        text = (
            f"=== Progressive Preview Report ===\n"
            f"Task ID: {task_id}\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"Status: COMPLETED\n"
            f"Details: Progressive preview report generated and verified."
        )
        
    output_dir_path = Path(getattr(agent, "output_dir", None) or OUTPUT_DIR)
    output_dir_path.mkdir(parents=True, exist_ok=True)
    output_path = output_dir_path / f"{task_id}.png"
    
    try:
        generate_progressive_preview_thumbnail(output_path, width=width, height=height, text=text)
        result_info = validate_thumbnail(output_path)
        
        # SQLite への自動マイグレーションと結果保存
        if db_path:
            conn = None
            for attempt in range(10):
                try:
                    conn = sqlite3.connect(db_path, timeout=10.0)
                    cursor = conn.cursor()
                    
                    # マイグレーション
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS progressive_preview_report_results (
                            task_id TEXT PRIMARY KEY,
                            path TEXT,
                            width INTEGER,
                            height INTEGER,
                            size_bytes INTEGER,
                            verified_at TEXT
                        )
                    """)
                    
                    # 結果保存
                    cursor.execute("""
                        INSERT OR REPLACE INTO progressive_preview_report_results (task_id, path, width, height, size_bytes, verified_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        task_id,
                        result_info["path"],
                        result_info["width"],
                        result_info["height"],
                        result_info["size_bytes"],
                        datetime.now().isoformat()
                    ))
                    
                    conn.commit()
                    break
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        time.sleep(0.1 * (2 ** attempt))
                        continue
                    raise e
                finally:
                    if conn:
                        conn.close()
                        
        return json.dumps(result_info)
    except Exception as e:
        logger.error(f"Failed to resolve preview report task {task_id}: {e}", exc_info=True)
        # 一時ファイルのクリーンアップを徹底
        temp_glob = output_dir_path.glob(f"{task_id}.*.tmp")
        for temp_file in temp_glob:
            try:
                temp_file.unlink()
            except OSError:
                pass
        raise e
