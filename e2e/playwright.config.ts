import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright設定ファイル
 * 
 * video-automation プロジェクトのE2Eテスト設定
 */
export default defineConfig({
    testDir: './tests',
    fullyParallel: true,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    workers: process.env.CI ? 1 : undefined,
    reporter: 'html',

    use: {
        // フロントエンドのベースURL
        baseURL: 'http://localhost:3000',

        // スクリーンショットとトレース
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
    },

    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
    ],

    // 開発サーバーの起動設定
    webServer: [
        {
            command: 'cd ../frontend && npm run dev',
            url: 'http://localhost:3000',
            reuseExistingServer: !process.env.CI,
            timeout: 120 * 1000,
        },
        {
            command: 'cd ../backend && python -m uvicorn main:app --reload --port 8000',
            url: 'http://localhost:8000/api/status',
            reuseExistingServer: !process.env.CI,
            timeout: 120 * 1000,
        },
    ],
});
