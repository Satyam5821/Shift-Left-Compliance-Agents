import { Fragment, useMemo } from 'react'
import { structuredPatch } from 'diff'
import type { StructuredPatchHunk } from 'diff'

function stripPatchLine(line: string): string {
  const body = line.length > 0 ? line.slice(1) : ''
  return body.endsWith('\n') ? body.slice(0, -1) : body
}

type UnifiedRow = {
  key: string
  mark: ' ' | '-' | '+'
  oldNo: number | null
  newNo: number | null
  text: string
}

type SplitRow = {
  key: string
  leftNo: number | null
  leftText: string
  leftKind: 'ctx' | 'del' | 'empty'
  rightNo: number | null
  rightText: string
  rightKind: 'ctx' | 'add' | 'empty'
}

function hunkToUnifiedRows(hunk: StructuredPatchHunk, hunkIdx: number): UnifiedRow[] {
  let oldCur = hunk.oldStart
  let newCur = hunk.newStart
  const rows: UnifiedRow[] = []
  hunk.lines.forEach((line, li) => {
    const mark = line[0] as ' ' | '-' | '+'
    const text = stripPatchLine(line)
    const key = `${hunkIdx}-${li}`
    if (mark === ' ') {
      rows.push({ key, mark: ' ', oldNo: oldCur, newNo: newCur, text })
      oldCur += 1
      newCur += 1
    } else if (mark === '-') {
      rows.push({ key, mark: '-', oldNo: oldCur, newNo: null, text })
      oldCur += 1
    } else if (mark === '+') {
      rows.push({ key, mark: '+', oldNo: null, newNo: newCur, text })
      newCur += 1
    }
  })
  return rows
}

function hunkToSplitRows(hunk: StructuredPatchHunk, hunkIdx: number): SplitRow[] {
  const rows: SplitRow[] = []
  let i = 0
  let o = hunk.oldStart
  let n = hunk.newStart
  const lines = hunk.lines
  let rowSeq = 0

  while (i < lines.length) {
    const line = lines[i]
    const c = line[0]
    if (c === ' ') {
      const text = stripPatchLine(line)
      rows.push({
        key: `${hunkIdx}-${rowSeq++}`,
        leftNo: o,
        leftText: text,
        leftKind: 'ctx',
        rightNo: n,
        rightText: text,
        rightKind: 'ctx',
      })
      o += 1
      n += 1
      i += 1
      continue
    }

    const dels: { line: number; text: string }[] = []
    while (i < lines.length && lines[i][0] === '-') {
      dels.push({ line: o, text: stripPatchLine(lines[i]) })
      o += 1
      i += 1
    }
    const adds: { line: number; text: string }[] = []
    while (i < lines.length && lines[i][0] === '+') {
      adds.push({ line: n, text: stripPatchLine(lines[i]) })
      n += 1
      i += 1
    }

    const max = Math.max(dels.length, adds.length)
    for (let k = 0; k < max; k++) {
      const d = dels[k]
      const a = adds[k]
      rows.push({
        key: `${hunkIdx}-${rowSeq++}`,
        leftNo: d ? d.line : null,
        leftText: d ? d.text : '',
        leftKind: d ? 'del' : 'empty',
        rightNo: a ? a.line : null,
        rightText: a ? a.text : '',
        rightKind: a ? 'add' : 'empty',
      })
    }
  }

  return rows
}

function unifiedRowBg(mark: ' ' | '-' | '+'): string {
  if (mark === '-') return 'bg-[#4a1c22]/95'
  if (mark === '+') return 'bg-[#0f3320]/95'
  return 'bg-transparent'
}

function splitCellBg(kind: 'ctx' | 'del' | 'add' | 'empty'): string {
  if (kind === 'empty') return 'bg-[#161b22]/50'
  if (kind === 'del') return 'bg-[#4a1c22]/90'
  if (kind === 'add') return 'bg-[#0f3320]/90'
  return 'bg-transparent'
}

function codeCellClass(mark: ' ' | '-' | '+'): string {
  if (mark === '-') return 'text-[#fde8ea]'
  if (mark === '+') return 'text-[#dafbe1]'
  return 'text-[#e6edf3]'
}

function splitCodeClass(kind: 'ctx' | 'del' | 'add' | 'empty'): string {
  if (kind === 'del') return 'text-[#fde8ea]'
  if (kind === 'add') return 'text-[#dafbe1]'
  if (kind === 'empty') return 'text-[#484f58]'
  return 'text-[#e6edf3]'
}

const srOnly = 'absolute m-[-1px] h-px w-px overflow-hidden border-0 p-0 whitespace-nowrap'

