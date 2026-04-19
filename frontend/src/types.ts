export type TabKey = 'overview' | 'issues' | 'fixes' | 'analytics' | 'history' | 'scans'

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

export type ScanCounters = {
  applied?: number
  skipped?: number
  errors?: number
}

export type ScanDoc = {
  scan_id: string
  repo?: string
  base_branch?: string
  head_sha?: string
  workflow_run_id?: string | number
  webhook_mode?: string
  fix_limit?: number
  total_issues?: number
  issue_counts?: Record<string, number>
  apply_counters?: ScanCounters
  pr?: string | null
  pr_number?: number
  pr_state?: string | null
  pr_merged?: boolean | null
  pr_merged_at?: string | null
  pr_checked_at?: number
  created_at?: string
  updated_at?: string
}

export type ScanStats = {
  scan_count: number
  issues_resolved: number
  applied_total: number
  skipped_total: number
  errors_total: number
  prs_created: number
  prs_merged: number
  last_scan_at?: string | null
}

export type ScanWiseStats = {
  scan_count: number
  applied_total: number
  skipped_total: number
  errors_total: number
  prs_created: number
  prs_merged: number
  success_rate: number | null
}

export type ScanWiseResponse = {
  ok: true
  range: string
  since?: string | null
  stats: ScanWiseStats
  charts?: {
    severity_totals?: Record<string, number>
    file_hotspots?: { name: string; value: number }[]
    issue_trend?: { day: string; count: number }[]
    apply_status?: { name: string; value: number }[]
  }
  scans: ScanDoc[]
}

export type ScanIssue = {
  scan_id: string
  issue_key?: string
  rule?: string
  severity?: string
  message?: string
  file?: string
  line?: number
}

export type ScanFixAttempt = {
  scan_id: string
  issue_key?: string
  source?: 'cache' | 'generated' | string
  fix_json?: {
    problem?: string
    solution?: string
    code_changes?: unknown[]
  }
}
