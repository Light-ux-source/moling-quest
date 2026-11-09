import { useEffect, useRef, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import { ApiError, fetchReport, getSession, pollSession } from '../../services/api'
import { AnswerResult, Report } from '../../types'
import './index.css'

function optionText(item: AnswerResult, key: string): string {
  const option = item.options.find((o) => o.key === key)
  return option ? option.text : ''
}

function formatAnswer(item: AnswerResult, value: string | string[] | null): string {
  if (value === null || value === undefined) return '未作答'
  if (Array.isArray(value)) {
    if (value.length === 0) return '未作答'
    if (item.type === 'short_answer') return value.join('；')
    return value
      .map((key) => {
        const text = optionText(item, key)
        return text ? `${key}. ${text}` : key
      })
      .join('\n')
  }
  if (!value.trim()) return '未作答'
  if (item.type === 'short_answer') return value
  const text = optionText(item, value)
  return text ? `${value}. ${text}` : value
}

function formatDuration(seconds: number): string {
  if (!seconds) return '—'
  if (seconds < 60) return `${seconds} 秒`
  return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

export default function ReportPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [grading, setGrading] = useState(true)
  const [openIds, setOpenIds] = useState<string[]>([])
  const alive = useRef(true)

  const loadReport = async (): Promise<void> => {
    try {
      // 先确认批改完成，避免用 409 反复探测
      const session = await getSession(sessionId)
      if (session.status !== 'completed') {
        await pollSession(sessionId)
      }
      const data = await fetchReport(sessionId)
      if (!alive.current) return
      setReport(data)
      setGrading(false)
      setError('')
    } catch (err) {
      if (!alive.current) return
      setGrading(false)
      setError((err as Error).message || (err as ApiError).message || '报告加载失败')
    }
  }

  useEffect(() => {
    alive.current = true
    if (!sessionId) {
      setError('缺少学习会话')
      setGrading(false)
      return
    }
    loadReport()
    return () => {
      alive.current = false
    }
  }, [])

  const toggle = (id: string) => {
    setOpenIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const restart = () => {
    if (!report) return
    Taro.reLaunch({ url: `/pages/index/index?topic=${encodeURIComponent(report.topic)}` })
  }

  const changeTopic = () => {
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  const copySource = (url: string) => {
    if (!url) return
    Taro.setClipboardData({ data: url }).then(() => {
      Taro.showToast({ title: '链接已复制', icon: 'none' })
    })
  }

  if (grading) {
    return (
      <View className='page'>
        <View className='grading-wrap'>
          <View className='grading-orb'>AI</View>
          <View className='grading-title'>AI 正在批改并生成报告</View>
          <View className='grading-sub'>客观题即时判分，简答题按得分点评估</View>
          <View className='grading-dots'>
            <View className='grading-dot' />
            <View className='grading-dot' />
            <View className='grading-dot' />
          </View>
        </View>
      </View>
    )
  }

  if (error || !report) {
    return (
      <View className='page'>
        <View className='card error-card'>
          <View className='error-title'>报告加载失败</View>
          <View className='error-text'>{error || '数据不存在'}</View>
          <View className='btn btn-primary error-btn' onClick={() => loadReport()}>
            重试
          </View>
          <View className='btn error-btn' onClick={changeTopic}>
            回到首页
          </View>
        </View>
      </View>
    )
  }

  const scoreClass = report.score >= 80 ? 'score-good' : report.score >= 60 ? 'score-mid' : 'score-low'

  return (
    <View className='page report-page'>
      <View className={`report-hero ${scoreClass}`}>
        <View className='report-topic'>{report.topic}</View>
        <View className='score-row'>
          <View className='score-num'>
            {report.score}
            <Text className='score-unit'>分</Text>
          </View>
          <View className='score-meta'>
            <View className='score-tag'>{report.level_tag || '已完成'}</View>
            <View className='score-detail'>
              答对 {report.correct}/{report.total} · 用时 {formatDuration(report.duration_sec)}
            </View>
            <View className='score-detail'>
              {report.level_label} · {report.model || 'AI'}
            </View>
          </View>
        </View>
        <View className='score-track'>
          <View className='score-track-fill' style={{ width: `${report.score}%` }} />
        </View>
      </View>

      <View className='card'>
        <View className='section-title'>AI 学习诊断</View>
        <View className='summary-text'>{report.summary}</View>
        <View className='type-grid'>
          {Object.keys(report.by_type).map((label) => {
            const item = report.by_type[label]
            const ratio = item.total ? Math.round((item.correct / item.total) * 100) : 0
            return (
              <View key={label} className='type-item'>
                <View className='type-item-label'>{label}</View>
                <View className='type-item-value'>
                  {item.correct}/{item.total}
                </View>
                <View className='type-item-bar'>
                  <View className='type-item-bar-fill' style={{ width: `${ratio}%` }} />
                </View>
              </View>
            )
          })}
        </View>
      </View>

      <View className='card'>
        <View className='section-title'>知识缺口</View>
        {report.knowledge_gaps.map((gap, index) => (
          <View key={`${gap}-${index}`} className='gap-item'>
            <View className='gap-dot' />
            <Text className='gap-text'>{gap}</Text>
          </View>
        ))}
        {report.knowledge_gaps.length === 0 && <View className='muted'>暂无，继续保持。</View>}
      </View>

      <View className='card'>
        <View className='section-title'>下一步怎么做</View>
        {report.next_steps.map((step, index) => (
          <View key={`${step}-${index}`} className='step-item'>
            <View className='step-num'>{index + 1}</View>
            <Text className='step-text'>{step}</Text>
          </View>
        ))}
      </View>

      <View className='card'>
        <View className='row between review-head'>
          <View className='section-title'>逐题解析</View>
          <Text className='muted'>点击展开</Text>
        </View>
        {report.items.map((item) => {
          const open = openIds.includes(item.question_id)
          return (
            <View key={item.question_id} className='review-item' onClick={() => toggle(item.question_id)}>
              <View className={`review-status ${item.is_correct ? 'review-status-ok' : 'review-status-bad'}`}>
                {item.is_correct ? '✓' : '×'}
              </View>
              <View className='review-body'>
                <View className='review-top'>
                  <Text className='review-seq'>第 {item.seq} 题</Text>
                  <Text className={`badge ${item.is_correct ? 'badge-ok' : 'badge-bad'}`}>
                    {item.type_label} · {item.is_correct ? '正确' : item.score > 0 ? '部分得分' : '错误'}
                  </Text>
                </View>
                <View className='review-stem'>{item.stem}</View>
                {open && (
                  <View className='review-detail'>
                    <View className='answer-block'>
                      <View className='answer-label'>你的答案</View>
                      <View className='answer-text'>{formatAnswer(item, item.user_answer)}</View>
                    </View>
                    <View className='answer-block'>
                      <View className='answer-label'>正确答案</View>
                      <View className='answer-text answer-correct'>
                        {formatAnswer(item, item.correct_answer)}
                      </View>
                    </View>
                    <View className='answer-block'>
                      <View className='answer-label'>批改反馈</View>
                      <View className='answer-text'>{item.feedback || '—'}</View>
                    </View>
                    {item.explanation && (
                      <View className='answer-block'>
                        <View className='answer-label'>解析</View>
                        <View className='answer-text'>{item.explanation}</View>
                      </View>
                    )}
                    {item.rubric.length > 0 && (
                      <View className='answer-block'>
                        <View className='answer-label'>得分要点</View>
                        {item.rubric.map((point, idx) => (
                          <View key={`${point}-${idx}`} className='rubric-item'>
                            · {point}
                          </View>
                        ))}
                      </View>
                    )}
                    {item.source_refs.length > 0 && (
                      <View className='answer-block'>
                        <View className='answer-label'>来源</View>
                        {item.source_refs.map((url) => (
                          <View key={url} className='source-link' onClick={() => copySource(url)}>
                            {url}
                          </View>
                        ))}
                      </View>
                    )}
                  </View>
                )}
              </View>
            </View>
          )
        })}
      </View>

      {report.suggested_topics.length > 0 && (
        <View className='card'>
          <View className='section-title'>建议接着练</View>
          <View className='topic-chips'>
            {report.suggested_topics.map((topic) => (
              <View
                key={topic}
                className='chip chip-active'
                onClick={() => Taro.reLaunch({ url: `/pages/index/index?topic=${encodeURIComponent(topic)}` })}
              >
                {topic}
              </View>
            ))}
          </View>
        </View>
      )}

      {report.sources.length > 0 && (
        <View className='card'>
          <View className='section-title'>参考来源</View>
          {report.sources.map((source, index) => (
            <View
              key={`${source.title}-${index}`}
              className='source-item'
              onClick={() => copySource(source.url)}
            >
              <View className='source-title'>{source.title || '未命名来源'}</View>
              <View className='muted'>{source.site_name || '未知站点'}</View>
            </View>
          ))}
        </View>
      )}

      <View className='report-actions'>
        <View className='btn action-btn' onClick={changeTopic}>
          换个主题
        </View>
        <View className='btn btn-primary action-btn action-btn-main' onClick={restart}>
          同主题再练一组
        </View>
      </View>

      <View className='usage-note'>
        本次消耗 {report.usage.tokens_in + report.usage.tokens_out} tokens · 约 ¥
        {report.usage.cost_cny.toFixed(4)}（{report.usage.note}）
      </View>
    </View>
  )
}