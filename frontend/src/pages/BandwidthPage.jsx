import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "@/App";
import api from "@/lib/api";
import { toast } from "sonner";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Cell, Legend
} from "recharts";
import {
  Activity, RefreshCw, Wifi, WifiOff, Cpu, MemoryStick,
  ArrowDownToLine, ArrowUpFromLine, Network, Radio, Server,
  Gauge, ChevronDown, Box
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

// ── Format helpers ─────────────────────────────────────────────────────────────

function fmtMbps(mbps) {
  if (!mbps || mbps === 0) return "0";
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
  if (mbps >= 1) return `${mbps.toFixed(2)} Mbps`;
  return `${(mbps * 1000).toFixed(1)} Kbps`;
}

function fmtBps(bps) {
  if (!bps || bps === 0) return "0 bps";
  if (bps >= 1e9) return `${(bps / 1e9).toFixed(2)} Gbps`;
  if (bps >= 1e6) return `${(bps / 1e6).toFixed(2)} Mbps`;
  if (bps >= 1e3) return `${(bps / 1e3).toFixed(1)} Kbps`;
  return `${bps} bps`;
}

const IFACE_COLORS = [
  "#06b6d4", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444",
  "#3b82f6", "#ec4899", "#14b8a6", "#f97316", "#84cc16"
];

function getIfaceColor(name, idx) {
  if (name.startsWith("ether")) return IFACE_COLORS[parseInt(name.replace(/\D/g, "")) % 5];
  if (name.startsWith("sfp") || name.startsWith("combo")) return "#8b5cf6";
  if (name.startsWith("wlan")) return "#10b981";
  if (name.startsWith("lte") || name.startsWith("lte")) return "#f59e0b";
  return IFACE_COLORS[idx % IFACE_COLORS.length];
}

// ── Custom Tooltip ──────────────────────────────────────────────────────────────

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card border border-border rounded-sm px-3 py-2 shadow-xl text-xs">
      <p className="text-muted-foreground mb-1 font-mono">{label}</p>
      {payload.map((p, i) => (
        <p key={i} style={{ color: p.color }} className="font-mono font-semibold">
          {p.name}: {fmtMbps(p.value)}
        </p>
      ))}
    </div>
  );
}

// ── Interface Card ──────────────────────────────────────────────────────────────

