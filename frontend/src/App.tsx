import { useEffect, useMemo, useState } from 'react'
import './App.css'
import type { Fix, Issue, TabKey } from './types'
import Sidebar from './components/Sidebar'
import OverviewPanel from './components/OverviewPanel'
import IssuePanel from './components/IssuePanel'
import FixPanel from './components/FixPanel'
import AnalyticsPanel from './components/AnalyticsPanel'
import HistoryPanel from './components/HistoryPanel'
import SearchModal from './components/SearchModal'
import { Skeleton } from './components/Skeleton'
import { useToast } from './components/Toast'

type ThemeMode = 'dark' | 'light'

const THEME_STORAGE_KEY = 'slca.theme'
const SIDEBAR_STORAGE_KEY = 'slca.sidebarCollapsed'
const ACTIVE_TAB_STORAGE_KEY = 'slca.activeTab'
const ISSUE_SORT_STORAGE_KEY = 'slca.issueSort'
const SCAN_HISTORY_STORAGE_KEY = 'slca.scanHistory'

type ScanSnapshot = {
  id: string
  ts: number
  source: 'overview' | 'issues' | 'fixes' | 'analytics' | 'manual'
  issuesCount: number
  fixesCount: number
  blocker: number
  critical: number
}

function computeSeverityCounts(issues: Issue[]) {
  const counts = { BLOCKER: 0, CRITICAL: 0, MAJOR: 0, MINOR: 0 }
  for (const issue of issues) counts[issue.severity] = (counts[issue.severity] || 0) + 1
  return counts
}

