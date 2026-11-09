import { View } from '@tarojs/components'

interface ProgressBarProps {
  value: number
  max?: number
  tone?: 'moss' | 'amber'
  size?: 'md' | 'sm'
  className?: string
}

export default function ProgressBar({
  value,
  max = 100,
  tone = 'moss',
  size = 'md',
  className = ''
}: ProgressBarProps) {
  const pct = max > 0 ? Math.max(0, Math.min(100, Math.round((value / max) * 100))) : 0
  return (
    <View className={`progress ${tone === 'amber' ? 'progress-amber' : ''} ${size === 'sm' ? 'progress-sm' : ''} ${className}`}>
      <View className='progress-fill' style={{ width: `${pct}%` }} />
    </View>
  )
}