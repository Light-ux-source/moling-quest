import Taro from '@tarojs/taro'
import { API_BASE, POLL_INTERVAL, POLL_TIMEOUT, STORAGE_KEYS } from '../config'
import type { Level, Report, SessionDetail } from '../types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  data?: unknown
  timeout?: number
}

function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    Taro.request({
      url: `${API_BASE}${path}`,
      method: options.method || 'GET',
      data: options.data as Record<string, unknown> | undefined,
      timeout: options.timeout || 30000,
      header: { 'Content-Type': 'application/json' },
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
}

export function createSession(payload: CreateSessionPayload): Promise<SessionDetail> {
  return request<SessionDetail>('/api/v1/sessions', { method: 'POST', data: payload, timeout: 20000 })
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/api/v1/sessions/${sessionId}`)
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

export function health(): Promise<{ mode: string; model: string; web_search: boolean }> {
  return request('/api/v1/health')
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/**
 * 轮询会话状态，直到 ready / completed / failed。
 * 生成一组题通常 10~40s（真实模型），Mock 模式约 1s。
 */
export async function pollSession(
  sessionId: string,
  onUpdate?: (session: SessionDetail) => void,
  timeout = POLL_TIMEOUT
): Promise<SessionDetail> {
  const startedAt = Date.now()
  let lastError: Error | null = null
  while (Date.now() - startedAt < timeout) {
    try {
      const session = await getSession(sessionId)
      onUpdate?.(session)
      if (session.status === 'ready' || session.status === 'completed') {
        return session
      }
      if (session.status === 'failed') {
        throw new ApiError(500, session.error || '生成失败，请重试')
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        throw err
      }
      lastError = err as Error
    }
    await sleep(POLL_INTERVAL)
  }
  throw new ApiError(0, lastError ? `等待超时：${lastError.message}` : '等待超时，请稍后重试')
}

export interface RecentSession {
  id: string
  topic: string
  level: Level
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