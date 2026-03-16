import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Search, RefreshCw, Server, Wifi, WifiOff, AlertCircle, CheckCircle, Clock, Activity } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function StatusBadge({ status }) {
  const s = (status || "").toLowerCase();
  if (s === "established") return <Badge className="rounded-sm text-[10px] border bg-green-500/10 text-green-500 border-green-500/20 gap-1"><CheckCircle className="w-3 h-3" />Established</Badge>;
  if (s === "active") return <Badge className="rounded-sm text-[10px] border bg-yellow-500/10 text-yellow-500 border-yellow-500/20 gap-1"><Activity className="w-3 h-3" />Active</Badge>;
  if (s === "idle") return <Badge className="rounded-sm text-[10px] border bg-muted-foreground/20 text-muted-foreground border-muted-foreground/20 gap-1"><Clock className="w-3 h-3" />Idle</Badge>;
  if (s === "connect") return <Badge className="rounded-sm text-[10px] border bg-blue-500/10 text-blue-500 border-blue-500/20 gap-1"><Wifi className="w-3 h-3" />Connecting</Badge>;
  return <Badge className="rounded-sm text-[10px] border bg-red-500/10 text-red-500 border-red-500/20 gap-1"><AlertCircle className="w-3 h-3" />{status || "Unknown"}</Badge>;
}

export default function BGPPage() {
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [data, setData] = useState({ peers: [], sessions: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

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
      const r = await api.get("/routing/bgp", { params: { device_id: selectedDevice } });
      setData(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to fetch BGP data");
      setData({ peers: [], sessions: [] });
    }
    setLoading(false);
  }, [selectedDevice]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const peers = data.peers || [];
  const filteredPeers = search
    ? peers.filter(p => JSON.stringify(p).toLowerCase().includes(search.toLowerCase()))
    : peers;

  const established = peers.filter(p => p._status === "established").length;
  const down = peers.length - established;

  return (
    <div className="space-y-3 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">BGP Peers</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Monitor status koneksi BGP dengan upstream ISP</p>
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
              <Input placeholder="Cari peer / IP..." value={search} onChange={e => setSearch(e.target.value)}
                className="pl-9 rounded-sm bg-card h-9 text-xs" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchData} className="rounded-sm h-9 w-9 flex-shrink-0">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Stats */}
      {selectedDevice && !error && peers.length > 0 && (
        <div className="flex items-center gap-4 text-xs px-1">
          <span className="text-muted-foreground">Total Peers: <span className="text-foreground font-mono">{peers.length}</span></span>
          <span className="text-green-500">Established: <span className="font-mono">{established}</span></span>
          {down > 0 && <span className="text-red-400">Down: <span className="font-mono">{down}</span></span>}
        </div>
      )}

      {/* Content */}
      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Pilih perangkat MikroTik untuk melihat BGP peers</p>
        </div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-8 text-center">
          <WifiOff className="w-10 h-10 mx-auto mb-3 text-red-500/50" />
          <p className="text-red-400 text-sm">{error}</p>
          <p className="text-xs text-muted-foreground mt-1">Pastikan BGP dikonfigurasi di router ini</p>
        </div>
      ) : loading ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <RefreshCw className="w-6 h-6 mx-auto mb-2 text-muted-foreground animate-spin" />
          <p className="text-sm text-muted-foreground">Mengambil data BGP...</p>
        </div>
      ) : peers.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <p className="text-sm text-muted-foreground">Tidak ada BGP peer yang dikonfigurasi</p>
        </div>
      ) : (
        <div className="space-y-2">
          {/* Alert jika ada peer down */}
          {down > 0 && (
            <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/30 rounded-sm text-sm text-red-400">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span><strong>{down}</strong> BGP peer sedang DOWN — periksa koneksi ke upstream ISP!</span>
            </div>
          )}

          {/* Peers table */}
          <div className="bg-card border border-border rounded-sm overflow-hidden">
            <div className="grid grid-cols-12 text-[10px] text-muted-foreground uppercase tracking-wider px-3 py-2 border-b border-border bg-muted/30">
              <div className="col-span-1">Status</div>
              <div className="col-span-3">Peer Name</div>
              <div className="col-span-2">Remote AS</div>
              <div className="col-span-3">Remote Address</div>
              <div className="col-span-3">Uptime / Info</div>
            </div>
            {filteredPeers.map((p, i) => (
              <div key={p[".id"] || i} className="grid grid-cols-12 items-center px-3 py-2.5 border-b border-border/50 last:border-0 hover:bg-muted/20 transition-colors">
                <div className="col-span-1">
                  <div className={`w-2 h-2 rounded-full ${p._is_up ? "bg-green-500 animate-pulse" : "bg-red-500"}`} />
                </div>
                <div className="col-span-3">
                  <span className="font-mono text-xs font-medium truncate block">{p.name || p.instance || "—"}</span>
                </div>
                <div className="col-span-2">
                  <span className="font-mono text-xs text-muted-foreground">{p["remote-as"] || p.remote_as || "—"}</span>
                </div>
                <div className="col-span-3">
                  <span className="font-mono text-xs text-muted-foreground truncate block">{p["remote-address"] || p.address || p["remote.address"] || "—"}</span>
                </div>
                <div className="col-span-3 flex items-center gap-2">
                  <StatusBadge status={p._status} />
                  {p.uptime && <span className="text-[10px] text-muted-foreground/70 font-mono">{p.uptime}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
