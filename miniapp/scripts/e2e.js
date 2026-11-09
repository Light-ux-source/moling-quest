/**
 * H5 端到端验收：首页 → 探索/造关 → 生成 → 预览 → 答题 → 结算 → 报告。
 * 运行：
 *   npm run build:h5 && python3 scripts/serve_h5.py dist-h5 10087
 *   node scripts/e2e.js
 * 需要后端 8000（Mock 或真实 Key 均可）。
 */
const fs = require('fs')
const os = require('os')
const path = require('path')
const { chromium } = require('playwright-core')

const WEB = process.env.WEB_BASE || 'http://127.0.0.1:10087'
const OUT = path.join(__dirname, '..', '..', 'shots')

function resolveChrome() {
  if (process.env.PW_CHROME && fs.existsSync(process.env.PW_CHROME)) return process.env.PW_CHROME
  const cache = path.join(os.homedir(), 'Library', 'Caches', 'ms-playwright')
  if (fs.existsSync(cache)) {
    const dir = fs.readdirSync(cache).find((name) => name.startsWith('chromium_headless_shell-'))
    if (dir) {
      const candidates = [
        path.join(cache, dir, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell'),
        path.join(cache, dir, 'chrome-headless-shell-linux64', 'chrome-headless-shell')
      ]
      const found = candidates.find((file) => fs.existsSync(file))
      if (found) return found
    }
  }
  try {
    return chromium.executablePath()
  } catch (err) {
    return undefined
  }
}

async function layoutReport(page, name) {
  const info = await page.evaluate(() => {
    const doc = document.documentElement
    const overflow = []
    document.querySelectorAll('*').forEach((el) => {
      const rect = el.getBoundingClientRect()
      if (rect.width > 0 && (rect.right > doc.clientWidth + 2 || rect.left < -2)) {
        overflow.push(`${el.tagName}.${String(el.className)}`.slice(0, 80))
      }
    })
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
      scrollHeight: doc.scrollHeight,
      overflow: overflow.slice(0, 5)
    }
  })
  console.log(`[${name}] layout`, JSON.stringify(info))
  return info
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })
  const executablePath = resolveChrome()
  const browser = await chromium.launch({
    ...(executablePath ? { executablePath } : {}),
    args: ['--no-sandbox']
  })
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: 'zh-CN'
  })
  await context.route('https://fonts.googleapis.com/**', (route) => route.abort())
  await context.route('https://fonts.gstatic.com/**', (route) => route.abort())

  const page = await context.newPage()
  const errors = []
  const badResponses = []
  page.on('response', (res) => {
    if (res.status() >= 400) badResponses.push(`${res.status()} ${res.url()}`)
  })
  page.on('console', (msg) => {
    const text = msg.text()
    if (msg.type() === 'error' && !text.includes('ERR_FAILED') && !text.includes('favicon')) {
      errors.push(text)
    }
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))

  await page.goto(WEB, { waitUntil: 'load', timeout: 60000 })
  await page.waitForTimeout(900)
  await layoutReport(page, 'home')
  console.log('首页标题:', (await page.locator('body').innerText()).slice(0, 80).replace(/\n/g, ' | '))

  // 从 tabbar 的「探索」进入造关页
  await page.getByText('探索', { exact: true }).click()
  await page.waitForURL(/pages\/create\/index/, { timeout: 20000 })
  await page.waitForSelector('.create-title', { timeout: 20000 })
  console.log('已进入造关页')

  const topic = `端到端验收主题 ${Date.now()}`
  await page.locator('textarea').first().fill(topic)
  await page.getByText('生成关卡', { exact: true }).click()
  await page.waitForURL(/pages\/generating\/index/, { timeout: 30000 })
  console.log('已进入生成页')
  await page.waitForURL(/pages\/preview\/index/, { timeout: 90000 })
  await page.waitForSelector('.preview-title', { timeout: 30000 })
  await page.waitForTimeout(800)
  const previewTitle = await page.locator('.preview-title').innerText()
  console.log('预览章节:', previewTitle)
  await layoutReport(page, 'preview')

  await page.getByText('开始闯关', { exact: true }).click()
  await page.waitForURL(/pages\/quiz\/index/, { timeout: 30000 })
  await page.waitForSelector('.question-stem', { timeout: 30000 })
  await page.waitForTimeout(800)
  await layoutReport(page, 'quiz')

  for (let i = 0; i < 12; i += 1) {
    const optionCount = await page.locator('.option-card').count()
    if (optionCount > 0) {
      await page.locator('.option-card').first().click()
    } else {
      const box = page.locator('.answer-input textarea').first()
      if (await box.count()) {
        await box.fill('先说明定义，再描述机制和适用场景，最后给一个具体例子。')
      }
    }
    const nextLabel = await page.locator('.quiz-next').innerText()
    await page.locator('.quiz-next').click()
    if (nextLabel.includes('提交')) break
    await page.waitForTimeout(250)
  }

  await page.waitForURL(/pages\/result\/index/, { timeout: 90000 })
  await page.waitForSelector('.result-title', { timeout: 60000 })
  await page.waitForTimeout(900)
  const resultTitle = await page.locator('.result-title').innerText()
  const resultSub = await page.locator('.result-sub').innerText()
  console.log('结算:', resultTitle, '|', resultSub)
  await layoutReport(page, 'result')
  await page.screenshot({ path: path.join(OUT, 'e2e-result.png'), animations: 'disabled', timeout: 30000 })

  await page.locator('.result-action').first().click()
  await page.waitForURL(/pages\/report\/index/, { timeout: 30000 })
  await page.waitForSelector('.report-title', { timeout: 90000 })
  await page.waitForTimeout(800)
  const reportTitle = await page.locator('.report-title').innerText()
  const score = (await page.locator('.score-num').innerText()).trim()
  const reviews = await page.locator('.review-item').count()
  console.log('报告:', reportTitle, '| 分数', score, '| 逐题', reviews)

  await page.locator('.review-item').first().click()
  await page.waitForTimeout(400)
  const detailVisible = await page.locator('.review-detail').count()
  console.log('展开解析块:', detailVisible)
  await layoutReport(page, 'report')
  await page.locator('.page-shell:visible').last().screenshot({
    path: path.join(OUT, 'e2e-report.png'),
    animations: 'disabled',
    timeout: 30000
  })

  // 响应式：375 / 390 / 768 三档无横向溢出
  for (const width of [375, 390, 768]) {
    await page.setViewportSize({ width, height: width === 768 ? 1024 : 812 })
    await page.waitForTimeout(350)
    const info = await layoutReport(page, `report@${width}`)
    if (info.scrollWidth > info.clientWidth + 1) {
      errors.push(`横向溢出 @${width}px: ${info.scrollWidth} > ${info.clientWidth}`)
    }
  }

  console.log('bad responses:', badResponses.length ? badResponses.slice(0, 8) : 'none')
  console.log('console errors:', errors.length ? errors.slice(0, 8) : 'none')
  const ok =
    reviews === 5 &&
    detailVisible >= 1 &&
    Number.isFinite(Number(score)) &&
    errors.length === 0
  console.log(ok ? 'E2E PASS' : 'E2E CHECK FAILED')
  await browser.close()
  if (!ok) process.exit(1)
}

main().catch((err) => {
  console.error('E2E ERROR:', err)
  process.exit(1)
})