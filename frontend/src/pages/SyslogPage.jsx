import { useState, useEffect, useRef, useCallback } from "react";
import api from "@/lib/api";
import { Search, RefreshCw, Trash2, Filter, Activity, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const SEVERITY_COLORS = {
  emergency: "text-red-500 bg-red-500/10 border-red-500/20",
  alert: "text-red-500 bg-red-500/10 border-red-500/20",
  critical: "text-red-400 bg-red-400/10 border-red-400/20",
  error: "text-orange-400 bg-orange-400/10 border-orange-400/20",
  warning: "text-yellow-400 bg-yellow-400/10 border-yellow-400/20",
  notice: "text-blue-400 bg-blue-400/10 border-blue-400/20",
  info: "text-green-400 bg-green-400/10 border-green-400/20",
  debug: "text-muted-foreground bg-secondary/40 border-border",
};

const SEVERITY_LEVELS = ["all", "emergency", "alert", "critical", "error", "warning", "notice", "info", "debug"];

function formatTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("id-ID", { dateStyle: "short", timeStyle: "medium" });
  } catch { return iso; }
}

export default function SyslogPage() {
  const [entries, setEntries] = useState([]);
  const [sources, setSources] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [filters, setFilters] = useState({ source_ip: "", severity: "all", search: "", hours: "24" });
  const intervalRef = useRef(null);
  const logEndRef = useRef(null);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = { hours: parseInt(filters.hours), limit: 500 };
      if (filters.source_ip && filters.source_ip !== "all") params.source_ip = filters.source_ip;
      if (filters.severity !== "all") params.severity = filters.severity;
      if (filters.search) params.search = filters.search;
      const [entriesResp, statsResp, sourcesResp] = await Promise.all([
        api.get("/syslog/entries", { params }),
        api.get("/syslog/stats", { params: { hours: parseInt(filters.hours) } }),
        api.get("/syslog/sources"),
      ]);
      setEntries(entriesResp.data.reverse()); // Reverse: newest at bottom
      setStats(statsResp.data);
      setSources(sourcesResp.data);
    } catch (e) {
      console.error("Syslog fetch error:", e);
    }
    setLoading(false);
  }, [filters]);

  useEffect(() => { fetchEntries(); }, [fetchEntries]);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (autoRefresh) {
      intervalRef.current = setInterval(fetchEntries, 5000);
    }
    return () => clearInterval(intervalRef.current);
  }, [autoRefresh, fetchEntries]);

  // Auto-scroll to bottom on new entries
  useEffect(() => {
    if (autoRefresh) {
      logEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [entries, autoRefresh]);

  const handleClear = async () => {
    if (!window.confirm("Hapus semua log? Tindakan ini tidak dapat dibatalkan.")) return;
    try {
      await api.delete("/syslog/entries");
      setEntries([]);
      setStats(null);
    } catch (e) {
      console.error("Clear failed:", e);
    }
  };

  const exportCsv = () => {
    const header = "timestamp,source_ip,hostname,severity,message\n";
    const rows = entries.map(e =>
      `"${e.timestamp}","${e.source_ip}","${e.hostname}","${e.severity}","${(e.message || "").replace(/"/g, '""')}"`
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `syslog_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4 pb-16" data-testid="syslog-page">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Syslog</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">
            Log terpusat dari MikroTik devices
            {stats && <span className="ml-2 text-primary font-mono">{stats.total} entries</span>}
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button
            variant={autoRefresh ? "default" : "outline"} size="sm"
            onClick={() => setAutoRefresh(!autoRefresh)}
            className="rounded-sm gap-2 text-xs"
          >
            <Activity className={`w-3.5 h-3.5 ${autoRefresh ? "animate-pulse" : ""}`} />
            {autoRefresh ? "Live" : "Paused"}
          </Button>
          <Button variant="outline" size="sm" onClick={fetchEntries} disabled={loading} className="rounded-sm gap-2 text-xs">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={exportCsv} className="rounded-sm text-xs">CSV</Button>
          <Button variant="ghost" size="sm" onClick={handleClear} className="rounded-sm text-xs text-destructive">
            <Trash2 className="w-3.5 h-3.5 mr-1" /> Clear
          </Button>
        </div>
      </div>

      {/* Setup hint */}
      {entries.length === 0 && !loading && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-sm p-4 text-xs text-blue-300">
          <p className="font-semibold mb-1">💡 Cara konfigurasi MikroTik untuk kirim log ke sini:</p>
          <ol className="list-decimal ml-4 space-y-0.5 text-blue-300/80">
            <li>Buka Winbox → System → Logging → Actions → Add</li>
            <li>Type: <span className="font-mono bg-blue-500/20 px-1">remote</span>, Remote Address: <span className="font-mono bg-blue-500/20 px-1">{window.location.hostname}</span>, Remote Port: <span className="font-mono bg-blue-500/20 px-1">{stats?.port || 5140}</span></li>
            <li>Di tab Rules, tambahkan rule dengan Action ke actions yang sudah dibuat</li>
          </ol>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-2 flex-wrap">
        <Select value={filters.source_ip || "all"} onValueChange={v => setFilters(f => ({ ...f, source_ip: v === "all" ? "" : v }))}>
          <SelectTrigger className="w-full sm:w-40 rounded-sm bg-card text-xs h-8">
            <SelectValue placeholder="Semua Device" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Semua Device</SelectItem>
            {sources.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filters.severity} onValueChange={v => setFilters(f => ({ ...f, severity: v }))}>
          <SelectTrigger className="w-full sm:w-32 rounded-sm bg-card text-xs h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SEVERITY_LEVELS.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={filters.hours} onValueChange={v => setFilters(f => ({ ...f, hours: v }))}>
          <SelectTrigger className="w-full sm:w-28 rounded-sm bg-card text-xs h-8">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="1">1 Jam</SelectItem>
            <SelectItem value="6">6 Jam</SelectItem>
            <SelectItem value="24">24 Jam</SelectItem>
            <SelectItem value="168">7 Hari</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative flex-1 min-w-40">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Filter pesan..."
            value={filters.search}
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
            className="pl-8 rounded-sm bg-card h-8 text-xs"
          />
        </div>
      </div>

      {/* Log Terminal */}
      <div className="bg-card border border-border rounded-sm">
        <div className="px-3 py-2 border-b border-border flex items-center gap-2">
          <Terminal className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground font-mono">{entries.length} entries</span>
          {autoRefresh && <span className="text-xs text-green-500 animate-pulse">● live</span>}
        </div>
        <div className="h-[500px] overflow-y-auto font-mono text-[11px] p-2 space-y-0.5" id="syslog-container">
          {loading && entries.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">Memuat log...</div>
          ) : entries.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">Tidak ada log untuk filter yang dipilih</div>
          ) : entries.map((e, i) => (
            <div key={i} className="flex items-start gap-2 py-0.5 hover:bg-secondary/20 rounded px-1 group">
              <span className="text-muted-foreground/60 flex-shrink-0 w-32 hidden sm:block">{formatTime(e.timestamp)}</span>
              <span className="text-muted-foreground/50 flex-shrink-0 w-20 truncate hidden sm:block">{e.source_ip}</span>
              <Badge className={`rounded-sm text-[9px] px-1 py-0 border flex-shrink-0 capitalize ${SEVERITY_COLORS[e.severity] || "text-muted-foreground border-border"}`}>
                {e.severity?.slice(0, 4)}
              </Badge>
              <span className="text-foreground/80 flex-1 break-all leading-relaxed">{e.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}
