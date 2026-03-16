import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Search, RefreshCw, Server, WifiOff, AlertTriangle, Shield, BarChart3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return `${val.toFixed(1)} ${units[i]}`;
}

export default function ConnectionsPage() {
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [data, setData] = useState({ connections: [], total: 0, top_talkers: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState("top"); // top | all

  useEffect(() => {
    api.get("/devices").then(r => {
      setDevices(r.data);
      if (r.data.length === 1) setSelectedDevice(r.data[0].id);
    }).catch(() => {});
  }, []);

  const fetchData = useCallback(async () => {
    if (!selectedDevice) return;
    setLoading(true);
    setError("");
    try {
      const r = await api.get("/firewall/connections", { params: { device_id: selectedDevice, top: 200 } });
      setData(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to fetch connections");
      setData({ connections: [], total: 0, top_talkers: [] });
    }
    setLoading(false);
  }, [selectedDevice]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const conns = data.connections || [];
  const filtered = search
    ? conns.filter(c => JSON.stringify(c).toLowerCase().includes(search.toLowerCase()))
    : conns;

  return (
    <div className="space-y-3 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Active Connections</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Connection tracking & top bandwidth users</p>
        </div>
        <div className="flex gap-1">
          <Button variant={view === "top" ? "default" : "outline"} size="sm" className="rounded-sm text-xs gap-1.5" onClick={() => setView("top")}>
            <BarChart3 className="w-3.5 h-3.5" /> Top Talkers
          </Button>
          <Button variant={view === "all" ? "default" : "outline"} size="sm" className="rounded-sm text-xs gap-1.5" onClick={() => setView("all")}>
            <Shield className="w-3.5 h-3.5" /> Semua Koneksi
          </Button>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-col sm:flex-row gap-2">
          <div className="flex flex-col gap-1 sm:flex-none">
            <label className="text-[10px] text-muted-foreground uppercase tracking-widest">Select Device</label>
            <Select value={selectedDevice} onValueChange={setSelectedDevice}>
              <SelectTrigger className="w-full sm:w-52 rounded-sm bg-card text-xs h-9">
                <SelectValue placeholder="Select device..." />
              </SelectTrigger>
              <SelectContent>
                {devices.map(d => (
                  <SelectItem key={d.id} value={d.id}>
                    <span className="flex items-center gap-2">
                      <div className={`w-1.5 h-1.5 rounded-full ${d.status === "online" ? "bg-green-500" : "bg-red-500"}`} />
                      {d.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-2 flex-1 sm:self-end">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input placeholder="Cari IP, protokol..." value={search} onChange={e => setSearch(e.target.value)}
                className="pl-9 rounded-sm bg-card h-9 text-xs" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchData} className="rounded-sm h-9 w-9 flex-shrink-0">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Stats */}
      {selectedDevice && !error && data.total > 0 && (
        <div className="flex items-center gap-4 text-xs px-1">
          <span className="text-muted-foreground">Total Koneksi: <span className="text-foreground font-mono">{data.total}</span></span>
          <span className="text-muted-foreground">Top Talkers: <span className="font-mono">{data.top_talkers?.length || 0}</span></span>
        </div>
      )}

      {/* Content */}
      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Pilih perangkat MikroTik untuk melihat koneksi aktif</p>
        </div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-8 text-center">
          <WifiOff className="w-10 h-10 mx-auto mb-3 text-red-500/50" />
          <p className="text-red-400 text-sm">{error}</p>
          <p className="text-xs text-muted-foreground mt-1">Pastikan Connection Tracking aktif di Firewall MikroTik</p>
        </div>
      ) : loading ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <RefreshCw className="w-6 h-6 mx-auto mb-2 text-muted-foreground animate-spin" />
          <p className="text-sm text-muted-foreground">Mengambil data koneksi...</p>
        </div>
      ) : view === "top" ? (
        /* Top Talkers */
        <div className="space-y-2">
          {data.top_talkers?.length === 0 ? (
            <div className="bg-card border border-border rounded-sm p-8 text-center">
              <p className="text-sm text-muted-foreground">Tidak ada data top talkers (mungkin bytes tidak tersedia dari router)</p>
            </div>
          ) : (
            <div className="bg-card border border-border rounded-sm overflow-hidden">
              <div className="px-4 py-2.5 border-b border-border bg-muted/30">
                <p className="text-xs text-muted-foreground">Top IPs berdasarkan penggunaan bandwidth total (sumber + balasan)</p>
              </div>
              {data.top_talkers?.map((t, i) => {
                const maxBytes = data.top_talkers[0]?.bytes || 1;
                const pct = (t.bytes / maxBytes) * 100;
                return (
                  <div key={t.ip} className="px-4 py-3 border-b border-border/50 last:border-0">
                    <div className="flex items-center justify-between mb-1.5">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-muted-foreground/60 font-mono w-5">#{i + 1}</span>
                        <span className="font-mono text-sm font-medium">{t.ip}</span>
                        {i === 0 && (
                          <Badge className="rounded-sm text-[10px] border bg-red-500/10 text-red-400 border-red-500/20 gap-1">
                            <AlertTriangle className="w-2.5 h-2.5" /> Tertinggi
                          </Badge>
                        )}
                      </div>
                      <span className="font-mono text-sm font-semibold text-primary">{formatBytes(t.bytes)}</span>
                    </div>
                    {/* Progress bar */}
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${i === 0 ? "bg-red-500" : i < 3 ? "bg-orange-500" : "bg-primary/60"}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        /* All Connections */
        filtered.length === 0 ? (
          <div className="bg-card border border-border rounded-sm p-8 text-center">
            <p className="text-sm text-muted-foreground">Tidak ada koneksi aktif</p>
          </div>
        ) : (
          <div className="bg-card border border-border rounded-sm overflow-hidden">
            <div className="grid grid-cols-12 text-[10px] text-muted-foreground uppercase tracking-wider px-3 py-2 border-b border-border bg-muted/30">
              <div className="col-span-1">Proto</div>
              <div className="col-span-4">Source</div>
              <div className="col-span-4">Destination</div>
              <div className="col-span-2">Total</div>
              <div className="col-span-1">State</div>
            </div>
            {filtered.slice(0, 200).map((c, i) => (
              <div key={c[".id"] || i} className="grid grid-cols-12 items-center px-3 py-2 border-b border-border/50 last:border-0 hover:bg-muted/20 text-xs">
                <div className="col-span-1">
                  <Badge className="rounded-sm text-[10px] border bg-muted/50 text-muted-foreground border-border">
                    {c._protocol?.toUpperCase() || "—"}
                  </Badge>
                </div>
                <div className="col-span-4 font-mono text-xs truncate">{c._src || "—"}</div>
                <div className="col-span-4 font-mono text-xs text-muted-foreground truncate">{c._dst || "—"}</div>
                <div className="col-span-2 font-mono text-[10px]">{formatBytes(c._total_bytes)}</div>
                <div className="col-span-1 text-[10px] text-muted-foreground">{c._state || "—"}</div>
              </div>
            ))}
          </div>
        )
      )}
    </div>
  );
}
