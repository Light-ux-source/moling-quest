import { Text, View } from '@tarojs/components'
import Taro, { useRouter } from '@tarojs/taro'
import PageShell from '../../components/PageShell'
import PageHeader from '../../components/PageHeader'
import Mascot from '../../components/Mascot'
import './index.css'

type AboutType = 'about' | 'privacy' | 'terms'

const TITLES: Record<AboutType, string> = {
  about: '关于与反馈',
  privacy: '隐私政策',
  terms: '用户协议'
}

const PRIVACY_SECTIONS = [
  {
    title: '我们收集什么',
    body: '微信登录唯一标识（用于识别账号）、昵称与头像（可跳过）、学习记录与积分、AI 造关额度使用情况、必要的设备与日志信息。我们不收集手机号、通讯录、好友列表、真实姓名、身份证或精确位置。'
  },
  {
    title: '为什么收集',
    body: '用于账号登录与跨设备同步、展示学习记录与积分、控制每日造关额度、保障账号安全与排查故障。不会将你的学习数据用于模型训练，也不会出售或向无关第三方共享。'
  },
  {
    title: '保留多久',
    body: '登录用户的学习记录在账号存续期内保留；游客记录建议保留 30 天；额度与安全日志至少保留 90 天。注销账号后，昵称、头像、微信绑定等个人信息会被删除，学习记录会匿名化保留用于统计。'
  },
  {
    title: '你的权利',
    body: '你可以在「设置」中修改昵称/头像、退出登录、清除本地缓存或注销账号；也可以联系我们请求查询、更正或删除个人信息。注销后账号不可恢复。'
  },
  {
    title: '未成年人',
    body: '本产品默认面向成人自主学习场景。若你为未成年人，请在监护人同意与指导下使用；如后续涉及未成年人模式，我们会另行说明。'
  }
]

const TERMS_SECTIONS = [
  {
    title: '服务说明',
    body: '墨灵闯关是一个 AI 出题学习工具：你输入知识点，AI 检索并生成题目，你作答后获得解析与学习建议。题目与解析由 AI 生成，可能存在错误或过时信息，请结合可靠资料判断。'
  },
  {
    title: '账号与登录',
    body: '你使用微信一键登录，首次登录自动创建账号。请妥善保管你的微信账号与设备；因账号共享、设备丢失等造成的损失由你自行承担。'
  },
  {
    title: '使用边界',
    body: '请勿利用本服务生成、传播违法或侵权内容，请勿攻击、爬取、批量注册或绕过额度限制。我们有权对异常账号采取限流、暂停或终止服务等措施。'
  },
  {
    title: 'AI 内容标识',
    body: '依据相关要求，AI 生成内容会带有「内容由 AI 生成，仅供学习参考」标识。本服务不构成考试承诺、医疗/法律等专业建议或官方认证。'
  },
  {
    title: '协议更新',
    body: '我们可能根据产品与法规变化更新本协议，更新后会在小程序内展示。继续使用即视为接受更新后的条款。'
  }
]

export default function AboutPage() {
  const router = useRouter()
  const raw = (router.params?.type || 'about') as AboutType
  const type: AboutType = ['about', 'privacy', 'terms'].includes(raw) ? raw : 'about'
  const sections = type === 'privacy' ? PRIVACY_SECTIONS : type === 'terms' ? TERMS_SECTIONS : []

  const copyFeedback = () => {
    Taro.setClipboardData({ data: 'feedback@moling.app' })
      .then(() => Taro.showToast({ title: '反馈邮箱已复制', icon: 'success' }))
      .catch(() => Taro.showToast({ title: '复制失败，请手动记录', icon: 'none' }))
  }

  return (
    <PageShell>
      <PageHeader back title={TITLES[type]} />
      <View className='about-page'>
        {type === 'about' ? (
          <>
            <View className='about-hero'>
              <Mascot pose='happy' className='mascot-idle' />
              <Text className='about-hero-title'>墨灵闯关</Text>
              <Text className='about-hero-sub'>把知识点变成一场雾林冒险。</Text>
              <Text className='about-version'>v0.3.0 · 用户系统版</Text>
            </View>

            <View className='about-card'>
              <Text className='about-card-title'>这是一款什么工具</Text>
              <Text className='about-body'>
                输入一个知识点，AI 会先检索资料、再生成一组有梯度的题；答完后给出解析、知识缺口和下一步建议。
                我们希望把「枯燥的被动阅读」换成「有反馈的主动回忆」。
              </Text>
            </View>

            <View className='about-card'>
              <Text className='about-card-title'>你的数据</Text>
              <Text className='about-body'>
                登录后，学习记录、积分和额度会跟着微信账号走；换设备登录同一个微信即可继续。
                你可以随时在设置中退出或注销账号。
              </Text>
              <View className='about-inline-actions'>
                <View className='chip chip-ghost' onClick={() => Taro.navigateTo({ url: '/pages/about/index?type=privacy' })}>
                  隐私政策
                </View>
                <View className='chip chip-ghost' onClick={() => Taro.navigateTo({ url: '/pages/about/index?type=terms' })}>
                  用户协议
                </View>
              </View>
            </View>

            <View className='about-card'>
              <Text className='about-card-title'>反馈</Text>
              <Text className='about-body'>遇到问题、想提建议，或发现 AI 生成的题目有误，欢迎告诉我们。</Text>
              <View className='about-feedback' onClick={copyFeedback}>
                <Text className='about-feedback-label'>反馈邮箱</Text>
                <Text className='about-feedback-value'>feedback@moling.app</Text>
                <Text className='about-feedback-copy'>复制</Text>
              </View>
            </View>

            <Text className='about-disclaimer'>
              内容由 AI 生成，仅供学习参考。本产品为原创视觉，不使用任何第三方官方角色素材。
            </Text>
          </>
        ) : (
          <>
            <View className='about-doc-head'>
              <Text className='about-doc-title'>{TITLES[type]}</Text>
              <Text className='about-doc-date'>更新日期：2026-11-10</Text>
            </View>
            {sections.map((section) => (
              <View key={section.title} className='about-doc-section'>
                <Text className='about-doc-section-title'>{section.title}</Text>
                <Text className='about-body'>{section.body}</Text>
              </View>
            ))}
            <Text className='about-disclaimer'>
              如对本政策或协议有疑问，可通过 feedback@moling.app 联系我们。
            </Text>
          </>
        )}
        <View className='about-bottom-space' />
      </View>
    </PageShell>
  )
}
