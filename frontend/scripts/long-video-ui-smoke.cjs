// Live rendering acceptance for the checkpointed long-video workflow.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';
const API = process.env.API_BASE_URL || 'http://127.0.0.1:8500/api';

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const validation = await fetch(`${API}/video/long/jobs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      keyframe_name: 'validation-only.png',
      prompts: Array.from({ length: 21 }, () => 'validation prompt'),
      frames: 121,
      width: 512,
      height: 512,
      steps: 1,
      cfg: 1,
      denoise: 1,
    }),
  });
  const validationBody = await validation.json().catch(() => ({}));
  if (validation.status !== 400 || !String(validationBody.detail || '').includes('最多')) {
    throw new Error(`长视频边界未按预期拒绝：${validation.status}`);
  }

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const unexpectedHttpErrors = [];
  const generationRequests = [];
  const externalRequests = [];

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
  page.on('response', (response) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
      unexpectedHttpErrors.push(`${response.status()} ${response.url()}`);
    }
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
      request.url().includes('/api/video/long/jobs')
    ) {
      generationRequests.push(request.url());
    }
  });

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.locator('.ant-tabs-tab').nth(2).click();
    await page
      .locator('.video-workspace-switch')
      .getByText('长视频分段', { exact: true })
      .click();
    const panel = page.locator('.long-video-panel');
    await panel.getByRole('heading', { name: '长视频分段接力' }).waitFor();
    await panel.getByPlaceholder('第 1 段动作描述').waitFor();
    await panel.getByPlaceholder('第 2 段动作描述').waitFor();
    await panel.getByRole('button', { name: /开始分段生成/ }).waitFor();
    await panel.getByText('检查点可恢复', { exact: true }).waitFor();
    await page.screenshot({
      path: path.join(outDir, 'long_video_workspace.png'),
      fullPage: true,
    });

    const report = {
      validation_status: validation.status,
      validation_detail: validationBody.detail,
      visible_segments: 2,
      checkpoint_recovery_visible: true,
      generation_requests: generationRequests,
      external_requests: externalRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'long_video_ui_report.json'),
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
      throw new Error('页面验收存在生成/外部请求或浏览器错误');
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
