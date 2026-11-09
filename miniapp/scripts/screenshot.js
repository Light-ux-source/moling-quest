/**
 * 视觉验收截图：S01–S08，375×812，2x。
 * 运行：
 *   1) 后端 8000 已启动
 *   2) SQLITE_PATH=../backend/data/app.db ../backend/.venv/bin/python scripts/seed_demo.py --reset
 *   3) npm run build:h5 && python3 scripts/serve_h5.py dist-h5 10087
 *   4) node scripts/screenshot.js
 */
const fs = require('fs')
const os = require('os')
const path = require('path')
const { chromium } = require('playwright-core')

const WEB = process.env.WEB_BASE || 'http://127.0.0.1:10087'
const API = process.env.API_BASE || 'http://127.0.0.1:8000'
const OUT = path.join(__dirname, '..', '..', 'shots')
const SEED_FILE = path.join(__dirname, '..', '.demo-seed.json')

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

async function main() {
  if (!fs.existsSync(SEED_FILE)) {
    throw new Error(`缺少 ${SEED_FILE}，请先运行 scripts/seed_demo.py --reset`)
  }
  const seed = JSON.parse(fs.readFileSync(SEED_FILE, 'utf-8'))
  fs.mkdirSync(OUT, { recursive: true })

  const executablePath = resolveChrome()
  const browser = await chromium.launch({
    ...(executablePath ? { executablePath } : {}),
    args: ['--no-sandbox']
  })
  const context = await browser.newContext({
    viewport: { width: 375, height: 812 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    locale: 'zh-CN'
  })
  await context.addInitScript((cid) => {
    try {
      localStorage.setItem('ml_client_id', JSON.stringify({ data: cid }))
    } catch (err) {
      /* ignore */
    }
  }, seed.client_id)
  await context.route('https://fonts.googleapis.com/**', (route) => route.abort())
  await context.route('https://fonts.gstatic.com/**', (route) => route.abort())

  const page = await context.newPage()
  const errors = []
  page.on('console', (msg) => {
    const text = msg.text()
    if (msg.type() === 'error' && !text.includes('ERR_FAILED') && !text.includes('favicon')) {
      errors.push(text)
    }
  })
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`))

  const shot = async (name, fullPage = false) => {
    await page.screenshot({
      path: path.join(OUT, name),
      fullPage,
      animations: 'disabled',
      timeout: 30000
    })
    console.log('saved', name)
  }

  await page.goto(WEB, { waitUntil: 'load', timeout: 60000 })
  await page.waitForSelector('.chapter-mini', { timeout: 30000 })
  await page.waitForTimeout(800)
  await shot('index.png')

  await page.goto(`${WEB}/#/pages/map/index?chapterId=${seed.ready_chapter}`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForSelector('.map-canvas', { timeout: 30000 })
  await page.waitForTimeout(800)
  await shot('map.png')

  await page.goto(`${WEB}/#/pages/quiz/index?sessionId=${seed.ready_session}&startSeq=3`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForSelector('.question-stem', { timeout: 30000 })
  await page.waitForTimeout(500)
  const option = page.locator('.option-card').first()
  if (await option.count()) await option.click()
  await page.waitForTimeout(300)
  await shot('quiz.png')

  await page.goto(`${WEB}/#/pages/preview/index?sessionId=${seed.ready_session}`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForSelector('.preview-title', { timeout: 30000 })
  await page.waitForTimeout(600)
  await shot('preview.png')

  await page.goto(`${WEB}/#/pages/result/index?sessionId=${seed.completed_session}`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForSelector('.result-title', { timeout: 60000 })
  await page.waitForTimeout(1200)
  await shot('result.png')

  await page.goto(`${WEB}/#/pages/report/index?sessionId=${seed.completed_session}`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForSelector('.report-title', { timeout: 60000 })
  await page.waitForTimeout(900)
  await shot('report.png')
  await page.locator('.page-shell').screenshot({
    path: path.join(OUT, 'report-full.png'),
    animations: 'disabled',
    timeout: 30000
  })
  console.log('saved report-full.png')

  await page.goto(`${WEB}/#/pages/create/index`, { waitUntil: 'load', timeout: 60000 })
  await page.waitForSelector('.create-title', { timeout: 30000 })
  await page.waitForTimeout(500)
  await shot('create.png')

  const res = await fetch(`${API}/api/v1/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Client-Id': seed.client_id },
    body: JSON.stringify({ topic: '期权定价的直觉', level: 'basic', question_count: 5 })
  })
  if (!res.ok) throw new Error(`创建生成中会话失败: ${res.status}`)
  const created = await res.json()
  await page.goto(`${WEB}/#/pages/generating/index?sessionId=${created.id}`, {
    waitUntil: 'load',
    timeout: 60000
  })
  await page.waitForTimeout(250)
  await shot('generating.png')

  console.log('console errors:', errors.length ? errors.slice(0, 5) : 'none')
  await browser.close()
}

main().catch((err) => {
  console.error('SCREENSHOT ERROR:', err)
  process.exit(1)
})