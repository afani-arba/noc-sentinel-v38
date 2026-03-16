import { useState, useEffect, useRef } from "react";
import api from "@/lib/api";
import {
  Server, Cpu, HardDrive, Activity, Wifi, WifiOff, AlertTriangle,
  CheckCircle2, RefreshCw, Monitor, ZapOff, TrendingUp, TrendingDown
} from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, Tooltip } from "recharts";

const REFRESH_INTERVAL = 10000; // 10 seconds

// Glow color by alert level
function getGlowStyle(level, status) {
  if (status === "offline" || level === "critical") {
    return {
      borderColor: "rgba(239,68,68,0.6)",
      boxShadow: "0 0 20px rgba(239,68,68,0.4), inset 0 0 20px rgba(239,68,68,0.05)",
    };
  }
  if (level === "warning") {
    return {
      borderColor: "rgba(234,179,8,0.6)",
      boxShadow: "0 0 20px rgba(234,179,8,0.3), inset 0 0 20px rgba(234,179,8,0.05)",
    };
  }
  return {
    borderColor: "rgba(34,197,94,0.5)",
    boxShadow: "0 0 16px rgba(34,197,94,0.25), inset 0 0 16px rgba(34,197,94,0.04)",
  };
}

function StatusBadge({ status }) {
  if (status === "online") {
    return (
      <span className="flex items-center gap-1 text-green-400 text-xs font-semibold">
        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
        ONLINE
      </span>
    );
  }
  if (status === "offline") {
    return (
      <span className="flex items-center gap-1 text-red-400 text-xs font-semibold">
        <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
        OFFLINE
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-gray-400 text-xs font-semibold">
      <span className="w-2 h-2 rounded-full bg-gray-400" />
      UNKNOWN
    </span>
  );
}

function MetricBar({ value, max = 100, color }) {
  const pct = Math.min(100, Math.max(0, value));
  const barColor = value > 80 ? "#ef4444" : value > 60 ? "#eab308" : color;
  return (
    <div className="w-full h-1.5 rounded-full bg-white/10">
      <div
        className="h-full rounded-full transition-all duration-700"
        style={{ width: `${pct}%`, backgroundColor: barColor }}
      />
    </div>
  );
}

function DeviceCard({ device }) {
  const glowStyle = getGlowStyle(device.alert_level, device.status);
  const isOffline = device.status === "offline";

  return (
    <div
      className="relative rounded-xl border p-4 flex flex-col gap-2 transition-all duration-500"
      style={{
        background: "linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%)",
        backdropFilter: "blur(12px)",
        ...glowStyle,
      }}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-white truncate leading-tight">
            {device.identity || device.name}
          </p>
          <p className="text-[10px] text-slate-400 font-mono">{device.ip_address}</p>
        </div>
        <StatusBadge status={device.status} />
      </div>

      {/* Model + Uptime */}
      {device.model && (
        <p className="text-[10px] text-slate-500 truncate">{device.model} {device.ros_version ? `· v${device.ros_version}` : ""}</p>
      )}

      {/* Metrics */}
      {!isOffline ? (
        <div className="space-y-2 mt-1">
          <div>
            <div className="flex justify-between text-[10px] mb-0.5">
              <span className="text-slate-400 flex items-center gap-1"><Cpu className="w-3 h-3" /> CPU</span>
              <span className={`font-mono font-semibold ${device.cpu_load > 80 ? "text-red-400" : device.cpu_load > 60 ? "text-yellow-400" : "text-green-400"}`}>{device.cpu_load}%</span>
            </div>
            <MetricBar value={device.cpu_load} color="#22c55e" />
          </div>
          <div>
            <div className="flex justify-between text-[10px] mb-0.5">
              <span className="text-slate-400 flex items-center gap-1"><HardDrive className="w-3 h-3" /> MEM</span>
              <span className={`font-mono font-semibold ${device.memory_usage > 80 ? "text-red-400" : device.memory_usage > 60 ? "text-yellow-400" : "text-blue-400"}`}>{device.memory_usage}%</span>
            </div>
            <MetricBar value={device.memory_usage} color="#3b82f6" />
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-center py-3">
          <WifiOff className="w-8 h-8 text-red-500/60" />
        </div>
      )}

      {/* Footer stats */}
      <div className="grid grid-cols-3 gap-1 mt-1 pt-2 border-t border-white/10">
        <div className="text-center">
          <p className="text-[9px] text-slate-500 uppercase">Ping</p>
          <p className={`text-[11px] font-mono font-bold ${device.ping_ms > 100 ? "text-yellow-400" : "text-cyan-400"}`}>
            {isOffline ? "—" : `${device.ping_ms}ms`}
          </p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingDown className="w-2.5 h-2.5" />DL</p>
          <p className="text-[11px] font-mono font-bold text-blue-400">{isOffline ? "—" : `${device.download_mbps}M`}</p>
        </div>
        <div className="text-center">
          <p className="text-[9px] text-slate-500 flex items-center justify-center gap-0.5"><TrendingUp className="w-2.5 h-2.5" />UL</p>
          <p className="text-[11px] font-mono font-bold text-green-400">{isOffline ? "—" : `${device.upload_mbps}M`}</p>
        </div>
      </div>
    </div>
  );
}

function EventTicker({ events }) {
  const ref = useRef(null);
  // Infinitely scroll the event list
  useEffect(() => {
    const el = ref.current;
    if (!el || !events.length) return;
    let x = 0;
    const speed = 0.7;
    const anim = requestAnimationFrame(function tick() {
      x -= speed;
      if (Math.abs(x) >= el.scrollWidth / 2) x = 0;
      el.style.transform = `translateX(${x}px)`;
      requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(anim);
  }, [events]);

  const colorMap = {
    red: "text-red-400",
    green: "text-green-400",
    yellow: "text-yellow-400",
    orange: "text-orange-400",
    blue: "text-blue-400",
  };

  const items = [...events, ...events]; // duplicate for seamless loop

  return (
    <div className="overflow-hidden whitespace-nowrap">
      <div ref={ref} className="inline-flex gap-8">
        {items.map((ev, i) => (
          <span key={i} className={`text-xs font-mono ${colorMap[ev.color] || "text-slate-400"}`}>
            <span className="text-slate-500 mr-2">{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" }) : ""}</span>
            {ev.message}
          </span>
        ))}
      </div>
    </div>
  );
}

export default function WallDisplayPage() {
  const [data, setData] = useState(null);
  const [events, setEvents] = useState([]);
  const [time, setTime] = useState(new Date());
  const [bwHistory, setBwHistory] = useState([]);

  const fetchData = async () => {
    try {
      const [statusRes, eventsRes] = await Promise.all([
        api.get("/wallboard/status"),
        api.get("/wallboard/events"),
      ]);
      setData(statusRes.data);
      setEvents(eventsRes.data.events || []);

      // Build quick BW history from summary
      const total_dl = statusRes.data.devices.reduce((s, d) => s + d.download_mbps, 0);
      const total_ul = statusRes.data.devices.reduce((s, d) => s + d.upload_mbps, 0);
      setBwHistory(prev => {
        const next = [...prev, { download: parseFloat(total_dl.toFixed(2)), upload: parseFloat(total_ul.toFixed(2)) }];
        return next.slice(-30);
      });
    } catch (e) {
      console.error("Wallboard fetch error:", e);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    const clockInterval = setInterval(() => setTime(new Date()), 1000);
    return () => { clearInterval(interval); clearInterval(clockInterval); };
  }, []);

  const summary = data?.summary || { total: 0, online: 0, offline: 0, warning: 0 };
  const devices = data?.devices || [];

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        background: "linear-gradient(135deg, #020817 0%, #0a1628 50%, #020817 100%)",
        fontFamily: "'Inter', 'Rajdhani', sans-serif",
      }}
    >
      {/* ── TOP HEADER ─────────────────────────────────────────────── */}
      <div
        className="flex items-center justify-between px-6 py-3 border-b"
        style={{
          borderColor: "rgba(99,179,237,0.2)",
          background: "linear-gradient(90deg, rgba(14,165,233,0.08) 0%, rgba(0,0,0,0) 50%, rgba(14,165,233,0.08) 100%)",
        }}
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-blue-500/20 border border-blue-500/40 rounded-lg flex items-center justify-center">
            <Monitor className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-lg font-['Rajdhani'] font-bold text-white tracking-wider">
              NOC SENTINEL <span className="text-blue-400">v3</span>
            </h1>
            <p className="text-[10px] text-slate-400 tracking-widest uppercase">ARBA MONITORING · WALL DISPLAY</p>
          </div>
        </div>

        {/* Stats Counter */}
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/30">
            <CheckCircle2 className="w-4 h-4 text-green-400" />
            <span className="text-green-400 font-bold font-['Rajdhani'] text-xl">{summary.online}</span>
            <span className="text-green-400/70 text-xs">online</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30">
            <ZapOff className="w-4 h-4 text-red-400" />
            <span className="text-red-400 font-bold font-['Rajdhani'] text-xl">{summary.offline}</span>
            <span className="text-red-400/70 text-xs">offline</span>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
            <AlertTriangle className="w-4 h-4 text-yellow-400" />
            <span className="text-yellow-400 font-bold font-['Rajdhani'] text-xl">{summary.warning}</span>
            <span className="text-yellow-400/70 text-xs">warning</span>
          </div>
          <div className="text-right">
            <p className="text-2xl font-mono font-bold text-white">
              {time.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </p>
            <p className="text-[10px] text-slate-400">{time.toLocaleDateString("id-ID", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })}</p>
          </div>
        </div>
      </div>

      {/* ── MAIN CONTENT ────────────────────────────────────────────── */}
      <div className="flex flex-1 gap-4 p-4 min-h-0">
        {/* Device Grid */}
        <div className="flex-1 overflow-y-auto">
          {devices.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center text-slate-500">
                <Server className="w-16 h-16 mx-auto mb-3 opacity-30" />
                <p>No devices configured</p>
              </div>
            </div>
          ) : (
            <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))" }}>
              {devices.map(d => <DeviceCard key={d.id} device={d} />)}
            </div>
          )}
        </div>

        {/* Right Panel */}
        <div className="w-72 flex flex-col gap-4">
          {/* BW Chart */}
          <div
            className="rounded-xl border p-4 flex-1"
            style={{
              background: "rgba(255,255,255,0.03)",
              borderColor: "rgba(99,179,237,0.2)",
            }}
          >
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest mb-3 flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-blue-400" /> Bandwidth Real-time
            </h3>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={bwHistory}>
                  <defs>
                    <linearGradient id="wdl" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="wul" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22c55e" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Tooltip
                    contentStyle={{ background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: "8px", fontSize: "11px" }}
                    labelStyle={{ color: "#94a3b8" }}
                  />
                  <Area type="monotone" dataKey="download" stroke="#3b82f6" fill="url(#wdl)" strokeWidth={2} name="DL (Mbps)" dot={false} />
                  <Area type="monotone" dataKey="upload" stroke="#22c55e" fill="url(#wul)" strokeWidth={2} name="UL (Mbps)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <div className="flex gap-4 mt-2 text-[10px] text-slate-500">
              <span className="flex items-center gap-1"><span className="w-2 h-[2px] bg-blue-500 inline-block" /> DL</span>
              <span className="flex items-center gap-1"><span className="w-2 h-[2px] bg-green-500 inline-block" /> UL</span>
            </div>
          </div>

          {/* Active Alerts */}
          <div
            className="rounded-xl border p-4"
            style={{
              background: "rgba(255,255,255,0.03)",
              borderColor: "rgba(99,179,237,0.2)",
            }}
          >
            <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest mb-3 flex items-center gap-2">
              <AlertTriangle className="w-3.5 h-3.5 text-yellow-400" /> Active Alerts
            </h3>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {devices.filter(d => d.alert_level !== "normal").length === 0 ? (
                <div className="flex items-center gap-2 text-green-400 text-xs">
                  <CheckCircle2 className="w-4 h-4" /> All systems normal
                </div>
              ) : (
                devices
                  .filter(d => d.alert_level !== "normal")
                  .map(d => (
                    <div key={d.id} className={`flex items-start gap-2 p-2 rounded-lg text-xs ${d.alert_level === "critical" ? "bg-red-500/10 border border-red-500/20" : "bg-yellow-500/10 border border-yellow-500/20"}`}>
                      {d.alert_level === "critical" ? <WifiOff className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" /> : <AlertTriangle className="w-3.5 h-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />}
                      <div>
                        <p className={`font-semibold ${d.alert_level === "critical" ? "text-red-300" : "text-yellow-300"}`}>{d.name}</p>
                        <p className="text-slate-400 font-mono text-[10px]">
                          {d.status === "offline" ? "OFFLINE" : `CPU:${d.cpu_load}% MEM:${d.memory_usage}%`}
                        </p>
                      </div>
                    </div>
                  ))
              )}
            </div>
          </div>

          {/* Refresh indicator */}
          <div className="flex items-center justify-center gap-2 text-slate-600 text-[10px]">
            <RefreshCw className="w-3 h-3 animate-spin" style={{ animationDuration: "3s" }} />
            Auto-refresh every 10s
          </div>
        </div>
      </div>

      {/* ── BOTTOM TICKER ───────────────────────────────────────────── */}
      <div
        className="border-t px-4 py-2"
        style={{
          borderColor: "rgba(99,179,237,0.2)",
          background: "rgba(0,0,0,0.4)",
        }}
      >
        {events.length > 0 ? (
          <EventTicker events={events} />
        ) : (
          <p className="text-slate-600 text-xs text-center font-mono">No recent events</p>
        )}
      </div>
    </div>
  );
}
