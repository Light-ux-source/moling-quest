import { useEffect, useRef, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import StarRating from '../../components/StarRating'
import SealStamp from '../../components/SealStamp'
import ProgressBar from '../../components/ProgressBar'
import LoadingOrb from '../../components/LoadingOrb'
import ErrorCard from '../../components/ErrorCard'
import LoginSheet from '../../components/LoginSheet'
import {
  createSession,
  fetchSettlement,
  getChapter,
  getSession,
  pollSession
} from '../../services/api'
import type { ChapterDetail, SessionDetail, Settlement } from '../../types'
import { formatDuration, starText, topicShort } from '../../utils/format'
import { errorMessage, handleCreateError } from '../../utils/quota'
import { goToMap, goToReport } from '../../utils/nav'
import './index.css'

export default function ResultPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [chapter, setChapter] = useState<ChapterDetail | null>(null)
  const [settlement, setSettlement] = useState<Settlement | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [litStars, setLitStars] = useState(0)
  const [creating, setCreating] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const alive = useRef(true)
  const creatingRef = useRef(false)

  useEffect(() => {
    alive.current = true
    const load = async () => {
      if (!sessionId) {
        setError('缺少学习会话')
        setLoading(false)
        return
      }
      try {
        let detail = await getSession(sessionId)
        if (!alive.current) return
        setSession(detail)
        if (detail.status !== 'completed') {
          detail = await pollSession(sessionId, { stopAt: ['completed'] })
          if (!alive.current) return
          setSession(detail)
        }
        const data = await fetchSettlement(sessionId)
        if (!alive.current) return
        setSettlement(data)
        if (detail.chapter_id) {
          getChapter(detail.chapter_id)
            .then((chapterData) => {
              if (alive.current) setChapter(chapterData)
            })
            .catch(() => undefined)
        }
        setError('')
      } catch (err) {
        if (alive.current) setError((err as Error).message || '结算加载失败')
      } finally {
        if (alive.current) setLoading(false)
      }
    }
    load()
    return () => {
      alive.current = false
    }
  }, [sessionId])

  useEffect(() => {
    if (!settlement) return
    setLitStars(0)
    const timers: ReturnType<typeof setTimeout>[] = []
    for (let i = 0; i < settlement.stars; i += 1) {
      timers.push(setTimeout(() => setLitStars(i + 1), 120 * (i + 1)))
    }
    return () => timers.forEach((timer) => clearTimeout(timer))
  }, [settlement])

  const openReport = () => {
    goToReport(sessionId)
  }

  const openMap = () => {
    goToMap(session?.chapter_id)
  }

  const retry = async () => {
    if (!session || creatingRef.current) return
    creatingRef.current = true
    try {
      const modal = await Taro.showModal({
        title: '重练本关？',
        content: '会重新生成一组题，并消耗 1 次造关额度。',
        confirmText: '重练',
        cancelText: '再想想'
      })
      if (!modal.confirm) return
      setCreating(true)
      const created = await createSession({
        topic: session.topic,
        level: session.level,
        question_count: session.question_count,
        types: session.types,
        kind: session.kind === 'daily' ? 'daily' : 'standard'
      })
      Taro.redirectTo({ url: `/pages/generating/index?sessionId=${created.id}` })
    } catch (err) {
      if (await handleCreateError(err, () => setLoginOpen(true))) return
      Taro.showToast({ title: errorMessage(err, '创建失败，请重试'), icon: 'none' })
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader back title='关卡结算' />
        <LoadingOrb title='正在结算这一关' subtitle='星子正在落下来' />
      </PageShell>
    )
  }

  if (error || !settlement) {
    return (
      <PageShell>
        <PageHeader back title='关卡结算' />
        <ErrorCard
          title='结算没有落下来'
          message={error || '数据不存在'}
          retryLabel='重新加载'
          onRetry={() => Taro.redirectTo({ url: `/pages/result/index?sessionId=${sessionId}` })}
          backLabel='回首页'
          onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </PageShell>
    )
  }

  const passed = settlement.stars > 0
  const perfect = settlement.stars >= 3
  const title = perfect ? '满星通关' : passed ? '通关' : '再走一遍'
  const accuracy = Math.round(settlement.accuracy * 100)
  const chapterTitle = chapter?.title || session?.topic || '本关'
  const primaryLabel = !passed ? (creating ? '正在准备…' : '重练本关') : '下一关'

  return (
    <PageShell>
      <PageHeader back title='关卡结算' />
      <View className='result-body'>
        <View className='result-top row between'>
          <Text className='result-top-title'>{topicShort(chapterTitle, 16)}</Text>
          <View className='chip chip-ghost'>
            <Icon name='clock-ink3' size={16} />
            {formatDuration(settlement.duration_sec)}
          </View>
        </View>

        <View className={`result-card ${perfect ? 'perfect' : passed ? 'passed' : 'retry'}`}>
          <View className='result-eyebrow'>关 卡 评 级</View>
          <View className={`result-stars ${passed ? 'lit' : ''}`}>
            <StarRating stars={litStars} size='lg' animate />
          </View>
          <View className='result-title'>{title}</View>
          <View className='result-sub'>
            正确率 {accuracy}% · {starText(settlement.stars)}
          </View>
          {passed && (
            <View className='result-seal'>
              <SealStamp text={perfect ? '满星' : '通关'} animate />
            </View>
          )}
        </View>

        <View className='result-stats'>
          <View className='result-stat'>
            <Text className='result-stat-num'>{accuracy}%</Text>
            <Text className='result-stat-label'>正确率</Text>
          </View>
          <View className='result-stat'>
            <Text className='result-stat-num'>{formatDuration(settlement.duration_sec, true)}</Text>
            <Text className='result-stat-label'>用时</Text>
          </View>
          <View className='result-stat'>
            <Text className='result-stat-num'>×{settlement.combo}</Text>
            <Text className='result-stat-label'>连击</Text>
          </View>
        </View>

        <View className='result-exp'>
          <View className='row between'>
            <Text className='result-exp-title'>
              积分 +{settlement.exp}
              {settlement.exp_to_next > 0
                ? ` / 距离升级还差 ${settlement.exp_to_next}`
                : ' / 已到最高段位'}
            </Text>
            <Text className='result-rank'>{settlement.rank_after.label}</Text>
          </View>
          <ProgressBar value={settlement.rank_after.progress_pct} max={100} tone='amber' />
          <View className='row between result-exp-foot'>
            <Text className='muted'>
              {settlement.level_up ? '段位提升，继续往前走' : '每一步都算数'}
            </Text>
            {chapter?.comprehensive?.status === 'unlocked' && (
              <Text className='result-unlock'>解锁：章末 · 综合</Text>
            )}
          </View>
        </View>

        {settlement.wrong_count > 0 && (
          <View className='result-wrong' onClick={openReport}>
            <View className='grow'>
              <Text className='result-wrong-title'>错题 {settlement.wrong_count} 道</Text>
              <Text className='result-wrong-desc'>去报告里逐题看看，</Text>
            </View>
            <View className='chip chip-active'>去查看</View>
          </View>
        )}

        <View className='result-bottom-space' />
      </View>

      <View className='result-footer'>
        <View className='result-actions'>
          <View className='btn btn-ghost result-action' onClick={openReport}>
            查看解析
          </View>
          <View
            className={`btn btn-primary result-action result-action-main ${creating ? 'btn-disabled' : ''}`}
            onClick={() => {
              if (!passed) {
                retry()
              } else {
                openMap()
              }
            }}
          >
            {primaryLabel}
          </View>
        </View>
      </View>

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          Taro.showToast({ title: '登录成功，可以继续了', icon: 'success' })
        }}
        reason='登录后可继续造关，学习记录也会跟着账号走。'
      />
    </PageShell>
  )
}