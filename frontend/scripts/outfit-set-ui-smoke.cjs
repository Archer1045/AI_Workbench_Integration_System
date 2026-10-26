// Outfit Set live UI acceptance: built-in load, structured clothing apply,
// built-in copy creation and cleanup without submitting an image job.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';
const API = process.env.API_BASE_URL || 'http://127.0.0.1:8500/api';
const DRAW_STATE_KEY = 'rider-studio:draw-state-v2';

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const problems = [];
  const httpErrors = [];
  const requestFailures = [];
  const shots = [];
  let generationRequests = 0;
  let createdPresetId = '';

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
      (request.url().includes('/api/draw') ||
        request.url().includes('/candidates/ai'))
    ) {
      generationRequests += 1;
    }
  });
  page.on('requestfailed', (request) => {
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`,
    );
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

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1200);
    await page.evaluate((key) => localStorage.removeItem(key), DRAW_STATE_KEY);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1600);
    await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
    await page.waitForTimeout(600);

    const card = page.locator('.group-card').first();
    await card.waitFor({ state: 'visible' });
    const expandButton = card.getByText('展开', { exact: true });
    if (await expandButton.isVisible().catch(() => false)) {
      await expandButton.click();
      await page.waitForTimeout(250);
    }
    await card.getByText('结构化', { exact: true }).click();
    await page.waitForTimeout(300);

    await page.getByRole('button', { name: '服装套装', exact: true }).click();
    const drawer = page
      .locator('.ant-drawer.ant-drawer-open')
      .filter({ hasText: '套装库' });
    await drawer.waitFor({ state: 'visible' });
    await drawer.getByText('套装库', { exact: true }).waitFor();
    const outfitRows = drawer.locator('.outfit-set-list-item');
    await outfitRows.first().waitFor();
    const builtinCount = await outfitRows.count();
    if (builtinCount < 12) {
      throw new Error(`套装库仅显示 ${builtinCount} 个套装`);
    }
    await shoot('outfit-drawer', drawer);

    await drawer.getByRole('button', { name: '校验并应用', exact: true }).click();
    try {
      await drawer
        .getByRole('button', { name: '校验并应用', exact: true })
        .waitFor({ state: 'hidden', timeout: 10000 });
    } catch (error) {
      await shoot('outfit-apply-failed', drawer);
      const notices = await page
        .locator('.ant-message-notice-content')
        .allTextContents();
      throw new Error(
        `套装应用后抽屉未关闭；notices=${JSON.stringify(notices)} ` +
          `httpErrors=${JSON.stringify(httpErrors)} ` +
          `requestFailures=${JSON.stringify(requestFailures)}`,
      );
    }
    await page.waitForTimeout(700);

    const applied = await page.evaluate((key) => {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const state = JSON.parse(raw);
      const group = state.groups?.[0];
      const clothing = group?.prompt_document?.characters?.[0]?.clothing;
      return {
        mode: group?.mode,
        source: clothing?.source,
        outfitId: clothing?.preset_snapshot?.outfit_set?.preset_id,
        itemCount: clothing?.preset_snapshot?.outfit_items?.length || 0,
        tags: clothing?.tags || [],
      };
    }, DRAW_STATE_KEY);
    if (applied?.source !== 'outfit_set' || applied.itemCount < 1) {
      throw new Error(`套装未写入结构化服装块：${JSON.stringify(applied)}`);
    }
    await shoot('outfit-applied');

    await page.getByRole('button', { name: '服装套装', exact: true }).click();
    await drawer.waitFor({ state: 'visible' });
    const copyButton = drawer.getByText('另存副本', { exact: true });
    await copyButton.waitFor({ state: 'visible', timeout: 15000 });
    await copyButton.click();
    const modal = page.locator('.ant-modal').filter({ hasText: '另存用户副本' });
    await modal.waitFor({ state: 'visible' });
    const copyName = `UI验收套装_${Date.now()}`;
    await modal.getByPlaceholder('套装名称').fill(copyName);
    await modal.getByRole('button', { name: '保存副本', exact: true }).click();
    await modal.waitFor({ state: 'hidden', timeout: 15000 });
    await page.waitForTimeout(500);
    await drawer.getByText(copyName, { exact: true }).first().waitFor();
    await shoot('outfit-copy-saved', drawer);

    const listResponse = await fetch(`${API}/prompt-agent/outfit-presets`);
    const list = await listResponse.json();
    const created = (list.items || []).find((item) => item.name === copyName);
    createdPresetId = created?.preset_id || '';
    if (!createdPresetId || created.source !== 'user') {
      throw new Error(`未找到新建用户套装：${copyName}`);
    }

    const report = {
      builtin_count: builtinCount,
      applied,
      created_preset_id: createdPresetId,
      created_name: copyName,
      generation_requests: generationRequests,
      http_errors: httpErrors,
      request_failures: requestFailures,
      console_problems: problems,
      screenshots: shots,
    };
    fs.writeFileSync(
      path.join(outDir, 'outfit_set_ui_report.json'),
      JSON.stringify(report, null, 2),
      'utf8',
    );
    console.log(JSON.stringify(report, null, 2));
    if (
      generationRequests ||
      httpErrors.length ||
      requestFailures.length ||
      problems.length
    ) {
      throw new Error('页面验收存在请求或浏览器错误');
    }
  } finally {
    if (createdPresetId) {
      await fetch(`${API}/prompt-agent/outfit-presets/${createdPresetId}`, {
        method: 'DELETE',
      }).catch(() => undefined);
    }
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
