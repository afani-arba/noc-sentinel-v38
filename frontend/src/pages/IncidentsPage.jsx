import { useState, useEffect, useCallback, useRef } from "react";
import api from "@/lib/api";
import {
  Plus, X, AlertTriangle, AlertCircle, Clock, User, Server,
  MessageSquare, RefreshCw, ChevronRight, Filter, Search, CheckCircle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";

const SEV_CONFIG = {
  critical: { bg: "bg-red-500/10", border: "border-red-500/40", text: "text-red-400", dot: "bg-red-500", label: "CRITICAL" },
  high:     { bg: "bg-orange-500/10", border: "border-orange-500/40", text: "text-orange-400", dot: "bg-orange-500", label: "HIGH" },
  medium:   { bg: "bg-yellow-500/10", border: "border-yellow-500/40", text: "text-yellow-400", dot: "bg-yellow-500", label: "MEDIUM" },
  low:      { bg: "bg-blue-500/10", border: "border-blue-500/40", text: "text-blue-400", dot: "bg-blue-500", label: "LOW" },
};

const COL_CONFIG = {
  open:        { label: "Open", headerBg: "bg-red-500/10", headerBorder: "border-red-500/40", headerText: "text-red-400", count_bg: "bg-red-500" },
  in_progress: { label: "In Progress", headerBg: "bg-yellow-500/10", headerBorder: "border-yellow-500/40", headerText: "text-yellow-400", count_bg: "bg-yellow-500" },
  resolved:    { label: "Resolved", headerBg: "bg-green-500/10", headerBorder: "border-green-500/40", headerText: "text-green-400", count_bg: "bg-green-500" },
};

function SeverityBadge({ severity }) {
  const c = SEV_CONFIG[severity] || SEV_CONFIG.medium;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold border ${c.bg} ${c.border} ${c.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${c.dot}`} />
      {c.label}
    </span>
  );
}

function TicketCard({ ticket, onClick, selected }) {
  const sev = SEV_CONFIG[ticket.severity] || SEV_CONFIG.medium;
  return (
    <div
      className={`rounded-lg border p-3 cursor-pointer transition-all hover:shadow-lg ${selected ? "ring-1 ring-primary border-primary/50" : "border-border bg-card hover:bg-secondary/40"}`}
      style={{ borderLeft: `3px solid ${ticket.severity === "critical" ? "#ef4444" : ticket.severity === "high" ? "#f97316" : ticket.severity === "medium" ? "#eab308" : "#3b82f6"}` }}
      onClick={() => onClick(ticket)}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[10px] font-mono text-muted-foreground">{ticket.id}</span>
        <SeverityBadge severity={ticket.severity} />
      </div>
      <p className="text-sm font-semibold text-foreground leading-snug mb-1 line-clamp-2">{ticket.title}</p>
      {ticket.device_name && (
        <p className="text-xs text-muted-foreground flex items-center gap-1 mb-2">
          <Server className="w-3 h-3" /> {ticket.device_name}
        </p>
      )}
      <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-2 border-t border-border/50">
        <span className="flex items-center gap-1">
          <User className="w-3 h-3" />
          {ticket.assignee || "Unassigned"}
        </span>
        <span className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {ticket.elapsed_str || "—"}
        </span>
      </div>
    </div>
  );
}

function TicketDetail({ ticket, onClose, onUpdate, users }) {
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [updating, setUpdating] = useState(false);

  if (!ticket) return null;

  const handleStatusChange = async (newStatus) => {
    setUpdating(true);
    try {
      await api.put(`/incidents/${ticket.id}`, { status: newStatus });
      onUpdate();
      toast.success(`Status updated to ${newStatus}`);
    } catch (e) {
      toast.error("Failed to update status");
    }
    setUpdating(false);
  };

  const handleComment = async () => {
    if (!comment.trim()) return;
    setSubmitting(true);
    try {
      await api.post(`/incidents/${ticket.id}/comments`, { text: comment });
      setComment("");
      onUpdate();
      toast.success("Comment added");
    } catch (e) {
      toast.error("Failed to add comment");
    }
    setSubmitting(false);
  };

  const timelineIconMap = {
    created: "🟢",
    updated: "🔄",
    comment: "💬",
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg h-full bg-background border-l border-border flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between px-5 py-4 border-b border-border flex-shrink-0">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-mono text-muted-foreground mb-0.5">{ticket.id}</p>
            <h3 className="text-base font-bold leading-snug">{ticket.title}</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary ml-3 flex-shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content - scrollable */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {/* Meta */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground text-[10px] uppercase mb-1">Severity</p>
              <SeverityBadge severity={ticket.severity} />
            </div>
            <div>
              <p className="text-muted-foreground text-[10px] uppercase mb-1">Status</p>
              <span className={`text-xs font-semibold ${COL_CONFIG[ticket.status]?.headerText || "text-foreground"}`}>
                {COL_CONFIG[ticket.status]?.label || ticket.status}
              </span>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px] uppercase mb-1">Device</p>
              <p className="font-mono">{ticket.device_name || "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px] uppercase mb-1">Assignee</p>
              <p>{ticket.assignee || "Unassigned"}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-[10px] uppercase mb-1">Created</p>
              <p className="font-mono">{ticket.created_at ? new Date(ticket.created_at).toLocaleString("id-ID") : "—"}</p>
            </div>
            {ticket.resolved_at && (
              <div>
                <p className="text-muted-foreground text-[10px] uppercase mb-1">Resolved</p>
                <p className="font-mono">{new Date(ticket.resolved_at).toLocaleString("id-ID")}</p>
              </div>
            )}
          </div>

          {/* Description */}
          {ticket.description && (
            <div>
              <p className="text-[10px] uppercase text-muted-foreground tracking-wider mb-2">Description</p>
              <p className="text-sm text-foreground/80 leading-relaxed bg-secondary/30 rounded-lg p-3">{ticket.description}</p>
            </div>
          )}

          {/* Status Actions */}
          {ticket.status !== "resolved" && (
            <div className="flex gap-2">
              {ticket.status === "open" && (
                <Button size="sm" variant="outline" className="text-xs rounded-sm flex-1" onClick={() => handleStatusChange("in_progress")} disabled={updating}>
                  🔄 Mark In Progress
                </Button>
              )}
              <Button size="sm" className="text-xs rounded-sm flex-1 bg-green-600 hover:bg-green-700" onClick={() => handleStatusChange("resolved")} disabled={updating}>
                <CheckCircle className="w-3.5 h-3.5 mr-1" /> Resolve
              </Button>
            </div>
          )}

          {/* Timeline */}
          <div>
            <p className="text-[10px] uppercase text-muted-foreground tracking-wider mb-2">Timeline</p>
            <div className="space-y-2">
              {(ticket.timeline || []).map((t, i) => (
                <div key={i} className="flex gap-2.5 text-xs">
                  <span className="text-base leading-none">{timelineIconMap[t.action] || "📋"}</span>
                  <div>
                    <span className="font-semibold text-foreground/80">{t.by}</span>
                    <span className="text-muted-foreground ml-1">{t.note}</span>
                    <p className="text-[10px] text-muted-foreground font-mono mt-0.5">
                      {t.at ? new Date(t.at).toLocaleString("id-ID") : ""}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Comments */}
          <div>
            <p className="text-[10px] uppercase text-muted-foreground tracking-wider mb-2 flex items-center gap-1">
              <MessageSquare className="w-3 h-3" /> Comments ({(ticket.comments || []).length})
            </p>
            <div className="space-y-2 mb-3">
              {(ticket.comments || []).map(c => (
                <div key={c.id} className="bg-secondary/30 rounded-lg p-3 text-xs">
                  <div className="flex justify-between mb-1">
                    <span className="font-semibold text-foreground">{c.user}</span>
                    <span className="text-muted-foreground font-mono text-[10px]">{c.timestamp ? new Date(c.timestamp).toLocaleString("id-ID") : ""}</span>
                  </div>
                  <p className="text-foreground/80">{c.text}</p>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                value={comment}
                onChange={e => setComment(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !e.shiftKey && handleComment()}
                placeholder="Add a comment..."
                className="text-xs h-8 rounded-sm flex-1"
              />
              <Button size="sm" onClick={handleComment} disabled={submitting || !comment.trim()} className="rounded-sm h-8">
                {submitting ? <RefreshCw className="w-3 h-3 animate-spin" /> : "Send"}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function NewIncidentModal({ onClose, onCreated, devices }) {
  const [form, setForm] = useState({ title: "", description: "", device_id: "", device_name: "", severity: "medium", assignee: "", site: "" });
  const [submitting, setSubmitting] = useState(false);

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }));

  const handleDeviceChange = (id) => {
    const dev = devices.find(d => d.id === id);
    set("device_id", id);
    set("device_name", dev?.name || "");
  };

  const handleSubmit = async () => {
    if (!form.title.trim()) { toast.error("Title is required"); return; }
    setSubmitting(true);
    try {
      await api.post("/incidents", form);
      toast.success("Incident ticket created");
      onCreated();
      onClose();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to create incident");
    }
    setSubmitting(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative bg-background border border-border rounded-xl shadow-2xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold font-['Rajdhani']">New Incident Ticket</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-secondary"><X className="w-4 h-4" /></button>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Title *</label>
            <Input value={form.title} onChange={e => set("title", e.target.value)} placeholder="e.g. Router downstream link down" className="mt-1 text-sm h-9 rounded-sm" />
          </div>
          <div>
            <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Description</label>
            <textarea
              value={form.description}
              onChange={e => set("description", e.target.value)}
              placeholder="Describe the incident in detail..."
              rows={3}
              className="mt-1 w-full text-sm rounded-sm border border-input bg-background px-3 py-2 focus:outline-none focus:ring-1 focus:ring-ring resize-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Device</label>
              <Select value={form.device_id} onValueChange={handleDeviceChange}>
                <SelectTrigger className="mt-1 h-9 text-xs rounded-sm"><SelectValue placeholder="Select device" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {devices.map(d => <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Severity</label>
              <Select value={form.severity} onValueChange={v => set("severity", v)}>
                <SelectTrigger className="mt-1 h-9 text-xs rounded-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {["critical", "high", "medium", "low"].map(s => <SelectItem key={s} value={s}>{s.toUpperCase()}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Assignee</label>
              <Input value={form.assignee} onChange={e => set("assignee", e.target.value)} placeholder="Technician name" className="mt-1 text-sm h-9 rounded-sm" />
            </div>
            <div>
              <label className="text-[10px] uppercase text-muted-foreground tracking-wider">Site / Location</label>
              <Input value={form.site} onChange={e => set("site", e.target.value)} placeholder="e.g. Gedung A Lt.3" className="mt-1 text-sm h-9 rounded-sm" />
            </div>
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <Button variant="outline" className="flex-1 rounded-sm" onClick={onClose}>Cancel</Button>
          <Button className="flex-1 rounded-sm" onClick={handleSubmit} disabled={submitting}>
            {submitting ? <RefreshCw className="w-4 h-4 animate-spin" /> : "Create Ticket"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function KanbanColumn({ status, tickets, selectedId, onSelect }) {
  const cfg = COL_CONFIG[status];
  return (
    <div className="flex flex-col min-w-[280px] max-w-sm flex-1">
      {/* Column Header */}
      <div className={`flex items-center justify-between px-3 py-2.5 rounded-t-lg border ${cfg.headerBg} ${cfg.headerBorder}`}>
        <h3 className={`text-sm font-bold font-['Rajdhani'] uppercase tracking-wider ${cfg.headerText}`}>
          {cfg.label}
        </h3>
        <span className={`text-xs font-bold px-2 py-0.5 rounded-full text-white ${cfg.count_bg}`}>
          {tickets.length}
        </span>
      </div>
      {/* Cards */}
      <div className={`flex-1 rounded-b-lg border-x border-b ${cfg.headerBorder} bg-secondary/10 p-2 space-y-2 min-h-40 overflow-y-auto`}
        style={{ maxHeight: "calc(100vh - 300px)" }}
      >
        {tickets.length === 0 ? (
          <div className="flex items-center justify-center h-20 text-muted-foreground text-xs italic">No tickets</div>
        ) : (
          tickets.map(t => (
            <TicketCard key={t.id} ticket={t} onClick={onSelect} selected={selectedId === t.id} />
          ))
        )}
      </div>
    </div>
  );
}

export default function IncidentsPage() {
  const [kanban, setKanban] = useState({ open: [], in_progress: [], resolved: [], counts: {} });
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [showNewModal, setShowNewModal] = useState(false);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterSeverity, setFilterSeverity] = useState("");
  const [filterSearch, setFilterSearch] = useState("");
  const [stats, setStats] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [kanbanRes, devRes, statsRes] = await Promise.all([
        api.get("/incidents/kanban"),
        api.get("/devices"),
        api.get("/incidents/stats/overview"),
      ]);
      setKanban(kanbanRes.data);
      setDevices(devRes.data);
      setStats(statsRes.data);
    } catch (e) {
      console.error("Incidents fetch error:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const fetchSelectedTicket = useCallback(async (id) => {
    if (!id) return;
    try {
      const r = await api.get(`/incidents/${id}`);
      setSelectedTicket(r.data);
    } catch (e) { }
  }, []);

  const handleSelect = (ticket) => {
    fetchSelectedTicket(ticket.id);
  };

  const handleUpdate = () => {
    fetchAll();
    if (selectedTicket) fetchSelectedTicket(selectedTicket.id);
  };

  // Apply frontend filters
  const filterTickets = (tickets) => {
    return tickets.filter(t => {
      if (filterSeverity && t.severity !== filterSeverity) return false;
      if (filterSearch) {
        const q = filterSearch.toLowerCase();
        return t.title?.toLowerCase().includes(q) || t.device_name?.toLowerCase().includes(q) || t.id?.toLowerCase().includes(q);
      }
      return true;
    });
  };

  return (
    <div className="space-y-4 pb-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold font-['Rajdhani'] tracking-tight flex items-center gap-2">
            <AlertTriangle className="w-6 h-6 text-yellow-400" /> Incident Management
          </h1>
          <p className="text-sm text-muted-foreground">Track and resolve network incidents — Kanban style</p>
        </div>
        <div className="flex items-center gap-2">
          <Button className="rounded-sm text-sm" onClick={() => setShowNewModal(true)}>
            <Plus className="w-4 h-4 mr-1.5" /> New Ticket
          </Button>
          <Button variant="outline" size="icon" className="h-9 w-9 rounded-sm" onClick={fetchAll} disabled={loading}>
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Stats Row */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {[
            { label: "Open", value: stats.open, color: "text-red-400" },
            { label: "In Progress", value: stats.in_progress, color: "text-yellow-400" },
            { label: "Resolved", value: stats.resolved, color: "text-green-400" },
            { label: "Active Critical", value: stats.by_severity?.critical || 0, color: "text-red-500" },
          ].map(s => (
            <div key={s.label} className="bg-card border border-border rounded-sm px-4 py-3">
              <p className="text-[10px] uppercase text-muted-foreground">{s.label}</p>
              <p className={`text-2xl font-bold font-['Rajdhani'] ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex flex-wrap items-center gap-2 bg-card border border-border rounded-sm p-2">
        <Filter className="w-4 h-4 text-muted-foreground" />
        <div className="relative flex-1 min-w-40">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            value={filterSearch}
            onChange={e => setFilterSearch(e.target.value)}
            placeholder="Search by title, device, ID..."
            className="pl-7 text-xs h-8 rounded-sm"
          />
        </div>
        <Select value={filterSeverity} onValueChange={setFilterSeverity}>
          <SelectTrigger className="w-32 h-8 text-xs rounded-sm"><SelectValue placeholder="All Severity" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="">All Severity</SelectItem>
            {["critical", "high", "medium", "low"].map(s => <SelectItem key={s} value={s}>{s.toUpperCase()}</SelectItem>)}
          </SelectContent>
        </Select>
        {(filterSeverity || filterSearch) && (
          <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => { setFilterSeverity(""); setFilterSearch(""); }}>
            <X className="w-3 h-3 mr-1" /> Clear
          </Button>
        )}
      </div>

      {/* Kanban Board */}
      <div className="flex gap-4 overflow-x-auto pb-2">
        {["open", "in_progress", "resolved"].map(status => (
          <KanbanColumn
            key={status}
            status={status}
            tickets={filterTickets(kanban[status] || [])}
            selectedId={selectedTicket?.id}
            onSelect={handleSelect}
          />
        ))}
      </div>

      {/* Ticket Detail Side Panel */}
      {selectedTicket && (
        <TicketDetail
          ticket={selectedTicket}
          onClose={() => setSelectedTicket(null)}
          onUpdate={handleUpdate}
          users={[]}
        />
      )}

      {/* New Ticket Modal */}
      {showNewModal && (
        <NewIncidentModal
          onClose={() => setShowNewModal(false)}
          onCreated={fetchAll}
          devices={devices}
        />
      )}
    </div>
  );
}
