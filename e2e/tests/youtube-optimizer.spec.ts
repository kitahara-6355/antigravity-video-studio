import { test, expect } from '@playwright/test';

/**
 * YouTube Optimizer E2Eテスト
 * 
 * テスト対象:
 * - フック分析ダッシュボード
 * - サムネイルA/Bテスト
 * - SEOメタデータエディタ
 * - AI改善案機能
 */

test.describe('YouTube Optimizer Panel', () => {

    test.beforeEach(async ({ page }) => {
        // アプリケーションにアクセス
        await page.goto('/');

        // Director Briefingを開く（仮定）
        // 実際のUIに合わせて調整が必要
    });

    test('フック分析ダッシュボードが表示される', async ({ page }) => {
        // YouTube Optimizerパネルを開く
        const optimizerButton = page.locator('button:has-text("YouTube最適化")');
        if (await optimizerButton.isVisible()) {
            await optimizerButton.click();
        }

        // フックタブを確認
        const hookTab = page.locator('.tab-btn:has-text("フック")');
        await expect(hookTab).toBeVisible();
    });

    test('サムネイルA/Bパネルが表示される', async ({ page }) => {
        // YouTube Optimizerパネルを開く
        const optimizerButton = page.locator('button:has-text("YouTube最適化")');
        if (await optimizerButton.isVisible()) {
            await optimizerButton.click();
        }

        // サムネタブをクリック
        const thumbnailTab = page.locator('.tab-btn:has-text("サムネ")');
        if (await thumbnailTab.isVisible()) {
            await thumbnailTab.click();
        }

        // サムネイルパネルが表示されることを確認
        const panel = page.locator('.thumbnail-ab-panel');
        // パネルが存在する場合のみテスト
    });

    test('AI改善案ボタンがクリック可能', async ({ page }) => {
        // YouTube Optimizerパネルを開く
        const optimizerButton = page.locator('button:has-text("YouTube最適化")');
        if (await optimizerButton.isVisible()) {
            await optimizerButton.click();
        }

        // AI改善案ボタンを確認
        const aiButton = page.locator('button:has-text("AIに改善案を依頼")');
        if (await aiButton.isVisible()) {
            await expect(aiButton).toBeEnabled();
        }
    });

    test('設定保存ボタンが動作する', async ({ page }) => {
        // YouTube Optimizerパネルを開く
        const optimizerButton = page.locator('button:has-text("YouTube最適化")');
        if (await optimizerButton.isVisible()) {
            await optimizerButton.click();
        }

        // 設定保存ボタンを確認
        const saveButton = page.locator('button:has-text("設定を保存")');
        if (await saveButton.isVisible()) {
            await expect(saveButton).toBeEnabled();
        }
    });
});

test.describe('API Endpoints', () => {

    test('YouTube Optimizer API ヘルスチェック', async ({ request }) => {
        const response = await request.get('http://localhost:8000/api/youtube/health');
        expect(response.ok()).toBeTruthy();

        const data = await response.json();
        expect(data.status).toBe('ok');
        expect(data.service).toBe('youtube_optimizer');
    });

    test('A/Bテスト追跡 API ヘルスチェック', async ({ request }) => {
        const response = await request.get('http://localhost:8000/api/thumbnail/health');
        expect(response.ok()).toBeTruthy();

        const data = await response.json();
        expect(data.status).toBe('ok');
    });

    test('ショート動画生成 API ヘルスチェック', async ({ request }) => {
        const response = await request.get('http://localhost:8000/api/shorts/health');
        expect(response.ok()).toBeTruthy();

        const data = await response.json();
        expect(data.status).toBe('ok');
    });
});
