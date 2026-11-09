import Taro from '@tarojs/taro'
import { API_BASE, POLL_INTERVAL, POLL_MAX_INTERVAL, POLL_TIMEOUT, STORAGE_KEYS } from '../config'
import type {
  ChapterDetail,
  ChapterKind,
  ChapterSummary,
  Level,
  Profile,
  Report,
  SessionDetail,
  Settlement
} from '../types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH'
  data?: unknown
  timeout?: number
}

let cachedClientId = ''

/** 匿名设备 ID：无登录时用它隔离章节/统计，换设备不同步。 */
export function getClientId(): string {
  if (cachedClientId) return cachedClientId
  try {
    const stored = Taro.getStorageSync(STORAGE_KEYS.clientId)
    if (typeof stored === 'string' && stored.trim()) {
      cachedClientId = stored.trim()
      return cachedClientId
    }
  } catch (err) {
    console.warn('读取 client_id 失败', err)
  }
  cachedClientId = `ml_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
  try {
    Taro.setStorageSync(STORAGE_KEYS.clientId, cachedClientId)
  } catch (err) {
    console.warn('保存 client_id 失败', err)
  }
  return cachedClientId
}

function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    Taro.request({
      url: `${API_BASE}${path}`,
      method: options.method || 'GET',
      data: options.data as Record<string, unknown> | undefined,
      timeout: options.timeout || 30000,
      header: {
        'Content-Type': 'application/json',
        'X-Client-Id': getClientId()
      },
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data as T)
          return
        }
        const detail =
          (res.data && typeof res.data === 'object' && 'detail' in res.data
            ? String((res.data as { detail?: string }).detail)
            : '') || `请求失败（${res.statusCode}）`
        reject(new ApiError(res.statusCode, detail))
      },
      fail(err) {
        reject(new ApiError(0, err?.errMsg || '网络连接失败，请确认后端服务已启动'))
      }
    })
  })
}

export interface CreateSessionPayload {
  topic: string
  level: Level
  question_count: number
  types: string[]
  kind?: ChapterKind
}

export function createSession(payload: CreateSessionPayload): Promise<SessionDetail> {
  return request<SessionDetail>('/api/v1/sessions', {
    method: 'POST',
    data: payload,
    timeout: 20000
  })
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/v1/sessions/${sessionId}`)
}

export function updateProgress(sessionId: string, currentSeq: number): Promise<{ current_seq: number }> {
  return request(`/api/v1/sessions/${sessionId}/progress`, {
    method: 'PATCH',
    data: { current_seq: currentSeq }
  })
}

export function submitAnswers(
  sessionId: string,
  answers: Array<{ question_id: string; answer: string | string[] }>
): Promise<{ status: string }> {
  return request(`/api/v1/sessions/${sessionId}/answers`, {
    method: 'POST',
    data: { answers },
    timeout: 20000
  })
}

export function fetchReport(sessionId: string): Promise<Report> {
  return request<Report>(`/api/v1/sessions/${sessionId}/report`)
}

export function fetchSettlement(sessionId: string): Promise<Settlement> {
  return request<Settlement>(`/api/v1/sessions/${sessionId}/settlement`)
}

export function retrySession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/v1/sessions/${sessionId}/retry`, { method: 'POST' })
}

export function getChapters(limit = 10): Promise<{ items: ChapterSummary[] }> {
  return request<{ items: ChapterSummary[] }>(`/api/v1/chapters?limit=${limit}`)
}

export function getChapter(chapterId: string): Promise<ChapterDetail> {
  return request<ChapterDetail>(`/api/v1/chapters/${chapterId}`)
}

export function createComprehensive(chapterId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/v1/chapters/${chapterId}/comprehensive`, { method: 'POST' })
}

export function getProfile(): Promise<Profile> {
  return request<Profile>('/api/v1/profile')
}

