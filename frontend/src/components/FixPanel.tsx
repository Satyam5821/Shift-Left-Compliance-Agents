import type { Fix } from '../types'

interface FixPanelProps {
  fixes: Fix[]
  expandedIssue: string | null
  toggleExpanded: (key: string) => void
}

const getSeverityColor = (severity: string) => {
  switch (severity) {
    case 'BLOCKER':
      return 'bg-red-900 text-white'
    case 'CRITICAL':
      return 'bg-red-600 text-white'
    case 'MAJOR':
      return 'bg-orange-500 text-white'
    case 'MINOR':
      return 'bg-yellow-400 text-black'
    default:
      return 'bg-gray-400 text-white'
  }
}

const FixPanel = ({ fixes, expandedIssue, toggleExpanded }: FixPanelProps) => {
  if (fixes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-600 p-8 text-center text-slate-400">
        No fixes available. Run a scan to generate recommendations.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {fixes.map((item, idx) => (
        <div
          key={`${item.issue.key}-${idx}`}
          onClick={() => toggleExpanded(item.issue.key)}
          className={`group rounded-lg border p-4 transition cursor-pointer ${
            expandedIssue === item.issue.key
              ? 'border-emerald-500/50 bg-emerald-500/10'
              : 'border-slate-700 bg-slate-800/30 hover:border-slate-600 hover:bg-slate-800/50'
          }`}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${getSeverityColor(item.issue.severity)}`}>
                  {item.issue.severity}
                </span>
                <span className="rounded-full px-2 py-0.5 text-xs font-medium bg-emerald-500/20 text-emerald-400">
                  AI Fix
                </span>
              </div>
              <h3 className="mt-2 text-sm font-semibold text-white">{item.issue.message}</h3>
            </div>
            <div className="text-right text-xs text-slate-400">
              <p className="font-semibold text-slate-200">Line {item.issue.line}</p>
              <p className="truncate max-w-xs">{item.issue.file.split(':').slice(1).join(':')}</p>
            </div>
          </div>

          {expandedIssue === item.issue.key && (
            <div className="mt-4 space-y-3">
              <div className="rounded-lg bg-slate-900 p-3 border border-slate-700">
                <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-2">Suggested Fix</p>
                <pre className="max-h-60 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-200 font-mono border border-slate-800">
                  {item.fix}
                </pre>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export default FixPanel
