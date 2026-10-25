// DRAW-OPT-01 真实页面验收：新组默认原文、结构化编辑器默认收起、旧结构化数据刷新可恢复。
// 用法（在 studio/frontend 下）：node scripts/structured-editor-ui-smoke.cjs <证据输出目录>
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

  const selectedMode = async (card) =>
    (await card.locator('.ant-segmented-item-selected').first().textContent())?.trim() || '';

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(800);

  let cards = page.locator('.group-card');
  const initialGroupCount = await cards.count();
  const initialMode = await selectedMode(cards.first());

  await page.getByRole('button', { name: '添加一组' }).click();
  await page.waitForTimeout(400);
  cards = page.locator('.group-card');
  const addedGroupCount = await cards.count();
  const addedCard = cards.last();
  const newGroupMode = await selectedMode(addedCard);
  const addedBorderColor = await addedCard.evaluate(
    (element) => getComputedStyle(element).borderColor,
  );
  const addedIsActive = addedBorderColor.includes('22, 119, 255');

  await addedCard.getByText('结构化', { exact: true }).click();
  await page.waitForTimeout(500);
  const structuredMode = await selectedMode(addedCard);
  const trigger = addedCard.getByText('高级结构化编辑', { exact: true });
  const triggerVisible = await trigger.isVisible();
  const displayNameField = addedCard
    .locator('.setting-field')
    .filter({ has: page.getByText('显示名称', { exact: true }) })
    .first();
  const advancedInitiallyVisible = await displayNameField.isVisible().catch(() => false);
  await shoot('structured_editor_collapsed', addedCard);

  await addedCard.locator('.structured-editor-collapse .ant-collapse-header').click();
  await page.waitForTimeout(350);
  const advancedExpandedVisible = await displayNameField.isVisible();
  await displayNameField.locator('input').fill('收敛测试角色');
  await page.waitForTimeout(500);
  const storedBeforeReload = await page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, DRAW_STATE_KEY);
  await shoot('structured_editor_expanded', addedCard);
  const expandedViewportFile = path.join(
    outDir,
    'ui_structured_editor_expanded_viewport.png',
  );
  await page.screenshot({ path: expandedViewportFile, fullPage: false });
  shots.push(expandedViewportFile);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
  await page.waitForTimeout(800);
  cards = page.locator('.group-card');
  const restoredCard = cards.last();
  const restoredMode = await selectedMode(restoredCard);
  const restoredAdvancedInitiallyVisible = await restoredCard
    .locator('.setting-field')
    .filter({ has: page.getByText('显示名称', { exact: true }) })
    .first()
    .isVisible()
    .catch(() => false);
  await restoredCard.locator('.structured-editor-collapse .ant-collapse-header').click();
  await page.waitForTimeout(350);
  const restoredName = await restoredCard
    .locator('.setting-field')
    .filter({ has: page.getByText('显示名称', { exact: true }) })
    .first()
    .locator('input')
    .inputValue();

  const storedGroups = storedBeforeReload?.groups || [];
  const report = {
    url: BASE,
    groupCreation: {
      initialGroupCount,
      initialMode,
      addedGroupCount,
      newGroupMode,
      addedIsActive,
      addedBorderColor,
    },
    structuredEditor: {
      structuredMode,
      triggerVisible,
      advancedInitiallyVisible,
      advancedExpandedVisible,
      restoredMode,
      restoredAdvancedInitiallyVisible,
      restoredName,
      storedMode: storedGroups[1]?.mode || '',
      storedDisplayName:
        storedGroups[1]?.prompt_document?.characters?.[0]?.display_name || '',
    },
    generationRequests,
    shots,
    httpErrors,
    problems,
  };
  fs.writeFileSync(
    path.join(outDir, 'structured_editor_ui_report.json'),
    JSON.stringify(report, null, 2),
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();

  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    generationRequests > 0 ||
    initialGroupCount !== 1 ||
    initialMode !== '原始文本' ||
    addedGroupCount !== 2 ||
    newGroupMode !== '原始文本' ||
    !addedIsActive ||
    structuredMode !== '结构化' ||
    !triggerVisible ||
    advancedInitiallyVisible ||
    !advancedExpandedVisible ||
    restoredMode !== '结构化' ||
    restoredAdvancedInitiallyVisible ||
    restoredName !== '收敛测试角色' ||
    report.structuredEditor.storedMode !== 'structured' ||
    report.structuredEditor.storedDisplayName !== '收敛测试角色';
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('structured editor UI smoke failed:', err);
  process.exit(1);
});
