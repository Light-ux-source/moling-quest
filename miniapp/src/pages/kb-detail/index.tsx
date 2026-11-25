import { useCallback, useEffect, useState } from 'react'
import { Text, View } from '@tarojs/components'
import Taro, { useDidShow, useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Icon from '../../components/Icon'
import ProgressBar from '../../components/ProgressBar'
import ErrorCard from '../../components/ErrorCard'
import KbAddSheet, { KbAddMode } from '../../components/KbAddSheet'
import {
  addKbText,
  addKbUrl,
  deleteKbDocument,
  deleteKnowledgeBase,
  getKnowledgeBase,
  pollKbDocument,
  retryKbDocument,
  uploadKbFile
} from '../../services/api'
import type { KbDetail, KbDocument } from '../../types'
import { formatDate } from '../../utils/format'
import { pickFile } from '../../utils/upload'
import './index.css'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中',
  parsing: '解析中',
  chunking: '分块中',
  embedding: '向量化',
  ready: '已就绪',
  failed: '处理失败'
}

function isProcessing(doc: KbDocument): boolean {
  return !['ready', 'failed'].includes(doc.status)
}

function formatBytes(value: number): string {
  if (!value) return ''
  if (value < 1024) return `${value}B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)}KB`
  return `${(value / 1024 / 1024).toFixed(1)}MB`
}

function docIcon(doc: KbDocument): string {
  if (doc.kind === 'web') return 'share-ink'
  if (doc.kind === 'text') return 'list-paper'
  return 'tab-book-ink3'
}

