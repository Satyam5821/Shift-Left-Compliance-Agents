import { useEffect, useMemo, useState } from 'react'
import { notifyWorkspaceContextChanged } from '../workspaceContext'

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
const LS_ACTIVE_REPO_FULL_NAME = 'slca.activeRepoFullName'
const LS_WORKSPACES = 'slca.workspaces'
const LS_ACTIVE_WORKSPACE_ID = 'slca.activeWorkspaceId'
const LS_CLIENT_ID = 'slca.clientId'
const LS_PENDING_WORKSPACE_NAV = 'slca.pendingWorkspaceNav'

export type Workspace = {
  id: string
  name: string
  installationId: number
  /** Primary repo (first in repos[]) — kept for backward compatibility */
  repoFullName: string
  repos: string[]
  createdAt: number
}

function normalizeBase(apiBase: string) {
  return (apiBase || '').replace(/\/+$/, '')
}

function uniqRepos(list: string[]) {
  const out: string[] = []
  const seen = new Set<string>()
  for (const r of list) {
    const s = (r || '').trim()
    if (!s || !s.includes('/')) continue
    if (seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

function normalizeWorkspaceFromServer(w: any): Workspace | null {
  if (!w || typeof w !== 'object' || typeof w.id !== 'string') return null
  const installationId = Number(w.installationId || 0)
  if (!Number.isFinite(installationId) || installationId <= 0) return null

  let repos: string[] = []
  if (Array.isArray(w.repos)) {
    repos = uniqRepos(w.repos.map((x: any) => String(x || '')))
  }
  const primary = String(w.repoFullName || '').trim()
  if (primary && primary.includes('/') && !repos.includes(primary)) repos.unshift(primary)
  repos = uniqRepos(repos)
  if (!repos.length) return null

  const createdAt = Number(w.createdAt || w.created_at || Date.now())

  return {
    id: String(w.id),
    name: String(w.name || 'Workspace'),
    installationId,
    repoFullName: repos[0],
    repos,
    createdAt: Number.isFinite(createdAt) ? createdAt : Date.now(),
  }
}

function normalizeWorkspaceFromLocal(w: any): Workspace | null {
  const base = normalizeWorkspaceFromServer(w)
  if (!base) return null
  // legacy: only repoFullName
  if (!Array.isArray((w as any).repos) && typeof (w as any).repoFullName === 'string') {
    const r = String((w as any).repoFullName || '').trim()
    if (r) return { ...base, repos: uniqRepos([r]), repoFullName: r }
  }
  return base
}

export default function GitHubConnectPanel({
  apiBase,
  authToken,
  variant = 'default',
  onWorkspaceActivated,
}: {
  apiBase: string
  authToken: string
  /** Full-screen gate: always show GitHub setup, hide collapse toggle */
  variant?: 'default' | 'gate'
  /** Called after user selects a workspace or creates one (gate closes) */
  onWorkspaceActivated?: () => void
}) {
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

  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    try {
      const raw = window.localStorage.getItem(LS_WORKSPACES)
      const parsed = raw ? (JSON.parse(raw) as unknown) : []
      if (!Array.isArray(parsed)) return []
      return parsed.map(normalizeWorkspaceFromLocal).filter(Boolean) as Workspace[]
    } catch {
      return []
    }
  })

  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LS_ACTIVE_WORKSPACE_ID) || ''
    } catch {
      return ''
    }
  })

  const [activeRepoForScans, setActiveRepoForScans] = useState<string>(() => {
    try {
      return window.localStorage.getItem(LS_ACTIVE_REPO_FULL_NAME) || ''
    } catch {
      return ''
    }
  })

  

  const [newWorkspaceName, setNewWorkspaceName] = useState('')
  /** Full GitHub install + repo + create form — hidden until user opens it */
  const [setupExpanded, setSetupExpanded] = useState(false)

  const api = useMemo(() => normalizeBase(apiBase), [apiBase])
  const installUrl = `${api}/github/install`
  const apiKey = (import.meta.env.VITE_SHIFTLEFT_API_KEY as string | undefined) || ''

  const [clientId] = useState(() => {
    try {
      const existing = window.localStorage.getItem(LS_CLIENT_ID)
      if (existing && existing.trim()) return existing.trim()
      const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
      window.localStorage.setItem(LS_CLIENT_ID, id)
      return id
    } catch {
      return `${Date.now()}-${Math.random().toString(16).slice(2)}`
    }
  })

  const persistRemote = (ws: Workspace) => {
    const body = {
      id: ws.id,
      name: ws.name,
      installationId: ws.installationId,
      repoFullName: ws.repoFullName,
      repos: ws.repos,
      createdAt: ws.createdAt,
    }
    if (authToken) {
      fetch(`${api}/workspaces`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
        body: JSON.stringify(body),
      }).catch(() => {})
    } else if (apiKey) {
      fetch(`${api}/workspaces`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey,
          'X-Client-Id': clientId,
        },
        body: JSON.stringify(body),
      }).catch(() => {})
    }
  }

  const deleteRemote = (id: string) => {
    if (authToken) {
      fetch(`${api}/workspaces/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${authToken}` },
      }).catch(() => {})
    } else if (apiKey) {
      fetch(`${api}/workspaces/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        headers: { 'X-API-Key': apiKey, 'X-Client-Id': clientId },
      }).catch(() => {})
    }
  }

  const applyScanRepo = (repo: string) => {
    const r = (repo || '').trim()
    if (!r) {
      try {
        window.localStorage.removeItem(LS_ACTIVE_REPO_FULL_NAME)
      } catch {}
      setActiveRepoForScans('')
      notifyWorkspaceContextChanged()
      return
    }
    try {
      window.localStorage.setItem(LS_ACTIVE_REPO_FULL_NAME, r)
      window.localStorage.setItem(LS_REPO_FULL_NAME, r)
    } catch {}
    setActiveRepoForScans(r)
    setRepoFullName(r)
    notifyWorkspaceContextChanged()
  }

  const refresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${api}/github/installations?limit=100`)
      const raw = (await r.json()) as unknown
      const data = raw as InstallationsResponse
      if (!data || data.ok !== true) {
        setItems([])
        setError(data && data.ok === false ? data.error : 'Unable to load GitHub installations')
        return
      }
      const next = Array.isArray(data.installations) ? data.installations : []
      setItems(next)
      if (installationId === '' && next.length === 1 && next[0]?.installation_id) {
        setInstallationId(next[0].installation_id)
      }
    } catch {
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

  // Load persisted workspaces from backend when possible
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const headers: Record<string, string> = {}
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`
      else if (apiKey) {
        headers['X-API-Key'] = apiKey
        headers['X-Client-Id'] = clientId
      } else {
        return
      }
      try {
        const r = await fetch(`${api}/workspaces?limit=100`, { headers })
        if (!r.ok) return
        const data = await r.json()
        if (cancelled) return
        if (data && data.ok === true && Array.isArray(data.workspaces)) {
          const next = (data.workspaces as any[]).map(normalizeWorkspaceFromServer).filter(Boolean) as Workspace[]
          if (next.length) setWorkspaces(next)
        }
      } catch {
        // ignore
      }
    })()
    return () => {
      cancelled = true
    }
  }, [api, apiKey, clientId, authToken])

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
      window.localStorage.setItem(LS_WORKSPACES, JSON.stringify(workspaces.slice(0, 50)))
    } catch {
      // ignore
    }
    notifyWorkspaceContextChanged()
  }, [workspaces])

  useEffect(() => {
    try {
      if (!activeWorkspaceId) window.localStorage.removeItem(LS_ACTIVE_WORKSPACE_ID)
      else window.localStorage.setItem(LS_ACTIVE_WORKSPACE_ID, activeWorkspaceId)
    } catch {
      // ignore
    }
  }, [activeWorkspaceId])

  const selectedInstall = items.find((x) => x.installation_id === installationId) || null
  const installRepos = selectedInstall?.repositories || []
  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || null

  

  // Keep scan target repo consistent with active workspace
  useEffect(() => {
    if (!activeWs) return
    const preferred =
      (activeRepoForScans && activeWs.repos.includes(activeRepoForScans) && activeRepoForScans) || activeWs.repos[0] || ''
    if (preferred && preferred !== activeRepoForScans) applyScanRepo(preferred)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspaceId, workspaces])

  useEffect(() => {
    if (variant === 'gate') setSetupExpanded(true)
  }, [variant])

  const onSelectWorkspaceId = (id: string) => {
    setActiveWorkspaceId(id)
    if (!id) {
      try {
        window.localStorage.removeItem(LS_ACTIVE_WORKSPACE_ID)
        window.localStorage.removeItem(LS_PENDING_WORKSPACE_NAV)
      } catch {}
      applyScanRepo('')
      return
    }
    const ws = workspaces.find((w) => w.id === id)
    if (ws) {
      try {
        window.localStorage.setItem(LS_ACTIVE_WORKSPACE_ID, id)
      } catch {}
      setInstallationId(ws.installationId)
      const nextRepo = ws.repos[0] || ''
      setRepoFullName(nextRepo)
      applyScanRepo(nextRepo)
      try {
        window.localStorage.setItem(LS_PENDING_WORKSPACE_NAV, '1')
      } catch {}
      try {
        notifyWorkspaceContextChanged()
      } catch {
        // ignore
      }
    }
  }

  const activeWorkspaceManageBlock =
    activeWs ? (
      <div className="mt-6 border-t border-(--border-soft) pt-6">
        <div className="rounded-lg bg-(--panel-2) p-6">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <p className="text-[12px] font-semibold text-(--muted)">Selected workspace</p>
              <div className="mt-1 text-lg font-bold text-(--text)">{activeWs.name}</div>
            </div>
            <div>
              <button
                type="button"
                onClick={() => {
                  deleteRemote(activeWs.id)
                  setWorkspaces((prev) => prev.filter((x) => x.id !== activeWs.id))
                  setActiveWorkspaceId('')
                  applyScanRepo('')
                }}
                className="rounded-md border border-rose-500/20 bg-rose-500/10 px-3 py-2 font-semibold text-rose-100 transition hover:bg-rose-500/15"
              >
                Delete workspace
              </button>
            </div>
          </div>

          <div className="mb-4">
            <p className="text-sm font-semibold text-(--muted)">Repos in this workspace</p>
            <div className="mt-3 flex flex-wrap gap-3">
              {activeWs.repos.map((r) => (
                <span
                  key={r}
                  className="inline-flex items-center gap-3 rounded-full border border-(--border) bg-(--surface-elevated) px-3 py-2 text-sm text-(--text)"
                >
                  <span className="font-mono">{r}</span>
                  <button
                    type="button"
                    className="rounded-md border border-(--border) bg-transparent px-2 py-1 text-[11px] font-semibold"
                    onClick={() => {
                      const nextRepos = activeWs.repos.filter((x) => x !== r)
                      if (!nextRepos.length) return
                      const next: Workspace = {
                        ...activeWs,
                        repos: nextRepos,
                        repoFullName: nextRepos[0],
                      }
                      setWorkspaces((prev) => prev.map((w) => (w.id === next.id ? next : w)))
                      persistRemote(next)
                      if (activeRepoForScans === r) applyScanRepo(next.repos[0])
                    }}
                  >
                    Remove
                  </button>
                </span>
              ))}
            </div>
          </div>

          <label className="grid gap-2">
            <span className="text-sm font-semibold text-(--muted)">Repo used for Scans tab</span>
            <select
              value={activeRepoForScans}
              onChange={(e) => applyScanRepo(e.target.value)}
              className="w-full rounded-md border border-(--border) bg-(--panel-2) px-3 py-3 text-sm text-(--text)"
            >
              {activeWs.repos.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
    ) : null

  const addAnotherRepoBlock =
    activeWs ? (
      <div className="mt-4 border-t border-(--border-soft) pt-4">
        <p className="text-[11px] font-semibold text-(--muted)">Add another repo to &quot;{activeWs.name}&quot;</p>
        <p className="mt-1 text-[11px] text-(--muted)">Use Installation + Repo above, then pick the repo and click Add.</p>
        <div className="mt-2 flex gap-2">
          <select
            value={repoFullName}
            onChange={(e) => setRepoFullName(e.target.value)}
            disabled={!installationId || installRepos.length === 0}
            className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text) disabled:opacity-60"
          >
            <option value="">
              {installationId ? (installRepos.length ? 'Pick a repo…' : 'No repos listed') : 'Select installation first'}
            </option>
            {installRepos.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={!repoFullName || !activeWs}
            onClick={() => {
              if (!activeWs || !repoFullName) return
              if (activeWs.repos.includes(repoFullName)) return
              const next: Workspace = {
                ...activeWs,
                repos: uniqRepos([...activeWs.repos, repoFullName]),
                repoFullName: activeWs.repoFullName,
              }
              setWorkspaces((prev) => prev.map((w) => (w.id === next.id ? next : w)))
              persistRemote(next)
            }}
            className="shrink-0 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 transition hover:bg-emerald-500/15 disabled:opacity-60"
          >
            Add
          </button>
        </div>
      </div>
    ) : null

  return (
    <div className="w-full max-w-7xl mx-auto space-y-6">
      {variant === 'gate' ? (
        <section className="rounded-xl border border-teal-500/20 bg-teal-500/4 p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wider text-teal-600 dark:text-teal-300">Step 1</p>
              <h2 className="mt-1 text-sm font-bold text-(--text)">Existing workspaces</h2>
              <p className="mt-1 max-w-xl text-[11px] text-(--muted)">Pick a workspace you already have. You&apos;ll go to the dashboard for that workspace.</p>
            </div>
            <span className="shrink-0 rounded-full border border-(--border-soft) bg-(--surface-elevated) px-2.5 py-1 text-[11px] font-semibold text-(--muted)">
              {workspaces.length}/50
            </span>
          </div>
          {workspaces.length > 0 ? (
            <label className="mt-4 grid gap-1">
              <span className="text-sm font-semibold text-(--muted)">Workspace</span>
              <select
                value={activeWorkspaceId}
                onChange={(e) => onSelectWorkspaceId(e.target.value)}
                className="w-full rounded-lg border border-(--border) bg-(--panel-2) px-4 py-3 text-sm text-(--text)"
              >
                <option value="">Select a workspace…</option>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} ({w.repos.length} repo{w.repos.length === 1 ? '' : 's'})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="mt-4 rounded-lg border border-(--border-dashed) bg-(--panel-2) p-3 text-[11px] text-(--muted)">
              You don&apos;t have any workspaces yet. Use <strong className="text-(--text)">Step 2</strong> below to connect GitHub and create your first one.
            </p>
          )}
          {activeWorkspaceManageBlock}
        </section>
      ) : (
        <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Workspaces</p>
              <p className="mt-1 max-w-xl text-[11px] text-(--muted)">
                Each workspace is its own context: issues, analytics, and scans follow the repos you link. One workspace may include several GitHub repos from the
                same installation.
              </p>
            </div>
            <span className="shrink-0 text-[11px] font-medium text-(--muted)">{workspaces.length}/50</span>
          </div>

          {workspaces.length > 0 ? (
            <label className="mt-3 grid gap-1">
              <span className="text-[11px] font-semibold text-(--muted)">Active workspace</span>
              <select
                value={activeWorkspaceId}
                onChange={(e) => onSelectWorkspaceId(e.target.value)}
                className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text)"
              >
                <option value="">Select a workspace…</option>
                {workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} ({w.repos.length} repo{w.repos.length === 1 ? '' : 's'})
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <p className="mt-3 text-[11px] text-(--muted)">
              No workspaces yet. Click <span className="font-semibold text-(--text)">Create new workspace</span> to open GitHub setup and add your first one.
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setSetupExpanded(true)}
              className="rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 transition hover:bg-emerald-500/15"
            >
              Create new workspace
            </button>
            <button
              type="button"
              onClick={() => setSetupExpanded((v) => !v)}
              className="rounded-md border border-(--border) bg-(--surface-elevated) px-3 py-2 text-xs font-semibold text-(--text) transition hover:bg-(--surface-hover)"
            >
              {setupExpanded ? 'Hide GitHub & setup' : 'Show GitHub & setup'}
            </button>
          </div>
        </div>
      )}

      {setupExpanded || variant === 'gate' ? (
        <>
          {variant === 'gate' ? (
            <section className="rounded-xl border border-violet-500/25 bg-violet-500/6 p-4 sm:p-5">
              <p className="text-[10px] font-bold uppercase tracking-wider text-violet-600 dark:text-violet-300">Step 2</p>
              <h2 className="mt-1 text-sm font-bold text-(--text)">Create a new workspace</h2>
              <p className="mt-1 text-[11px] text-(--muted)">
                Connect GitHub, choose installation and repo, then name your workspace. You can also attach more repos to the workspace you selected in Step 1.
              </p>
            </section>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">GitHub setup</p>
              <p className="mt-1 text-[11px] text-(--muted)">
                Install the app, choose the installation, pick a repo, then create a workspace. One workspace can include multiple repos from that installation.
              </p>
            </div>
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
                Install app
              </button>
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1">
              <span className="text-[11px] font-semibold text-(--muted)">1) Installation</span>
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
              <span className="text-[11px] font-semibold text-(--muted)">2) Repo (first repo for a new workspace)</span>
              <select
                value={repoFullName}
                onChange={(e) => setRepoFullName(e.target.value)}
                disabled={!installationId || installRepos.length === 0}
                className="w-full rounded-md border border-(--border) bg-(--surface-elevated) px-2 py-2 text-xs text-(--text) disabled:opacity-60"
              >
                <option value="">{installationId ? (installRepos.length ? 'Select…' : 'No repos tracked yet') : 'Select installation first'}</option>
                {installRepos.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Add workspace</p>
              <span className="text-[11px] text-(--muted)">{workspaces.length}/50</span>
            </div>

            {workspaces.length === 0 ? (
              <div className="mt-2 rounded-md border border-(--border-dashed) bg-(--panel-2) p-3 text-[11px] text-(--muted)">
                Pick <span className="font-semibold text-(--text)">Installation</span> + <span className="font-semibold text-(--text)">Repo</span> above, type a workspace name, then click{' '}
                <span className="font-semibold text-(--text)">Create</span>.
              </div>
            ) : null}

            <div className="mt-2 grid gap-2">
              <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                <input
                  value={newWorkspaceName}
                  onChange={(e) => setNewWorkspaceName(e.target.value)}
                  placeholder="Workspace name (e.g. Core platform)"
                  className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text)"
                />
                <button
                  type="button"
                  disabled={!(typeof installationId === 'number' && installationId > 0 && repoFullName) || !newWorkspaceName.trim()}
                  onClick={async () => {
                    const name = newWorkspaceName.trim()
                    if (!(typeof installationId === 'number' && installationId > 0 && repoFullName && name)) return
                    const ws: Workspace = {
                      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
                      name,
                      installationId,
                      repoFullName,
                      repos: uniqRepos([repoFullName]),
                      createdAt: Date.now(),
                    }
                    const nextList = [ws, ...workspaces].slice(0, 50)
                    try {
                      window.localStorage.setItem(LS_WORKSPACES, JSON.stringify(nextList))
                      window.localStorage.setItem(LS_ACTIVE_WORKSPACE_ID, ws.id)
                    } catch {}
                    setWorkspaces(nextList)
                    setActiveWorkspaceId(ws.id)
                    setNewWorkspaceName('')
                    applyScanRepo(ws.repos[0])
                    persistRemote(ws)
                    try {
                      window.localStorage.setItem(LS_PENDING_WORKSPACE_NAV, '1')
                    } catch {}
                    // Sonar token override removed — workspace created without token
                    onWorkspaceActivated?.()
                  }}
                  className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 transition hover:bg-emerald-500/15 disabled:opacity-60"
                >
                  Create
                </button>
              </div>

              {/* Sonar token override removed */}

              {variant === 'gate' ? addAnotherRepoBlock : null}
              {variant !== 'gate' && activeWs ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px]">
                    <span className="text-(--muted)">
                      Editing workspace: <span className="font-semibold text-(--text)">{activeWs.name}</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        deleteRemote(activeWs.id)
                        setWorkspaces((prev) => prev.filter((x) => x.id !== activeWs.id))
                        setActiveWorkspaceId('')
                        applyScanRepo('')
                      }}
                      className="rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-1 font-semibold text-rose-100 transition hover:bg-rose-500/15"
                    >
                      Delete workspace
                    </button>
                  </div>

                  <div>
                    <p className="text-[11px] font-semibold text-(--muted)">Repos in this workspace</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {activeWs.repos.map((r) => (
                        <span
                          key={r}
                          className="inline-flex items-center gap-2 rounded-full border border-(--border) bg-(--panel-2) px-2 py-1 text-[11px] text-(--text)"
                        >
                          <span className="font-mono">{r}</span>
                          <button
                            type="button"
                            className="rounded-md border border-(--border) bg-(--surface-elevated) px-1.5 py-0.5 text-[10px] font-semibold"
                            onClick={() => {
                              const nextRepos = activeWs.repos.filter((x) => x !== r)
                              if (!nextRepos.length) return
                              const next: Workspace = {
                                ...activeWs,
                                repos: nextRepos,
                                repoFullName: nextRepos[0],
                              }
                              setWorkspaces((prev) => prev.map((w) => (w.id === next.id ? next : w)))
                              persistRemote(next)
                              if (activeRepoForScans === r) applyScanRepo(next.repos[0])
                            }}
                          >
                            Remove
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="grid gap-2 sm:grid-cols-2">
                    <label className="grid gap-1">
                      <span className="text-[11px] font-semibold text-(--muted)">Repo used for Scans tab</span>
                      <select
                        value={activeRepoForScans}
                        onChange={(e) => applyScanRepo(e.target.value)}
                        className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text)"
                      >
                        {activeWs.repos.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label className="grid gap-1">
                      <span className="text-[11px] font-semibold text-(--muted)">Add another repo</span>
                      <div className="flex gap-2">
                        <select
                          value={repoFullName}
                          onChange={(e) => setRepoFullName(e.target.value)}
                          disabled={!installationId || installRepos.length === 0}
                          className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text) disabled:opacity-60"
                        >
                          <option value="">
                            {installationId ? (installRepos.length ? 'Pick a repo…' : 'No repos listed') : 'Select installation above'}
                          </option>
                          {installRepos.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={!repoFullName || !activeWs}
                          onClick={() => {
                            if (!activeWs || !repoFullName) return
                            if (activeWs.repos.includes(repoFullName)) return
                            const next: Workspace = {
                              ...activeWs,
                              repos: uniqRepos([...activeWs.repos, repoFullName]),
                              repoFullName: activeWs.repoFullName,
                            }
                            setWorkspaces((prev) => prev.map((w) => (w.id === next.id ? next : w)))
                            persistRemote(next)
                          }}
                          className="shrink-0 rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 transition hover:bg-emerald-500/15 disabled:opacity-60"
                        >
                          Add
                        </button>
                      </div>
                    </label>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="text-[11px] text-(--muted)">
            <span className="font-semibold text-(--text)">Tip:</span> use separate workspaces when you want isolated metrics (e.g. team A vs team B). Each workspace can still list multiple repos from one GitHub installation.
          </div>
        </>
      ) : null}

      {error ? (
        <div className="rounded-md border border-rose-500/20 bg-rose-500/10 p-2 text-[11px] text-rose-100">{error}</div>
      ) : null}
    </div>
  )
}
