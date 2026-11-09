import { View, Text } from '@tarojs/components'
import { SessionStatus } from '../types'
import './StageLoading.css'

const STEPS = [
  { key: 'searching', label: '联网检索资料', hint: '匹配权威来源与最新内容' },
  { key: 'digesting', label: '提炼知识要点', hint: '整理成可出题的知识提纲' },
  { key: 'generating', label: '生成个性化题目', hint: '按难度与题型配比组卷' }
]

const ORDER: Record<string, number> = {
  queued: 0,
  searching: 0,
  digesting: 1,
  generating: 2,
  ready: 3,
  completed: 3
}

interface Props {
  status: SessionStatus
  progress: number
  topic: string
  error?: string | null
  onRetry?: () => void
}

export default function StageLoading({ status, progress, topic, error, onRetry }: Props) {
  if (status === 'failed') {
    return (
      <View className='stage-wrap'>
        <View className='stage-icon stage-icon-error'>!</View>
        <View className='stage-title'>生成失败</View>
        <View className='stage-error'>{error || '服务开小差了，请稍后重试'}</View>
        {onRetry && (
          <View className='btn btn-primary stage-retry' onClick={onRetry}>
            重新生成
          </View>
        )}
      </View>
    )
  }

  const activeIndex = ORDER[status] ?? 0
  const percent = Math.max(4, Math.min(progress || 4, 99))

  return (
    <View className='stage-wrap'>
      <View className='stage-orb'>
        <View className='stage-orb-core'>AI</View>
        <View className='stage-orb-ring' />
      </View>
      <View className='stage-title'>正在为「{topic}」准备题目</View>
      <View className='stage-progress'>
        <View className='stage-progress-fill' style={{ width: `${percent}%` }} />
      </View>
      <View className='stage-steps'>
        {STEPS.map((step, index) => {
          const done = index < activeIndex
          const active = index === activeIndex
          return (
            <View key={step.key} className='stage-step'>
              <View
                className={`stage-dot ${done ? 'stage-dot-done' : ''} ${active ? 'stage-dot-active' : ''}`}
              >
                {done ? '✓' : index + 1}
              </View>
              <View className='stage-step-body'>
                <Text className={`stage-step-label ${done || active ? 'stage-step-label-on' : ''}`}>
                  {step.label}
                </Text>
                <Text className='stage-step-hint'>{step.hint}</Text>
              </View>
            </View>
          )
        })}
      </View>
      <View className='stage-tip'>通常 10～40 秒。可以先回忆一下：这个主题你已经知道什么？</View>
    </View>
  )
}