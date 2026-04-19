import { useMemo } from "react";
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
} from "recharts";
import type { Fix, Issue, ScanStats, ScanWiseResponse } from "../types";

interface AnalyticsPanelProps {
  issues: Issue[];
  fixes: Fix[];
  lastUpdated: string;
  scanStats?: ScanStats | null;
  scanWise?: ScanWiseResponse | null;
  liveRefresh: boolean;
  onChangeLiveRefresh: (next: boolean) => void;
  range: string;
  onChangeRange: (next: string) => void;
  source: "current" | "history";
  onChangeSource: (next: "current" | "history") => void;
  onDrillDownToIssues: (filter: {
    severity?: Issue["severity"];
    status?: string;
    file?: string;
  }) => void;
}

const SEVERITY_META: Record<
  Issue["severity"],
  { label: string; color: string }
> = {
  BLOCKER: { label: "Blocker", color: "#ef4444" },
  CRITICAL: { label: "Critical", color: "#f97316" },
  MAJOR: { label: "Major", color: "#eab308" },
  MINOR: { label: "Minor", color: "#22c55e" },
};

const chartTooltipStyle = {
  background: "var(--chart-tooltip-bg)",
  border: "1px solid var(--chart-tooltip-border)",
  borderRadius: 12,
  color: "var(--text)",
} as const;

function toDayKey(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Unknown";
  return d.toISOString().slice(0, 10);
}

