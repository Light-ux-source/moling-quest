import { useEffect, useRef, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useRouter, useShareAppMessage } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import ProgressBar from '../../components/ProgressBar'
import LoadingOrb from '../../components/LoadingOrb'
import ErrorCard from '../../components/ErrorCard'
import StarRating from '../../components/StarRating'
import LoginSheet from '../../components/LoginSheet'
import { createSession, waitForReport } from '../../services/api'
import type { Level, Report } from '../../types'
import { ALL_TYPES } from '../../types'
import {
  formatAnswer,
  formatDate,
  formatDuration,
  scoreTone,
  starText,
  topicShort
} from '../../utils/format'
import { errorMessage, handleCreateError } from '../../utils/quota'
import './index.css'

export default function ReportPage() {
  const router = useRouter()
  const sessionId = router.params?.sessionId || ''
  const [report, setReport] = useState<Report | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [openIds, setOpenIds] = useState<string[]>([])
  const [creating, setCreating] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const alive = useRef(true)
  const creatingRef = useRef(false)

  const load = async () => {
    if (!sessionId) {
      setError('缺少学习会话')
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const data = await waitForReport(sessionId)
      if (!alive.current) return
      setReport(data)
      setError('')
    } catch (err) {
      if (alive.current) setError((err as Error).message || '报告加载失败')
    } finally {
      if (alive.current) setLoading(false)
    }
  }

  useEffect(() => {
    alive.current = true
    load()
    return () => {
      alive.current = false
    }
  }, [sessionId])

  useShareAppMessage(() => ({
    title: report ? `${report.topic} · ${report.score} 分学习诊断` : '墨灵闯关 · 学习诊断',
    path: `/pages/report/index?sessionId=${sessionId}`
  }))

  const toggle = (id: string) => {
    setOpenIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  const practice = async (topic = report?.topic || '') => {
    if (!report || creatingRef.current || !topic) return
    creatingRef.current = true
    try {
      const modal = await Taro.showModal({
        title: '再练一组？',
        content: '会新建一组题，并消耗 1 次造关额度。',
        confirmText: '开始',
        cancelText: '再想想'
      })
      if (!modal.confirm) return
      setCreating(true)
      Taro.showLoading({ title: '正在造新一组…', mask: true })
      const session = await createSession({
        topic,
        level: report.level as Level,
        question_count: report.total,
        types: ALL_TYPES
      })
      Taro.hideLoading()
      Taro.redirectTo({ url: `/pages/generating/index?sessionId=${session.id}` })
    } catch (err) {
      Taro.hideLoading()
      if (await handleCreateError(err, () => setLoginOpen(true))) return
      Taro.showToast({ title: errorMessage(err, '创建失败，请重试'), icon: 'none' })
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }

  const share = () => {
    if (process.env.TARO_ENV === 'weapp') {
      Taro.showShareMenu({ withShareTicket: true })
      Taro.showToast({ title: '点右上角分享这一页', icon: 'none' })
      return
    }
    const url = typeof window !== 'undefined' ? window.location.href : ''
    if (!url) return
    Taro.setClipboardData({ data: url }).then(() => {
      Taro.showToast({ title: '链接已复制', icon: 'none' })
    })
  }

  const copySource = (url: string) => {
    if (!url) return
    Taro.setClipboardData({ data: url }).then(() => {
      Taro.showToast({ title: '链接已复制', icon: 'none' })
    })
  }

  const changeTopic = () => Taro.redirectTo({ url: '/pages/create/index' })

  if (loading) {
    return (
      <PageShell>
        <PageHeader back title='学习报告' />
        <LoadingOrb title='正在批改并生成报告' subtitle='客观题即时判分，简答题按得分点评估' />
      </PageShell>
    )
  }

  if (error || !report) {
    return (
      <PageShell>
        <PageHeader back title='学习报告' />
        <ErrorCard
          title='报告没有长出来'
          message={error || '数据不存在'}
          retryLabel='重新加载'
          onRetry={load}
          backLabel='回首页'
          onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </PageShell>
    )
  }

  const tone = scoreTone(report.score)
  const typeEntries = Object.keys(report.by_type).map((label) => ({
    label,
    ...report.by_type[label]
  }))

  return (
    <PageShell>
      <PageHeader
        back
        title='学习报告'
        right={
          <View className='chip chip-ghost' onClick={share}>
            <Icon name='share-ink' size={16} />
            分享
          </View>
        }
      />
      <View className='report-body'>
        <View className='report-meta row between'>
          <Text className='report-date'>本次报告 · {formatDate(report.generated_at)}</Text>
          <Text className='report-duration'>用时 {formatDuration(report.duration_sec)}</Text>
        </View>
        <View className='report-title'>{topicShort(report.topic, 20)}</View>
        <View className='report-subtitle'>学习诊断</View>

        <View className={`score-card ${tone}`}>
          <View className='score-ring'>
            <Text className='score-num'>{report.score}</Text>
            <Text className='score-unit'>分</Text>
          </View>
          <View className='score-meta'>
            <View className='score-tag-row'>
              <View className='chip chip-active'>{report.level_tag || '已完成'}</View>
              <StarRating stars={report.settlement?.stars || 0} size='sm' />
            </View>
            <Text className='score-summary'>{report.summary}</Text>
            <Text className='score-detail'>
              答对 {report.correct}/{report.total} · 正确率 {Math.round(report.accuracy * 100)}%
            </Text>
          </View>
        </View>

        <View className='report-card'>
          <View className='section-title report-card-title'>分题型</View>
          <View className='type-bars'>
            {typeEntries.map((item) => {
              const ratio = item.total ? (item.correct / item.total) * 100 : 0
              return (
                <View key={item.label} className='type-row'>
                  <Text className='type-label'>{item.label}</Text>
                  <View className='grow'>
                    <ProgressBar value={ratio} max={100} size='sm' tone={ratio >= 80 ? 'moss' : 'amber'} />
                  </View>
                  <Text className='type-value'>
                    {item.correct}/{item.total}
                  </Text>
                </View>
              )
            })}
          </View>
        </View>

        <View className='report-card report-dashed'>
          <View className='section-title report-card-title'>知识缺口</View>
          {report.knowledge_gaps.length > 0 ? (
            report.knowledge_gaps.map((gap, index) => (
              <View key={`${gap}-${index}`} className='gap-item'>
                <View className='gap-dot' />
                <Text className='gap-text'>{gap}</Text>
              </View>
            ))
          ) : (
            <Text className='muted'>这次没有明显缺口，继续保持。</Text>
          )}
        </View>

        <View className='report-card report-dashed'>
          <View className='section-title report-card-title'>下一步</View>
          {report.next_steps.map((step, index) => (
            <View key={`${step}-${index}`} className='step-item'>
              <View className='step-num'>{index + 1}</View>
              <Text className='step-text'>{step}</Text>
            </View>
          ))}
        </View>

        <View className='section-row'>
          <Text className='section-title'>逐题解析</Text>
          <Text className='more'>点击展开</Text>
        </View>
        <View className='review-list'>
          {report.items.map((item) => {
            const open = openIds.includes(item.question_id)
            return (
              <View key={item.question_id} className={`review-item ${open ? 'open' : ''}`} onClick={() => toggle(item.question_id)}>
                <View className='review-head'>
                  <View className={`review-status ${item.is_correct ? 'ok' : 'bad'}`}>
                    <Icon name={item.is_correct ? 'check-paper' : 'close-ink3'} size={16} />
                  </View>
                  <View className='grow'>
                    <View className='review-top'>
                      <Text className='review-seq'>第 {item.seq} 题</Text>
                      <Text className={`tag ${item.is_correct ? 'tag-ok' : 'tag-bad'}`}>
                        {item.type_label} · {item.is_correct ? '正确' : item.score > 0 ? '部分得分' : '错误'}
                      </Text>
                    </View>
                    <Text className='review-stem'>{item.stem}</Text>
                  </View>
                  <Icon name={open ? 'chevron-down-ink3' : 'chevron-right-ink3'} size={18} />
                </View>
                {open && (
                  <View className='review-detail'>
                    <View className='answer-block'>
                      <Text className='answer-label'>你的答案</Text>
                      <Text className='answer-text'>{formatAnswer(item, item.user_answer)}</Text>
                    </View>
                    <View className='answer-block'>
                      <Text className='answer-label'>正确答案</Text>
                      <Text className='answer-text answer-correct'>{formatAnswer(item, item.correct_answer)}</Text>
                    </View>
                    <View className='answer-block'>
                      <Text className='answer-label'>批改反馈</Text>
                      <Text className='answer-text'>{item.feedback || '—'}</Text>
                    </View>
                    {item.explanation ? (
                      <View className='answer-block'>
                        <Text className='answer-label'>解析</Text>
                        <Text className='answer-text'>{item.explanation}</Text>
                      </View>
                    ) : null}
                    {item.rubric.length > 0 && (
                      <View className='answer-block'>
                        <Text className='answer-label'>得分要点</Text>
                        {item.rubric.map((point, idx) => (
                          <Text key={`${point}-${idx}`} className='rubric-item'>
                            · {point}
                          </Text>
                        ))}
                      </View>
                    )}
                    {item.source_refs.length > 0 && (
                      <View className='answer-block'>
                        <Text className='answer-label'>来源</Text>
                        {item.source_refs.map((url) => (
                          <Text key={url} className='source-link' onClick={() => copySource(url)}>
                            {url}
                          </Text>
                        ))}
                      </View>
                    )}
                  </View>
                )}
              </View>
            )
          })}
        </View>

        {report.sources.length > 0 && (
          <View className='report-card'>
            <View className='section-title report-card-title'>参考来源</View>
            {report.sources.map((source, index) => (
              <View key={`${source.title}-${index}`} className='source-item' onClick={() => copySource(source.url)}>
                <View className='grow'>
                  <Text className='source-title'>{source.title || '未命名来源'}</Text>
                  <Text className='source-site'>{source.site_name || '未知站点'}</Text>
                </View>
                <Icon name='copy-ink3' size={16} />
              </View>
            ))}
          </View>
        )}

        {report.suggested_topics.length > 0 && (
          <View className='report-card'>
            <View className='section-title report-card-title'>建议接着练</View>
            <View className='chip-row'>
              {report.suggested_topics.map((topic) => (
                <View key={topic} className='chip chip-active' onClick={() => practice(topic)}>
                  {topic}
                </View>
              ))}
            </View>
          </View>
        )}

        <View className='report-disclaimer'>
          内容由 AI 生成，仅供学习参考
          {report.model ? ` · ${report.model}` : ''}
        </View>
        <View className='report-usage'>
          本次消耗 {report.usage.tokens_in + report.usage.tokens_out} tokens · 约 ¥
          {Number(report.usage.cost_cny || 0).toFixed(4)}（{report.usage.note}）
        </View>
        <View className='report-bottom-space' />
      </View>

      <View className='report-footer'>
        <View className='report-actions'>
          <View className='btn btn-ghost report-action' onClick={changeTopic}>
            换个主题
          </View>
          <View
            className={`btn btn-primary report-action report-action-main ${creating ? 'btn-disabled' : ''}`}
            onClick={() => practice()}
          >
            {creating ? '正在准备…' : '再练一组'}
          </View>
        </View>
      </View>

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          Taro.showToast({ title: '登录成功，可以继续造关了', icon: 'success' })
        }}
        reason='登录后可继续造关，学习记录也会跟着账号走。'
      />
    </PageShell>
  )
}