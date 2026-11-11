import { useEffect, useRef, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import Mascot from '../../components/Mascot'
import ProgressBar from '../../components/ProgressBar'
import ErrorCard from '../../components/ErrorCard'
import { getSession, pollSession, retrySession } from '../../services/api'
import type { SessionDetail } from '../../types'
import { topicShort } from '../../utils/format'
import { goBackOrHome } from '../../utils/nav'
import './index.css'

const STEP_TITLES = ['联网检索资料', '提炼知识要点', '生成个性化题目']

function stepStates(session: SessionDetail | null): Array<'done' | 'active' | 'pending'> {
  const status = session?.status || 'queued'
  if (status === 'ready' || status === 'completed') return ['done', 'done', 'done']
  if (status === 'generating') return ['done', 'done', 'active']
  if (status === 'digesting') return ['done', 'active', 'pending']
  return ['active', 'pending', 'pending']
}

export default function GeneratingPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [error, setError] = useState('')
  const [networkError, setNetworkError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [slow, setSlow] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [retrying, setRetrying] = useState(false)
  const alive = useRef(true)
  const cancelled = useRef(false)
  const startedAt = useRef(Date.now())

  useEffect(() => {
    alive.current = true
    cancelled.current = false
    startedAt.current = Date.now()
    setElapsed(0)
    setSlow(false)
    const timer = setInterval(() => {
      if (!alive.current) return
      const seconds = Math.round((Date.now() - startedAt.current) / 1000)
      setElapsed(seconds)
      if (seconds >= 45) setSlow(true)
    }, 1000)
    return () => {
      clearInterval(timer)
      alive.current = false
    }
  }, [attempt])

  useEffect(() => {
    if (!sessionId) {
      setError('缺少学习会话')
      return
    }
    let active = true
    const run = async () => {
      try {
        const first = await getSession(sessionId)
        if (!active) return
        setSession(first)
        if (first.status === 'ready') {
          Taro.redirectTo({ url: `/pages/preview/index?sessionId=${sessionId}` })
          return
        }
        if (first.status === 'completed') {
          Taro.redirectTo({ url: `/pages/result/index?sessionId=${sessionId}` })
          return
        }
        if (first.status === 'failed') {
          setError(first.error || '生成失败，请重试')
          return
        }
        const final = await pollSession(sessionId, {
          onUpdate: (value) => {
            if (!active || cancelled.current) return
            setSession(value)
            setNetworkError('')
          },
          onNetworkError: (message) => {
            if (active) setNetworkError(message)
          }
        })
        if (!active || cancelled.current) return
        if (final.status === 'ready') {
          Taro.redirectTo({ url: `/pages/preview/index?sessionId=${sessionId}` })
        } else if (final.status === 'completed') {
          Taro.redirectTo({ url: `/pages/result/index?sessionId=${sessionId}` })
        }
      } catch (err) {
        if (!active || cancelled.current) return
        setError((err as Error).message || '生成失败，请重试')
      }
    }
    run()
    return () => {
      active = false
    }
  }, [sessionId, attempt])

  const handleRetry = async () => {
    if (retrying) return
    setRetrying(true)
    setError('')
    try {
      await retrySession(sessionId)
      setAttempt((value) => value + 1)
    } catch (err) {
      setError((err as Error).message || '重试失败，请稍后')
    } finally {
      setRetrying(false)
    }
  }

  const cancel = () => {
    cancelled.current = true
    goBackOrHome()
  }

  const later = () => {
    cancelled.current = true
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  const changeTopic = () => {
    cancelled.current = true
    Taro.redirectTo({ url: '/pages/create/index' })
  }

  if (error && (session?.status === 'failed' || !session)) {
    return (
      <PageShell>
        <PageHeader back title='AI 生成中' onBack={() => Taro.reLaunch({ url: '/pages/index/index' })} />
        <ErrorCard
          title='这次没长出来'
          message={error}
          retryLabel={retrying ? '正在重试…' : '再试一次'}
          onRetry={handleRetry}
          backLabel='换个主题'
          onBack={changeTopic}
        />
      </PageShell>
    )
  }

  const states = stepStates(session)
  const progress = session?.progress || 4
  const sources = session?.sources?.length || 0
  const topic = session?.topic || '你的主题'

  return (
    <PageShell>
      <PageHeader back title='AI 生成中' onBack={cancel} />
      {networkError ? <View className='gen-network'>网络不稳定，正在重试…</View> : null}
      <View className='gen-body'>
        <View className='gen-orb'>
          <Mascot pose='thinking' className='mascot-orb gen-mascot' float />
        </View>
        <View className='gen-title'>正在为「{topicShort(topic, 12)}」准备题目</View>
        <View className='gen-sub'>通常 10–40 秒，可以先在脑子里过一遍知识点</View>

        <View className='gen-progress'>
          <ProgressBar value={progress} max={100} />
          <View className='gen-progress-row'>
            <Text className='gen-progress-label'>当前进度</Text>
            <Text className='gen-progress-num'>{progress}%</Text>
          </View>
        </View>

        <View className='gen-steps'>
          {STEP_TITLES.map((title, index) => {
            const state = states[index]
            const extra =
              index === 0
                ? sources > 0
                  ? `找到 ${sources} 条来源`
                  : state === 'done'
                    ? '未检索到来源，使用模型知识'
                    : '进行中'
                : state === 'done'
                  ? '已完成'
                  : state === 'active'
                    ? '进行中'
                    : '等待'
            return (
              <View key={title} className={`gen-step ${state}`}>
                <View className='gen-step-num'>
                  {state === 'done' ? <Icon name='check-paper' size={16} /> : <Text>{index + 1}</Text>}
                </View>
                <View className='grow'>
                  <Text className='gen-step-title'>{title}</Text>
                  <Text className='gen-step-desc'>{extra}</Text>
                </View>
              </View>
            )
          })}
        </View>

        <View className='gen-tip'>
          <View className='row gen-tip-head'>
            <Icon name='sparkle-amber' size={16} />
            <Text>小提示</Text>
          </View>
          <Text className='gen-tip-text'>
            {elapsed < 8
              ? '先别急着看答案，回忆一下你已经知道的定义和场景。'
              : '题目会覆盖定义、机制、应用和边界，答完会告诉你哪里还薄弱。'}
          </Text>
        </View>

        {slow && (
          <View className='gen-slow'>
            <Text className='gen-slow-title'>比平时久了一点</Text>
            <Text className='gen-slow-text'>可以继续等，也可以稍后回来，任务会在后台继续。</Text>
            <View className='gen-slow-actions'>
              <View className='btn btn-ghost btn-sm' onClick={later}>
                稍后回来
              </View>
              <View className='btn btn-primary btn-sm' onClick={() => setSlow(false)}>
                继续等
              </View>
            </View>
          </View>
        )}

        <View className='gen-bottom-space' />
      </View>

      <View className='gen-footer'>
        <View className='gen-elapsed'>已等待 {elapsed} 秒</View>
        <View className='btn btn-ghost btn-block' onClick={cancel}>
          取消生成
        </View>
      </View>
    </PageShell>
  )
}