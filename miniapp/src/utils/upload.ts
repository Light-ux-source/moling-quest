import Taro from '@tarojs/taro'
import { IS_H5 } from '../config'

export interface PickedFile {
  path: string
  name: string
  size: number
  revoke?: () => void
}

const ACCEPT = '.pdf,.docx,.pptx,.xlsx,.txt,.md,.markdown,.html,.htm'

/**
 * 跨端选择文件：
 * - H5：隐藏 input[type=file] + blob URL（Taro H5 uploadFile 支持 blob URL）
 * - 微信小程序：chooseMessageFile（H5 不支持该 API）
 */
export function pickFile(): Promise<PickedFile | null> {
  if (IS_H5) return pickH5()
  return pickWeapp()
}

function pickWeapp(): Promise<PickedFile | null> {
  return new Promise((resolve, reject) => {
    Taro.chooseMessageFile({
      count: 1,
      type: 'file',
      extension: ['pdf', 'docx', 'pptx', 'xlsx', 'txt', 'md', 'markdown', 'html', 'htm']
    })
      .then((res) => {
        const file = res.tempFiles?.[0]
        if (!file) {
          resolve(null)
          return
        }
        resolve({ path: file.path, name: file.name || '资料', size: Number(file.size || 0) })
      })
      .catch((err) => {
        if (String(err?.errMsg || '').includes('cancel')) {
          resolve(null)
          return
        }
        reject(err)
      })
  })
}

function pickH5(): Promise<PickedFile | null> {
  return new Promise((resolve, reject) => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = ACCEPT
    input.style.position = 'fixed'
    input.style.left = '-9999px'
    input.style.top = '0'
    input.setAttribute('data-kb-file-input', '1')
    document.body.appendChild(input)

    let settled = false
    let fallbackTimer: number | undefined
    const cleanup = () => {
      if (input.parentNode) input.parentNode.removeChild(input)
      if (fallbackTimer) window.clearTimeout(fallbackTimer)
    }
    const finish = (value: PickedFile | null) => {
      if (settled) return
      settled = true
      cleanup()
      resolve(value)
    }

    input.addEventListener('change', () => {
      const file = input.files?.[0]
      if (!file) {
        finish(null)
        return
      }
      const path = URL.createObjectURL(file)
      finish({
        path,
        name: file.name || '资料',
        size: Number(file.size || 0),
        revoke: () => URL.revokeObjectURL(path)
      })
    })
    input.addEventListener('cancel', () => finish(null))
    // 极少数浏览器取消时不触发 cancel；120s 后兜底释放 Promise，不影响用户重新选择
    fallbackTimer = window.setTimeout(() => finish(null), 120000)
    try {
      input.click()
    } catch (err) {
      finish(null)
      reject(err)
    }
  })
}