function loadHistory(): ScanSnapshot[] {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(SCAN_HISTORY_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as ScanSnapshot[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function getInitialTheme(): ThemeMode {
  if (typeof window === 'undefined') return 'dark'
  const saved = window.localStorage.getItem(THEME_STORAGE_KEY)
  return saved === 'light' ? 'light' : 'dark'
}

function getInitialSidebarCollapsed() {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === '1'
}

function applyTheme(theme: ThemeMode) {
  document.documentElement.setAttribute('data-theme', theme)
}


export default function App() {
  const toast = useToast()
  const [issues, setIssues] = useState<Issue[]>([])
  const [fixes, setFixes] = useState<Fix[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isOnline, setIsOnline] = useState(true)
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>(() => {
    if (typeof window === 'undefined') return 'overview'
    const saved = window.localStorage.getItem(ACTIVE_TAB_STORAGE_KEY) as TabKey | null
    return saved && ['overview', 'issues', 'fixes', 'analytics', 'history'].includes(saved) ? saved : 'overview'
  })
  const [lastUpdated, setLastUpdated] = useState<string>('–')
  const [sortBy, setSortBy] = useState<'severity' | 'date' | 'file'>(() => {
    if (typeof window === 'undefined') return 'severity'
    const saved = window.localStorage.getItem(ISSUE_SORT_STORAGE_KEY) as 'severity' | 'date' | 'file' | null
    return saved && ['severity', 'date', 'file'].includes(saved) ? saved : 'severity'
  })
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getInitialSidebarCollapsed)
  const [searchOpen, setSearchOpen] = useState(false)
  const [scanHistory, setScanHistory] = useState<ScanSnapshot[]>(loadHistory)
  const [loaded, setLoaded] = useState<Record<TabKey, boolean>>({
    overview: false,
    issues: false,
    fixes: false,
    analytics: false,
    history: true,
  })

  const API_BASE = 'http://127.0.0.1:8000'

  const updateTimestamp = () => {
    setLastUpdated(new Date().toLocaleTimeString())
  }

  const recordSnapshot = (source: ScanSnapshot['source'], nextIssues: Issue[], nextFixes: Fix[]) => {
    const sev = computeSeverityCounts(nextIssues)
    const snap: ScanSnapshot = {
      id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      ts: Date.now(),
      source,
      issuesCount: nextIssues.length,
      fixesCount: nextFixes.length,
      blocker: sev.BLOCKER,
      critical: sev.CRITICAL,
    }
    setScanHistory((prev) => {
      const next = [snap, ...prev].slice(0, 50)
      window.localStorage.setItem(SCAN_HISTORY_STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  const fetchIssues = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/issues`)
      const data = await response.json()
      const nextIssues = data.issues || []
      setIssues(nextIssues)
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, issues: true }))
      toast.push({ kind: 'success', title: 'Synced issues', message: `${(data.issues || []).length} loaded` })
      recordSnapshot('issues', nextIssues, fixes)
    } catch (err) {
      setError('Failed to fetch issues. Is backend running?')
      toast.push({ kind: 'error', title: 'Sync failed', message: 'Unable to fetch issues' })
      console.error(err)
    }
    setLoading(false)
  }

  const fetchFixes = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/fixes`)
      const data = await response.json()
      const nextFixes = data.results || []
      setFixes(nextFixes)
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, fixes: true }))
      toast.push({ kind: 'success', title: 'Synced fixes', message: `${(data.results || []).length} loaded` })
      recordSnapshot('fixes', issues, nextFixes)
    } catch (err) {
      setError('Failed to fetch fixes. Is backend running?')
      toast.push({ kind: 'error', title: 'Sync failed', message: 'Unable to fetch fixes' })
      console.error(err)
    }
    setLoading(false)
  }

  const fetchOverview = async () => {
    setLoading(true)
    setError(null)
    try {
      const [issuesResponse, fixesResponse] = await Promise.all([
        fetch(`${API_BASE}/issues`),
        fetch(`${API_BASE}/fixes`),
      ])

      const issuesData = await issuesResponse.json()
      const fixesData = await fixesResponse.json()
      const nextIssues = issuesData.issues || []
      const nextFixes = fixesData.results || []
      setIssues(nextIssues)
      setFixes(nextFixes)
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, overview: true }))
      toast.push({
        kind: 'success',
        title: 'Synced overview',
        message: `${(issuesData.issues || []).length} issues • ${(fixesData.results || []).length} fixes`,
      })
      recordSnapshot('overview', nextIssues, nextFixes)
    } catch (err) {
      setError('Failed to load overview data. Is backend running?')
      toast.push({ kind: 'error', title: 'Sync failed', message: 'Unable to load overview' })
      console.error(err)
    }
    setLoading(false)
  }

  const fetchAnalytics = async () => {
    setLoading(true)
    setError(null)
    try {
      const [issuesResponse, fixesResponse] = await Promise.all([
        fetch(`${API_BASE}/issues`),
        fetch(`${API_BASE}/fixes`),
      ])
      const issuesData = await issuesResponse.json()
      const fixesData = await fixesResponse.json()
      const nextIssues = issuesData.issues || []
      const nextFixes = fixesData.results || []
      setIssues(nextIssues)
      setFixes(nextFixes)
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, analytics: true }))
      toast.push({ kind: 'info', title: 'Analytics refreshed', message: 'Metrics updated' })
      recordSnapshot('analytics', nextIssues, nextFixes)
    } catch (err) {
      setError('Failed to load analytics data. Is backend running?')
      toast.push({ kind: 'error', title: 'Refresh failed', message: 'Unable to load analytics data' })
      console.error(err)
    }
    setLoading(false)
  }

  const fetchHistory = () => {
    // local-only tab; nothing to fetch
  }

  const refreshActiveTab = () => {
    if (activeTab === 'issues') {
      fetchIssues()
    } else if (activeTab === 'fixes') {
      fetchFixes()
    } else if (activeTab === 'analytics') {
      fetchAnalytics()
    } else if (activeTab === 'history') {
      fetchHistory()
    } else {
      fetchOverview()
    }
  }

  useEffect(() => {
    // Only fetch if this tab hasn't been loaded yet
    if (!loaded[activeTab]) {
      refreshActiveTab()
    }
  }, [activeTab, loaded])

  useEffect(() => {
    applyTheme(theme)
    window.localStorage.setItem(THEME_STORAGE_KEY, theme)
  }, [theme])

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    window.localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, activeTab)
  }, [activeTab])

  useEffect(() => {
    window.localStorage.setItem(ISSUE_SORT_STORAGE_KEY, sortBy)
  }, [sortBy])

  useEffect(() => {
    setIsOnline(navigator.onLine)
    const onOnline = () => setIsOnline(true)
    const onOffline = () => setIsOnline(false)
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const summary = useMemo(() => {
    const counts = { BLOCKER: 0, CRITICAL: 0, MAJOR: 0, MINOR: 0 }
    issues.forEach((issue) => {
      counts[issue.severity] = (counts[issue.severity] || 0) + 1
    })
    return counts
  }, [issues])

  const severityOrder = { BLOCKER: 0, CRITICAL: 1, MAJOR: 2, MINOR: 3 }

  const sortedIssues = useMemo(() => {
    const sorted = [...issues]
    if (sortBy === 'severity') {
      sorted.sort((a, b) => severityOrder[a.severity] - severityOrder[b.severity])
    } else if (sortBy === 'date') {
      sorted.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    } else if (sortBy === 'file') {
      sorted.sort((a, b) => a.file.localeCompare(b.file))
    }
    return sorted
  }, [issues, sortBy])

  return (
    <div className="app-shell min-h-screen bg-(--app-bg)">
      <div
        className={`app-layout grid min-h-screen gap-0 ${
          sidebarCollapsed ? 'md:grid-cols-[80px_1fr]' : 'md:grid-cols-[288px_1fr]'
        }`}
      >
        <Sidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          issuesCount={issues.length}
          fixesCount={fixes.length}
          lastUpdated={lastUpdated}
          issues={issues}
          fetchOverview={fetchOverview}
          fetchIssues={fetchIssues}
          fetchFixes={fetchFixes}
          fetchAnalytics={fetchAnalytics}
          fetchHistory={fetchHistory}
          collapsed={sidebarCollapsed}
          setCollapsed={setSidebarCollapsed}
        />

        <main className="main-panel md:ml-0 rounded-lg border border-(--border) bg-(--panel) p-6 shadow-2xl shadow-(color:--shadow) md:rounded-lg">
          {!isOnline && (
            <div className="mb-4 rounded-lg border border-amber-500/25 bg-amber-500/10 p-3 text-sm text-amber-100">
              You are offline. Showing last loaded data (if any).
            </div>
          )}
          <div className="mt-12 md:mt-0 mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-widest text-violet-300 font-semibold">Dashboard</p>
              <h1 className="mt-1 text-3xl font-bold text-(--text)">Shift Left Compliance Agent</h1>
              <p className="mt-2 text-sm text-(--muted)">
                Real-time issue tracking and AI-powered code fixes
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <button
                onClick={() => setSearchOpen(true)}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-(--border-soft) bg-(--panel-2) px-4 py-2.5 text-sm font-semibold text-(--text) transition hover:opacity-95 active:scale-[0.99]"
                title="Search (Ctrl+K)"
              >
                <span className="text-base">⌕</span>
                <span>Search</span>
                <span className="hidden sm:inline rounded-md border border-(--border-soft) bg-white/5 px-2 py-0.5 text-[11px] font-mono text-(--muted)">
                  Ctrl K
                </span>
              </button>
              <button
                onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-(--border-soft) bg-(--panel-2) px-4 py-2.5 text-sm font-semibold text-(--text) transition hover:opacity-95 active:scale-[0.99]"
              >
                {theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
              </button>
              <button
                onClick={() => {
                  setLoaded({ overview: false, issues: false, fixes: false, analytics: false, history: true })
                  refreshActiveTab()
                }}
                disabled={loading}
                className={`inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-bold text-white transition ${
                  loading
                    ? 'bg-violet-600/50 cursor-not-allowed opacity-75'
                    : 'bg-violet-600 hover:bg-violet-500 active:scale-95'
                }`}
              >
                {loading ? '⟳ Syncing...' : '⟳ Sync Latest'}
              </button>
                  <span className="rounded-lg border border-(--border-soft) bg-(--panel-2) px-3 py-2 text-xs font-medium text-(--text)">
                {activeTab === 'overview'
                  ? 'Overview'
                  : activeTab === 'issues'
                  ? 'Issues'
                  : activeTab === 'fixes'
                  ? 'Fixes'
                      : activeTab === 'analytics'
                      ? 'Analytics'
                      : 'History'}
              </span>
            </div>
          </div>

          {error && (
            <div className="mb-6 rounded-lg border border-rose-900/30 bg-rose-950/40 p-4 text-sm text-rose-100">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>⚠️ {error}</span>
                <button
                  onClick={refreshActiveTab}
                  className="inline-flex items-center justify-center rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-100 transition hover:bg-rose-500/15"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Total Issues</p>
                <p className="mt-2 text-3xl font-bold text-(--text)">{issues.length}</p>
              </div>
              <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">AI Fixes</p>
                <p className="mt-2 text-3xl font-bold text-(--text)">{fixes.length}</p>
              </div>
            </div>

            <div className="rounded-lg border border-(--border) bg-(--panel-2) p-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-bold text-(--text)">
                      {activeTab === 'issues'
                        ? 'Issues'
                        : activeTab === 'fixes'
                        ? 'Fixes'
                        : activeTab === 'analytics'
                        ? 'Analytics'
                        : activeTab === 'history'
                        ? 'History'
                        : 'Overview'}
                    </h2>
                    <p className="mt-1 text-xs text-(--muted)">
                      {activeTab === 'issues'
                        ? `${issues.length} issue${issues.length !== 1 ? 's' : ''} found`
                        : activeTab === 'fixes'
                        ? `${fixes.length} fix${fixes.length !== 1 ? 'es' : ''} available`
                        : activeTab === 'analytics'
                        ? 'Metrics, hotspots & trends'
                        : activeTab === 'history'
                        ? 'Snapshots over time (local)'
                        : 'Compliance metrics & insights'}
                    </p>
                  </div>
                  <span className="rounded-full bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-600 border border-violet-500/20">
                    {activeTab === 'overview'
                      ? 'Overview'
                      : activeTab === 'issues'
                      ? 'Issues'
                      : activeTab === 'fixes'
                      ? 'Fixes'
                      : 'Analytics'}
                  </span>
                </div>

                {loading && (
                  <div className="space-y-3">
                    <div className="rounded-lg border border-dashed border-(--border-dashed) p-4 text-sm text-(--muted)">
                      <div className="mb-2 inline-flex animate-spin text-lg">⟳</div>
                      <p>Loading {activeTab}…</p>
                    </div>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Skeleton className="h-20" />
                      <Skeleton className="h-20" />
                    </div>
                    <Skeleton className="h-24" />
                    <Skeleton className="h-24" />
                    <Skeleton className="h-24" />
                  </div>
                )}

                {!loading && activeTab === 'overview' && (
                  <OverviewPanel issuesCount={issues.length} fixesCount={fixes.length} lastUpdated={lastUpdated} summary={summary} />
                )}

                {!loading && activeTab === 'issues' && (
                  <IssuePanel
                    issues={sortedIssues}
                    expandedIssue={expandedIssue}
                    toggleExpanded={(key) => setExpandedIssue(expandedIssue === key ? null : key)}
                    sortBy={sortBy}
                    setSortBy={setSortBy}
                  />
                )}

                {!loading && activeTab === 'fixes' && (
                  <FixPanel
                    fixes={fixes}
                    expandedIssue={expandedIssue}
                    toggleExpanded={(key) => setExpandedIssue(expandedIssue === key ? null : key)}
                    onViewIssue={(issueKey) => {
                      setActiveTab('issues')
                      setExpandedIssue(issueKey)
                      if (!loaded.issues) fetchIssues()
                    }}
                  />
                )}

                {!loading && activeTab === 'analytics' && (
                  <AnalyticsPanel issues={issues} fixes={fixes} lastUpdated={lastUpdated} />
                )}

                {!loading && activeTab === 'history' && (
                  <HistoryPanel
                    history={scanHistory}
                    onClear={() => {
                      window.localStorage.removeItem(SCAN_HISTORY_STORAGE_KEY)
                      setScanHistory([])
                    }}
                  />
                )}
              </div>
            </div>
          </div>
        </main>
      </div>

      <SearchModal
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        issues={issues}
        onSelectIssue={(issue) => {
          setActiveTab('issues')
          setExpandedIssue(issue.key)
          setSearchOpen(false)
          if (!loaded.issues) fetchIssues()
        }}
      />
    </div>
  )
}
