/**
 * 环境配置
 * - 开发：H5 与小程序都指向本机 FastAPI（小程序需在开发者工具勾选「不校验合法域名」）
 * - 生产：构建时注入 TARO_APP_API_BASE=https://api.your-domain.com
 */
const FALLBACK_BASE = 'http://127.0.0.1:8000'
const injected = process.env.TARO_APP_API_BASE

export const API_BASE = (injected && injected.trim() ? injected : FALLBACK_BASE).replace(/\/+$/, '')

export const STORAGE_KEYS = {
  clientId: 'ml_client_id',
  recentSessions: 'ml_recent_sessions',
  drafts: 'ml_quiz_drafts',
  lastChapter: 'ml_last_chapter',
  authToken: 'ml_auth_token',
  authUser: 'ml_auth_user',
  agreedTerms: 'ml_agreed_terms'
} as const

export const POLL_INTERVAL = 1200
export const POLL_MAX_INTERVAL = 5000
export const POLL_TIMEOUT = 120000

export const IS_WEAPP = process.env.TARO_ENV === 'weapp'
export const IS_H5 = process.env.TARO_ENV === 'h5'