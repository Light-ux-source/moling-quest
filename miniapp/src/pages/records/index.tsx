import { useCallback, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, useReachBottom } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import ErrorCard from '../../components/ErrorCard'
import Mascot from '../../components/Mascot'
import StarRating from '../../components/StarRating'
import { getProfile, getRecords } from '../../services/api'
import { formatDateTime } from '../../utils/format'
import type { Profile, RecordItem } from '../../types'
import './index.css'

const PAGE_SIZE = 20

export default function RecordsPage() {
  const [items, setItems] = useState<RecordItem[]>([])
  const [total, setTotal] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async (reset = true) => {
    if (reset) {
      setLoading(true)
      setError('')
    } else {
      setLoadingMore(true)
    }
    try {
      const offset = reset ? 0 : items.length
      const [records, profileData] = await Promise.all([
        getRecords(PAGE_SIZE, offset),
        reset ? getProfile().catch(() => null) : Promise.resolve(null)
      ])
      setItems(reset ? records.items : [...items, ...records.items])
      setTotal(records.total)
      setHasMore(records.has_more)
      if (profileData) setProfile(profileData)
    } catch (err) {
      setError((err as Error).message || '记录加载失败')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [items])

  useDidShow(() => {
    load(true)
  })

  useReachBottom(() => {
    if (hasMore && !loadingMore && !loading) load(false)
  })

  const renderItem = (item: RecordItem) => (
    <View key={item.id} className='record-card'>
      <View className='record-top'>
        <View className={`record-status ${item.status}`}>{item.status_label}</View>
        <Text className='record-date'>{formatDateTime(item.created_at)}</Text>
      </View>
      <Text className='record-topic'>{item.topic}</Text>
      <View className='record-meta'>
        <Text className='record-meta-item'>{item.question_count} 题</Text>
        <Text className='record-meta-item'>{item.level_label}</Text>
        {item.status === 'completed' ? (
          <>
            <Text className='record-meta-item'>正确率 {Math.round(item.accuracy * 100)}%</Text>
            <View className='record-stars'>
              <StarRating stars={item.stars} size='sm' />
            </View>
          </>
        ) : (
          <Text className='record-meta-item'>{item.status_label}</Text>
        )}
        <Text className={`record-points ${item.status === 'completed' ? '' : 'pending'}`}>
          {item.status === 'completed' ? `+${item.points} 积分` : '—'}
        </Text>
      </View>
    </View>
  )

  return (
    <PageShell>
      <PageHeader back title='学习记录' />
      <View className='records-page'>
        <View className='records-head'>
          <View>
            <Text className='records-title'>走过的每一段路</Text>
            <Text className='records-sub'>按时间倒序，只记录自己的进度。</Text>
          </View>
          <View className='chip chip-ghost'>{total} 条</View>
        </View>

        <View className='records-summary'>
          <View className='records-summary-item'>
            <Text className='records-summary-num'>{total}</Text>
            <Text className='records-summary-label'>学习记录</Text>
          </View>
          <View className='records-summary-divider' />
          <View className='records-summary-item'>
            <Text className='records-summary-num'>{profile?.points ?? 0}</Text>
            <Text className='records-summary-label'>累计积分</Text>
          </View>
          <View className='records-summary-divider' />
          <View className='records-summary-item'>
            <Text className='records-summary-num'>{profile?.streak_days ?? 0}</Text>
            <Text className='records-summary-label'>连续天</Text>
          </View>
        </View>

        {loading ? (
          <View className='records-loading'>
            <Mascot pose='thinking' className='mascot-orb' />
            <Text className='records-loading-text'>正在翻找走过的路…</Text>
          </View>
        ) : error ? (
          <ErrorCard
            title='记录没有翻出来'
            message={error}
            retryLabel='重新加载'
            onRetry={() => load(true)}
            backLabel='回首页'
            onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
          />
        ) : items.length === 0 ? (
          <View className='records-empty'>
            <Mascot pose='idle' className='mascot-empty' />
            <Text className='records-empty-title'>还没有学习记录</Text>
            <Text className='records-empty-desc'>去走一段新路，这里就会留下脚印。</Text>
            <View
              className='btn btn-primary records-empty-btn'
              onClick={() => Taro.navigateTo({ url: '/pages/create/index' })}
            >
              去造一条新路
            </View>
          </View>
        ) : (
          <>
            <View className='records-list'>{items.map(renderItem)}</View>
            <View className='records-load-more'>
              {hasMore ? (
                <View
                  className={`chip chip-ghost ${loadingMore ? 'disabled' : ''}`}
                  onClick={() => !loadingMore && load(false)}
                >
                  {loadingMore ? '加载中…' : '加载更多'}
                </View>
              ) : (
                <Text className='records-end'>已经走到记录的最早一页</Text>
              )}
            </View>
          </>
        )}

        <Text className='records-note'>
          学习记录仅展示列表；报告详情仍从答题结算页进入。
        </Text>
        <View className='records-bottom-space' />
      </View>
    </PageShell>
  )
}
