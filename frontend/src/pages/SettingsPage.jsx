import { useState, useEffect } from "react";
import api from "@/lib/api";
import { Download, RefreshCw, CheckCircle2, Github, Terminal, Clock, Database, Wifi, WifiOff, Save, Info, Eye, EyeOff, AlertCircle, Cpu, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";

// ─── InfluxDB Section ────────────────────────────────────────────────────────
function InfluxDBSection() {
  const [cfg, setCfg] = useState({ url: "", token: "", org: "", bucket: "noc-sentinel" });
  const [status, setStatus] = useState(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [showToken, setShowToken] = useState(false);

  useEffect(() => {
    api.get("/metrics/status")
      .then(r => {
        setStatus(r.data);
        if (r.data.url) setCfg(c => ({ ...c, url: r.data.url || "", org: r.data.org || "", bucket: r.data.bucket || "noc-sentinel" }));
      })
      .catch(() => { });
  }, []);

  const handleSave = async () => {
    if (!cfg.url || !cfg.token || !cfg.org) { toast.error("URL, Token, dan Org wajib diisi"); return; }
    setSaving(true);
    try {
      await api.post("/system/save-influxdb-config", cfg);
      toast.success("Disimpan. Restart backend untuk mengaktifkan.");
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal simpan"); }
    setSaving(false);
  };

  const handleTest = async () => {
    if (!cfg.url || !cfg.token || !cfg.org) { toast.error("Isi URL, Token, Org dahulu"); return; }
    setTesting(true);
    try {
      await api.post("/system/save-influxdb-config", cfg);
      const r = await api.post("/metrics/test-connection");
      setStatus({ ...r.data, enabled: true });
      toast.success(`Berhasil! InfluxDB v${r.data.version}`);
    } catch (e) {
      const msg = e.response?.data?.detail || "Koneksi gagal";
      setStatus({ enabled: true, connected: false, error: msg });
      toast.error(msg);
    }
    setTesting(false);
  };

  return (
    <div className="bg-card border border-border rounded-sm p-4 sm:p-6 space-y-4" data-testid="influxdb-section">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-sm bg-blue-500/10 flex items-center justify-center">
            <Database className="w-4 h-4 text-blue-400" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold font-['Rajdhani']">InfluxDB Time-Series</h2>
            <p className="text-[10px] sm:text-xs text-muted-foreground">Simpan metrik historis dengan resolusi tinggi</p>
          </div>
        </div>
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-[10px] font-medium border ${status?.connected ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-secondary text-muted-foreground border-border"
          }`}>
          {status?.connected ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
          {status?.connected ? `Terhubung (v${status.version})` : "Tidak Terhubung"}
        </div>
      </div>

      {/* Info */}
      <div className="flex items-start gap-2 p-3 rounded-sm bg-blue-500/10 border border-blue-500/20 text-xs text-blue-300">
        <Info className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
        <div>
          <p className="font-semibold mb-0.5">Keuntungan InfluxDB vs MongoDB:</p>
          <ul className="list-disc ml-3 space-y-0.5 text-blue-300/80">
            <li>Simpan metrik hingga <strong>bulan/tahun</strong> (MongoDB default 7 hari)</li>
            <li>Query bandwidth, CPU, memory per menit / jam / hari</li>
            <li>Setiap polling (30 detik) tersimpan dengan resolusi tinggi</li>
          </ul>
        </div>
      </div>

      {/* Form fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2 space-y-1.5">
          <Label className="text-xs text-muted-foreground">URL InfluxDB</Label>
          <Input value={cfg.url} onChange={e => setCfg(c => ({ ...c, url: e.target.value }))}
            placeholder="http://localhost:8086" className="rounded-sm bg-background font-mono text-xs" />
          <p className="text-[10px] text-muted-foreground/60">Contoh: http://localhost:8086 atau http://192.168.1.100:8086</p>
        </div>

        <div className="sm:col-span-2 space-y-1.5">
          <Label className="text-xs text-muted-foreground">API Token</Label>
          <div className="relative">
            <Input type={showToken ? "text" : "password"} value={cfg.token}
              onChange={e => setCfg(c => ({ ...c, token: e.target.value }))}
              placeholder="Token dari: influx auth create --all-access"
              className="rounded-sm bg-background font-mono text-xs pr-10" />
            <button onClick={() => setShowToken(!showToken)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              {showToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Organization</Label>
          <Input value={cfg.org} onChange={e => setCfg(c => ({ ...c, org: e.target.value }))}
            placeholder="nama-organisasi" className="rounded-sm bg-background font-mono text-xs" />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Bucket</Label>
          <Input value={cfg.bucket} onChange={e => setCfg(c => ({ ...c, bucket: e.target.value }))}
            placeholder="noc-sentinel" className="rounded-sm bg-background font-mono text-xs" />
        </div>
      </div>

      {status?.error && (
        <div className="flex items-center gap-2 p-3 rounded-sm bg-red-500/10 border border-red-500/20 text-xs text-red-400">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" /> <span>{status.error}</span>
        </div>
      )}

      <div className="flex gap-2 pt-2 border-t border-border/50">
        <Button onClick={handleTest} disabled={testing || saving} size="sm" variant="outline" className="rounded-sm gap-2">
          {testing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Wifi className="w-3.5 h-3.5" />}
          {testing ? "Testing..." : "Test Koneksi"}
        </Button>
        <Button onClick={handleSave} disabled={saving || testing} size="sm" className="rounded-sm gap-2">
          <Save className="w-3.5 h-3.5" /> {saving ? "Menyimpan..." : "Simpan"}
        </Button>
      </div>

      {/* Collapsible install guide */}
      <details className="group">
        <summary className="text-xs text-muted-foreground cursor-pointer hover:text-foreground flex items-center gap-1.5 select-none">
          <span className="group-open:rotate-90 inline-block transition-transform">▶</span>
          Panduan Instalasi InfluxDB di Server
        </summary>
        <div className="mt-3 space-y-2 text-xs font-mono">
          <div className="p-3 rounded-sm bg-secondary/30 border border-border space-y-1">
            <p className="font-sans text-muted-foreground font-semibold">1. Tambah InfluxDB repository (Ubuntu/Debian):</p>
            <p className="text-green-400">curl --silent --location -O https://repos.influxdata.com/influxdata-archive.key</p>
            <p className="text-green-400 text-[10px] break-all">gpg --show-keys --with-fingerprint --with-colons ./influxdata-archive.key 2&gt;&amp;1 | grep -q '^fpr:\+24C975CBA61A024EE1B631787C3D57159FC2F927:$' &amp;&amp; cat influxdata-archive.key | gpg --dearmor | sudo tee /etc/apt/keyrings/influxdata-archive.gpg &gt; /dev/null &amp;&amp; echo 'deb [signed-by=/etc/apt/keyrings/influxdata-archive.gpg] https://repos.influxdata.com/debian stable main' | sudo tee /etc/apt/sources.list.d/influxdata.list</p>
            <p className="text-green-400">sudo apt-get update &amp;&amp; sudo apt-get install influxdb2 -y</p>
            <p className="text-green-400">sudo systemctl enable --now influxdb</p>
          </div>
          <div className="p-3 rounded-sm bg-secondary/30 border border-border space-y-1">
            <p className="font-sans text-muted-foreground font-semibold">2. Setup awal (jalankan sekali):</p>
            <p className="text-green-400">influx setup</p>
            <p className="font-sans text-[10px] text-muted-foreground"># Masukkan: username, password, org name, bucket name, retention (0 = tak terbatas)</p>
          </div>
          <div className="p-3 rounded-sm bg-secondary/30 border border-border space-y-1">
            <p className="font-sans text-muted-foreground font-semibold">3. Buat API Token:</p>
            <p className="text-green-400">influx auth create --org nama-org --all-access</p>
            <p className="font-sans text-[10px] text-muted-foreground"># Salin token yang muncul → paste ke field Token di atas</p>
          </div>
          <div className="p-3 rounded-sm bg-secondary/30 border border-border space-y-1">
            <p className="font-sans text-muted-foreground font-semibold">4. Install Python library (di server):</p>
            <p className="text-green-400">cd /path/noc-sentinel/backend</p>
            <p className="text-green-400">pip install influxdb-client==1.50.0</p>
          </div>
          <p className="font-sans text-[10px] text-muted-foreground/70">Setelah selesai: isi form di atas → Test → Simpan → Restart backend.</p>
        </div>
      </details>
    </div>
  );
}

// ─── GenieACS Section ────────────────────────────────────────────────────────
function GenieACSSection() {
  const [cfg, setCfg] = useState({ url: "", username: "", password: "" });
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [showPwd, setShowPwd] = useState(false);
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    api.get("/system/genieacs-config").then(r => {
      setCfg(c => ({ ...c, url: r.data.url || "", username: r.data.username || "" }));
    }).catch(() => { });
  }, []);

  const handleSave = async () => {
    if (!cfg.url) { toast.error("GENIEACS_URL wajib diisi"); return; }
    setSaving(true);
    try {
      const r = await api.post("/system/save-genieacs-config", cfg);
      toast.success(r.data.message);
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal simpan"); }
    setSaving(false);
  };

  const handleTest = async () => {
    if (!cfg.url) { toast.error("Isi URL dahulu"); return; }
    setTesting(true);
    setTestResult(null);
    try {
      await api.post("/system/save-genieacs-config", cfg);
      const r = await api.get("/genieacs/test-connection");
      setTestResult(r.data);
      if (r.data.success) toast.success(r.data.message);
      else toast.error(r.data.error || "Koneksi gagal");
    } catch (e) { toast.error(e.response?.data?.detail || "Koneksi gagal"); }
    setTesting(false);
  };

  return (
    <div className="bg-card border border-border rounded-sm p-4 sm:p-6 space-y-4" data-testid="genieacs-section">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-sm bg-cyan-500/10 flex items-center justify-center">
            <Cpu className="w-4 h-4 text-cyan-400" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold font-['Rajdhani']">GenieACS / TR-069</h2>
            <p className="text-[10px] sm:text-xs text-muted-foreground">Konfigurasi ACS server untuk manajemen CPE pelanggan</p>
          </div>
        </div>
        {testResult && (
          <div className={`flex items-center gap-1.5 px-2 py-1 rounded-sm text-[10px] font-medium border ${testResult.success ? "bg-green-500/10 text-green-400 border-green-500/20" : "bg-red-500/10 text-red-400 border-red-500/20"
            }`}>
            {testResult.success ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {testResult.success ? `Terhubung — ${testResult.stats?.total ?? 0} CPE` : "Gagal Terhubung"}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2 space-y-1.5">
          <Label className="text-xs text-muted-foreground">GenieACS URL (NBI)<span className="text-destructive ml-1">*</span></Label>
          <Input value={cfg.url} onChange={e => setCfg(c => ({ ...c, url: e.target.value }))}
            placeholder="http://10.x.x.x:7557" className="rounded-sm font-mono text-xs" />
          <p className="text-[10px] text-muted-foreground">Port NBI default GenieACS adalah 7557</p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Username</Label>
          <Input value={cfg.username} onChange={e => setCfg(c => ({ ...c, username: e.target.value }))}
            placeholder="admin" className="rounded-sm text-xs" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Password</Label>
          <div className="relative">
            <Input value={cfg.password} onChange={e => setCfg(c => ({ ...c, password: e.target.value }))}
              type={showPwd ? "text" : "password"} placeholder={cfg.url ? "(tidak berubah jika kosong)" : ""}
              className="rounded-sm text-xs pr-9" />
            <button type="button" className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              onClick={() => setShowPwd(v => !v)}>
              {showPwd ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>
      </div>

      {testResult && !testResult.success && (
        <div className="flex items-start gap-2 p-3 rounded-sm bg-red-500/10 border border-red-500/20 text-xs text-red-300">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>{testResult.error}</span>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Button onClick={handleSave} disabled={saving} className="rounded-sm gap-2 h-8 text-xs">
          <Save className="w-3.5 h-3.5" />{saving ? "Menyimpan..." : "Simpan"}
        </Button>
        <Button onClick={handleTest} variant="outline" disabled={testing || saving} className="rounded-sm gap-2 h-8 text-xs">
          <Zap className="w-3.5 h-3.5" />{testing ? "Testing..." : "Test Koneksi"}
        </Button>
      </div>

      <details className="text-xs">
        <summary className="cursor-pointer text-muted-foreground hover:text-foreground transition-colors">Cara konfigurasi GenieACS ▸</summary>
        <div className="mt-3 space-y-2 font-mono text-[11px] bg-secondary/20 border border-border rounded-sm p-3">
          <p className="font-sans text-muted-foreground font-semibold">1. Pastikan genieacs-nbi aktif di node GenieACS:</p>
          <p className="text-green-400">systemctl status genieacs-nbi</p>
          <p className="font-sans text-muted-foreground font-semibold mt-2">2. Cek koneksi dari node NOC ke GenieACS:</p>
          <p className="text-green-400">curl http://10.x.x.x:7557/devices?limit=1</p>
          <p className="font-sans text-[10px] text-muted-foreground">Jika dapat JSON → isi URL di atas → Test Koneksi</p>
        </div>
      </details>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const [checking, setChecking] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [updateInfo, setUpdateInfo] = useState(null);
  const [updateLog, setUpdateLog] = useState([]);
  const [updateDone, setUpdateDone] = useState(false);
  const [appInfo, setAppInfo] = useState(null);
  const [serviceName, setServiceName] = useState("noc-backend");
  const [savingSvc, setSavingSvc] = useState(false);

  useEffect(() => {
    api.get("/system/app-info").then(r => {
      setAppInfo(r.data);
      if (r.data.service_name) setServiceName(r.data.service_name);
    }).catch(() => { });
  }, []);

  const saveServiceName = async () => {
    setSavingSvc(true);
    try {
      const r = await api.post("/system/save-service-name", { service_name: serviceName });
      toast.success(r.data.message);
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSavingSvc(false);
  };

  const checkUpdate = async () => {
    setChecking(true); setUpdateInfo(null); setUpdateDone(false); setUpdateLog([]);
    try {
      const r = await api.get("/system/check-update");
      setUpdateInfo(r.data);
      r.data.has_update ? toast.info("Update tersedia!") : toast.success("Aplikasi sudah versi terbaru");
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal cek update"); }
    setChecking(false);
  };

  const performUpdate = async () => {
    if (!updateInfo?.has_update) { toast.error("Tidak ada update"); return; }
    setUpdating(true); setUpdateDone(false); setUpdateLog(["🚀 Memulai update di background..."]);

    try {
      // Mulai background job — langsung return tanpa tunggu selesai
      await api.post("/system/perform-update");

      // Polling setiap 2 detik
      const poll = setInterval(async () => {
        try {
          const s = await api.get("/system/update-status");
          setUpdateLog([...s.data.log]);

          if (s.data.done) {
            clearInterval(poll);
            setUpdating(false);
            if (s.data.success) {
              toast.success("✅ Update berhasil! Silakan reload halaman.");
              setUpdateInfo(null);
              setUpdateDone(true);
            } else {
              toast.error("Update gagal: " + (s.data.error || "lihat log"));
            }
          }
        } catch {
          // network hiccup — lanjut poll
        }
      }, 2000);

      // Safety: berhenti polling setelah 15 menit
      setTimeout(() => clearInterval(poll), 15 * 60 * 1000);

    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal memulai update");
      setUpdateLog(prev => [...prev, `❌ Error: ${e.response?.data?.detail || e.message}`]);
      setUpdating(false);
    }
  };

  return (
    <div className="space-y-4 pb-16" data-testid="settings-page">
      <div>
        <h1 className="text-xl sm:text-2xl md:text-3xl font-bold font-['Rajdhani'] tracking-tight">Pengaturan</h1>
        <p className="text-xs sm:text-sm text-muted-foreground">Pengaturan sistem dan update aplikasi</p>
      </div>

      {/* Update Section */}
      <div className="bg-card border border-border rounded-sm p-4 sm:p-6" data-testid="update-section">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 rounded-sm bg-primary/10 flex items-center justify-center">
            <Github className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-semibold font-['Rajdhani']">Update Aplikasi</h2>
            <p className="text-[10px] sm:text-xs text-muted-foreground">Pull update dari GitHub dan rebuild otomatis</p>
          </div>
        </div>

        <div className="space-y-3">
          {/* Current version info */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 items-center text-[10px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              Versi saat ini:&nbsp;
              <code className="bg-secondary px-1 rounded font-mono">
                {appInfo?.commit ? appInfo.commit.slice(0, 7) : (updateInfo?.current_commit ? updateInfo.current_commit.slice(0, 7) : "—")}
              </code>
            </span>
            {(appInfo?.message || updateInfo?.current_message) && (
              <span className="text-muted-foreground/70 truncate max-w-xs">
                {appInfo?.message || updateInfo?.current_message}
              </span>
            )}
          </div>

          {/* Update status card */}
          {updateInfo && (
            <div className={`p-4 rounded-sm border ${updateInfo.has_update ? 'bg-yellow-500/10 border-yellow-500/30' : 'bg-green-500/10 border-green-500/30'}`}>
              <div className="flex items-center gap-2">
                {updateInfo.has_update
                  ? <><Download className="w-4 h-4 text-yellow-500" /><span className="text-yellow-500 font-medium text-sm">Update Tersedia!</span></>
                  : <><CheckCircle2 className="w-4 h-4 text-green-500" /><span className="text-green-500 font-medium text-sm">Sudah versi terbaru</span></>
                }
              </div>
              {updateInfo.has_update && (
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {updateInfo.commits_behind > 0 && (
                    <p>Tertinggal <span className="font-mono text-foreground">{updateInfo.commits_behind}</span> commit</p>
                  )}
                  {updateInfo.latest_message && (
                    <p>Perubahan terbaru: <span className="text-foreground">{updateInfo.latest_message}</span></p>
                  )}
                  {updateInfo.latest_date && (
                    <p>Tanggal: <span className="font-mono">{updateInfo.latest_date}</span></p>
                  )}
                  <p className="text-[10px]">
                    Commit: <code className="bg-secondary px-1 rounded">{updateInfo.latest_commit?.slice(0, 7)}</code>
                  </p>
                </div>
              )}
              {updateInfo.message && !updateInfo.has_update && (
                <p className="mt-1 text-xs text-muted-foreground">{updateInfo.message}</p>
              )}
            </div>
          )}

          {/* Update log */}
          {updateLog.length > 0 && (
            <div className="bg-secondary/30 border border-border rounded-sm p-3">
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="w-4 h-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground font-medium">Log Update</span>
              </div>
              <div className="font-mono text-xs space-y-1 max-h-48 overflow-y-auto">
                {updateLog.map((log, i) => (
                  <div key={i} className={
                    log.startsWith('Error') || log.toLowerCase().includes('gagal') ? 'text-red-400' :
                      log.startsWith('===') || log.includes('selesai') ? 'text-green-400 font-semibold' :
                        'text-foreground/70'
                  }>{log}</div>
                ))}
                {updating && <div className="text-primary animate-pulse">Proses berjalan...</div>}
              </div>
            </div>
          )}

          {/* Konfigurasi Service Name */}
          <div className="p-3 rounded-sm border border-border bg-secondary/20 space-y-2">
            <p className="text-xs font-medium text-muted-foreground">⚙️ Konfigurasi Service Systemd</p>
            <div className="flex gap-2 items-center">
              <Input
                value={serviceName}
                onChange={e => setServiceName(e.target.value)}
                placeholder="noc-backend"
                className="h-7 text-xs rounded-sm font-mono flex-1"
              />
              <Button size="sm" className="rounded-sm h-7 text-xs gap-1" onClick={saveServiceName} disabled={savingSvc}>
                <Save className="w-3 h-3" />{savingSvc ? "..." : "Simpan"}
              </Button>
            </div>
            <details className="text-[10px] text-muted-foreground/70">
              <summary className="cursor-pointer hover:text-muted-foreground">Jika restart service gagal saat update ▸</summary>
              <div className="mt-2 font-mono p-2 bg-secondary/40 rounded-sm space-y-1">
                <p className="text-green-400">echo 'www-data ALL=(ALL) NOPASSWD: /bin/systemctl restart {serviceName}' | sudo tee /etc/sudoers.d/noc-sentinel</p>
                <p className="text-green-400">sudo chmod 0440 /etc/sudoers.d/noc-sentinel</p>
              </div>
            </details>
          </div>

          {/* Action buttons */}
          <div className="flex flex-wrap gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={checkUpdate} disabled={checking || updating}
              className="rounded-sm gap-2 flex-1 sm:flex-none" data-testid="check-update-btn">
              <RefreshCw className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} />
              {checking ? "Mengecek..." : "Cek Update"}
            </Button>
            <Button size="sm" onClick={performUpdate} disabled={updating || !updateInfo?.has_update}
              className="rounded-sm gap-2 flex-1 sm:flex-none" data-testid="perform-update-btn">
              <Download className={`w-4 h-4 ${updating ? 'animate-bounce' : ''}`} />
              {updating ? "Mengupdate..." : "Update Sekarang"}
            </Button>
            {updateDone && (
              <Button size="sm" variant="default" onClick={() => window.location.reload()}
                className="rounded-sm gap-2 flex-1 sm:flex-none bg-green-600 hover:bg-green-700" data-testid="reload-btn">
                <RefreshCw className="w-4 h-4" /> Reload Halaman
              </Button>
            )}
          </div>

          <div className="p-3 bg-secondary/20 rounded-sm border border-dashed border-border">
            <p className="text-[10px] text-muted-foreground">
              <strong>Cara kerja:</strong> Push kode ke GitHub dari PC → Klik "Cek Update" di sini → Klik "Update Sekarang" → Tunggu log selesai → Reload halaman.
            </p>
          </div>
        </div>
      </div>

      {/* InfluxDB Section */}
      <InfluxDBSection />

      {/* GenieACS Section */}
      <GenieACSSection />

      {/* System Info */}
      <div className="bg-card border border-border rounded-sm p-6">
        <h2 className="text-lg font-semibold font-['Rajdhani'] mb-4">Informasi Sistem</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          {[
            ["Aplikasi", appInfo?.version || "NOC-SENTINEL v2.5"],
            ["Commit", appInfo?.commit ? appInfo.commit.slice(0, 7) : "—"],
            ["Update", appInfo?.date || "—"],
            ["Backend", "FastAPI + Python"],
            ["Frontend", "React + Tailwind"],
            ["Database", "MongoDB + InfluxDB"],
          ].map(([label, val]) => (
            <div key={label} className="flex justify-between p-2 bg-secondary/20 rounded-sm">
              <span className="text-muted-foreground">{label}</span>
              <span className="font-mono text-right">{val}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

