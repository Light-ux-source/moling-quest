import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import Icon from './Icon'

export type TabKey = 'home' | 'explore' | 'mistakes' | 'profile'

interface TabBarProps {
  active?: TabKey
}

const ITEMS: Array<{ key: TabKey; label: string; icon: string; disabled?: boolean }> = [
  { key: 'home', label: '闯关', icon: 'tab-home' },
  { key: 'explore', label: '探索', icon: 'tab-compass' },
  { key: 'mistakes', label: '错题', icon: 'tab-book', disabled: true },
  { key: 'profile', label: '我的', icon: 'tab-user' }
]

export default function TabBar({ active = 'home' }: TabBarProps) {
  const go = (key: TabKey, disabled?: boolean) => {
    if (disabled) {
      Taro.showToast({ title: '错题本即将开放', icon: 'none' })
      return
    }
    if (key === active) return
    if (key === 'home') {
      Taro.reLaunch({ url: '/pages/index/index' })
      return
    }
    if (key === 'explore') {
      Taro.navigateTo({ url: '/pages/create/index' })
      return
    }
    if (key === 'profile') {
      Taro.reLaunch({ url: '/pages/profile/index' })
    }
  }

  return (
    <View className='tabbar'>
      {ITEMS.map((item) => {
        const isActive = item.key === active
        return (
          <View
            key={item.key}
            className={`tabbar-item ${isActive ? 'active' : ''} ${item.disabled ? 'disabled' : ''}`}
            onClick={() => go(item.key, item.disabled)}
          >
            <Icon
              name={`${item.icon}-${isActive ? 'mossdeep' : 'ink3'}`}
              size={20}
            />
            <Text>{item.label}</Text>
          </View>
        )
      })}
    </View>
  )
}
