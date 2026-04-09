export type TabKey = 'overview' | 'issues' | 'fixes' | 'analytics' | 'history'

export interface Issue {
  key: string
  message: string
  severity: 'MINOR' | 'MAJOR' | 'CRITICAL' | 'BLOCKER'
  file: string
  line: number
  status: string
  created_at: string
}

export interface Fix {
  issue: Issue
  fix: string
  fix_raw?: string | null
  fix_json?: unknown
  source?: 'cache' | 'generated'
  llm_meta?: {
    provider?: string | null
    errors?: string[]
  }
}
