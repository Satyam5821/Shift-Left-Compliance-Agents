/** Shared focus style for interactive controls across panels */
export const focusRing =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/90 focus-visible:ring-offset-2 focus-visible:ring-offset-(--panel-2)'

export const focusRingSummary =
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400/80 focus-visible:ring-offset-2 focus-visible:ring-offset-(--panel-2) rounded-sm'

type PanelLoadingProps = {
  message?: string
  className?: string
  dense?: boolean
}

export function PanelLoading({ message = 'Loading…', className = '', dense = false }: PanelLoadingProps) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className={`rounded-lg border border-(--border-dashed) bg-(--surface-elevated) text-sm text-(--muted) ${dense ? 'p-2' : 'p-4'} ${className}`}
    >
      <div className="flex items-center gap-3">
        <div
          className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-(--border) border-t-violet-400"
          aria-hidden
        />
        <p>{message}</p>
      </div>
    </div>
  )
}

type PanelErrorProps = {
  message: string
  title?: string
  className?: string
  onRetry?: () => void
  retryLabel?: string
}

export function PanelError({
  message,
  title = 'Something went wrong',
  className = '',
  onRetry,
  retryLabel = 'Retry',
}: PanelErrorProps) {
  return (
    <div role="alert" className={`rounded-lg border border-rose-900/40 bg-rose-950/50 p-3 text-xs text-rose-100 ${className}`}>
      <p className="font-semibold text-rose-50">{title}</p>
      <p className="mt-1 text-rose-100/90">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className={`mt-2 rounded-md border border-rose-400/35 bg-rose-900/45 px-2.5 py-1 text-xs font-semibold text-rose-50 transition hover:bg-rose-900/65 ${focusRing}`}
        >
          {retryLabel}
        </button>
      ) : null}
    </div>
  )
}
