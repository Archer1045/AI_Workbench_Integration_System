// Live acceptance for pinned outfit-set versions and append-only rollback.
// Creates one temporary user set through the local API and removes it afterwards.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const API = process.env.API_BASE_URL || 'http://127.0.0.1:8500/api';

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${response.status} ${url}: ${JSON.stringify(body)}`);
  }
  return body;
}

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const suffix = Date.now().toString();
  const setName = `UI 版本验收 ${suffix}`;
  const appearanceName = `UI 角色套装关联 ${suffix}`;
  let presetId = '';
  let appearanceId = '';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const unexpectedHttpErrors = [];
  const externalRequests = [];
  const generationRequests = [];

  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !message.text().includes('Failed to load resource')
    ) {
      consoleProblems.push(message.text());
    }
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  page.on('requestfailed', (request) => {
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText || ''}`,
    );
  });
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (
      !['127.0.0.1', 'localhost'].includes(url.hostname) &&
      !['blob:', 'data:'].includes(url.protocol)
    ) {
      externalRequests.push(`${request.method()} ${request.url()}`);
    }
    if (
      request.method() === 'POST' &&
      (request.url().includes('/api/draw') ||
        request.url().includes('/api/video/generate') ||
        request.url().includes('/candidates/ai'))
    ) {
      generationRequests.push(request.url());
    }
  });
  page.on('response', (response) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
      unexpectedHttpErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    const initial = await jsonRequest(`${API}/prompt-agent/outfit-presets`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: setName,
        description: 'UI live acceptance v1',
        category: 'Test',
        items: [
          { clothing_id: 'organza_overlay_shirt' },
          { clothing_id: 'tulle_tiered_midi_skirt' },
          { clothing_id: 'shoe_mary_janes' },
        ],
      }),
    });
    presetId = initial.item.preset_id;
    await jsonRequest(`${API}/prompt-agent/outfit-presets/${presetId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: `${setName} v2`,
        description: 'UI live acceptance v2',
        category: 'Test',
        items: [
          { clothing_id: 'chiffon_draped_blouse' },
          { clothing_id: 'shoe_black_stiletto_heels' },
        ],
      }),
    });

    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
    await page.getByRole('button', { name: '服装套装', exact: true }).click();
    const drawer = page
      .locator('.ant-drawer.ant-drawer-open')
      .filter({ hasText: '服装套装' });
    await drawer.waitFor({ state: 'visible' });
    await drawer.getByPlaceholder('搜索套装').fill(setName);
    await drawer.getByText(`${setName} v2`, { exact: true }).first().click();
    await drawer.getByText('2 件 · v2', { exact: true }).waitFor();

    await drawer.getByRole('button', { name: /历史版本/ }).click();
    const history = page
      .locator('.ant-modal-content')
      .filter({ hasText: '回滚不会删除历史版本' });
    await history.waitFor({ state: 'visible' });
    await history.getByText('v1', { exact: true }).waitFor();
    await history.getByText('v2', { exact: true }).waitFor();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: path.join(outDir, 'outfit_version_history.png'),
      fullPage: true,
    });

    await history.getByRole('button', { name: '恢复此版本' }).click();
    const rollbackResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes(`/outfit-presets/${presetId}/rollback`) &&
        response.status() === 200,
    );
    await page.getByRole('button', { name: '确 定' }).click();
    await rollbackResponse;
    await page.waitForTimeout(800);

    const versions = await jsonRequest(
      `${API}/prompt-agent/outfit-presets/${presetId}/versions`,
    );
    if (versions.total !== 3 || versions.items[0].version !== 3) {
      throw new Error(`回滚后版本不符合预期：${JSON.stringify(versions)}`);
    }
    if (versions.items[0].name !== setName) {
      throw new Error('回滚未恢复 v1 内容');
    }

    await history.getByRole('button', { name: 'Close' }).click();
    await history.waitFor({ state: 'hidden' });
    await page.waitForTimeout(350);
    await drawer.locator('.ant-drawer-close').click({ force: true });
    await page.waitForTimeout(500);
    if (await drawer.isVisible().catch(() => false)) {
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
    }

    await page.getByRole('button', { name: /预设选择器/ }).click();
    const presetDrawer = page
      .locator('.ant-drawer.ant-drawer-open')
      .filter({ hasText: '预设选择器' });
    await presetDrawer.waitFor({ state: 'visible' });
    await presetDrawer.getByRole('tab', { name: '角色工具' }).click();
    await presetDrawer.getByRole('button', { name: '打开角色外貌' }).click();
    await page.waitForTimeout(700);
    const characterModal = page.getByRole('dialog', {
      name: '填入角色外貌/默认服装',
    });
    await characterModal.waitFor({ state: 'visible' });
    await characterModal.getByRole('button', { name: /新建/ }).click();
    const editModal = page.getByRole('dialog', { name: '新增外观预设' });
    await editModal.waitFor({ state: 'visible' });
    await editModal.getByPlaceholder('预设名称').fill(appearanceName);
    await editModal
      .getByPlaceholder('例如 outfit_genshin_columbina_default')
      .fill('outfit_genshin_columbina_default');
    const setField = editModal
      .getByText('默认服装套装（可选）', { exact: true })
      .locator('..');
    const setCombobox = setField.getByRole('combobox').first();
    await setCombobox.click();
    await setCombobox.fill(setName);
    await page.getByText(`${setName} · Test · v3`, { exact: true }).click();
    await page.waitForTimeout(1000);
    const setFieldText = await setField.textContent();
    if (!setFieldText?.includes('v3')) {
      throw new Error(`角色编辑器未显示固定版本 v3：${setFieldText || ''}`);
    }
    await page.screenshot({
      path: path.join(outDir, 'character_default_outfit_set.png'),
      fullPage: true,
    });
    await editModal.getByRole('button', { name: /确 定|OK/ }).click();
    await editModal.waitFor({ state: 'hidden' });
    await page.waitForTimeout(500);

    const appearanceList = await jsonRequest(
      `${API}/prompt-agent/appearance-presets?keyword=${encodeURIComponent(appearanceName)}`,
    );
    const appearance = appearanceList.items.find(
      (item) => item.name === appearanceName,
    );
    if (!appearance) throw new Error('页面未保存角色默认套装关联');
    appearanceId = appearance.preset_id;
    if (
      appearance.outfit_set_id !== presetId ||
      appearance.outfit_set_version !== 3 ||
      appearance.outfit_id !== 'outfit_genshin_columbina_default'
    ) {
      throw new Error(`角色默认套装关联字段不正确：${JSON.stringify(appearance)}`);
    }

    const report = {
      preset_id: presetId,
      appearance_id: appearanceId,
      saved_versions: versions.items.map((item) => item.version),
      rollback_latest_version: versions.items[0].version,
      rollback_restored_name: versions.items[0].name,
      character_set_pinned_version: appearance.outfit_set_version,
      character_atomic_outfit_id: appearance.outfit_id,
      character_set_items: appearance.outfit_set_items?.length || 0,
      generation_requests: generationRequests,
      external_requests: externalRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'outfit_version_ui_report.json'),
      JSON.stringify(report, null, 2),
      'utf8',
    );
    console.log(JSON.stringify(report, null, 2));
    if (
      generationRequests.length ||
      externalRequests.length ||
      unexpectedHttpErrors.length ||
      requestFailures.length ||
      consoleProblems.length ||
      pageErrors.length
    ) {
      throw new Error('页面验收存在外部请求、生成请求或浏览器错误');
    }
  } finally {
    if (appearanceId) {
      await fetch(`${API}/prompt-agent/appearance-presets/${appearanceId}`, {
        method: 'DELETE',
      }).catch(() => undefined);
    }
    if (presetId) {
      await fetch(`${API}/prompt-agent/outfit-presets/${presetId}`, {
        method: 'DELETE',
      }).catch(() => undefined);
    }
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
