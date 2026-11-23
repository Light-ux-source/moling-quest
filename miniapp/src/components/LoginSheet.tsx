import { useEffect, useState } from 'react'
import { Button, Form, Image, Input, Text, View } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { IS_WEAPP } from '../config'
import { health, updateProfile, uploadAvatar } from '../services/api'
import { signInDev, signInWithWechat } from '../services/auth'
import type { User } from '../types'
import { goHome } from '../utils/nav'
import Icon from './Icon'
import Mascot from './Mascot'
import './LoginSheet.css'

interface LoginSheetProps {
  open: boolean
  onClose: () => void
  onSuccess: (nickname: string) => void
  reason?: string
}

/** 登录弹层：协议勾选 + 微信一键登录 + 新用户完善头像昵称 + 仅开发可见的体验登录。 */
export default function LoginSheet({ open, onClose, onSuccess, reason }: LoginSheetProps) {
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState<'wechat' | 'dev' | ''>('')
  const [error, setError] = useState('')
  const [devLogin, setDevLogin] = useState(false)
  const [step, setStep] = useState<'login' | 'profile'>('login')
  const [profileUser, setProfileUser] = useState<User | null>(null)
  const [nickname, setNickname] = useState('')
  const [avatarTemp, setAvatarTemp] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)
  const [profileError, setProfileError] = useState('')

  useEffect(() => {
    if (!open) return
    setError('')
    setProfileError('')
    setStep('login')
    setProfileUser(null)
    setNickname('')
    setAvatarTemp('')
    health()
      .then((data) => setDevLogin(!!data.dev_login))
      .catch(() => setDevLogin(!IS_WEAPP))
  }, [open])

  if (!open) return null

  const requireAgreement = (): boolean => {
    if (agreed) return true
    Taro.showToast({ title: '请先阅读并同意用户协议与隐私政策', icon: 'none' })
    return false
  }

  const finish = (name?: string) => {
    const value = (name || profileUser?.nickname || '旅人').trim() || '旅人'
    setStep('login')
    setProfileUser(null)
    setNickname('')
    setAvatarTemp('')
    setProfileError('')
    onSuccess(value)
  }

  const handleClose = () => {
    if (step === 'profile') {
      finish()
      return
    }
    onClose()
  }

  const handleWechat = async () => {
    if (!requireAgreement() || loading) return
    setLoading('wechat')
    setError('')
    try {
      const data = await signInWithWechat()
      if (data.is_new) {
        setProfileUser(data.user)
        setStep('profile')
        return
      }
      Taro.showToast({ title: '登录成功', icon: 'success' })
      finish(data.user.nickname)
    } catch (err) {
      setError((err as Error).message || '登录没有完成，请重试')
    } finally {
      setLoading('')
    }
  }

  const handleDev = async () => {
    if (!requireAgreement() || loading) return
    setLoading('dev')
    setError('')
    try {
      const data = await signInDev()
      Taro.showToast({ title: '已进入体验账号', icon: 'success' })
      finish(data.user.nickname || '体验旅人')
    } catch (err) {
      setError((err as Error).message || '体验登录失败')
    } finally {
      setLoading('')
    }
  }

  const handleChooseAvatar = (event: any) => {
    const url = event?.detail?.avatarUrl
    if (url) setAvatarTemp(url)
  }

  const handleProfileSubmit = async (event: any) => {
    if (savingProfile) return
    const submitted = String(event?.detail?.value?.nickname ?? '').trim()
    if (submitted.length > 16) {
      setProfileError('昵称需要 1–16 个字符')
      return
    }
    if (!submitted && !avatarTemp) {
      finish()
      return
    }

    setSavingProfile(true)
    setProfileError('')
    try {
      let avatarUrl = ''
      if (avatarTemp) {
        const uploaded = await uploadAvatar(avatarTemp)
        avatarUrl = uploaded.avatar_url
      }
      const payload: { nickname?: string; avatar_url?: string } = {}
      if (submitted) payload.nickname = submitted
      if (avatarUrl) payload.avatar_url = avatarUrl
      const updated = Object.keys(payload).length ? await updateProfile(payload) : null
      Taro.showToast({ title: '资料已保存', icon: 'success' })
      finish(updated?.nickname || submitted || profileUser?.nickname)
    } catch (err) {
      setProfileError((err as Error).message || '资料保存失败，请重试')
    } finally {
      setSavingProfile(false)
    }
  }

  const handleSkipProfile = () => {
    finish()
  }

  const handleNicknameReview = (event: any) => {
    if (event?.detail?.pass === false) {
      setProfileError('昵称未通过内容安全检测，请换一个')
    }
  }

  return (
    <View className='login-mask' onClick={handleClose}>
      <View className='login-sheet' onClick={(e) => e.stopPropagation()}>
        <View className='login-grab' />
        <View className='login-head'>
          <View className='login-mascot'>
            <Mascot pose='head' className='mascot-head' />
          </View>
          <View className='login-head-copy'>
            <Text className='login-title'>{step === 'profile' ? '让墨团记住你' : '登录后，路才记得住'}</Text>
            <Text className='login-sub'>
              {step === 'profile'
                ? '微信不会自动提供头像昵称，请在这里选择或填写；也可以稍后在设置里补。'
                : reason || '学习记录、积分和每日额度都会跟着你的微信走。'}
            </Text>
          </View>
          <View className='login-close' onClick={handleClose}>
            <Icon name='close-ink3' size={18} />
          </View>
        </View>

        {step === 'profile' ? (
          <Form onSubmit={handleProfileSubmit}>
            <View className='login-profile'>
              <Button
                className='login-avatar-btn'
                openType='chooseAvatar'
                onChooseAvatar={handleChooseAvatar}
              >
                {avatarTemp ? (
                  <Image className='login-avatar-img' src={avatarTemp} mode='aspectFill' />
                ) : (
                  <Mascot pose='head' className='mascot-head' />
                )}
              </Button>
              <Text className='login-avatar-hint'>
                {avatarTemp ? '点击更换头像' : '点击选择微信头像'}
              </Text>

              <Input
                className='login-nickname-input'
                type='nickname'
                name='nickname'
                value={nickname}
                maxlength={16}
                placeholder='微信昵称，或自己起一个'
                placeholderClass='login-nickname-placeholder'
                onInput={(e) => {
                  setNickname(e.detail.value)
                  if (profileError) setProfileError('')
                }}
                onNickNameReview={handleNicknameReview}
              />

              <Button
                className={`btn btn-primary btn-block login-profile-save ${savingProfile ? 'btn-disabled' : ''}`}
                formType='submit'
              >
                {savingProfile ? '保存中…' : '保存并开始'}
              </Button>
              <View className='btn btn-ghost btn-block login-profile-skip' onClick={handleSkipProfile}>
                稍后再说
              </View>
            </View>
          </Form>
        ) : (
          <>
            <View className='login-benefits'>
              <View className='login-benefit'>
                <Icon name='leaf-moss' size={16} />
                <Text>换设备也能继续学</Text>
              </View>
              <View className='login-benefit'>
                <Icon name='star-amber' size={16} />
                <Text>积分与记录不丢</Text>
              </View>
              <View className='login-benefit'>
                <Icon name='clock-ink3' size={16} />
                <Text>每天 3 组额度</Text>
              </View>
            </View>

            <View className='login-actions'>
              <View
                className={`btn btn-primary btn-block ${loading === 'wechat' ? 'btn-disabled' : ''}`}
                onClick={handleWechat}
              >
                {loading === 'wechat' ? '正在登录…' : '微信一键登录'}
              </View>
              {devLogin && (
                <View
                  className={`btn btn-ghost btn-block login-dev ${loading === 'dev' ? 'btn-disabled' : ''}`}
                  onClick={handleDev}
                >
                  {loading === 'dev' ? '正在进入…' : '体验登录（开发）'}
                </View>
              )}
            </View>

            <View className='login-agree' onClick={() => setAgreed((value) => !value)}>
              <View className={`login-check ${agreed ? 'on' : ''}`}>
                {agreed && <Icon name='check-paper' size={16} />}
              </View>
              <Text className='login-agree-text'>
                我已阅读并同意
                <Text
                  className='login-link'
                  onClick={(e) => {
                    e.stopPropagation()
                    Taro.navigateTo({ url: '/pages/about/index?type=terms' })
                  }}
                >
                  《用户协议》
                </Text>
                与
                <Text
                  className='login-link'
                  onClick={(e) => {
                    e.stopPropagation()
                    Taro.navigateTo({ url: '/pages/about/index?type=privacy' })
                  }}
                >
                  《隐私政策》
                </Text>
              </Text>
            </View>

            {error ? (
              <View className='login-error-box'>
                <Text className='login-error'>{error}</Text>
                <Text className='login-error-hint'>可以重试；也可以先回首页继续浏览已有内容。</Text>
              </View>
            ) : null}

            <Text className='login-note'>
              只获取微信身份用于登录，不读取手机号、通讯录或好友列表；头像昵称需你主动选择/填写。
            </Text>
            <Text className='login-home' onClick={goHome}>
              先回首页看看
            </Text>
          </>
        )}

        {step === 'profile' && profileError ? (
          <Text className='login-error'>{profileError}</Text>
        ) : null}

        {step === 'profile' ? (
          <Text className='login-note'>头像与昵称只用于展示，可随时在设置里修改。</Text>
        ) : null}
      </View>
    </View>
  )
}