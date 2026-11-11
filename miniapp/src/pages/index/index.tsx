import { useCallback, useRef, useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import Mascot from '../../components/Mascot'
import Icon from '../../components/Icon'
import StarRating from '../../components/StarRating'
import ProgressBar from '../../components/ProgressBar'
import ErrorCard from '../../components/ErrorCard'
import LoginSheet from '../../components/LoginSheet'
import { useSafeArea } from '../../hooks/useSafeArea'
import { IS_WEAPP } from '../../config'
import { createSession, getChapters, getProfile, health, pushRecentSession, resolveMediaUrl } from '../../services/api'
import type { ChapterSummary, Profile } from '../../types'
import { ALL_TYPES } from '../../types'
import { estimateMinutes, greeting, starText, topicShort } from '../../utils/format'
import { errorMessage, handleCreateError } from '../../utils/quota'
import './index.css'

function isGenerating(status?: string | null): boolean {
  return !!status && ['queued', 'searching', 'digesting', 'generating'].includes(status)
}

function heroCopy(chapter?: ChapterSummary) {
  if (!chapter) {
    return {
      eyebrow: "TODAY'S PATH · 第一章",
      title: '从第一个知识点开始',
      desc: '输入一个知识点，AI 会检索资料并出题。',
      cta: '造一条新路',
      action: 'create' as const
    }
  }
  if (isGenerating(chapter.status)) {
    return {
      eyebrow: "TODAY'S PATH · 正在造关",
      title: chapter.title,
      desc: 'AI 正在检索资料、提炼要点并出题，通常需要 10–40 秒。',
      cta: '查看进度',
      action: 'generating' as const
    }
  }
  if (chapter.status === 'failed') {
    return {
      eyebrow: "TODAY'S PATH · 未完成",
      title: chapter.title,
      desc: '这次没长出来，点进去再试一次，不会消耗新的额度。',
      cta: '重新生成',
      action: 'generating' as const
    }
  }
  if (chapter.status === 'completed') {
    const accuracy = Math.round((chapter.accuracy || 0) * 100)
    return {
      eyebrow: "TODAY'S PATH · 本章已完成",
      title: chapter.title,
      desc: `正确率 ${accuracy}% · ${starText(chapter.stars)}，去报告看看下一步学什么。`,
      cta: '回顾这一章',
      action: 'report' as const
    }
  }
  return {
    eyebrow: "TODAY'S PATH · 继续闯关",
    title: chapter.title,
    desc: `已生成 ${chapter.progress.total ? chapter.question_count : chapter.question_count} 题，${
      chapter.next_title ? `下一关：${chapter.next_title}` : '继续完成这一章'
    }。`,
    cta: '继续闯关',
    action: 'map' as const
  }
}

export default function Index() {
  const { top } = useSafeArea()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [chapters, setChapters] = useState<ChapterSummary[]>([])
  const [mode, setMode] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [dailyLoading, setDailyLoading] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const loadedOnce = useRef(false)
  const dailyRef = useRef(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [profileData, chapterData, healthData] = await Promise.all([
        getProfile(),
        getChapters(4),
        health().catch(() => null)
      ])
      setProfile(profileData)
      setChapters(chapterData.items || [])
      setMode(healthData?.mode || '')
      setError('')
    } catch (err) {
      setError((err as Error).message || '加载失败，请重试')
    } finally {
      setLoading(false)
      loadedOnce.current = true
    }
  }, [])

  useDidShow(() => {
    load()
  })

  const standardChapters = chapters.filter((c) => c.kind !== 'daily')
  const mainChapter =
    standardChapters.find((c) => isGenerating(c.status)) ||
    standardChapters.find((c) => c.status === 'ready') ||
    standardChapters.find((c) => c.status === 'failed') ||
    standardChapters[0]
  const copy = heroCopy(mainChapter)
  const streak = profile?.streak_days || 0
  const avatar = resolveMediaUrl(profile?.avatar_url)

  const openMain = () => {
    if (!mainChapter) {
      Taro.navigateTo({ url: '/pages/create/index' })
      return
    }
    if (copy.action === 'create') {
      Taro.navigateTo({ url: '/pages/create/index' })
      return
    }
    if (copy.action === 'generating') {
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${mainChapter.session_id}` })
      return
    }
    if (copy.action === 'report') {
      Taro.navigateTo({ url: `/pages/report/index?sessionId=${mainChapter.session_id}` })
      return
    }
    Taro.navigateTo({ url: `/pages/map/index?chapterId=${mainChapter.id}` })
  }

  const openChapter = (chapter: ChapterSummary) => {
    if (isGenerating(chapter.status) || chapter.status === 'failed') {
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${chapter.session_id}` })
      return
    }
    Taro.navigateTo({ url: `/pages/map/index?chapterId=${chapter.id}` })
  }

  const handleDaily = async () => {
    if (dailyRef.current) return
    dailyRef.current = true
    setDailyLoading(true)
    const topic = (mainChapter ? `${mainChapter.topic} · 常见误区` : '雾林拾遗 · 常见常识').slice(0, 200)
    try {
      const session = await createSession({
        topic,
        level: 'basic',
        question_count: 3,
        types: ALL_TYPES,
        kind: 'daily'
      })
      pushRecentSession({
        id: session.id,
        chapterId: session.chapter_id || undefined,
        topic,
        level: 'basic',
        status: session.status,
        createdAt: Date.now()
      })
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${session.id}` })
    } catch (err) {
      if (await handleCreateError(err, () => setLoginOpen(true))) return
      Taro.showToast({ title: errorMessage(err, '创建失败，请重试'), icon: 'none' })
    } finally {
      dailyRef.current = false
      setDailyLoading(false)
    }
  }

  const renderSkeleton = () => (
    <>
      <View className='skeleton home-skeleton-hero' />
      <View className='skeleton home-skeleton-row' />
      <View className='skeleton home-skeleton-row' />
    </>
  )

  return (
    <PageShell tabbar activeTab='home'>
      <View className='home' style={{ paddingTop: `${top + 16}px` }}>
        <View className={`home-hello ${IS_WEAPP ? 'weapp' : ''}`}>
          <View className='col home-hi-col'>
            <Text className='hi'>{greeting()}，{profile?.nickname || '旅人'}</Text>
            <Text className='name'>今天也去雾林走走？</Text>
          </View>
          <View className='row home-hello-right'>
            <View className='streak'>
              <Icon name='flame-amberdeep' size={16} />
              <Text>{streak > 0 ? `${streak} 天` : '今天'}</Text>
            </View>
            <View className='home-avatar'>
              {avatar ? (
                <Image className='home-avatar-img' src={avatar} mode='aspectFill' />
              ) : (
                <Mascot pose='head' className='mascot-head' />
              )}
            </View>
          </View>
        </View>

        {error ? (
          <ErrorCard
            title='雾林起雾了'
            message={error}
            retryLabel='重新加载'
            onRetry={load}
            backLabel='去造关'
            onBack={() => Taro.navigateTo({ url: '/pages/create/index' })}
          />
        ) : loading && !profile ? (
          renderSkeleton()
        ) : (
          <>
            <View className='hero-card rise-in' onClick={openMain}>
              <View className='hero-copy'>
                <View className='eyebrow-line'>{copy.eyebrow}</View>
                <View className='hero-title'>{topicShort(copy.title, 16)}</View>
                <View className='hero-desc'>{copy.desc}</View>
                <View className='hero-meta'>
                  <View className='hero-meta-chip'>
                    <Icon name='list-paper' size={16} />
                    <Text>{mainChapter?.question_count || 5} 题</Text>
                  </View>
                  <View className='hero-meta-chip'>
                    <Icon name='clock-paper' size={16} />
                    <Text>约 {estimateMinutes(mainChapter?.question_count || 5)} 分钟</Text>
                  </View>
                  <View className='hero-meta-chip'>
                    <Text>最佳 {starText(mainChapter?.stars || 0)}</Text>
                  </View>
                </View>
                <View className='hero-cta'>
                  <Text>{copy.cta}</Text>
                  <Icon name='arrow-right-mossdeep' size={16} />
                </View>
              </View>
              <View className='hero-stars'>
                <StarRating stars={mainChapter?.stars || 0} variant='hero' />
              </View>
              <Mascot pose='idle' className='mascot-hero' float />
            </View>

            {standardChapters.length > 0 && (
              <>
                <View className='section-row'>
                  <Text className='section-title'>你的章节</Text>
                  <Text
                    className='more'
                    onClick={() =>
                      standardChapters.length > 2
                        ? Taro.showToast({ title: '更多章节下一版开放', icon: 'none' })
                        : Taro.navigateTo({ url: '/pages/create/index' })
                    }
                  >
                    {standardChapters.length > 2 ? `全部 ${standardChapters.length} 个` : '造新章节'}
                  </Text>
                </View>

                {standardChapters.slice(0, 2).map((chapter, index) => {
                  const done = chapter.progress?.done || 0
                  const total = chapter.progress?.total || chapter.question_count
                  return (
                    <View key={chapter.id} className='chapter-mini' onClick={() => openChapter(chapter)}>
                      <View className={`chapter-icon ${index % 2 === 0 ? 'chapter-icon-moss' : 'chapter-icon-amber'}`}>
                        <Icon
                          name={index % 2 === 0 ? 'chapter-data-mossdeep' : 'chapter-cache-amberdeep'}
                          size={24}
                        />
                      </View>
                      <View className='chapter-mini-body'>
                        <View className='chapter-mini-top'>
                          <Text className='chapter-mini-title'>{topicShort(chapter.title, 14)}</Text>
                          {chapter.status === 'completed' && <Text className='tag tag-seal'>已通关</Text>}
                        </View>
                        <Text className='chapter-mini-desc'>
                          {done} / {total} 关
                          {chapter.next_title ? ` · 下一关：${chapter.next_title}` : ' · 已完成'}
                        </Text>
                        <ProgressBar value={done} max={total || 1} size='sm' tone={index % 2 === 0 ? 'moss' : 'amber'} />
                      </View>
                      <Icon name='chevron-right-ink3' size={18} />
                    </View>
                  )
                })}
              </>
            )}

            <View className='daily-strip' onClick={handleDaily}>
              <View className='daily-icon'>
                <Icon name='leaf-moss' size={24} />
              </View>
              <View className='grow'>
                <Text className='daily-title'>今日挑战 · 雾林拾遗</Text>
                <Text className='daily-desc'>3 题 · 全对得 30 积分</Text>
              </View>
              <Text className='daily-go'>{dailyLoading ? '准备中…' : '去挑战'}</Text>
            </View>

            {mode === 'mock' && <View className='mock-note'>Mock 演示模式 · 题目为本地模拟数据</View>}
          </>
        )}
        <View className='home-bottom-space' />
      </View>

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          load()
        }}
        reason='登录后可继续今日挑战，学习记录也会跟着账号走。'
      />
    </PageShell>
  )
}