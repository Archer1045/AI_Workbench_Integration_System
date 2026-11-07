// NEXT-DRAW 14–18 真实页面验收：不提交任何生成任务。
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const DRAW_STATE_KEY = 'rider-studio:draw-state-v2';

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
  await page.waitForTimeout(700);

  let cards = page.locator('.group-card');
  const initialCardCount = await cards.count();
  const firstCard = cards.first();
  const initiallyExpanded = await firstCard.locator('textarea').count();
  await firstCard.getByRole('button', { name: '展开' }).click();
  await page.waitForTimeout(300);
  const textarea = firstCard.locator('textarea').first();
  const originalPrompt = await textarea.inputValue();
  await textarea.fill(`${originalPrompt}, undo-test`);
  await page.waitForTimeout(700);
  await page.getByRole('button', { name: '撤销提示词修改' }).click();
  await page.waitForTimeout(300);
  const undonePrompt = await textarea.inputValue();

  await firstCard.getByLabel('停用第 1 组').click();
  await page.waitForTimeout(300);
  const disabledVisible = await firstCard.getByText('未启用', { exact: true }).count();
  const disabledState = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw).groups?.[0]?.enabled : null;
  }, DRAW_STATE_KEY);
  await firstCard.getByLabel('启用第 1 组').click();

  await firstCard.getByRole('button', { name: '复制第 1 组' }).click();
  await page.waitForTimeout(300);
  cards = page.locator('.group-card');
  const duplicatedCardCount = await cards.count();

  await page.getByRole('button', { name: '提示词大纲' }).click();
  const outline = page.locator('.draw-outline-drawer').last();
  await outline.waitFor({ state: 'visible', timeout: 15000 });
  const outlineVisible = await outline.getByText('提示词大纲', { exact: true }).count();
  await page.keyboard.press('Escape');
  await page.waitForTimeout(250);

  await page.getByRole('button', { name: '生成设置' }).click();
  const settings = page.locator('.draw-settings-drawer').last();
  await settings.waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(500);
  const settingsVisible = await settings.getByText('基础参数', { exact: true }).count();
  const stickyVisible = await page.locator('.draw-sticky-actions').isVisible();
  const shot = path.join(outDir, 'ui_next_draw_batch.png');
  await page.screenshot({ path: shot, fullPage: true });
  shots.push(shot);

  const report = {
    url: BASE,
    groups: {
      initialCardCount,
      initiallyExpanded: initiallyExpanded > 0,
      undoRestored: undonePrompt === originalPrompt,
      disabledVisible: disabledVisible > 0,
      disabledState,
      duplicatedCardCount,
    },
    panels: {
      outlineVisible: outlineVisible > 0,
      settingsVisible: settingsVisible > 0,
      stickyVisible,
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'next_draw_ui_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    initialCardCount !== 1 ||
    initiallyExpanded > 0 ||
    !report.groups.undoRestored ||
    disabledVisible === 0 ||
    disabledState !== false ||
    duplicatedCardCount !== 2 ||
    outlineVisible === 0 ||
    settingsVisible === 0 ||
    !stickyVisible ||
    generationRequests > 0 ||
    httpErrors.length > 0 ||
    problems.length > 0;
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('next draw UI smoke failed:', err);
  process.exit(1);
});
