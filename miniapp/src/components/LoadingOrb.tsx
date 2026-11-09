import { View, Text } from '@tarojs/components'
import Mascot from './Mascot'

interface LoadingOrbProps {
  title: string
  subtitle?: string
}

export default function LoadingOrb({ title, subtitle }: LoadingOrbProps) {
  return (
    <View className='loading-orb'>
      <View className='orb-ring'>
        <Mascot pose='thinking' className='mascot-orb' float />
      </View>
      <View className='orb-title'>{title}</View>
      {subtitle ? <View className='orb-sub'>{subtitle}</View> : null}
      <View className='orb-dots'>
        <View className='orb-dot' />
        <View className='orb-dot' />
        <View className='orb-dot' />
      </View>
    </View>
  )
}