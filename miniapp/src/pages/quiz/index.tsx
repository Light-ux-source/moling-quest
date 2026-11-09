import { useEffect, useRef, useState } from 'react'
import { View, Text, Textarea } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import ProgressBar from '../../components/ProgressBar'
import ErrorCard from '../../components/ErrorCard'
import LoadingOrb from '../../components/LoadingOrb'
import {
  clearDraft,
  getSession,
  loadDraft,
  saveDraft,
  submitAnswers,
  updateProgress
} from '../../services/api'
import type { QuestionType, SessionDetail } from '../../types'
import { DIFFICULTY_META, TYPE_META } from '../../types'
import { isBlankAnswer, topicShort } from '../../utils/format'
import './index.css'

export default function QuizPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const startSeq = Number(router.params?.startSeq || 0)
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [current, setCurrent] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    const load = async () => {
      if (!sessionId) {
        setError('缺少学习会话，请返回重新开始')
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
        if (['grading', 'reporting', 'completed'].includes(detail.status)) {
          Taro.redirectTo({ url: `/pages/result/index?sessionId=${sessionId}` })
          return
        }
        if (detail.status === 'failed') {
          setError(detail.error || '题目生成失败，请返回重试')
          setLoading(false)
          return
        }
        const draft = loadDraft(sessionId)
        const total = detail.questions.length
        const rawIndex = startSeq > 0 ? startSeq - 1 : (draft?.currentSeq || detail.current_seq || 1) - 1
        const index = Math.max(0, Math.min(Number.isFinite(rawIndex) ? rawIndex : 0, total - 1))
        setSession(detail)
        setAnswers(draft?.answers || {})
        setCurrent(index)
        setError('')
      } catch (err) {
        if (alive.current) setError((err as Error).message || '加载失败，请重试')
      } finally {
        if (alive.current) setLoading(false)
      }
    }
    load()
    return () => {
      alive.current = false
    }
  }, [sessionId, startSeq])

  useEffect(() => {
    if (!session) return
    saveDraft(session.id, { answers, currentSeq: current + 1, updatedAt: Date.now() })
  }, [answers, current, session])

  useEffect(() => {
    if (!session || session.status !== 'ready') return
    updateProgress(session.id, current + 1).catch(() => undefined)
  }, [current, session])

  const questions = session?.questions || []
  const question = questions[current]
  const answerValue = question ? answers[question.id] : undefined
  const total = questions.length
  const isLast = current === total - 1
  const progress = total ? ((current + 1) / total) * 100 : 0

  const setAnswer = (questionId: string, value: string | string[]) => {
    setAnswers((prev) => ({ ...prev, [questionId]: value }))
  }

  const selectOption = (key: string) => {
    if (!question) return
    if (question.type === 'multiple_choice') {
      const prev = Array.isArray(answerValue) ? answerValue : []
      const next = prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key].sort()
      setAnswer(question.id, next)
    } else {
      setAnswer(question.id, key)
    }
  }

  const goTo = (index: number) => {
    if (index < 0 || index >= total) return
    setCurrent(index)
    Taro.pageScrollTo({ scrollTop: 0, duration: 120 })
  }

  const handleSubmit = async () => {
    if (submitting || !session) return
    const payload = questions.map((q) => ({
      question_id: q.id,
      answer: answers[q.id] ?? (q.type === 'multiple_choice' ? [] : '')
    }))
    const blank = payload.filter((p) => isBlankAnswer(p.answer)).length
    if (blank > 0) {
      const modal = await Taro.showModal({
        title: '还有未作答的题目',
        content: `还有 ${blank} 题没作答，提交后将按 0 分计入报告。`,
        confirmText: '仍然提交',
        cancelText: '继续答题'
      })
      if (!modal.confirm) return
    }
    setSubmitting(true)
    try {
      await submitAnswers(session.id, payload)
      clearDraft(session.id)
      Taro.redirectTo({ url: `/pages/result/index?sessionId=${session.id}` })
    } catch (err) {
      const message = (err as Error).message || '提交失败，请重试'
      if (message.includes('已提交')) {
        Taro.redirectTo({ url: `/pages/result/index?sessionId=${session.id}` })
        return
      }
      Taro.showToast({ title: message, icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <PageShell>
        <PageHeader back title='答题' />
        <LoadingOrb title='正在翻开题目' subtitle='稍等，雾林正在铺开这一关' />
      </PageShell>
    )
  }

  if (error) {
    return (
      <PageShell>
        <PageHeader back title='答题' />
        <ErrorCard
          title='这一关没打开'
          message={error}
          retryLabel='重新加载'
          onRetry={() => Taro.redirectTo({ url: `/pages/quiz/index?sessionId=${sessionId}` })}
          backLabel='回首页'
          onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </PageShell>
    )
  }

  if (!question) {
    return (
      <PageShell>
        <PageHeader back title='答题' />
        <ErrorCard title='题目为空' message='这组题没有成功生成，请返回重新出题。' backLabel='回首页' onBack={() => Taro.reLaunch({ url: '/pages/index/index' })} />
      </PageShell>
    )
  }

  const answeredCount = questions.filter((q) => !isBlankAnswer(answers[q.id])).length
  const meta = TYPE_META[question.type as QuestionType]
  const selectedAnswer = Array.isArray(answerValue) ? answerValue : answerValue ? [answerValue] : []

  return (
    <PageShell>
      <PageHeader
        back
        title={`第 ${current + 1} 关 · ${topicShort(session?.topic || '', 10)}`}
        right={<Text className='quiz-index'>{current + 1} / {total}</Text>}
      />
      <View className='quiz-body'>
        <ProgressBar value={progress} max={100} />
        <View className='quiz-subline'>
          <Text>已作答 {answeredCount} 题</Text>
          <Text>共 {total} 题</Text>
        </View>

        <View className='quiz-tags'>
          <View className='chip chip-active'>{meta?.label || '题目'}</View>
          <View className='chip chip-ghost'>{DIFFICULTY_META[question.difficulty] || '中等'}</View>
          {question.type === 'multiple_choice' && <View className='chip chip-amber'>选全才得分</View>}
        </View>

        <View className='question-stem'>{question.stem}</View>

        {question.options.length > 0 ? (
          <View className='option-list'>
            {question.options.map((opt) => {
              const selected = selectedAnswer.includes(opt.key)
              return (
                <View
                  key={opt.key}
                  className={`option-card ${selected ? 'selected' : ''}`}
                  onClick={() => selectOption(opt.key)}
                >
                  <View className='option-key'>{opt.key}</View>
                  <View className='option-text'>{opt.text}</View>
                </View>
              )
            })}
          </View>
        ) : (
          <View className='short-wrap'>
            <Textarea
              className='answer-input'
              value={typeof answerValue === 'string' ? answerValue : ''}
              placeholder='用自己的话写出要点，AI 会按得分点批改'
              placeholderClass='answer-placeholder'
              maxlength={600}
              onInput={(e) => setAnswer(question.id, e.detail.value)}
            />
            <View className='answer-count'>
              {typeof answerValue === 'string' ? answerValue.length : 0}/600
            </View>
            <View className='answer-hint'>写「定义 → 机制 → 场景」三句话，通常就能覆盖得分点。</View>
          </View>
        )}

        <View className='quiz-bottom-space' />
      </View>

      <View className='quiz-footer'>
        <View className='quiz-actions'>
          <View
            className={`btn btn-ghost quiz-prev ${current === 0 ? 'btn-disabled' : ''}`}
            onClick={() => goTo(current - 1)}
          >
            <Icon name='arrow-right-ink' size={16} className='quiz-prev-icon' />
            上一题
          </View>
          <View
            className={`btn btn-primary quiz-next ${submitting ? 'btn-disabled' : ''}`}
            onClick={() => {
              if (isLast) {
                handleSubmit()
              } else {
                goTo(current + 1)
              }
            }}
          >
            {isLast ? (submitting ? '提交中…' : '提交答案') : '下一题'}
            {!isLast && <Icon name='arrow-right-paper' size={16} />}
          </View>
        </View>
        <View className='dots'>
          {questions.map((q, index) => {
            const answered = !isBlankAnswer(answers[q.id])
            return (
              <View
                key={q.id}
                className={`dot ${index === current ? 'current' : ''} ${answered ? 'answered' : ''}`}
                onClick={() => goTo(index)}
              />
            )
          })}
        </View>
      </View>
    </PageShell>
  )
}