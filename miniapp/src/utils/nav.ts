import Taro from '@tarojs/taro'

const HOME_URL = '/pages/index/index'

/** 任何页面都能安全回到首页；reLaunch 会清空页面栈，避免 10 层上限卡死。 */
export function goHome(): void {
  Taro.reLaunch({ url: HOME_URL }).catch(() => undefined)
}

/** 返回上一页；没有上一页时回首页。 */
export function goBackOrHome(): void {
  let pages: ReturnType<typeof Taro.getCurrentPages> = []
  try {
    pages = Taro.getCurrentPages()
  } catch (err) {
    goHome()
    return
  }
  if (pages.length > 1) {
    Taro.navigateBack({ delta: 1 }).catch(() => goHome())
    return
  }
  goHome()
}

/**
 * 进入学习报告：若栈内已有同一 session 的报告页，直接返回它；
 * 否则用 redirectTo 替换当前页，避免页面栈无限增长。
 */
export function goToReport(sessionId?: string | null): void {
  if (!sessionId) {
    goHome()
    return
  }
  const url = `/pages/report/index?sessionId=${sessionId}`
  let pages: ReturnType<typeof Taro.getCurrentPages> = []
  try {
    pages = Taro.getCurrentPages()
  } catch (err) {
    pages = []
  }

  for (let index = pages.length - 2; index >= 0; index -= 1) {
    const page = pages[index]
    const route = String(page.route || page.__route__ || '').replace(/^\//, '')
    if (route !== 'pages/report/index') continue
    const options = (page.options || page.params || {}) as Record<string, unknown>
    const pageSessionId = options.sessionId || options.session_id
    if (pageSessionId && String(pageSessionId) === String(sessionId)) {
      Taro.navigateBack({ delta: pages.length - 1 - index }).catch(() => {
        Taro.redirectTo({ url }).catch(() => goHome())
      })
      return
    }
  }

  Taro.redirectTo({ url }).catch(() => goHome())
}

/**
 * 进入章节地图：如果页面栈里已有同一章的地图，直接返回它，避免重复压栈；
 * 否则用 redirectTo 替换当前页，保持栈深度可控。
 */
export function goToMap(chapterId?: string | null): void {
  if (!chapterId) {
    goHome()
    return
  }
  const url = `/pages/map/index?chapterId=${chapterId}`
  let pages: ReturnType<typeof Taro.getCurrentPages> = []
  try {
    pages = Taro.getCurrentPages()
  } catch (err) {
    pages = []
  }

  for (let index = pages.length - 2; index >= 0; index -= 1) {
    const page = pages[index]
    const route = String(page.route || page.__route__ || '').replace(/^\//, '')
    if (route !== 'pages/map/index') continue
    const options = (page.options || page.params || {}) as Record<string, unknown>
    const pageChapterId = options.chapterId || options.chapter_id
    if (!pageChapterId || String(pageChapterId) === String(chapterId)) {
      Taro.navigateBack({ delta: pages.length - 1 - index }).catch(() => {
        Taro.redirectTo({ url }).catch(() => goHome())
      })
      return
    }
  }

  Taro.redirectTo({ url }).catch(() => goHome())
}