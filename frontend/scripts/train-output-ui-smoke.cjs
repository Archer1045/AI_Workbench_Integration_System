// DRAW-OPT-12 真实页面验收：训练产物分组/搜索/收藏/分页，以及对比最多 4 个与最近组合。
// 用法（在 studio/frontend 下）：node scripts/train-output-ui-smoke.cjs <证据输出目录>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const OUTPUT_FAVORITES_KEY = 'rider-studio:train-output-favorites-v1';
const RECENT_COMPARE_COMBOS_KEY = 'rider-studio:train-recent-compares-v1';
const TARGET_COMPARE_COUNT = 6;

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const problems = [];
  const httpErrors = [];
  const existingWarnings = [];
  const shots = [];
  let compareRequestCount = 0;

  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (text.includes('[rc-collapse]')) {
      existingWarnings.push(text);
    } else if (!text.includes('Failed to load resource')) {
      problems.push(`console: ${text}`);
    }
  });
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
  page.on('response', (res) => {
    if (res.status() >= 400) httpErrors.push(`${res.status()} ${res.url()}`);
  });
  page.on('requestfailed', (req) => {
    problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText}`);
  });
  page.on('request', (req) => {
    if (req.url().includes('/api/train/compare-generate')) compareRequestCount += 1;
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

  const openTrain = async () => {
    await page.getByRole('tab', { name: 'LoRA 训练' }).first().click({ timeout: 15000 });
    await page.locator('.train-box').filter({ hasText: '训练产物' }).first().waitFor({
      state: 'visible',
      timeout: 30000,
    });
    await page.waitForTimeout(1200);
  };

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2500);
  await page.evaluate(
    ({ favoritesKey, recentKey }) => {
      localStorage.removeItem(favoritesKey);
      localStorage.removeItem(recentKey);
    },
    { favoritesKey: OUTPUT_FAVORITES_KEY, recentKey: RECENT_COMPARE_COMBOS_KEY },
  );
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await openTrain();

  const outputBox = page.locator('.train-box').filter({ hasText: '训练产物' }).first();
  const summary = outputBox.locator('.train-output-summary').first();
  await summary.waitFor({ state: 'visible', timeout: 20000 });
  const initialSummary = (await summary.textContent()) || '';
  const initialFamilyCount = Number(initialSummary.match(/(\d+) 个名称族/)?.[1] || 0);
  const initialFileCount = Number(initialSummary.match(/(\d+) 个匹配文件/)?.[1] || 0);
  const paginationCount = await outputBox.locator('.train-output-pagination .ant-pagination-item').count();

  const outputSearch = outputBox.getByLabel('搜索训练产物');
  await outputSearch.fill('my_Sorana');
  await page.waitForTimeout(350);
  const filteredSummary = (await summary.textContent()) || '';
  const filteredFamily = outputBox.locator('.ant-collapse-item').first();
  await filteredFamily.locator('.ant-collapse-header').click();
  await page.waitForTimeout(250);
  const filteredRows = await filteredFamily.locator('.train-output-row').count();
  const favoriteButton = filteredFamily.locator('.train-output-favorite').first();
  const favoriteLabel = (await favoriteButton.getAttribute('aria-label')) || '';
  const favoriteName = favoriteLabel.replace(/^收藏 /, '');
  if (!favoriteName) problems.push('没有找到可收藏的训练产物');
  await favoriteButton.click();
  await page.waitForTimeout(250);
  const storedFavorites = await page.evaluate((key) => localStorage.getItem(key), OUTPUT_FAVORITES_KEY);
  await shoot('train_outputs_search_group', outputBox);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await openTrain();
  const reloadedOutputBox = page.locator('.train-box').filter({ hasText: '训练产物' }).first();
  await reloadedOutputBox.getByLabel('搜索训练产物').fill('my_Sorana');
  await page.waitForTimeout(350);
  const reloadedFamily = reloadedOutputBox.locator('.ant-collapse-item').first();
  await reloadedFamily.locator('.ant-collapse-header').click();
  await page.waitForTimeout(250);
  const persistedFavorite = await reloadedFamily
    .getByLabel(`取消收藏 ${favoriteName}`)
    .count();

  await reloadedOutputBox.getByText('转换后', { exact: true }).click();
  await page.waitForTimeout(250);
  const comfyFamilies = reloadedOutputBox.locator('.ant-collapse-item');
  if (await comfyFamilies.count()) {
    await comfyFamilies.first().locator('.ant-collapse-header').click();
    await page.waitForTimeout(250);
  }
  const comfyRows = await reloadedOutputBox.locator('.train-output-row').count();
  const comfyBadRows = await reloadedOutputBox
    .locator('.train-output-row')
    .filter({ hasNotText: '可直接复制' })
    .count();

  await reloadedOutputBox.getByText('全部', { exact: true }).click();
  await reloadedOutputBox.getByLabel('搜索训练产物').fill('');
  await page.waitForTimeout(300);
  const pageTwo = reloadedOutputBox.locator('.train-output-pagination .ant-pagination-item-2');
  const hasPageTwo = (await pageTwo.count()) > 0;
  if (hasPageTwo) {
    await pageTwo.click();
    await page.waitForTimeout(250);
  }
  const activePageText = await reloadedOutputBox
    .locator('.train-output-pagination .ant-pagination-item-active')
    .textContent();
  await shoot('train_outputs_pagination', reloadedOutputBox);

  await reloadedOutputBox.getByRole('button', { name: '一键对比出图' }).click();
  const modal = page.locator('.ant-modal').filter({ hasText: '一键对比出图' }).last();
  await modal.waitFor({ state: 'visible', timeout: 15000 });
  await modal.getByLabel('搜索对比 LoRA').fill('my_');
  await page.waitForTimeout(350);
  const compareCheckboxes = modal.locator('[aria-label^="对比 "]');
  const availableCompareCount = await compareCheckboxes.count();
  if (availableCompareCount < TARGET_COMPARE_COUNT) {
    problems.push(
      `搜索后只有 ${availableCompareCount} 个对比项，无法验证至少 ${TARGET_COMPARE_COUNT} 个选择`,
    );
  }
  const selectedNames = [];
  for (
    let index = 0;
    index < Math.min(TARGET_COMPARE_COUNT, availableCompareCount);
    index += 1
  ) {
    const checkbox = compareCheckboxes.nth(index);
    const label = (await checkbox.getAttribute('aria-label')) || '';
    selectedNames.push(label.replace(/^对比 /, ''));
    await checkbox.check({ force: true });
    await page.waitForTimeout(120);
  }
  const compareCounter = await modal.getByText(
    new RegExp(`已选\\s*${TARGET_COMPARE_COUNT}`),
  ).count();
  const selectedCount = await modal.locator('.train-compare-selected .ant-tag').count();
  await shoot('train_compare_selector', modal);

  if (selectedNames.length === TARGET_COMPARE_COUNT) {
    await page.evaluate(
      ({ key, names }) => localStorage.setItem(key, JSON.stringify([names])),
      { key: RECENT_COMPARE_COMBOS_KEY, names: selectedNames },
    );
  }
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await openTrain();
  const finalOutputBox = page.locator('.train-box').filter({ hasText: '训练产物' }).first();
  await finalOutputBox.getByRole('button', { name: '一键对比出图' }).click();
  const finalModal = page.locator('.ant-modal').filter({ hasText: '一键对比出图' }).last();
  await finalModal.waitFor({ state: 'visible', timeout: 15000 });
  const recentButton = finalModal.getByRole('button', { name: /组合 1/ }).first();
  const recentVisible = await recentButton.count();
  if (recentVisible) {
    await recentButton.click();
    await page.waitForTimeout(250);
  }
  const loadedRecentCount = await finalModal.locator('.train-compare-selected .ant-tag').count();
  await shoot('train_recent_compare', finalModal);

  const report = {
    url: BASE,
    output: {
      initialSummary,
      initialFamilyCount,
      initialFileCount,
      paginationCount,
      filteredSummary,
      filteredRows,
      favoriteName,
      storedFavorites: storedFavorites ? JSON.parse(storedFavorites) : [],
      persistedFavorite: persistedFavorite === 1,
      comfyRows,
      comfyBadRows,
      hasPageTwo,
      activePageText,
    },
    compare: {
      availableCompareCount,
      compareCounter: compareCounter > 0,
      selectedNames,
      selectedCount,
      recentVisible: recentVisible === 1,
      loadedRecentCount,
      compareRequestCount,
    },
    shots,
    httpErrors,
    existingWarnings,
    problems,
  };
  fs.writeFileSync(path.join(outDir, 'train_output_ui_report.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
  const failed =
    problems.length > 0 ||
    httpErrors.length > 0 ||
    compareCounter === 0 ||
    selectedCount !== TARGET_COMPARE_COUNT ||
    loadedRecentCount !== TARGET_COMPARE_COUNT ||
    recentVisible !== 1 ||
    compareRequestCount !== 0;
  if (failed) process.exitCode = 1;
})().catch((err) => {
  console.error('train output UI smoke failed:', err);
  process.exit(1);
});
