/**
 * H5 端到端验收：真实点击走完「输入 → 出题 → 答题 → 提交 → 报告」。
 * 运行：node scripts/e2e.js
 */
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright-core')

const WEB = process.env.WEB_BASE || 'http://127.0.0.1:10087'
// 可选：PW_CHROME=/path/to/chrome，未设置时使用 Playwright 自带浏览器
const EXE = process.env.PW_CHROME
const OUT = path.join(__dirname, '..', '..', 'shots')

async function layoutReport(page, name) {
  const info = await page.evaluate(() => {
    const doc = document.documentElement
    const overflow = []
    document.querySelectorAll('*').forEach((el) => {
      const rect = el.getBoundingClientRect()
      if (rect.width > 0 && rect.right > doc.clientWidth + 2) {
        overflow.push(`${el.tagName}.${el.className}`.slice(0, 80))
      }
    })
    return {
      title: document.title,
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
  const browser = await chromium.launch({
    ...(EXE ? { executablePath: EXE } : {}),
    args: ['--no-sandbox']
  })
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: 'zh-CN'
  })
  const page = await context.newPage()
  const errors = []
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('404')) errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))

  await page.goto(WEB, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)

  const heroText = await page.locator('.hero-title').innerText()
  console.log('首页标题:', heroText.replace(/\n/g, ' '))

  const textarea = page.locator('textarea').first()
  await textarea.fill('HTTP 缓存机制：强缓存与协商缓存的区别')
  await page.waitForTimeout(300)
  await layoutReport(page, 'index')

  await page.getByText('开始出题', { exact: true }).click()
  await page.waitForURL(/pages\/quiz\/index/, { timeout: 60000 })
  console.log('已进入答题页')

  await page.waitForSelector('.q-stem', { timeout: 60000 })
  const stem = await page.locator('.q-stem').innerText()
  console.log('第 1 题:', stem.slice(0, 60))
  await layoutReport(page, 'quiz')

  // 逐题作答
  for (let i = 0; i < 10; i++) {
    const optionCount = await page.locator('.option-row').count()
    if (optionCount > 0) {
      await page.locator('.option-row').first().click()
    } else {
      const answerBox = page.locator('.answer-input textarea').first()
      if (await answerBox.count()) {
        await answerBox.fill('先说明定义，再描述机制分为三步，最后给出一个适用场景。')
      }
    }
    const nextLabel = await page.locator('.footer-btn-main').innerText()
    await page.locator('.footer-btn-main').click()
    if (nextLabel.includes('提交')) break
    await page.waitForTimeout(250)
  }

  await page.waitForURL(/pages\/report\/index/, { timeout: 60000 })
  await page.waitForSelector('.score-num', { timeout: 60000 })
  await page.waitForTimeout(1000)

  const score = (await page.locator('.score-num').innerText()).replace(/\n/g, ' ')
  const summary = await page.locator('.summary-text').innerText()
  const gaps = await page.locator('.gap-item').count()
  const reviews = await page.locator('.review-item').count()
  console.log('报告分数:', score)
  console.log('诊断摘要:', summary.slice(0, 80))
  console.log('知识缺口条数:', gaps, '逐题解析条数:', reviews)

  // 展开第一题解析，验证交互
  await page.locator('.review-item').first().click()
  await page.waitForTimeout(400)
  const detailVisible = await page.locator('.review-detail').count()
  console.log('展开解析块:', detailVisible)

  await layoutReport(page, 'report')
  await page.screenshot({ path: path.join(OUT, 'report-full.png'), fullPage: true })
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(300)
  await page.screenshot({ path: path.join(OUT, 'report.png') })

  console.log('console errors:', errors.length ? errors : 'none')
  const ok = reviews === 5 && detailVisible >= 1 && errors.length === 0
  console.log(ok ? 'E2E PASS' : 'E2E CHECK FAILED')
  await browser.close()
  if (!ok) process.exit(1)
}

main().catch((err) => {
  console.error('E2E ERROR:', err)
  process.exit(1)
})