import { View } from '@tarojs/components'

interface ErrorCardProps {
  title?: string
  message: string
  onRetry?: () => void
  retryLabel?: string
  onBack?: () => void
  backLabel?: string
}

export default function ErrorCard({
  title = '这次没长出来',
  message,
  onRetry,
  retryLabel = '再试一次',
  onBack,
  backLabel = '返回'
}: ErrorCardProps) {
  return (
    <View className='error-card'>
      <View className='error-title'>{title}</View>
      <View className='error-text'>{message}</View>
      <View className='error-actions'>
        {onBack ? (
          <View className='btn btn-ghost' onClick={onBack}>
            {backLabel}
          </View>
        ) : null}
        {onRetry ? (
          <View className='btn btn-primary' onClick={onRetry}>
            {retryLabel}
          </View>
        ) : null}
      </View>
    </View>
  )
}