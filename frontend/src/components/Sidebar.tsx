import { useState } from 'react'
import type { TabKey, Issue } from '../types'
import AnalyticsSection from './AnalyticsSection'

interface SidebarProps {
  activeTab: TabKey
  setActiveTab: (tab: TabKey) => void
  issuesCount: number
  fixesCount: number
  lastUpdated: string
  issues: Issue[]
  fetchOverview: () => void
  fetchIssues: () => void
  fetchFixes: () => void
}

const Sidebar = ({
  activeTab,
  setActiveTab,
  issuesCount,
  fixesCount,
  lastUpdated,
  issues,
  fetchOverview,
  fetchIssues,
  fetchFixes,
}: SidebarProps) => {
  const [isOpen, setIsOpen] = useState(true)

  const navItems = [
    { id: 'overview', label: 'Overview', icon: '📊', count: '', action: fetchOverview },
    { id: 'issues', label: 'Issues', icon: '📋', count: `${issuesCount}`, action: fetchIssues },
    { id: 'fixes', label: 'Fixes', icon: '🛠️', count: `${fixesCount}`, action: fetchFixes },
  ] as const

  return (
    <>
      {/* Hamburger Button (visible on mobile) */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed top-4 left-4 z-50 flex h-10 w-10 items-center justify-center rounded-lg bg-sky-500 text-white md:hidden"
      >
        {isOpen ? '✕' : '☰'}
      </button>

      {/* Overlay for mobile */}
      {isOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setIsOpen(false)} />
      )}

      {/* Sidebar */}
      <aside
        className={`sidebar fixed left-0 top-0 z-40 h-screen w-72 transform transition-transform duration-300 md:relative md:transform-none ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        } border-r border-slate-700 bg-slate-900 p-6 md:h-auto md:border-r md:border-slate-800`}
      >
        <div className="mb-8 mt-14 md:mt-0">
          <div className="mb-3">
            <h2 className="text-2xl font-bold text-white">Shift-Left</h2>
            <p className="text-sm text-slate-400">Compliance Auditor</p>
          </div>
          <p className="text-xs text-slate-500">Manage issues and fixes in real-time</p>
        </div>

        {/* Navigation */}
        <nav className="space-y-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setActiveTab(item.id as TabKey)
                item.action()
                if (window.innerWidth < 768) setIsOpen(false)
              }}
              className={`group w-full rounded-lg px-4 py-3 text-left transition ${
                activeTab === item.id
                  ? 'border border-sky-400 bg-sky-500/15 shadow-lg shadow-sky-500/10'
                  : 'border border-slate-700 bg-slate-800/40 hover:border-slate-600 hover:bg-slate-800/60'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-lg">{item.icon}</span>
                  <span className="font-medium text-white">{item.label}</span>
                </div>
                {item.count && (
                  <span className="rounded-full bg-sky-500/20 px-2 py-1 text-xs font-semibold text-sky-300">
                    {item.count}
                  </span>
                )}
              </div>
            </button>
          ))}
        </nav>

        {/* Analytics Section */}
        <AnalyticsSection issues={issues} />

        {/* Status Bar */}
        <div className="mt-10 rounded-lg border border-slate-700 bg-slate-800/40 p-4">
          <div className="mb-3 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse"></span>
            <p className="text-xs font-semibold text-slate-300 uppercase tracking-wide">Live</p>
          </div>
          <div className="space-y-2 text-xs text-slate-400">
            <p>Last sync: <span className="text-slate-200 font-mono">{lastUpdated}</span></p>
            <p>Status: <span className="text-emerald-400 font-medium">Connected</span></p>
          </div>
        </div>
      </aside>
    </>
  )
}

export default Sidebar
