// DRAW-OPT-05 真实页面验收：默精简插入、完整长句可选、人数约束保留。
// 用法（在 studio/frontend 下）：node scripts/pose-prompt-layering-ui-smoke.cjs <证据输出目录>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const DRAW_STATE_KEY = 'rider-studio:draw-state-v2';
const BOILERPLATE = 'single continuous scene with anime rendering';

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const problems = [];
  const httpErrors = [];
  const shots = [];
  let generationRequests = 0;

  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('Failed to load resource')) {
      problems.push(`console: ${msg.text()} @ ${msg.location().url || 'unknown'}`);
    }
  });
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
  page.on('response', (res) => {
    if (res.status() >= 400) httpErrors.push(`${res.status()} ${res.url()}`);
  });
  page.on('request', (req) => {
    if (req.url().includes('/api/draw')) generationRequests += 1;
  });

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(800);

  await page.getByRole('button', { name: '体位预设' }).click();
  const modal = page.locator('.ant-modal').filter({ hasText: '体位预设提示词' }).last();
  await modal.waitFor({ state: 'visible', timeout: 15000 });
  const verifiedCountText =
    (await modal.getByText(/^已验收 \d+$/).textContent()) || '';
  const needsReworkCountText =
    (await modal.getByText(/^需返工 \d+$/).textContent()) || '';
  await modal.getByPlaceholder('搜索体位/标签').fill('两女一男并排');
  await page.waitForTimeout(350);
  const reworkStatusVisible = await modal.getByText('需返工', { exact: true }).count();
  await modal.getByPlaceholder('搜索体位/标签').fill('三人三角构图');
  await page.waitForTimeout(500);
  await modal.getByText('三人三角构图', { exact: true }).waitFor({
    state: 'visible',
    timeout: 15000,
  });

  const row = modal
    .locator('.ant-table-tbody tr')
    .filter({ hasText: '三人三角构图' })
    .first();
  const coreTagText =
    (await row.locator('.ant-tag').filter({ hasText: '精简' }).first().textContent()) || '';
  const fullTagText =
    (await row.locator('.ant-tag').filter({ hasText: '完整' }).first().textContent()) || '';
  const defaultCoreSelected = await modal
    .locator('.ant-segmented-item-selected')
    .getByText('精简插入', { exact: true })
    .count();
  const verifiedStatusVisible = await row.getByText('已验收', { exact: true }).count();
  const shot = path.join(outDir, 'ui_pose_prompt_layering.png');
  await modal.screenshot({ path: shot });
  shots.push(shot);

  await modal.getByRole('button', { name: /插入精简版/ }).click();
  await page.waitForTimeout(600);
  const coreMessage = await page
    .getByText(/已把「三人三角构图」精简版写入当前组互动块/)
    .count();
  const corePrompt = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw).groups?.[0]?.prompt || '' : '';
  }, DRAW_STATE_KEY);

  await modal.getByText('完整长句', { exact: true }).click();
  await page.waitForTimeout(250);
  await modal.getByRole('button', { name: /插入完整版/ }).click();
  await page.waitForTimeout(600);
  const fullMessage = await page
    .getByText(/已把「三人三角构图」完整版写入当前组互动块/)
    .count();
  const fullPrompt = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw).groups?.[0]?.prompt || '' : '';
  }, DRAW_STATE_KEY);

  const coreLength = Number(coreTagText.match(/(\d+) 字符/)?.[1] || 0);
  const fullLength = Number(fullTagText.match(/(\d+) 字符/)?.[1] || 0);
  const report = {
    url: BASE,
    catalog: {
      verifiedCountText,
      needsReworkCountText,
      reworkStatusVisible: reworkStatusVisible > 0,
      verifiedStatusVisible: verifiedStatusVisible > 0,
      coreTagText,
      fullTagText,
      coreLength,
      fullLength,
      defaultCoreSelected: defaultCoreSelected === 1,
    },
    insertion: {
      coreMessage: coreMessage === 1,
      fullMessage: fullMessage === 1,
      corePromptLength: corePrompt.length,
      fullPromptLength: fullPrompt.length,
      coreContainsCount: corePrompt.includes('exactly three people, three separate bodies'),
      coreContainsCorePose: corePrompt.includes('triangular formation'),
      coreContainsBoilerplate: corePrompt.includes(BOILERPLATE),
      fullContainsBoilerplate: fullPrompt.includes(BOILERPLATE),
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'pose_prompt_layering_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    !report.catalog.defaultCoreSelected ||
    !report.catalog.reworkStatusVisible ||
    !report.catalog.verifiedStatusVisible ||
    coreLength <= 0 ||
    fullLength <= coreLength ||
    coreMessage !== 1 ||
    fullMessage !== 1 ||
    !report.insertion.coreContainsCount ||
    !report.insertion.coreContainsCorePose ||
    report.insertion.coreContainsBoilerplate ||
    !report.insertion.fullContainsBoilerplate;
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('pose prompt layering UI smoke failed:', err);
  process.exit(1);
});