export function health(): Promise<{ mode: string; model: string; web_search: boolean }> {
  return request('/api/v1/health')
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

export interface PollOptions {
  onUpdate?: (session: SessionDetail) => void
  onNetworkError?: (message: string) => void
  timeout?: number
  /** 命中这些状态就返回；默认 ready / completed */
  stopAt?: SessionDetail['status'][]
}

/**
 * 轮询会话状态：1.2s 一次，失败指数退避（最长 5s），超时 120s。
 * 页面卸载时由调用方通过 alive 标记停止 setState，轮询本身会自然结束。
 */
export async function pollSession(sessionId: string, options: PollOptions = {}): Promise<SessionDetail> {
  const stopAt = options.stopAt || ['ready', 'completed']
  const startedAt = Date.now()
  const timeout = options.timeout || POLL_TIMEOUT
  let interval = POLL_INTERVAL
  let lastError: Error | null = null

  while (Date.now() - startedAt < timeout) {
    try {
      const session = await getSession(sessionId)
      options.onUpdate?.(session)
      if (stopAt.includes(session.status)) return session
      if (session.status === 'failed') {
        throw new ApiError(500, session.error || '生成失败，请重试')
      }
      interval = POLL_INTERVAL
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) throw err
      if (err instanceof ApiError && err.status === 500) throw err
      lastError = err as Error
      options.onNetworkError?.(lastError.message)
      interval = Math.min(POLL_MAX_INTERVAL, Math.round(interval * 1.6))
    }
    await sleep(interval)
  }
  throw new ApiError(0, lastError ? `等待超时：${lastError.message}` : '等待超时，请稍后重试')
}

/** 等待批改完成，再取报告；避免用 409 反复探测。 */
export async function waitForReport(
  sessionId: string,
  onUpdate?: (session: SessionDetail) => void
): Promise<Report> {
  const session = await pollSession(sessionId, { onUpdate, stopAt: ['completed'] })
  if (session.status !== 'completed') {
    throw new ApiError(409, '批改尚未完成，请稍候')
  }
  return fetchReport(sessionId)
}

export interface RecentSession {
  id: string
  chapterId?: string
  topic: string
  level: Level
  status?: string
  stars?: number
  createdAt: number
}

export function loadRecentSessions(): RecentSession[] {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEYS.recentSessions)
    if (Array.isArray(raw)) return raw as RecentSession[]
  } catch (err) {
    console.warn('读取最近学习记录失败', err)
  }
  return []
}

export function pushRecentSession(item: RecentSession): RecentSession[] {
  const list = loadRecentSessions().filter((s) => s.id !== item.id)
  const next = [item, ...list].slice(0, 6)
  try {
    Taro.setStorageSync(STORAGE_KEYS.recentSessions, next)
  } catch (err) {
    console.warn('保存最近学习记录失败', err)
  }
  return next
}

export interface QuizDraft {
  answers: Record<string, string | string[]>
  currentSeq: number
  updatedAt: number
}

type DraftMap = Record<string, QuizDraft>

function loadDraftMap(): DraftMap {
  try {
    const raw = Taro.getStorageSync(STORAGE_KEYS.drafts)
    if (raw && typeof raw === 'object') return raw as DraftMap
  } catch (err) {
    console.warn('读取答题草稿失败', err)
  }
  return {}
}

export function loadDraft(sessionId: string): QuizDraft | null {
  const map = loadDraftMap()
  return map[sessionId] || null
}

export function saveDraft(sessionId: string, draft: QuizDraft): void {
  const map = loadDraftMap()
  map[sessionId] = { ...draft, updatedAt: Date.now() }
  const keys = Object.keys(map)
    .sort((a, b) => (map[b].updatedAt || 0) - (map[a].updatedAt || 0))
    .slice(0, 6)
  const trimmed: DraftMap = {}
  keys.forEach((key) => {
    trimmed[key] = map[key]
  })
  try {
    Taro.setStorageSync(STORAGE_KEYS.drafts, trimmed)
  } catch (err) {
    console.warn('保存答题草稿失败', err)
  }
}

export function clearDraft(sessionId: string): void {
  const map = loadDraftMap()
  if (!map[sessionId]) return
  delete map[sessionId]
  try {
    Taro.setStorageSync(STORAGE_KEYS.drafts, map)
  } catch (err) {
    console.warn('清理答题草稿失败', err)
  }
}