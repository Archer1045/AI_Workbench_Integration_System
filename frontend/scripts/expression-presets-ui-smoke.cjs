// DRAW-OPT-09 真实页面验收：表情目录加载、搜索、结构化块写入和 legacy 文本追加。
// 用法（在 studio/frontend 下）：node scripts/expression-presets-ui-smoke.cjs <证据输出目录>
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

  const shoot = async (name, locator) => {
    const file = path.join(outDir, `ui_${name}.png`);
    if (locator) {
      await locator.screenshot({ path: file });
    } else {
      await page.screenshot({ path: file, fullPage: true });
    }
    shots.push(file);
  };

  const openExpressionModal = async () => {
    await page.getByRole('button', { name: '表情预设' }).click({ timeout: 15000 });
    const modal = page.locator('.expression-presets-modal').last();
    await modal.waitFor({ state: 'visible', timeout: 15000 });
    await modal.locator('.expression-preset-card').first().waitFor({
      state: 'visible',
      timeout: 15000,
    });
    return modal;
  };

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(1000);

  const groupCard = page.locator('.group-card').first();
  await groupCard.getByText('结构化', { exact: true }).click();
  await page.waitForTimeout(300);
  let modal = await openExpressionModal();
  const totalCards = await modal.locator('.expression-preset-card').count();
  await shoot('expression_library', modal);

  await modal.getByLabel('搜索表情预设').fill('害羞');
  await page.waitForTimeout(300);
  const filteredCards = await modal.locator('.expression-preset-card').count();
  const shyVisible = await modal.getByText('害羞脸红', { exact: true }).count();
  await modal.getByRole('button', { name: '插入 害羞脸红' }).click();
  await page.waitForTimeout(500);
  const structuredMessage = await page
    .getByText('已把「害羞脸红」写入目标角色表情块', { exact: true })
    .count();
  await page.waitForTimeout(300);
  const structuredState = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, DRAW_STATE_KEY);
  const structuredExpression =
    structuredState?.groups?.[0]?.prompt_document?.characters?.[0]?.expression;
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  const expressionField = groupCard
    .locator('.setting-field')
    .filter({ has: page.getByText('表情', { exact: true }) })
    .first();
  if (await expressionField.count()) {
    await expressionField.scrollIntoViewIfNeeded();
    await page.waitForTimeout(150);
    await shoot('expression_structured_insert', expressionField);
  } else {
    problems.push('没有找到结构化表情块');
  }
  await groupCard.getByText('原始文本', { exact: true }).click();
  await page.waitForTimeout(300);
  modal = await openExpressionModal();
  await modal.getByLabel('搜索表情预设').fill('得意');
  await page.waitForTimeout(300);
  await modal.getByRole('button', { name: '插入 得意' }).click();
  await page.waitForTimeout(400);
  const legacyMessage = await page
    .getByText('已把「得意」写入目标角色表情块', { exact: true })
    .count();
  await page.waitForTimeout(300);
  const legacyState = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, DRAW_STATE_KEY);
  const legacyPrompt = legacyState?.groups?.[0]?.prompt || '';

  const report = {
    url: BASE,
    catalog: {
      totalCards,
      filteredCards,
      shyVisible: shyVisible === 1,
    },
    structured: {
      successMessage: structuredMessage === 1,
      tags: structuredExpression?.tags || [],
      presetRefs: structuredExpression?.preset_refs || [],
      snapshot: structuredExpression?.preset_snapshot || null,
      source: structuredExpression?.source || null,
    },
    legacy: {
      successMessage: legacyMessage === 1,
      prompt: legacyPrompt,
      containsSmug: legacyPrompt.includes('smug smile'),
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'expression_presets_ui_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    totalCards !== 24 ||
    filteredCards !== 1 ||
    structuredMessage !== 1 ||
    legacyMessage !== 1 ||
    !report.structured.tags.includes('shy expression') ||
    !report.structured.presetRefs.some(
      (item) => item.preset_id === 'expression_shy_blush',
    ) ||
    !report.legacy.containsSmug;
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('expression preset UI smoke failed:', err);
  process.exit(1);
});
