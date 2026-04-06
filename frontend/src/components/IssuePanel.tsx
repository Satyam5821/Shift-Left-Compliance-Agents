import { useEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
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
  return status === 'open' ? 'bg-teal-400 text-zinc-950' : 'bg-neutral-600 text-white'
}

function IssueRow({
  issue,
  expanded,
  onToggle,
}: {
  issue: Issue
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <div
      onClick={onToggle}
      className={`group rounded-lg border p-4 transition cursor-pointer ${
        expanded
          ? 'border-violet-500/50 bg-violet-500/10'
          : 'border-(--border) bg-(--panel-2) hover:border-(--border-soft) hover:bg-(--surface-hover)'
      }`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${getSeverityColor(issue.severity)}`}>
              {issue.severity}
            </span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getStatusColor(issue.status)}`}>
              {issue.status}
            </span>
          </div>
          {/* Allow long regex/messages to wrap instead of overflowing */}
          <h3 className="mt-2 text-sm font-semibold text-(--text) break-all whitespace-normal">
            {issue.message}
          </h3>
        </div>
        <div className="text-right text-xs text-(--muted) shrink-0">
          <p className="font-semibold text-(--text)">Line {issue.line}</p>
          <p className="truncate max-w-xs">{issue.file.split(':').slice(1).join(':')}</p>
        </div>
      </div>

      {expanded && (
        <div className="mt-4 rounded-lg bg-(--surface-elevated) p-3 text-xs border border-(--border)">
          <p className="text-(--muted)">Key:</p>
          <p className="mt-1 break-all font-mono text-(--text)">{issue.key}</p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <div className="rounded bg-(--panel-2) p-2 border border-(--border-soft)">
              <p className="text-xs uppercase text-(--muted) font-medium">File</p>
              <p className="mt-1 break-all text-(--text) text-xs">{issue.file}</p>
            </div>
            <div className="rounded bg-(--panel-2) p-2 border border-(--border-soft)">
              <p className="text-xs uppercase text-(--muted) font-medium">Created</p>
              <p className="mt-1 text-(--text) text-xs">{new Date(issue.created_at).toLocaleDateString()}</p>
            </div>
            <div className="rounded bg-(--panel-2) p-2 border border-(--border-soft)">
              <p className="text-xs uppercase text-(--muted) font-medium">Status</p>
              <p className="mt-1 text-xs font-medium text-(--accent-teal)">{issue.status}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const ISSUE_PAGE_SIZE_KEY = 'slca.issuePageSize'

const IssuePanel = ({ issues, expandedIssue, toggleExpanded, sortBy, setSortBy }: IssuePanelProps) => {
  const parentRef = useRef<HTMLDivElement>(null)
  const [pageSize, setPageSize] = useState<number>(() => {
    if (typeof window === 'undefined') return 25
    const saved = Number(window.localStorage.getItem(ISSUE_PAGE_SIZE_KEY))
    return saved && saved > 0 ? saved : 25
  })
  const [pageIndex, setPageIndex] = useState<number>(0)

  const totalPages = Math.max(1, Math.ceil(issues.length / pageSize))

  const pageIssues = useMemo(() => {
    const start = pageIndex * pageSize
    const end = start + pageSize
    return issues.slice(start, end)
  }, [issues, pageIndex, pageSize])

  const virtualizer = useVirtualizer({
    count: pageIssues.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 132,
    overscan: 10,
    measureElement: (el) => el.getBoundingClientRect().height,
  })

  useEffect(() => {
    virtualizer.measure()
  }, [expandedIssue, pageIssues.length, virtualizer])

  // If user expands an issue (e.g., from Fixes/Search), move to the page containing it.
  useEffect(() => {
    if (!expandedIssue) return
    const idx = issues.findIndex((x) => x.key === expandedIssue)
    if (idx < 0) return
    const nextPage = Math.floor(idx / pageSize)
    setPageIndex(nextPage)
  }, [expandedIssue, issues, pageSize])

  // When sorting changes, reset to first page for predictable navigation.
  useEffect(() => {
    setPageIndex(0)
  }, [sortBy])

  useEffect(() => {
    window.localStorage.setItem(ISSUE_PAGE_SIZE_KEY, String(pageSize))
  }, [pageSize])

  if (issues.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
        No issues found. Your code is clean! ✨
      </div>
    )
  }

  const showingStart = pageIndex * pageSize + 1
  const showingEnd = Math.min(issues.length, pageIndex * pageSize + pageSize)

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <label htmlFor="sort-select" className="text-xs font-semibold uppercase text-(--muted)">
            Sort by:
          </label>
          <select
            id="sort-select"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'severity' | 'date' | 'file')}
            className="rounded-lg border border-(--border) bg-(--panel-2) px-3 py-2 text-sm font-medium text-(--text) cursor-pointer hover:border-(--border-soft) transition"
          >
            <option value="severity">Severity (Highest First)</option>
            <option value="date">Date (Newest First)</option>
            <option value="file">File Name</option>
          </select>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <label htmlFor="page-size" className="text-xs font-semibold uppercase text-(--muted)">
              Page size
            </label>
            <select
              id="page-size"
              value={pageSize}
              onChange={(e) => {
                const next = Number(e.target.value) || 25
                setPageSize(next)
                setPageIndex(0)
              }}
              className="rounded-lg border border-(--border) bg-(--panel-2) px-2 py-2 text-xs font-medium text-(--text) cursor-pointer hover:border-(--border-soft) transition"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
            </select>
          </div>
          <p className="text-xs text-(--muted)">
            {issues.length} issue{issues.length !== 1 ? 's' : ''} · showing {showingStart}-{showingEnd}
          </p>
        </div>
      </div>

      <div
        ref={parentRef}
        className="max-h-[min(70vh,720px)] overflow-auto rounded-lg border border-(--border) bg-(--panel-2)"
        role="list"
        aria-label="Issues list"
      >
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const issue = pageIssues[virtualRow.index]
            const expanded = expandedIssue === issue.key
            return (
              <div
                key={issue.key}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="px-3 py-2"
              >
                <IssueRow
                  issue={issue}
                  expanded={expanded}
                  onToggle={() => toggleExpanded(issue.key)}
                />
              </div>
            )
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 text-xs text-(--muted)">
          <span>Page</span>
          <span className="font-semibold text-(--text)">
            {pageIndex + 1}/{totalPages}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setPageIndex((p) => Math.max(0, p - 1))}
            disabled={pageIndex === 0}
            className="inline-flex items-center justify-center rounded-lg border border-(--border) bg-(--panel-2) px-3 py-2 text-xs font-semibold text-(--text) disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Prev
          </button>
          <button
            onClick={() => setPageIndex((p) => Math.min(totalPages - 1, p + 1))}
            disabled={pageIndex >= totalPages - 1}
            className="inline-flex items-center justify-center rounded-lg border border-(--border) bg-(--panel-2) px-3 py-2 text-xs font-semibold text-(--text) disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}

export default IssuePanel
