import { useState } from 'react'
import { View, Text, Textarea } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import { createSession, pushRecentSession } from '../../services/api'
import type { Level, QuestionType } from '../../types'
import { ALL_TYPES, LEVEL_META, TYPE_META } from '../../types'
import { safeDecode } from '../../utils/format'
import './index.css'

const EXAMPLES = [
  'React Hooks 依赖数组',
  '期权定价的直觉',
  '细胞呼吸三阶段',
  '唐诗格律里的平仄'
]

const COUNTS = [3, 5, 8]

export default function CreatePage() {
  const router = useRouter()
  const preset = router.params?.topic ? safeDecode(router.params.topic) : ''
  const [topic, setTopic] = useState(preset.slice(0, 200))
  const [level, setLevel] = useState<Level>('basic')
  const [count, setCount] = useState(5)
  const [types, setTypes] = useState<QuestionType[]>(ALL_TYPES)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

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

  const handleGenerate = async () => {
    const value = topic.trim()
    if (value.length < 2) {
      setError('先写下想学的知识点，至少 2 个字')
      return
    }
    if (value.length > 200) {
      setError('主题请控制在 200 字以内')
      return
    }
    if (types.length === 0) {
      setError('至少选择一种题型')
      return
    }
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      const session = await createSession({
        topic: value,
        level,
        question_count: count,
        types,
        kind: 'standard'
      })
      pushRecentSession({
        id: session.id,
        chapterId: session.chapter_id || undefined,
        topic: value,
        level,
        status: session.status,
        createdAt: Date.now()
      })
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${session.id}` })
    } catch (err) {
      setError((err as Error).message || '创建失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageShell>
      <PageHeader back title='造一条新路' />
      <View className='create-body'>
        <View className='create-head'>
          <View className='create-eyebrow'>AI CREATE</View>
          <View className='create-title'>造一条新的路</View>
          <View className='create-sub'>输入一个具体的知识点，AI 会先检索资料，再出题。</View>
        </View>

        <View className={`create-card ${error ? 'has-error' : ''}`}>
          <Text className='create-label'>我想学</Text>
          <Textarea
            className='create-textarea'
            value={topic}
            maxlength={200}
            placeholder='越具体越好，例如「HTTP 强缓存与协商缓存的区别」'
            placeholderClass='create-placeholder'
            onInput={(e) => {
              setTopic(e.detail.value.slice(0, 200))
              if (error) setError('')
            }}
          />
          <View className='create-count-row'>
            <Text className='create-hint'>一个知识点，比一个学科名更好出题</Text>
            <Text className={`create-count ${topic.length > 200 ? 'over' : ''}`}>{topic.length}/200</Text>
          </View>
          {error ? <Text className='create-error'>{error}</Text> : null}
          <View className='create-examples'>
            {EXAMPLES.map((item) => (
              <View key={item} className='chip chip-sm' onClick={() => {
                setTopic(item)
                if (error) setError('')
              }}>
                {item}
              </View>
            ))}
          </View>
        </View>

        <View className='create-section'>
          <Text className='create-label'>难度</Text>
          <View className='chip-row'>
            {(Object.keys(LEVEL_META) as Level[]).map((key) => (
              <View
                key={key}
                className={`chip ${level === key ? 'chip-active' : ''}`}
                onClick={() => setLevel(key)}
              >
                {LEVEL_META[key].label}
              </View>
            ))}
          </View>
          <Text className='create-level-desc'>{LEVEL_META[level].desc}</Text>
        </View>

        <View className='create-section'>
          <Text className='create-label'>题量</Text>
          <View className='chip-row'>
            {COUNTS.map((n) => (
              <View
                key={n}
                className={`chip ${count === n ? 'chip-active' : ''}`}
                onClick={() => setCount(n)}
              >
                {n} 题
              </View>
            ))}
          </View>
        </View>

        <View className='create-section'>
          <Text className='create-label'>题型</Text>
          <View className='chip-row'>
            {ALL_TYPES.map((key) => (
              <View
                key={key}
                className={`chip ${types.includes(key) ? 'chip-active' : ''}`}
                onClick={() => toggleType(key)}
              >
                {TYPE_META[key].short}
              </View>
            ))}
          </View>
        </View>

        <View className='trust-note create-trust'>
          <Icon name='clock-ink3' size={16} />
          <Text>预计 20–40 秒 · 会标注来源 · 生成后可先预览再开始</Text>
        </View>

        <View className='create-bottom-space' />
      </View>

      <View className='create-footer'>
        <View
          className={`btn btn-primary btn-block ${submitting ? 'btn-disabled' : ''}`}
          onClick={handleGenerate}
        >
          {submitting ? '正在创建…' : '生成关卡'}
        </View>
      </View>
    </PageShell>
  )
}