import { useEffect, useRef, useState } from 'react'
import { View, Text, Textarea } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import StageLoading from '../../components/StageLoading'
import { getSession, pollSession, submitAnswers } from '../../services/api'
import { QuestionType, SessionDetail, TYPE_META } from '../../types'
import './index.css'

const DIFFICULTY_LABEL: Record<string, string> = {
  easy: '基础',
  medium: '中等',
  hard: '较难'
}

function isEmptyAnswer(value: string | string[] | undefined): boolean {
  if (value === undefined || value === null) return true
  if (Array.isArray(value)) return value.length === 0
  return !String(value).trim()
}

function safeDecode(value?: string): string {
  if (!value) return ''
  try {
    return decodeURIComponent(value)
  } catch (err) {
    return value
  }
}

export default function Quiz() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [topic, setTopic] = useState(safeDecode(router.params?.topic))
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({})
  const [current, setCurrent] = useState(0)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const alive = useRef(true)

  const goReport = () => {
    Taro.redirectTo({ url: `/pages/report/index?sessionId=${sessionId}` })
  }

  const load = async () => {
    if (!sessionId) {
      setError('缺少学习会话，请返回重新开始')
      return
    }
    setError('')
    try {
      const first = await getSession(sessionId)
      if (!alive.current) return
      setTopic(first.topic)
      setSession(first)

      if (first.status === 'completed' || first.status === 'grading' || first.status === 'reporting') {
        goReport()
        return
      }
      if (first.status === 'ready' || first.status === 'failed') return

      const final = await pollSession(sessionId, (s) => {
        if (alive.current) {
          setSession(s)
          setTopic(s.topic)
        }
      })
      if (alive.current) setSession(final)
    } catch (err) {
      if (!alive.current) return
      setError((err as Error).message || '加载失败，请重试')
    }
  }

  useEffect(() => {
    alive.current = true
    load()
    return () => {
      alive.current = false
    }
  }, [])

  const questions = session?.questions || []
  const question = questions[current]
  const answerValue = question ? answers[question.id] : undefined

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

  const answeredCount = questions.filter((q) => !isEmptyAnswer(answers[q.id])).length

  const handleSubmit = async () => {
    if (submitting || !session) return
    const payload = questions.map((q) => ({
      question_id: q.id,
      answer: answers[q.id] ?? (q.type === 'multiple_choice' ? [] : '')
    }))
    const blank = payload.filter((p) => isEmptyAnswer(p.answer)).length
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
      await submitAnswers(sessionId, payload)
      goReport()
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '提交失败，请重试', icon: 'none', duration: 2500 })
    } finally {
      setSubmitting(false)
    }
  }

  if (!session && !error) {
    return (
      <View className='page'>
        <StageLoading status='queued' progress={4} topic={topic || '你的主题'} />
      </View>
    )
  }

  if (error) {
    return (
      <View className='page'>
        <View className='card error-card'>
          <View className='error-title'>加载失败</View>
          <View className='error-text'>{error}</View>
          <View className='btn btn-primary error-btn' onClick={load}>
            重试
          </View>
          <View className='btn error-btn' onClick={() => Taro.navigateBack()}>
            返回
          </View>
        </View>
      </View>
    )
  }

  if (session && session.status !== 'ready' && session.status !== 'completed') {
    return (
      <View className='page'>
        <StageLoading
          status={session.status}
          progress={session.progress}
          topic={topic || session.topic}
          error={session.error}
          onRetry={load}
        />
      </View>
    )
  }

  if (!question) {
    return (
      <View className='page'>
        <View className='card error-card'>
          <View className='error-title'>题目为空</View>
          <View className='error-text'>这组题目没有成功生成，请返回重新出题。</View>
        </View>
      </View>
    )
  }

  const progressPercent = Math.round(((current + 1) / questions.length) * 100)
  const isLast = current === questions.length - 1
  const meta = TYPE_META[question.type as QuestionType]

  return (
    <View className='page quiz-page'>
      <View className='quiz-head'>
        <View className='row between'>
          <Text className='quiz-topic'>{topic}</Text>
          <Text className='quiz-index'>
            {current + 1} / {questions.length}
          </Text>
        </View>
        <View className='progress-track'>
          <View className='progress-fill' style={{ width: `${progressPercent}%` }} />
        </View>
        <View className='quiz-sub'>
          已作答 {answeredCount} 题 · 共 {questions.length} 题
        </View>
      </View>

      <View className='card question-card'>
        <View className='q-meta'>
          <Text className='badge'>{meta?.label || '题目'}</Text>
          <Text className='badge badge-warn'>{DIFFICULTY_LABEL[question.difficulty] || '中等'}</Text>
        </View>
        <View className='q-stem'>{question.stem}</View>

        {question.options.length > 0 ? (
          <View className='option-list'>
            {question.options.map((opt) => {
              const selected = Array.isArray(answerValue)
                ? answerValue.includes(opt.key)
                : answerValue === opt.key
              return (
                <View
                  key={opt.key}
                  className={`option-row ${selected ? 'option-row-active' : ''}`}
                  onClick={() => selectOption(opt.key)}
                >
                  <View className={`option-key ${selected ? 'option-key-active' : ''}`}>{opt.key}</View>
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
          </View>
        )}

        {question.type === 'multiple_choice' && <View className='q-hint'>多选题：选全才得分</View>}
      </View>

      <View className='quiz-footer'>
        <View
          className={`btn footer-btn ${current === 0 ? 'btn-disabled' : ''}`}
          onClick={() => current > 0 && setCurrent(current - 1)}
        >
          上一题
        </View>
        <View
          className={`btn btn-primary footer-btn footer-btn-main ${submitting ? 'btn-disabled' : ''}`}
          onClick={() => {
            if (isLast) {
              handleSubmit()
            } else {
              setCurrent(current + 1)
            }
          }}
        >
          {isLast ? (submitting ? '提交中…' : '提交答案') : '下一题'}
        </View>
      </View>

      <View className='dots'>
        {questions.map((q, index) => {
          const answered = !isEmptyAnswer(answers[q.id])
          return (
            <View
              key={q.id}
              className={`dot ${index === current ? 'dot-current' : ''} ${answered ? 'dot-answered' : ''}`}
              onClick={() => setCurrent(index)}
            />
          )
        })}
      </View>
    </View>
  )
}