// Edge acceptance for owner-aware runbook card preference chains.
// The runbook POST is intercepted so no formal runbook file is created.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1100 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const externalRequests = [];
  let capturedDraft = null;

  await page.route('**/api/game-assistant/fgo/execution/runbooks', async (route) => {
    if (route.request().method() === 'POST') {
      capturedDraft = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          name: capturedDraft.name,
          actions: capturedDraft.steps.length,
          summary: 'UI acceptance',
          support: capturedDraft.support || {},
        }),
      });
      return;
    }
    await route.continue();
  });
  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !message.text().includes('Failed to load resource') &&
      !message.text().includes('[rc-collapse]') &&
      !message.text().includes('`addonBefore` is deprecated')
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
  });

  const dropdownFor = async () =>
    page
      .locator('.ant-select-dropdown:not(.ant-select-dropdown-hidden)')
      .last();
  const chooseFirst = async (select) => {
    await select.locator('.ant-select-selector').click();
    const option = (await dropdownFor())
      .locator('.ant-select-item-option')
      .first();
    await option.waitFor({ state: 'visible' });
    await option.click();
    await page.waitForTimeout(150);
  };
  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.getByRole('tab', { name: '游戏助手' }).click();
    await page.getByRole('button', { name: '执行' }).click();
    const builder = page.locator('.ant-card').filter({ hasText: '新建 runbook' }).first();
    await builder.waitFor({ state: 'visible' });

    for (const index of [1, 2, 3]) {
      await chooseFirst(builder.locator('.ant-select').nth(index));
    }

    const kindSelect = builder.locator('.ant-select').filter({ hasText: /^技能$/ }).first();
    await kindSelect.locator('.ant-select-selector').click();
    await (await dropdownFor())
      .locator('.ant-select-item-option')
      .filter({ hasText: '指令卡' })
      .click();

    await chooseFirst(builder.locator('.ant-select').nth(8));
    const colorSelect = builder.locator('.ant-select').nth(9);
    await colorSelect.locator('.ant-select-selector').click();
    await (await dropdownFor())
      .locator('.ant-select-item-option')
      .filter({ hasText: '红（Buster）' })
      .click();
    await builder.getByRole('button', { name: '加入偏好链' }).click();
    await builder.getByRole('button', { name: '加任意卡兜底' }).click();
    await chooseFirst(builder.locator('.ant-select').nth(7));

    const addAction = builder.getByRole('button', { name: /加动作/ });
    await addAction.click();
    await addAction.click();
    await addAction.click();
    await page.screenshot({
      path: path.join(outDir, 'runbook_owner_chain.png'),
      fullPage: true,
    });

    await builder.getByRole('button', { name: /生成并校验/ }).click();
    const deadline = Date.now() + 15000;
    while (!capturedDraft && Date.now() < deadline) {
      await page.waitForTimeout(100);
    }
    if (!capturedDraft) throw new Error('没有捕获 runbook 提交');
    const cardSteps = capturedDraft.steps.filter((step) => step.kind === 'card');
    if (cardSteps.length !== 3 || !cardSteps[0].choose?.length) {
      throw new Error(`卡片动作或偏好链缺失：${JSON.stringify(capturedDraft.steps)}`);
    }
    for (const step of cardSteps) {
      if (!step.choose[0]?.owner) throw new Error('第一条偏好链丢失了卡主');
      const last = step.choose[step.choose.length - 1];
      if (last.owner || last.card !== 'any') {
        throw new Error('最后一条不是显式的不限卡主任意卡');
      }
    }

    const report = {
      runbook_name: capturedDraft.name,
      team_size: capturedDraft.team.length,
      card_steps: cardSteps.length,
      first_preference: cardSteps[0].choose[0],
      final_preference: cardSteps[0].choose[cardSteps[0].choose.length - 1],
      preference_count: cardSteps[0].choose.length,
      formal_file_written: false,
      external_requests: externalRequests,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'runbook_owner_chain_report.json'),
      JSON.stringify(report, null, 2),
      'utf8',
    );
    console.log(JSON.stringify(report, null, 2));
    if (
      externalRequests.length ||
      requestFailures.length ||
      consoleProblems.length ||
      pageErrors.length
    ) {
      throw new Error('页面验收存在外部请求或浏览器错误');
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
