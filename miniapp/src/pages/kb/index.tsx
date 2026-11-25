import { useCallback, useState } from 'react'
import { Input, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import EmptyState from '../../components/EmptyState'
import ErrorCard from '../../components/ErrorCard'
import { createKnowledgeBase, getKnowledgeBases } from '../../services/api'
import type { KbList, KbSummary } from '../../types'
import { formatDate } from '../../utils/format'
import './index.css'

export default function KbListPage() {
  const [data, setData] = useState<KbList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const result = await getKnowledgeBases()
      setData(result)
      setError('')
    } catch (err) {
      if (!silent) setError((err as Error).message || '资料库加载失败')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useDidShow(() => {
    load()
  })

  const openCreate = () => {
    setName('')
    setCreateOpen(true)
  }

  const submitCreate = async () => {
    const value = name.trim()
    if (value.length < 1) {
      Taro.showToast({ title: '先给资料库起个名字', icon: 'none' })
      return
    }
    if (creating) return
    setCreating(true)
    try {
      const kb = await createKnowledgeBase(value, '')
      setCreateOpen(false)
      setName('')
      await load()
      Taro.navigateTo({ url: `/pages/kb-detail/index?kbId=${kb.id}` })
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '创建失败', icon: 'none' })
    } finally {
      setCreating(false)
    }
  }

  const openKb = (kb: KbSummary) => {
    Taro.navigateTo({ url: `/pages/kb-detail/index?kbId=${kb.id}` })
  }

  const limits = data?.limits
  const items = data?.items || []

  return (
    <PageShell>
      <PageHeader
        back
        title='我的资料库'
        right={
          limits?.can_create ? (
            <View className='chip chip-active' onClick={openCreate}>
              新建
            </View>
          ) : null
        }
      />
      <View className='kb-page'>
        <View className='kb-hero'>
          <View className='kb-eyebrow'>PRIVATE KNOWLEDGE</View>
          <View className='kb-title'>把资料变成题目</View>
          <View className='kb-sub'>
            上传内部培训、客服知识库或文档，AI 只依据这些资料出题，并逐题标注来源。
          </View>
          <View className='kb-hero-stats'>
            <View className='kb-stat'>
              <Text className='kb-stat-num'>{items.length}</Text>
              <Text className='kb-stat-label'>资料库</Text>
            </View>
            <View className='kb-stat-divider' />
            <View className='kb-stat'>
              <Text className='kb-stat-num'>
                {items.reduce((sum, item) => sum + (item.doc_count || 0), 0)}
              </Text>
              <Text className='kb-stat-label'>份资料</Text>
            </View>
            <View className='kb-stat-divider' />
            <View className='kb-stat'>
              <Text className='kb-stat-num'>
                {items.reduce((sum, item) => sum + (item.chunk_count || 0), 0)}
              </Text>
              <Text className='kb-stat-label'>个片段</Text>
            </View>
          </View>
        </View>

        {createOpen ? (
          <View className='kb-create-panel'>
            <Text className='kb-panel-title'>新建资料库</Text>
            <Input
              className='kb-input'
              value={name}
              maxlength={40}
              placeholder='例如：客服知识库 / 新人培训 / 产品手册'
              placeholderClass='kb-placeholder'
              onInput={(event) => setName(event.detail.value.slice(0, 40))}
            />
            <View className='kb-create-actions'>
              <View className='btn btn-ghost btn-sm' onClick={() => setCreateOpen(false)}>
                取消
              </View>
              <View
                className={`btn btn-primary btn-sm ${creating ? 'btn-disabled' : ''}`}
                onClick={submitCreate}
              >
                {creating ? '创建中…' : '创建'}
              </View>
            </View>
          </View>
        ) : null}

        {error ? (
          <ErrorCard title='资料库没打开' message={error} onRetry={() => load()} retryLabel='重新加载' />
        ) : loading && !data ? (
          <>
            <View className='skeleton kb-skeleton' />
            <View className='skeleton kb-skeleton' />
          </>
        ) : items.length === 0 ? (
          <EmptyState
            title='还没有资料库'
            text='建一个资料库，把 PDF、Word、PPT、网页或粘贴文本放进去，就能开始出题。'
            actionLabel='建第一个资料库'
            onAction={openCreate}
          />
        ) : (
          <View className='kb-list'>
            {items.map((kb) => (
              <View key={kb.id} className='kb-card' onClick={() => openKb(kb)}>
                <View className='kb-card-icon'>
                  <Icon name='tab-book-mossdeep' size={24} />
                </View>
                <View className='grow'>
                  <View className='kb-card-top'>
                    <Text className='kb-card-name'>{kb.name}</Text>
                    {kb.is_guest ? <Text className='tag tag-seal'>游客</Text> : null}
                  </View>
                  <Text className='kb-card-meta'>
                    {kb.doc_count} 份资料 · {kb.chunk_count} 个片段
                  </Text>
                  <Text className='kb-card-date'>更新于 {formatDate(kb.updated_at)}</Text>
                </View>
                <Icon name='chevron-right-ink3' size={16} />
              </View>
            ))}
          </View>
        )}

        {limits ? (
          <View className='kb-limit-note'>
            {limits.can_create
              ? `还可以建 ${limits.remaining_kbs} 个资料库 · 每个最多 ${limits.max_docs_per_kb} 份资料`
              : `资料库数量已达上限（${limits.max_kbs} 个），删掉一个再建`}
          </View>
        ) : null}
        <View className='kb-bottom-space' />
      </View>
    </PageShell>
  )
}