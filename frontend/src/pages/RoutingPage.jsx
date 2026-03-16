import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Search, RefreshCw, Server, WifiOff, CheckCircle, AlertCircle, Route, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const PROTO_COLORS = {
  bgp: "bg-purple-500/10 text-purple-400 border-purple-500/20",
  ospf: "bg-blue-500/10 text-blue-400 border-blue-500/20",
  connected: "bg-green-500/10 text-green-400 border-green-500/20",
  static: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  rip: "bg-yellow-500/10 text-yellow-400 border-yellow-500/20",
};

export default function RoutingPage() {
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [routes, setRoutes] = useState([]);
  const [ospf, setOspf] = useState({ neighbors: [], instances: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [view, setView] = useState("routes"); // routes | ospf

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
      const [routeRes, ospfRes] = await Promise.allSettled([
        api.get("/routing/routes", { params: { device_id: selectedDevice, limit: 200 } }),
        api.get("/routing/ospf", { params: { device_id: selectedDevice } }),
      ]);
      if (routeRes.status === "fulfilled") setRoutes(routeRes.value.data);
      if (ospfRes.status === "fulfilled") setOspf(ospfRes.value.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to fetch routing data");
    }
    setLoading(false);
  }, [selectedDevice]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = search
    ? routes.filter(r => JSON.stringify(r).toLowerCase().includes(search.toLowerCase()))
    : routes;

  const activeRoutes = routes.filter(r => r._active).length;
  const fullNeighbors = ospf.neighbors?.filter(n => n._is_full).length || 0;

  return (
    <div className="space-y-3 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">OSPF / Routing</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Monitor routing table dan OSPF neighbors</p>
        </div>
        <div className="flex gap-1">
          <Button variant={view === "routes" ? "default" : "outline"} size="sm" className="rounded-sm text-xs gap-1.5" onClick={() => setView("routes")}>
            <Route className="w-3.5 h-3.5" /> IP Routes
          </Button>
          <Button variant={view === "ospf" ? "default" : "outline"} size="sm" className="rounded-sm text-xs gap-1.5" onClick={() => setView("ospf")}>
            <Globe className="w-3.5 h-3.5" /> OSPF
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
              <Input placeholder="Cari network / gateway..." value={search} onChange={e => setSearch(e.target.value)}
                className="pl-9 rounded-sm bg-card h-9 text-xs" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchData} className="rounded-sm h-9 w-9 flex-shrink-0">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Stats */}
      {selectedDevice && !error && (
        <div className="flex items-center gap-4 text-xs px-1 flex-wrap">
          <span className="text-muted-foreground">Routes Aktif: <span className="text-foreground font-mono">{activeRoutes}</span></span>
          <span className="text-muted-foreground">Total: <span className="font-mono">{routes.length}</span></span>
          {ospf.neighbors?.length > 0 && (
            <>
              <span className="text-muted-foreground">OSPF Neighbors: <span className="font-mono">{ospf.neighbors.length}</span></span>
              <span className="text-green-500">Full: <span className="font-mono">{fullNeighbors}</span></span>
            </>
          )}
        </div>
      )}

      {/* Content */}
      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Pilih perangkat MikroTik untuk melihat routing</p>
        </div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-8 text-center">
          <WifiOff className="w-10 h-10 mx-auto mb-3 text-red-500/50" />
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      ) : loading ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <RefreshCw className="w-6 h-6 mx-auto mb-2 text-muted-foreground animate-spin" />
          <p className="text-sm text-muted-foreground">Mengambil data routing...</p>
        </div>
      ) : view === "routes" ? (
        routes.length === 0 ? (
          <div className="bg-card border border-border rounded-sm p-8 text-center">
            <p className="text-sm text-muted-foreground">Tidak ada route ditemukan</p>
          </div>
        ) : (
          <div className="bg-card border border-border rounded-sm overflow-hidden">
            <div className="grid grid-cols-12 text-[10px] text-muted-foreground uppercase tracking-wider px-3 py-2 border-b border-border bg-muted/30">
              <div className="col-span-1">Active</div>
              <div className="col-span-4">Destination</div>
              <div className="col-span-3">Gateway</div>
              <div className="col-span-2">Protocol</div>
              <div className="col-span-2">Distance</div>
            </div>
            {filtered.map((r, i) => (
              <div key={r[".id"] || i} className="grid grid-cols-12 items-center px-3 py-2 border-b border-border/50 last:border-0 hover:bg-muted/20 transition-colors">
                <div className="col-span-1">
                  {r._active
                    ? <CheckCircle className="w-3.5 h-3.5 text-green-500" />
                    : <div className="w-3.5 h-3.5 rounded-full bg-muted-foreground/20" />}
                </div>
                <div className="col-span-4">
                  <span className="font-mono text-xs">{r._dst || r["dst-address"] || "—"}</span>
                </div>
                <div className="col-span-3">
                  <span className="font-mono text-xs text-muted-foreground">{r._gateway || r.gateway || "connected"}</span>
                </div>
                <div className="col-span-2">
                  <Badge className={`rounded-sm text-[10px] border ${PROTO_COLORS[r._protocol] || "bg-muted/50 text-muted-foreground border-border"}`}>
                    {r._protocol || "—"}
                  </Badge>
                </div>
                <div className="col-span-2">
                  <span className="text-xs text-muted-foreground font-mono">{r._distance ?? r.distance ?? "—"}</span>
                </div>
              </div>
            ))}
          </div>
        )
      ) : (
        /* OSPF view */
        <div className="space-y-3">
          {ospf.neighbors?.length === 0 ? (
            <div className="bg-card border border-border rounded-sm p-8 text-center">
              <p className="text-sm text-muted-foreground">Tidak ada OSPF neighbor atau OSPF belum dikonfigurasi</p>
            </div>
          ) : (
            <div className="bg-card border border-border rounded-sm overflow-hidden">
              <div className="px-3 py-2 border-b border-border bg-muted/30 text-[10px] text-muted-foreground uppercase tracking-wider">
                OSPF Neighbors ({ospf.neighbors?.length || 0})
              </div>
              {ospf.neighbors?.map((n, i) => (
                <div key={n[".id"] || i} className="grid grid-cols-12 items-center px-3 py-2.5 border-b border-border/50 last:border-0 hover:bg-muted/20">
                  <div className="col-span-1">
                    <div className={`w-2 h-2 rounded-full ${n._is_full ? "bg-green-500 animate-pulse" : "bg-yellow-500"}`} />
                  </div>
                  <div className="col-span-3 font-mono text-xs">{n.address || n.neighbor || "—"}</div>
                  <div className="col-span-3 text-xs text-muted-foreground font-mono">{n.interface || "—"}</div>
                  <div className="col-span-3">
                    <Badge className={`rounded-sm text-[10px] border ${n._is_full ? "bg-green-500/10 text-green-500 border-green-500/20" : "bg-yellow-500/10 text-yellow-500 border-yellow-500/20"}`}>
                      {n._state || "—"}
                    </Badge>
                  </div>
                  <div className="col-span-2 text-[10px] text-muted-foreground font-mono">{n["dead-timer"] || n.uptime || ""}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
