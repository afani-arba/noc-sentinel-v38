import { useState, useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
import {
  LayoutDashboard, Users, Wifi, FileText, Server, Shield, LogOut, Menu, ChevronLeft, Settings, Bell, HardDrive, Terminal,
  GitBranch, Route, Cable, ShieldAlert, Cpu, Receipt, Monitor, BarChart2, AlertTriangle, ClipboardList, Activity, Download, CalendarClock
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, DropdownMenuSeparator
} from "@/components/ui/dropdown-menu";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard", end: true },
  { to: "/pppoe", icon: Users, label: "PPPoE Users" },
  { to: "/hotspot", icon: Wifi, label: "Hotspot Users" },
  { to: "/reports", icon: FileText, label: "Reports" },
  { to: "/devices", icon: Server, label: "Devices", adminOnly: true },
  { separator: true, label: "Routing & Security", adminOnly: true },
  { to: "/bgp", icon: GitBranch, label: "BGP Peers", adminOnly: true },
  { to: "/routing", icon: Route, label: "OSPF / Routes", adminOnly: true },
  { to: "/connections", icon: Cable, label: "Active Connections", adminOnly: true },
  { to: "/firewall", icon: ShieldAlert, label: "Firewall Rules", adminOnly: true },
  { separator: true, label: "CPE Management", adminOnly: true },
  { to: "/genieacs", icon: Cpu, label: "GenieACS / TR-069", adminOnly: true },
  { separator: true, label: "v3 — NOC Features" },
  { to: "/wallboard", icon: Monitor, label: "Wall Display" },
  { to: "/bandwidth", icon: Activity, label: "Bandwidth Monitor" },
  { to: "/topology", icon: GitBranch, label: "Network Map" },
  { to: "/sla", icon: BarChart2, label: "SLA Monitor" },
  { to: "/incidents", icon: AlertTriangle, label: "Incidents" },
  { to: "/audit", icon: ClipboardList, label: "Audit Log", adminOnly: true },
  { separator: true, label: "Admin", adminOnly: true },
  { to: "/billing", icon: Receipt, label: "Billing", adminOnly: true },
  { to: "/notifications", icon: Bell, label: "Notifikasi", adminOnly: true },
  { to: "/backups", icon: HardDrive, label: "Backup Config", adminOnly: true },
  { to: "/scheduler", icon: CalendarClock, label: "Scheduler & Monitor", adminOnly: true },
  { to: "/syslog", icon: Terminal, label: "Syslog", adminOnly: true },
  { to: "/update", icon: Download, label: "Update Aplikasi", adminOnly: true },
  { to: "/settings", icon: Settings, label: "Pengaturan", adminOnly: true },
  { to: "/admin", icon: Shield, label: "Admin", adminOnly: true },
];

