import { useCallback, useEffect, useRef, useState } from 'react'
import { View, Text, Textarea } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import LoginSheet from '../../components/LoginSheet'
import { createSession, getKnowledgeBases, pushRecentSession } from '../../services/api'
import type { KbSummary, Level, QuestionType } from '../../types'
import { ALL_TYPES, LEVEL_META, TYPE_META } from '../../types'
import { safeDecode } from '../../utils/format'
import { errorMessage, handleCreateError } from '../../utils/quota'
import './index.css'

const EXAMPLES = [
  'React Hooks 依赖数组',
  '期权定价的直觉',
  '细胞呼吸三阶段',
  '唐诗格律里的平仄'
]

const COUNTS = [3, 5, 10, 15]

export default function CreatePage() {
  const router = useRouter()
  const preset = router.params?.topic ? safeDecode(router.params.topic) : ''
  const [topic, setTopic] = useState(preset.slice(0, 200))
  const [level, setLevel] = useState<Level>('basic')
  const [count, setCount] = useState(5)
  const [types, setTypes] = useState<QuestionType[]>(ALL_TYPES)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [loginOpen, setLoginOpen] = useState(false)
  const [kbList, setKbList] = useState<KbSummary[]>([])
  const [kbIds, setKbIds] = useState<string[]>([])
  const [sourceMode, setSourceMode] = useState<'kb_only' | 'hybrid'>('kb_only')
  const [kbLoading, setKbLoading] = useState(true)
  const submittingRef = useRef(false)

  const loadKbs = useCallback(async () => {
    try {
      const data = await getKnowledgeBases()
      setKbList(data.items || [])
    } catch (err) {
      console.warn('资料库加载失败', err)
    } finally {
      setKbLoading(false)
    }
  }, [])

  useEffect(() => {
    loadKbs()
  }, [loadKbs])

  useDidShow(() => {
    loadKbs()
  })

  const toggleKb = (id: string) => {
    setKbIds((prev) => {
      if (prev.includes(id)) return prev.filter((item) => item !== id)
      if (prev.length >= 3) {
        Taro.showToast({ title: '一次最多选 3 个资料库', icon: 'none' })
        return prev
      }
      return [...prev, id]
    })
  }

  const enableKb = () => {
    if (kbLoading) return
    if (!kbList.length) {
      Taro.navigateTo({ url: '/pages/kb/index' })
      return
    }
    if (!kbIds.length) setKbIds([kbList[0].id])
  }

  const disableKb = () => {
    setKbIds([])
    setSourceMode('kb_only')
  }

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
    if (submittingRef.current) return
    submittingRef.current = true
    setError('')
    setSubmitting(true)
    try {
      const session = await createSession({
        topic: value,
        level,
        question_count: count,
        types,
        kind: 'standard',
        kb_ids: kbIds,
        source_mode: kbIds.length ? sourceMode : 'model'
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
      if (await handleCreateError(err, () => setLoginOpen(true))) {
        setError('')
      } else {
        setError(errorMessage(err, '创建失败，请重试'))
      }
    } finally {
      submittingRef.current = false
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
          <Text className='create-label'>出题资料</Text>
          <View className='chip-row'>
            <View className={`chip ${kbIds.length === 0 ? 'chip-active' : ''}`} onClick={disableKb}>
              模型知识
            </View>
            <View className={`chip ${kbIds.length > 0 ? 'chip-active' : ''}`} onClick={enableKb}>
              我的资料库
            </View>
          </View>

          {kbIds.length > 0 ? (
            <>
              <View className='kb-pick-list'>
                {kbList.map((kb) => (
                  <View
                    key={kb.id}
                    className={`kb-pick ${kbIds.includes(kb.id) ? 'active' : ''}`}
                    onClick={() => toggleKb(kb.id)}
                  >
                    <View className='grow'>
                      <Text className='kb-pick-name'>{kb.name}</Text>
                      <Text className='kb-pick-meta'>
                        {kb.doc_count} 份资料 · {kb.chunk_count} 个片段
                      </Text>
                    </View>
                    <View className={`kb-pick-check ${kbIds.includes(kb.id) ? 'on' : ''}`}>
                      {kbIds.includes(kb.id) ? <Icon name='check-moss' size={16} /> : null}
                    </View>
                  </View>
                ))}
              </View>
              <View className='chip-row kb-mode-row'>
                <View
                  className={`chip chip-sm ${sourceMode === 'kb_only' ? 'chip-active' : ''}`}
                  onClick={() => setSourceMode('kb_only')}
                >
                  仅资料库
                </View>
                <View
                  className={`chip chip-sm ${sourceMode === 'hybrid' ? 'chip-active' : ''}`}
                  onClick={() => setSourceMode('hybrid')}
                >
                  资料库 + 联网
                </View>
              </View>
              <Text className='create-level-desc'>
                默认只依据资料库，来源可追溯；需要最新信息时再开联网。
              </Text>
            </>
          ) : (
            <View className='kb-entry-hint' onClick={() => Taro.navigateTo({ url: '/pages/kb/index' })}>
              <Icon name='tab-book-mossdeep' size={18} />
              <Text>上传培训资料 / 内部文档，建立自己的资料库 →</Text>
            </View>
          )}
          {kbLoading ? <Text className='create-hint'>正在读取资料库…</Text> : null}
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
          <Text>预计 20–60 秒 · 会标注来源 · 生成后可先预览再开始</Text>
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

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          Taro.showToast({ title: '登录成功，可以继续造关了', icon: 'success' })
        }}
        reason='已体验 1 组。登录后可继续造关，学习记录也会跟着账号走。'
      />
    </PageShell>
  )
}