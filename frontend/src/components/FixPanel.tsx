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

type FixChange =
  | {
      op: 'move'
      from: string
      to: string
      notes?: string
    }
  | {
      op: 'replace' | 'insert_before' | 'insert_after' | 'delete'
      file: string
      line?: number
      old_code?: string
      new_code?: string
      notes?: string
    }

type FixJson = {
  problem?: string
  solution?: string
  explanation?: string
  best_practice?: string
  fixed_code?: string
  code_changes?: FixChange[]
}

type SnippetLine = { line: number; text: string }
type SnippetResponse =
  | { ok: true; file: string; start: number; end: number; total: number; lines: SnippetLine[] }
  | { ok: false; error: string; file: string }

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

  function asFixJson(value: unknown): FixJson | null {
    if (!value || typeof value !== 'object') return null
    return value as FixJson
  }

  function extractFixJson(item: Fix): FixJson | null {
    const direct = asFixJson((item as Fix & { fix_json?: unknown }).fix_json)
    if (direct) return direct

    // Sometimes the backend stores fix as JSON string
    try {
      const parsed = JSON.parse(item.fix)
      return asFixJson(parsed)
    } catch {
      return null
    }
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text)
      toast.push({ kind: 'success', title: 'Copied', message: 'Copied to clipboard' })
    } catch {
      toast.push({ kind: 'error', title: 'Copy failed', message: 'Clipboard permission denied' })
    }
  }

  const API_BASE = (import.meta as unknown as { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

  const [snippetCache, setSnippetCache] = useState<Record<string, SnippetResponse>>({})
  const [previewMode, setPreviewMode] = useState<Record<string, 'split' | 'unified'>>({})

  async function getSnippet(file: string, line: number, radius: number) {
    const key = `${file}:${line}:${radius}`
    if (snippetCache[key]) return snippetCache[key]

    try {
      const res = await fetch(`${API_BASE}/snippet?file=${encodeURIComponent(file)}&line=${encodeURIComponent(String(line))}&radius=${encodeURIComponent(String(radius))}`)
      const data = (await res.json()) as SnippetResponse
      setSnippetCache((prev) => ({ ...prev, [key]: data }))
      return data
    } catch {
      const data: SnippetResponse = { ok: false, error: 'Failed to load snippet', file }
      setSnippetCache((prev) => ({ ...prev, [key]: data }))
      return data
    }
  }

  function applyChangeToLines(lines: SnippetLine[], change: FixChange): SnippetLine[] {
    if (change.op === 'move') return lines

    const next = lines.map((l) => ({ ...l }))
    const lineNo = typeof change.line === 'number' ? change.line : undefined
    const idx = lineNo ? next.findIndex((l) => l.line === lineNo) : -1

    if (change.op === 'replace' && idx >= 0 && typeof change.new_code === 'string') {
      next[idx] = { ...next[idx], text: change.new_code }
      return next
    }
    if (change.op === 'insert_before' && idx >= 0 && typeof change.new_code === 'string') {
      const insertLines = change.new_code.split('\n').map((t, i) => ({ line: next[idx].line - 0.1 - i * 0.001, text: t }))
      return [...next.slice(0, idx), ...insertLines.reverse(), ...next.slice(idx)]
    }
    if (change.op === 'insert_after' && idx >= 0 && typeof change.new_code === 'string') {
      const insertLines = change.new_code.split('\n').map((t, i) => ({ line: next[idx].line + 0.1 + i * 0.001, text: t }))
      return [...next.slice(0, idx + 1), ...insertLines, ...next.slice(idx + 1)]
    }
    if (change.op === 'delete' && idx >= 0) {
      return [...next.slice(0, idx), ...next.slice(idx + 1)]
    }
    return next
  }

  function renderUnifiedDiff(before: SnippetLine[], after: SnippetLine[]) {
    const max = Math.max(before.length, after.length)
    const out: string[] = []
    for (let i = 0; i < max; i++) {
      const b = before[i]
      const a = after[i]

      if (b && a && b.text === a.text) {
        out.push(` ${String(b.line).padStart(4, ' ')}  ${b.text}`)
        continue
      }

      if (b) out.push(`-${String(b.line).padStart(4, ' ')}  ${b.text}`)
      if (a) out.push(`+${String(a.line).padStart(4, ' ')}  ${a.text}`)
    }
    return out.join('\n')
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
                    <p className="text-xs font-semibold text-(--accent-teal) uppercase tracking-wider">Fix</p>
                    <button
                      onClick={async (e) => {
                        e.stopPropagation()
                        const fixText = normalizeFixText(item.fix)
                        await copyText(fixText)
                      }}
                      className="rounded-lg border border-teal-400/25 bg-teal-400/10 px-2.5 py-1 text-xs font-semibold text-(--accent-teal) transition hover:bg-teal-400/15"
                    >
                      Copy
                    </button>
                  </div>

                  {(() => {
                    const fixJson = extractFixJson(item)
                    const changes = (fixJson?.code_changes || []).filter(Boolean)

                    if (fixJson && changes.length > 0) {
                      return (
                        <div className="space-y-3">
                          <div className="rounded-lg border border-(--border) bg-(--panel-2) p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Summary</p>
                                <p className="mt-1 text-sm font-semibold text-(--text) wrap-break-word">
                                  {fixJson.problem || item.issue.message}
                                </p>
                                {fixJson.solution ? (
                                  <p className="mt-1 text-xs text-(--muted) whitespace-pre-wrap wrap-break-word">{fixJson.solution}</p>
                                ) : null}
                              </div>
                              <button
                                onClick={async (e) => {
                                  e.stopPropagation()
                                  await copyText(JSON.stringify(fixJson, null, 2))
                                }}
                                className="shrink-0 rounded-lg border border-(--border-soft) bg-(--surface-elevated) px-2.5 py-1 text-xs font-semibold text-(--text) hover:bg-(--surface-hover) transition"
                              >
                                Copy JSON
                              </button>
                            </div>
                          </div>

                          <div className="rounded-lg border border-(--border) bg-(--panel-2) p-3">
                            <div className="flex items-center justify-between gap-3">
                              <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Code changes</p>
                              <button
                                onClick={async (e) => {
                                  e.stopPropagation()
                                  await copyText(JSON.stringify(changes, null, 2))
                                }}
                                className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) px-2.5 py-1 text-xs font-semibold text-(--text) hover:bg-(--surface-hover) transition"
                              >
                                Copy changes
                              </button>
                            </div>

                            <div className="mt-3 space-y-2">
                              {changes.map((ch, idx) => {
                                if (ch.op === 'move') {
                                  return (
                                    <div key={idx} className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-3">
                                      <div className="flex items-center justify-between gap-3">
                                        <div className="min-w-0">
                                          <p className="text-xs font-semibold text-(--text)">
                                            <span className="font-mono">{ch.op}</span>
                                          </p>
                                          <p className="mt-1 text-xs text-(--muted) break-all font-mono">
                                            {ch.from} → {ch.to}
                                          </p>
                                          {ch.notes ? <p className="mt-1 text-xs text-(--muted)">{ch.notes}</p> : null}
                                        </div>
                                        <button
                                          onClick={async (e) => {
                                            e.stopPropagation()
                                            await copyText(`${ch.from} -> ${ch.to}`)
                                          }}
                                          className="shrink-0 rounded-md border border-(--border-soft) bg-(--panel-2) px-2 py-1 text-xs font-semibold text-(--text) hover:bg-(--surface-hover) transition"
                                        >
                                          Copy
                                        </button>
                                      </div>
                                    </div>
                                  )
                                }

                                const header = `${ch.op}${ch.file ? ` · ${ch.file}` : ''}${typeof ch.line === 'number' && ch.line > 0 ? `:${ch.line}` : ''}`

                                return (
                                  <div key={idx} className="rounded-lg border border-(--border-soft) bg-(--surface-elevated) p-3">
                                    <div className="flex items-center justify-between gap-3">
                                      <p className="text-xs font-semibold text-(--text) break-all">
                                        <span className="font-mono">{header}</span>
                                      </p>
                                      <button
                                        onClick={async (e) => {
                                          e.stopPropagation()
                                          await copyText(JSON.stringify(ch, null, 2))
                                        }}
                                        className="shrink-0 rounded-md border border-(--border-soft) bg-(--panel-2) px-2 py-1 text-xs font-semibold text-(--text) hover:bg-(--surface-hover) transition"
                                      >
                                        Copy
                                      </button>
                                    </div>

                                    {ch.notes ? <p className="mt-1 text-xs text-(--muted)">{ch.notes}</p> : null}

                                    {ch.file && typeof ch.line === 'number' && ch.line > 0 && (
                                      <details
                                        className="mt-2 rounded-lg border border-(--border) bg-(--panel-2) p-2"
                                        onToggle={async (e) => {
                                          e.stopPropagation()
                                          const open = (e.currentTarget as HTMLDetailsElement).open
                                          if (open) await getSnippet(ch.file!, ch.line || 1, 12)
                                        }}
                                      >
                                        <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-(--muted)">
                                          Preview (before / after)
                                        </summary>
                                        <div className="mt-2">
                                          {(() => {
                                            const cacheKey = `${ch.file}:${ch.line || 1}:12`
                                            const snip = snippetCache[cacheKey]
                                            if (!snip)
                                              return <p className="text-xs text-(--muted)">Loading preview…</p>
                                            if (!snip.ok) {
                                              return <p className="mt-2 text-xs text-red-600">{snip.error}</p>
                                            }

                                            const before = snip.lines
                                            const after = applyChangeToLines(before, ch)

                                            const modeKey = cacheKey
                                            const mode = previewMode[modeKey] || 'split'

                                            const render = (label: string, ls: SnippetLine[]) => (
                                              <div className="rounded border border-(--code-border) bg-(--code-bg) p-2">
                                                <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">{label}</p>
                                                <pre className="mt-1 max-h-56 overflow-auto text-xs text-(--text) font-mono whitespace-pre">
                                                  {ls
                                                    .map((l) => `${String(Math.round(l.line)).padStart(4, ' ')}  ${l.text}`)
                                                    .join('\n')}
                                                </pre>
                                              </div>
                                            )

                                            return (
                                              <div className="mt-2 space-y-2">
                                                <div className="flex items-center justify-between gap-2">
                                                  <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">
                                                    View
                                                  </p>
                                                  <div className="flex items-center gap-2">
                                                    <button
                                                      onClick={(e) => {
                                                        e.stopPropagation()
                                                        setPreviewMode((p) => ({ ...p, [modeKey]: 'split' }))
                                                      }}
                                                      className={`rounded-md border px-2 py-1 text-xs font-semibold transition ${
                                                        mode === 'split'
                                                          ? 'border-teal-400/30 bg-teal-400/10 text-(--accent-teal)'
                                                          : 'border-(--border-soft) bg-(--surface-elevated) text-(--text) hover:bg-(--surface-hover)'
                                                      }`}
                                                    >
                                                      Split
                                                    </button>
                                                    <button
                                                      onClick={(e) => {
                                                        e.stopPropagation()
                                                        setPreviewMode((p) => ({ ...p, [modeKey]: 'unified' }))
                                                      }}
                                                      className={`rounded-md border px-2 py-1 text-xs font-semibold transition ${
                                                        mode === 'unified'
                                                          ? 'border-teal-400/30 bg-teal-400/10 text-(--accent-teal)'
                                                          : 'border-(--border-soft) bg-(--surface-elevated) text-(--text) hover:bg-(--surface-hover)'
                                                      }`}
                                                    >
                                                      Unified
                                                    </button>
                                                  </div>
                                                </div>

                                                {mode === 'split' ? (
                                                  <div className="grid gap-2 md:grid-cols-2">
                                                    {render('Before', before)}
                                                    {render('After', after)}
                                                  </div>
                                                ) : (
                                                  <div className="rounded border border-(--code-border) bg-(--code-bg) p-2">
                                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Diff</p>
                                                    <pre className="mt-1 max-h-56 overflow-auto text-xs text-(--text) font-mono whitespace-pre">
                                                      {renderUnifiedDiff(before, after)}
                                                    </pre>
                                                  </div>
                                                )}
                                              </div>
                                            )
                                          })()}
                                        </div>
                                      </details>
                                    )}

                                    {(ch.old_code || ch.new_code) && (
                                      <div className="mt-2 grid gap-2 md:grid-cols-2">
                                        <div className="rounded border border-(--code-border) bg-(--code-bg) p-2">
                                          <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Old</p>
                                          <pre className="mt-1 overflow-auto text-xs text-(--text) font-mono whitespace-pre-wrap wrap-break-word">
                                            {ch.old_code || '—'}
                                          </pre>
                                        </div>
                                        <div className="rounded border border-(--code-border) bg-(--code-bg) p-2">
                                          <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">New</p>
                                          <pre className="mt-1 overflow-auto text-xs text-(--text) font-mono whitespace-pre-wrap wrap-break-word">
                                            {ch.new_code || '—'}
                                          </pre>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                )
                              })}
                            </div>
                          </div>

                          {(fixJson.explanation || fixJson.best_practice || fixJson.fixed_code) && (
                            <details className="rounded-lg border border-(--border) bg-(--panel-2) p-3">
                              <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-(--muted)">
                                Details
                              </summary>
                              <div className="mt-3 space-y-3">
                                {fixJson.explanation ? (
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Explanation</p>
                                    <p className="mt-1 text-xs text-(--text) whitespace-pre-wrap wrap-break-word">{fixJson.explanation}</p>
                                  </div>
                                ) : null}
                                {fixJson.best_practice ? (
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Best practice</p>
                                    <p className="mt-1 text-xs text-(--text) whitespace-pre-wrap wrap-break-word">{fixJson.best_practice}</p>
                                  </div>
                                ) : null}
                                {fixJson.fixed_code ? (
                                  <div>
                                    <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Fixed code</p>
                                    <pre className="mt-1 rounded border border-(--code-border) bg-(--code-bg) p-2 text-xs text-(--text) font-mono whitespace-pre-wrap wrap-break-word overflow-auto">
                                      {fixJson.fixed_code}
                                    </pre>
                                  </div>
                                ) : null}
                              </div>
                            </details>
                          )}
                        </div>
                      )
                    }

                    // Fallback: show raw fix text
                    return (
                      <>
                        <pre className="max-h-60 overflow-auto rounded bg-(--code-bg) p-3 text-xs text-(--text) font-mono border border-(--code-border) whitespace-pre-wrap wrap-break-word">
                          {normalizeFixText(item.fix)}
                        </pre>
                        <p className="mt-2 text-[11px] text-(--muted)">
                          Tip: paste this change into{' '}
                          <span className="font-mono text-(--text)">{getIssueFilePath(item.issue.file)}</span> near line{' '}
                          <span className="font-mono text-(--text)">{item.issue.line}</span>.
                        </p>
                      </>
                    )
                  })()}
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
