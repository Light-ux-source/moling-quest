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


async function runKbFlow(page) {
  await page.goto(WEB + '/#/pages/kb/index', { waitUntil: 'networkidle' })
  await page.waitForSelector('.kb-title', { timeout: 20000 })
  await page.waitForTimeout(700)
  await layoutReport(page, 'kb-list')
  await page.locator('.page-shell:visible').last().screenshot({
    path: path.join(OUT, 'e2e-kb-list.png'),
    animations: 'disabled',
    timeout: 30000
  })

  const name = `E2E 资料库 ${Date.now()}`
  const newChip = page.getByText('新建', { exact: true }).first()
  if (await newChip.count()) {
    await newChip.click()
  } else {
    await page.getByText('建第一个资料库', { exact: true }).click()
  }
  await page.waitForSelector('.kb-create-panel', { timeout: 10000 })
  await page.locator('.kb-create-panel input').first().fill(name)
  await page.getByText('创建', { exact: true }).click()
  await page.waitForURL(/pages\/kb-detail\/index/, { timeout: 20000 })
  await page.waitForSelector('.kb-action', { timeout: 20000 })

  const sample = path.join(os.tmpdir(), 'lwa-kb-e2e.txt')
  fs.writeFileSync(
    sample,
    [
      '公司内部缓存规范 v3',
      '强缓存默认 TTL 为 600 秒，仅允许用于静态资源；禁止对 /api 路径启用强缓存。',
      '协商缓存必须携带 ETag 或 Last-Modified；资源未变化时返回 304。',
      '缓存键必须包含租户 ID 与语言，避免跨租户串数据。',
      '发布新版本时，必须刷新 CDN 并递增静态资源文件名哈希。'
    ].join('\n\n'),
    'utf8'
  )
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.locator('.kb-action').first().click()
  ])
  await chooser.setFiles(sample)
  await page.waitForSelector('.kb-doc-status.ready', { timeout: 120000 })
  await page.waitForTimeout(800)
  const docReady = await page.locator('.kb-doc-status.ready').count()
  console.log('资料库文件已就绪:', docReady)
  await layoutReport(page, 'kb-detail')
  await page.locator('.page-shell:visible').last().screenshot({
    path: path.join(OUT, 'e2e-kb-detail.png'),
    animations: 'disabled',
    timeout: 30000
  })

  await page.goto(WEB + '/#/pages/create/index', { waitUntil: 'networkidle' })
  await page.waitForSelector('.create-title', { timeout: 20000 })
  await page.locator('textarea').first().fill('公司内部缓存规范')
  await page.locator('.chip', { hasText: '我的资料库' }).first().click()
  await page.waitForSelector('.kb-pick', { timeout: 15000 })
  const firstKb = page.locator('.kb-pick').first()
  const firstClass = (await firstKb.getAttribute('class')) || ''
  if (!firstClass.includes('active')) await firstKb.click()
  await page.getByText('生成关卡', { exact: true }).click()
  await page.waitForURL(/pages\/generating\/index/, { timeout: 30000 })
  await page.waitForURL(/pages\/preview\/index/, { timeout: 150000 })
  await page.waitForSelector('.preview-source.kb', { timeout: 30000 })
  const kbSourceCount = await page.locator('.preview-source.kb').count()
  const sourceKindText = await page.locator('.preview-source.kb').first().innerText()
  console.log('知识库来源:', kbSourceCount, '|', sourceKindText.replace(/\n/g, ' / ').slice(0, 100))
  await page.waitForTimeout(700)
  await layoutReport(page, 'kb-preview')
  await page.locator('.page-shell:visible').last().screenshot({
    path: path.join(OUT, 'e2e-kb-preview.png'),
    animations: 'disabled',
    timeout: 30000
  })

  // 清理：通过后端 API 删除本次资料库，避免 E2E 反复运行占满限额
  const stored = await page.evaluate(() => {
    const unwrap = (key) => {
      const raw = localStorage.getItem(key) || ''
      if (!raw) return ''
      try {
        const parsed = JSON.parse(raw)
        return typeof parsed?.data === 'string' ? parsed.data : raw
      } catch (err) {
        return raw
      }
    }
    return { token: unwrap('ml_auth_token'), clientId: unwrap('ml_client_id') }
  })
  // 从页面 URL 取不到 kbId 时，从资料库列表中按名称查找
  const cleanup = await page.evaluate(
    async ({ name, token, clientId }) => {
      const base = 'http://127.0.0.1:8000/api/v1'
      const headers = { 'X-Client-Id': clientId, Authorization: `Bearer ${token}` }
      const list = await fetch(`${base}/kb`, { headers }).then((r) => r.json())
      const target = (list.items || []).find((item) => item.name === name)
      if (!target) return false
      const res = await fetch(`${base}/kb/${target.id}`, { method: 'DELETE', headers })
      return res.status === 204
    },
    { name, token: stored.token, clientId: stored.clientId }
  )
  console.log('资料库清理:', cleanup)
  return { docReady, kbSourceCount }
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

  // 用户系统：游客 → 体验登录 → 个人中心 → 学习记录
  await page.getByText('我的', { exact: true }).click()
  await page.waitForURL(/pages\/profile\/index/, { timeout: 20000 })
  await page.waitForTimeout(900)
  const loginCta = page.getByText('去登录', { exact: true }).first()
  if (await loginCta.count()) {
    await loginCta.click()
    await page.waitForTimeout(600)
    const agree = page.getByText('我已阅读并同意', { exact: false }).first()
    if (await agree.count()) await agree.click()
    const devLogin = page.getByText('体验登录（开发）', { exact: true }).first()
    if (!(await devLogin.count())) throw new Error('体验登录入口不存在')
    await devLogin.click()
    await page.waitForTimeout(1600)
  }
  const profileText = await page.locator('body').innerText()
  if (!/今日|额度|学习记录/.test(profileText)) {
    throw new Error('个人中心未加载：' + profileText.slice(0, 120))
  }
  await layoutReport(page, 'profile')
  await page.screenshot({ path: path.join(OUT, 'e2e-profile.png'), animations: 'disabled', timeout: 30000 })

  await page.getByText('学习记录', { exact: true }).click()
  await page.waitForURL(/pages\/records\/index/, { timeout: 20000 })
  await page.waitForTimeout(900)
  await layoutReport(page, 'records')
  await page.screenshot({ path: path.join(OUT, 'e2e-records.png'), animations: 'disabled', timeout: 30000 })
  await page.goBack()
  await page.waitForTimeout(600)
  await page.getByText('闯关', { exact: true }).click()
  await page.waitForURL(/pages\/index\/index/, { timeout: 20000 })
  await page.waitForTimeout(700)

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

  // 学习记录应包含刚才完成的一组
  await page.goto(WEB + '/#/pages/records/index', { waitUntil: 'networkidle' })
  await page.waitForTimeout(900)
  const recordCards = await page.locator('.record-card').count()
  console.log('学习记录条数:', recordCards)
  if (recordCards < 1) {
    errors.push('登录后学习记录为空，游客数据可能未迁移')
  }

  // 知识库 RAG：新建资料库 → 上传文件 → 选库出题 → 预览显示知识库来源
  const kbFlow = await runKbFlow(page)
  if (kbFlow.docReady < 1 || kbFlow.kbSourceCount < 1) {
    errors.push('知识库流程未通过：资料未就绪或预览缺少知识库来源')
  }

  // 响应式：375 / 390 / 768 三档无横向溢出
  await page.setViewportSize({ width: 390, height: 812 })
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
    kbFlow.docReady >= 1 &&
    kbFlow.kbSourceCount >= 1 &&
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