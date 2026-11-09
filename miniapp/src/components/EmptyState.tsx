import { View } from '@tarojs/components'
import Mascot from './Mascot'

interface EmptyStateProps {
  title: string
  text?: string
  actionLabel?: string
  onAction?: () => void
  pose?: 'idle' | 'thinking'
}

export default function EmptyState({ title, text, actionLabel, onAction, pose = 'idle' }: EmptyStateProps) {
  return (
    <View className='empty-state'>
      <Mascot pose={pose} className='mascot-empty' float />
      <View className='empty-title'>{title}</View>
      {text ? <View className='empty-text'>{text}</View> : null}
      {actionLabel && onAction ? (
        <View className='btn btn-primary btn-block' onClick={onAction}>
          {actionLabel}
        </View>
      ) : null}
    </View>
  )
}