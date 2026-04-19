import { useEffect, useMemo, useRef, useState } from 'react'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import type { ScanDoc, ScanFixAttempt, ScanIssue } from '../types'
import GitHubStyleDiff from './GitHubStyleDiff'
import { focusRing, PanelError } from './PanelStatus'

type ScanCodeChange = {
  op?: string
  file?: string
  line?: number
  old_code?: string
  new_code?: string
  notes?: string
  from?: string
  to?: string
}

function asScanCodeChange(raw: unknown): ScanCodeChange | null {
  if (!raw || typeof raw !== 'object') return null
  return raw as ScanCodeChange
}

/** Sonar line can be stored as number or numeric string; never concatenate with issue keys in the UI. */
function coerceDisplayLine(v: unknown): number | undefined {
  if (typeof v === 'number' && Number.isFinite(v) && v > 0) return Math.floor(v)
  if (typeof v === 'string') {
    const m = v.match(/^\s*(\d+)/)
    if (m) return parseInt(m[1], 10)
  }
  return undefined
}

function sortLineKey(v: unknown): number {
  return coerceDisplayLine(v) ?? 1_000_000
}

type Props = {
  scans: ScanDoc[]
  selectedScanId: string | null
  scan?: ScanDoc | null
  issues?: ScanIssue[]
  fixAttempts?: ScanFixAttempt[]
  loading: boolean
  error?: string | null
  onSelectScan: (scanId: string) => void
  onRefreshList: () => void
  onDownloadPdf: () => void
  apiBase: string
}

function formatTs(v?: string) {
  if (!v) return '–'
  const t = Date.parse(v)
  if (Number.isNaN(t)) return v
  return new Date(t).toLocaleString()
}

function counters(scan?: ScanDoc | null) {
  const c = scan?.apply_counters || {}
  return {
    applied: c.applied ?? 0,
    skipped: c.skipped ?? 0,
    errors: c.errors ?? 0,
  }
}

