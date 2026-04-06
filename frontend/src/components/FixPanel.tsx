import type { Fix } from '../types'
import { useEffect, useMemo, useState } from 'react'
import { useToast } from './Toast'

interface FixPanelProps {
  fixes: Fix[]
  expandedIssue: string | null
  toggleExpanded: (key: string) => void
  onViewIssue: (issueKey: string) => void
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

function getIssueFilePath(file: string) {
  return file.split(':').slice(1).join(':') || file
}

const FIX_PAGE_SIZE_KEY = 'slca.fixPageSize'

const FixPanel = ({ fixes, expandedIssue, toggleExpanded, onViewIssue }: FixPanelProps) => {
  const toast = useToast()
  const [pageSize, setPageSize] = useState<number>(() => {
    if (typeof window === 'undefined') return 25
    const saved = Number(window.localStorage.getItem(FIX_PAGE_SIZE_KEY))
    return saved && saved > 0 ? saved : 25
  })
  const [pageIndex, setPageIndex] = useState<number>(0)

  const totalPages = Math.max(1, Math.ceil(fixes.length / pageSize))

  const pageFixes = useMemo(() => {
    const start = pageIndex * pageSize
    const end = start + pageSize
    return fixes.slice(start, end)
  }, [fixes, pageIndex, pageSize])

  useEffect(() => {
    if (!expandedIssue) return
    const idx = fixes.findIndex((x) => x.issue.key === expandedIssue)
    if (idx < 0) return
    const nextPage = Math.floor(idx / pageSize)
    setPageIndex(nextPage)
  }, [expandedIssue, fixes, pageSize])

  useEffect(() => {
    setPageIndex((p) => Math.min(p, totalPages - 1))
  }, [totalPages])

  useEffect(() => {
    window.localStorage.setItem(FIX_PAGE_SIZE_KEY, String(pageSize))
  }, [pageSize])

  function normalizeFixText(fix: unknown): string {
    if (typeof fix === 'string') return fix

    // Backend sometimes returns: { raw_response: ... }
    if (fix && typeof fix === 'object' && 'raw_response' in fix) {
      const raw = (fix as { raw_response?: unknown }).raw_response
      return typeof raw === 'string' ? raw : JSON.stringify(raw ?? fix)
    }

    try {
      return JSON.stringify(fix)
    } catch {
      return String(fix)
    }
  }

  if (fixes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
        No fixes available. Run a scan to generate recommendations.
      </div>
    )
  }

  const showingStart = pageIndex * pageSize + 1
  const showingEnd = Math.min(fixes.length, pageIndex * pageSize + pageSize)

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <label htmlFor="fix-page-size" className="text-xs font-semibold uppercase text-(--muted)">
            Page size
          </label>
          <select
            id="fix-page-size"
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
          {fixes.length} fixes · showing {showingStart}-{showingEnd}
        </p>
      </div>

      <div className="space-y-3">
        {pageFixes.map((item) => (
          <div
            key={item.issue.key}
            onClick={() => toggleExpanded(item.issue.key)}
            className={`group rounded-lg border p-4 transition cursor-pointer ${
              expandedIssue === item.issue.key
                ? 'border-teal-400/50 bg-teal-400/10'
                : 'border-(--border) bg-(--panel-2) hover:border-(--border-soft) hover:bg-(--surface-hover)'
            }`}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${getSeverityColor(item.issue.severity)}`}>
                    {item.issue.severity}
                  </span>
                  <span className="rounded-full px-2 py-0.5 text-xs font-medium bg-teal-400/15 text-teal-800 border border-teal-400/25">
                    AI Fix
                  </span>
                </div>
                <h3 className="mt-2 text-sm font-semibold text-(--text) break-all whitespace-normal">{item.issue.message}</h3>
              </div>
              <div className="text-right text-xs text-(--muted) shrink-0">
                <p className="font-semibold text-(--text)">Line {item.issue.line}</p>
                <p className="break-all">{item.issue.file.split(':').slice(1).join(':')}</p>
              </div>
            </div>

            {expandedIssue === item.issue.key && (
              <div className="mt-4 space-y-3">
                <div className="rounded-lg border border-(--border) bg-(--panel-2) p-3">
                  <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Where to change</p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-3">
                    <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-2">
                      <p className="text-[11px] uppercase tracking-wider text-(--muted)">File</p>
                      <p className="mt-1 break-all font-mono text-xs text-(--text)">{getIssueFilePath(item.issue.file)}</p>
                    </div>
                    <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-2">
                      <p className="text-[11px] uppercase tracking-wider text-(--muted)">Line</p>
                      <p className="mt-1 font-mono text-xs text-(--text)">{item.issue.line}</p>
                    </div>
                    <div className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-2">
                      <p className="text-[11px] uppercase tracking-wider text-(--muted)">Issue</p>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          onViewIssue(item.issue.key)
                        }}
                        className="mt-1 inline-flex items-center justify-center rounded-md border border-violet-500/20 bg-violet-500/10 px-2 py-1 text-xs font-semibold text-violet-600 transition hover:bg-violet-500/15"
                      >
                        View in Issues
                      </button>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg bg-(--surface-elevated) p-3 border border-(--border)">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="text-xs font-semibold text-(--accent-teal) uppercase tracking-wider">What to change</p>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        const fixText = normalizeFixText(item.fix)
                        try {
                          await navigator.clipboard.writeText(fixText)
                          toast.push({ kind: 'success', title: 'Copied', message: 'Fix copied to clipboard' })
                        } catch {
                          toast.push({ kind: 'error', title: 'Copy failed', message: 'Clipboard permission denied' })
                        }
                      }}
                      className="rounded-lg border border-teal-400/25 bg-teal-400/10 px-2.5 py-1 text-xs font-semibold text-(--accent-teal) transition hover:bg-teal-400/15"
                    >
                      Copy
                    </button>
                  </div>
                  <pre className="max-h-60 overflow-auto rounded bg-(--code-bg) p-3 text-xs text-(--text) font-mono border border-(--code-border)">
                    {normalizeFixText(item.fix)}
                  </pre>
                  <p className="mt-2 text-[11px] text-(--muted)">
                    Tip: paste this change into <span className="font-mono text-(--text)">{getIssueFilePath(item.issue.file)}</span> near line{' '}
                    <span className="font-mono text-(--text)">{item.issue.line}</span>.
                  </p>
                </div>
              </div>
            )}
          </div>
        ))}
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

export default FixPanel
