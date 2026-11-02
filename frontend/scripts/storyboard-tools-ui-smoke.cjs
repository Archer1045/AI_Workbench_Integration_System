// Live acceptance for storyboard slicing and compatible video merging.
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';
const FFMPEG =
  process.env.FFMPEG_EXE ||
  'D:\\AI\\ComfyUI\\venv\\Lib\\site-packages\\imageio_ffmpeg\\binaries\\ffmpeg-win-x86_64-v7.1.exe';

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
  const rows = [];
  for (let y = 0; y < height; y += 1) {
    const row = Buffer.alloc(1 + width * 3);
    for (let x = 0; x < width; x += 1) {
      row[1 + x * 3] = Math.round((x / width) * 255);
      row[2 + x * 3] = Math.round((y / height) * 255);
      row[3 + x * 3] = 220;
    }
    rows.push(row);
  }
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    pngChunk('IHDR', header),
    pngChunk('IDAT', zlib.deflateSync(Buffer.concat(rows))),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

function createVideo(output, color, frequency) {
  execFileSync(
    FFMPEG,
    [
      '-hide_banner',
      '-loglevel',
      'error',
      '-y',
      '-f',
      'lavfi',
      '-i',
      `color=c=${color}:s=64x64:r=10:d=0.6`,
      '-f',
      'lavfi',
      '-i',
      `sine=frequency=${frequency}:sample_rate=44100:duration=0.6`,
      '-shortest',
      '-c:v',
      'libx264',
      '-pix_fmt',
      'yuv420p',
      '-c:a',
      'aac',
      output,
    ],
    { stdio: 'pipe' },
  );
}

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rider-storyboard-smoke-'));
  const imagePath = path.join(tempDir, 'storyboard.png');
  const firstVideo = path.join(tempDir, 'first.mp4');
  const secondVideo = path.join(tempDir, 'second.mp4');
  fs.writeFileSync(imagePath, createPng(720, 480));
  createVideo(firstVideo, 'red', 440);
  createVideo(secondVideo, 'blue', 660);

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
      request.url().includes('/api/video/generate')
    ) {
      generationRequests.push(request.url());
    }
  });

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.locator('.ant-tabs-tab').nth(2).click();
    await page
      .locator('.video-workspace-switch')
      .getByText('分镜与合并', { exact: true })
      .click();
    const panel = page.locator('.storyboard-tools');
    await panel.getByRole('heading', { name: '分镜与视频合并' }).waitFor();

    await panel.locator('input[type="file"]').setInputFiles(imagePath);
    const sliceResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/storyboard/slice') &&
        response.status() === 200,
    );
    await panel.getByRole('button', { name: /生成 4 个分镜 PNG/ }).click();
    const slice = await sliceResponse;
    fs.writeFileSync(
      path.join(outDir, 'storyboard_4cells.zip'),
      await slice.body(),
    );
    await panel.getByRole('button', { name: /下载 ZIP \+ 元数据/ }).waitFor();

    await panel.getByText('视频合并', { exact: true }).click();
    await panel
      .locator('input[type="file"]')
      .setInputFiles([firstVideo, secondVideo]);
    const preflightResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/storyboard/merge/preflight') &&
        response.status() === 200,
    );
    await panel.getByRole('button', { name: /合并前预检/ }).click();
    const preflight = await preflightResponse;
    const preflightBody = await preflight.json();
    if (!preflightBody.compatible) {
      throw new Error(`兼容视频预检失败：${JSON.stringify(preflightBody)}`);
    }
    await panel.getByText('兼容，可无损合并为 MP4').waitFor();

    const mergeResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes('/api/storyboard/merge') &&
        !response.url().includes('preflight') &&
        response.status() === 200,
    );
    await panel.getByRole('button', { name: /无损合并/ }).click();
    const merge = await mergeResponse;
    const mergeBody = await merge.json();
    const mergedBytes = await page.request.get(
      new URL(mergeBody.url, BASE).href,
    );
    if (!mergedBytes.ok()) {
      throw new Error(`合并视频不可下载：HTTP ${mergedBytes.status()}`);
    }
    fs.writeFileSync(
      path.join(outDir, 'merged_segments.mp4'),
      await mergedBytes.body(),
    );
    await panel.getByText('合并结果', { exact: true }).waitFor();
    await page.screenshot({
      path: path.join(outDir, 'storyboard_tools_workspace.png'),
      fullPage: true,
    });

    const report = {
      slice_grid: 4,
      slice_cell_count: 4,
      preflight_compatible: preflightBody.compatible,
      preflight_files: preflightBody.files.length,
      preflight_audio_codec: preflightBody.files[0].audio?.codec || '',
      merge_format: mergeBody.format,
      merge_url: mergeBody.url,
      merge_bytes: mergeBody.bytes,
      generation_requests: generationRequests,
      external_requests: externalRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'storyboard_tools_ui_report.json'),
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
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
