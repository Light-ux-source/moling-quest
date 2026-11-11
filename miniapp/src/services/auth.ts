import Taro from '@tarojs/taro'
import { IS_WEAPP } from '../config'
import {
  clearAuthSession,
  getMe,
  getStoredUser,
  loginDev,
  loginWechat,
  logout as apiLogout,
  setAuthSession
} from './api'
import type { User } from '../types'

/** 微信一键登录：小程序端拿 code，交给后端换 openid。 */
export async function signInWithWechat(): Promise<User> {
  if (!IS_WEAPP) {
    throw new Error('当前环境不支持微信登录，请使用体验登录')
  }
  const result = await Taro.login()
  if (!result?.code) {
    throw new Error('微信登录没有返回凭证，请重试')
  }
  const data = await loginWechat(result.code)
  setAuthSession(data.token, data.user)
  return data.user
}

/** 本地体验登录：仅开发/验收环境使用，生产由后端关闭。 */
export async function signInDev(nickname?: string): Promise<User> {
  const data = await loginDev(nickname)
  setAuthSession(data.token, data.user)
  return data.user
}

export async function signOut(): Promise<void> {
  try {
    await apiLogout()
  } catch (err) {
    console.warn('退出登录接口失败，仍清理本地登录态', err)
  } finally {
    clearAuthSession()
  }
}

/** 校验本地登录态；失效时清理并返回 null。 */
export async function restoreSession(): Promise<User | null> {
  if (!getStoredUser()) return null
  try {
    const me = await getMe()
    if (me.authenticated && me.user) return me.user
    clearAuthSession()
    return null
  } catch (err) {
    return null
  }
}