export default function KbDetailPage() {
  const router = useRouter()
  const kbId = router.params?.kbId || ''
  const [detail, setDetail] = useState<KbDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [sheetMode, setSheetMode] = useState<KbAddMode | null>(null)
  const [sheetLoading, setSheetLoading] = useState(false)

  const load = useCallback(
    async (silent = false) => {
      if (!kbId) {
        setError('缺少资料库')
        setLoading(false)
        return
      }
      if (!silent) setLoading(true)
      try {
        const data = await getKnowledgeBase(kbId)
        setDetail(data)
        setError('')
      } catch (err) {
        if (!silent) setError((err as Error).message || '资料库加载失败')
      } finally {
        if (!silent) setLoading(false)
      }
    },
    [kbId]
  )

  useDidShow(() => {
    load()
  })

  const processing = !!detail?.documents?.some(isProcessing)
  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => load(true), 1500)
    return () => clearInterval(timer)
  }, [processing, load])

  const handlePickFile = async () => {
    if (uploading) return
    const file = await pickFile()
    if (!file) return
    const max = detail?.limits?.max_file_bytes || 20 * 1024 * 1024
    if (file.size > max) {
      file.revoke?.()
      Taro.showToast({ title: `文件不能超过 ${Math.round(max / 1024 / 1024)}MB`, icon: 'none' })
      return
    }
    setUploading(true)
    try {
      const doc = await uploadKbFile(kbId, file.path, file.name)
      file.revoke?.()
      setDetail((prev) =>
        prev ? { ...prev, documents: [doc, ...prev.documents] } : prev
      )
      await load(true)
      Taro.showToast({ title: '已加入，正在切片', icon: 'none' })
      pollKbDocument(kbId, doc.id).then(() => load(true)).catch(() => undefined)
    } catch (err) {
      file.revoke?.()
      Taro.showToast({ title: (err as Error).message || '上传失败', icon: 'none' })
    } finally {
      setUploading(false)
    }
  }

  const submitAdd = async (payload: { url?: string; title?: string; text?: string }) => {
    if (!sheetMode || sheetLoading) return
    setSheetLoading(true)
    try {
      const doc =
        sheetMode === 'url'
          ? await addKbUrl(kbId, payload.url || '', payload.title)
          : await addKbText(kbId, payload.title || '粘贴文本', payload.text || '')
      setSheetMode(null)
      setDetail((prev) =>
        prev ? { ...prev, documents: [doc, ...prev.documents] } : prev
      )
      await load(true)
      Taro.showToast({ title: '已加入，正在切片', icon: 'none' })
      pollKbDocument(kbId, doc.id).then(() => load(true)).catch(() => undefined)
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '添加失败', icon: 'none' })
    } finally {
      setSheetLoading(false)
    }
  }

  const retryDoc = async (doc: KbDocument) => {
    try {
      await retryKbDocument(kbId, doc.id)
      await load(true)
      pollKbDocument(kbId, doc.id).then(() => load(true)).catch(() => undefined)
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '重试失败', icon: 'none' })
    }
  }

  const removeDoc = async (doc: KbDocument) => {
    const res = await Taro.showModal({
      title: '删除这份资料？',
      content: '对应的片段和向量也会删掉，已生成的题目不受影响。',
      confirmText: '删除',
      confirmColor: '#BF5B42',
      cancelText: '取消'
    })
    if (!res.confirm) return
    try {
      await deleteKbDocument(kbId, doc.id)
      await load()
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '删除失败', icon: 'none' })
    }
  }

  const removeKb = async () => {
    if (!detail) return
    const res = await Taro.showModal({
      title: `删除「${detail.name}」？`,
      content: '资料库、资料、片段与向量都会被删除，且无法恢复。',
      confirmText: '删除',
      confirmColor: '#BF5B42',
      cancelText: '取消'
    })
    if (!res.confirm) return
    try {
      await deleteKnowledgeBase(kbId)
      Taro.navigateBack().catch(() => Taro.reLaunch({ url: '/pages/kb/index' }))
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '删除失败', icon: 'none' })
    }
  }

  if (error && !detail) {
    return (
      <PageShell>
        <PageHeader back title='资料库' />
        <ErrorCard
          title='资料库没打开'
          message={error}
          onRetry={() => load()}
          retryLabel='重新加载'
          onBack={() => Taro.reLaunch({ url: '/pages/kb/index' })}
          backLabel='返回列表'
        />
      </PageShell>
    )
  }

  if (loading && !detail) {
    return (
      <PageShell>
        <PageHeader back title='资料库' />
        <View className='kb-page'>
          <View className='skeleton kb-skeleton' />
          <View className='skeleton kb-skeleton' />
        </View>
      </PageShell>
    )
  }

  const kb = detail
  const docs = kb?.documents || []
  const processingCount = docs.filter(isProcessing).length

  return (
    <PageShell>
      <PageHeader
        back
        title='资料库'
        right={<View className='chip chip-ghost'>{docs.length} 份</View>}
      />
      {kb ? (
        <View className='kb-page'>
          <View className='kb-detail-hero'>
            <View className='kb-detail-icon'>
              <Icon name='tab-book-mossdeep' size={28} />
            </View>
            <View className='grow'>
              <View className='kb-detail-name'>{kb.name}</View>
              <View className='kb-detail-meta'>
                {kb.doc_count} 份资料 · {kb.chunk_count} 个片段
                {processingCount > 0 ? ` · ${processingCount} 份处理中` : ''}
              </View>
              <View className='kb-detail-date'>更新于 {formatDate(kb.updated_at)}</View>
            </View>
          </View>

          <View className='kb-actions'>
            <View className={`kb-action ${uploading ? 'kb-action-disabled' : ''}`} onClick={handlePickFile}>
              <View className='kb-action-icon'>
                <Icon name='tab-book-mossdeep' size={24} />
              </View>
              <Text className='kb-action-title'>{uploading ? '上传中…' : '上传文件'}</Text>
              <Text className='kb-action-desc'>PDF / Word / PPT / Excel / 文本</Text>
            </View>
            <View className='kb-action' onClick={() => setSheetMode('url')}>
              <View className='kb-action-icon'>
                <Icon name='share-ink' size={24} />
              </View>
              <Text className='kb-action-title'>网页链接</Text>
              <Text className='kb-action-desc'>抓取正文并切片</Text>
            </View>
            <View className='kb-action' onClick={() => setSheetMode('text')}>
              <View className='kb-action-icon'>
                <Icon name='list-paper' size={24} />
              </View>
              <Text className='kb-action-title'>粘贴文本</Text>
              <Text className='kb-action-desc'>制度 / 话术 / 纪要</Text>
            </View>
          </View>

          <View className='kb-section-row'>
            <Text className='section-title'>资料</Text>
            <Text className='kb-section-hint'>
              {kb.limits.max_docs_per_kb} 份上限 · 单文件 {Math.round(kb.limits.max_file_bytes / 1024 / 1024)}MB
            </Text>
          </View>

          {docs.length === 0 ? (
            <View className='kb-empty-docs'>
              <Text className='kb-empty-title'>还没有资料</Text>
              <Text className='kb-empty-text'>
                先上传一份 PDF、Word，或粘贴一段内部文档。处理完成后就能用它出题。
              </Text>
              <View className='btn btn-primary btn-sm' onClick={handlePickFile}>
                上传第一份资料
              </View>
            </View>
          ) : (
            <View className='kb-doc-list'>
              {docs.map((doc) => (
                <View key={doc.id} className={`kb-doc ${doc.status === 'failed' ? 'failed' : ''}`}>
                  <View className='kb-doc-icon'>
                    <Icon name={docIcon(doc)} size={20} />
                  </View>
                  <View className='grow'>
                    <View className='kb-doc-top'>
                      <Text className='kb-doc-title'>{doc.title}</Text>
                      <View className={`kb-doc-status ${doc.status}`}>
                        {STATUS_LABEL[doc.status] || doc.status}
                      </View>
                    </View>
                    <Text className='kb-doc-meta'>
                      {doc.kind === 'web' ? '网页' : doc.kind === 'text' ? '文本' : '文件'}
                      {doc.size_bytes ? ` · ${formatBytes(doc.size_bytes)}` : ''}
                      {doc.chunk_count ? ` · ${doc.chunk_count} 个片段` : ''}
                    </Text>
                    {isProcessing(doc) ? (
                      <ProgressBar value={doc.progress} max={100} size='sm' />
                    ) : null}
                    {doc.status === 'failed' ? (
                      <Text className='kb-doc-error'>{doc.error || '处理失败，可以重试'}</Text>
                    ) : null}
                  </View>
                  <View className='kb-doc-actions'>
                    {doc.status === 'failed' ? (
                      <View className='kb-doc-action' onClick={() => retryDoc(doc)}>
                        <Icon name='refresh-mossdeep' size={16} />
                      </View>
                    ) : null}
                    <View className='kb-doc-action' onClick={() => removeDoc(doc)}>
                      <Icon name='close-ink3' size={16} />
                    </View>
                  </View>
                </View>
              ))}
            </View>
          )}

          <View className='kb-detail-footer'>
            <Text className='kb-detail-footer-text'>
              资料只对你可见 · 出题时会标注文档与页码
            </Text>
            <Text className='kb-delete-kb' onClick={removeKb}>
              删除资料库
            </Text>
          </View>
          <View className='kb-bottom-space' />
        </View>
      ) : null}

      <KbAddSheet
        open={!!sheetMode}
        mode={sheetMode || 'url'}
        loading={sheetLoading}
        onClose={() => setSheetMode(null)}
        onSubmit={submitAdd}
      />
    </PageShell>
  )
}