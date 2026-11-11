import { ReactNode } from 'react'
import { View } from '@tarojs/components'
import { IS_WEAPP } from '../config'
import { goBackOrHome } from '../utils/nav'
import { useSafeArea } from '../hooks/useSafeArea'
import Icon from './Icon'

interface PageHeaderProps {
  title?: ReactNode
  back?: boolean
  onBack?: () => void
  right?: ReactNode
  center?: boolean
}

export default function PageHeader({ title, back = false, onBack, right, center = false }: PageHeaderProps) {
  const { top, barHeight } = useSafeArea()

  const handleBack = () => {
    if (onBack) {
      onBack()
      return
    }
    goBackOrHome()
  }

  return (
    <View className='page-header' style={{ paddingTop: `${top}px` }}>
      <View
        className={`page-header-bar ${IS_WEAPP ? 'weapp' : ''}`}
        style={{ height: `${barHeight}px` }}
      >
        {back && (
          <View className='icon-btn' onClick={handleBack}>
            <Icon name='back-ink' size={18} />
          </View>
        )}
        <View className={`page-header-title ${center ? 'center' : ''}`}>{title}</View>
        {right ? <View className='page-header-right'>{right}</View> : null}
      </View>
    </View>
  )
}