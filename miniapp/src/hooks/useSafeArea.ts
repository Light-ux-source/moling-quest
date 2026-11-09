import { useEffect, useState } from 'react'
import Taro from '@tarojs/taro'
import { IS_WEAPP } from '../config'

interface SafeArea {
  top: number
  barHeight: number
}

/** 微信端读取状态栏与胶囊位置；H5 端不伪造状态栏。 */
export function useSafeArea(): SafeArea {
  const [area, setArea] = useState<SafeArea>({ top: 0, barHeight: 44 })

  useEffect(() => {
    if (!IS_WEAPP) return
    try {
      const info = Taro.getWindowInfo ? Taro.getWindowInfo() : Taro.getSystemInfoSync()
      const status = Number(info.statusBarHeight || 0)
      const menu = Taro.getMenuButtonBoundingClientRect
        ? Taro.getMenuButtonBoundingClientRect()
        : null
      const barHeight = menu
        ? Math.max(44, (menu.top - status) * 2 + menu.height)
        : 44
      setArea({ top: status, barHeight })
    } catch (err) {
      console.warn('读取安全区失败', err)
    }
  }, [])

  return area
}