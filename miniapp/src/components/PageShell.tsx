import { PropsWithChildren } from 'react'
import { View } from '@tarojs/components'
import TabBar, { TabKey } from './TabBar'

interface PageShellProps extends PropsWithChildren {
  tabbar?: boolean
  activeTab?: TabKey
  className?: string
}

export default function PageShell({
  children,
  tabbar = false,
  activeTab = 'home',
  className = ''
}: PageShellProps) {
  return (
    <View className={`page-shell paper-noise ${tabbar ? 'page-with-tabbar' : ''} ${className}`}>
      {children}
      {tabbar && <TabBar active={activeTab} />}
    </View>
  )
}