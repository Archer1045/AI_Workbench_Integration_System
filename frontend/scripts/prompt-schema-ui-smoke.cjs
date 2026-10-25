// NEXT-DRAW-02 页面验收：分类子字段、道具归属和提示词大纲。
// 用法（在 studio/frontend 下）：node scripts/prompt-schema-ui-smoke.cjs <证据输出目录>
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
      await page.screenshot({ path: file, fullPage: true });
    }
    shots.push(file);
  };

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1800);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(700);

  const card = page.locator('.group-card').first();
  const expandButton = card.getByText('展开', { exact: true });
  if (await expandButton.isVisible().catch(() => false)) {
    await expandButton.click();
    await page.waitForTimeout(300);
  }
  await card.getByText('结构化', { exact: true }).click();
  await page.waitForTimeout(300);
  await card.locator('.structured-editor-collapse .ant-collapse-header').click();
  await page.waitForTimeout(300);
  await card.getByText('全局提示词', { exact: true }).click();
  await page.waitForTimeout(300);

  const fields = {
    场景时间: 'night',
    场景天气: 'rain',
    镜头景别: 'full body',
    镜头角度: 'from below',
    光照色调: 'cool',
    服装穿着状态: 'wet',
    服装鞋履: 'black high heels',
    表情视线: 'looking at viewer',
    表情面部细节: 'light blush',
    角色道具: 'book',
    场景道具: 'chair',
  };
  for (const [label, value] of Object.entries(fields)) {
    await card.getByLabel(label).fill(value);
  }
  await card.getByLabel('表情强度').fill('0.8');
  await page.waitForTimeout(900);

  const stored = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, DRAW_STATE_KEY);
  const document = stored?.groups?.[0]?.prompt_document;
  const character = document?.characters?.[0];
  const schema = {
    scene: document?.global?.scene,
    camera: document?.global?.camera,
    lighting: document?.global?.lighting,
    clothing: character?.clothing,
    expression: character?.expression,
    globalProps: document?.props?.global,
    characterProps: document?.props?.characters?.[character?.role_id],
  };
  await card.getByLabel('场景时间').scrollIntoViewIfNeeded();
  await page.waitForTimeout(200);
  await shoot('prompt_schema_editor');

  await page.getByRole('button', { name: '预设选择器' }).click();
  const presetDrawer = page.locator('.preset-center-drawer');
  await presetDrawer.waitFor({ state: 'visible', timeout: 15000 });
  await presetDrawer.getByRole('button', { name: /^服装/ }).click();
  await presetDrawer
    .getByPlaceholder('搜索名称、ID、标签或分类')
    .fill('黑色细高跟鞋');
  await page.waitForTimeout(350);
  await presetDrawer.getByText('黑色细高跟鞋', { exact: true }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await presetDrawer
    .getByRole('button', { name: '应用到当前提示词' })
    .click();
  await page
    .getByText('已把「黑色细高跟鞋」写入目标角色鞋履块', { exact: true })
    .waitFor({ state: 'visible', timeout: 10000 });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(500);
  const shoeState = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    const saved = raw ? JSON.parse(raw) : null;
    return saved?.groups?.[0]?.prompt_document?.characters?.[0]?.clothing
      ?.footwear;
  }, DRAW_STATE_KEY);

  await page.getByRole('button', { name: '提示词大纲' }).click();
  const outline = page.locator('.draw-outline-drawer');
  await outline.waitFor({ state: 'visible', timeout: 15000 });
  await outline.getByText('角色道具', { exact: true }).waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await outline.getByText('场景道具', { exact: true }).waitFor({
    state: 'visible',
    timeout: 10000,
  });
  const outlineChecks = {};
  for (const value of [
    'night',
    'rain',
    'full body',
    'from below',
    'cool',
    'wet',
    'black high heels',
    'looking at viewer',
    'light blush',
    'book',
    'chair',
  ]) {
    outlineChecks[value] = (await outline.getByText(value, { exact: true }).count()) > 0;
  }
  await shoot('prompt_schema_outline', outline);

  const report = {
    url: BASE,
    schema,
    shoePreset: {
      tags: shoeState?.tags || [],
      presetRefs: shoeState?.preset_refs || [],
    },
    outlineChecks,
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'prompt_schema_ui_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    schema.scene?.time?.[0] !== 'night' ||
    schema.scene?.weather?.[0] !== 'rain' ||
    schema.camera?.framing?.[0] !== 'full body' ||
    schema.camera?.angle?.[0] !== 'from below' ||
    schema.lighting?.palette?.[0] !== 'cool' ||
    schema.clothing?.clothing_state?.[0] !== 'wet' ||
    schema.clothing?.footwear?.tags?.[0] !== 'black high heels' ||
    !shoeState?.tags?.includes('black stiletto heels') ||
    !shoeState?.preset_refs?.some(
      (item) => item.preset_id === 'shoe_black_stiletto_heels',
    ) ||
    schema.expression?.gaze?.[0] !== 'looking at viewer' ||
    schema.expression?.face_details?.[0] !== 'light blush' ||
    schema.expression?.intensity !== 0.8 ||
    schema.globalProps?.tags?.[0] !== 'chair' ||
    schema.characterProps?.tags?.[0] !== 'book' ||
    !Object.values(outlineChecks).every(Boolean);
  if (failed) process.exitCode = 1;
})().catch((error) => {
  console.error('prompt schema UI smoke failed:', error);
  process.exit(1);
});
