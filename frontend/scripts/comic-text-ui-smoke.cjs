// Live acceptance for deterministic comic text rendering and dialogue extraction.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const value of buffer) {
    crc ^= value;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const name = Buffer.from(type, 'ascii');
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const checksum = Buffer.alloc(4);
  checksum.writeUInt32BE(crc32(Buffer.concat([name, data])));
  return Buffer.concat([length, name, data, checksum]);
}

function createPng(width, height) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const row = Buffer.alloc(1 + width * 3);
  for (let x = 0; x < width; x += 1) {
    const gradient = Math.round(235 + (x / width) * 20);
    row[1 + x * 3] = gradient;
    row[2 + x * 3] = gradient;
    row[3 + x * 3] = gradient;
  }
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    pngChunk('IHDR', header),
    pngChunk('IDAT', zlib.deflateSync(raw)),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });
  const imagePath = path.join(
    os.tmpdir(),
    `rider-comic-smoke-${Date.now()}.png`,
  );
  fs.writeFileSync(imagePath, createPng(720, 1000));

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
      (request.url().includes('/api/draw/jobs') ||
        request.url().includes('/api/draw/inpaint/jobs'))
    ) {
      generationRequests.push(request.url());
    }
  });

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.locator('.ant-tabs-tab').first().click();
    await page.locator('.ai-drawing-mode-tabs button').nth(4).click();
    const panel = page.locator('.comic-text-panel');
    await panel.getByRole('heading', { name: '漫画文字' }).waitFor();
    await panel.getByText('自动气泡检测当前不可用').waitFor();

    await panel.locator('input[type="file"]').setInputFiles(imagePath);
    await panel.getByText('720 × 1000', { exact: true }).waitFor();
    await panel
      .getByPlaceholder('例：漫画分镜，空白气泡。[这是第一句。] [Second line.]')
      .fill(
        '漫画分镜，人物站在窗边，[中文对白需要自动换行。] [Fast English dialogue wraps safely.]',
      );
    await panel
      .getByRole('button', { name: /提取对白并清洗提示词/ })
      .click();
    await panel.getByText('对白提取（2 句）').waitFor();
    await panel.getByRole('button', { name: '全部加入画布' }).click();
    await panel.getByRole('button', { name: /渲染 2 个文字框/ }).waitFor();

    await panel.locator('.comic-canvas-stage > img').click({
      position: { x: 400, y: 500 },
    });
    const renderResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/image-tools/comic/render'),
      { timeout: 60000 },
    );
    await panel.getByRole('button', { name: /渲染 2 个文字框/ }).click();
    const response = await renderResponse;
    if (response.status() !== 200) {
      console.error(await response.text());
      throw new Error(`漫画文字渲染返回 HTTP ${response.status()}`);
    }
    fs.writeFileSync(
      path.join(outDir, 'comic_text_result.png'),
      await response.body(),
    );
    await panel.getByText('渲染结果', { exact: true }).waitFor();
    await panel.getByText('未写入图片库', { exact: true }).waitFor();
    await page.screenshot({
      path: path.join(outDir, 'comic_text_workspace.png'),
      fullPage: true,
    });

    const report = {
      uploaded_image: '720 × 1000',
      dialogue_count: 2,
      rendered_box_count: 2,
      render_status: response.status(),
      auto_bubble_available: false,
      generation_requests: generationRequests,
      external_requests: externalRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'comic_text_ui_report.json'),
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
    fs.rmSync(imagePath, { force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
