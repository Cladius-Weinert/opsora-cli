// opsora-gmail.js — Headless Gmail checker via Playwright
// Run: node C:\tools\pw\opsora-gmail.js
const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({
        headless: true,
        args: ['--no-sandbox']
    });

    const context = await browser.newContext({
        userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    });
    const page = await context.newPage();

    try {
        console.log('📧 Navigating to Gmail...');
        await page.goto('https://mail.google.com', {
            waitUntil: 'networkidle',
            timeout: 30000
        });

        const url = page.url();
        const title = await page.title();
        console.log(`URL: ${url}`);
        console.log(`Title: ${title}`);

        // Check if logged in
        if (url.includes('accounts.google.com')) {
            console.log('STATUS: NOT_LOGGED_IN');
            console.log('LOGIN_PAGE: Yes - need to login first');
        } else if (url.includes('mail.google.com')) {
            console.log('STATUS: LOGGED_IN');

            // Get inbox content
            const inboxText = await page.evaluate(() => {
                const body = document.body;
                return body ? body.innerText.substring(0, 3000) : '';
            });

            console.log('---INBOX CONTENT---');
            console.log(inboxText);

            // Try to get unread count
            const unreadCount = await page.evaluate(() => {
                // Look for common Gmail unread indicators
                const unreadEls = document.querySelectorAll('[aria-label*="unread"]');
                for (const el of unreadEls) {
                    const match = el.textContent.match(/(\d+)\s*unread/);
                    if (match) return match[1];
                }
                return 'unknown';
            });
            console.log(`UNREAD_COUNT: ${unreadCount}`);
        } else {
            console.log(`STATUS: REDIRECTED to ${url}`);
        }
    } catch (err) {
        console.log(`ERROR: ${err.message}`);
        // Still try to get page state
        try {
            const url = page.url();
            const title = await page.title();
            console.log(`Fallback - URL: ${url}, Title: ${title}`);
        } catch {}
    } finally {
        await browser.close();
    }
})();
