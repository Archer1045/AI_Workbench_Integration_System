// Live acceptance for independently bound pose/costume galleries.
// Creates a temporary local gallery and restores the previous binding afterwards.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';
const API = process.env.API_BASE_URL || 'http://127.0.0.1:8500/api';

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

function createPng(width, height, rgb) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8;
  header[9] = 2;
  const row = Buffer.alloc(1 + width * 3);
  for (let x = 0; x < width; x += 1) {
    row[1 + x * 3] = rgb[0];
    row[2 + x * 3] = rgb[1];
    row[3 + x * 3] = rgb[2];
  }
  const raw = Buffer.concat(
    Array.from({ length: height }, () => row),
  );
  return Buffer.concat([
    Buffer.from('89504e470d0a1a0a', 'hex'),
    pngChunk('IHDR', header),
    pngChunk('IDAT', zlib.deflateSync(raw)),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`${response.status} ${url}: ${JSON.stringify(body)}`);
  }
  return body;
}

async function bindPose(directory) {
  return jsonRequest(`${API}/external-galleries/settings/pose`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      directory,
      confirmed_local_access: true,
    }),
  });
}

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const initialSettings = (
    await jsonRequest(`${API}/external-galleries/settings`)
  ).settings;
  const galleryRoot = fs.mkdtempSync(
    path.join(os.tmpdir(), 'rider-external-gallery-'),
  );
  fs.mkdirSync(path.join(galleryRoot, 'data'), { recursive: true });
  fs.mkdirSync(path.join(galleryRoot, 'images'), { recursive: true });
  fs.writeFileSync(
    path.join(galleryRoot, 'images', 'pose-front.png'),
    createPng(240, 320, [220, 225, 235]),
  );
  fs.writeFileSync(
    path.join(galleryRoot, 'images', 'pose-side.png'),
    createPng(240, 320, [215, 230, 220]),
  );
  fs.writeFileSync(
    path.join(galleryRoot, 'data', 'pose-zh.json'),
    JSON.stringify(
      [
        {
          id: 'smoke-pose-front',
          姿势名称: '验收正面站姿',
          分类: '站姿',
          体系: '基础',
          角度: '正面',
          标签: ['全身', '验收'],
          原图: 'images/pose-front.png',
        },
        {
          id: 'smoke-pose-side',
          姿势名称: '验收侧面站姿',
          分类: '站姿',
          体系: '基础',
          角度: '侧面',
          标签: ['全身', '验收'],
          原图: 'images/pose-side.png',
        },
      ],
      null,
      2,
    ),
    'utf8',
  );

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const consoleProblems = [];
  const pageErrors = [];
  const requestFailures = [];
  const unexpectedHttpErrors = [];
  const generationRequests = [];
  const relevantRequests = [];

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
    if (request.url().includes('/api/external-galleries/')) {
      relevantRequests.push(`${request.method()} ${request.url()}`);
    }
    if (request.url().includes('/api/draw/inpaint/sources')) {
      relevantRequests.push(`${request.method()} ${request.url()}`);
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
    const binding = await bindPose(galleryRoot);
    if (!binding.settings.pose.configured) {
      throw new Error('临时姿势图库未绑定成功');
    }
    const catalogue = await jsonRequest(
      `${API}/external-galleries/pose/catalogue`,
    );
    if (catalogue.mode !== 'manifest' || catalogue.count !== 2) {
      throw new Error(`图库清单元数据不正确：${JSON.stringify(catalogue)}`);
    }

    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.locator('.ant-tabs-tab').first().click();
    await page.locator('.ai-drawing-mode-tabs button').nth(1).click();
    await page.locator('.inpaint-header').getByText('外部参考图库').click();

    const drawer = page
      .locator('.ant-drawer.ant-drawer-open')
      .filter({ hasText: '外部参考图库' });
    await drawer.waitFor({ state: 'visible' });
    await drawer.getByRole('tab', { name: '姿势图库' }).waitFor();
    await drawer.getByText('验收正面站姿', { exact: true }).waitFor();
    await drawer.getByPlaceholder('搜索名称、标签或相对路径').fill('侧面');
    await drawer.getByText('验收侧面站姿', { exact: true }).waitFor();
    await drawer.getByText('验收正面站姿', { exact: true }).waitFor({
      state: 'hidden',
    });
    await drawer.getByPlaceholder('搜索名称、标签或相对路径').fill('');
    await drawer.getByText('验收正面站姿', { exact: true }).click();
    await drawer.getByText('240 × 320', { exact: true }).waitFor();
    await drawer
      .locator('.external-gallery-card.is-selected')
      .getByRole('button', { name: '收藏', exact: true })
      .click();
    await drawer.getByText('收藏 1', { exact: true }).waitFor();
    await drawer.screenshot({
      path: path.join(outDir, 'external_gallery_pose.png'),
    });

    await drawer.locator('.external-gallery-inspector button').click({
      force: true,
    });
    await page.waitForTimeout(5000);
    if (
      !relevantRequests.some(
        (request) =>
          request.startsWith('POST ') &&
          request.includes('/api/draw/inpaint/sources'),
      )
    ) {
      console.error(
        JSON.stringify(
          {
            relevantRequests,
            requestFailures,
            unexpectedHttpErrors,
            consoleProblems,
            pageErrors,
          },
          null,
          2,
        ),
      );
      throw new Error('选择外部素材后未创建局部重绘临时底图');
    }
    await drawer.waitFor({ state: 'hidden' });
    await page.getByText('姿势库 · 验收正面站姿', { exact: true }).waitFor();
    await page.screenshot({
      path: path.join(outDir, 'external_gallery_inpaint_source.png'),
      fullPage: true,
    });

    const report = {
      gallery_mode: catalogue.mode,
      manifest: catalogue.manifest,
      catalogue_count: catalogue.count,
      selected_item: '验收正面站姿',
      selected_dimensions: '240 × 320',
      temporary_upload_created: true,
      generation_requests: generationRequests,
      unexpected_http_errors: unexpectedHttpErrors,
      request_failures: requestFailures,
      console_problems: consoleProblems,
      page_errors: pageErrors,
    };
    fs.writeFileSync(
      path.join(outDir, 'external_gallery_ui_report.json'),
      JSON.stringify(report, null, 2),
      'utf8',
    );
    console.log(JSON.stringify(report, null, 2));
    if (
      generationRequests.length ||
      unexpectedHttpErrors.length ||
      requestFailures.length ||
      consoleProblems.length ||
      pageErrors.length
    ) {
      throw new Error('页面验收存在生成请求或浏览器错误');
    }
  } finally {
    const cleared = await fetch(
      `${API}/external-galleries/settings/pose`,
      { method: 'DELETE' },
    ).catch(() => null);
    if (cleared && !cleared.ok) {
      console.error(`清理临时姿势图库绑定失败：HTTP ${cleared.status}`);
    }
    if (initialSettings.pose.configured) {
      await bindPose(initialSettings.pose.directory).catch(() => undefined);
    }
    await browser.close();
    fs.rmSync(galleryRoot, { recursive: true, force: true });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
