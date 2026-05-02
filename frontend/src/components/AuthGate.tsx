type Props = {
  apiBase: string
  title?: string
  subtitle?: string
}

export default function AuthGate({
  apiBase,
  title = 'Sign in to continue',
  subtitle = 'Connect your GitHub account to view scans, issues, and workspaces.',
}: Props) {
  const loginUrl = `${apiBase.replace(/\/+$/, '')}/auth/github/login`
  return (
    <div className="min-h-screen bg-(--app-bg) flex items-center justify-center p-6">
      <div className="w-full max-w-lg rounded-2xl border border-(--border) bg-(--panel) p-6 shadow-2xl shadow-(color:--shadow)">
        <p className="text-xs font-semibold uppercase tracking-widest text-violet-300">Shift Left Compliance Agent</p>
        <h1 className="mt-2 text-2xl font-bold text-(--text)">{title}</h1>
        <p className="mt-2 text-sm text-(--muted)">{subtitle}</p>

        <div className="mt-5 flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => window.open(loginUrl, '_blank', 'noopener,noreferrer')}
            className="inline-flex flex-1 items-center justify-center rounded-lg bg-violet-600 px-4 py-2.5 text-sm font-bold text-white transition hover:bg-violet-500 active:scale-95"
          >
            Sign in with GitHub
          </button>
          <button
            onClick={() => window.open(loginUrl, '_blank', 'noopener,noreferrer')}
            className="inline-flex flex-1 items-center justify-center rounded-lg border border-(--border-soft) bg-(--panel-2) px-4 py-2.5 text-sm font-semibold text-(--text) transition hover:opacity-95 active:scale-[0.99]"
          >
            Create account
          </button>
        </div>

        <div className="mt-5 rounded-lg border border-(--border-dashed) bg-(--surface-elevated) p-3 text-xs text-(--muted)">
          After signing in, return to this tab — you’ll be logged in automatically.
        </div>
      </div>
    </div>
  )
}

