import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import {
  TrendingUp, AlertTriangle, Clock, Award, Server, Download,
  BarChart2, RefreshCw, Shield, CheckCircle2, ChevronUp, ChevronDown
} from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend
} from "recharts";

// SLA Grade Colors
const GRADE_CONFIG = {
  A: { bg: "bg-green-500/10", border: "border-green-500/40", text: "text-green-400", label: "Excellent (≥99.9%)" },
  B: { bg: "bg-blue-500/10", border: "border-blue-500/40", text: "text-blue-400", label: "Good (≥99.0%)" },
  C: { bg: "bg-yellow-500/10", border: "border-yellow-500/40", text: "text-yellow-400", label: "Fair (≥95.0%)" },
  D: { bg: "bg-red-500/10", border: "border-red-500/40", text: "text-red-400", label: "Poor (<95.0%)" },
};

const PIE_COLORS = ["#22c55e", "#3b82f6", "#eab308", "#ef4444"];

// GitHub-style contribution heatmap cell
function HeatmapCell({ value, date, onClick }) {
  let color = "rgba(255,255,255,0.05)";
  if (value >= 99.9) color = "#166534";
  else if (value >= 99) color = "#15803d";
  else if (value >= 95) color = "#eab308";
  else if (value >= 90) color = "#f97316";
  else if (value > 0) color = "#ef4444";

  return (
    <div
      className="w-4 h-4 rounded-sm cursor-pointer transition-transform hover:scale-110"
      style={{ backgroundColor: color }}
      title={`${date}: ${value.toFixed(1)}%`}
      onClick={() => onClick && onClick(date)}
    />
  );
}

function UptimePill({ pct }) {
  const color = pct >= 99.9 ? "text-green-400" : pct >= 99 ? "text-blue-400" : pct >= 95 ? "text-yellow-400" : "text-red-400";
  return <span className={`font-mono font-bold text-sm ${color}`}>{pct.toFixed(2)}%</span>;
}

