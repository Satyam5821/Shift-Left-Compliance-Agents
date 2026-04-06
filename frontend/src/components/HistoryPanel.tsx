interface ScanSnapshot {
  id: string
  ts: number
  source: 'overview' | 'issues' | 'fixes' | 'analytics' | 'manual'
  issuesCount: number
  fixesCount: number
  blocker: number
  critical: number
}

function formatTs(ts: number) {
  const d = new Date(ts)
  return d.toLocaleString()
}

function formatDelta(n: number) {
  if (n === 0) return '0'
  return n > 0 ? `+${n}` : `${n}`
}

export default function HistoryPanel({
  history,
  onClear,
}: {
  history: ScanSnapshot[]
  onClear: () => void
}) {
  if (history.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
        No scan history yet. Click <span className="font-semibold text-(--text)">Sync Latest</span> to create snapshots.
      </div>
    )
  }

  const latest = history[0]
  const previous = history[1]

  const dIssues = previous ? latest.issuesCount - previous.issuesCount : 0
  const dFixes = previous ? latest.fixesCount - previous.fixesCount : 0
  const dCritical = previous ? (latest.blocker + latest.critical) - (previous.blocker + previous.critical) : 0

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 className="text-sm font-semibold text-(--text)">Latest vs previous</h3>
            <p className="mt-1 text-xs text-(--muted)">Quick deltas between last two snapshots</p>
          </div>
          <button
            onClick={onClear}
            className="inline-flex items-center justify-center rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-100 transition hover:bg-rose-500/15"
          >
            Clear history
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-3">
            <p className="text-xs text-(--muted)">Issues</p>
            <p className="mt-1 text-2xl font-bold text-(--text)">{latest.issuesCount}</p>
            <p className="mt-1 text-xs text-(--muted)">Δ {formatDelta(dIssues)}</p>
          </div>
          <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-3">
            <p className="text-xs text-(--muted)">Critical (B+C)</p>
            <p className="mt-1 text-2xl font-bold text-(--text)">{latest.blocker + latest.critical}</p>
            <p className="mt-1 text-xs text-(--muted)">Δ {formatDelta(dCritical)}</p>
          </div>
          <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-3">
            <p className="text-xs text-(--muted)">Fixes</p>
            <p className="mt-1 text-2xl font-bold text-(--text)">{latest.fixesCount}</p>
            <p className="mt-1 text-xs text-(--muted)">Δ {formatDelta(dFixes)}</p>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-(--text)">Timeline</h3>
          <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-3 py-1 text-xs font-medium text-(--muted)">
            {history.length} snapshot{history.length !== 1 ? 's' : ''}
          </span>
        </div>

        <div className="mt-3 overflow-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-xs text-(--muted)">
                <th className="py-2 pr-4">Time</th>
                <th className="py-2 pr-4">Source</th>
                <th className="py-2 pr-4">Issues</th>
                <th className="py-2 pr-4">Critical</th>
                <th className="py-2 pr-4">Fixes</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h, idx) => {
                const prev = history[idx + 1]
                const ddIssues = prev ? h.issuesCount - prev.issuesCount : 0
                const ddFixes = prev ? h.fixesCount - prev.fixesCount : 0
                const ddCritical = prev ? (h.blocker + h.critical) - (prev.blocker + prev.critical) : 0
                return (
                  <tr key={h.id} className="border-t border-(--border-soft)">
                    <td className="py-3 pr-4 text-xs text-(--text) whitespace-nowrap">{formatTs(h.ts)}</td>
                    <td className="py-3 pr-4 text-xs text-(--muted) whitespace-nowrap">{h.source}</td>
                    <td className="py-3 pr-4 text-xs text-(--text) whitespace-nowrap">
                      {h.issuesCount}{' '}
                      <span className="text-(--muted)">({formatDelta(ddIssues)})</span>
                    </td>
                    <td className="py-3 pr-4 text-xs text-(--text) whitespace-nowrap">
                      {h.blocker + h.critical}{' '}
                      <span className="text-(--muted)">({formatDelta(ddCritical)})</span>
                    </td>
                    <td className="py-3 pr-4 text-xs text-(--text) whitespace-nowrap">
                      {h.fixesCount}{' '}
                      <span className="text-(--muted)">({formatDelta(ddFixes)})</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

