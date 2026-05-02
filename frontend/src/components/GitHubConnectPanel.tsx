import { useEffect, useMemo, useState } from 'react'

type InstallDoc = {
  installation_id: number
  account_login?: string
  account_type?: string
  repositories?: string[]
  updated_at?: string
  active?: boolean
}

type InstallationsResponse =
  | { ok: true; count: number; installations: InstallDoc[] }
  | { ok: false; error: string }

const LS_INSTALLATION_ID = 'slca.github.installationId'
const LS_REPO_FULL_NAME = 'slca.github.repoFullName'

function normalizeBase(apiBase: string) {
  return (apiBase || '').replace(/\/+$/, '')
}

export default function GitHubConnectPanel({ apiBase }: { apiBase: string }) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [items, setItems] = useState<InstallDoc[]>([])

  const [installationId, setInstallationId] = useState<number | ''>(() => {
    try {
      const v = window.localStorage.getItem(LS_INSTALLATION_ID)
      const n = v ? parseInt(v, 10) : NaN
      return Number.isFinite(n) && n > 0 ? n : ''
    } catch {
      return ''
    }
  })
  const [repoFullName, setRepoFullName] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LS_REPO_FULL_NAME) || ''
    } catch {
      return ''
    }
  })

  const api = useMemo(() => normalizeBase(apiBase), [apiBase])
  const installUrl = `${api}/github/install`

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${api}/github/installations?limit=100`)
      const data = (await r.json()) as InstallationsResponse
      if (!data || (data as any).ok !== true) {
        setItems([])
        setError((data as any)?.error || 'Unable to load GitHub installations')
        return
      }
      const next = Array.isArray(data.installations) ? data.installations : []
      setItems(next)
      if (installationId === '' && next.length === 1 && next[0]?.installation_id) {
        setInstallationId(next[0].installation_id)
      }
    } catch (e) {
      setItems([])
      setError('Unable to load GitHub installations (backend offline?)')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api])

  useEffect(() => {
    try {
      if (installationId === '') window.localStorage.removeItem(LS_INSTALLATION_ID)
      else window.localStorage.setItem(LS_INSTALLATION_ID, String(installationId))
    } catch {
      // ignore
    }
  }, [installationId])

  useEffect(() => {
    try {
      if (!repoFullName) window.localStorage.removeItem(LS_REPO_FULL_NAME)
      else window.localStorage.setItem(LS_REPO_FULL_NAME, repoFullName)
    } catch {
      // ignore
    }
  }, [repoFullName])

  const selectedInstall = items.find((x) => x.installation_id === installationId) || null
  const repos = selectedInstall?.repositories || []

  return (
    <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">GitHub connections</p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="rounded-md border border-(--border) bg-(--surface-elevated) px-2 py-1 text-[11px] font-semibold text-(--text) transition hover:bg-(--surface-hover) disabled:opacity-60"
          >
            {loading ? 'Loading…' : 'Refresh'}
          </button>
          <button
            type="button"
            onClick={() => window.open(installUrl, '_blank', 'noopener,noreferrer')}
            className="rounded-md border border-violet-500/25 bg-violet-500/10 px-2 py-1 text-[11px] font-semibold text-violet-200 transition hover:bg-violet-500/15"
          >
            Connect
          </button>
        </div>
      </div>

      <p className="mt-2 text-[11px] text-(--muted)">
        Install the GitHub App, then select an installation + repo here (saved locally in your browser).
      </p>

      {error && (
        <div className="mt-3 rounded-md border border-rose-500/20 bg-rose-500/10 p-2 text-[11px] text-rose-100">
          {error}
        </div>
      )}

      <div className="mt-3 grid gap-2">
        <label className="grid gap-1">
          <span className="text-[11px] font-semibold text-(--muted)">Installation</span>
          <select
            value={installationId}
            onChange={(e) => {
              const v = e.target.value
              const n = v ? parseInt(v, 10) : NaN
              setInstallationId(Number.isFinite(n) && n > 0 ? n : '')
              setRepoFullName('')
            }}
            className="w-full rounded-md border border-(--border) bg-(--surface-elevated) px-2 py-2 text-xs text-(--text)"
          >
            <option value="">Select…</option>
            {items.map((it) => (
              <option key={it.installation_id} value={it.installation_id}>
                {it.account_login || 'account'} ({it.installation_id})
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-1">
          <span className="text-[11px] font-semibold text-(--muted)">Repo</span>
          <select
            value={repoFullName}
            onChange={(e) => setRepoFullName(e.target.value)}
            disabled={!installationId || repos.length === 0}
            className="w-full rounded-md border border-(--border) bg-(--surface-elevated) px-2 py-2 text-xs text-(--text) disabled:opacity-60"
          >
            <option value="">{installationId ? (repos.length ? 'Select…' : 'No repos tracked yet') : 'Select installation first'}</option>
            {repos.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <div className="mt-1 text-[11px] text-(--muted)">
          <span className="font-semibold text-(--text)">Selected:</span>{' '}
          {installationId ? `installation ${installationId}` : '—'}
          {repoFullName ? ` • ${repoFullName}` : ''}
        </div>
      </div>
    </div>
  )
}

