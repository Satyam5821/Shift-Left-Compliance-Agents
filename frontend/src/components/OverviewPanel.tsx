import type { ScanStats } from '../types'

interface OverviewPanelProps {
  issuesCount: number
  fixesCount: number
  lastUpdated: string
  summary: Record<'BLOCKER' | 'CRITICAL' | 'MAJOR' | 'MINOR', number>
  scanStats?: ScanStats | null
}

const OverviewPanel = ({ issuesCount, fixesCount, lastUpdated, summary, scanStats }: OverviewPanelProps) => {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Issues Found</p>
          <p className="mt-3 text-2xl font-bold text-(--text)">{issuesCount}</p>
          <p className="mt-1 text-xs text-(--muted)">Active in codebase</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">AI Fixes</p>
          <p className="mt-3 text-2xl font-bold text-(--text)">{fixesCount}</p>
          <p className="mt-1 text-xs text-(--muted)">Ready to apply</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Issues Resolved</p>
          <p className="mt-3 text-2xl font-bold text-(--accent-teal)">{scanStats?.issues_resolved ?? '—'}</p>
          <p className="mt-1 text-xs text-(--muted)">Applied across scans</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">PRs Merged</p>
          <p className="mt-3 text-2xl font-bold text-violet-300">{scanStats?.prs_merged ?? '—'}</p>
          <p className="mt-1 text-xs text-(--muted)">Verified via GitHub API</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">PRs Created</p>
          <p className="mt-3 text-2xl font-bold text-(--text)">{scanStats?.prs_created ?? '—'}</p>
          <p className="mt-1 text-xs text-(--muted)">Scans with a PR link</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Last Sync</p>
          <p className="mt-3 text-sm font-mono text-violet-500">{lastUpdated}</p>
          <p className="mt-1 text-xs text-(--muted)">Live tracking</p>
        </div>
      </div>

      <div className="space-y-3">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-sm font-semibold text-(--text) mb-3">Severity Breakdown</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="flex items-center justify-between rounded border border-(--border-soft) bg-(--surface-elevated) p-2">
              <span className="text-xs text-(--muted)">🔴 Blockers</span>
              <span className="font-bold text-red-500">{summary.BLOCKER}</span>
            </div>
            <div className="flex items-center justify-between rounded border border-(--border-soft) bg-(--surface-elevated) p-2">
              <span className="text-xs text-(--muted)">🟠 Critical</span>
              <span className="font-bold text-orange-500">{summary.CRITICAL}</span>
            </div>
            <div className="flex items-center justify-between rounded border border-(--border-soft) bg-(--surface-elevated) p-2">
              <span className="text-xs text-(--muted)">🟡 Major</span>
              <span className="font-bold text-amber-500">{summary.MAJOR}</span>
            </div>
            <div className="flex items-center justify-between rounded border border-(--border-soft) bg-(--surface-elevated) p-2">
              <span className="text-xs text-(--muted)">🟢 Minor</span>
              <span className="font-bold text-emerald-600">{summary.MINOR}</span>
            </div>
          </div>
        </div>

        <div
          className={`rounded-lg border p-4 ${
            summary.BLOCKER > 0 || summary.CRITICAL > 0
              ? 'border-red-900/30 bg-red-950/20'
              : 'border-emerald-900/30 bg-emerald-950/20'
          }`}
        >
          <p className="text-sm font-semibold text-(--text)">
            {summary.BLOCKER > 0 || summary.CRITICAL > 0 ? '⚠️ High Priority Issues Detected' : '✓ All Clear'}
          </p>
          <p className="mt-1 text-xs text-(--muted)">
            {summary.BLOCKER > 0 || summary.CRITICAL > 0
              ? `${summary.BLOCKER + summary.CRITICAL} critical issue${summary.BLOCKER + summary.CRITICAL !== 1 ? 's' : ''} require attention`
              : 'No blocker or critical issues found'}
          </p>
        </div>
      </div>
    </div>
  )
}

export default OverviewPanel
