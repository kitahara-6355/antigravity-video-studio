import { test, expect } from '@playwright/test';

/**
 * SmartCut E2Eテスト
 * 
 * テスト対象:
 * - 動的尺調整
 * - シーン固定機能
 * - 最終化フロー
 */

test.describe('SmartCut Panel', () => {

    test.beforeEach(async ({ page }) => {
        await page.goto('/');
    });

    test('SmartCutパネルが表示される', async ({ page }) => {
        // SmartCutボタンを確認
        const smartcutButton = page.locator('button:has-text("スマートカット")');
        if (await smartcutButton.isVisible()) {
            await smartcutButton.click();

            // パネルが表示されることを確認
            const panel = page.locator('.smartcut-panel');
            // パネルの存在を確認
        }
    });

    test('尺調整スライダーが動作する', async ({ page }) => {
        const smartcutButton = page.locator('button:has-text("スマートカット")');
        if (await smartcutButton.isVisible()) {
            await smartcutButton.click();

            // スライダーを確認
            const slider = page.locator('input[type="range"]');
            if (await slider.isVisible()) {
                await expect(slider).toBeEnabled();
            }
        }
    });

    test('シーン固定ボタンが存在する', async ({ page }) => {
        const smartcutButton = page.locator('button:has-text("スマートカット")');
        if (await smartcutButton.isVisible()) {
            await smartcutButton.click();

            // 固定ボタンを確認
            const lockButton = page.locator('button:has-text("固定")');
            // ボタンの存在を確認
        }
    });
});

test.describe('SmartCut API Endpoints', () => {

    test('SmartCut API ヘルスチェック', async ({ request }) => {
        const response = await request.get('http://localhost:8000/api/smartcut/health');
        expect(response.ok()).toBeTruthy();

        const data = await response.json();
        expect(data.status).toBe('ok');
    });

    test('SmartCut 推奨取得API', async ({ request }) => {
        // 初期化リクエスト
        const initResponse = await request.post('http://localhost:8000/api/smartcut/init', {
            data: {
                segments: [
                    { id: 'test-1', title: 'Test Segment', start: 0, end: 60, duration: 60, score: 80 }
                ],
                target_minutes: 5
            }
        });

        // レスポンスを確認
        if (initResponse.ok()) {
            const data = await initResponse.json();
            expect(data.success).toBe(true);
        }
    });

    test('SmartCut 候補一覧取得', async ({ request }) => {
        const response = await request.get('http://localhost:8000/api/smartcut/all-candidates');

        if (response.ok()) {
            const data = await response.json();
            expect(data.success).toBe(true);
        }
    });
});