function IfaceCard({ iface, color, isSelected, onClick }) {
  const totalMbps = iface.download_mbps + iface.upload_mbps;
  return (
    <button
      onClick={onClick}
      className={`text-left p-3 rounded-sm border transition-all duration-200 w-full ${
        isSelected
          ? "border-primary/50 bg-primary/5"
          : "border-border hover:border-border/80 hover:bg-secondary/20"
      } ${iface.disabled ? "opacity-40" : ""}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
          <span className="text-xs font-semibold font-mono">{iface.name}</span>
          {!iface.running && !iface.disabled && (
            <Badge variant="outline" className="text-[9px] rounded-sm h-4 text-yellow-400 border-yellow-400/30 px-1">down</Badge>
          )}
          {iface.disabled && (
            <Badge variant="outline" className="text-[9px] rounded-sm h-4 text-muted-foreground border-muted-foreground/30 px-1">disabled</Badge>
          )}
        </div>
        <span className="text-[10px] text-muted-foreground">{iface.type || "ether"}</span>
      </div>
      <div className="flex gap-3">
        <div className="flex items-center gap-1">
          <ArrowDownToLine className="w-3 h-3 text-cyan-400" />
          <span className="text-[11px] font-mono font-semibold text-cyan-300">{fmtMbps(iface.download_mbps)}</span>
        </div>
        <div className="flex items-center gap-1">
          <ArrowUpFromLine className="w-3 h-3 text-emerald-400" />
          <span className="text-[11px] font-mono font-semibold text-emerald-300">{fmtMbps(iface.upload_mbps)}</span>
        </div>
      </div>
    </button>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

const POLL_INTERVAL = 5000;
const HISTORY_MAX = 60; // 5 menit (60 × 5s)

export default function BandwidthPage() {
  const { user } = useAuth();
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState(null);
  const [selectedIface, setSelectedIface] = useState(null); // null = all
  const [liveData, setLiveData] = useState(null);
  const [history, setHistory] = useState([]); // time-series untuk chart
  const [loading, setLoading] = useState(false);
  const [loadingDevices, setLoadingDevices] = useState(true);
  const [hasData, setHasData] = useState(true); // false = belum ada data bandwidth
  const intervalRef = useRef(null);
  const [showDeviceDropdown, setShowDeviceDropdown] = useState(false);

  // Load devices list
  useEffect(() => {
    api.get("/devices")
      .then(r => {
        const deviceList = r.data || [];
        setDevices(deviceList);
        if (deviceList.length > 0) setSelectedDevice(deviceList[0]);
      })
      .catch(() => toast.error("Gagal memuat daftar device"))
      .finally(() => setLoadingDevices(false));
  }, []);

  const fetchLive = useCallback(async (isFirstLoad = false) => {
    if (!selectedDevice?.id) return;
    try {
      const r = await api.get(`/bandwidth/live/${selectedDevice.id}`);
      const data = r.data;
      setLiveData(data);
      setHasData(data.has_data !== false);

      // Seed history dari trend API saat pertama load
      if (isFirstLoad && data.trend && data.trend.length > 0) {
        const seedPoints = data.trend.map(t => {
          const ts = new Date(t.timestamp);
          const timeLabel = ts.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          return { time: timeLabel, download: t.download_mbps, upload: t.upload_mbps };
        });
        setHistory(seedPoints);
        return; // point sudah di-seed, tidak perlu append lagi
      }

      // Append ke history time-series (live polling)
      const now = new Date();
      const timeLabel = now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

      const ifaces = data.interfaces || [];
      const point = { time: timeLabel };

      if (selectedIface && selectedIface !== "all") {
        const f = ifaces.find(i => i.name === selectedIface);
        point.download = f?.download_mbps ?? 0;
        point.upload = f?.upload_mbps ?? 0;
      } else {
        point.download = data.total_download_mbps ?? 0;
        point.upload = data.total_upload_mbps ?? 0;
        // Tambah per-iface juga untuk bar chart
        ifaces.forEach(i => {
          if (i.is_physical && i.running) {
            point[`dl_${i.name}`] = i.download_mbps;
            point[`ul_${i.name}`] = i.upload_mbps;
          }
        });
      }

      setHistory(prev => [...prev.slice(-(HISTORY_MAX - 1)), point]);
    } catch (e) {
      // silent — jangan toast biar tidak spam
    }
  }, [selectedDevice, selectedIface]);

  // Start/restart polling ketika device atau interface berubah
  useEffect(() => {
    if (!selectedDevice) return;
    setHistory([]);
    setHasData(true);
    setLoading(true);
    fetchLive(true).finally(() => setLoading(false));

    clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => fetchLive(false), POLL_INTERVAL);

    return () => clearInterval(intervalRef.current);
  }, [selectedDevice, selectedIface, fetchLive]);

  const physicalIfaces = (liveData?.interfaces || []).filter(i => i.is_physical);
  const allIfaces = liveData?.interfaces || [];

  // Bar chart data (current snapshot per interface)
  const barData = physicalIfaces
    .filter(i => i.download_mbps > 0 || i.upload_mbps > 0 || !selectedIface)
    .map(i => ({
      name: i.name,
      Download: i.download_mbps,
      Upload: i.upload_mbps,
    }))
    .slice(0, 16);

  return (
    <div className="space-y-4 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <Activity className="w-6 h-6 text-primary" />
            Bandwidth Monitor
          </h1>
          <p className="text-xs text-muted-foreground">
            Real-time traffic per interface — update setiap 5 detik
          </p>
        </div>

        {/* Device Picker */}
        <div className="relative">
          <button
            onClick={() => setShowDeviceDropdown(v => !v)}
            className="flex items-center gap-2 px-3 py-2 bg-card border border-border rounded-sm text-sm hover:bg-secondary/20 transition-colors min-w-[200px] justify-between"
          >
            <div className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${selectedDevice?.status === "online" ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
              <span className="font-medium truncate">{selectedDevice?.name || "Pilih Device"}</span>
            </div>
            <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          </button>
          {showDeviceDropdown && (
            <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-sm shadow-xl min-w-[220px] max-h-64 overflow-y-auto">
              {devices.map(d => (
                <button
                  key={d.id}
                  className={`w-full text-left px-3 py-2.5 text-sm hover:bg-secondary/30 transition-colors flex items-center gap-2 ${selectedDevice?.id === d.id ? "bg-primary/10 text-primary" : ""}`}
                  onClick={() => { setSelectedDevice(d); setSelectedIface(null); setShowDeviceDropdown(false); }}
                >
                  <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${d.status === "online" ? "bg-green-500" : "bg-red-500"}`} />
                  <span className="truncate">{d.name}</span>
                  <span className="text-[10px] text-muted-foreground ml-auto font-mono">{d.ip_address}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Device Stats Bar */}
      {liveData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Total Download", value: fmtMbps(liveData.total_download_mbps), icon: ArrowDownToLine, color: "text-cyan-400" },
            { label: "Total Upload", value: fmtMbps(liveData.total_upload_mbps), icon: ArrowUpFromLine, color: "text-emerald-400" },
            { label: "CPU Load", value: `${liveData.cpu_load ?? 0}%`, icon: Cpu, color: liveData.cpu_load > 80 ? "text-red-400" : "text-foreground" },
            { label: "Memory", value: `${liveData.memory_usage ?? 0}%`, icon: MemoryStick, color: liveData.memory_usage > 85 ? "text-red-400" : "text-foreground" },
          ].map(s => (
            <div key={s.label} className="bg-card border border-border rounded-sm px-4 py-3">
              <div className="flex items-center gap-2 mb-1">
                <s.icon className={`w-3.5 h-3.5 ${s.color}`} />
                <span className="text-[10px] text-muted-foreground uppercase tracking-wide">{s.label}</span>
              </div>
              <p className={`text-xl font-bold font-mono ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* No-data warning — muncul jika device belum pernah dihitung bandwidth-nya */}
      {liveData && !hasData && (
        <div className="flex items-start gap-3 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-sm">
          <Activity className="w-4 h-4 text-yellow-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-yellow-300">Data bandwidth belum tersedia</p>
            <p className="text-[11px] text-yellow-300/70 mt-0.5">
              Sistem memerlukan minimal 2 siklus polling (±60 detik) untuk menghitung bandwidth (delta octets).
              Grafik akan muncul otomatis setelah data tersedia.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Interface List (sidebar) */}
        <div className="lg:col-span-1">
          <div className="bg-card border border-border rounded-sm p-3">
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-2">
              Interfaces {liveData ? `(${allIfaces.length})` : ""}
            </p>
            <div className="space-y-1.5">
              {/* All Interfaces button */}
              <button
                onClick={() => setSelectedIface(null)}
                className={`w-full text-left p-2 rounded-sm text-xs transition-all border ${
                  !selectedIface ? "border-primary/50 bg-primary/5 text-primary" : "border-transparent text-muted-foreground hover:bg-secondary/20"
                }`}
              >
                <div className="flex items-center gap-2">
                  <Network className="w-3.5 h-3.5" />
                  <span className="font-semibold">Semua Interface</span>
                </div>
              </button>
              {physicalIfaces.map((iface, idx) => (
                <IfaceCard
                  key={iface.name}
                  iface={iface}
                  color={getIfaceColor(iface.name, idx)}
                  isSelected={selectedIface === iface.name}
                  onClick={() => setSelectedIface(iface.name === selectedIface ? null : iface.name)}
                />
              ))}
              {!liveData && !loading && (
                <p className="text-xs text-muted-foreground text-center py-6">Pilih device untuk melihat interfaces</p>
              )}
              {loading && (
                <p className="text-xs text-muted-foreground text-center py-6 animate-pulse">Memuat...</p>
              )}
            </div>
          </div>
        </div>

        {/* Charts */}
        <div className="lg:col-span-3 space-y-4">
          {/* Real-time Area Chart */}
          <div className="bg-card border border-border rounded-sm p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-xs font-semibold">
                  {selectedIface ? `Interface: ${selectedIface}` : "Total Traffic (Semua Interface)"}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  Real-time · Update 5 detik · Menampilkan {history.length} sample
                </p>
              </div>
              <div className="flex items-center gap-1 text-[10px] text-green-400 font-mono">
                <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                LIVE
              </div>
            </div>

            {history.length === 0 ? (
              <div className="h-48 flex items-center justify-center text-muted-foreground text-sm">
                <div className="text-center">
                  <Activity className="w-8 h-8 mx-auto mb-2 opacity-30 animate-pulse" />
                  <p>Mengumpulkan data traffic...</p>
                </div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={history} margin={{ left: 0, right: 4, top: 4, bottom: 0 }}>
                  <defs>
                    <linearGradient id="dlGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="ulGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 9, fill: "#6b7280" }}
                    interval={Math.max(1, Math.floor(history.length / 8))}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 9, fill: "#6b7280" }}
                    tickFormatter={v => fmtMbps(v)}
                    tickLine={false}
                    axisLine={false}
                    width={60}
                  />
                  <Tooltip content={<CustomTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="download"
                    name="Download"
                    stroke="#06b6d4"
                    strokeWidth={2}
                    fill="url(#dlGrad)"
                    dot={false}
                    activeDot={{ r: 3 }}
                    isAnimationActive={false}
                  />
                  <Area
                    type="monotone"
                    dataKey="upload"
                    name="Upload"
                    stroke="#10b981"
                    strokeWidth={2}
                    fill="url(#ulGrad)"
                    dot={false}
                    activeDot={{ r: 3 }}
                    isAnimationActive={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Per-Interface Bar Chart */}
          {barData.length > 0 && (
            <div className="bg-card border border-border rounded-sm p-4">
              <p className="text-xs font-semibold mb-1">Current Bandwidth per Interface</p>
              <p className="text-[10px] text-muted-foreground mb-3">Snapshot terbaru</p>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={barData} margin={{ left: 0, right: 4, top: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#6b7280" }} tickLine={false} />
                  <YAxis tick={{ fontSize: 9, fill: "#6b7280" }} tickFormatter={v => fmtMbps(v)} tickLine={false} axisLine={false} width={55} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend
                    iconSize={8}
                    wrapperStyle={{ fontSize: 10, paddingTop: 8 }}
                  />
                  <Bar dataKey="Download" fill="#06b6d4" radius={[2, 2, 0, 0]} maxBarSize={32} isAnimationActive={false} />
                  <Bar dataKey="Upload" fill="#10b981" radius={[2, 2, 0, 0]} maxBarSize={32} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Interface Detail Table */}
          {allIfaces.length > 0 && (
            <div className="bg-card border border-border rounded-sm p-4">
              <p className="text-xs font-semibold mb-3">Detail Semua Interface</p>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-border">
                      {["Interface", "Type", "Status", "Download", "Upload", "RX Bytes", "TX Bytes"].map(h => (
                        <th key={h} className="px-2 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {allIfaces.map((iface, idx) => (
                      <tr key={iface.name} className="border-b border-border/20 hover:bg-secondary/10 transition-colors">
                        <td className="px-2 py-2">
                          <div className="flex items-center gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: getIfaceColor(iface.name, idx) }} />
                            <span className="text-xs font-mono font-semibold">{iface.name}</span>
                          </div>
                        </td>
                        <td className="px-2 py-2 text-[11px] text-muted-foreground">{iface.type || "—"}</td>
                        <td className="px-2 py-2">
                          {iface.disabled
                            ? <Badge variant="outline" className="text-[9px] rounded-sm text-muted-foreground border-muted-foreground/30">disabled</Badge>
                            : iface.running
                              ? <Badge variant="outline" className="text-[9px] rounded-sm text-green-400 border-green-400/30">running</Badge>
                              : <Badge variant="outline" className="text-[9px] rounded-sm text-yellow-400 border-yellow-400/30">down</Badge>
                          }
                        </td>
                        <td className="px-2 py-2 text-[11px] font-mono text-cyan-300">{fmtMbps(iface.download_mbps)}</td>
                        <td className="px-2 py-2 text-[11px] font-mono text-emerald-300">{fmtMbps(iface.upload_mbps)}</td>
                        <td className="px-2 py-2 text-[11px] font-mono text-muted-foreground">{fmtBps(iface.rx_bytes)}</td>
                        <td className="px-2 py-2 text-[11px] font-mono text-muted-foreground">{fmtBps(iface.tx_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
