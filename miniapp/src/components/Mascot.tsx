import { Image } from '@tarojs/components'

export type MascotPose = 'idle' | 'happy' | 'thinking' | 'head'

interface MascotProps {
  pose?: MascotPose
  className?: string
  float?: boolean
}

const SOURCES: Record<MascotPose, string> = {
  idle: '/assets/mascot/idle.svg',
  happy: '/assets/mascot/happy.svg',
  thinking: '/assets/mascot/thinking.svg',
  head: '/assets/mascot/head.svg'
}

/** 原创猫灵「墨团」；SVG 来自已确认原型，不用官方 IP 素材。 */
export default function Mascot({ pose = 'idle', className = 'mascot-idle', float = false }: MascotProps) {
  return (
    <Image
      className={`mascot ${className} ${float ? 'mascot-float' : ''}`}
      src={SOURCES[pose]}
      mode='aspectFit'
    />
  )
}