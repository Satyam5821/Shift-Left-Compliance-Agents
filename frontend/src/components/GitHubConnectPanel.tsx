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
const LS_WORKSPACES = 'slca.workspaces'
const LS_ACTIVE_WORKSPACE_ID = 'slca.activeWorkspaceId'
const LS_CLIENT_ID = 'slca.clientId'
const LS_AUTH_TOKEN = 'slca.authToken'

type Workspace = {
  id: string
  name: string
  installationId: number
  repoFullName: string
  createdAt: number
}

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
  const [workspaces, setWorkspaces] = useState<Workspace[]>(() => {
    try {
      const raw = window.localStorage.getItem(LS_WORKSPACES)
      const parsed = raw ? (JSON.parse(raw) as unknown) : []
      return Array.isArray(parsed) ? (parsed as Workspace[]) : []
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
  const [newWorkspaceName, setNewWorkspaceName] = useState('')

  const api = useMemo(() => normalizeBase(apiBase), [apiBase])
  const installUrl = `${api}/github/install`
  const apiKey = (import.meta.env.VITE_SHIFTLEFT_API_KEY as string | undefined) || ''
  const authToken = useMemo(() => {
    try {
      return window.localStorage.getItem(LS_AUTH_TOKEN) || ''
    } catch {
      return ''
    }
  }, [])

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

  // Try loading persisted workspaces from backend (optional).
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
        const r = await fetch(`${api}/workspaces?limit=100`, {
          headers,
        })
        if (!r.ok) return
        const data = await r.json()
        if (cancelled) return
        if (data && data.ok === true && Array.isArray(data.workspaces)) {
          const next = (data.workspaces as any[])
            .filter((w) => w && typeof w === 'object' && typeof w.id === 'string')
            .map((w) => ({
              id: String(w.id),
              name: String(w.name || 'Workspace'),
              installationId: Number(w.installationId || 0),
              repoFullName: String(w.repoFullName || ''),
              createdAt: Number(w.created_at || Date.now()),
            }))
            .filter((w) => w.installationId > 0 && w.repoFullName)
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
      if (!repoFullName) window.localStorage.removeItem(LS_REPO_FULL_NAME)
      else window.localStorage.setItem(LS_REPO_FULL_NAME, repoFullName)
    } catch {
      // ignore
    }
  }, [repoFullName])

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_WORKSPACES, JSON.stringify(workspaces.slice(0, 50)))
    } catch {
      // ignore
    }
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
  const repos = selectedInstall?.repositories || []
  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId) || null

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

      <div className="mt-3 rounded-lg border border-(--border) bg-(--surface-elevated) p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)">Workspace</p>
          <span className="text-[11px] text-(--muted)">{workspaces.length}/50</span>
        </div>

        <div className="mt-2 grid gap-2">
          <select
            value={activeWorkspaceId}
            onChange={(e) => {
              const id = e.target.value
              setActiveWorkspaceId(id)
              const ws = workspaces.find((w) => w.id === id)
              if (ws) {
                setInstallationId(ws.installationId)
                setRepoFullName(ws.repoFullName)
              }
            }}
            className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text)"
          >
            <option value="">No workspace selected</option>
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} • {w.repoFullName}
              </option>
            ))}
          </select>

          {activeWs && (
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="text-(--muted)">
                Active: <span className="font-semibold text-(--text)">{activeWs.name}</span>
              </span>
              <button
                type="button"
                onClick={() => {
                  setWorkspaces((prev) => prev.filter((x) => x.id !== activeWs.id))
                  setActiveWorkspaceId('')
                  if (authToken) {
                    fetch(`${api}/workspaces/${encodeURIComponent(activeWs.id)}`, {
                      method: 'DELETE',
                      headers: { Authorization: `Bearer ${authToken}` },
                    }).catch(() => {})
                  } else if (apiKey) {
                    fetch(`${api}/workspaces/${encodeURIComponent(activeWs.id)}`, {
                      method: 'DELETE',
                      headers: { 'X-API-Key': apiKey, 'X-Client-Id': clientId },
                    }).catch(() => {})
                  }
                }}
                className="rounded-md border border-rose-500/20 bg-rose-500/10 px-2 py-1 font-semibold text-rose-100 transition hover:bg-rose-500/15"
              >
                Delete
              </button>
            </div>
          )}

          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <input
              value={newWorkspaceName}
              onChange={(e) => setNewWorkspaceName(e.target.value)}
              placeholder="New workspace name (e.g. Payments API)"
              className="w-full rounded-md border border-(--border) bg-(--panel-2) px-2 py-2 text-xs text-(--text)"
            />
            <button
              type="button"
              disabled={!(typeof installationId === 'number' && installationId > 0 && repoFullName) || !newWorkspaceName.trim()}
              onClick={() => {
                const name = newWorkspaceName.trim()
                if (!(typeof installationId === 'number' && installationId > 0 && repoFullName && name)) return
                const ws: Workspace = {
                  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
                  name,
                  installationId,
                  repoFullName,
                  createdAt: Date.now(),
                }
                setWorkspaces((prev) => [ws, ...prev].slice(0, 50))
                setActiveWorkspaceId(ws.id)
                setNewWorkspaceName('')
                if (authToken) {
                  fetch(`${api}/workspaces`, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      Authorization: `Bearer ${authToken}`,
                    },
                    body: JSON.stringify(ws),
                  }).catch(() => {})
                } else if (apiKey) {
                  fetch(`${api}/workspaces`, {
                    method: 'POST',
                    headers: {
                      'Content-Type': 'application/json',
                      'X-API-Key': apiKey,
                      'X-Client-Id': clientId,
                    },
                    body: JSON.stringify(ws),
                  }).catch(() => {})
                }
              }}
              className="rounded-md border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs font-bold text-emerald-200 transition hover:bg-emerald-500/15 disabled:opacity-60"
            >
              Save
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-3 rounded-md border border-rose-500/20 bg-rose-500/10 p-2 text-[11px] text-rose-100">
          {error}
        </div>
      )}

      <div className="mt-3 grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="text-[11px] text-(--muted)">
            Account: <span className="font-semibold text-(--text)">{authToken ? 'signed in' : 'guest'}</span>
          </div>
        </div>
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