// ─── SidebarContent sebagai komponen TERPISAH di luar Layout ──────────────────
// PENTING: jangan definisikan komponen di dalam komponen lain —
// setiap render akan dianggap komponen baru → remount → scroll reset
function SidebarContent({ collapsed, filteredNav, user, onNavClick }) {
  return (
    <div className="flex flex-col h-full">
      {/* Logo */}
      <div className="flex items-center gap-3 px-4 h-16 border-b border-border/50 flex-shrink-0">
        <div className="w-8 h-8 rounded-sm bg-primary/20 flex items-center justify-center flex-shrink-0">
          <Server className="w-4 h-4 text-primary" />
        </div>
        {!collapsed && (
          <div className="overflow-hidden">
            <h1 className="text-base font-bold tracking-tight text-foreground font-['Rajdhani']">ARBA</h1>
            <p className="text-[10px] text-muted-foreground uppercase tracking-widest">Monitoring System</p>
          </div>
        )}
      </div>

      {/* Nav — scrollable */}
      <nav className="flex-1 min-h-0 px-2 py-4 space-y-1 overflow-y-auto">
        {filteredNav.map((item, idx) => {
          if (item.separator) {
            return (
              <div key={`sep-${idx}`} className="px-3 pt-3 pb-1">
                {!collapsed && (
                  <p className="text-[9px] text-muted-foreground/50 uppercase tracking-widest font-semibold">{item.label}</p>
                )}
                {collapsed && <div className="border-t border-border/30 my-1" />}
              </div>
            );
          }
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={onNavClick}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm transition-all duration-200 group ${
                  isActive
                    ? "bg-primary/10 text-primary border-l-2 border-primary"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
                }`
              }
            >
              <item.icon className="w-4 h-4 flex-shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* User info */}
      <div className="p-3 border-t border-border/50 flex-shrink-0">
        {!collapsed ? (
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-sm bg-secondary flex items-center justify-center text-xs font-semibold text-foreground">
              {user?.full_name?.charAt(0)?.toUpperCase() || "A"}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-foreground truncate">{user?.full_name}</p>
              <p className="text-[10px] text-muted-foreground capitalize">{user?.role}</p>
            </div>
          </div>
        ) : (
          <div className="w-8 h-8 rounded-sm bg-secondary flex items-center justify-center text-xs font-semibold text-foreground mx-auto">
            {user?.full_name?.charAt(0)?.toUpperCase() || "A"}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Layout ───────────────────────────────────────────────────────────────────
export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const timeStr = now.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dateStr = now.toLocaleDateString("id-ID", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const isAdmin = user?.role === "administrator";
  const filteredNav = navItems.filter((item) => !item.adminOnly || isAdmin);
  const closeMobile = () => setMobileOpen(false);

  return (
    <div className="flex h-screen overflow-hidden noise-bg" data-testid="app-layout">
      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="fixed inset-0 bg-black/60 z-40 lg:hidden" onClick={closeMobile} />
      )}

      {/* Sidebar — Mobile */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-60 bg-card border-r border-border transform transition-transform duration-300 lg:hidden ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <SidebarContent
          collapsed={false}
          filteredNav={filteredNav}
          user={user}
          onNavClick={closeMobile}
        />
      </aside>

      {/* Sidebar — Desktop */}
      <aside
        className={`hidden lg:flex flex-col border-r border-border bg-card transition-all duration-300 ${
          collapsed ? "w-16" : "w-60"
        }`}
      >
        <SidebarContent
          collapsed={collapsed}
          filteredNav={filteredNav}
          user={user}
          onNavClick={() => {}}
        />
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-14 flex items-center justify-between px-4 lg:px-6 border-b border-border/50 backdrop-blur-md bg-background/80 sticky top-0 z-30">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              onClick={() => setMobileOpen(true)}
              data-testid="mobile-menu-btn"
            >
              <Menu className="w-5 h-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="hidden lg:flex"
              onClick={() => setCollapsed(!collapsed)}
              data-testid="collapse-sidebar-btn"
            >
              <ChevronLeft className={`w-4 h-4 transition-transform ${collapsed ? "rotate-180" : ""}`} />
            </Button>
          </div>

          <div className="flex items-center gap-3">
            {/* Live Clock */}
            <div className="flex flex-col items-end">
              <span className="text-sm font-mono font-semibold text-foreground tabular-nums">{timeStr}</span>
              <span className="text-[10px] text-muted-foreground">{dateStr}</span>
            </div>

            <div className="hidden sm:flex items-center gap-2 px-3 py-1 rounded-sm bg-secondary/50 text-xs">
              <div className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
              <span className="text-muted-foreground font-mono">System Online</span>
            </div>

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="gap-2" data-testid="user-menu-btn">
                  <div className="w-6 h-6 rounded-sm bg-primary/20 flex items-center justify-center text-xs font-semibold text-primary">
                    {user?.full_name?.charAt(0)?.toUpperCase() || "A"}
                  </div>
                  <span className="hidden sm:inline text-sm">{user?.full_name}</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <div className="px-2 py-1.5">
                  <p className="text-sm font-medium">{user?.full_name}</p>
                  <p className="text-xs text-muted-foreground capitalize">{user?.role}</p>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={handleLogout} data-testid="logout-btn" className="text-destructive">
                  <LogOut className="w-4 h-4 mr-2" />
                  Logout
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
