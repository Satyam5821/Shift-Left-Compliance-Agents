import { useMemo } from 'react'
import type { Issue } from '../types'

interface AnalyticsSectionProps {
  issues: Issue[]
}

const AnalyticsSection = ({ issues }: AnalyticsSectionProps) => {
  const severityData = useMemo(() => {
    const counts = { BLOCKER: 0, CRITICAL: 0, MAJOR: 0, MINOR: 0 }
    issues.forEach((issue) => {
      counts[issue.severity] = (counts[issue.severity] || 0) + 1
    })

    return [
      { name: 'Blocker', value: counts.BLOCKER, color: '#ef4444' },
      { name: 'Critical', value: counts.CRITICAL, color: '#f97316' },
      { name: 'Major', value: counts.MAJOR, color: '#eab308' },
      { name: 'Minor', value: counts.MINOR, color: '#22c55e' },
    ].filter((item) => item.value > 0)
  }, [issues])

  const totalIssues = issues.length
  const criticalCount = (issues.filter((i) => i.severity === 'BLOCKER' || i.severity === 'CRITICAL') || [])
    .length

  const totalValue = severityData.reduce((sum, item) => sum + item.value, 0)

  return (
    <div className="mt-8 rounded-lg border border-slate-700 bg-slate-800/40 p-4">
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wide text-slate-300">Analytics</h3>

      {/* Summary Stats */}
      <div className="mb-6 grid grid-cols-2 gap-3">
        <div className="rounded-lg bg-slate-900/50 p-3">
          <p className="text-xs text-slate-400">Total Issues</p>
          <p className="mt-1 text-2xl font-bold text-white">{totalIssues}</p>
        </div>
        <div className="rounded-lg bg-red-950/30 p-3">
          <p className="text-xs text-red-300">Critical</p>
          <p className="mt-1 text-2xl font-bold text-red-400">{criticalCount}</p>
        </div>
      </div>

      {/* Simple Bar Chart */}
      {severityData.length > 0 ? (
        <div className="space-y-3">
          {severityData.map((item) => {
            const percentage = totalValue > 0 ? (item.value / totalValue) * 100 : 0
            return (
              <div key={item.name} className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-400">{item.name}</span>
                  <span className="font-semibold text-slate-200">{item.value}</span>
                </div>
                <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{
                      width: `${percentage}%`,
                      backgroundColor: item.color,
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="h-32 flex items-center justify-center text-slate-400 text-sm">
          No issues to display
        </div>
      )}

      {/* Severity Breakdown List */}
      <div className="mt-4 space-y-2 border-t border-slate-700 pt-4">
        {severityData.map((item) => (
          <div key={item.name} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }}></div>
              <span className="text-xs text-slate-400">{item.name}</span>
            </div>
            <span className="font-semibold text-slate-200">{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AnalyticsSection
