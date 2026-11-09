import { View } from '@tarojs/components'

interface SealStampProps {
  text: string
  size?: 'md' | 'sm'
  animate?: boolean
}

export default function SealStamp({ text, size = 'md', animate = false }: SealStampProps) {
  return (
    <View className={`seal ${size === 'sm' ? 'seal-small' : ''} ${animate ? 'seal-drop' : ''}`}>
      {text}
    </View>
  )
}