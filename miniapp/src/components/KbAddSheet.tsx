import { useEffect, useState } from 'react'
import { Input, Text, Textarea, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './KbAddSheet.css'

export type KbAddMode = 'url' | 'text'

interface KbAddSheetProps {
  open: boolean
  mode: KbAddMode
  loading?: boolean
  onClose: () => void
  onSubmit: (payload: { url?: string; title?: string; text?: string }) => void
}

export default function KbAddSheet({ open, mode, loading = false, onClose, onSubmit }: KbAddSheetProps) {
  const [url, setUrl] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')

  useEffect(() => {
    if (!open) return
    setUrl('')
    setTitle('')
    setText('')
  }, [open, mode])

  if (!open) return null

  const submit = () => {
    if (loading) return
    if (mode === 'url') {
      const value = url.trim()
      if (!/^https?:\/\//i.test(value)) {
        Taro.showToast({ title: '请粘贴 http(s) 链接', icon: 'none' })
        return
      }
      onSubmit({ url: value, title: title.trim() })
      return
    }
    const content = text.trim()
    if (content.length < 1) {
      Taro.showToast({ title: '先粘贴一些文字', icon: 'none' })
      return
    }
    onSubmit({ title: title.trim() || '粘贴文本', text: content })
  }

  return (
    <>
      <View className='sheet-mask' onClick={onClose} />
      <View className='sheet kb-sheet'>
        <View className='sheet-grab' />
        <View className='kb-sheet-head'>
          <View>
            <View className='kb-sheet-title'>{mode === 'url' ? '添加网页链接' : '粘贴文本'}</View>
            <View className='kb-sheet-sub'>
              {mode === 'url'
                ? '会抓取网页正文并切片；需要登录或反爬的页面建议改用粘贴文本。'
                : '适合内部制度、客服话术、会议纪要等没有现成文件的资料。'}
            </View>
          </View>
          <View className='kb-sheet-close' onClick={onClose}>
            <Text>关闭</Text>
          </View>
        </View>

        {mode === 'url' ? (
          <>
            <Text className='kb-field-label'>链接</Text>
            <Input
              className='kb-input'
              value={url}
              placeholder='https://example.com/article'
              placeholderClass='kb-placeholder'
              onInput={(event) => setUrl(event.detail.value)}
            />
            <Text className='kb-field-label'>标题（可选）</Text>
            <Input
              className='kb-input'
              value={title}
              maxlength={200}
              placeholder='不填会使用网页标题'
              placeholderClass='kb-placeholder'
              onInput={(event) => setTitle(event.detail.value)}
            />
          </>
        ) : (
          <>
            <Text className='kb-field-label'>标题</Text>
            <Input
              className='kb-input'
              value={title}
              maxlength={200}
              placeholder='例如：客服退款话术'
              placeholderClass='kb-placeholder'
              onInput={(event) => setTitle(event.detail.value)}
            />
            <Text className='kb-field-label'>正文</Text>
            <Textarea
              className='kb-textarea'
              value={text}
              maxlength={200000}
              placeholder='把资料内容粘贴到这里…'
              placeholderClass='kb-placeholder'
              onInput={(event) => setText(event.detail.value)}
            />
            <Text className='kb-field-hint'>{text.length} / 200000 字</Text>
          </>
        )}

        <View className='kb-sheet-actions'>
          <View className='btn btn-ghost btn-sm' onClick={onClose}>
            取消
          </View>
          <View className={`btn btn-primary btn-sm ${loading ? 'btn-disabled' : ''}`} onClick={submit}>
            {loading ? '处理中…' : '添加并切片'}
          </View>
        </View>
      </View>
    </>
  )
}