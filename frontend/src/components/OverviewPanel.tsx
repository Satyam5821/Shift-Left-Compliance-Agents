interface OverviewPanelProps {
  issuesCount: number
  fixesCount: number
  lastUpdated: string
  summary: Record<'BLOCKER' | 'CRITICAL' | 'MAJOR' | 'MINOR', number>
}

const OverviewPanel = ({ issuesCount, fixesCount, lastUpdated, summary }: OverviewPanelProps) => {
  return (
    <div className="space-y-4">
      {/* Metrics Grid */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Issues Found</p>
          <p className="mt-3 text-2xl font-bold text-white">{issuesCount}</p>
          <p className="mt-1 text-xs text-slate-400">Active in codebase</p>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">AI Fixes</p>
          <p className="mt-3 text-2xl font-bold text-white">{fixesCount}</p>
          <p className="mt-1 text-xs text-slate-400">Ready to apply</p>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Last Sync</p>
          <p className="mt-3 text-sm font-mono text-sky-400">{lastUpdated}</p>
          <p className="mt-1 text-xs text-slate-400">Live tracking</p>
        </div>
      </div>

      {/* Status Cards */}
      <div className="space-y-3">
        {/* Severity Breakdown */}
        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
          <p className="text-sm font-semibold text-white mb-3">Severity Breakdown</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="flex items-center justify-between rounded bg-slate-800 p-2">
              <span className="text-xs text-slate-400">🔴 Blockers</span>
              <span className="font-bold text-red-400">{summary.BLOCKER}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-slate-800 p-2">
              <span className="text-xs text-slate-400">🟠 Critical</span>
              <span className="font-bold text-orange-400">{summary.CRITICAL}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-slate-800 p-2">
              <span className="text-xs text-slate-400">🟡 Major</span>
              <span className="font-bold text-amber-400">{summary.MAJOR}</span>
            </div>
            <div className="flex items-center justify-between rounded bg-slate-800 p-2">
              <span className="text-xs text-slate-400">🟢 Minor</span>
              <span className="font-bold text-emerald-400">{summary.MINOR}</span>
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <div className={`rounded-lg border p-4 ${
          summary.BLOCKER > 0 || summary.CRITICAL > 0
            ? 'border-red-900/30 bg-red-950/20'
            : 'border-emerald-900/30 bg-emerald-950/20'
        }`}>
          <p className="text-sm font-semibold text-white">
            {summary.BLOCKER > 0 || summary.CRITICAL > 0
              ? '⚠️ High Priority Issues Detected'
              : '✓ All Clear'}
          </p>
          <p className="mt-1 text-xs text-slate-400">
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