export default function SLAPage() {
  const [period, setPeriod] = useState("30d");
  const [summary, setSummary] = useState(null);
  const [devices, setDevices] = useState([]);
  const [heatmap, setHeatmap] = useState([]);
  const [weeklyData, setWeeklyData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [sortField, setSortField] = useState("uptime_pct");
  const [sortDir, setSortDir] = useState("asc");

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, devRes, hmRes, wkRes] = await Promise.all([
        api.get("/sla/summary", { params: { period } }),
        api.get("/sla/devices", { params: { period } }),
        api.get("/sla/heatmap", { params: { period } }),
        api.get("/sla/incidents-weekly"),
      ]);
      setSummary(sumRes.data);
      setDevices(devRes.data);
      setHeatmap(hmRes.data);
      setWeeklyData(wkRes.data);
    } catch (e) {
      console.error("SLA fetch error:", e);
    }
    setLoading(false);
  }, [period]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleExport = async () => {
    window.open(`${api.defaults.baseURL}/sla/export?period=${period}`, "_blank");
  };

  const handleSort = (field) => {
    if (sortField === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  };

  const sortedDevices = [...devices].sort((a, b) => {
    const av = a[sortField], bv = b[sortField];
    return sortDir === "asc" ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });

  // Grade distribution for Pie chart
  const gradeDist = ["A", "B", "C", "D"].map(g => ({
    name: `Grade ${g}`, value: devices.filter(d => d.grade === g).length
  })).filter(g => g.value > 0);

  if (loading && !summary) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const SortIcon = ({ field }) => {
    if (sortField !== field) return null;
    return sortDir === "asc" ? <ChevronUp className="w-3 h-3 inline ml-1" /> : <ChevronDown className="w-3 h-3 inline ml-1" />;
  };

  return (
    <div className="space-y-6 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <Shield className="w-6 h-6 text-blue-400" /> SLA & Uptime Monitor
          </h1>
          <p className="text-sm text-muted-foreground">Service Level Agreement reporting & analysis</p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={period} onValueChange={setPeriod}>
            <SelectTrigger className="w-32 rounded-sm bg-card text-xs h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7d">Last 7 Days</SelectItem>
              <SelectItem value="30d">Last 30 Days</SelectItem>
              <SelectItem value="90d">Last 90 Days</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" className="rounded-sm text-xs" onClick={handleExport}>
            <Download className="w-3.5 h-3.5 mr-1.5" /> Export CSV
          </Button>
          <Button variant="outline" size="icon" className="h-9 w-9 rounded-sm" onClick={fetchAll} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {[
            {
              label: "Avg Uptime", value: `${summary.avg_uptime_pct ?? 100}%`, sub: `${period} period`,
              icon: TrendingUp, color: "text-green-400", bg: "bg-green-500/10",
              accent: summary.avg_uptime_pct >= 99.9 ? "border-green-500/30" : summary.avg_uptime_pct >= 99 ? "border-blue-500/30" : "border-yellow-500/30"
            },
            {
              label: "Total Incidents", value: summary.total_incidents ?? 0, sub: "device outages",
              icon: AlertTriangle, color: "text-red-400", bg: "bg-red-500/10", accent: "border-red-500/20"
            },
            {
              label: "Avg MTTR", value: `${summary.mttr_minutes ?? 0}m`, sub: "mean time to recover",
              icon: Clock, color: "text-yellow-400", bg: "bg-yellow-500/10", accent: "border-yellow-500/20"
            },
            {
              label: "Top Performer", value: summary.top_performer?.name ?? "—", sub: summary.top_performer ? `${summary.top_performer.uptime_pct}% uptime` : "no data",
              icon: Award, color: "text-purple-400", bg: "bg-purple-500/10", accent: "border-purple-500/20"
            },
          ].map((c, i) => (
            <div key={i} className={`bg-card border ${c.accent || "border-border"} rounded-sm p-4`}>
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{c.label}</p>
                  <p className="text-xl font-bold font-['Rajdhani'] mt-1 truncate">{c.value}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{c.sub}</p>
                </div>
                <div className={`w-9 h-9 rounded-sm ${c.bg} flex items-center justify-center flex-shrink-0`}>
                  <c.icon className={`w-4.5 h-4.5 ${c.color}`} />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Heatmap */}
      <div className="bg-card border border-border rounded-sm p-5">
        <h3 className="text-base font-semibold font-['Rajdhani'] mb-4 flex items-center gap-2">
          <BarChart2 className="w-4 h-4 text-blue-400" /> Uptime Heatmap Calendar
          <span className="text-xs text-muted-foreground font-normal ml-1">— each cell = 1 day</span>
        </h3>
        {heatmap.length > 0 ? (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-1">
              {heatmap.map(h => (
                <HeatmapCell key={h.date} value={h.uptime_pct} date={h.date} />
              ))}
            </div>
            {/* Legend */}
            <div className="flex items-center gap-4 text-[10px] text-muted-foreground">
              <span>Less</span>
              {["rgba(255,255,255,0.05)", "#166534", "#15803d", "#eab308", "#f97316", "#ef4444"].map((c, i) => (
                <div key={i} className="w-3.5 h-3.5 rounded-sm" style={{ backgroundColor: c }} />
              ))}
              <span>More downtime</span>
              <span className="ml-4 flex items-center gap-1"><div className="w-3.5 h-3.5 rounded-sm bg-green-800" /> ≥99.9%</span>
              <span className="flex items-center gap-1"><div className="w-3.5 h-3.5 rounded-sm bg-yellow-500" /> 95–99%</span>
              <span className="flex items-center gap-1"><div className="w-3.5 h-3.5 rounded-sm bg-red-500" /> &lt;90%</span>
            </div>
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground">
            <BarChart2 className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No uptime data yet. Heatmap will populate as devices are monitored.</p>
          </div>
        )}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Grade Distribution Pie */}
        <div className="bg-card border border-border rounded-sm p-5">
          <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">SLA Grade Distribution</h3>
          {gradeDist.length > 0 ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={gradeDist} cx="50%" cy="50%" innerRadius={55} outerRadius={90} paddingAngle={3} dataKey="value">
                    {gradeDist.map((_, i) => <Cell key={i} fill={PIE_COLORS[i]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "#121214", border: "1px solid #27272a", borderRadius: "4px", fontSize: "12px" }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: "11px" }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-56 flex items-center justify-center text-muted-foreground text-sm">No grade data available</div>
          )}
        </div>

        {/* Weekly Incidents Bar */}
        <div className="bg-card border border-border rounded-sm p-5">
          <h3 className="text-base font-semibold font-['Rajdhani'] mb-4">Incidents Per Week (Last 12 Weeks)</h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weeklyData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                <XAxis dataKey="week" tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#121214", border: "1px solid #27272a", borderRadius: "4px", fontSize: "12px" }} />
                <Bar dataKey="count" fill="#ef4444" name="Incidents" radius={[2, 2, 0, 0]} maxBarSize={32} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Device SLA Table */}
      <div className="bg-card border border-border rounded-sm">
        <div className="px-5 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-base font-semibold font-['Rajdhani'] flex items-center gap-2">
            <Server className="w-4 h-4 text-muted-foreground" /> Device SLA Report
          </h3>
          <span className="text-xs text-muted-foreground">{devices.length} devices</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                {[
                  { key: "name", label: "Device" },
                  { key: "ip_address", label: "IP" },
                  { key: "status", label: "Status" },
                  { key: "uptime_pct", label: "Uptime %" },
                  { key: "downtime_hours", label: "Downtime" },
                  { key: "incident_count", label: "Incidents" },
                  { key: "mttr_minutes", label: "MTTR" },
                  { key: "grade", label: "Grade" },
                ].map(col => (
                  <th
                    key={col.key}
                    className="px-4 py-3 text-left text-[10px] uppercase tracking-wider text-muted-foreground cursor-pointer hover:text-foreground select-none"
                    onClick={() => handleSort(col.key)}
                  >
                    {col.label}<SortIcon field={col.key} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedDevices.length === 0 ? (
                <tr><td colSpan={8} className="px-4 py-8 text-center text-muted-foreground text-sm">No devices found</td></tr>
              ) : sortedDevices.map(d => {
                const gc = GRADE_CONFIG[d.grade] || GRADE_CONFIG.D;
                return (
                  <tr key={d.device_id} className="border-b border-border/40 hover:bg-secondary/30 transition-colors">
                    <td className="px-4 py-3 text-sm font-semibold">{d.name}</td>
                    <td className="px-4 py-3 text-xs font-mono text-muted-foreground">{d.ip_address}</td>
                    <td className="px-4 py-3">
                      <span className={`flex items-center gap-1.5 text-xs ${d.status === "online" ? "text-green-400" : "text-red-400"}`}>
                        <span className={`w-1.5 h-1.5 rounded-full ${d.status === "online" ? "bg-green-400" : "bg-red-400"}`} />
                        {d.status}
                      </span>
                    </td>
                    <td className="px-4 py-3"><UptimePill pct={d.uptime_pct} /></td>
                    <td className="px-4 py-3 text-xs font-mono text-muted-foreground">{d.downtime_hours}h</td>
                    <td className="px-4 py-3 text-xs text-center">{d.incident_count}</td>
                    <td className="px-4 py-3 text-xs font-mono text-muted-foreground">{d.mttr_minutes}m</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold border ${gc.bg} ${gc.border} ${gc.text}`}>
                        {d.grade}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