const AnalyticsPanel = ({
  issues,
  fixes,
  lastUpdated,
  scanStats,
  scanWise,
  liveRefresh,
  onChangeLiveRefresh,
  range,
  onChangeRange,
  source,
  onChangeSource,
  onDrillDownToIssues,
}: AnalyticsPanelProps) => {
  const severityCounts = useMemo(() => {
    const counts: Record<Issue["severity"], number> = {
      BLOCKER: 0,
      CRITICAL: 0,
      MAJOR: 0,
      MINOR: 0,
    };
    if (source === "history") {
      const src = scanWise?.charts?.severity_totals || {};
      counts.BLOCKER = Number((src as any).BLOCKER || 0);
      counts.CRITICAL = Number((src as any).CRITICAL || 0);
      counts.MAJOR = Number((src as any).MAJOR || 0);
      counts.MINOR = Number((src as any).MINOR || 0);
      return counts;
    }
    for (const issue of issues) counts[issue.severity] += 1;
    return counts;
  }, [issues, scanWise, source]);

  const severityData = useMemo(
    () =>
      (Object.keys(SEVERITY_META) as Issue["severity"][]).map((key) => ({
        key,
        name: SEVERITY_META[key].label,
        value: severityCounts[key],
        color: SEVERITY_META[key].color,
      })),
    [severityCounts],
  );

  const statusData = useMemo(() => {
    if (source === "history") return (scanWise?.charts?.apply_status || []).slice();
    const counts = new Map<string, number>();
    for (const issue of issues)
      counts.set(issue.status, (counts.get(issue.status) || 0) + 1);
    return Array.from(counts.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [issues, scanWise, source]);

  const fileHotspots = useMemo(() => {
    if (source === "history") return (scanWise?.charts?.file_hotspots || []).slice(0, 8);
    const counts = new Map<string, number>();
    for (const issue of issues) {
      const file = issue.file.split(":").slice(1).join(":") || issue.file;
      counts.set(file, (counts.get(file) || 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8);
  }, [issues, scanWise, source]);

  const trendData = useMemo(() => {
    if (source === "history") return (scanWise?.charts?.issue_trend || []).slice(-14);
    const counts = new Map<string, number>();
    for (const issue of issues) {
      const key = toDayKey(issue.created_at);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([day, count]) => ({ day, count }))
      .sort((a, b) => a.day.localeCompare(b.day))
      .slice(-14);
  }, [issues, scanWise, source]);

  const criticalTotal = severityCounts.BLOCKER + severityCounts.CRITICAL;

  const tickProps = { fill: "var(--chart-tick)", fontSize: 12 };

  const scanWiseStats = scanWise?.stats;
  const attempted =
    (scanWiseStats?.applied_total || 0) +
    (scanWiseStats?.skipped_total || 0) +
    (scanWiseStats?.errors_total || 0);
  const successPct =
    scanWiseStats?.success_rate != null
      ? Math.round(scanWiseStats.success_rate * 1000) / 10
      : null;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-(--muted)">
            Analytics
          </p>
          <p className="mt-1 text-xs text-(--muted)">
            Mode:{" "}
            <span
              className={
                liveRefresh
                  ? "text-(--accent-teal) font-semibold"
                  : "text-violet-300 font-semibold"
              }
            >
              {liveRefresh ? "Live" : "Sticky"}
            </span>
            <span className="text-(--muted)"> • </span>
            {liveRefresh
              ? "Refreshes on every tab switch"
              : "Uses last loaded data"}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)" htmlFor="analytics-source">
            Data
          </label>
          <select
            id="analytics-source"
            value={source}
            onChange={(e) => onChangeSource(e.target.value as "current" | "history")}
            className="rounded-lg border border-(--border) bg-(--panel-2) px-2 py-2 text-xs font-semibold text-(--text)"
            aria-label="Analytics data source"
          >
            <option value="current">Current issues (live)</option>
            <option value="history">Previous scans (history)</option>
          </select>

          <label
            className="text-[11px] font-semibold uppercase tracking-wider text-(--muted)"
            htmlFor="analytics-range"
          >
            Range
          </label>
          <select
            id="analytics-range"
            value={range}
            onChange={(e) => onChangeRange(e.target.value)}
            className="rounded-lg border border-(--border) bg-(--panel-2) px-2 py-2 text-xs font-semibold text-(--text)"
            aria-label="Analytics time range"
          >
            <option value="24h">Last 24h</option>
            <option value="7d">Last 7d</option>
            <option value="14d">Last 14d</option>
            <option value="30d">Last 30d</option>
          </select>

          <button
            type="button"
            onClick={() => onChangeLiveRefresh(!liveRefresh)}
            aria-pressed={liveRefresh}
            className={`inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition ${
              liveRefresh
                ? "border-teal-400/25 bg-teal-400/10 text-(--accent-teal) hover:bg-teal-400/15"
                : "border-violet-500/20 bg-violet-500/10 text-violet-200 hover:bg-violet-500/15"
            }`}
          >
            {liveRefresh ? "Live refresh: ON" : "Live refresh: OFF"}
          </button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            Total Issues
          </p>
          <p className="mt-2 text-3xl font-bold text-(--text)">
            {issues.length}
          </p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            Critical (B+C)
          </p>
          <p className="mt-2 text-3xl font-bold text-(--text)">
            {criticalTotal}
          </p>
          <p className="mt-2 text-xs text-(--muted)">Blocker + Critical</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            AI Fixes
          </p>
          <p className="mt-2 text-3xl font-bold text-(--text)">
            {fixes.length}
          </p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            Issues Resolved
          </p>
          <p className="mt-2 text-3xl font-bold text-(--accent-teal)">
            {scanStats?.issues_resolved ?? "—"}
          </p>
          <p className="mt-2 text-xs text-(--muted)">Applied across scans</p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            Success Rate
          </p>
          <p className="mt-2 text-3xl font-bold text-violet-300">
            {successPct != null ? `${successPct}%` : "—"}
          </p>
          <p className="mt-2 text-xs text-(--muted)">
            {attempted > 0
              ? `${attempted} attempted edits`
              : "No apply attempts"}
          </p>
        </div>
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
          <p className="text-xs font-medium uppercase tracking-wider text-(--muted)">
            Last Sync
          </p>
          <p className="mt-2 text-sm font-mono text-violet-500">
            {lastUpdated}
          </p>
          <p className="mt-2 text-xs text-(--muted)">Live tracking</p>
        </div>
      </div>

      <div className="rounded-lg border border-(--border) bg-(--panel-2) p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-(--text)">
              Scan-wise (commit-wise) activity
            </p>
            <p className="mt-1 text-xs text-(--muted)">
              Last <span className="font-mono">{range}</span> •{" "}
              {scanWiseStats?.scan_count ?? 0} scan(s)
            </p>
          </div>
          <div className="text-right text-xs text-(--muted)">
            <p>
              PRs merged:{" "}
              <span className="font-semibold text-violet-200">
                {scanWiseStats?.prs_merged ?? 0}
              </span>
            </p>
            <p>
              PRs created:{" "}
              <span className="font-semibold text-(--text)">
                {scanWiseStats?.prs_created ?? 0}
              </span>
            </p>
          </div>
        </div>

        {!scanWise || !scanWise.scans || scanWise.scans.length === 0 ? (
          <div className="mt-3 rounded-lg border border-dashed border-(--border-dashed) p-6 text-center text-xs text-(--muted)">
            No scan data in this range.
          </div>
        ) : (
          <div className="mt-3 overflow-auto">
            <table className="w-full min-w-[860px] border-collapse text-xs">
              <thead>
                <tr className="text-(--muted)">
                  <th className="px-2 py-2 text-left font-semibold">Scan</th>
                  <th className="px-2 py-2 text-left font-semibold">Repo</th>
                  <th className="px-2 py-2 text-left font-semibold">Created</th>
                  <th className="px-2 py-2 text-right font-semibold">
                    Applied
                  </th>
                  <th className="px-2 py-2 text-right font-semibold">
                    Skipped
                  </th>
                  <th className="px-2 py-2 text-right font-semibold">Errors</th>
                  <th className="px-2 py-2 text-left font-semibold">PR</th>
                  <th className="px-2 py-2 text-left font-semibold">Merged</th>
                </tr>
              </thead>
              <tbody>
                {scanWise.scans.slice(0, 50).map((s) => {
                  const c = (s.apply_counters || {}) as {
                    applied?: number;
                    skipped?: number;
                    errors?: number;
                  };
                  const applied = c.applied ?? 0;
                  const skipped = c.skipped ?? 0;
                  const errors = c.errors ?? 0;
                  return (
                    <tr key={s.scan_id} className="border-t border-(--border)">
                      <td className="px-2 py-2 font-mono text-(--text)">
                        {s.scan_id}
                      </td>
                      <td className="px-2 py-2 text-(--text)">
                        {s.repo || "—"}
                      </td>
                      <td className="px-2 py-2 font-mono text-(--muted)">
                        {s.created_at || "—"}
                      </td>
                      <td className="px-2 py-2 text-right font-semibold text-(--accent-teal)">
                        {applied}
                      </td>
                      <td className="px-2 py-2 text-right font-semibold text-amber-400">
                        {skipped}
                      </td>
                      <td className="px-2 py-2 text-right font-semibold text-rose-300">
                        {errors}
                      </td>
                      <td className="px-2 py-2">
                        {s.pr ? (
                          <a
                            className="text-violet-300 underline"
                            href={s.pr}
                            target="_blank"
                            rel="noreferrer"
                          >
                            PR
                          </a>
                        ) : (
                          <span className="text-(--muted)">—</span>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        {s.pr_merged === true ? (
                          <span className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 font-semibold text-emerald-200">
                            merged
                          </span>
                        ) : s.pr ? (
                          <span className="rounded-full border border-(--border) bg-(--surface-elevated) px-2 py-0.5 font-semibold text-(--text)">
                            open
                          </span>
                        ) : (
                          <span className="text-(--muted)">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">
                Severity Distribution
              </h3>
              <p className="mt-1 text-xs text-(--muted)">
                Where risk is concentrated
              </p>
            </div>
            <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-3 py-1 text-xs font-medium text-violet-600">
              By severity
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={severityData}
                  dataKey="value"
                  nameKey="name"
                  innerRadius={55}
                  outerRadius={85}
                  paddingAngle={2}
                  onClick={(data) => {
                    const key = (data as { key?: Issue["severity"] }).key;
                    if (key) onDrillDownToIssues({ severity: key });
                  }}
                >
                  {severityData.map((entry) => (
                    <Cell
                      key={entry.key}
                      fill={entry.color}
                      opacity={entry.value === 0 ? 0.2 : 1}
                    />
                  ))}
                </Pie>
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ color: "var(--text)" }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">
                Status Breakdown
              </h3>
              <p className="mt-1 text-xs text-(--muted)">
                {source === "history"
                  ? "Applied vs skipped vs errors (agent outcome)"
                  : "Open vs resolved (and any custom states)"}
              </p>
            </div>
            <span className="rounded-full border border-teal-400/20 bg-teal-400/10 px-3 py-1 text-xs font-medium text-(--accent-teal)">
              {source === "history" ? "By outcome" : "By status"}
            </span>
          </div>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={statusData}
                margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
              >
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                <XAxis
                  dataKey="name"
                  tick={tickProps}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis tick={tickProps} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Bar
                  dataKey="value"
                  name="Issues"
                  radius={[10, 10, 0, 0]}
                  fill="#8b5cf6"
                  onClick={(bar) => {
                    const status = (bar as { name?: string })?.name;
                    if (source === "current" && typeof status === "string")
                      onDrillDownToIssues({ status });
                  }}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">
                Top File Hotspots
              </h3>
              <p className="mt-1 text-xs text-(--muted)">
                {source === "history" ? "Most changed files (from fix metadata)" : "Most issues by file"}
              </p>
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
              {fileHotspots.map((row: { name: string; value: number }) => (
                <button
                  key={row.name}
                  type="button"
                  onClick={() => onDrillDownToIssues({ file: row.name })}
                  className="flex items-center justify-between rounded-lg border border-(--border) bg-(--surface-elevated) px-3 py-2"
                >
                  <p className="truncate pr-4 text-xs text-(--text)">
                    {row.name}
                  </p>
                  <span className="shrink-0 rounded-full bg-violet-500/10 px-2 py-0.5 text-xs font-semibold text-violet-600 border border-violet-500/20">
                    {row.value}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-(--border) bg-(--panel-2) p-5">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-(--text)">
                Issue Trend (Last 14 days)
              </h3>
              <p className="mt-1 text-xs text-(--muted)">
                {source === "history" ? "Issues per scan day (from scan snapshots)" : "Issues created per day"}
              </p>
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
                <BarChart
                  data={trendData}
                  margin={{ top: 8, right: 16, left: 0, bottom: 8 }}
                >
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis
                    dataKey="day"
                    tick={{ ...tickProps, fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={tickProps}
                    axisLine={false}
                    tickLine={false}
                    allowDecimals={false}
                  />
                  <Tooltip contentStyle={chartTooltipStyle} />
                  <Bar
                    dataKey="count"
                    name="Issues"
                    radius={[10, 10, 0, 0]}
                    fill="#2dd4bf"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default AnalyticsPanel;
