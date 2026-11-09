import { useEffect, useState } from 'react'
import { View, Text, Textarea } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { createSession, health, loadRecentSessions, pushRecentSession, RecentSession } from '../../services/api'
import { LEVEL_META, QuestionType, Level } from '../../types'
import './index.css'

const EXAMPLES = [
  'React Hooks 的 useEffect 依赖数组',
  '期权定价的 Black-Scholes 直觉',
  '细胞呼吸的三个阶段',
  '唐诗格律里的平仄规则'
]

const TYPE_OPTIONS: Array<{ key: QuestionType; label: string }> = [
  { key: 'single_choice', label: '单选' },
  { key: 'multiple_choice', label: '多选' },
  { key: 'true_false', label: '判断' },
  { key: 'short_answer', label: '简答' }
]

const COUNTS = [3, 5, 8]

export default function Index() {
  const router = useRouter()
  const [topic, setTopic] = useState('')
  const [level, setLevel] = useState<Level>('basic')
  const [count, setCount] = useState(5)
  const [types, setTypes] = useState<QuestionType[]>(['single_choice', 'multiple_choice', 'true_false', 'short_answer'])
  const [submitting, setSubmitting] = useState(false)
  const [recent, setRecent] = useState<RecentSession[]>([])
  const [mode, setMode] = useState<string>('')

  useEffect(() => {
    setRecent(loadRecentSessions())
    const preset = router.params?.topic
    if (preset) setTopic(decodeURIComponent(preset).slice(0, 200))
    health()
      .then((res) => setMode(res.mode))
      .catch(() => setMode('offline'))
  }, [])

  const toggleType = (key: QuestionType) => {
    setTypes((prev) => {
      if (prev.includes(key)) {
        if (prev.length === 1) {
          Taro.showToast({ title: '至少保留一种题型', icon: 'none' })
          return prev
        }
        return prev.filter((t) => t !== key)
      }
      return [...prev, key]
    })
  }

  const handleStart = async () => {
    const value = topic.trim()
    if (value.length < 2) {
      Taro.showToast({ title: '先输入想学习的知识点', icon: 'none' })
      return
    }
    if (submitting) return
    setSubmitting(true)
    Taro.showLoading({ title: '正在创建…', mask: true })
    try {
      const session = await createSession({
        topic: value,
        level,
        question_count: count,
        types
      })
      setRecent(pushRecentSession({ id: session.id, topic: value, level, createdAt: Date.now() }))
      Taro.hideLoading()
      Taro.navigateTo({
        url: `/pages/quiz/index?sessionId=${session.id}&topic=${encodeURIComponent(value)}`
      })
    } catch (err) {
      Taro.hideLoading()
      const message = (err as Error).message || '创建失败，请重试'
      Taro.showToast({ title: message, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  const openRecent = (item: RecentSession) => {
    Taro.navigateTo({
      url: `/pages/quiz/index?sessionId=${item.id}&topic=${encodeURIComponent(item.topic)}`
    })
  }

  return (
    <View className='page index-page'>
      <View className='hero'>
        <View className='hero-eyebrow'>AI LEARNING COACH</View>
        <View className='hero-title'>
          想学什么，
          <Text className='hero-accent'>AI 现场出题</Text>
        </View>
        <View className='hero-sub'>检索资料 · 生成题目 · 即时批改 · 输出学习报告</View>
        <View className='hero-badges'>
          <Text className='hero-badge'>联网检索</Text>
          <Text className='hero-badge'>多题型</Text>
          <Text className='hero-badge'>个性化报告</Text>
          {mode === 'mock' && <Text className='hero-badge hero-badge-warn'>Mock 演示模式</Text>}
        </View>
      </View>

      <View className='card topic-card'>
        <View className='card-label'>我想学</View>
        <Textarea
          className='topic-input'
          value={topic}
          maxlength={200}
          placeholder='输入一个具体的知识点，越具体效果越好'
          placeholderClass='topic-placeholder'
          onInput={(e) => setTopic(e.detail.value.slice(0, 200))}
        />
        <View className='row between topic-meta'>
          <Text className='muted'>例：不要写「英语」，写「虚拟语气在条件句中的三种时态」</Text>
          <Text className='muted topic-count'>{topic.length}/200</Text>
        </View>
        <View className='topic-examples'>
          {EXAMPLES.map((item) => (
            <View key={item} className='chip' onClick={() => setTopic(item)}>
              {item}
            </View>
          ))}
        </View>
      </View>

      <View className='card options-card'>
        <View className='section-title'>学习难度</View>
        <View className='level-row'>
          {(Object.keys(LEVEL_META) as Level[]).map((key) => (
            <View
              key={key}
              className={`level-item ${level === key ? 'level-item-active' : ''}`}
              onClick={() => setLevel(key)}
            >
              <Text className='level-label'>{LEVEL_META[key].label}</Text>
              <Text className='level-desc'>{LEVEL_META[key].desc}</Text>
            </View>
          ))}
        </View>

        <View className='section-title section-gap'>题目数量</View>
        <View className='count-row'>
          {COUNTS.map((n) => (
            <View
              key={n}
              className={`count-item ${count === n ? 'count-item-active' : ''}`}
              onClick={() => setCount(n)}
            >
              {n} 题
            </View>
          ))}
        </View>

        <View className='section-title section-gap'>题型</View>
        <View className='type-row'>
          {TYPE_OPTIONS.map((item) => (
            <View
              key={item.key}
              className={`chip ${types.includes(item.key) ? 'chip-active' : ''}`}
              onClick={() => toggleType(item.key)}
            >
              {item.label}
            </View>
          ))}
        </View>
      </View>

      <View className={`btn btn-primary start-btn ${submitting ? 'btn-disabled' : ''}`} onClick={handleStart}>
        {submitting ? '正在创建学习会话…' : '开始出题'}
      </View>
      <View className='start-tip'>AI 通常需要 10～40 秒检索并生成题目</View>

      {recent.length > 0 && (
        <View className='card recent-card'>
          <View className='row between'>
            <View className='section-title'>最近学习</View>
            <Text className='muted'>{recent.length} 组</Text>
          </View>
          {recent.map((item) => (
            <View key={item.id} className='recent-item' onClick={() => openRecent(item)}>
              <View className='recent-dot' />
              <View className='recent-body'>
                <View className='recent-topic'>{item.topic}</View>
                <View className='muted'>{LEVEL_META[item.level]?.label || item.level} · 继续查看</View>
              </View>
              <Text className='recent-arrow'>›</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  )
}