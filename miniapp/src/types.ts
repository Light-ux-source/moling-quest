export type QuestionType = 'single_choice' | 'multiple_choice' | 'true_false' | 'short_answer'
export type Level = 'basic' | 'advanced' | 'challenge'
export type ChapterKind = 'standard' | 'daily' | 'comprehensive' | 'review'

export interface Option {
  key: string
  text: string
}

export interface Question {
  id: string
  seq: number
  type: QuestionType
  title: string
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
  chapter_id?: string | null
  parent_chapter_id?: string | null
  topic: string
  level: Level
  question_count: number
  types: string[]
  kind: ChapterKind
  status: SessionStatus
  stage?: string | null
  progress: number
  current_seq: number
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

export interface RankInfo {
  key: string
  label: string
  exp: number
  next_key?: string | null
  next_label?: string | null
  exp_to_next: number
  progress_pct: number
}

export interface Settlement {
  session_id: string
  chapter_id?: string | null
  stars: number
  accuracy: number
  correct: number
  total: number
  exp: number
  combo: number
  wrong_count: number
  duration_sec: number
  rank_before: RankInfo
  rank_after: RankInfo
  level_up: boolean
  exp_to_next: number
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
  settlement?: Settlement | null
}

export interface ChapterProgress {
  done: number
  total: number
}

export type ChapterNodeStatus = 'done' | 'current' | 'locked' | 'unlocked'

export interface ChapterNode {
  seq: number
  title: string
  kind: 'question' | 'comprehensive'
  status: ChapterNodeStatus
  stars: number
  score: number
  is_correct: boolean
  question_id?: string | null
  chapter_id?: string | null
  session_id?: string | null
}

export interface ChapterDetail {
  id: string
  session_id: string
  parent_chapter_id?: string | null
  title: string
  topic: string
  level: Level
  question_count: number
  kind: ChapterKind
  status: SessionStatus
  error?: string | null
  stars: number
  accuracy: number
  exp: number
  progress: ChapterProgress
  current_node: number
  nodes: ChapterNode[]
  comprehensive?: ChapterNode | null
  sources: SourceItem[]
  created_at: string
  completed_at?: string | null
}

export interface ChapterSummary {
  id: string
  session_id: string
  title: string
  topic: string
  level: Level
  question_count: number
  kind: ChapterKind
  status: SessionStatus | null
  stars: number
  accuracy: number
  exp: number
  progress: ChapterProgress
  next_title: string
  created_at: string
  completed_at?: string | null
}

export interface Profile {
  client_id: string
  nickname: string
  chapters_completed: number
  total_stars: number
  total_exp: number
  leaf_count: number
  streak_days: number
  rank: RankInfo
  quota: { used: number; limit: number; remaining: number; period: string }
  weekly: Array<{ date: string; exp: number }>
  recent_chapters: ChapterSummary[]
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

export const DIFFICULTY_META: Record<string, string> = {
  easy: '基础',
  medium: '中等',
  hard: '较难'
}

export const ALL_TYPES: QuestionType[] = [
  'single_choice',
  'multiple_choice',
  'true_false',
  'short_answer'
]