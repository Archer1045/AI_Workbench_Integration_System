// 前端 UI 冒烟：用 Playwright 打开开发服务器，依次进入「本期活动 / 活动日历 / 执行」，
// 截图 + 收集控制台错误。**纯离线**（只需要后端 8500 与前端 5173 在跑），不碰游戏、不花 AP。
//
// 用法（在 studio/frontend 下）：
//   node scripts/ui-smoke.cjs [截图输出目录]
// 浏览器用系统自带的 Edge（channel: 'msedge'），所以不需要下载 Playwright 的浏览器包。
const { chromium } = require('playwright');
const path = require('path');
const os = require('os');

const BASE = process.env.UI_SMOKE_URL || 'http://localhost:5173/';

(async () => {
  const outDir = process.argv[2] || os.tmpdir();
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const problems = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') problems.push(`console: ${msg.text()}`);
  });
  page.on('pageerror', (err) => problems.push(`pageerror: ${err.message}`));
  page.on('requestfailed', (req) => problems.push(`requestfailed: ${req.url()} ${req.failure()?.errorText}`));

  const shots = [];
  const shoot = async (name, fullPage = false) => {
    const file = path.join(outDir, `ui_${name}.png`);
    await page.screenshot({ path: file, fullPage });
    shots.push(file);
  };
  const openTab = async (label) => {
    // 左侧导航是 .ga-navbtn；不能用 getByRole(name) —— antd 图标会给可访问名加上 aria-label
    const button = page.locator('.ga-navbtn', { hasText: label }).first();
    await button.click({ timeout: 15000 });
    await page.waitForTimeout(1500);
  };

  await page.goto(BASE, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(4000);
  const title = await page.title();
  // 工作台是顶层 Tab：先进「游戏助手」那一个
  await page.getByRole('tab', { name: '游戏助手' }).first().click({ timeout: 15000 });
  await page.waitForTimeout(4000);
  const hasAssistant = await page.locator('.game-assistant').count();

  await shoot('01_activity', true);
  // 折叠条在活动卡下面、内层容器滚动时视口截不到 ⇒ 单独做元素截图
  const endedBar = page.locator('.ga-ended-bar').first();
  if (await endedBar.count()) {
    const file = path.join(outDir, 'ui_04_ended_bar.png');
    await endedBar.screenshot({ path: file });
    shots.push(file);
  } else {
    problems.push('没找到 .ga-ended-bar（若活动已结束，这条折叠条应该出现）');
  }
  try {
    await openTab('活动日历');
    await shoot('02_calendar', true);
    const grid = page.locator('.ga-cal').first();
    if (await grid.count()) {
      const file = path.join(outDir, 'ui_05_calendar_grid.png');
      await grid.screenshot({ path: file });
      shots.push(file);
    }
  } catch (err) {
    problems.push(`切到「活动日历」失败：${err.message}`);
  }
  try {
    await openTab('执行');
    await shoot('03_execute', true);
    // 如果下拉里有「活动已结束」的 runbook：先打开危险开关把它放行，再选中它
    // （正常情况下它是禁用的），确认 warning 与「归档这份」都出现。
    const runbookSelect = page.locator('.ga-exec-grid .ant-select').first();
    await runbookSelect.click({ timeout: 10000 });
    await page.waitForTimeout(600);
    const endedOption = page.locator('.ant-select-item-option', { hasText: '活动已结束' }).first();
    if (await endedOption.count()) {
      const disabledBefore = await endedOption.getAttribute('aria-disabled');
      const clsBefore = await endedOption.getAttribute('class');
      const dropdown = page.locator('.ant-select-dropdown').first();
      const dropdownShot = path.join(outDir, 'ui_07_runbook_options.png');
      await dropdown.screenshot({ path: dropdownShot });
      shots.push(dropdownShot);
      await page.keyboard.press('Escape');
      const dangerSwitch = page.locator('.ga-exec-switch', { hasText: '允许跑' }).locator('.ant-switch').first();
      await dangerSwitch.click({ timeout: 10000 });
      await page.waitForTimeout(400);
      await runbookSelect.click({ timeout: 10000 });
      await page.waitForTimeout(600);
      const enabledNow = page.locator('.ant-select-item-option', { hasText: '活动已结束' }).first();
      const disabledAfter = await enabledNow.getAttribute('aria-disabled');
      await enabledNow.click({ timeout: 10000 });
      await page.waitForTimeout(800);
      const settingsCard = page.locator('.ant-card', { hasText: '运行设置' }).first();
      const shotName = path.join(outDir, 'ui_06_ended_runbook.png');
      await settingsCard.screenshot({ path: shotName });
      shots.push(shotName);
      problems.push(
        `ended-runbook 选项：放行前 aria-disabled=${disabledBefore} / class~disabled=${String(clsBefore).includes('disabled')}；` +
          `放行后 aria-disabled=${disabledAfter}`,
      );
    } else {
      problems.push('执行页下拉里没有「活动已结束」的 runbook（已归档或没有结束活动的 runbook）');
      const settingsCard = page.locator('.ant-card', { hasText: '运行设置' }).first();
      const file = path.join(outDir, 'ui_08_archived.png');
      await settingsCard.screenshot({ path: file });
      shots.push(file);
    }
  } catch (err) {
    problems.push(`切到「执行」失败：${err.message}`);
  }

  console.log(JSON.stringify({ url: BASE, title, assistantNodes: hasAssistant, shots, problems }, null, 2));
  await browser.close();
})().catch((err) => {
  console.error('smoke failed:', err);
  process.exit(1);
});
