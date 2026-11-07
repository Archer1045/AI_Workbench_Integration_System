// Bilibili Opus image-guide review acceptance. The source is already imported
// and analyzed by the backend; this script only verifies the review UI and that
// nothing is published automatically.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.UI_SMOKE_URL || 'http://127.0.0.1:5173/';

(async () => {
  const outDir = process.argv[2];
  if (!outDir) throw new Error('缺少证据输出目录');
  fs.mkdirSync(outDir, { recursive: true });

  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const problems = [];
  const httpErrors = [];
  let publishRequests = 0;

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
    if (request.method() === 'POST' && request.url().includes('/publish')) {
      publishRequests += 1;
    }
  });

  try {
    await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(1300);
    await page.getByRole('tab', { name: '游戏助手' }).first().click();
    await page.waitForTimeout(1000);

    const materialsRow = page
      .locator('.ga-slim-row')
      .filter({ hasText: '活动资料：阶段时间轴' });
    await materialsRow.waitFor({ state: 'visible', timeout: 15000 });
    await page.locator('.ga-slim-row button').last().click();
    await page.waitForTimeout(1000);

    const panel = page.locator('.ga-source-manager');
    if ((await panel.count()) === 0) {
      await page.screenshot({
        path: path.join(outDir, 'bilibili_opus_review_open_failed.png'),
        fullPage: true,
      });
      throw new Error('展开活动资料后未找到攻略来源面板');
    }
    await panel.waitFor({ state: 'visible', timeout: 15000 });
    await panel
      .getByText('FGO万圣2026攻略图片汇总', { exact: true })
      .first()
      .waitFor({ state: 'visible', timeout: 15000 });
    await page.waitForTimeout(1000);

    const imageCards = panel.locator('.ga-image-card');
    const imageCount = await imageCards.count();
    if (imageCount !== 28) {
      throw new Error(`图片复核卡片数量为 ${imageCount}，预期 28`);
    }
    const sectionText = await panel
      .locator('.ga-small.ga-muted')
      .allTextContents();
    for (const section of ['倍卡英灵与助战挂法', '主线概况', '90+', '90++', '高难作业']) {
      if (!sectionText.some((text) => text.includes(section))) {
        throw new Error(`页面未显示章节：${section}`);
      }
    }
    if (!(await panel.getByText(/新增 mechanics: 9/).isVisible())) {
      throw new Error('结构化 revision 预览未显示 9 个 mechanics');
    }
    if (!(await panel.getByRole('button', { name: '发布 revision' }).isVisible())) {
      throw new Error('缺少人工发布入口');
    }

    const screenshot = path.join(outDir, 'bilibili_opus_review.png');
    await panel.screenshot({ path: screenshot });
    const report = {
      image_count: imageCount,
      sections: [
        '倍卡英灵与助战挂法',
        '主线概况',
        '90+',
        '90++',
        '高难作业',
      ],
      extraction_preview: '新增 mechanics: 9',
      publish_requests: publishRequests,
      http_errors: httpErrors,
      console_problems: problems,
      screenshot,
    };
    fs.writeFileSync(
      path.join(outDir, 'bilibili_opus_ui_report.json'),
      JSON.stringify(report, null, 2),
      'utf8',
    );
    console.log(JSON.stringify(report, null, 2));
    if (publishRequests || httpErrors.length || problems.length) {
      throw new Error('页面验收存在自动发布或浏览器错误');
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
