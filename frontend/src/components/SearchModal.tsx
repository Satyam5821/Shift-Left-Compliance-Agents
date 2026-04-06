import { useEffect, useMemo, useRef, useState } from 'react'
import type { Issue } from '../types'

interface SearchModalProps {
  open: boolean
  onClose: () => void
  issues: Issue[]
  onSelectIssue: (issue: Issue) => void
}

function getIssueFile(issue: Issue) {
  return issue.file.split(':').slice(1).join(':') || issue.file
}

const SearchModal = ({ open, onClose, issues, onSelectIssue }: SearchModalProps) => {
  const [query, setQuery] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (!open) return
    setQuery('')
    const t = window.setTimeout(() => inputRef.current?.focus(), 0)
    return () => window.clearTimeout(t)
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return issues.slice(0, 20)

    const scored = issues.map((issue) => {
      const file = getIssueFile(issue).toLowerCase()
      const message = issue.message.toLowerCase()
      const severity = issue.severity.toLowerCase()
      const status = issue.status.toLowerCase()

      const hay = `${severity} ${status} ${file} ${message}`
      const idx = hay.indexOf(q)
      const score = idx === -1 ? 9999 : idx
      return { issue, score }
    })

    return scored
      .filter((x) => x.score !== 9999)
      .sort((a, b) => a.score - b.score)
      .slice(0, 30)
      .map((x) => x.issue)
  }, [issues, query])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-100">
      <div className="absolute inset-0 bg-black/55" onClick={onClose} />
      <div className="absolute left-1/2 top-[14%] w-[min(820px,calc(100vw-2rem))] -translate-x-1/2">
        <div className="rounded-2xl border border-(--border) bg-(--panel) backdrop-blur shadow-2xl shadow-(color:--shadow)">
          <div className="flex items-center gap-3 border-b border-(--border-soft) px-4 py-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-violet-500/20 bg-violet-500/10 text-violet-600">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M10.5 18a7.5 7.5 0 1 1 5.4-2.3L20 19.8"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              </svg>
            </div>
            <div className="flex-1">
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search issues by message, file, severity…"
                className="w-full bg-transparent text-sm text-(--text) placeholder:text-(--muted) outline-none"
              />
              <p className="mt-1 text-xs text-(--muted)">
                Tip: press <span className="font-mono text-(--text)">Esc</span> to close
              </p>
            </div>
            <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-2.5 py-1 text-[11px] font-medium text-(--muted)">
              {issues.length} issues
            </span>
          </div>

          <div className="max-h-[55vh] overflow-auto p-2">
            {results.length === 0 ? (
              <div className="rounded-xl border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
                No results. Try a different keyword.
              </div>
            ) : (
              <div className="space-y-2">
                {results.map((issue) => (
                  <button
                    key={issue.key}
                    onClick={() => {
                      onSelectIssue(issue)
                      onClose()
                    }}
                    className="w-full rounded-xl border border-(--border) bg-(--surface-elevated) px-3 py-3 text-left transition hover:border-(--border-soft) hover:bg-(--surface-hover)"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 text-xs font-semibold text-violet-600">
                            {issue.severity}
                          </span>
                          <span className="rounded-full border border-(--border) bg-(--panel-2) px-2 py-0.5 text-xs font-medium text-(--muted)">
                            {issue.status}
                          </span>
                        </div>
                        <p className="mt-2 truncate text-sm font-semibold text-(--text)">{issue.message}</p>
                        <p className="mt-1 truncate text-xs text-(--muted)">{getIssueFile(issue)}</p>
                      </div>
                      <span className="shrink-0 rounded-lg bg-(--panel-2) px-2 py-1 text-xs font-semibold text-(--text)">
                        Line {issue.line}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-(--border-soft) px-4 py-3 text-xs text-(--muted)">
            <span>
              Open search: <span className="font-mono text-(--text)">Ctrl</span> +{' '}
              <span className="font-mono text-(--text)">K</span>
            </span>
            <span>Jump opens Issues and expands selection</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default SearchModal
