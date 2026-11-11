import { useEffect, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { IS_WEAPP } from '../config'
import { health } from '../services/api'
import { signInDev, signInWithWechat } from '../services/auth'
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

/** 登录弹层：协议勾选 + 微信一键登录 + 仅开发可见的体验登录。 */
export default function LoginSheet({ open, onClose, onSuccess, reason }: LoginSheetProps) {
  const [agreed, setAgreed] = useState(false)
  const [loading, setLoading] = useState<'wechat' | 'dev' | ''>('')
  const [error, setError] = useState('')
  const [devLogin, setDevLogin] = useState(false)

  useEffect(() => {
    if (!open) return
    setError('')
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

  const handleWechat = async () => {
    if (!requireAgreement() || loading) return
    setLoading('wechat')
    setError('')
    try {
      const user = await signInWithWechat()
      Taro.showToast({ title: '登录成功', icon: 'success' })
      onSuccess(user.nickname || '旅人')
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
      const user = await signInDev()
      Taro.showToast({ title: '已进入体验账号', icon: 'success' })
      onSuccess(user.nickname || '体验旅人')
    } catch (err) {
      setError((err as Error).message || '体验登录失败')
    } finally {
      setLoading('')
    }
  }

  return (
    <View className='login-mask' onClick={onClose}>
      <View className='login-sheet' onClick={(e) => e.stopPropagation()}>
        <View className='login-grab' />
        <View className='login-head'>
          <View className='login-mascot'>
            <Mascot pose='head' className='mascot-head' />
          </View>
          <View className='login-head-copy'>
            <Text className='login-title'>登录后，路才记得住</Text>
            <Text className='login-sub'>
              {reason || '学习记录、积分和每日额度都会跟着你的微信走。'}
            </Text>
          </View>
          <View className='login-close' onClick={onClose}>
            <Icon name='close-ink3' size={18} />
          </View>
        </View>

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
          只获取微信身份用于登录，不读取手机号、通讯录或好友列表。
        </Text>
        <Text className='login-home' onClick={goHome}>
          先回首页看看
        </Text>
      </View>
    </View>
  )
}
