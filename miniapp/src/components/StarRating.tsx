import { View } from '@tarojs/components'
import Icon from './Icon'

interface StarRatingProps {
  stars: number
  variant?: 'amber' | 'hero'
  size?: 'sm' | 'md' | 'lg'
  animate?: boolean
}

/** 三星制；实心琥珀、空心陈纸。同时输出文字语义（父组件负责提示）。 */
export default function StarRating({ stars, variant = 'amber', size = 'md', animate = false }: StarRatingProps) {
  const filled = variant === 'hero' ? 'star-paper' : 'star-amber'
  const empty = 'star-empty'
  return (
    <View className={`stars ${size === 'lg' ? 'stars-lg' : ''} ${variant === 'hero' ? 'stars-hero' : ''}`}>
      {[0, 1, 2].map((index) => (
        <Icon
          key={index}
          name={index < stars ? filled : empty}
          size={size === 'sm' ? 16 : size === 'lg' ? 28 : 20}
          className={`star ${animate && index < stars ? 'star-pop' : ''} ${index >= stars && variant === 'hero' ? 'star-dim' : ''}`}
        />
      ))}
    </View>
  )
}