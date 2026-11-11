import { useEffect, useRef, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import LoadingOrb from '../../components/LoadingOrb'
import ErrorCard from '../../components/ErrorCard'
import { getSession, regenerateSession } from '../../services/api'
import type { SessionDetail } from '../../types'
import { TYPE_META } from '../../types'
import { estimateMinutes, topicShort } from '../../utils/format'
import { goToMap } from '../../utils/nav'
import './index.css'

export default function PreviewPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [regenerating, setRegenerating] = useState(false)
  const alive = useRef(true)
  const regeneratingRef = useRef(false)

  useEffect(() => {
    alive.current = true
    const load = async () => {
      if (!sessionId) {
        setError('缺少学习会话')
        setLoading(false)
        return
      }
      try {
        const detail = await getSession(sessionId)
        if (!alive.current) return
        if (['queued', 'searching', 'digesting', 'generating'].includes(detail.status)) {
          Taro.redirectTo({ url: `/pages/generating/index?sessionId=${sessionId}` })
          return
        }
        if (detail.status === 'completed' || detail.status === 'grading' || detail.status === 'reporting') {
          Taro.redirectTo({ url: `/pages/result/index?sessionId=${sessionId}` })
          return
        }
        if (detail.status === 'failed') {
          setError(detail.error || '生成失败，请重试')
          setLoading(false)
          return
        }
        setSession(detail)
        setError('')
      } catch (err) {
        if (alive.current) setError((err as Error).message || '预览加载失败')
      } finally {
        if (alive.current) setLoading(false)
      }
    }
    load()
    return () => {
      alive.current = false
    }
  }, [sessionId])

  const copySource = (url: string) => {
    if (!url) return
    Taro.setClipboardData({ data: url }).then(() => {
      Taro.showToast({ title: '链接已复制', icon: 'none' })
    })
  }

  const regenerate = async () => {
    if (!session || regeneratingRef.current) return
    regeneratingRef.current = true
    try {
      const modal = await Taro.showModal({
        title: '重新生成这一章？',
        content: '会重新检索并出题，预计 20–40 秒；不会额外消耗造关额度。',
        confirmText: '重新生成',
        cancelText: '再想想'
      })
      if (!modal.confirm) return
      setRegenerating(true)
      await regenerateSession(session.id)
      Taro.redirectTo({ url: `/pages/generating/index?sessionId=${session.id}` })
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '生成失败，请重试', icon: 'none' })
    } finally {
      regeneratingRef.current = false
      setRegenerating(false)
    }
  }

  const start = () => {
    if (!session) return
    Taro.redirectTo({ url: `/pages/quiz/index?sessionId=${session.id}&startSeq=1` })
  }

  const backToMap = () => {
    goToMap(session?.chapter_id)
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader back title='关卡预览' onBack={backToMap} />
        <LoadingOrb title='正在展开初稿' subtitle='AI 正在把资料排成一条路' />
      </PageShell>
    )
  }

  if (error || !session) {
    return (
      <PageShell>
        <PageHeader back title='关卡预览' onBack={backToMap} />
        <ErrorCard
          title='初稿没展开'
          message={error || '数据不存在'}
          retryLabel='重新加载'
          onRetry={() => Taro.redirectTo({ url: `/pages/preview/index?sessionId=${sessionId}` })}
          backLabel='回首页'
          onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </PageShell>
    )
  }

  const questions = session.questions || []
  const sources = session.sources || []
  const levelLabel = session.level === 'basic' ? '入门' : session.level === 'advanced' ? '进阶' : '挑战'

  return (
    <PageShell>
      <PageHeader
        back
        title='关卡预览'
        onBack={backToMap}
        right={<View className='chip chip-active'>AI 初稿</View>}
      />
      <View className='preview-body'>
        <View className='preview-hero'>
          <View className='preview-eyebrow'>
            新章节 · {questions.length} 关 · {levelLabel}
          </View>
          <View className='preview-title'>{topicShort(session.topic, 20)}</View>
          <View className='preview-meta'>
            <View className='preview-meta-chip'>
              <Icon name='leaf-paper' size={16} />
              {sources.length} 个来源
            </View>
            <View className='preview-meta-chip'>
              <Icon name='list-paper' size={16} />
              {questions.length} 题
            </View>
            <View className='preview-meta-chip'>
              <Icon name='clock-paper' size={16} />
              约 {estimateMinutes(questions.length)} 分钟
            </View>
          </View>
        </View>

        <View className='section-row'>
          <Text className='section-title'>关卡内容</Text>
          <Text className='more'>第 1 / {questions.length} 关</Text>
        </View>
        <View className='preview-list'>
          {questions.map((question) => (
            <View key={question.id} className='preview-item'>
              <View className='preview-item-main'>
                <Text className='preview-item-title'>
                  {question.seq}. {question.title || topicShort(question.stem, 14)}
                </Text>
                <Text className='preview-item-stem'>{question.stem}</Text>
              </View>
              <View className='chip chip-sm'>{TYPE_META[question.type].short}</View>
            </View>
          ))}
        </View>

        {questions.length < session.question_count && (
          <View className='preview-note'>
            生成了 {questions.length} 题（请求 {session.question_count} 题），校验时丢弃了部分不合规题目。
          </View>
        )}

        {sources.length > 0 ? (
          <View className='preview-sources'>
            <View className='section-row'>
              <Text className='section-title'>来源</Text>
              <Text className='more'>点击复制链接</Text>
            </View>
            {sources.map((source, index) => (
              <View key={`${source.title}-${index}`} className='preview-source' onClick={() => copySource(source.url)}>
                <View className='grow'>
                  <Text className='preview-source-title'>{source.title || '未命名来源'}</Text>
                  <Text className='preview-source-site'>{source.site_name || '未知站点'}</Text>
                </View>
                <Icon name='copy-ink3' size={16} />
              </View>
            ))}
          </View>
        ) : (
          <View className='preview-note'>本次未联网检索到可用来源，题目基于模型知识生成。</View>
        )}

        <View className='preview-disclaimer'>内容由 AI 生成，仅供学习参考。可以先预览，再开始闯关。</View>
        <View className='preview-bottom-space' />
      </View>

      <View className='preview-footer'>
        <View className='preview-actions'>
          <View
            className={`btn btn-ghost preview-action ${regenerating ? 'btn-disabled' : ''}`}
            onClick={regenerate}
          >
            {regenerating ? '正在重生成…' : '重新生成'}
          </View>
          <View className='btn btn-primary preview-action preview-action-main' onClick={start}>
            开始闯关
          </View>
        </View>
      </View>
    </PageShell>
  )
}