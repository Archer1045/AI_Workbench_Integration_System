// DRAW-OPT-13 真实页面验收：统一预设入口、表情/水中合并、搜索、收藏和最近使用。
// 用法（在 studio/frontend 下）：node scripts/unified-preset-selector-smoke.cjs <证据输出目录>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';
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

  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !message.text().includes('Failed to load resource')
    ) {
      problems.push(
        `console: ${message.text()} @ ${message.location().url || 'unknown'}`,
      );
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400) {
      httpErrors.push(`${response.status()} ${response.url()}`);
    }
  });
  page.on('request', (request) => {
    if (
      request.method() === 'POST' &&
      request.url().includes('/api/draw')
    ) {
      generationRequests += 1;
    }
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

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2000);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(800);

  const separateExpressionButton = await page
    .getByRole('button', { name: '表情预设', exact: true })
    .count();
  const separatePoseButton = await page
    .getByRole('button', { name: '体位预设', exact: true })
    .count();
  const separateWaterButton = await page
    .getByRole('button', { name: '水中玩法', exact: true })
    .count();

  await page.getByRole('button', { name: '预设选择器' }).click();
  const drawer = page.locator('.preset-center-drawer');
  await drawer.waitFor({ state: 'visible', timeout: 15000 });
  await drawer.getByText('浏览预设', { exact: true }).waitFor({
    state: 'visible',
    timeout: 15000,
  });
  await drawer.locator('.preset-library-type-item').first().waitFor({
    state: 'visible',
    timeout: 15000,
  });
  await drawer.getByRole('button', { name: /^服装/ }).waitFor({
    state: 'visible',
    timeout: 15000,
  });

  const typeLabels = await drawer
    .locator('.preset-library-type-item span')
    .allTextContents();
  await drawer.getByRole('button', { name: /^表情/ }).click();
  await drawer.locator('.preset-library-card').first().waitFor({
    state: 'visible',
    timeout: 15000,
  });
  const expressionCards = await drawer.locator('.preset-library-card').count();
  await drawer
    .getByPlaceholder('搜索名称、ID、标签或分类')
    .fill('害羞');
  await page.waitForTimeout(350);
  const filteredExpressionCards = await drawer
    .locator('.preset-library-card')
    .count();
  await drawer.getByText('害羞脸红', { exact: true }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await shoot('unified_preset_expression', drawer);

  await drawer.getByRole('button', { name: '收藏预设' }).click();
  const favoriteActive = await drawer
    .getByRole('button', { name: '取消收藏预设' })
    .count();
  await drawer.getByRole('button', { name: '应用到当前提示词' }).click();
  await page
    .getByText('已把「害羞脸红」写入目标角色表情块', { exact: true })
    .waitFor({ state: 'visible', timeout: 10000 });
  await page.waitForTimeout(300);
  await drawer.getByRole('button', { name: '只看最近使用' }).click();
  const recentExpressionVisible = await drawer
    .getByText('害羞脸红', { exact: true })
    .count();
  await drawer.getByRole('button', { name: '只看收藏' }).click();
  const favoriteExpressionVisible = await drawer
    .getByText('害羞脸红', { exact: true })
    .count();

  await drawer.getByRole('button', { name: /^水中/ }).click();
  await drawer.locator('.preset-library-card').first().waitFor({
    state: 'visible',
    timeout: 15000,
  });
  const waterCards = await drawer.locator('.preset-library-card').count();
  await shoot('unified_preset_water', drawer);

  const report = {
    url: BASE,
    separateEntriesRemoved:
      separateExpressionButton === 0 &&
      separatePoseButton === 0 &&
      separateWaterButton === 0,
    typeLabels,
    expression: {
      cards: expressionCards,
      filteredCards: filteredExpressionCards,
      favoriteActive: favoriteActive === 1,
      recentVisible: recentExpressionVisible > 0,
      favoriteVisible: favoriteExpressionVisible > 0,
    },
    water: {
      cards: waterCards,
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'unified_preset_selector_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const requiredTypes = ['体位', '服装', '场景', '表情', '水中', '身体改造'];
  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    !report.separateEntriesRemoved ||
    expressionCards < 1 ||
    filteredExpressionCards !== 1 ||
    !report.expression.favoriteActive ||
    !report.expression.recentVisible ||
    !report.expression.favoriteVisible ||
    waterCards < 1 ||
    !requiredTypes.every((label) => typeLabels.includes(label));
  if (failed) process.exitCode = 1;
})().catch((error) => {
  console.error('unified preset selector smoke failed:', error);
  process.exit(1);
});
