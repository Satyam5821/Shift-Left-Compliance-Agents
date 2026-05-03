import GitHubConnectPanel from './GitHubConnectPanel'
import { PATH_WORKSPACES } from '../routes'

type Mode = 'required' | 'manage'

type Props = {
  apiBase: string
  authToken: string
  mode: Mode
  onWorkspaceReady: () => void
  onBackToDashboard: () => void
  onSignOut: () => void
}

export default function WorkspaceGate({ apiBase, authToken, mode, onWorkspaceReady, onBackToDashboard, onSignOut }: Props) {
  return (
    <div className="relative min-h-screen overflow-x-hidden bg-(--app-bg)">
      <div
        className="pointer-events-none absolute inset-0 opacity-90"
        aria-hidden
        style={{
          background: `
            radial-gradient(ellipse 100% 80% at 50% -30%, rgba(139, 92, 246, 0.22), transparent 50%),
            radial-gradient(ellipse 70% 50% at 100% 50%, rgba(45, 212, 191, 0.08), transparent 45%),
            radial-gradient(ellipse 60% 40% at 0% 80%, rgba(139, 92, 246, 0.1), transparent 40%)
          `,
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.35] dark:opacity-[0.2]"
        aria-hidden
        style={{
          backgroundImage: `linear-gradient(rgba(139, 92, 246, 0.06) 1px, transparent 1px),
            linear-gradient(90deg, rgba(139, 92, 246, 0.06) 1px, transparent 1px)`,
          backgroundSize: '48px 48px',
        }}
      />

      <div className="relative z-10 mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-10 sm:px-6 sm:py-14 md:px-8">
        <header className="mb-8 flex flex-col gap-6 sm:mb-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <nav className="flex flex-wrap items-center gap-2 text-[11px] font-medium text-(--muted)">
              <span className="rounded-md bg-(--panel-2) px-2 py-1 font-mono text-[10px] text-violet-600 dark:text-violet-300">{PATH_WORKSPACES}</span>
              <span aria-hidden className="text-(--border)">
                /
              </span>
              <span className="text-(--text)">{mode === 'required' ? 'Setup' : 'Manage'}</span>
            </nav>
            <div className="flex flex-wrap items-center gap-2">
              {mode === 'manage' ? (
                <button
                  type="button"
                  onClick={onBackToDashboard}
                  className="inline-flex items-center justify-center rounded-xl border border-(--border-soft) bg-(--surface-elevated) px-4 py-2.5 text-xs font-semibold text-(--text) shadow-sm transition hover:border-violet-500/30 hover:bg-(--surface-hover)"
                >
                  ← Back to dashboard
                </button>
              ) : null}
              <button
                type="button"
                onClick={onSignOut}
                className="inline-flex items-center justify-center rounded-xl border border-(--border-soft) bg-transparent px-4 py-2.5 text-xs font-semibold text-(--muted) transition hover:border-rose-500/30 hover:bg-rose-500/10 hover:text-rose-200"
              >
                Sign out
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:gap-6">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-violet-500/25 bg-linear-to-br from-violet-500/20 to-teal-500/10 shadow-lg shadow-violet-500/10">
              <svg className="h-7 w-7 text-violet-600 dark:text-violet-300" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path
                  d="M4 5a2 2 0 0 1 2-2h5l7 7v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5Z"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinejoin="round"
                />
                <path d="M11 3v6h6" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-violet-600 dark:text-violet-300">Shift Left Compliance Agent</p>
              <h1 className="mt-2 text-balance text-2xl font-bold tracking-tight text-(--text) sm:text-3xl">
                {mode === 'required' ? 'Set up your workspace' : 'Manage workspaces'}
              </h1>
              <p className="mt-3 max-w-xl text-pretty text-sm leading-relaxed text-(--muted)">
                Choose a workspace, create a new one, or remove one you no longer need. Your dashboard stays scoped to the active workspace until you change it here.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <span
                  className={`inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-semibold ${
                    mode === 'required'
                      ? 'border-amber-500/30 bg-amber-500/10 text-amber-200'
                      : 'border-teal-500/25 bg-teal-500/10 text-teal-200'
                  }`}
                >
                  {mode === 'required' ? '● First-time setup' : '● Manage & switch'}
                </span>
                <span className="inline-flex items-center rounded-full border border-(--border-soft) bg-(--panel-2) px-3 py-1 text-[11px] font-medium text-(--muted)">
                  Bookmark this page · {PATH_WORKSPACES}
                </span>
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 rounded-3xl border border-(--border) bg-(--panel) p-1 shadow-2xl shadow-(color:--shadow) backdrop-blur-xl sm:p-1.5">
          <div className="rounded-[1.35rem] border border-(--border-soft) bg-(--panel-2) p-4 sm:p-6 md:p-8">
            <GitHubConnectPanel apiBase={apiBase} authToken={authToken} variant="gate" onWorkspaceActivated={onWorkspaceReady} />
          </div>
        </div>

        <p className="mt-8 text-center text-[11px] text-(--muted)">
          Tip: Use <strong className="text-(--text)">Manage workspaces</strong> in the sidebar anytime to return here.
        </p>
      </div>
    </div>
  )
}
