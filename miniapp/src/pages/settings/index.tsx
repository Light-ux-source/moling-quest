import { useCallback, useState } from 'react'
import { Button, Image, Input, Switch, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Mascot from '../../components/Mascot'
import LoginSheet from '../../components/LoginSheet'
import ErrorCard from '../../components/ErrorCard'
import { STORAGE_KEYS, IS_WEAPP } from '../../config'
import {
  clearAuthSession,
  deleteAccount,
  getProfile,
  resolveMediaUrl,
  updateProfile,
  updateSettings,
  uploadAvatar
} from '../../services/api'
import { signOut } from '../../services/auth'
import type { Profile } from '../../types'
import './index.css'

export default function SettingsPage() {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [nickname, setNickname] = useState('')
  const [avatarTemp, setAvatarTemp] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [loginOpen, setLoginOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getProfile()
      setProfile(data)
      setNickname(data.nickname || '')
      setError('')
    } catch (err) {
      setError((err as Error).message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useDidShow(() => {
    load()
  })

  const openLogin = () => setLoginOpen(true)

  const chooseAvatar = async () => {
    if (!profile?.is_logged_in) {
      openLogin()
      return
    }
    try {
      const res = await Taro.chooseImage({ count: 1, sizeType: ['compressed'], sourceType: ['album', 'camera'] })
      const path = res.tempFilePaths?.[0]
      if (path) setAvatarTemp(path)
    } catch (err) {
      // 用户取消选择时不提示
    }
  }

  const handleChooseAvatar = (event: any) => {
    const url = event?.detail?.avatarUrl
    if (url) setAvatarTemp(url)
  }

  const saveProfile = async () => {
    if (!profile?.is_logged_in) {
      openLogin()
      return
    }
    const value = nickname.trim()
    if (value.length < 1 || value.length > 16) {
      Taro.showToast({ title: '昵称需要 1–16 个字符', icon: 'none' })
      return
    }
    if (saving) return
    setSaving(true)
    try {
      if (value !== profile.nickname) {
        await updateProfile({ nickname: value })
      }
      if (avatarTemp) {
        const uploaded = await uploadAvatar(avatarTemp)
        await updateProfile({ avatar_url: uploaded.avatar_url })
        setAvatarTemp('')
      }
      Taro.showToast({ title: '资料已保存', icon: 'success' })
      await load()
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '保存失败', icon: 'none' })
    } finally {
      setSaving(false)
    }
  }

  const toggleReminder = async (value: boolean) => {
    if (!profile?.is_logged_in) {
      openLogin()
      return
    }
    const previous = profile
    setProfile({ ...profile, settings: { reminder_enabled: value } })
    try {
      await updateSettings({ reminder_enabled: value })
    } catch (err) {
      setProfile(previous)
      Taro.showToast({ title: (err as Error).message || '保存失败', icon: 'none' })
    }
  }

  const clearCache = async () => {
    const res = await Taro.showModal({
      title: '清除本地缓存',
      content: '会清理最近学习、草稿等本地数据，不会删除服务端的学习记录。',
      confirmText: '清除'
    })
    if (!res.confirm) return
    try {
      Taro.removeStorageSync(STORAGE_KEYS.recentSessions)
      Taro.removeStorageSync(STORAGE_KEYS.drafts)
      Taro.removeStorageSync(STORAGE_KEYS.lastChapter)
      Taro.showToast({ title: '本地缓存已清理', icon: 'success' })
    } catch (err) {
      Taro.showToast({ title: '清理失败，请重试', icon: 'none' })
    }
  }

  const handleLogout = async () => {
    const res = await Taro.showModal({
      title: '退出登录',
      content: '退出后这台设备回到游客状态，服务端的学习记录会保留。',
      confirmText: '退出'
    })
    if (!res.confirm) return
    await signOut()
    Taro.reLaunch({ url: '/pages/index/index' })
  }

  const handleDelete = async () => {
    const first = await Taro.showModal({
      title: '注销账号',
      content: '注销后账号不可恢复，昵称/头像等个人信息会被删除，学习记录将匿名化保留统计。确定继续吗？',
      confirmText: '继续',
      confirmColor: '#BF5B42'
    })
    if (!first.confirm) return
    const second = await Taro.showModal({
      title: '最后确认',
      content: '确定要注销当前账号吗？此操作不可撤销。',
      confirmText: '注销',
      confirmColor: '#BF5B42'
    })
    if (!second.confirm) return
    try {
      await deleteAccount()
      clearAuthSession()
      Taro.showToast({ title: '账号已注销', icon: 'success' })
      setTimeout(() => Taro.reLaunch({ url: '/pages/index/index' }), 800)
    } catch (err) {
      Taro.showToast({ title: (err as Error).message || '注销失败，请重试', icon: 'none' })
    }
  }

  const openPage = (type: string) => {
    Taro.navigateTo({ url: `/pages/about/index?type=${type}` })
  }

  if (loading && !profile) {
    return (
      <PageShell>
        <PageHeader back title='设置' />
        <View className='settings-loading'>
          <Mascot pose='thinking' className='mascot-orb' />
          <Text className='settings-loading-text'>正在整理你的资料…</Text>
        </View>
      </PageShell>
    )
  }

  if (error && !profile) {
    return (
      <PageShell>
        <PageHeader back title='设置' />
        <View className='settings-page'>
          <ErrorCard
            title='资料没有打开'
            message={error}
            retryLabel='重新加载'
            onRetry={load}
            backLabel='回首页'
            onBack={() => Taro.reLaunch({ url: '/pages/index/index' })}
          />
        </View>
      </PageShell>
    )
  }

  const avatar = resolveMediaUrl(avatarTemp || profile?.avatar_url)
  const loggedIn = !!profile?.is_logged_in

  return (
    <PageShell>
      <PageHeader back title='设置' />
      <View className='settings-page'>
        {!loggedIn && (
          <View className='settings-login-card' onClick={openLogin}>
            <Mascot pose='head' className='mascot-head' />
            <View className='grow'>
              <Text className='settings-login-title'>登录后同步资料与记录</Text>
              <Text className='settings-login-desc'>当前是游客身份，资料和记录只留在这台设备。</Text>
            </View>
            <View className='chip chip-active'>去登录</View>
          </View>
        )}

        <View className='settings-section'>
          <Text className='settings-section-title'>账号与资料</Text>
          <View className='settings-card'>
            <View className='settings-profile-row'>
              {IS_WEAPP && loggedIn ? (
                <Button className='settings-avatar-btn' openType='chooseAvatar' onChooseAvatar={handleChooseAvatar}>
                  {avatar ? (
                    <Image className='settings-avatar-img' src={avatar} mode='aspectFill' />
                  ) : (
                    <Mascot pose='head' className='mascot-head' />
                  )}
                </Button>
              ) : (
                <View className='settings-avatar-btn' onClick={chooseAvatar}>
                  {avatar ? (
                    <Image className='settings-avatar-img' src={avatar} mode='aspectFill' />
                  ) : (
                    <Mascot pose='head' className='mascot-head' />
                  )}
                </View>
              )}
              <View className='grow'>
                <Text className='settings-profile-name'>{profile?.nickname || '旅人'}</Text>
                <Text className='settings-profile-sub'>
                  {loggedIn ? (profile?.wechat_bound ? '已绑定微信' : '体验账号') : '游客身份'}
                  {loggedIn ? ' · 头像与昵称可修改' : ''}
                </Text>
              </View>
              {loggedIn && <View className='chip chip-ghost' onClick={saveProfile}>{saving ? '保存中…' : '保存'}</View>}
            </View>

            <View className='settings-field'>
              <Text className='settings-field-label'>昵称</Text>
              <Input
                className='settings-input'
                type='nickname'
                value={nickname}
                maxlength={16}
                disabled={!loggedIn}
                placeholder='给自己起个名字'
                onInput={(e) => setNickname(e.detail.value)}
              />
            </View>
            <Text className='settings-hint'>头像支持 JPG / PNG / WebP，不超过 2MB。</Text>
          </View>
        </View>

        <View className='settings-section'>
          <Text className='settings-section-title'>偏好</Text>
          <View className='settings-card'>
            <View className='settings-row'>
              <View className='grow'>
                <Text className='settings-row-label'>学习提醒</Text>
                <Text className='settings-row-sub'>本期仅记录偏好，推送能力后续开放</Text>
              </View>
              <Switch
                checked={!!profile?.settings?.reminder_enabled}
                color='#3E6650'
                onChange={(e) => toggleReminder(e.detail.value)}
              />
            </View>
            <View className='settings-row' onClick={() => openPage('privacy')}>
              <Text className='settings-row-label'>隐私政策</Text>
              <Text className='settings-row-arrow'>›</Text>
            </View>
            <View className='settings-row' onClick={() => openPage('terms')}>
              <Text className='settings-row-label'>用户协议</Text>
              <Text className='settings-row-arrow'>›</Text>
            </View>
            <View className='settings-row' onClick={() => openPage('about')}>
              <Text className='settings-row-label'>关于与反馈</Text>
              <Text className='settings-row-arrow'>›</Text>
            </View>
          </View>
        </View>

        <View className='settings-section'>
          <Text className='settings-section-title'>数据与账号</Text>
          <View className='settings-card'>
            <View className='settings-row' onClick={clearCache}>
              <Text className='settings-row-label'>清除本地缓存</Text>
              <Text className='settings-row-arrow'>›</Text>
            </View>
            {loggedIn && (
              <View className='settings-row' onClick={handleLogout}>
                <Text className='settings-row-label'>退出登录</Text>
                <Text className='settings-row-arrow'>›</Text>
              </View>
            )}
            {loggedIn && (
              <View className='settings-row danger' onClick={handleDelete}>
                <Text className='settings-row-label'>注销账号</Text>
                <Text className='settings-row-arrow'>›</Text>
              </View>
            )}
          </View>
        </View>

        <Text className='settings-version'>墨灵闯关 v0.3.0 · 内容由 AI 生成，仅供学习参考</Text>
        <View className='settings-bottom-space' />
      </View>

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={() => {
          setLoginOpen(false)
          load()
        }}
        reason='登录后才能修改资料、同步记录和管理账号。'
      />
    </PageShell>
  )
}
