import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "@/App";
import api from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend
} from "recharts";
import {
  Receipt, Users, Package, LayoutDashboard, RefreshCw, Plus,
  Search, CheckCircle2, Clock, AlertTriangle, Trash2, Edit2,
  DollarSign, MessageCircle, ChevronDown, X, Download, Upload,
  PhoneCall, ArrowUpDown, WifiOff, Wifi, Printer, Send, TrendingUp
} from "lucide-react";

// ── Utilities ─────────────────────────────────────────────────────────────────

const Rp = (n) => `Rp ${(Number(n) || 0).toLocaleString("id-ID")}`;

const STATUS_MAP = {
  paid: { label: "Lunas", cls: "bg-green-500/15 text-green-400 border-green-500/30" },
  unpaid: { label: "Belum Bayar", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
  overdue: { label: "Jatuh Tempo", cls: "bg-red-500/15 text-red-400 border-red-500/30" },
};

function StatusBadge({ status }) {
  const s = STATUS_MAP[status] || STATUS_MAP.unpaid;
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-sm border ${s.cls}`}>
      {status === "paid" && <CheckCircle2 className="w-2.5 h-2.5" />}
      {status === "overdue" && <AlertTriangle className="w-2.5 h-2.5" />}
      {status === "unpaid" && <Clock className="w-2.5 h-2.5" />}
      {s.label}
    </span>
  );
}

// ── Print Invoice (CSS print-only) ────────────────────────────────────────────
function printInvoice(invoice, pkgName) {
  const html = `
    <html><head><title>${invoice.invoice_number}</title><style>
      body { font-family: Arial, sans-serif; padding: 32px; color: #111; }
      h1 { font-size: 22px; margin: 0 0 4px; }
      .sub { color: #666; font-size: 12px; margin: 0 0 24px; }
      table { width: 100%; border-collapse: collapse; margin: 16px 0; }
      td, th { padding: 8px 12px; border: 1px solid #ddd; font-size: 13px; }
      th { background: #f5f5f5; text-align: left; font-weight: 600; }
      .total { font-size: 18px; font-weight: bold; color: #1a1a1a; }
      .status { padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: bold; display: inline-block; }
      .paid { background: #d1fae5; color: #065f46; }
      .unpaid { background: #fef3c7; color: #92400e; }
      .overdue { background: #fee2e2; color: #991b1b; }
      .footer { margin-top: 32px; font-size: 11px; color: #999; border-top: 1px solid #eee; padding-top: 12px; }
    </style></head><body>
    <h1>🌐 ARBA Monitoring System</h1>
    <p class="sub">Invoice Tagihan Berlangganan Internet</p>
    <table>
      <tr><th colspan="2">INVOICE #${invoice.invoice_number}</th></tr>
      <tr><td>Status</td><td><span class="status ${invoice.status}">${invoice.status.toUpperCase()}</span></td></tr>
      <tr><td>Nama Pelanggan</td><td>${invoice.customer_name || '—'}</td></tr>
      <tr><td>Username</td><td>${invoice.customer_username || '—'}</td></tr>
      <tr><td>No. Telepon</td><td>${invoice.customer_phone || '—'}</td></tr>
      <tr><td>Paket</td><td>${pkgName || invoice.package_name || '—'}</td></tr>
      <tr><td>Periode</td><td>${invoice.period_start} s/d ${invoice.period_end}</td></tr>
      <tr><td>Jatuh Tempo</td><td>${invoice.due_date}</td></tr>
      <tr><td>Tagihan</td><td>${Rp(invoice.amount)}</td></tr>
      ${invoice.discount ? `<tr><td>Diskon</td><td>- ${Rp(invoice.discount)}</td></tr>` : ''}
      <tr><td><strong>Total</strong></td><td class="total">${Rp(invoice.total)}</td></tr>
      ${invoice.status === 'paid' ? `<tr><td>Dibayar Via</td><td>${invoice.payment_method || '—'} (${invoice.paid_at?.slice(0, 10) || ''})</td></tr>` : ''}
    </table>
    <p class="footer">Dicetak: ${new Date().toLocaleString('id-ID')} • Terima kasih atas kepercayaan Anda 🙏</p>
    </body></html>
  `;
  const w = window.open('', '_blank', 'width=700,height=900');
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => { w.print(); w.close(); }, 400);
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, color }) {
  return (
    <div className={`bg-card border border-border rounded-sm p-4 border-l-2 ${color}`}>
      <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className="text-xl font-bold font-mono mt-1">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Invoice Detail Modal ──────────────────────────────────────────────────────

function InvoiceModal({ invoice, packages, onClose, onPaid, onDelete }) {
  const [method, setMethod] = useState("cash");
  const [paying, setPaying] = useState(false);
  const [waLoading, setWaLoading] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [mtDisabled, setMtDisabled] = useState(invoice.mt_disabled || false);

  const handlePay = async () => {
    setPaying(true);
    try {
      const r = await api.patch(`/billing/invoices/${invoice.id}/pay`, { payment_method: method });
      toast.success(r.data.message || "Invoice ditandai lunas!");
      onPaid();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setPaying(false);
  };

  const sendWa = async () => {
    setWaLoading(true);
    try {
      const r = await api.get(`/billing/invoices/${invoice.id}/whatsapp-link`);
      window.open(r.data.link, "_blank");
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal generate link WA"); }
    setWaLoading(false);
  };

  const toggleMikroTik = async () => {
    setDisabling(true);
    try {
      const action = mtDisabled ? "enable" : "disable";
      const r = await api.post(`/billing/invoices/${invoice.id}/${action}-user`);
      toast.success(r.data.message);
      setMtDisabled(!mtDisabled);
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setDisabling(false);
  };

  const handlePrint = () => {
    const pkg = packages.find(p => p.id === invoice.package_id);
    printInvoice(invoice, pkg?.name);
  };

  const pkg = packages.find(p => p.id === invoice.package_id) || {};

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <div>
            <p className="text-xs font-mono text-muted-foreground">{invoice.invoice_number}</p>
            <h3 className="font-semibold">{invoice.customer_name || "—"}</h3>
          </div>
          <div className="flex items-center gap-2">
            <StatusBadge status={invoice.status} />
            {mtDisabled && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-sm border border-orange-500/30 text-orange-400 flex items-center gap-1">
                <WifiOff className="w-2.5 h-2.5" /> Diputus
              </span>
            )}
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        <div className="p-4 space-y-3">
          {/* Info */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              ["Username", invoice.customer_username],
              ["Telepon", invoice.customer_phone || "—"],
              ["Paket", invoice.package_name || pkg.name || "—"],
              ["Periode", `${invoice.period_start} s/d ${invoice.period_end}`],
              ["Jatuh Tempo", invoice.due_date],
            ].map(([k, v]) => (
              <div key={k} className="bg-secondary/20 rounded-sm p-2">
                <p className="text-muted-foreground text-[10px]">{k}</p>
                <p className="font-medium">{v}</p>
              </div>
            ))}
            <div className="bg-secondary/20 rounded-sm p-2">
              <p className="text-muted-foreground text-[10px]">Total</p>
              <p className="font-bold text-primary">{Rp(invoice.total)}</p>
            </div>
          </div>

          {invoice.status !== "paid" && (
            <div className="space-y-2 pt-1">
              <Label className="text-xs text-muted-foreground">Metode Pembayaran</Label>
              <div className="flex gap-2">
                {["cash", "transfer", "qris"].map(m => (
                  <button key={m} onClick={() => setMethod(m)}
                    className={`flex-1 py-1.5 text-xs rounded-sm border capitalize transition-colors ${method === m ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground"
                      }`}>{m}</button>
                ))}
              </div>
              <Button onClick={handlePay} disabled={paying} className="w-full rounded-sm gap-2">
                <CheckCircle2 className="w-4 h-4" />{paying ? "Memproses..." : "Tandai Lunas"}
              </Button>
            </div>
          )}

          {invoice.status === "paid" && (
            <div className="p-2 bg-green-500/10 border border-green-500/20 rounded-sm text-xs text-green-400">
              ✓ Lunas via <strong>{invoice.payment_method}</strong> • {invoice.paid_at?.slice(0, 10)}
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="grid grid-cols-2 gap-2 p-4 pt-0">
          <Button variant="outline" size="sm" className="rounded-sm gap-1 text-xs"
            onClick={sendWa} disabled={waLoading}>
            <MessageCircle className="w-3.5 h-3.5 text-green-400" />
            {waLoading ? "..." : "Kirim WA"}
          </Button>
          <Button variant="outline" size="sm" className="rounded-sm gap-1 text-xs"
            onClick={handlePrint}>
            <Printer className="w-3.5 h-3.5 text-blue-400" /> Cetak
          </Button>
          <Button variant="outline" size="sm"
            className={`rounded-sm gap-1 text-xs ${mtDisabled ? "border-green-500/30 text-green-400 hover:bg-green-500/10" : "border-orange-500/30 text-orange-400 hover:bg-orange-500/10"
              }`}
            onClick={toggleMikroTik} disabled={disabling}>
            {mtDisabled ? <Wifi className="w-3.5 h-3.5" /> : <WifiOff className="w-3.5 h-3.5" />}
            {disabling ? "..." : mtDisabled ? "Enable User" : "Putus User"}
          </Button>
          <Button variant="outline" size="sm" className="rounded-sm gap-1 text-xs text-destructive hover:bg-destructive/10"
            onClick={onDelete}>
            <Trash2 className="w-3.5 h-3.5" /> Hapus
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Dashboard Tab ─────────────────────────────────────────────────────────────

function DashboardTab({ month, year }) {
  const [stats, setStats] = useState(null);
  const [recent, setRecent] = useState([]);
  const [trend, setTrend] = useState([]);

  useEffect(() => {
    api.get("/billing/stats", { params: { month, year } }).then(r => setStats(r.data)).catch(() => { });
    api.get("/billing/invoices", { params: { month, year, status: "overdue" } }).then(r => setRecent(r.data.slice(0, 5))).catch(() => { });
    api.get("/billing/monthly-summary", { params: { months: 6 } }).then(r => setTrend(r.data)).catch(() => { });
  }, [month, year]);

  const fmtRp = (val) => {
    if (val >= 1_000_000) return `Rp ${(val / 1_000_000).toFixed(1)}jt`;
    if (val >= 1_000) return `Rp ${(val / 1_000).toFixed(0)}rb`;
    return Rp(val);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Total Tagihan" value={Rp(stats?.total_amount)} sub={`${stats?.total_invoices || 0} invoice`} color="border-l-primary" />
        <StatCard label="Sudah Bayar" value={Rp(stats?.paid_amount)} sub={`${stats?.paid_count || 0} lunas`} color="border-l-green-500" />
        <StatCard label="Belum Bayar" value={Rp(stats?.unpaid_amount)} sub={`${stats?.unpaid_count || 0} invoice`} color="border-l-amber-500" />
        <StatCard label="Jatuh Tempo" value={stats?.overdue_count || 0} sub="pelanggan" color="border-l-red-500" />
      </div>

      {/* Grafik Tren Pendapatan */}
      {trend.length > 0 && (
        <div className="bg-card border border-border rounded-sm p-4">
          <h3 className="text-sm font-semibold mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-primary" /> Tren Pendapatan 6 Bulan Terakhir
          </h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="label" tick={{ fontSize: 10, fill: '#888' }} />
              <YAxis tickFormatter={fmtRp} tick={{ fontSize: 10, fill: '#888' }} width={72} />
              <Tooltip
                formatter={(val, name) => [Rp(val), name === "paid" ? "Lunas" : "Belum/Overdue"]}
                contentStyle={{ background: '#1a1a2e', border: '1px solid #333', borderRadius: 4, fontSize: 11 }}
                labelStyle={{ color: '#aaa' }}
              />
              <Legend formatter={n => n === "paid" ? "Lunas" : "Belum Bayar"} wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="paid" stackId="a" fill="#22c55e" radius={[0, 0, 0, 0]} />
              <Bar dataKey="unpaid" stackId="a" fill="#f59e0b" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {recent.length > 0 && (
        <div className="bg-card border border-border rounded-sm p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400" /> Tagihan Jatuh Tempo
          </h3>
          <div className="space-y-2">
            {recent.map(inv => (
              <div key={inv.id} className="flex items-center justify-between text-xs p-2 bg-red-500/5 border border-red-500/20 rounded-sm">
                <div>
                  <p className="font-medium">{inv.customer_name}</p>
                  <p className="text-muted-foreground">{inv.customer_username} • {inv.package_name}</p>
                </div>
                <div className="text-right">
                  <p className="font-mono font-bold text-red-400">{Rp(inv.total)}</p>
                  <p className="text-muted-foreground">{inv.due_date}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Invoices Tab ──────────────────────────────────────────────────────────────

function InvoicesTab({ month, year, packages, customers }) {
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [bulking, setBulking] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [showReminderModal, setShowReminderModal] = useState(false);

  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get("/billing/invoices", { params: { month, year, status, search } });
      setInvoices(r.data);
    } catch { toast.error("Gagal memuat tagihan"); }
    setLoading(false);
  }, [month, year, status, search]);

  useEffect(() => { load(); }, [load]);

  const bulkCreate = async () => {
    setBulking(true);
    try {
      const r = await api.post("/billing/invoices/bulk-create", null, { params: { month, year } });
      toast.success(r.data.message);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setBulking(false);
  };

  const syncDisable = async () => {
    if (!window.confirm("Putus koneksi semua pelanggan dengan tagihan JATUH TEMPO?")) return;
    setSyncing(true);
    try {
      const r = await api.post("/billing/invoices/sync-status", null, { params: { action: "disable", status_filter: "overdue" } });
      toast.success(r.data.message);
      if (r.data.errors?.length) toast.warning(r.data.errors.slice(0, 3).join("; "));
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSyncing(false);
  };

  const deleteInv = async (id) => {
    if (!window.confirm("Hapus invoice ini?")) return;
    try {
      await api.delete(`/billing/invoices/${id}`);
      toast.success("Invoice dihapus");
      setSelected(null);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
  };

  // Reminder massal: filter yang belum bayar dan punya nomor telepon
  const unpaidWithPhone = invoices.filter(i => i.status !== "paid" && i.customer_phone);

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari nama / username..."
            className="pl-8 h-8 rounded-sm text-xs" onKeyDown={e => e.key === "Enter" && load()} />
        </div>
        <select value={status} onChange={e => setStatus(e.target.value)}
          className="h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
          <option value="">Semua Status</option>
          <option value="unpaid">Belum Bayar</option>
          <option value="paid">Lunas</option>
          <option value="overdue">Jatuh Tempo</option>
        </select>
        <Button size="sm" variant="outline" className="rounded-sm h-8 gap-1 text-xs" onClick={load}>
          <RefreshCw className="w-3.5 h-3.5" />
        </Button>
        {isAdmin && <>
          <Button size="sm" variant="outline" className="rounded-sm h-8 gap-1 text-xs" onClick={bulkCreate} disabled={bulking}>
            <Download className="w-3.5 h-3.5" />{bulking ? "Membuat..." : "Generate Massal"}
          </Button>
          <Button size="sm" variant="outline"
            className="rounded-sm h-8 gap-1 text-xs border-orange-500/40 text-orange-400 hover:bg-orange-500/10"
            onClick={syncDisable} disabled={syncing}>
            <WifiOff className="w-3.5 h-3.5" />{syncing ? "Memutus..." : "Putus Overdue"}
          </Button>
          {unpaidWithPhone.length > 0 && (
            <Button size="sm" variant="outline"
              className="rounded-sm h-8 gap-1 text-xs border-green-500/40 text-green-400 hover:bg-green-500/10"
              onClick={() => setShowReminderModal(true)}>
              <Send className="w-3.5 h-3.5" /> Reminder ({unpaidWithPhone.length})
            </Button>
          )}
          <Button size="sm" className="rounded-sm h-8 gap-1 text-xs" onClick={() => setShowCreate(true)}>
            <Plus className="w-3.5 h-3.5" /> Tambah
          </Button>
        </>}
      </div>

      {/* Table */}
      {loading ? (
        <p className="text-muted-foreground text-sm text-center py-8 animate-pulse">Memuat tagihan...</p>
      ) : invoices.length === 0 ? (
        <div className="text-center py-10">
          <Receipt className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
          <p className="text-muted-foreground text-sm">Tidak ada tagihan</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[700px]">
            <thead>
              <tr className="border-b border-border">
                {["No. Invoice", "Pelanggan", "Paket", "Total", "Jatuh Tempo", "Status", "Aksi"].map(h => (
                  <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.map(inv => (
                <tr key={inv.id} className="border-b border-border/30 hover:bg-secondary/20 transition-colors">
                  <td className="px-3 py-2.5 text-[10px] font-mono text-muted-foreground">{inv.invoice_number}</td>
                  <td className="px-3 py-2.5">
                    <p className="text-xs font-medium">{inv.customer_name}</p>
                    <p className="text-[10px] text-muted-foreground">{inv.customer_username}</p>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-muted-foreground">{inv.package_name}</td>
                  <td className="px-3 py-2.5 text-xs font-mono font-bold">{Rp(inv.total)}</td>
                  <td className="px-3 py-2.5 text-[10px] text-muted-foreground">{inv.due_date}</td>
                  <td className="px-3 py-2.5"><StatusBadge status={inv.status} /></td>
                  <td className="px-3 py-2.5">
                    <Button size="sm" variant="outline" className="rounded-sm h-6 text-[10px] px-2" onClick={() => setSelected(inv)}>
                      Detail
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-muted-foreground mt-2 text-right font-mono">{invoices.length} tagihan</p>
        </div>
      )}

      {selected && (
        <InvoiceModal invoice={selected} packages={packages}
          onClose={() => setSelected(null)}
          onPaid={() => { setSelected(null); load(); }}
          onDelete={() => deleteInv(selected.id)} />
      )}

      {showCreate && (
        <CreateInvoiceModal packages={packages} customers={customers}
          month={month} year={year}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load(); }} />
      )}

      {showReminderModal && (
        <BulkReminderModal invoices={unpaidWithPhone}
          onClose={() => setShowReminderModal(false)} />
      )}
    </div>
  );
}

// ── Create Invoice Modal ──────────────────────────────────────────────────────

function CreateInvoiceModal({ packages, customers, month, year, onClose, onCreated }) {
  const [form, setForm] = useState({
    customer_id: "", package_id: "", amount: "", discount: "0",
    period_start: `${year}-${String(month).padStart(2, "0")}-01`,
    period_end: "", due_date: "", notes: "",
  });
  const [saving, setSaving] = useState(false);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const selectedCustomer = customers.find(c => c.id === form.customer_id);
  const selectedPkg = packages.find(p => p.id === form.package_id);

  useEffect(() => {
    if (selectedPkg && !form.amount) set("amount", String(selectedPkg.price));
  }, [selectedPkg]); // eslint-disable-line

  const submit = async () => {
    if (!form.customer_id || !form.package_id || !form.amount || !form.period_end || !form.due_date) {
      toast.error("Isi semua field yang wajib"); return;
    }
    setSaving(true);
    try {
      await api.post("/billing/invoices", {
        ...form, amount: Number(form.amount), discount: Number(form.discount || 0),
      });
      toast.success("Invoice berhasil dibuat");
      onCreated();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="font-semibold">Buat Invoice Baru</h3>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Pelanggan *</Label>
            <select value={form.customer_id} onChange={e => set("customer_id", e.target.value)}
              className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
              <option value="">Pilih pelanggan...</option>
              {customers.filter(c => c.active).map(c => (
                <option key={c.id} value={c.id}>{c.name} ({c.username})</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Paket *</Label>
            <select value={form.package_id} onChange={e => { set("package_id", e.target.value); const p = packages.find(x => x.id === e.target.value); if (p) set("amount", String(p.price)); }}
              className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
              <option value="">Pilih paket...</option>
              {packages.map(p => <option key={p.id} value={p.id}>{p.name} — {Rp(p.price)}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Tagihan (Rp) *</Label>
              <Input value={form.amount} onChange={e => set("amount", e.target.value)} className="h-8 rounded-sm text-xs" type="number" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Diskon (Rp)</Label>
              <Input value={form.discount} onChange={e => set("discount", e.target.value)} className="h-8 rounded-sm text-xs" type="number" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Mulai Periode *</Label>
              <Input value={form.period_start} onChange={e => set("period_start", e.target.value)} className="h-8 rounded-sm text-xs" type="date" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Akhir Periode *</Label>
              <Input value={form.period_end} onChange={e => set("period_end", e.target.value)} className="h-8 rounded-sm text-xs" type="date" />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Jatuh Tempo * {selectedCustomer && <span className="text-muted-foreground">(tgl {selectedCustomer.due_day} tiap bulan)</span>}</Label>
            <Input value={form.due_date} onChange={e => set("due_date", e.target.value)} className="h-8 rounded-sm text-xs" type="date" />
          </div>
        </div>
        <div className="flex gap-2 p-4 border-t border-border">
          <Button variant="outline" className="flex-1 rounded-sm text-xs" onClick={onClose}>Batal</Button>
          <Button className="flex-1 rounded-sm text-xs" onClick={submit} disabled={saving}>
            {saving ? "Menyimpan..." : "Buat Invoice"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Customers Tab ─────────────────────────────────────────────────────────────

function CustomersTab({ packages, onRefresh }) {
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  const load = useCallback(async () => {
    setLoading(true);
    try { const r = await api.get("/customers", { params: { search } }); setCustomers(r.data); }
    catch { toast.error("Gagal memuat pelanggan"); }
    setLoading(false);
  }, [search]);

  useEffect(() => { load(); }, [load]);

  const deleteCust = async (id) => {
    if (!window.confirm("Hapus pelanggan ini?")) return;
    try { await api.delete(`/customers/${id}`); toast.success("Dihapus"); load(); }
    catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input value={search} onChange={e => setSearch(e.target.value)} placeholder="Cari nama / username / telepon..."
            className="pl-8 h-8 rounded-sm text-xs" />
        </div>
        <Button size="sm" variant="outline" className="rounded-sm h-8 gap-1 text-xs" onClick={load}><RefreshCw className="w-3.5 h-3.5" /></Button>
        {isAdmin && <>
          <Button size="sm" variant="outline" className="rounded-sm h-8 gap-1 text-xs" onClick={() => setShowImport(true)}>
            <Upload className="w-3.5 h-3.5" /> Import MikroTik
          </Button>
          <Button size="sm" className="rounded-sm h-8 gap-1 text-xs" onClick={() => { setEditTarget(null); setShowForm(true); }}>
            <Plus className="w-3.5 h-3.5" /> Tambah
          </Button>
        </>}
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm text-center py-8 animate-pulse">Memuat...</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left min-w-[700px]">
            <thead>
              <tr className="border-b border-border">
                {["Nama", "Username", "Layanan", "Paket", "Jatuh Tempo", "Status", "Aksi"].map(h => (
                  <th key={h} className="px-3 py-2 text-[10px] text-muted-foreground uppercase tracking-wider font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {customers.map(c => {
                const pkg = packages.find(p => p.id === c.package_id);
                return (
                  <tr key={c.id} className="border-b border-border/30 hover:bg-secondary/20">
                    <td className="px-3 py-2.5">
                      <p className="text-xs font-medium">{c.name}</p>
                      <p className="text-[10px] text-muted-foreground">{c.phone || "—"}</p>
                    </td>
                    <td className="px-3 py-2.5 text-xs font-mono">{c.username}</td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${c.service_type === "pppoe" ? "border-blue-500/30 text-blue-400" : "border-purple-500/30 text-purple-400"}`}>
                        {c.service_type.toUpperCase()}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-muted-foreground">{pkg?.name || <span className="text-amber-400/80 text-[10px]">Belum ada paket</span>}</td>
                    <td className="px-3 py-2.5 text-[10px] text-muted-foreground">Tgl {c.due_day}</td>
                    <td className="px-3 py-2.5">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${c.active ? "border-green-500/30 text-green-400" : "border-red-500/30 text-red-400"}`}>
                        {c.active ? "Aktif" : "Non-aktif"}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      {isAdmin && (
                        <div className="flex gap-1">
                          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => { setEditTarget(c); setShowForm(true); }}>
                            <Edit2 className="w-3 h-3" />
                          </Button>
                          <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => deleteCust(c.id)}>
                            <Trash2 className="w-3 h-3 text-destructive" />
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="text-[10px] text-muted-foreground mt-2 text-right font-mono">{customers.length} pelanggan</p>
        </div>
      )}

      {showForm && <CustomerForm packages={packages} initial={editTarget}
        onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); load(); onRefresh?.(); }} />}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImported={() => { setShowImport(false); load(); }} />}
    </div>
  );
}

// ── Customer Form Modal ───────────────────────────────────────────────────────

function CustomerForm({ packages, initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: initial?.name || "", phone: initial?.phone || "", address: initial?.address || "",
    service_type: initial?.service_type || "pppoe", username: initial?.username || "",
    device_id: initial?.device_id || "", package_id: initial?.package_id || "",
    due_day: initial?.due_day || 10, active: initial?.active ?? true,
  });
  const [devices, setDevices] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => { api.get("/devices").then(r => setDevices(r.data)).catch(() => { }); }, []);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const isEdit = !!initial;

  const submit = async () => {
    if (!form.name || !form.username || !form.device_id) { toast.error("Nama, username, dan device wajib"); return; }
    setSaving(true);
    try {
      if (isEdit) { await api.put(`/customers/${initial.id}`, { name: form.name, phone: form.phone, address: form.address, package_id: form.package_id, due_day: Number(form.due_day), active: form.active }); }
      else { await api.post("/customers", { ...form, due_day: Number(form.due_day) }); }
      toast.success(isEdit ? "Pelanggan diupdate" : "Pelanggan ditambahkan");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="font-semibold">{isEdit ? "Edit Pelanggan" : "Tambah Pelanggan"}</h3>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-4 space-y-3 max-h-[65vh] overflow-y-auto">
          {[["Nama *", "name", "text"], ["Telepon", "phone", "tel"], ["Alamat", "address", "text"], ["Username MikroTik *", "username", "text"]].map(([label, key, type]) => (
            <div key={key} className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">{label}</Label>
              <Input value={form[key]} onChange={e => set(key, e.target.value)} type={type} className="h-8 rounded-sm text-xs" disabled={isEdit && key === "username"} />
            </div>
          ))}
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Jenis Layanan</Label>
              <select value={form.service_type} onChange={e => set("service_type", e.target.value)} disabled={isEdit}
                className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
                <option value="pppoe">PPPoE</option>
                <option value="hotspot">Hotspot</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Tgl Jatuh Tempo</Label>
              <Input value={form.due_day} onChange={e => set("due_day", e.target.value)} type="number" min="1" max="28" className="h-8 rounded-sm text-xs" />
            </div>
          </div>
          {!isEdit && (
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Device MikroTik *</Label>
              <select value={form.device_id} onChange={e => set("device_id", e.target.value)}
                className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
                <option value="">Pilih device...</option>
                {devices.map(d => <option key={d.id} value={d.id}>{d.name} ({d.host})</option>)}
              </select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Paket Berlangganan</Label>
            <select value={form.package_id} onChange={e => set("package_id", e.target.value)}
              className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
              <option value="">— Pilih paket —</option>
              {packages.map(p => <option key={p.id} value={p.id}>{p.name} ({Rp(p.price)})</option>)}
            </select>
          </div>
          {isEdit && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.active} onChange={e => set("active", e.target.checked)} className="rounded" />
              <span className="text-xs text-muted-foreground">Pelanggan aktif</span>
            </label>
          )}
        </div>
        <div className="flex gap-2 p-4 border-t border-border">
          <Button variant="outline" className="flex-1 rounded-sm text-xs" onClick={onClose}>Batal</Button>
          <Button className="flex-1 rounded-sm text-xs" onClick={submit} disabled={saving}>{saving ? "Menyimpan..." : isEdit ? "Update" : "Tambah"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Import Modal ──────────────────────────────────────────────────────────────

function ImportModal({ onClose, onImported }) {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState("");
  const [type, setType] = useState("pppoe");
  const [dueDay, setDueDay] = useState(10);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);

  useEffect(() => { api.get("/devices").then(r => setDevices(r.data)).catch(() => { }); }, []);

  const doImport = async () => {
    if (!deviceId) { toast.error("Pilih device dahulu"); return; }
    setLoading(true);
    try {
      const r = await api.post(`/customers/import/${type}`, null, { params: { device_id: deviceId, due_day: dueDay } });
      setResult(r.data);
      toast.success(r.data.message);
    } catch (e) { toast.error(e.response?.data?.detail || "Import gagal"); }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-sm shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="font-semibold">Import dari MikroTik</h3>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-4 space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Device MikroTik</Label>
            <select value={deviceId} onChange={e => setDeviceId(e.target.value)}
              className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
              <option value="">Pilih device...</option>
              {devices.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Jenis</Label>
              <select value={type} onChange={e => setType(e.target.value)}
                className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
                <option value="pppoe">PPPoE</option>
                <option value="hotspot">Hotspot</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Default Jatuh Tempo</Label>
              <Input value={dueDay} onChange={e => setDueDay(e.target.value)} type="number" min="1" max="28" className="h-8 rounded-sm text-xs" />
            </div>
          </div>
          {result && (
            <div className="p-2 bg-green-500/10 border border-green-500/20 rounded-sm text-xs text-green-300">
              ✓ {result.message}
            </div>
          )}
        </div>
        <div className="flex gap-2 p-4 border-t border-border">
          <Button variant="outline" className="flex-1 rounded-sm text-xs" onClick={result ? onImported : onClose}>{result ? "Selesai" : "Batal"}</Button>
          {!result && (
            <Button className="flex-1 rounded-sm text-xs gap-1" onClick={doImport} disabled={loading}>
              <Upload className="w-3.5 h-3.5" />{loading ? "Mengimport..." : "Import"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Packages Tab ──────────────────────────────────────────────────────────────

function PackagesTab({ packages, onRefresh }) {
  const [showForm, setShowForm] = useState(false);
  const [editPkg, setEditPkg] = useState(null);
  const [devices, setDevices] = useState([]);
  const [syncDevice, setSyncDevice] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [editPrice, setEditPrice] = useState({}); // {pkg_id: price_value}
  const [savingPrice, setSavingPrice] = useState({});
  const { user } = useAuth();
  const isAdmin = user?.role === "administrator";

  useEffect(() => {
    api.get("/devices").then(r => setDevices(r.data)).catch(() => { });
  }, []);

  const deletePkg = async (id) => {
    if (!window.confirm("Hapus paket ini?")) return;
    try { await api.delete(`/billing/packages/${id}`); toast.success("Paket dihapus"); onRefresh(); }
    catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
  };

  const syncFromMikroTik = async () => {
    if (!syncDevice) { toast.error("Pilih device dulu"); return; }
    setSyncing(true);
    try {
      const r = await api.post("/billing/packages/sync-from-mikrotik", null, {
        params: { device_id: syncDevice }
      });
      toast.success(r.data.message);
      onRefresh();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal sync"); }
    setSyncing(false);
  };

  const savePrice = async (pkg) => {
    const price = editPrice[pkg.id];
    if (price === undefined) return;
    setSavingPrice(s => ({ ...s, [pkg.id]: true }));
    try {
      await api.patch(`/billing/packages/${pkg.id}/price`, { price: Number(price) });
      toast.success(`Harga ${pkg.name} disimpan`);
      setEditPrice(p => { const n = { ...p }; delete n[pkg.id]; return n; });
      onRefresh();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSavingPrice(s => ({ ...s, [pkg.id]: false }));
  };

  const toggleActive = async (pkg) => {
    try {
      await api.patch(`/billing/packages/${pkg.id}/price`, { active: !pkg.active });
      toast.success(`Paket ${pkg.active ? "dinonaktifkan" : "diaktifkan"}`);
      onRefresh();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
  };

  return (
    <div className="space-y-3">
      {/* Toolbar: Sync dari MikroTik + Tambah Manual */}
      {isAdmin && (
        <div className="flex flex-wrap gap-2 items-center">
          <div className="flex items-center gap-1 flex-1 min-w-[200px]">
            <select value={syncDevice} onChange={e => setSyncDevice(e.target.value)}
              className="flex-1 h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
              <option value="">Pilih device MikroTik...</option>
              {devices.map(d => <option key={d.id} value={d.id}>{d.name} ({d.host})</option>)}
            </select>
            <Button size="sm" variant="outline"
              className="rounded-sm h-8 gap-1 text-xs border-blue-500/40 text-blue-400 hover:bg-blue-500/10 whitespace-nowrap"
              onClick={syncFromMikroTik} disabled={syncing || !syncDevice}>
              <RefreshCw className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`} />
              {syncing ? "Sync..." : "Sync Profile"}
            </Button>
          </div>
          <Button size="sm" variant="outline" className="rounded-sm h-8 gap-1 text-xs whitespace-nowrap"
            onClick={() => { setEditPkg(null); setShowForm(true); }}>
            <Plus className="w-3.5 h-3.5" /> Tambah Manual
          </Button>
        </div>
      )}

      {/* Info hint */}
      {packages.length === 0 ? (
        <div className="text-center py-10">
          <Package className="w-10 h-10 text-muted-foreground/30 mx-auto mb-2" />
          <p className="text-muted-foreground text-sm mb-1">Belum ada paket</p>
          <p className="text-[11px] text-muted-foreground/60">Pilih device MikroTik lalu klik "Sync Profile" untuk mengambil daftar paket</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {["Nama Paket", "Tipe", "Speed", "Harga/Bulan", "Status", ""].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {packages.map(p => (
                <tr key={p.id} className="border-b border-border/40 hover:bg-secondary/20">
                  <td className="px-3 py-2.5">
                    <p className="text-xs font-medium">{p.name}</p>
                    {p.source_device_name && (
                      <p className="text-[10px] text-muted-foreground">{p.source_device_name}</p>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${p.service_type === "pppoe" || p.type === "pppoe"
                        ? "border-blue-500/30 text-blue-400"
                        : "border-purple-500/30 text-purple-400"
                      }`}>
                      {(p.service_type || p.type || "pppoe").toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-[10px] text-muted-foreground">
                    {(p.speed_down || p.speed_up) ? `⬇${p.speed_down} ⬆${p.speed_up}` : "—"}
                  </td>
                  <td className="px-3 py-2.5">
                    {isAdmin ? (
                      <div className="flex items-center gap-1">
                        <Input
                          type="number"
                          value={editPrice[p.id] !== undefined ? editPrice[p.id] : p.price}
                          onChange={e => setEditPrice(prev => ({ ...prev, [p.id]: e.target.value }))}
                          className="h-7 w-28 text-xs rounded-sm font-mono"
                          min="0"
                        />
                        {editPrice[p.id] !== undefined && (
                          <Button size="sm" className="h-7 px-2 text-xs rounded-sm"
                            onClick={() => savePrice(p)}
                            disabled={savingPrice[p.id]}>
                            {savingPrice[p.id] ? "..." : "✓"}
                          </Button>
                        )}
                      </div>
                    ) : (
                      <span className={`font-mono text-xs font-bold ${p.price > 0 ? 'text-primary' : 'text-amber-400'
                        }`}>
                        {p.price > 0 ? Rp(p.price) : 'Belum diisi'}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {isAdmin ? (
                      <button onClick={() => toggleActive(p)}
                        className={`text-[10px] px-1.5 py-0.5 rounded-sm border cursor-pointer transition-colors ${p.active ? "border-green-500/30 text-green-400 hover:bg-green-500/10" : "border-red-500/30 text-red-400 hover:bg-red-500/10"
                          }`}>
                        {p.active ? "Aktif" : "Non-aktif"}
                      </button>
                    ) : (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-sm border ${p.active ? "border-green-500/30 text-green-400" : "border-red-500/30 text-red-400"
                        }`}>{p.active ? "Aktif" : "Non-aktif"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    {isAdmin && (
                      <div className="flex gap-1">
                        <Button size="icon" variant="ghost" className="h-6 w-6"
                          onClick={() => { setEditPkg(p); setShowForm(true); }}>
                          <Edit2 className="w-3 h-3" />
                        </Button>
                        <Button size="icon" variant="ghost" className="h-6 w-6"
                          onClick={() => deletePkg(p.id)}>
                          <Trash2 className="w-3 h-3 text-destructive" />
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-muted-foreground mt-2 text-right font-mono">{packages.length} paket</p>
        </div>
      )}
      {showForm && <PackageForm initial={editPkg} onClose={() => setShowForm(false)} onSaved={() => { setShowForm(false); onRefresh(); }} />}
    </div>
  );
}

function PackageForm({ initial, onClose, onSaved }) {
  const [form, setForm] = useState({
    name: initial?.name || "", price: initial?.price || "", speed_up: initial?.speed_up || "",
    speed_down: initial?.speed_down || "", type: initial?.type || "pppoe",
    billing_cycle: initial?.billing_cycle || 30, active: initial?.active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
  const isEdit = !!initial;

  const submit = async () => {
    if (!form.name || !form.price) { toast.error("Nama dan harga wajib"); return; }
    setSaving(true);
    try {
      if (isEdit) await api.put(`/billing/packages/${initial.id}`, { ...form, price: Number(form.price), billing_cycle: Number(form.billing_cycle) });
      else await api.post("/billing/packages", { ...form, price: Number(form.price), billing_cycle: Number(form.billing_cycle) });
      toast.success(isEdit ? "Paket diupdate" : "Paket ditambahkan");
      onSaved();
    } catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="font-semibold">{isEdit ? "Edit Paket" : "Tambah Paket"}</h3>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-4 space-y-3">
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Nama Paket *</Label>
            <Input value={form.name} onChange={e => set("name", e.target.value)} className="h-8 rounded-sm text-xs" placeholder="Paket 20Mbps" />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Harga (Rp) *</Label>
              <Input value={form.price} onChange={e => set("price", e.target.value)} type="number" className="h-8 rounded-sm text-xs" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Jenis Layanan</Label>
              <select value={form.type} onChange={e => set("type", e.target.value)}
                className="w-full h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
                <option value="pppoe">PPPoE</option>
                <option value="hotspot">Hotspot</option>
                <option value="both">Keduanya</option>
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Upload Speed</Label>
              <Input value={form.speed_up} onChange={e => set("speed_up", e.target.value)} className="h-8 rounded-sm text-xs" placeholder="20M" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Download Speed</Label>
              <Input value={form.speed_down} onChange={e => set("speed_down", e.target.value)} className="h-8 rounded-sm text-xs" placeholder="20M" />
            </div>
          </div>
          {isEdit && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={form.active} onChange={e => set("active", e.target.checked)} />
              <span className="text-xs text-muted-foreground">Paket aktif</span>
            </label>
          )}
        </div>
        <div className="flex gap-2 p-4 border-t border-border">
          <Button variant="outline" className="flex-1 rounded-sm text-xs" onClick={onClose}>Batal</Button>
          <Button className="flex-1 rounded-sm text-xs" onClick={submit} disabled={saving}>{saving ? "Menyimpan..." : isEdit ? "Update" : "Tambah"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Bulk Reminder Modal (WA Massal) ───────────────────────────────────────────

function BulkReminderModal({ invoices, onClose }) {
  const [sending, setSending] = useState(false);
  const [progress, setProgress] = useState(0);
  const [done, setDone] = useState(false);

  const sendAll = async () => {
    setSending(true);
    setProgress(0);
    for (let i = 0; i < invoices.length; i++) {
      try {
        const r = await api.get(`/billing/invoices/${invoices[i].id}/whatsapp-link`);
        window.open(r.data.link, "_blank");
      } catch { /* skip */ }
      setProgress(i + 1);
      await new Promise(res => setTimeout(res, 800));
    }
    setDone(true);
    setSending(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-card border border-border rounded-sm w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h3 className="font-semibold flex items-center gap-2">
            <Send className="w-4 h-4 text-green-400" /> Reminder Massal WhatsApp
          </h3>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-sm text-muted-foreground">
            Akan mengirim pesan tagihan ke <strong className="text-foreground">{invoices.length} pelanggan</strong> yang belum bayar dan memiliki nomor telepon.
          </p>
          <div className="bg-amber-500/10 border border-amber-500/20 rounded-sm p-3 text-xs text-amber-400">
            ⚠️ Browser akan membuka tab WA baru untuk setiap pelanggan. Pastikan popup tidak diblokir browser.
          </div>
          <div className="max-h-48 overflow-y-auto space-y-1.5 border border-border rounded-sm p-2">
            {invoices.map((inv, i) => (
              <div key={inv.id} className={`flex items-center justify-between text-xs p-1.5 rounded-sm ${i < progress ? "bg-green-500/10 text-green-400" : "text-muted-foreground"
                }`}>
                <span>{i < progress ? "✓" : `${i + 1}.`} {inv.customer_name}</span>
                <span className="font-mono">{Rp(inv.total)}</span>
              </div>
            ))}
          </div>
          {sending && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Mengirim...</span><span>{progress}/{invoices.length}</span>
              </div>
              <div className="w-full h-1.5 bg-secondary rounded-full overflow-hidden">
                <div className="h-full bg-green-500 transition-all duration-300 rounded-full"
                  style={{ width: `${(progress / invoices.length) * 100}%` }} />
              </div>
            </div>
          )}
          {done && (
            <div className="p-2 bg-green-500/10 border border-green-500/20 rounded-sm text-xs text-green-400 text-center">
              ✓ Selesai! {progress} pesan telah dibuka.
            </div>
          )}
        </div>
        <div className="flex gap-2 p-4 border-t border-border">
          <Button variant="outline" className="flex-1 rounded-sm text-xs" onClick={onClose}>
            {done ? "Tutup" : "Batal"}
          </Button>
          {!done && (
            <Button className="flex-1 rounded-sm text-xs gap-1" onClick={sendAll} disabled={sending}>
              <Send className="w-3.5 h-3.5" />
              {sending ? `Mengirim ${progress}/${invoices.length}...` : "Kirim Semua"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const [tab, setTab] = useState("dashboard");
  const [packages, setPackages] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [unbilledPPPoE, setUnbilledPPPoE] = useState([]);
  const [notifDismissed, setNotifDismissed] = useState(false);
  const today = new Date();
  const [month, setMonth] = useState(today.getMonth() + 1);
  const [year, setYear] = useState(today.getFullYear());

  const loadPackages = useCallback(() => {
    api.get("/billing/packages").then(r => setPackages(r.data)).catch(() => { });
  }, []);

  const loadCustomers = useCallback(() => {
    api.get("/customers").then(r => setCustomers(r.data)).catch(() => { });
  }, []);

  useEffect(() => { loadPackages(); loadCustomers(); }, [loadPackages, loadCustomers]);

  // Deteksi PPPoE user baru yang belum ada billing record
  useEffect(() => {
    const checkUnbilled = async () => {
      try {
        const [devRes, custRes] = await Promise.all([
          api.get("/devices"),
          api.get("/customers")
        ]);
        const onlineDevs = (devRes.data || []).filter(d => d.status === "online");
        const billedSet = new Set(
          (custRes.data || []).map(c => c.pppoe_username || c.username).filter(Boolean)
        );
        let allPPPoE = [];
        for (const dev of onlineDevs.slice(0, 5)) {
          try {
            const r = await api.get("/pppoe-users", { params: { device_id: dev.id } });
            allPPPoE.push(...(r.data || []).map(u => ({ ...u, device_name: dev.name })));
          } catch {}
        }
        const unregistered = allPPPoE.filter(u => u.name && !billedSet.has(u.name));
        setUnbilledPPPoE(unregistered);
      } catch {}
    };
    checkUnbilled();
  }, []);

  const tabs = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "invoices", label: "Tagihan", icon: Receipt },
    { id: "customers", label: "Pelanggan", icon: Users },
    { id: "packages", label: "Paket", icon: Package },
  ];

  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agt", "Sep", "Okt", "Nov", "Des"];

  return (
    <div className="space-y-4 pb-16">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <Receipt className="w-6 h-6 text-primary" /> Billing Management
          </h1>
          <p className="text-xs text-muted-foreground">Manajemen tagihan berlangganan PPPoE &amp; Hotspot</p>
        </div>
        {/* Month selector */}
        <div className="flex items-center gap-2 self-start">
          <select value={month} onChange={e => setMonth(Number(e.target.value))}
            className="h-8 text-xs rounded-sm border border-border bg-secondary px-2 text-foreground">
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <Input value={year} onChange={e => setYear(Number(e.target.value))} type="number"
            className="h-8 w-20 rounded-sm text-xs" min="2020" max="2099" />
        </div>
      </div>

      {/* Notifikasi PPPoE user belum ada billing */}
      {unbilledPPPoE.length > 0 && !notifDismissed && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-sm p-3 flex items-start gap-3">
          <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-amber-400">
              {unbilledPPPoE.length} user PPPoE baru belum diatur paket billing
            </p>
            <p className="text-[10px] text-muted-foreground mt-0.5">
              User: {unbilledPPPoE.slice(0, 4).map(u => u.name).join(", ")}
              {unbilledPPPoE.length > 4 && ` +${unbilledPPPoE.length - 4} lainnya`}
            </p>
          </div>
          <div className="flex gap-1.5 flex-shrink-0">
            <Button size="sm" variant="outline"
              className="rounded-sm text-xs h-7 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
              onClick={() => setTab("customers")}>
              Atur Paket
            </Button>
            <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setNotifDismissed(true)}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-border gap-1">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm border-b-2 transition-colors ${tab === t.id ? "border-primary text-primary" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}>
            <t.icon className="w-3.5 h-3.5" />{t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="bg-card border border-border rounded-sm p-4">
        {tab === "dashboard" && <DashboardTab month={month} year={year} />}
        {tab === "invoices" && <InvoicesTab month={month} year={year} packages={packages} customers={customers} />}
        {tab === "customers" && <CustomersTab packages={packages} onRefresh={loadCustomers} />}
        {tab === "packages" && <PackagesTab packages={packages} onRefresh={loadPackages} />}
      </div>
    </div>
  );
}