type Props = {
  filePath: string
  oldText: string
  newText: string
  mode: 'unified' | 'split'
  /** Tighter max-height for nested cards (e.g. Fix panel) */
  variant?: 'default' | 'compact'
  /** Accessible name for the diff region */
  ariaLabel?: string
  className?: string
}

export default function GitHubStyleDiff({
  filePath,
  oldText,
  newText,
  mode,
  variant = 'default',
  ariaLabel = 'Code diff',
  className = '',
}: Props) {
  const patch = useMemo(() => {
    const oldStr = oldText ?? ''
    const newStr = newText ?? ''
    if (oldStr === '' && newStr === '') return null
    try {
      return structuredPatch(`a/${filePath}`, `b/${filePath}`, oldStr, newStr, undefined, undefined, {
        context: Infinity,
      })
    } catch {
      return null
    }
  }, [filePath, oldText, newText])

  if (!patch || patch.hunks.length === 0) {
    return (
      <p className="px-3 py-2 text-xs text-(--muted)">Could not build a diff for this snippet.</p>
    )
  }

  const scrollMax =
    variant === 'compact' ? 'max-h-[min(40vh,260px)]' : 'max-h-[min(70vh,560px)]'

  return (
    <div
      role="region"
      aria-label={ariaLabel}
      className={`overflow-hidden rounded-md border border-[#30363d] text-[13px] leading-snug ${className}`}
    >
      <div className="flex items-center gap-2 border-b border-[#30363d] bg-[#161b22] px-3 py-2">
        <span className="text-[#8b949e]" aria-hidden>
          <svg className="inline h-4 w-4" viewBox="0 0 16 16" fill="currentColor">
            <path d="M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8z" />
          </svg>
        </span>
        <span className="font-mono text-sm font-semibold text-[#f0f3f6]">{filePath}</span>
      </div>

      {mode === 'unified' ? (
        <div className={`overflow-auto ${scrollMax}`}>
          <table className="w-full min-w-[520px] border-collapse font-mono">
            <caption className={srOnly}>Unified diff for {filePath}</caption>
            <tbody>
              {patch.hunks.map((hunk, hi) => (
                <Fragment key={`u-hunk-${hi}`}>
                  <tr className="bg-[#21262d]">
                    <th scope="colgroup" colSpan={4} className="sticky left-0 px-2 py-1.5 text-left text-[12px] font-normal text-[#e6bfff]">
                      @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
                    </th>
                  </tr>
                  {hunkToUnifiedRows(hunk, hi).map((r) => (
                    <tr key={r.key} className={unifiedRowBg(r.mark)}>
                      <td className="w-6 select-none px-1 text-center text-[#8b949e]" aria-hidden>
                        {r.mark === ' ' ? '' : r.mark}
                      </td>
                      <td className="w-10 select-none border-r border-[#30363d] px-2 text-right text-[#8b949e]">
                        {r.oldNo ?? ''}
                      </td>
                      <td className="w-10 select-none border-r border-[#30363d] px-2 text-right text-[#8b949e]">
                        {r.newNo ?? ''}
                      </td>
                      <td className={`whitespace-pre px-2 py-0.5 pr-4 ${codeCellClass(r.mark)}`}>{r.text || ' '}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={`overflow-auto ${scrollMax}`}>
          <table className="w-full min-w-[640px] border-collapse font-mono">
            <caption className={srOnly}>Split diff for {filePath}</caption>
            <tbody>
              {patch.hunks.map((hunk, hi) => (
                <Fragment key={`s-hunk-${hi}`}>
                  <tr className="bg-[#21262d]">
                    <th scope="colgroup" colSpan={4} className="sticky left-0 px-2 py-1.5 text-left text-[12px] font-normal text-[#e6bfff]">
                      @@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@
                    </th>
                  </tr>
                  {hunkToSplitRows(hunk, hi).map((r) => (
                    <tr key={r.key}>
                      <td
                        className={`w-10 select-none border-r border-[#30363d] px-2 py-0.5 text-right align-top text-[#8b949e] ${splitCellBg(r.leftKind)}`}
                      >
                        {r.leftNo ?? ''}
                      </td>
                      <td
                        className={`min-w-[45%] whitespace-pre border-r border-[#30363d] px-2 py-0.5 align-top ${splitCodeClass(r.leftKind)} ${splitCellBg(r.leftKind)}`}
                      >
                        {r.leftText}
                      </td>
                      <td
                        className={`w-10 select-none border-r border-[#30363d] px-2 py-0.5 text-right align-top text-[#8b949e] ${splitCellBg(r.rightKind)}`}
                      >
                        {r.rightNo ?? ''}
                      </td>
                      <td
                        className={`min-w-[45%] whitespace-pre px-2 py-0.5 align-top ${splitCodeClass(r.rightKind)} ${splitCellBg(r.rightKind)}`}
                      >
                        {r.rightText}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
