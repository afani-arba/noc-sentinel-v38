import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import useDeviceEvents from "@/hooks/useDeviceEvents";
import {
  Server, ArrowDown, ArrowUp, Cpu, HardDrive, Activity, Monitor, Network,
  AlertTriangle, AlertCircle, Info, CheckCircle2, RefreshCw, Thermometer, Zap, Battery,
  Layers, CircuitBoard, Radio, GitCompare, Wifi, TrendingUp
} from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, BarChart, Bar, Cell
} from "recharts";

const alertIcons = { warning: AlertTriangle, error: AlertCircle, info: Info, success: CheckCircle2 };
const alertColors = { warning: "text-yellow-500", error: "text-red-500", info: "text-blue-500", success: "text-green-500" };
const ttStyle = { contentStyle: { backgroundColor: "#121214", borderColor: "#27272a", borderRadius: "4px", color: "#fafafa", fontSize: "12px", fontFamily: "'JetBrains Mono', monospace" } };

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("all");
  const [interfaces, setInterfaces] = useState(["all"]);
  const [selectedInterface, setSelectedInterface] = useState("all");
  const [loading, setLoading] = useState(true);
  const [sysResource, setSysResource] = useState(null);
  // Traffic history filter
  const [trafficRange, setTrafficRange] = useState("24h");
  const [dateFilter, setDateFilter] = useState("");
  const [trafficData, setTrafficData] = useState(null); // null = use stats.traffic_data
  const [loadingTraffic, setLoadingTraffic] = useState(false);
  // v3 — Top Talkers
  const [topTalkers, setTopTalkers] = useState([]);
  const [topTalkersRange, setTopTalkersRange] = useState("1h");
  // v4 — ISP Multi-series
  const [ispSeries, setIspSeries]   = useState([]);  // [{name, data:[{time,download,upload}]}]
  const [ispRange, setIspRange]   = useState("24h");
  const [ispInterfaceList, setIspInterfaceList] = useState([]); // daftar ISP ifaces terdeteksi
  // v4 — Historical Comparison
  const [compareData, setCompareData] = useState(null); // {current, previous, anomalies}
  const [comparePeriod, setComparePeriod] = useState("week");
  const [showCompare, setShowCompare] = useState(false);

  // ━━━ SSE Real-time ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const { devices: sseDevices, summary: sseSummary, connected: sseConnected, lastUpdate: sseLastUpdate } = useDeviceEvents();

  // Merge SSE data into stats summary ketika SSE aktif
  useEffect(() => {
    if (sseConnected && sseSummary && sseSummary.total > 0) {
      setStats(prev => {
        if (!prev) return prev;
        return {
          ...prev,
          total_devices: sseSummary.total,
          online_devices: sseSummary.online,
          offline_devices: sseSummary.offline,
        };
      });
    }
  }, [sseConnected, sseSummary]);
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  useEffect(() => {
    api.get("/devices").then(r => {
      setDevices(r.data);
      // Set first device as default if available
      if (r.data.length > 0) {
        setSelectedDevice(r.data[0].id);
      }
    }).catch(() => { });
  }, []);

  useEffect(() => {
    if (selectedDevice === "all") { setInterfaces(["all"]); setSelectedInterface("all"); setSysResource(null); return; }
    api.get("/dashboard/interfaces", { params: { device_id: selectedDevice } })
      .then(r => {
        // New format: {interfaces: [...], isp_interfaces: [...]}
        // Old format (fallback): plain array
        const raw = r.data;
        const ifaceList = Array.isArray(raw) ? raw : (raw?.interfaces || ["all"]);
        const ispList   = Array.isArray(raw) ? [] : (raw?.isp_interfaces || []);
        setInterfaces(ifaceList);
        setIspInterfaceList(ispList);
        // Default ke "all" agar backend menampilkan akumulasi semua ISP interface
        // (backend ISP-aware: jika ada isp_bandwidth → sum semua ISP; jika tidak → sum semua interface)
        setSelectedInterface("all");
      }).catch(() => { setInterfaces(["all"]); setSelectedInterface("all"); setIspInterfaceList([]); });
    // Fetch system resource info (board name, architecture, ROS version, etc.)
    api.get(`/devices/${selectedDevice}/system-resource`)
      .then(r => { if (!r.data.error) setSysResource(r.data); else setSysResource(null); })
      .catch(() => setSysResource(null));
  }, [selectedDevice]);

  const fetchStats = useCallback(async () => {
    try {
      const params = {};
      if (selectedDevice !== "all") params.device_id = selectedDevice;
      if (selectedInterface !== "all") params.interface = selectedInterface;
      const r = await api.get("/dashboard/stats", { params });
      const data = r.data;

      // Pastikan system_health selalu ada
      if (!data.system_health) {
        data.system_health = { cpu: 0, memory: 0, cpu_temp: 0, board_temp: 0, voltage: 0, power: 0 };
      }

      // Fetch extended health metrics jika device spesifik dipilih
      if (selectedDevice !== "all") {
        try {
          const hr = await api.get(`/devices/${selectedDevice}/system-health`);
          if (hr.data && Object.keys(hr.data).length > 0) {
            const rd = hr.data;
            const h = data.system_health;
            // Gunakan nilai terbesar (non-zero) dari kedua sumber
            // Ini mencegah nilai 0 dari satu sumber menimpa nilai valid dari sumber lain
            const pick = (a, b) => (Number(a) > 0 ? Number(a) : Number(b) > 0 ? Number(b) : 0);
            data.system_health = {
              ...h,
              cpu_temp:    pick(rd.cpu_temp,    h.cpu_temp),
              board_temp:  pick(rd.board_temp,  h.board_temp),
              sfp_temp:    pick(rd.sfp_temp,    h.sfp_temp || 0),
              switch_temp: pick(rd.switch_temp, h.switch_temp || 0),
              voltage:     pick(rd.voltage,     h.voltage),
              power:       pick(rd.power,       h.power),
              fans:        rd.fans       || h.fans       || {},
              fan_state:   rd.fan_state  || h.fan_state  || "",
              psu:         rd.psu        || h.psu        || {},
              extra_temps: rd.extra_temps || h.extra_temps || {},
            };
          }
        } catch (_) {
          // Health fetch gagal — tetap gunakan data dari stats
          const h = data.system_health;
          data.system_health = { ...h, fans: {}, fan_state: "", psu: {}, extra_temps: {} };
        }
      }

      setStats(data);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [selectedDevice, selectedInterface]);

  const fetchTrafficHistory = useCallback(async () => {
    // BUG 5 FIX: sebelumnya "24h" di-bypass dan tidak fetch dari traffic-history
    // Sekarang SEMUA range (1h, 12h, 24h, week, month) fetch dari endpoint yang benar
    setLoadingTraffic(true);
    try {
      const params = { range: trafficRange };
      if (selectedDevice !== "all") params.device_id = selectedDevice;
      if (selectedInterface !== "all") params.interface = selectedInterface;
      if (dateFilter) params.date = dateFilter;
      const r = await api.get("/dashboard/traffic-history", { params });
      setTrafficData(r.data.length > 0 ? r.data : null);
    } catch {
      setTrafficData(null);
    }
    setLoadingTraffic(false);
  }, [trafficRange, dateFilter, selectedDevice, selectedInterface]);


  useEffect(() => {
    fetchStats();
    const iv = setInterval(fetchStats, 30000);
    return () => clearInterval(iv);
  }, [fetchStats]);

  useEffect(() => { fetchTrafficHistory(); }, [fetchTrafficHistory]);

  // v3 — Top Talkers
  useEffect(() => {
    api.get("/dashboard/top-talkers", { params: { range: topTalkersRange, limit: 10 } })
      .then(r => setTopTalkers(r.data || []))
      .catch(() => setTopTalkers([]));
  }, [topTalkersRange]);

  // v4 — ISP Multi-series chart
  useEffect(() => {
    if (!selectedDevice || selectedDevice === "all") { setIspSeries([]); return; }
    api.get("/dashboard/isp-traffic-history", { params: { device_id: selectedDevice, range: ispRange } })
      .then(r => setIspSeries(r.data?.series || []))
      .catch(() => setIspSeries([]));
  }, [selectedDevice, ispRange]);

  // v4 — Historical Comparison
  useEffect(() => {
    if (!showCompare) return;
    const params = { period: comparePeriod };
    if (selectedDevice && selectedDevice !== "all") params.device_id = selectedDevice;
    api.get("/dashboard/traffic-compare", { params })
      .then(r => setCompareData(r.data))
      .catch(() => setCompareData(null));
  }, [showCompare, comparePeriod, selectedDevice]);

  if (loading && !stats) return <div className="flex items-center justify-center h-64" data-testid="dashboard-loading"><span className="text-muted-foreground text-sm">Loading dashboard...</span></div>;
  if (!stats) return null;

  const td = trafficData ?? (stats?.traffic_data || []);
  // Defensive aliases — prevent TypeError when API returns partial data
  const health = stats.system_health || {};
  const devStat = stats.devices || { online: 0, total: 0 };
  const bw = stats.total_bandwidth || { download: 0, upload: 0 };
  // Calculate averages only from non-zero values
  const pingValues = td.filter(d => d.ping > 0).map(d => d.ping);
  const jitterValues = td.filter(d => d.jitter > 0).map(d => d.jitter);
  const avgPing = pingValues.length ? Math.round(pingValues.reduce((s, v) => s + v, 0) / pingValues.length) : 0;
  const avgJitter = jitterValues.length ? (jitterValues.reduce((s, v) => s + v, 0) / jitterValues.length).toFixed(1) : "0";
  const sd = stats.selected_device;
  const noData = td.length === 0;

  return (
    <div className="space-y-4 pb-16" data-testid="dashboard-page">
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Dashboard</h1>
            <p className="text-xs sm:text-sm text-muted-foreground">Real-time network monitoring</p>
          </div>
          {/* SSE Live / Polling badge */}
          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-sm border text-[10px] font-mono font-semibold transition-all ${
            sseConnected
              ? "bg-green-500/10 border-green-500/20 text-green-400"
              : "bg-secondary/30 border-border text-muted-foreground"
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${
              sseConnected ? "bg-green-500 animate-pulse" : "bg-muted-foreground"
            }`} />
            {sseConnected ? (
              <>
                <Radio className="w-2.5 h-2.5" />
                LIVE {sseLastUpdate ? `· ${new Date(sseLastUpdate).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}
              </>
            ) : (
              <>POLLING · 30s</>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:flex sm:flex-row gap-2 sm:gap-3 sm:items-end">
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1"><Monitor className="w-3 h-3" /> Device</label>
            <Select value={selectedDevice} onValueChange={setSelectedDevice}>
              <SelectTrigger className="w-full sm:w-44 rounded-sm bg-card text-xs h-9" data-testid="dashboard-device-select"><SelectValue placeholder="All Devices" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all"><span className="flex items-center gap-2"><Server className="w-3 h-3 text-muted-foreground" /> All Devices</span></SelectItem>
                {devices.map(d => (
                  <SelectItem key={d.id} value={d.id}><span className="flex items-center gap-2"><div className={`w-1.5 h-1.5 rounded-full ${d.status === "online" ? "bg-green-500" : "bg-red-500"}`} /><span className="font-mono text-xs">{d.name}</span></span></SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest flex items-center gap-1"><Network className="w-3 h-3" /> Interface
            </label>
            <div className="flex gap-1">
              <Select value={selectedInterface} onValueChange={setSelectedInterface}>
                <SelectTrigger className="w-full sm:w-32 rounded-sm bg-card text-xs h-9" data-testid="dashboard-interface-select"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {interfaces.map(i => <SelectItem key={i} value={i}><span className="font-mono text-xs">{i === "all" ? "All Interfaces" : i}</span></SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      </div>

      {sd && (
        <div className="flex flex-wrap items-center gap-2 sm:gap-4 px-3 py-2 bg-card border border-border rounded-sm text-[10px] sm:text-xs animate-fade-in" data-testid="device-info-bar">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${sd.status === "online" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
          <span className="font-semibold truncate max-w-[100px] sm:max-w-none">{sd.identity || sd.name}</span>
          <span className="text-muted-foreground font-mono hidden sm:inline">{sd.ip_address}</span>
          {sd.ros_version && <Badge variant="outline" className="rounded-sm text-[10px]">v{sd.ros_version}</Badge>}
          {sd.uptime && <span className="text-muted-foreground hidden sm:inline">Up: <span className="font-mono text-foreground">{sd.uptime}</span></span>}
        </div>
      )}

      {/* System Resource Info Panel */}
      {sysResource && selectedDevice !== "all" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {[
            { label: "Architecture", value: sysResource.architecture_name || "—", icon: Layers },
            { label: "Board Name", value: sysResource.board_name || "—", icon: CircuitBoard },
            { label: "ROS Version", value: sysResource.version || "—", icon: Monitor },
            { label: "Build Time", value: sysResource.build_time ? sysResource.build_time.slice(0, 10) : "—", icon: Activity },
            { label: "CPU Count", value: sysResource.cpu_count > 0 ? `${sysResource.cpu_count}` : "—", icon: Cpu },
            { label: "CPU Frequency", value: sysResource.cpu_frequency > 0 ? `${sysResource.cpu_frequency} MHz` : "—", icon: Zap },
          ].map((item) => (
            <div key={item.label} className="bg-card border border-border rounded-sm p-2.5 flex items-center gap-2">
              <item.icon className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
              <div className="min-w-0">
                <p className="text-[9px] text-muted-foreground uppercase tracking-wider">{item.label}</p>
                <p className="text-xs font-mono font-semibold truncate" title={item.value}>{item.value}</p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          { label: "Devices", value: `${devStat.online ?? 0}/${devStat.total ?? 0}`, sub: "online/total", icon: Server, color: "text-purple-500", bg: "bg-purple-500/10" },
          { label: "Download", value: `${bw.download ?? 0}`, sub: "Mbps", icon: ArrowDown, color: "text-blue-500", bg: "bg-blue-500/10" },
          { label: "Upload", value: `${bw.upload ?? 0}`, sub: "Mbps", icon: ArrowUp, color: "text-green-500", bg: "bg-green-500/10" },
          { label: "Avg Ping", value: `${avgPing}`, sub: "ms", icon: Activity, color: "text-cyan-500", bg: "bg-cyan-500/10" },
          { label: "Avg Jitter", value: avgJitter, sub: "ms", icon: Activity, color: "text-rose-500", bg: "bg-rose-500/10" },
        ].map((c, i) => (
          <div key={c.label} className="bg-card border border-border rounded-sm p-3 sm:p-4 opacity-0 animate-slide-up" style={{ animationDelay: `${i * 0.04}s`, animationFillMode: 'forwards' }} data-testid={`stat-card-${c.label.toLowerCase().replace(/\s/g, '-')}`}>
            <div className="flex items-start justify-between">
              <div><p className="text-[9px] sm:text-[10px] text-muted-foreground uppercase tracking-wider">{c.label}</p><p className="text-lg sm:text-xl font-bold font-['Rajdhani'] mt-0.5 sm:mt-1">{c.value} <span className="text-xs sm:text-sm font-normal text-muted-foreground">{c.sub}</span></p></div>
              <div className={`w-7 h-7 sm:w-8 sm:h-8 rounded-sm ${c.bg} flex items-center justify-center`}><c.icon className={`w-3.5 h-3.5 sm:w-4 sm:h-4 ${c.color}`} /></div>
            </div>
          </div>
        ))}
      </div>

      {noData && devices.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">No devices configured</p><p className="text-xs text-muted-foreground mt-1">Add a MikroTik device in the Devices page to start monitoring</p></div>
      ) : noData ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center"><Activity className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" /><p className="text-muted-foreground">Waiting for data...</p><p className="text-xs text-muted-foreground mt-1">SNMP polling runs every 30 seconds. Traffic data will appear after 2 polling cycles.</p></div>
      ) : (
        <>
          {/* Traffic Chart */}
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="traffic-chart">
            <div className="flex items-center justify-between mb-3 sm:mb-4">
              <div className="flex items-center gap-2">
                <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani']">Traffic History</h3>
                {/* Badge ISP-accumulated mode */}
                {selectedInterface === "all" && ispInterfaceList.length > 0 && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-sm bg-blue-500/10 border border-blue-500/20 text-blue-400 font-mono hidden sm:inline">
                    ISP ×{ispInterfaceList.length} accumulated
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                {loadingTraffic && <RefreshCw className="w-3 h-3 animate-spin" />}
                <span className="font-mono">{td.length} samples</span>
              </div>
            </div>
            <div className="h-48 sm:h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={td}>
                  <defs>
                    <linearGradient id="gDl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} /><stop offset="95%" stopColor="#3b82f6" stopOpacity={0} /></linearGradient>
                    <linearGradient id="gUl" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.3} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} /></linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} /><YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} width={40} /><Tooltip {...ttStyle} />
                  <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#gDl)" strokeWidth={2} name="Download (Mbps)" />
                  <Area type="monotone" dataKey="upload" stroke="#10b981" fill="url(#gUl)" strokeWidth={2} name="Upload (Mbps)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="flex items-center gap-4 sm:gap-6 mt-2 sm:mt-3 text-[10px] sm:text-xs text-muted-foreground">
              <div className="flex items-center gap-1 sm:gap-2"><div className="w-3 h-[2px] bg-blue-500" /><ArrowDown className="w-3 h-3" /> Download</div>
              <div className="flex items-center gap-1 sm:gap-2"><div className="w-3 h-[2px] bg-green-500" /><ArrowUp className="w-3 h-3" /> Upload</div>
            </div>
          </div>

          {/* Ping & Jitter */}
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="ping-jitter-chart">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-3 sm:mb-4 gap-2">
              <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani']">Ping & Jitter</h3>
              <div className="flex items-center gap-2 sm:gap-3 text-[10px] sm:text-xs">
                <div className="flex items-center gap-1 sm:gap-2 px-2 py-1 rounded-sm bg-cyan-500/10 border border-cyan-500/20"><span className="text-cyan-400">Ping:</span><span className="font-mono text-cyan-300 font-semibold">{avgPing} ms</span></div>
                <div className="flex items-center gap-1 sm:gap-2 px-2 py-1 rounded-sm bg-rose-500/10 border border-rose-500/20"><span className="text-rose-400">Jitter:</span><span className="font-mono text-rose-300 font-semibold">{avgJitter} ms</span></div>
              </div>
            </div>
            {avgPing === 0 && avgJitter === "0" ? (
              <div className="h-48 flex items-center justify-center bg-secondary/20 rounded-sm border border-dashed border-border">
                <div className="text-center">
                  <Activity className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
                  <p className="text-sm text-muted-foreground">Ping data tidak tersedia</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">Server monitoring tidak dapat menjangkau IP device via ICMP.<br />Pastikan firewall MikroTik mengizinkan ICMP dari server monitoring.</p>
                </div>
              </div>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={td}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" /><XAxis dataKey="time" tick={{ fill: "#a1a1aa", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#27272a" }} /><YAxis tick={{ fill: "#a1a1aa", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "#27272a" }} domain={[0, 'auto']} /><Tooltip {...ttStyle} />
                    <Legend iconType="line" wrapperStyle={{ fontSize: "11px", color: "#a1a1aa" }} />
                    <Line type="monotone" dataKey="ping" stroke="#06b6d4" strokeWidth={2} dot={false} name="Ping (ms)" />
                    <Line type="monotone" dataKey="jitter" stroke="#f43f5e" strokeWidth={2} dot={false} strokeDasharray="5 3" name="Jitter (ms)" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* ── ISP Multi-series Chart (hanya jika device spesifik & ada multi-ISP) ── */}
          {ispSeries.length > 1 && selectedDevice !== "all" && (
            <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="isp-multi-chart">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-3 sm:mb-4 gap-2">
                <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani'] flex items-center gap-2">
                  <Wifi className="w-4 h-4 text-violet-400" />
                  ISP per-Interface
                  <span className="text-xs text-muted-foreground font-normal">— multi-ISP comparison</span>
                </h3>
                <div className="flex gap-1">
                  {["1h", "12h", "24h", "week"].map(r => (
                    <button key={r} onClick={() => setIspRange(r)}
                      className={`text-[10px] px-2 py-1 rounded-sm border transition-colors ${
                        ispRange === r ? "bg-violet-600 text-white border-violet-600" : "border-border text-muted-foreground hover:border-violet-500/50"
                      }`}>{r}</button>
                  ))}
                </div>
              </div>
              {/* Download chart */}
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">Download (Mbps)</p>
              <div className="h-36 sm:h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="time" type="category" allowDuplicatedCategory={false} tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                    <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} width={40} />
                    <Tooltip {...ttStyle} />
                    <Legend iconType="line" wrapperStyle={{ fontSize: "11px", color: "#a1a1aa" }} />
                    {ispSeries.map((s, i) => {
                      const colors = ["#8b5cf6","#06b6d4","#f59e0b","#10b981","#f43f5e","#3b82f6","#ec4899","#84cc16"];
                      return (
                        <Line key={s.name} data={s.data} type="monotone" dataKey="download"
                          stroke={colors[i % colors.length]} strokeWidth={2} dot={false}
                          name={`${s.name} ↓`} />
                      );
                    })}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {/* Upload chart */}
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1 mt-3">Upload (Mbps)</p>
              <div className="h-36 sm:h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="time" type="category" allowDuplicatedCategory={false} tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                    <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} width={40} />
                    <Tooltip {...ttStyle} />
                    <Legend iconType="line" wrapperStyle={{ fontSize: "11px", color: "#a1a1aa" }} />
                    {ispSeries.map((s, i) => {
                      const colors = ["#8b5cf6","#06b6d4","#f59e0b","#10b981","#f43f5e","#3b82f6","#ec4899","#84cc16"];
                      return (
                        <Line key={s.name} data={s.data} type="monotone" dataKey="upload"
                          stroke={colors[i % colors.length]} strokeWidth={2} dot={false} strokeDasharray="5 3"
                          name={`${s.name} ↑`} />
                      );
                    })}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* ── Historical Comparison Panel ────────────────────────── */}
          <div className="bg-card border border-border rounded-sm p-3 sm:p-5" data-testid="historical-compare">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-3 gap-2">
              <h3 className="text-base sm:text-lg font-semibold font-['Rajdhani'] flex items-center gap-2">
                <GitCompare className="w-4 h-4 text-amber-400" />
                Perbandingan Historis
                <span className="text-xs text-muted-foreground font-normal">— today vs sebelumnya</span>
              </h3>
              <div className="flex items-center gap-2">
                <div className="flex gap-1">
                  {[["week","vs 7hr lalu"],["month","vs 30hr lalu"]].map(([p,lbl]) => (
                    <button key={p} onClick={() => { setComparePeriod(p); setShowCompare(true); }}
                      className={`text-[10px] px-2 py-1 rounded-sm border transition-colors ${
                        comparePeriod === p && showCompare ? "bg-amber-600 text-white border-amber-600" : "border-border text-muted-foreground hover:border-amber-500/50"
                      }`}>{lbl}</button>
                  ))}
                </div>
                {!showCompare && (
                  <button onClick={() => setShowCompare(true)}
                    className="text-[10px] px-3 py-1 rounded-sm border border-amber-500/30 text-amber-400 hover:bg-amber-500/10 transition-colors">
                    Tampilkan
                  </button>
                )}
              </div>
            </div>

            {showCompare && compareData ? (
              <>
                {/* Anomaly badges */}
                {compareData.anomalies?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-3">
                    <span className="text-[10px] text-amber-400 font-semibold uppercase tracking-wider">⚠ Anomali detected:</span>
                    {compareData.anomalies.slice(0, 5).map((a, i) => (
                      <span key={i} className="text-[10px] px-2 py-0.5 rounded-sm bg-amber-500/10 border border-amber-500/20 text-amber-300 font-mono">
                        {a.time} {a.type === "download_spike" ? "↓" : "↑"} {a.value}M (baseline: {a.baseline}M)
                      </span>
                    ))}
                  </div>
                )}
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart>
                      <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                      <XAxis dataKey="time" type="category" allowDuplicatedCategory={false} tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} />
                      <YAxis tick={{ fill: "#a1a1aa", fontSize: 10 }} tickLine={false} axisLine={{ stroke: "#27272a" }} width={40} />
                      <Tooltip {...ttStyle} />
                      <Legend iconType="line" wrapperStyle={{ fontSize: "11px", color: "#a1a1aa" }} />
                      <Line data={compareData.current}  dataKey="download" name="Hari Ini ↓" stroke="#3b82f6" strokeWidth={2} dot={false} type="monotone" />
                      <Line data={compareData.previous} dataKey="download" name={`${compareData.offset_days}hr lalu ↓`} stroke="#3b82f6" strokeWidth={1.5} dot={false} strokeDasharray="5 3" type="monotone" />
                      <Line data={compareData.current}  dataKey="upload"   name="Hari Ini ↑"  stroke="#10b981" strokeWidth={2} dot={false} type="monotone" />
                      <Line data={compareData.previous} dataKey="upload"   name={`${compareData.offset_days}hr lalu ↑`} stroke="#10b981" strokeWidth={1.5} dot={false} strokeDasharray="5 3" type="monotone" />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                {compareData.current?.length === 0 && compareData.previous?.length === 0 && (
                  <p className="text-xs text-muted-foreground text-center py-4">Data historis tidak tersedia untuk periode ini</p>
                )}
              </>
            ) : showCompare ? (
              <div className="h-32 flex items-center justify-center"><RefreshCw className="w-4 h-4 animate-spin text-muted-foreground" /></div>
            ) : (
              <div className="h-32 flex items-center justify-center bg-secondary/10 rounded-sm border border-dashed border-border">
                <div className="text-center">
                  <TrendingUp className="w-8 h-8 mx-auto mb-2 text-muted-foreground/30" />
                  <p className="text-sm text-muted-foreground">Klik "Tampilkan" untuk melihat perbandingan traffic</p>
                </div>
              </div>
            )}
          </div>
        </>
      )}


      {/* Bottom Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card border border-border rounded-sm p-5" data-testid="system-health">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">System Health {sd && <span className="text-sm text-muted-foreground font-normal">- {sd.identity || sd.name}</span>}</h3>
          <div className="space-y-4">
            {/* CPU & Memory bars */}
            {[
              { label: "CPU Load", value: health.cpu ?? 0, icon: Cpu, unit: "%" },
              { label: "Memory", value: health.memory ?? 0, icon: HardDrive, unit: "%" },
            ].map(m => (
              <div key={m.label} className="flex items-center gap-3">
                <m.icon className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1"><span className="text-xs text-muted-foreground">{m.label}</span><span className="text-xs font-mono" style={{ color: m.value > 80 ? "#ef4444" : m.value > 60 ? "#f59e0b" : "#10b981" }}>{m.value}{m.unit}</span></div>
                  <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full rounded-full transition-all duration-1000" style={{ width: `${m.value}%`, backgroundColor: m.value > 80 ? "#ef4444" : m.value > 60 ? "#f59e0b" : "#10b981" }} /></div>
                </div>
              </div>
            ))}

            {/* Temperature sensors */}
            <div className="grid grid-cols-2 gap-3 pt-2 border-t border-border/50">
              {health.cpu_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-orange-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">CPU Temp</p>
                    <p className="text-sm font-mono" style={{ color: health.cpu_temp > 70 ? "#ef4444" : health.cpu_temp > 50 ? "#f59e0b" : "#10b981" }}>{health.cpu_temp}°C</p>
                  </div>
                </div>
              )}
              {health.board_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-red-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Board Temp</p>
                    <p className="text-sm font-mono" style={{ color: health.board_temp > 60 ? "#ef4444" : health.board_temp > 45 ? "#f59e0b" : "#10b981" }}>{health.board_temp}°C</p>
                  </div>
                </div>
              )}
              {health.sfp_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-blue-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">SFP Temp</p>
                    <p className="text-sm font-mono" style={{ color: health.sfp_temp > 70 ? "#ef4444" : health.sfp_temp > 50 ? "#f59e0b" : "#10b981" }}>{health.sfp_temp}°C</p>
                  </div>
                </div>
              )}
              {health.switch_temp > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Thermometer className="w-4 h-4 text-purple-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Switch Temp</p>
                    <p className="text-sm font-mono" style={{ color: health.switch_temp > 70 ? "#ef4444" : health.switch_temp > 50 ? "#f59e0b" : "#10b981" }}>{health.switch_temp}°C</p>
                  </div>
                </div>
              )}
              {health.voltage > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Zap className="w-4 h-4 text-yellow-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Voltage</p>
                    <p className="text-sm font-mono">{health.voltage}V</p>
                  </div>
                </div>
              )}
              {health.power > 0 && (
                <div className="flex items-center gap-2 p-2 rounded-sm bg-secondary/30">
                  <Battery className="w-4 h-4 text-green-500" />
                  <div>
                    <p className="text-[10px] text-muted-foreground">Power</p>
                    <p className="text-sm font-mono">{health.power}W</p>
                  </div>
                </div>
              )}
            </div>

            {/* PSU Status — tampilkan jika ada */}
            {health.psu && Object.keys(health.psu).length > 0 && (
              <div className="pt-2 border-t border-border/50">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">PSU Status</p>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(health.psu).map(([psu, state]) => (
                    <div key={psu} className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-xs font-mono border ${state === "ok" ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"}`}>
                      <div className={`w-1.5 h-1.5 rounded-full ${state === "ok" ? "bg-green-500" : "bg-red-500 animate-pulse"}`} />
                      {psu.toUpperCase()}: {state.toUpperCase()}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Fan Speeds */}
            {health.fans && Object.keys(health.fans).length > 0 && (
              <div className="pt-2 border-t border-border/50">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">Fan Speeds</p>
                <div className="grid grid-cols-2 gap-1.5">
                  {Object.entries(health.fans).map(([fan, rpm]) => (
                    <div key={fan} className="flex items-center justify-between px-2 py-1 rounded-sm bg-secondary/30 text-xs">
                      <span className="text-muted-foreground">{fan.replace("fan", "Fan ")}</span>
                      <span className="font-mono text-blue-400">{rpm.toLocaleString()} RPM</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Show message if no extended metrics available */}
            {health.cpu_temp === 0 && health.board_temp === 0 && health.voltage === 0 && (
              <p className="text-xs text-muted-foreground/50 text-center pt-2">Extended metrics not available for this device</p>
            )}
          </div>
        </div>
        <div className="bg-card border border-border rounded-sm p-5" data-testid="recent-alerts">
          <h3 className="text-lg font-semibold font-['Rajdhani'] mb-4">Alerts</h3>
          <div className="space-y-3">
            {(stats.alerts || []).map(a => {
              const Icon = alertIcons[a.type] || Info; return (
                <div key={a.id} className="flex items-start gap-3 p-2.5 rounded-sm bg-secondary/30 border border-border/50 hover:bg-secondary/50 transition-colors">
                  <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${alertColors[a.type]}`} />
                  <div className="flex-1 min-w-0"><p className="text-sm text-foreground">{a.message}</p><p className="text-xs text-muted-foreground mt-0.5 font-mono">{a.time}</p></div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* ── v3: Top Talkers ──────────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-sm p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold font-['Rajdhani'] flex items-center gap-2">
            <ArrowUp className="w-4 h-4 text-orange-400" /> Top Talkers
            <span className="text-xs text-muted-foreground font-normal">— top bandwidth consumers</span>
          </h3>
          <div className="flex gap-1">
            {["1h", "12h", "24h"].map(r => (
              <button key={r} onClick={() => setTopTalkersRange(r)}
                className={`text-[10px] px-2 py-1 rounded-sm border transition-colors ${
                  topTalkersRange === r ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:border-primary/50"
                }`}>{r}</button>
            ))}
          </div>
        </div>
        {topTalkers.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Activity className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No bandwidth data yet for this period.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {topTalkers.map((t, i) => {
              const maxBw = topTalkers[0]?.total_mbps || 1;
              const pct = Math.round((t.total_mbps / maxBw) * 100);
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="w-5 text-[10px] text-muted-foreground text-right">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex justify-between mb-0.5">
                      <span className="text-xs font-mono truncate text-foreground/80">{t.label}</span>
                      <span className="text-xs font-mono font-bold text-orange-400 flex-shrink-0 ml-2">{t.total_mbps} Mbps</span>
                    </div>
                    <div className="w-full h-1.5 bg-secondary rounded-full">
                      <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: `linear-gradient(90deg, #f97316, #ef4444)` }} />
                    </div>
                    <div className="flex gap-3 mt-0.5 text-[9px] text-muted-foreground">
                      <span className="text-blue-400">↓ {t.download_mbps}M</span>
                      <span className="text-green-400">↑ {t.upload_mbps}M</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
