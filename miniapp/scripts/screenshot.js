/**
 * 视觉验收脚本：起一个 ready 会话和一个已完成会话，截取三个核心页面。
 * 运行：node scripts/screenshot.js  （需先启动后端 8000 与静态服务 10087）
 */
const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright-core')

const API = process.env.API_BASE || 'http://127.0.0.1:8000'
const WEB = process.env.WEB_BASE || 'http://127.0.0.1:10087'
// 可选：指定本机 Chromium 路径；不指定则使用 Playwright 自带浏览器
const EXE = process.env.PW_CHROME
const OUT = path.join(__dirname, '..', '..', 'shots')

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function post(pathname, body) {
  const res = await fetch(`${API}${pathname}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
  if (!res.ok) throw new Error(`${pathname} -> ${res.status} ${await res.text()}`)
  return res.json()
}

async function getJson(pathname) {
  const res = await fetch(`${API}${pathname}`)
  return { ok: res.ok, status: res.status, body: res.ok ? await res.json() : null }
}

async function waitReady(id) {
  for (let i = 0; i < 60; i++) {
    const { body } = await getJson(`/api/v1/sessions/${id}`)
    if (body && body.status === 'ready') return body
    if (body && body.status === 'failed') throw new Error(body.error)
    await sleep(500)
  }
  throw new Error('等待题目生成超时')
}

async function waitReport(id) {
  for (let i = 0; i < 60; i++) {
    const res = await getJson(`/api/v1/sessions/${id}/report`)
    if (res.ok) return res.body
    await sleep(500)
  }
  throw new Error('等待报告超时')
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true })

  const ready = await post('/api/v1/sessions', {
    topic: 'HTTP 缓存机制：强缓存与协商缓存的区别',
    level: 'advanced',
    question_count: 5
  })
  const readyDetail = await waitReady(ready.id)
  console.log('ready session:', ready.id, readyDetail.questions.length, 'questions')

  const done = await post('/api/v1/sessions', {
    topic: 'React Hooks 的 useEffect 依赖数组',
    level: 'basic',
    question_count: 5
  })
  const doneDetail = await waitReady(done.id)
  const answers = doneDetail.questions.map((q) => ({
    question_id: q.id,
    answer:
      q.type === 'multiple_choice'
        ? ['A', 'B']
        : q.type === 'short_answer'
          ? '先说明定义，再描述机制分为三步，最后给出一个适用场景。'
          : 'A'
  }))
  await post(`/api/v1/sessions/${done.id}/answers`, { answers })
  const report = await waitReport(done.id)
  console.log('report:', report.score, report.level_tag)

  const browser = await chromium.launch({
    ...(EXE && fs.existsSync(EXE) ? { executablePath: EXE } : {}),
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
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.log('[h5 console]', msg.text())
  })

  await page.goto(WEB, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1000)
  await page.screenshot({ path: path.join(OUT, 'index.png') })
  console.log('index.png saved')

  await page.goto(`${WEB}/pages/quiz/index?sessionId=${ready.id}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(OUT, 'quiz.png') })
  console.log('quiz.png saved')

  await page.goto(`${WEB}/pages/report/index?sessionId=${done.id}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: path.join(OUT, 'report.png'), fullPage: true })
  console.log('report.png saved')

  await browser.close()
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})