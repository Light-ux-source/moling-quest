import { useCallback, useState } from 'react'
import { Image, Switch, Text, View } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import Mascot from '../../components/Mascot'
import Icon from '../../components/Icon'
import ErrorCard from '../../components/ErrorCard'
import LoginSheet from '../../components/LoginSheet'
import { useSafeArea } from '../../hooks/useSafeArea'
import { getProfile, resolveMediaUrl, updateSettings } from '../../services/api'
import { IS_WEAPP } from '../../config'
import type { Profile } from '../../types'
import './index.css'

export default function ProfilePage() {
  const { top } = useSafeArea()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [loginOpen, setLoginOpen] = useState(false)
  const [savingReminder, setSavingReminder] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await getProfile()
      setProfile(data)
      setError('')
    } catch (err) {
      setError((err as Error).message || '加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useDidShow(() => {
    load()
  })

  const openLogin = () => setLoginOpen(true)

  const handleLoginSuccess = () => {
    setLoginOpen(false)
    load()
  }

  const openSettings = () => {
    Taro.navigateTo({ url: '/pages/settings/index' })
  }

  const openRecords = () => {
    Taro.navigateTo({ url: '/pages/records/index' })
  }

  const openAbout = () => {
    Taro.navigateTo({ url: '/pages/about/index?type=about' })
  }

  const toggleReminder = async (value: boolean) => {
    if (!profile?.is_logged_in) {
      openLogin()
      return
    }
    if (savingReminder) return
    setSavingReminder(true)
    const previous = profile
    setProfile({ ...profile, settings: { reminder_enabled: value } })
    try {
      await updateSettings({ reminder_enabled: value })
      Taro.showToast({ title: value ? '已记录提醒偏好' : '已关闭提醒', icon: 'none' })
    } catch (err) {
      setProfile(previous)
      Taro.showToast({ title: (err as Error).message || '保存失败', icon: 'none' })
    } finally {
      setSavingReminder(false)
    }
  }

  const handleQuotaAction = () => {
    if (profile?.is_guest) {
      openLogin()
      return
    }
    Taro.showToast({ title: '会员功能即将开放', icon: 'none' })
  }

  const navigateSoon = (label: string) => {
    Taro.showToast({ title: `${label}即将开放`, icon: 'none' })
  }

  if (error && !profile) {
    return (
      <PageShell tabbar activeTab='profile'>
        <View className='profile-page' style={{ paddingTop: `${top + 16}px` }}>
          <ErrorCard
            title='雾林起雾了'
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

  const points = profile?.points ?? 0
  const quota = profile?.quota
  const quotaText = quota
    ? quota.period === 'trial'
      ? `试用 ${quota.used} / ${quota.limit} 次`
      : `今日 ${quota.used} / ${quota.limit} 次`
    : '今日 0 / 3 次'
  const quotaEmpty = !!quota && quota.remaining <= 0
  const nickname = profile?.nickname || '旅人'
  const avatar = resolveMediaUrl(profile?.avatar_url)

  return (
    <PageShell tabbar activeTab='profile'>
      <View className='profile-page' style={{ paddingTop: `${top + 16}px` }}>
        <View className={`profile-head ${IS_WEAPP ? 'weapp' : ''}`}>
          <View className='profile-avatar' onClick={() => (profile?.is_guest ? openLogin() : openSettings())}>
            {avatar ? (
              <Image className='profile-avatar-img' src={avatar} mode='aspectFill' />
            ) : (
              <Mascot pose='head' className='mascot-head' />
            )}
          </View>
          <View className='profile-identity'>
            <Text className='profile-name'>{nickname}</Text>
            <Text className='profile-sub'>
              已走过 {profile?.chapters_completed ?? 0} 关 · 连续 {profile?.streak_days ?? 0} 天
            </Text>
          </View>
          <View className='chip chip-ghost profile-settings' onClick={openSettings}>
            设置
          </View>
        </View>

        {profile?.is_guest && (
          <View className='profile-login-card' onClick={openLogin}>
            <View className='profile-login-icon'>
              <Icon name='tab-user-mossdeep' size={20} />
            </View>
            <View className='grow'>
              <Text className='profile-login-title'>登录后，学习记录跟着你走</Text>
              <Text className='profile-login-desc'>换设备也能继续学，积分不会丢。</Text>
            </View>
            <View className='chip chip-active'>去登录</View>
          </View>
        )}

        <View className='profile-stats'>
          <View className='profile-stat'>
            <Text className='profile-stat-num'>{profile?.chapters_completed ?? 0}</Text>
            <Text className='profile-stat-label'>通关</Text>
          </View>
          <View className='profile-stat'>
            <Text className='profile-stat-num'>{profile?.total_stars ?? 0}</Text>
            <Text className='profile-stat-label'>星星</Text>
          </View>
          <View className='profile-stat'>
            <Text className='profile-stat-num'>{profile?.streak_days ?? 0}</Text>
            <Text className='profile-stat-label'>连续天</Text>
          </View>
        </View>

        <View className='profile-points'>
          <View className='profile-points-left'>
            <Icon name='star-amber' size={18} />
            <Text className='profile-points-label'>积分</Text>
          </View>
          <Text className='profile-points-value'>{points}</Text>
          <Text className='profile-points-rank'>{profile?.rank?.label || '初入雾林'}</Text>
        </View>

        <View className={`profile-quota ${quotaEmpty ? 'empty' : ''}`}>
          <View className='grow'>
            <Text className='profile-quota-title'>AI 造关额度</Text>
            <Text className='profile-quota-value'>{quotaText}</Text>
            <Text className='profile-quota-hint'>
              {quotaEmpty
                ? quota?.is_guest
                  ? '登录后可继续造关，记录也会跟着账号走。'
                  : '明天 00:00 恢复。先去复习一下已学的内容吧。'
                : quota?.is_guest
                  ? '试用结束后登录，即可每天继续造关。'
                  : '每天 00:00 恢复，重试不重复扣。'}
            </Text>
          </View>
          <View className='chip chip-active' onClick={handleQuotaAction}>
            {profile?.is_guest ? '去登录' : '了解会员'}
          </View>
        </View>

        <View className='profile-menu'>
          <View className='profile-menu-row' onClick={openRecords}>
            <View className='profile-menu-icon'>
              <Icon name='list-paper' size={18} />
            </View>
            <Text className='profile-menu-label'>学习记录</Text>
            <Icon name='chevron-right-ink3' size={16} />
          </View>
          <View className='profile-menu-row disabled' onClick={() => navigateSoon('错题本')}>
            <View className='profile-menu-icon'>
              <Icon name='tab-book-ink3' size={18} />
            </View>
            <Text className='profile-menu-label'>错题本</Text>
            <Text className='profile-menu-soon'>即将开放</Text>
          </View>
          <View className='profile-menu-row disabled' onClick={() => navigateSoon('成就与段位')}>
            <View className='profile-menu-icon'>
              <Icon name='star-empty' size={18} />
            </View>
            <Text className='profile-menu-label'>成就与段位</Text>
            <Text className='profile-menu-soon'>即将开放</Text>
          </View>
          <View className='profile-menu-row'>
            <View className='profile-menu-icon'>
              <Icon name='clock-ink3' size={18} />
            </View>
            <View className='grow'>
              <Text className='profile-menu-label'>学习提醒</Text>
              <Text className='profile-menu-sub'>仅记录偏好，推送后续开放</Text>
            </View>
            <Switch
              checked={!!profile?.settings?.reminder_enabled}
              color='#3E6650'
              disabled={savingReminder}
              onChange={(e) => toggleReminder(e.detail.value)}
            />
          </View>
          <View className='profile-menu-row' onClick={openAbout}>
            <View className='profile-menu-icon'>
              <Icon name='info-ink3' size={18} />
            </View>
            <Text className='profile-menu-label'>关于与反馈</Text>
            <Icon name='chevron-right-ink3' size={16} />
          </View>
        </View>

        <Text className='profile-disclaimer'>
          内容由 AI 生成，仅供学习参考 · v0.3.0
        </Text>
        <View className='profile-bottom-space' />
      </View>

      <LoginSheet
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        onSuccess={handleLoginSuccess}
        reason='登录后，学习记录、积分和每日额度都会跟着你。'
      />
    </PageShell>
  )
}
