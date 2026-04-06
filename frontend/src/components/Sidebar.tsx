import { useEffect, useState } from 'react'
import type { TabKey, Issue } from '../types'

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
  fetchAnalytics: () => void
  fetchHistory: () => void
  collapsed: boolean
  setCollapsed: (collapsed: boolean) => void
}

function Icon({
  name,
  className,
}: {
  name: 'overview' | 'issues' | 'fixes' | 'analytics' | 'history'
  className?: string
}) {
  const common = `h-5 w-5 ${className || ''}`

  if (name === 'overview') {
    return (
      <svg className={common} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M4 4h7v7H4V4Zm9 0h7v11h-7V4ZM4 13h7v7H4v-7Zm9 4h7v3h-7v-3Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  if (name === 'issues') {
    return (
      <svg className={common} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M7 4h10a2 2 0 0 1 2 2v14l-4-2-4 2-4-2-4 2V6a2 2 0 0 1 2-2Z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path d="M8 8h8M8 12h8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
    )
  }

  if (name === 'fixes') {
    return (
      <svg className={common} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M14 7l3 3m-9 9l-3-3m1-7l4-4a3 3 0 0 1 4.2 0l4.8 4.8a3 3 0 0 1 0 4.2l-4 4a3 3 0 0 1-4.2 0L6 13"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
    )
  }

  if (name === 'history') {
    return (
      <svg className={common} viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path
          d="M3 12a9 9 0 1 0 3-6.7"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M3 3v4h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  return (
    <svg className={common} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M4 19V5m0 14h16M8 16V9m4 7V6m4 10v-4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
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
  fetchAnalytics,
  fetchHistory,
  collapsed,
  setCollapsed,
}: SidebarProps) => {
  const [isOpen, setIsOpen] = useState(true)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const navItems = [
    { id: 'overview', label: 'Overview', count: '', action: fetchOverview },
    { id: 'issues', label: 'Issues', count: `${issuesCount}`, action: fetchIssues },
    { id: 'fixes', label: 'Fixes', count: `${fixesCount}`, action: fetchFixes },
    { id: 'analytics', label: 'Analytics', count: '', action: fetchAnalytics },
    { id: 'history', label: 'History', count: '', action: fetchHistory },
  ] as const

  return (
    <>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="fixed top-4 left-4 z-50 flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-white shadow-lg shadow-(color:--shadow) md:hidden"
      >
        {isOpen ? '✕' : '☰'}
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-30 bg-black/50 md:hidden" onClick={() => setIsOpen(false)} />
      )}

      <aside
        className={`sidebar fixed left-0 top-0 z-40 h-screen transform transition-[transform,width] duration-300 md:relative md:transform-none ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        } ${collapsed ? 'w-20 p-4' : 'w-72 p-6'} border-r border-(--border) bg-(--panel) backdrop-blur md:h-auto md:border-r`}
      >
        <div className="mb-6 mt-14 md:mt-0">
          <div className={`mb-4 flex items-center ${collapsed ? 'justify-center' : 'gap-3'}`}>
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-violet-500/20 bg-violet-500/10 text-violet-600">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path
                  d="M7.5 7.5 12 5l4.5 2.5V13c0 3.3-2.2 6.2-4.5 7-2.3-.8-4.5-3.7-4.5-7V7.5Z"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinejoin="round"
                />
                <path d="M9.5 11.5 11 13l3.5-3.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
              </svg>
            </div>
            {!collapsed && (
              <div>
                <h2 className="text-base font-bold text-(--text) leading-tight">Shift Left</h2>
                <p className="text-xs text-(--muted)">Compliance Agent</p>
              </div>
            )}
          </div>
          {!collapsed && <p className="text-xs text-(--muted)">Shift Left Compliance Agent</p>}

          <div className={`mt-4 flex ${collapsed ? 'justify-center' : 'justify-between'}`}>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="inline-flex items-center justify-center rounded-lg border border-(--border) bg-(--surface-elevated) px-2.5 py-2 text-xs font-semibold text-(--text) transition hover:bg-(--surface-hover)"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              title={mounted ? (collapsed ? 'Expand' : 'Collapse') : undefined}
            >
              {collapsed ? '»' : '«'}
            </button>
          </div>
        </div>

        <nav className="space-y-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => {
                setActiveTab(item.id as TabKey)
                item.action()
                if (window.innerWidth < 768) setIsOpen(false)
              }}
              className={`group relative w-full rounded-xl ${collapsed ? 'px-2 py-2.5' : 'px-4 py-3'} text-left transition ${
                activeTab === item.id
                  ? 'border border-violet-400/60 bg-violet-500/10 shadow-lg shadow-violet-500/10'
                  : 'border border-(--border) bg-(--panel-2) hover:border-(--border-soft) hover:bg-(--surface-hover)'
              }`}
            >
              <div className="flex items-center justify-between">
                <div className={`flex items-center ${collapsed ? 'justify-center w-full' : 'gap-3'}`}>
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-lg border ${
                      activeTab === item.id
                        ? 'border-violet-500/20 bg-violet-500/10 text-violet-600'
                        : 'border-(--border) bg-(--surface-elevated) text-(--muted) group-hover:text-(--text)'
                    }`}
                  >
                    <Icon name={item.id} />
                  </span>
                  {!collapsed && <span className="font-medium text-(--text)">{item.label}</span>}
                </div>
                {!collapsed && item.count && (
                  <span className="rounded-full bg-violet-500/15 px-2 py-1 text-xs font-semibold text-violet-600 border border-violet-500/20">
                    {item.count}
                  </span>
                )}
              </div>
            </button>
          ))}
        </nav>

        {!collapsed && (
          <div className="mt-8 rounded-lg border border-(--border) bg-(--panel-2) p-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">Risk Snapshot</p>
              <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-2 py-0.5 text-[11px] font-medium text-(--muted)">
                {issuesCount} issues
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-(--muted)">
              <span>Critical</span>
              <span className="font-semibold text-red-500">
                {(issues.filter((i) => i.severity === 'BLOCKER' || i.severity === 'CRITICAL') || []).length}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between text-xs text-(--muted)">
              <span>Fixes</span>
              <span className="font-semibold text-(--accent-teal)">{fixesCount}</span>
            </div>
          </div>
        )}

        {!collapsed && (
          <div className="mt-10 rounded-lg border border-(--border) bg-(--panel-2) p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-(--accent-teal) animate-pulse" />
              <p className="text-xs font-semibold text-(--muted) uppercase tracking-wide">Live</p>
            </div>
            <div className="space-y-2 text-xs text-(--muted)">
              <p>
                Last sync: <span className="text-(--text) font-mono">{lastUpdated}</span>
              </p>
              <p>
                Status: <span className="text-(--accent-teal) font-medium">Connected</span>
              </p>
            </div>
          </div>
        )}
      </aside>
    </>
  )
}

export default Sidebar
