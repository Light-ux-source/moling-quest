import { Image } from '@tarojs/components'

export type IconSize = 16 | 18 | 20 | 24 | 28 | 32 | 40

interface IconProps {
  name: string
  size?: IconSize
  className?: string
}

/** 线性图标；资源由 scripts/gen_assets.py 从原型 SVG 生成。 */
export default function Icon({ name, size = 24, className = '' }: IconProps) {
  return (
    <Image
      className={`icon icon-${size} ${className}`}
      src={`/assets/icons/${name}.svg`}
      mode='aspectFit'
    />
  )
}