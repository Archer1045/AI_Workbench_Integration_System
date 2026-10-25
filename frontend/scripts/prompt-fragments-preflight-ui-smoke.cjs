// DRAW-OPT-20/23 页面验收：片段搜索/收藏/插入与生成前信息摘要。
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
      problems.push(`console: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
  page.on('response', (response) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
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
      await page.screenshot({ path: file, fullPage: false });
    }
    shots.push(file);
  };

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.evaluate(() =>
    localStorage.removeItem('rider-studio:draw-prompt-fragment-favorites-v1'),
  );
  await page.evaluate(() =>
    localStorage.removeItem('rider-studio:draw-prompt-history-v1'),
  );
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1800);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(700);

  const card = page.locator('.group-card').first();
  if (await card.getByText('展开', { exact: true }).isVisible().catch(() => false)) {
    await card.getByText('展开', { exact: true }).click();
  }
  await card.getByText('结构化', { exact: true }).click();
  await page.waitForTimeout(300);

  await page.getByRole('button', { name: '提示词片段' }).click();
  const fragmentDrawer = page.locator('.draw-fragment-drawer');
  await fragmentDrawer.waitFor({ state: 'visible', timeout: 15000 });
  await fragmentDrawer.getByLabel('搜索提示词片段').fill('电影');
  await fragmentDrawer.getByText('柔和电影光', { exact: true }).waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await fragmentDrawer
    .getByRole('button', { name: '收藏片段', exact: true })
    .click();
  await fragmentDrawer
    .getByRole('button', { name: '插入片段 柔和电影光' })
    .click();
  await page
    .getByText('已插入「柔和电影光」', { exact: true })
    .waitFor({ state: 'visible', timeout: 10000 });
  await fragmentDrawer.getByLabel('搜索提示词片段').fill('手部修正');
  await fragmentDrawer.getByText('手部修正', { exact: true }).waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await fragmentDrawer
    .getByRole('button', { name: '插入片段 手部修正' })
    .click();
  await page
    .getByText('已插入「手部修正」到负向提示词', { exact: true })
    .waitFor({ state: 'visible', timeout: 10000 });
  await shoot('prompt_fragments', fragmentDrawer);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
  const advancedTrigger = card.getByText('高级结构化编辑', { exact: true });
  if (await advancedTrigger.isVisible().catch(() => false)) {
    await card.locator('.structured-editor-collapse .ant-collapse-header').click();
    await page.waitForTimeout(300);
  }
  await card.getByLabel('角色负向').fill('bad anatomy');
  const negativeSection = card
    .locator('.ant-collapse-item')
    .filter({ hasText: '结构化负向提示词' })
    .first();
  await negativeSection
    .getByText('结构化负向提示词', { exact: true })
    .click();
  await page.waitForTimeout(300);
  await negativeSection
    .getByRole('textbox', { name: '场景', exact: true })
    .fill('extra people');
  await page.waitForTimeout(500);
  await page.waitForTimeout(1800);

  await page.getByRole('button', { name: '版本历史' }).click();
  const historyDrawer = page.locator('.draw-prompt-history-drawer');
  await historyDrawer.waitFor({ state: 'visible', timeout: 15000 });
  const historyItems = await historyDrawer.locator('.draw-history-item').count();
  await shoot('prompt_history', historyDrawer);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(350);

  const stored = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, DRAW_STATE_KEY);
  const document = stored?.groups?.[0]?.prompt_document;

  await page.getByRole('button', { name: '生成前摘要' }).click();
  const preflight = page.locator('.draw-preflight-drawer');
  await preflight.waitFor({ state: 'visible', timeout: 15000 });
  const preflightText = await preflight.innerText();
  await shoot('generation_preflight', preflight);

  const report = {
    url: BASE,
    fragment: {
      lightingTags: document?.global?.lighting?.tags || [],
      negativeAnatomyTags: document?.negative?.anatomy?.tags || [],
      characterNegativeTags: document?.characters?.[0]?.negative?.tags || [],
      sceneNegativeTags: document?.negative?.scene?.tags || [],
      favoriteStored: Boolean(
        await page.evaluate(() =>
          localStorage.getItem(
            'rider-studio:draw-prompt-fragment-favorites-v1',
          ),
        ),
      ),
    },
    preflight: {
      hasReadyGroups: preflightText.includes('可提交组'),
      hasRequestedCount: preflightText.includes('计划张数'),
      hasAnatomyLayer: preflightText.includes('anatomy: 4'),
      hasSceneLayer: preflightText.includes('scene: 1'),
      hasCharacterLayer: preflightText.includes('girlA:角色负向: 1'),
      hasModel: preflightText.includes('chosenIrisesMix'),
    },
    history: {
      versions: historyItems,
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'prompt_fragments_preflight_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    !report.fragment.lightingTags.includes('cinematic lighting') ||
    !report.fragment.negativeAnatomyTags.includes('bad hands') ||
    !report.fragment.characterNegativeTags.includes('bad anatomy') ||
    !report.fragment.sceneNegativeTags.includes('extra people') ||
    !report.fragment.favoriteStored ||
    report.history.versions < 1 ||
    !Object.values(report.preflight).every(Boolean);
  if (failed) process.exitCode = 1;
})().catch((error) => {
  console.error('prompt fragments/preflight UI smoke failed:', error);
  process.exit(1);
});
