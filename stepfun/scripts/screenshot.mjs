import { chromium } from 'playwright';
import fs from 'node:fs';

const OUT = '/mnt/d/oceanbase/stepfun_shots';
fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({
  args: ['--enable-unsafe-swiftshader', '--no-sandbox', '--disable-dev-shm-usage'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1180 }, deviceScaleFactor: 1 });

const logs = [];
page.on('console', (msg) => logs.push(`[console.${msg.type()}] ${msg.text()}`));
page.on('pageerror', (err) => logs.push(`[pageerror] ${err.message}`));
page.on('requestfailed', (req) => logs.push(`[requestfailed] ${req.url()} ${req.failure()?.errorText}`));

const step = async (name) => {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  console.log(`[shot] ${name}`);
};

await page.goto('http://127.0.0.1:8787/', { waitUntil: 'load', timeout: 60000 });
await page.waitForTimeout(1500);
await step('01-initial');

// 1. 加载模型（下载 23 MB ONNX 权重，给足时间）
await page.click('button:has-text("加载模型")');
await page.waitForFunction(
  () => {
    const nodes = [...document.querySelectorAll('p.hint')];
    return nodes.some((node) => node.textContent.includes('加载耗时') && !node.textContent.includes('—'));
  },
  null,
  { timeout: 300000 },
);
console.log('[ok] model loaded');
await step('02-model-loaded');

// 2. 向量化并入库
await page.click('button:has-text("向量化并写入 seekdb")');
await page.waitForTimeout(4000);
await step('03-indexed');

// 3. 检索
const question = await page.inputValue('input[placeholder^="输入问题"]');
await page.fill('input[placeholder^="输入问题"]', '浏览器端 embedding 和 seekdb 是怎么配合完成混合检索的？');
await page.click('button:has-text("检索")');
await page.waitForTimeout(4000);
await step('04-search');
console.log('[state] default question was:', question);

// 4. 量化对比（INT8 / FP16 / FP32 依次加载，耗时较长，失败不阻塞截图）
try {
  await page.click('button:has-text("量化对比")');
  await page.waitForTimeout(60000);
  await step('05-benchmark');
} catch (error) {
  logs.push(`[bench] ${error.message}`);
}

fs.writeFileSync(`${OUT}/console.log`, logs.join('\n'), 'utf8');
console.log('[done] logs:', logs.length);
await browser.close();