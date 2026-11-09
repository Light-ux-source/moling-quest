import type { AnswerResult, QuestionType } from '../types'

export function formatDuration(seconds: number, compact = false): string {
  if (!seconds || seconds < 0) return compact ? '0:00' : '—'
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  if (compact) return `${mins}:${String(secs).padStart(2, '0')}`
  if (mins <= 0) return `${secs} 秒`
  return `${mins} 分 ${secs} 秒`
}

export function estimateMinutes(questionCount: number): number {
  return Math.max(2, Math.round(questionCount * 0.8))
}

export function formatDate(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function safeDecode(value?: string): string {
  if (!value) return ''
  try {
    return decodeURIComponent(value)
  } catch (err) {
    return value
  }
}

export function isBlankAnswer(value: string | string[] | null | undefined): boolean {
  if (value === undefined || value === null) return true
  if (Array.isArray(value)) return value.length === 0
  return !String(value).trim()
}

export function optionText(item: Pick<AnswerResult, 'options'>, key: string): string {
  const option = (item.options || []).find((o) => o.key === key)
  return option ? option.text : ''
}

export function formatAnswer(
  item: Pick<AnswerResult, 'type' | 'options'> & { type: QuestionType },
  value: string | string[] | null
): string {
  if (value === null || value === undefined) return '未作答'
  if (Array.isArray(value)) {
    if (value.length === 0) return '未作答'
    if (item.type === 'short_answer') return value.join('；')
    return value
      .map((key) => {
        const text = optionText(item, key)
        return text ? `${key}. ${text}` : key
      })
      .join('\n')
  }
  if (!String(value).trim()) return '未作答'
  if (item.type === 'short_answer') return value
  const text = optionText(item, value)
  return text ? `${value}. ${text}` : value
}

export function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 12) return '早上好'
  if (hour < 18) return '下午好'
  return '晚上好'
}

export function scoreTone(score: number): 'good' | 'mid' | 'low' {
  if (score >= 80) return 'good'
  if (score >= 60) return 'mid'
  return 'low'
}

export function starText(stars: number): string {
  return `${'★'.repeat(Math.max(0, Math.min(3, stars)))}${'☆'.repeat(Math.max(0, 3 - stars))}`
}

export function topicShort(topic: string, max = 18): string {
  const text = (topic || '').trim()
  return text.length > max ? `${text.slice(0, max)}…` : text
}