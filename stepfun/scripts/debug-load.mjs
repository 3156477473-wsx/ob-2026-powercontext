import { chromium } from 'playwright';

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1440, height: 1180 } });
const logs = [];
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text().slice(0, 300)}`));
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message.slice(0, 300)}`));
page.on('requestfailed', (r) => logs.push(`[reqfail] ${r.url().slice(0, 160)} ${r.failure()?.errorText}`));
page.on('response', (r) => {
  const url = r.url();
  if (/huggingface|hf-mirror|\.onnx|\.json/.test(url)) logs.push(`[resp ${r.status()}] ${url.slice(0, 160)}`);
});

await page.goto('http://127.0.0.1:8787/', { waitUntil: 'load' });
await page.waitForTimeout(1500);
console.log('[device] selects:', await page.$$eval('select', (els) => els.map((e) => e.value)));
console.log('[inputs]', await page.$$eval('input', (els) => els.map((e) => e.value).slice(0, 4)));

await page.click('button:has-text("加载模型")');
for (let i = 0; i < 6; i += 1) {
  await page.waitForTimeout(15000);
  const text = await page.$$eval('p.hint, .status, .error, header', (els) =>
    els.map((e) => e.textContent.trim()).filter(Boolean).join(' || '),
  );
  console.log(`[t=${(i + 1) * 15}s] ${text.slice(0, 400)}`);
}
await page.screenshot({ path: '/mnt/d/oceanbase/stepfun_shots/debug-load.png', fullPage: true });
console.log('== logs');
console.log(logs.slice(0, 40).join('\n'));
await browser.close();