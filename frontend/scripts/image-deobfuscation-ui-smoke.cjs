// Local image deobfuscation UI acceptance. Never uploads to a third party,
// never calls a generation endpoint, and saves a JSON report without image copies.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';
const SAMPLE =
  process.env.IMAGE_DEOBFUSCATION_SAMPLE ||
  'C:\\Users\\admin\\AppData\\Local\\Temp\\codex-clipboard-af285635-2906-413a-8d41-41b8abbe69c5.jpg';
const CONTROL =
  process.env.IMAGE_DEOBFUSCATION_CONTROL ||
  path.resolve(
    __dirname,
    '..',
    'public',
    'body-modification-presets',
    'mod_ankle_rings.webp',
  );

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  if (!fs.existsSync(SAMPLE)) throw new Error(`验收样本不存在：${SAMPLE}`);
  if (!fs.existsSync(CONTROL)) throw new Error(`对照图片不存在：${CONTROL}`);
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const externalRequests = [];
  const generationRequests = [];
  const unexpectedHttpErrors = [];

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
    if (
      response.status() >= 400 &&
      response.url().includes('/api/') &&
      response.status() !== 422
    ) {
      unexpectedHttpErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.getByRole('tab', { name: 'AI 绘画' }).first().click();
    const modeTabs = page.locator('.ai-drawing-mode-tabs');
    await modeTabs.getByRole('tab', { name: '图片解混淆' }).click();
    await page.getByRole('heading', { name: '图片解混淆' }).waitFor();

    const fileInput = page.locator('.image-tool-panel input[type="file"]');
    await fileInput.setInputFiles(SAMPLE);
    await page.getByText('识别通过', { exact: true }).waitFor({ timeout: 30000 });
    await page.getByAltText('解混淆后的图片').waitFor({ state: 'visible' });
    const sampleDimensions = await page.getByText('720 × 1145', { exact: true }).textContent();
    const sampleAccepted = await page.getByText('识别通过', { exact: true }).isVisible();
    const downloadEnabled = await page
      .getByRole('button', { name: '下载 PNG' })
      .isEnabled();
    const reportHash = await page.locator('.ant-descriptions').textContent();
    if (!sampleDimensions || !sampleAccepted || !downloadEnabled) {
      throw new Error('小番茄样本未完整通过页面验收');
    }
    if (!reportHash?.includes('xiaofanqie-gilbert-v1')) {
      throw new Error('页面未显示解混淆算法报告');
    }

    await fileInput.setInputFiles(CONTROL);
    await page
      .getByText('未能确认这是小番茄混淆图', { exact: true })
      .waitFor({ timeout: 30000 });
    const rejectedMessage = await page
      .getByText('解混淆后粗糙度未明显下降，可能不是小番茄混淆图', {
        exact: true,
      })
      .textContent();

    await page
      .getByRole('checkbox', { name: '强制查看未通过识别的结果' })
      .check();
    await page.getByRole('button', { name: '重新解混淆' }).click();
    await page
      .getByText('当前为强制查看结果', { exact: true })
      .waitFor({ timeout: 30000 });
    const forcedDownloadEnabled = await page
      .getByRole('button', { name: '下载 PNG' })
      .isEnabled();

    const report = {
      sample_format: 'JPEG',
      sample_dimensions: sampleDimensions,
      sample_accepted: sampleAccepted,
      report_algorithm_visible: Boolean(reportHash?.includes('xiaofanqie-gilbert-v1')),
      control_rejected: Boolean(rejectedMessage),
      forced_view_visible: true,
      forced_download_enabled: forcedDownloadEnabled,
      generation_requests: generationRequests,
      external_requests: externalRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'image_deobfuscation_ui_report.json'),
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
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
