import type { Issue } from '../types'

interface IssuePanelProps {
  issues: Issue[]
  expandedIssue: string | null
  toggleExpanded: (key: string) => void
  sortBy: 'severity' | 'date' | 'file'
  setSortBy: (sort: 'severity' | 'date' | 'file') => void
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

const getStatusColor = (status: string) => {
  return status === 'open' ? 'bg-emerald-500 text-slate-950' : 'bg-slate-500 text-white'
}

const IssuePanel = ({ issues, expandedIssue, toggleExpanded, sortBy, setSortBy }: IssuePanelProps) => {
  if (issues.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-600 p-8 text-center text-slate-400">
        No issues found. Your code is clean! ✨
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Sort Controls */}
      <div className="flex items-center gap-2">
        <label htmlFor="sort-select" className="text-xs font-semibold uppercase text-slate-400">
          Sort by:
        </label>
        <select
          id="sort-select"
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as 'severity' | 'date' | 'file')}
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm font-medium text-white cursor-pointer hover:border-slate-600 transition"
        >
          <option value="severity">Severity (Highest First)</option>
          <option value="date">Date (Newest First)</option>
          <option value="file">File Name</option>
        </select>
      </div>

      {/* Issues List */}
      <div className="space-y-3">
      {issues.map((issue) => (
        <div
          key={issue.key}
          onClick={() => toggleExpanded(issue.key)}
          className={`group rounded-lg border p-4 transition cursor-pointer ${
            expandedIssue === issue.key
              ? 'border-sky-500/50 bg-sky-500/10'
              : 'border-slate-700 bg-slate-800/30 hover:border-slate-600 hover:bg-slate-800/50'
          }`}
        >
          <div className="flex items-start justify-between gap-4">
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${getSeverityColor(issue.severity)}`}>
                  {issue.severity}
                </span>
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getStatusColor(issue.status)}`}>
                  {issue.status}
                </span>
              </div>
              <h3 className="mt-2 text-sm font-semibold text-white">{issue.message}</h3>
            </div>
            <div className="text-right text-xs text-slate-400">
              <p className="font-semibold text-slate-200">Line {issue.line}</p>
              <p className="truncate max-w-xs">{issue.file.split(':').slice(1).join(':')}</p>
            </div>
          </div>

          {expandedIssue === issue.key && (
            <div className="mt-4 rounded-lg bg-slate-900 p-3 text-xs border border-slate-700">
              <p className="text-slate-400">Key:</p>
              <p className="mt-1 break-all font-mono text-slate-200">{issue.key}</p>
              <div className="mt-3 grid gap-2 sm:grid-cols-3">
                <div className="rounded bg-slate-800 p-2">
                  <p className="text-xs uppercase text-slate-500 font-medium">File</p>
                  <p className="mt-1 text-slate-300 text-xs">{issue.file}</p>
                </div>
                <div className="rounded bg-slate-800 p-2">
                  <p className="text-xs uppercase text-slate-500 font-medium">Created</p>
                  <p className="mt-1 text-slate-300 text-xs">{new Date(issue.created_at).toLocaleDateString()}</p>
                </div>
                <div className="rounded bg-slate-800 p-2">
                  <p className="text-xs uppercase text-slate-500 font-medium">Status</p>
                  <p className="mt-1 text-emerald-400 text-xs font-medium">{issue.status}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      ))}
      </div>
    </div>
  )
}

export default IssuePanel
