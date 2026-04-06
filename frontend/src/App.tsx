import { useEffect, useMemo, useState } from 'react'
import './App.css'
import type { Fix, Issue, TabKey } from './types'
import Sidebar from './components/Sidebar'
import OverviewPanel from './components/OverviewPanel'
import IssuePanel from './components/IssuePanel'
import FixPanel from './components/FixPanel'


export default function App() {
  const [issues, setIssues] = useState<Issue[]>([])
  const [fixes, setFixes] = useState<Fix[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expandedIssue, setExpandedIssue] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [lastUpdated, setLastUpdated] = useState<string>('–')
  const [sortBy, setSortBy] = useState<'severity' | 'date' | 'file'>('severity')
  const [loaded, setLoaded] = useState<Record<TabKey, boolean>>({
    overview: false,
    issues: false,
    fixes: false,
  })

  const API_BASE = 'http://127.0.0.1:8000'

  const updateTimestamp = () => {
    setLastUpdated(new Date().toLocaleTimeString())
  }

  const fetchIssues = async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_BASE}/issues`)
      const data = await response.json()
      setIssues(data.issues || [])
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, issues: true }))
    } catch (err) {
      setError('Failed to fetch issues. Is backend running?')
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
      setFixes(data.results || [])
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, fixes: true }))
    } catch (err) {
      setError('Failed to fetch fixes. Is backend running?')
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
      setIssues(issuesData.issues || [])
      setFixes(fixesData.results || [])
      updateTimestamp()
      setLoaded((prev) => ({ ...prev, overview: true }))
    } catch (err) {
      setError('Failed to load overview data. Is backend running?')
      console.error(err)
    }
    setLoading(false)
  }

  const refreshActiveTab = () => {
    if (activeTab === 'issues') {
      fetchIssues()
    } else if (activeTab === 'fixes') {
      fetchFixes()
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
    <div className="app-shell min-h-screen bg-slate-950">
      <div className="app-layout grid min-h-screen gap-0 md:grid-cols-[288px_1fr]">
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
        />

        <main className="main-panel md:ml-0 rounded-lg border border-slate-700 bg-slate-900 p-6 shadow-xl md:rounded-lg">
          <div className="mt-12 md:mt-0 mb-6 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-widest text-sky-400 font-semibold">Dashboard</p>
              <h1 className="mt-1 text-3xl font-bold text-white">Compliance Review</h1>
              <p className="mt-2 text-sm text-slate-400">
                Real-time issue tracking and AI-powered code fixes
              </p>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <button
                onClick={() => {
                  setLoaded({ overview: false, issues: false, fixes: false })
                  refreshActiveTab()
                }}
                disabled={loading}
                className={`inline-flex items-center justify-center gap-2 rounded-lg px-5 py-2.5 text-sm font-bold text-white transition ${
                  loading
                    ? 'bg-sky-600/50 cursor-not-allowed opacity-75'
                    : 'bg-sky-600 hover:bg-sky-500 active:scale-95'
                }`}
              >
                {loading ? '⟳ Syncing...' : '⟳ Sync Latest'}
              </button>
              <span className="rounded-lg bg-slate-800 px-3 py-2 text-xs font-medium text-slate-300">
                {activeTab === 'overview' ? 'Overview' : activeTab === 'issues' ? 'Issues' : 'Fixes'}
              </span>
            </div>
          </div>

          {error && (
            <div className="mb-6 rounded-lg border border-red-900/30 bg-red-950/50 p-4 text-sm text-red-200">
              ⚠️ {error}
            </div>
          )}

          <div className="space-y-6">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Total Issues</p>
                <p className="mt-2 text-3xl font-bold text-white">{issues.length}</p>
              </div>
              <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
                <p className="text-xs font-medium uppercase tracking-wider text-slate-400">AI Fixes</p>
                <p className="mt-2 text-3xl font-bold text-white">{fixes.length}</p>
              </div>
            </div>

            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-6">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-bold text-white">
                      {activeTab === 'issues' ? 'Issues' : activeTab === 'fixes' ? 'Fixes' : 'Overview'}
                    </h2>
                    <p className="mt-1 text-xs text-slate-500">
                      {activeTab === 'issues'
                        ? `${issues.length} issue${issues.length !== 1 ? 's' : ''} found`
                        : activeTab === 'fixes'
                        ? `${fixes.length} fix${fixes.length !== 1 ? 'es' : ''} available`
                        : 'Compliance metrics & insights'}
                    </p>
                  </div>
                  <span className="rounded-full bg-sky-500/10 px-3 py-1 text-xs font-medium text-sky-300 border border-sky-500/20">
                    {activeTab === 'overview' ? 'Overview' : activeTab === 'issues' ? 'Issues' : 'Fixes'}
                  </span>
                </div>

                {loading && (
                  <div className="rounded-lg border border-dashed border-slate-600 p-8 text-center text-slate-400">
                    <div className="mb-3 inline-flex animate-spin text-xl">⟳</div>
                    <p className="text-sm">Loading {activeTab}…</p>
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
                  <FixPanel fixes={fixes} expandedIssue={expandedIssue} toggleExpanded={(key) => setExpandedIssue(expandedIssue === key ? null : key)} />
                )}
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}
