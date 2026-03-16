import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { Search, RefreshCw, Server, WifiOff, ShieldCheck, ShieldX, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0; let val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return `${val.toFixed(1)} ${units[i]}`;
}

function formatPackets(n) {
  if (!n) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function ActionBadge({ action }) {
  if (!action) return null;
  if (action === "accept" || action === "passthrough")
    return <Badge className="rounded-sm text-[10px] border bg-green-500/10 text-green-500 border-green-500/20 gap-1"><ShieldCheck className="w-3 h-3" />{action}</Badge>;
  if (action === "drop" || action === "reject" || action === "tarpit")
    return <Badge className="rounded-sm text-[10px] border bg-red-500/10 text-red-400 border-red-500/20 gap-1"><ShieldX className="w-3 h-3" />{action}</Badge>;
  return <Badge className="rounded-sm text-[10px] border bg-yellow-500/10 text-yellow-500 border-yellow-500/20 gap-1"><ShieldAlert className="w-3 h-3" />{action}</Badge>;
}

export default function FirewallPage() {
  const [devices, setDevices] = useState([]);
  const [selectedDevice, setSelectedDevice] = useState("");
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [chainType, setChainType] = useState("filter");

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
      const r = await api.get("/firewall/rules", { params: { device_id: selectedDevice, chain_type: chainType } });
      setRules(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to fetch firewall rules");
      setRules([]);
    }
    setLoading(false);
  }, [selectedDevice, chainType]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filtered = search
    ? rules.filter(r => JSON.stringify(r).toLowerCase().includes(search.toLowerCase()))
    : rules;

  const dropRules = rules.filter(r => r._is_drop && !r._disabled).length;
  const acceptRules = rules.filter(r => r._is_accept && !r._disabled).length;
  const disabledRules = rules.filter(r => r._disabled).length;

  return (
    <div className="space-y-3 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Firewall Rules</h1>
          <p className="text-xs sm:text-sm text-muted-foreground">Monitor firewall rules dengan byte/packet counters</p>
        </div>
        {/* Chain type selector */}
        <div className="flex gap-1">
          {["filter", "nat", "mangle"].map(ct => (
            <Button key={ct} variant={chainType === ct ? "default" : "outline"} size="sm"
              className="rounded-sm text-xs capitalize" onClick={() => setChainType(ct)}>
              {ct}
            </Button>
          ))}
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
              <Input placeholder="Cari rule / comment / IP..." value={search} onChange={e => setSearch(e.target.value)}
                className="pl-9 rounded-sm bg-card h-9 text-xs" />
            </div>
            <Button variant="outline" size="icon" onClick={fetchData} className="rounded-sm h-9 w-9 flex-shrink-0">
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </div>

      {/* Stats */}
      {selectedDevice && !error && rules.length > 0 && (
        <div className="flex items-center gap-4 text-xs px-1 flex-wrap">
          <span className="text-muted-foreground">Total Rules: <span className="text-foreground font-mono">{rules.length}</span></span>
          <span className="text-green-500">Accept: <span className="font-mono">{acceptRules}</span></span>
          <span className="text-red-400">Drop: <span className="font-mono">{dropRules}</span></span>
          {disabledRules > 0 && <span className="text-muted-foreground/60">Disabled: <span className="font-mono">{disabledRules}</span></span>}
        </div>
      )}

      {/* Content */}
      {!selectedDevice ? (
        <div className="bg-card border border-border rounded-sm p-12 text-center">
          <Server className="w-12 h-12 mx-auto mb-3 text-muted-foreground/30" />
          <p className="text-sm text-muted-foreground">Pilih perangkat MikroTik untuk melihat firewall rules</p>
        </div>
      ) : error ? (
        <div className="bg-card border border-red-500/30 rounded-sm p-8 text-center">
          <WifiOff className="w-10 h-10 mx-auto mb-3 text-red-500/50" />
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      ) : loading ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <RefreshCw className="w-6 h-6 mx-auto mb-2 text-muted-foreground animate-spin" />
          <p className="text-sm text-muted-foreground">Mengambil firewall rules...</p>
        </div>
      ) : rules.length === 0 ? (
        <div className="bg-card border border-border rounded-sm p-8 text-center">
          <p className="text-sm text-muted-foreground">Tidak ada firewall {chainType} rules</p>
        </div>
      ) : (
        <div className="bg-card border border-border rounded-sm overflow-hidden">
          <div className="grid grid-cols-12 text-[10px] text-muted-foreground uppercase tracking-wider px-3 py-2 border-b border-border bg-muted/30">
            <div className="col-span-1">#</div>
            <div className="col-span-2">Chain</div>
            <div className="col-span-2">Action</div>
            <div className="col-span-3">Src → Dst</div>
            <div className="col-span-2">Bytes</div>
            <div className="col-span-2">Packets</div>
          </div>
          {filtered.map((r, i) => (
            <div
              key={r[".id"] || i}
              className={`grid grid-cols-12 items-center px-3 py-2 border-b border-border/50 last:border-0 hover:bg-muted/20 text-xs transition-colors ${r._disabled ? "opacity-40" : ""}`}
            >
              <div className="col-span-1 text-[10px] text-muted-foreground font-mono">{i + 1}</div>
              <div className="col-span-2">
                <span className="font-mono text-xs text-muted-foreground">{r._chain || "—"}</span>
              </div>
              <div className="col-span-2">
                <ActionBadge action={r._action} />
              </div>
              <div className="col-span-3 space-y-0.5">
                {r._comment && <p className="text-[10px] text-primary/80 font-medium truncate">{r._comment}</p>}
                <p className="text-[10px] text-muted-foreground font-mono truncate">
                  {r["src-address"] || r.src || "*"} → {r["dst-address"] || r.dst || "*"}
                </p>
              </div>
              <div className="col-span-2 font-mono text-xs">
                {r._bytes > 0
                  ? <span className={r._bytes > 1024 ** 3 ? "text-red-400" : r._bytes > 1024 ** 2 ? "text-yellow-500" : "text-foreground"}>{formatBytes(r._bytes)}</span>
                  : <span className="text-muted-foreground/50">—</span>
                }
              </div>
              <div className="col-span-2 font-mono text-xs text-muted-foreground">
                {r._packets > 0 ? formatPackets(r._packets) : <span className="text-muted-foreground/50">—</span>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
