// DRAW-OPT-08 真实页面验收：水中角色状态与场景修饰可独立组合，不触发出图。
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

  const readState = () =>
    page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    }, DRAW_STATE_KEY);

  const openWater = async () => {
    await page.getByRole('button', { name: '水中玩法' }).click();
    const modal = page.locator('.water-presets-modal').last();
    await modal.waitFor({ state: 'visible', timeout: 15000 });
    await modal.locator('.water-preset-card').first().waitFor({
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
  await page.waitForTimeout(800);

  let modal = await openWater();
  const totalCards = await modal.locator('.water-preset-card').count();
  await modal.getByLabel('搜索水中玩法').fill('半身');
  await page.waitForTimeout(300);
  await modal.getByRole('button', { name: '插入 半身浸水' }).click();
  await page.waitForTimeout(600);
  const roleMessage = await page
    .getByText('已把「半身浸水」写入目标角色状态块')
    .count();
  const legacyPrompt = (await readState())?.groups?.[0]?.prompt || '';
  const waterShot = path.join(outDir, 'ui_water_presets.png');
  await modal.screenshot({ path: waterShot });
  shots.push(waterShot);

  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  const groupCard = page.locator('.group-card').first();
  await groupCard.getByText('结构化', { exact: true }).click();
  await page.waitForTimeout(400);
  modal = await openWater();
  await modal.getByLabel('搜索水中玩法').fill('水面涟漪');
  await page.waitForTimeout(300);
  await modal.getByRole('button', { name: '插入 水面涟漪' }).click();
  await page.waitForTimeout(600);
  const sceneMessage = await page
    .getByText('已把「水面涟漪」写入场景块')
    .count();
  const structuredState = await readState();
  const sceneTags =
    structuredState?.groups?.[0]?.prompt_document?.global?.scene?.tags || [];

  const report = {
    url: BASE,
    catalog: {
      totalCards,
    },
    insertion: {
      roleMessage: roleMessage === 1,
      legacyPromptHasHalfSubmerged: legacyPrompt.includes('half-submerged body'),
      sceneMessage: sceneMessage === 1,
      sceneTags,
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'water_play_ui_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    totalCards !== 12 ||
    !report.insertion.roleMessage ||
    !report.insertion.legacyPromptHasHalfSubmerged ||
    !report.insertion.sceneMessage ||
    !sceneTags.includes('water surface ripples') ||
    generationRequests > 0 ||
    httpErrors.length > 0 ||
    problems.length > 0;
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('water play UI smoke failed:', err);
  process.exit(1);
});
