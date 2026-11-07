// Live acceptance for caption progress reconnection after a page refresh.
// This script expects an isolated backend with a temporary dataset.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const UI = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const API_BASE =
  process.env.CAPTION_SMOKE_API || 'http://127.0.0.1:8501/api';
const API_ORIGIN = new URL(API_BASE).origin;

async function requestJson(url, options = {}) {
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

  const idempotencyKey = `caption-refresh-${Date.now()}`;
  const startOptions = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
    body: JSON.stringify({
      mode: 'wd14',
      skip_existing: false,
      threshold: 0.35,
      batch_size: 1,
      remove_underscore: true,
      language: 'tags',
    }),
  };
  const started = await requestJson(`${API_BASE}/train/caption`, startOptions);
  const duplicate = await requestJson(`${API_BASE}/train/caption`, startOptions);
  if (duplicate.job_id !== started.job_id || duplicate.reused !== true) {
    throw new Error('相同的 Idempotency-Key 未复用运行中任务');
  }
  const jobId = started.job_id;
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const externalRequests = [];

  await page.route('**/api/**', async (route) => {
    const source = new URL(route.request().url());
    const target = new URL(source.pathname + source.search, API_ORIGIN);
    await route.continue({ url: target.toString() });
  });
  page.on('console', (message) => {
    if (
      message.type() === 'error' &&
      !message.text().includes('Failed to load resource') &&
      !message.text().includes('[rc-collapse]')
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

  const openTraining = async () => {
    const tab = page.getByRole('tab', { name: 'LoRA 训练' });
    if (!(await tab.getAttribute('aria-selected'))?.includes('true')) {
      await tab.click();
    }
    await page.locator('.train-progress').waitFor({ state: 'visible' });
  };
  const currentPercent = async () => {
    const text = await page.locator('.train-progress .ant-progress-text').textContent();
    return Number.parseInt(text || '0', 10);
  };
  const waitForProgress = async (minimum, timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const value = await currentPercent();
      if (value >= minimum) return value;
      await page.waitForTimeout(500);
    }
    throw new Error(`打标进度未达到 ${minimum}%`);
  };

  try {
    await page.goto(UI, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await openTraining();
    const beforeRefresh = await waitForProgress(1, 90000);
    const storedJob = await page.evaluate(() =>
      JSON.parse(localStorage.getItem('rider-studio:caption-task-v1') || '{}'),
    );
    if (storedJob.jobId !== jobId) {
      throw new Error(`页面未保存当前任务：${JSON.stringify(storedJob)}`);
    }

    await page.reload({ waitUntil: 'domcontentloaded' });
    await openTraining();
    const afterRefresh = await waitForProgress(beforeRefresh, 15000);
    await page.screenshot({
      path: path.join(outDir, 'caption_refresh_recovered.png'),
      fullPage: true,
    });

    const report = {
      job_id: jobId,
      before_refresh_percent: beforeRefresh,
      after_refresh_percent: afterRefresh,
      reconnected_from_storage: storedJob.jobId === jobId,
      idempotency_reused: duplicate.reused,
      external_requests: externalRequests,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'caption_refresh_recovery_report.json'),
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
    await fetch(`${API_BASE}/train/caption/${jobId}/stop`, {
      method: 'POST',
    }).catch(() => undefined);
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
