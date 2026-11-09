export type QuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer'
export type Level = 'basic' | 'advanced' | 'challenge'

export interface Option {
  key: string
  text: string
}

export interface Question {
  id: string
  seq: number
  type: QuestionType
  stem: string
  options: Option[]
  difficulty: string
}

export interface SourceItem {
  title: string
  url: string
  site_name?: string | null
  summary: string
}

export type SessionStatus =
  | 'queued'
  | 'searching'
  | 'digesting'
  | 'generating'
  | 'ready'
  | 'grading'
  | 'reporting'
  | 'completed'
  | 'failed'

export interface SessionDetail {
  id: string
  topic: string
  level: Level
  question_count: number
  types: string[]
  status: SessionStatus
  stage?: string | null
  progress: number
  error?: string | null
  questions: Question[]
  sources: SourceItem[]
  answered_count: number
  model?: string | null
  created_at: string
  updated_at: string
}

export interface AnswerResult {
  question_id: string
  seq: number
  type: QuestionType
  type_label: string
  stem: string
  options: Option[]
  user_answer: string | string[] | null
  correct_answer: string | string[] | null
  is_correct: boolean
  score: number
  feedback: string
  explanation: string
  rubric: string[]
  source_refs: string[]
}

export interface Report {
  session_id: string
  topic: string
  level: string
  level_label: string
  score: number
  total: number
  correct: number
  accuracy: number
  summary: string
  level_tag: string
  by_type: Record<string, { total: number; correct: number }>
  items: AnswerResult[]
  knowledge_gaps: string[]
  next_steps: string[]
  suggested_topics: string[]
  sources: SourceItem[]
  duration_sec: number
  generated_at: string
  model?: string | null
  usage: { tokens_in: number; tokens_out: number; cost_cny: number; currency: string; note: string }
}

export const TYPE_META: Record<QuestionType, { label: string; short: string }> = {
  single_choice: { label: '单选题', short: '单选' },
  multiple_choice: { label: '多选题', short: '多选' },
  true_false: { label: '判断题', short: '判断' },
  short_answer: { label: '简答题', short: '简答' }
}

export const LEVEL_META: Record<Level, { label: string; desc: string }> = {
  basic: { label: '入门', desc: '概念与识记' },
  advanced: { label: '进阶', desc: '应用与推理' },
  challenge: { label: '挑战', desc: '边界与取舍' }
}