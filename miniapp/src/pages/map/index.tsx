import { useCallback, useMemo, useRef, useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import Mascot from '../../components/Mascot'
import StarRating from '../../components/StarRating'
import ProgressBar from '../../components/ProgressBar'
import ErrorCard from '../../components/ErrorCard'
import LoginSheet from '../../components/LoginSheet'
import EmptyState from '../../components/EmptyState'
import { createComprehensive, getChapter, getProfile } from '../../services/api'
import type { ChapterDetail, ChapterNode, Profile } from '../../types'
import { estimateMinutes, starText, topicShort } from '../../utils/format'
import { errorMessage, handleCreateError } from '../../utils/quota'
import { FINAL_POSITION, NODE_LAYOUTS } from '../../utils/mapLayout'
import './index.css'

const LAYOUT_KEYS = [3, 5, 8]

function layoutKeyFor(count: number): number {
  if (LAYOUT_KEYS.includes(count)) return count
  if (count <= 3) return 3
  if (count <= 5) return 5
  return 8
}

function nodeClass(node: ChapterNode): string {
  if (node.kind === 'comprehensive') {
    return `map-node final ${node.status === 'done' ? 'done' : node.status === 'current' ? 'current' : node.status === 'unlocked' ? 'unlocked' : 'locked'}`
  }
  return `map-node ${node.status === 'done' ? 'done' : node.status === 'current' ? 'current' : 'locked'}`
}

export default function MapPage() {
  const router = useRouter()
  const chapterId = router.params?.chapterId || ''
  const [chapter, setChapter] = useState<ChapterDetail | null>(null)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [selectedSeq, setSelectedSeq] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const creatingRef = useRef(false)

  const load = useCallback(async () => {
    if (!chapterId) {
      setLoading(false)
      setError('缺少章节信息')
      return
    }
    setLoading(true)
    try {
      const [detail, profileData] = await Promise.all([getChapter(chapterId), getProfile()])
      setChapter(detail)
      setProfile(profileData)
      setSelectedSeq(detail.current_node || 1)
      setError('')
    } catch (err) {
      setError((err as Error).message || '章节加载失败')
    } finally {
      setLoading(false)
    }
  }, [chapterId])

  useDidShow(() => {
    load()
  })

  const layoutKey = layoutKeyFor(chapter?.question_count || 5)
  const positions = useMemo(() => {
    if (!chapter) return []
    const base = NODE_LAYOUTS[layoutKey] || NODE_LAYOUTS[5]
    const nodes = chapter.nodes.filter((n) => n.kind === 'question')
    return nodes.map((node, index) => {
      const pos = base[Math.min(index, base.length - 1)]
      return { node, x: pos[0], y: pos[1] }
    })
  }, [chapter, layoutKey])

  const finalNode = chapter?.nodes.find((n) => n.kind === 'comprehensive')
  const finalPosition = FINAL_POSITION[layoutKey] || FINAL_POSITION[5]
  const selected = chapter?.nodes.find((n) => n.seq === selectedSeq) || chapter?.nodes[0]
  const isCompleted = chapter?.status === 'completed'
  const isReady = chapter?.status === 'ready'
  const isFailed = chapter?.status === 'failed'
  const isGenerating = !!chapter && ['queued', 'searching', 'digesting', 'generating'].includes(chapter.status)

  const toast = (title: string) => Taro.showToast({ title, icon: 'none' })

  const startQuiz = (seq: number, sessionId = chapter?.session_id) => {
    if (!chapter || !sessionId) return
    Taro.navigateTo({ url: `/pages/quiz/index?sessionId=${sessionId}&startSeq=${seq}` })
  }

  const openReport = (sessionId?: string | null) => {
    if (!sessionId) return
    Taro.navigateTo({ url: `/pages/report/index?sessionId=${sessionId}` })
  }

  const handleComprehensive = async () => {
    if (!chapter || creatingRef.current) return
    if (finalNode?.status === 'done' && finalNode.session_id) {
      openReport(finalNode.session_id)
      return
    }
    if (finalNode?.status === 'current' && finalNode.session_id) {
      startQuiz(1, finalNode.session_id)
      return
    }
    if (finalNode?.status !== 'unlocked') {
      toast('前 5 关全部满星后解锁章末综合')
      return
    }
    creatingRef.current = true
    setCreating(true)
    try {
      const session = await createComprehensive(chapter.id)
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${session.id}` })
    } catch (err) {
      if (await handleCreateError(err, () => setLoginOpen(true))) return
      toast(errorMessage(err, '生成失败，请重试'))
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }

  const handlePrimary = () => {
    if (!chapter || !selected) return
    if (isGenerating) {
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${chapter.session_id}` })
      return
    }
    if (isFailed) {
      Taro.navigateTo({ url: `/pages/generating/index?sessionId=${chapter.session_id}` })
      return
    }
    if (selected.kind === 'comprehensive') {
      handleComprehensive()
      return
    }
    if (selected.status === 'locked') {
      toast('完成上一关解锁')
      return
    }
    if (isCompleted) {
      openReport(chapter.session_id)
      return
    }
    startQuiz(selected.seq)
  }

  const primaryLabel = (() => {
    if (!chapter || !selected) return '开始闯关'
    if (isGenerating) return '查看生成进度'
    if (isFailed) return '重新生成'
    if (selected.kind === 'comprehensive') {
      if (selected.status === 'done') return '查看综合报告'
      if (selected.status === 'current') return '继续综合关'
      if (selected.status === 'unlocked') return creating ? '正在造关…' : '生成章末综合'
      return '完成前 5 关解锁'
    }
    if (selected.status === 'locked') return '完成上一关解锁'
    if (isCompleted) return '查看本关报告'
    return '开始闯关'
  })()

  const sheetSub = (() => {
    if (!chapter || !selected) return ''
    if (selected.kind === 'comprehensive') {
      return `3 题 · 约 3 分钟 · ${selected.status === 'done' ? `最佳 ${starText(selected.stars)}` : '前 5 关满星解锁'}`
    }
    return `${chapter.question_count} 题 · 约 ${estimateMinutes(chapter.question_count)} 分钟 · 最佳 ${starText(chapter.stars)}`
  })()

  if (loading && !chapter) {
    return (
      <PageShell>
        <PageHeader back title='章节地图' />
        <View className='map-skeleton'>
          <View className='skeleton map-skeleton-canvas' />
          <View className='skeleton map-skeleton-sheet' />
        </View>
      </PageShell>
    )
  }

  if (error || !chapter) {
    return (
      <PageShell>
        <PageHeader back title='章节地图' />
        <ErrorCard
          title='地图没展开'
          message={error || '章节不存在'}
          retryLabel='重新加载'
          onRetry={load}
          backLabel='回首页'
          onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
        />
      </PageShell>
    )
  }

  return (
    <PageShell>
      <PageHeader
        back
        title={
          <View className='map-title'>
            <Text className='map-title-k'>CHAPTER</Text>
            <Text className='map-title-t'>{topicShort(chapter.title, 16)}</Text>
          </View>
        }
        right={
          <View className='leaf-count'>
            <Icon name='leaf-moss' size={16} />
            <Text>{profile?.leaf_count || 0}</Text>
          </View>
        }
      />

      <View className='map-canvas-wrap'>
        <View className='map-canvas'>
          <Image
            className='map-path'
            src={`/assets/map/path-${layoutKey}.svg`}
            mode='scaleToFill'
          />
          {positions.map(({ node, x, y }) => (
            <View
              key={node.seq}
              className='map-node-wrap'
              style={{ left: `${x}%`, top: `${y}%` }}
              onClick={() => setSelectedSeq(node.seq)}
            >
              {node.status === 'current' && (
                <Mascot pose='idle' className='map-mascot' float />
              )}
              <View className={nodeClass(node)}>
                {node.status === 'done' ? (
                  <Icon name='check-paper' size={18} />
                ) : node.status === 'current' ? (
                  <Text>{node.seq}</Text>
                ) : (
                  <Icon name='lock-ink3' size={16} />
                )}
              </View>
              <View className='map-label'>{topicShort(node.title, 8)}</View>
            </View>
          ))}

          {finalNode && (
            <View
              className='map-node-wrap'
              style={{ left: `${finalPosition[0]}%`, top: `${finalPosition[1]}%` }}
              onClick={() => setSelectedSeq(finalNode.seq)}
            >
              {finalNode.status === 'current' && (
                <Mascot pose='idle' className='map-mascot' float />
              )}
              <View className={nodeClass(finalNode)}>
                {finalNode.status === 'done' ? (
                  <Icon name='check-paper' size={18} />
                ) : finalNode.status === 'unlocked' ? (
                  <Icon name='sparkle-amber' size={18} />
                ) : finalNode.status === 'current' ? (
                  <Text>终</Text>
                ) : (
                  <Icon name='lock-ink3' size={16} />
                )}
              </View>
              <View className='map-label'>章末 · 综合</View>
            </View>
          )}

          <View className='map-fog' />
        </View>

        <View className='map-progress-card'>
          <View className='row between'>
            <Text className='section-title'>本章进度</Text>
            <Text className='map-progress-num'>
              {chapter.progress.done} / {chapter.progress.total} 关
            </Text>
          </View>
          <ProgressBar value={chapter.progress.done} max={chapter.progress.total || 1} />
        </View>
      </View>

      {selected && (
        <View className='sheet map-sheet'>
          <View className='sheet-grab' />
          <View className='map-sheet-row'>
            <View className='grow'>
              <Text className='map-sheet-title'>
                {selected.kind === 'comprehensive'
                  ? '章末 · 综合'
                  : `第 ${selected.seq} 关 · ${selected.title}`}
              </Text>
              <Text className='map-sheet-sub'>{sheetSub}</Text>
              <View className='map-sheet-stars'>
                <StarRating stars={selected.kind === 'comprehensive' ? selected.stars : chapter.stars} size='sm' />
              </View>
            </View>
            <View className='chip chip-amber'>
              {isCompleted ? '已完成' : isGenerating ? '生成中' : isFailed ? '待重试' : '继续上次'}
            </View>
          </View>
          <View
            className={`btn btn-primary map-start ${primaryLabel.startsWith('完成') ? 'btn-disabled' : ''}`}
            onClick={primaryLabel.startsWith('完成') ? () => toast(primaryLabel) : handlePrimary}
          >
            {primaryLabel}
          </View>
        </View>
      )}
      <View className='map-bottom-space' />

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          load()
        }}
        reason='登录后可继续章末综合，学习记录也会跟着账号走。'
      />
    </PageShell>
  )
}