export default function ScansPanel({
  scans,
  selectedScanId,
  scan,
  issues,
  fixAttempts,
  loading,
  error,
  onSelectScan,
  onRefreshList,
  onDownloadPdf,
  apiBase,
}: Props) {
  const reportRef = useRef<HTMLDivElement | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [selectedDiffFile, setSelectedDiffFile] = useState<string | null>(null)
  const [diffViewMode, setDiffViewMode] = useState<'split' | 'unified'>('unified')

  const selectedCounters = counters(scan)

  useEffect(() => {
    setSelectedDiffFile(null)
  }, [scan?.scan_id])

  const suggestedActions = useMemo(() => {
    const actions: { title: string; detail: string }[] = []
    if (!scan) {
      actions.push({ title: 'Pick a scan', detail: 'Select a scan to view its report and export a PDF.' })
      return actions
    }

    if ((selectedCounters.errors || 0) > 0) {
      actions.push({ title: 'Investigate errors', detail: 'Open Render logs for this scan_id and review apply report.' })
    }
    if ((selectedCounters.skipped || 0) > 0) {
      actions.push({
        title: 'Review skipped edits',
        detail: 'Skipped usually means anchors didn’t match. Consider refresh mode or improving prompt anchors.',
      })
    }
    if ((selectedCounters.applied || 0) > 0 && scan.pr) {
      actions.push({ title: 'Review & merge PR', detail: 'Open the PR, review diffs, then merge if checks pass.' })
    }
    if ((selectedCounters.applied || 0) === 0 && !scan.pr) {
      actions.push({
        title: 'No changes applied',
        detail: 'If Sonar still shows issues, rerun scan or switch to refresh mode to regenerate fixes.',
      })
    }
    actions.push({ title: 'Export PDF', detail: 'Download a PDF report for sharing/auditing.' })
    return actions
  }, [scan, selectedCounters.applied, selectedCounters.errors, selectedCounters.skipped])

  const fileChanges = useMemo(() => {
    const byFile: Record<string, number> = {}
    for (const fa of fixAttempts || []) {
      const cc = fa.fix_json?.code_changes
      if (!Array.isArray(cc)) continue
      for (const ch of cc) {
        const file = (ch as any)?.file
        if (typeof file === 'string' && file) byFile[file] = (byFile[file] || 0) + 1
      }
    }
    const items = Object.entries(byFile)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 15)
    return items
  }, [fixAttempts])

  const changesByFile = useMemo(() => {
    const map: Record<string, { issue_key?: string; change: ScanCodeChange }[]> = {}
    for (const fa of fixAttempts || []) {
      const cc = fa.fix_json?.code_changes
      if (!Array.isArray(cc)) continue
      for (const raw of cc) {
        const ch = asScanCodeChange(raw)
        if (!ch) continue
        const op = ch.op || (ch.from && ch.to ? 'move' : 'replace')
        if (op === 'move') {
          const from = typeof ch.from === 'string' ? ch.from : ''
          const to = typeof ch.to === 'string' ? ch.to : ''
          if (from) {
            if (!map[from]) map[from] = []
            map[from].push({ issue_key: fa.issue_key, change: { ...ch, op: 'move' } })
          }
          if (to && to !== from) {
            if (!map[to]) map[to] = []
            map[to].push({ issue_key: fa.issue_key, change: { ...ch, op: 'move' } })
          }
          continue
        }
        const file = typeof ch.file === 'string' ? ch.file : ''
        if (!file) continue
        if (!map[file]) map[file] = []
        map[file].push({ issue_key: fa.issue_key, change: ch })
      }
    }
    return map
  }, [fixAttempts])

  const selectedFileChanges = selectedDiffFile ? changesByFile[selectedDiffFile] || [] : []

  const sortedFileChanges = useMemo(() => {
    const list = [...selectedFileChanges]
    list.sort((a, b) => {
      const da = sortLineKey(a.change.line)
      const db = sortLineKey(b.change.line)
      if (da !== db) return da - db
      return String(a.change.op || '').localeCompare(String(b.change.op || ''))
    })
    return list
  }, [selectedFileChanges])

  const downloadPdf = async () => {
    if (!scan) return
    const el = reportRef.current
    if (!el) return
    setDownloading(true)
    try {
      // 先把报告节点强制渲染为接近 A4 正向打印宽度的窄版式，让文字更自然换行、
      // 排版更接近一份标准文档，避免原来"超宽却很矮"的窄条式 PDF。
      // 800px ≈ A4 去除合理边距后的视觉宽度，看起来接近标准报告。
      const CAPTURE_WIDTH = 800
      const h = Math.max(el.scrollHeight, el.offsetHeight, el.clientHeight)

      const canvas = await html2canvas(el, {
        scale: 2,
        backgroundColor: '#0b0b10',
        useCORS: true,
        logging: false,
        width: CAPTURE_WIDTH,
        windowWidth: CAPTURE_WIDTH,
        windowHeight: h,
        onclone: (doc) => {
          const node = doc.querySelector('[data-pdf-root="1"]')
          if (node instanceof HTMLElement) {
            // 在克隆文档中把报告节点宽度钉死为 CAPTURE_WIDTH，
            // 让文字按窄版式换行、内容自然增高，从而获得接近竖版 A4 的捕获结果。
            node.style.width = `${CAPTURE_WIDTH}px`
            node.style.maxWidth = `${CAPTURE_WIDTH}px`
            node.style.minWidth = `${CAPTURE_WIDTH}px`
            node.style.boxSizing = 'border-box'
            node.style.overflow = 'visible'
            node.style.maxHeight = 'none'
            node.style.height = 'auto'
          }
        },
      })

      const imgData = canvas.toDataURL('image/png')

      // 输出到标准 A4 纵向页面，并用报告主题色填充整页，避免出现白底"半幅"观感
      const pdf = new jsPDF('p', 'pt', 'a4')
      const pageWidth = pdf.internal.pageSize.getWidth()
      const pageHeight = pdf.internal.pageSize.getHeight()
      const margin = 24
      const imgWidth = pageWidth - margin * 2
      const imgHeight = (canvas.height * imgWidth) / canvas.width

      const BG: [number, number, number] = [11, 11, 16] // #0b0b10
      const paintPageBg = () => {
        pdf.setFillColor(BG[0], BG[1], BG[2])
        pdf.rect(0, 0, pageWidth, pageHeight, 'F')
      }

      // 调试信息：便于核对捕获与最终页面尺寸
      // eslint-disable-next-line no-console
      console.log('[PDF debug]', {
        captureWidth: CAPTURE_WIDTH,
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
        pageWidth,
        pageHeight,
        imgWidth,
        imgHeight,
      })

      // 跨页分片绘制：内容比单页还高时自动翻页，每页都先铺深色底再贴图
      const pageInnerH = pageHeight - margin * 2
      let y = margin
      paintPageBg()
      pdf.addImage(imgData, 'PNG', margin, y, imgWidth, imgHeight)
      let heightLeft = imgHeight - pageInnerH

      while (heightLeft > 0) {
        y = margin - (imgHeight - heightLeft)
        pdf.addPage()
        paintPageBg()
        pdf.addImage(imgData, 'PNG', margin, y, imgWidth, imgHeight)
        heightLeft -= pageInnerH
      }

      pdf.save(`shiftleft-scan-${scan.scan_id.replace(/[^\w.-]+/g, '_')}.pdf`)
      onDownloadPdf()
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
      <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Scan Reports</p>
            <p className="mt-1 text-xs text-(--muted)">Backend: {apiBase}</p>
          </div>
          <button
            type="button"
            onClick={onRefreshList}
            disabled={loading}
            aria-busy={loading}
            className={`inline-flex items-center justify-center rounded-lg border border-(--border) bg-(--surface-elevated) px-3 py-2 text-xs font-semibold text-(--text) transition hover:bg-(--surface-hover) disabled:opacity-60 ${focusRing}`}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {error ? <PanelError className="mt-3" title="Could not load scans" message={error} /> : null}

        <div className="mt-4 space-y-2 max-h-[520px] overflow-auto pr-1">
          {scans.length === 0 && (
            <div className="rounded-lg border border-(--border-dashed) bg-(--surface-elevated) p-4 text-xs text-(--muted)">
              No scans yet. Trigger a webhook run (Sonar workflow_run) and refresh.
            </div>
          )}

          {scans.map((s) => {
            const c = counters(s)
            const active = selectedScanId === s.scan_id
            return (
              <button
                type="button"
                key={s.scan_id}
                onClick={() => onSelectScan(s.scan_id)}
                aria-pressed={active}
                aria-label={`Scan report ${s.scan_id}`}
                className={`w-full rounded-lg border p-3 text-left transition ${focusRing} ${
                  active
                    ? 'border-violet-400/60 bg-violet-500/10'
                    : 'border-(--border) bg-(--surface-elevated) hover:bg-(--surface-hover)'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-xs font-mono text-(--text) truncate">{s.scan_id}</p>
                    <p className="mt-1 text-[11px] text-(--muted) truncate">{s.repo || '–'}</p>
                  </div>
                  <div className="shrink-0 text-right text-[11px] text-(--muted)">
                    <div>
                      <span className="text-(--accent-teal) font-semibold">{c.applied}</span> applied
                    </div>
                    <div>
                      <span className="text-amber-500 font-semibold">{c.skipped}</span> skipped •{' '}
                      <span className="text-rose-400 font-semibold">{c.errors}</span> errors
                    </div>
                  </div>
                </div>
                <div className="mt-2 text-[11px] text-(--muted)">
                  <span>Created: </span>
                  <span className="font-mono">{formatTs(s.created_at)}</span>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
        {!scan ? (
          <div className="rounded-lg border border-(--border-dashed) bg-(--surface-elevated) p-6 text-sm text-(--muted)">
            Select a scan from the left to view the report.
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Scan detail</p>
                <h3 className="mt-1 font-mono text-sm text-(--text) break-all">{scan.scan_id}</h3>
                <p className="mt-1 text-xs text-(--muted)">
                  Repo: <span className="text-(--text)">{scan.repo || '–'}</span> • Base:{' '}
                  <span className="text-(--text)">{scan.base_branch || 'main'}</span>
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {scan.pr && (
                  <a
                    href={scan.pr}
                    target="_blank"
                    rel="noreferrer"
                    className={`inline-flex items-center justify-center rounded-lg border border-(--border) bg-(--surface-elevated) px-3 py-2 text-xs font-semibold text-(--text) transition hover:bg-(--surface-hover) ${focusRing}`}
                  >
                    Open PR
                  </a>
                )}
                <button
                  type="button"
                  onClick={downloadPdf}
                  disabled={downloading}
                  aria-busy={downloading}
                  className={`inline-flex items-center justify-center rounded-lg px-3 py-2 text-xs font-bold text-white transition ${focusRing} ${
                    downloading ? 'bg-violet-600/50 cursor-not-allowed' : 'bg-violet-600 hover:bg-violet-500'
                  }`}
                >
                  {downloading ? 'Generating PDF…' : 'Download PDF'}
                </button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
                <p className="text-[11px] uppercase tracking-wider text-(--muted)">Applied</p>
                <p className="mt-1 text-2xl font-bold text-(--accent-teal)">{selectedCounters.applied}</p>
              </div>
              <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
                <p className="text-[11px] uppercase tracking-wider text-(--muted)">Skipped</p>
                <p className="mt-1 text-2xl font-bold text-amber-500">{selectedCounters.skipped}</p>
              </div>
              <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
                <p className="text-[11px] uppercase tracking-wider text-(--muted)">Errors</p>
                <p className="mt-1 text-2xl font-bold text-rose-400">{selectedCounters.errors}</p>
              </div>
            </div>

            <div className="mt-4 rounded-lg border border-(--border) bg-(--surface-elevated) p-4">
              <p className="text-sm font-semibold text-(--text)">Suggested next actions</p>
              <ul className="mt-3 space-y-2 text-xs text-(--muted)">
                {suggestedActions.map((a, idx) => (
                  <li key={idx} className="rounded-md border border-(--border) bg-(--panel-2) p-2">
                    <p className="font-semibold text-(--text)">{a.title}</p>
                    <p className="mt-0.5">{a.detail}</p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-4">
                <p className="text-sm font-semibold text-(--text)">Issues</p>
                <p className="mt-1 text-xs text-(--muted)">{(issues || []).length} issue(s)</p>
                <div className="mt-3 space-y-2 max-h-[260px] overflow-auto pr-1">
                  {(issues || []).map((i) => (
                    <div key={`${i.scan_id}-${i.issue_key}`} className="rounded-md border border-(--border) bg-(--panel-2) p-2">
                      <p className="text-xs font-mono text-(--text)">{i.issue_key || 'issue'}</p>
                      <p className="mt-1 text-xs text-(--muted)">{i.message}</p>
                      <p className="mt-1 text-[11px] text-(--muted)">
                        {i.rule} • {i.severity} • {i.file}:{i.line}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-4">
                <p className="text-sm font-semibold text-(--text)">Commit-wise (by file)</p>
                <p className="mt-1 text-xs text-(--muted)">
                  From <span className="font-mono">fix_json.code_changes</span>, grouped by file (top 15). Click a row for
                  before / after.
                </p>
                <div className="mt-3 space-y-2">
                  {fileChanges.length === 0 && (
                    <div className="rounded-md border border-(--border) bg-(--panel-2) p-3 text-xs text-(--muted)">
                      No code change metadata available for this scan.
                    </div>
                  )}
                  {fileChanges.map(([f, n]) => {
                    const active = selectedDiffFile === f
                    return (
                      <button
                        key={f}
                        type="button"
                        onClick={() => {
                          setSelectedDiffFile((cur) => (cur === f ? null : f))
                          setDiffViewMode('unified')
                        }}
                        aria-pressed={active}
                        aria-label={`Show diff for ${f}`}
                        className={`flex w-full cursor-pointer items-center justify-between rounded-md border px-3 py-2 text-left transition ${focusRing} ${
                          active
                            ? 'border-violet-400/50 bg-violet-500/10'
                            : 'border-(--border) bg-(--panel-2) hover:bg-(--surface-hover)'
                        }`}
                      >
                        <span className="text-xs font-mono text-(--text) truncate pr-2">{f}</span>
                        <span className="shrink-0 text-xs font-semibold text-violet-400">{n}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            </div>

            {selectedDiffFile && (
              <div className="mt-4 rounded-lg border border-violet-500/25 bg-(--surface-elevated) p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">File diff</p>
                    <p className="mt-1 break-all font-mono text-sm text-(--text)">{selectedDiffFile}</p>
                    <p className="mt-1 text-xs text-(--muted)">
                      {selectedFileChanges.length} patch block{selectedFileChanges.length === 1 ? '' : 's'} from stored fix
                      attempts (GitHub-style view).
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">View</span>
                    <button
                      type="button"
                      onClick={() => setDiffViewMode('unified')}
                      aria-pressed={diffViewMode === 'unified'}
                      aria-label="Unified diff view"
                      className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition ${focusRing} ${
                        diffViewMode === 'unified'
                          ? 'border-teal-400/30 bg-teal-400/10 text-(--accent-teal)'
                          : 'border-(--border) bg-(--panel-2) text-(--text) hover:bg-(--surface-hover)'
                      }`}
                    >
                      Unified
                    </button>
                    <button
                      type="button"
                      onClick={() => setDiffViewMode('split')}
                      aria-pressed={diffViewMode === 'split'}
                      aria-label="Split diff view"
                      className={`rounded-md border px-2.5 py-1 text-xs font-semibold transition ${focusRing} ${
                        diffViewMode === 'split'
                          ? 'border-teal-400/30 bg-teal-400/10 text-(--accent-teal)'
                          : 'border-(--border) bg-(--panel-2) text-(--text) hover:bg-(--surface-hover)'
                      }`}
                    >
                      Split
                    </button>
                    <button
                      type="button"
                      onClick={() => setSelectedDiffFile(null)}
                      aria-label="Close file diff"
                      className={`rounded-md border border-(--border) bg-(--panel-2) px-2.5 py-1 text-xs font-semibold text-(--text) hover:bg-(--surface-hover) ${focusRing}`}
                    >
                      Close
                    </button>
                  </div>
                </div>

                {selectedFileChanges.length === 0 ? (
                  <p className="mt-4 text-xs text-(--muted)">No change blocks found for this path.</p>
                ) : (
                  <div className="mt-4 space-y-5">
                    {sortedFileChanges.map((entry, idx) => {
                      const ch = entry.change
                      const op = ch.op || 'replace'
                      if (op === 'move') {
                        return (
                          <div key={idx} className="rounded-lg border border-(--border) bg-(--panel-2) p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="rounded border border-(--border) bg-(--surface-elevated) px-2 py-0.5 font-mono text-xs text-(--text)">
                                move
                              </span>
                              {entry.issue_key ? (
                                <span className="rounded border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 font-mono text-[11px] text-violet-200">
                                  {entry.issue_key}
                                </span>
                              ) : null}
                            </div>
                            <p className="mt-2 break-all font-mono text-xs text-(--muted)">
                              <span className="text-rose-300/90">{ch.from || '—'}</span>
                              <span className="text-(--muted)"> → </span>
                              <span className="text-teal-300/90">{ch.to || '—'}</span>
                            </p>
                            {ch.notes ? <p className="mt-2 text-xs text-(--muted)">{ch.notes}</p> : null}
                          </div>
                        )
                      }

                      const oldStr = ch.old_code ?? ''
                      const newStr = ch.new_code ?? ''
                      const hasOld = oldStr.length > 0
                      const hasNew = newStr.length > 0
                      const lineNum = coerceDisplayLine(ch.line)

                      return (
                        <div key={idx} className="space-y-2">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                            <span className="rounded border border-(--border) bg-(--panel-2) px-2 py-0.5 font-mono text-xs text-(--text)">
                              {op}
                            </span>
                            {lineNum != null ? (
                              <span className="text-xs text-(--muted)">
                                Line <span className="font-mono text-(--text)">{lineNum}</span>
                              </span>
                            ) : null}
                            {entry.issue_key ? (
                              <span className="rounded border border-violet-500/20 bg-violet-500/10 px-2 py-0.5 font-mono text-[11px] text-violet-200">
                                {entry.issue_key}
                              </span>
                            ) : null}
                          </div>
                          {ch.notes ? <p className="text-xs text-(--muted)">{ch.notes}</p> : null}

                          {!hasOld && !hasNew ? (
                            <p className="text-xs text-(--muted)">No old/new snippet in metadata for this block.</p>
                          ) : (
                            <GitHubStyleDiff
                              filePath={selectedDiffFile}
                              oldText={oldStr}
                              newText={newStr}
                              mode={diffViewMode}
                              ariaLabel={`Patch ${op} for ${selectedDiffFile}`}
                            />
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Hidden/printable region */}
            <div className="mt-4">
              <div
                ref={reportRef}
                data-pdf-root="1"
                className="rounded-lg border border-(--border) bg-(--panel) p-5 overflow-visible"
              >
                <h2 className="text-lg font-bold text-(--text)">Shift-Left Scan Report</h2>
                <p className="mt-1 text-xs text-(--muted)">scan_id: {scan.scan_id}</p>
                <p className="mt-1 text-xs text-(--muted)">repo: {scan.repo || '–'}</p>
                <p className="mt-1 text-xs text-(--muted)">
                  applied: {selectedCounters.applied} • skipped: {selectedCounters.skipped} • errors: {selectedCounters.errors}
                </p>
                {scan.pr && (
                  <p className="mt-2 text-xs text-(--muted)">
                    PR: <span className="font-mono">{scan.pr}</span>
                  </p>
                )}

                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-(--text)">Issues</h3>
                  <div className="mt-2 space-y-2">
                    {(issues || []).slice(0, 50).map((i) => (
                      <div key={`${i.scan_id}-${i.issue_key}`} className="rounded border border-(--border) bg-(--panel-2) p-2">
                        <p className="text-xs font-semibold text-(--text)">{i.issue_key}</p>
                        <p className="mt-0.5 text-xs text-(--muted)">{i.message}</p>
                        <p className="mt-0.5 text-[11px] text-(--muted)">
                          {i.rule} • {i.severity} • {i.file}:{i.line}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-(--text)">Top files changed (from fix metadata)</h3>
                  <div className="mt-2 space-y-1">
                    {fileChanges.map(([f, n]) => (
                      <div key={f} className="flex items-center justify-between rounded border border-(--border) bg-(--panel-2) px-2 py-1">
                        <span className="text-[11px] font-mono text-(--text) truncate">{f}</span>
                        <span className="text-[11px] text-(--muted)">{n}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

