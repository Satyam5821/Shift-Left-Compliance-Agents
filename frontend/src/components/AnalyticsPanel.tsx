import { useMemo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Fix, Issue } from '../types'

interface AnalyticsPanelProps {
  issues: Issue[]
  fixes: Fix[]
  lastUpdated: string
}

const SEVERITY_META: Record<Issue['severity'], { label: string; color: string }> = {
  BLOCKER: { label: 'Blocker', color: '#ef4444' },
  CRITICAL: { label: 'Critical', color: '#f97316' },
  MAJOR: { label: 'Major', color: '#eab308' },
  MINOR: { label: 'Minor', color: '#22c55e' },
}

const chartTooltipStyle = {
  background: 'var(--chart-tooltip-bg)',
  border: '1px solid var(--chart-tooltip-border)',
  borderRadius: 12,
  color: 'var(--text)',
} as const

function toDayKey(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'Unknown'
  return d.toISOString().slice(0, 10)
}

const AnalyticsPanel = ({ issues, fixes, lastUpdated }: AnalyticsPanelProps) => {
  const severityCounts = useMemo(() => {
    const counts: Record<Issue['severity'], number> = { BLOCKER: 0, CRITICAL: 0, MAJOR: 0, MINOR: 0 }
    for (const issue of issues) counts[issue.severity] += 1
    return counts
  }, [issues])

  const severityData = useMemo(
    () =>
      (Object.keys(SEVERITY_META) as Issue['severity'][]).map((key) => ({
        key,
        name: SEVERITY_META[key].label,
        value: severityCounts[key],
        color: SEVERITY_META[key].color,
      })),
    [severityCounts],
  )

  const statusData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const issue of issues) counts.set(issue.status, (counts.get(issue.status) || 0) + 1)
    return Array.from(counts.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
  }, [issues])

  const fileHotspots = useMemo(() => {
    const counts = new Map<string, number>()
    for (const issue of issues) {
      const file = issue.file.split(':').slice(1).join(':') || issue.file
      counts.set(file, (counts.get(file) || 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8)
  }, [issues])

  const trendData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const issue of issues) {
      const key = toDayKey(issue.created_at)
      counts.set(key, (counts.get(key) || 0) + 1)
    }
    return Array.from(counts.entries())
      .map(([day, count]) => ({ day, count }))
      .sort((a, b) => a.day.localeCompare(b.day))
      .slice(-14)
  }, [issues])

  const criticalTotal = severityCounts.BLOCKER + severityCounts.CRITICAL

  const tickProps = { fill: 'var(--chart-tick)', fontSize: 12 }

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Total Issues</p>
          <p className="mt-2 text-3xl font-bold text-(--text)">{issues.length}</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Critical (B+C)</p>
          <p className="mt-2 text-3xl font-bold text-(--text)">{criticalTotal}</p>
          <p className="mt-2 text-xs text-(--muted)">Blocker + Critical</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">AI Fixes</p>
          <p className="mt-2 text-3xl font-bold text-(--text)">{fixes.length}</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">Last Sync</p>
          <p className="mt-2 text-sm font-mono text-violet-500">{lastUpdated}</p>
          <p className="mt-2 text-xs text-(--muted)">Live tracking</p>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">Severity Distribution</h3>
              <p className="mt-1 text-xs text-(--muted)">Where risk is concentrated</p>
            </div>
            <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-600">
              By severity
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={severityData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
                  {severityData.map((entry) => (
                    <Cell key={entry.key} fill={entry.color} opacity={entry.value === 0 ? 0.2 : 1} />
                  ))}
                </Pie>
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ color: 'var(--text)' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">Status Breakdown</h3>
              <p className="mt-1 text-xs text-(--muted)">Open vs resolved (and any custom states)</p>
            </div>
            <span className="rounded-full border border-teal-400/20 bg-teal-400/10 px-3 py-1 text-xs font-medium text-(--accent-teal)">
              By status
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis dataKey="name" tick={tickProps} axisLine={false} tickLine={false} />
                <YAxis tick={tickProps} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Bar dataKey="value" name="Issues" radius={[10, 10, 0, 0]} fill="#8b5cf6" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">Top File Hotspots</h3>
              <p className="mt-1 text-xs text-(--muted)">Most issues by file</p>
            </div>
            <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-3 py-1 text-xs font-medium text-(--text)">
              Top {fileHotspots.length || 0}
            </span>
          </div>

          {fileHotspots.length === 0 ? (
            <div className="rounded-lg border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
              No hotspot data yet.
            </div>
          ) : (
            <div className="space-y-2">
              {fileHotspots.map((row) => (
                <div
                  key={row.name}
                  className="flex items-center justify-between rounded-lg border border-(--border) bg-(--surface-elevated) px-3 py-2"
                >
                  <p className="truncate pr-4 text-xs text-(--text)">{row.name}</p>
                  <span className="shrink-0 rounded-full bg-violet-500/10 px-2 py-0.5 text-xs font-semibold text-violet-600 border border-violet-500/20">
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">Issue Trend (Last 14 days)</h3>
              <p className="mt-1 text-xs text-(--muted)">Issues created per day</p>
            </div>
            <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-3 py-1 text-xs font-medium text-(--text)">
              Daily
            </span>
          </div>

          {trendData.length === 0 ? (
            <div className="rounded-lg border border-dashed border-(--border-dashed) p-8 text-center text-(--muted)">
              No trend data yet.
            </div>
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={trendData} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis dataKey="day" tick={{ ...tickProps, fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={tickProps} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Bar dataKey="count" name="Issues" radius={[10, 10, 0, 0]} fill="#2dd4bf" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default AnalyticsPanel
