import Taro from '@tarojs/taro'
import { goHome } from './nav'

function statusOf(err: unknown): number | undefined {
  const status = (err as { status?: unknown })?.status
  return typeof status === 'number' ? status : undefined
}

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'string' && err.trim()) return err
  return fallback
}

/** 429 且文案是额度/试用相关，而不是 IP 限流。 */
export function isQuotaExhaustedError(err: unknown): boolean {
  if (statusOf(err) !== 429) return false
  const message = errorMessage(err, '')
  return /用完|已体验|登录后可继续|额度/.test(message)
}

/** 游客试用额度用完：应引导登录，而不是只提示“明天再来”。 */
export function isGuestQuotaError(err: unknown): boolean {
  if (!isQuotaExhaustedError(err)) return false
  return /登录后可继续|已体验/.test(errorMessage(err, ''))
}

export function isAuthExpiredError(err: unknown): boolean {
  return statusOf(err) === 401
}

/** 登录用户的每日额度用尽：给出明确恢复时间，并提供回首页的逃生出口。 */
export async function showQuotaExhausted(message: string): Promise<void> {
  const content = `${message || '今天的 3 组已经用完，明天 00:00 恢复。'}\n\n要回首页复习一下吗？`
  let confirmed = false
  try {
    const result = await Taro.showModal({
      title: '今日额度已用完',
      content,
      confirmText: '回首页',
      cancelText: '留在这里',
      confirmColor: '#3E6650'
    })
    confirmed = !!result.confirm
  } catch (err) {
    confirmed = false
  }
  if (confirmed) goHome()
}

/**
 * 统一处理“创建新一组”失败：
 * - 401：登录态失效，打开登录弹层；
 * - 游客试用用完：打开登录弹层；
 * - 登录用户额度用完：额度弹窗 + 回首页；
 * - 其它：返回 false，由页面自行 toast/内联提示。
 */
export async function handleCreateError(
  err: unknown,
  openLogin: () => void
): Promise<boolean> {
  if (isAuthExpiredError(err)) {
    openLogin()
    return true
  }
  if (isGuestQuotaError(err)) {
    openLogin()
    return true
  }
  if (isQuotaExhaustedError(err)) {
    await showQuotaExhausted(errorMessage(err, '今日额度已用完'))
    return true
  }
  return false
}