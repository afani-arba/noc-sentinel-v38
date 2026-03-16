import { useState, useEffect, createContext, useContext, useCallback } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import api from "@/lib/api";
import LoginPage from "@/pages/LoginPage";
import DashboardPage from "@/pages/DashboardPage";
import PPPoEUsersPage from "@/pages/PPPoEUsersPage";
import HotspotUsersPage from "@/pages/HotspotUsersPage";
import ReportsPage from "@/pages/ReportsPage";
import DevicesPage from "@/pages/DevicesPage";
import AdminPage from "@/pages/AdminPage";
import SettingsPage from "@/pages/SettingsPage";
import NotificationsPage from "@/pages/NotificationsPage";
import BackupsPage from "@/pages/BackupsPage";
import SyslogPage from "@/pages/SyslogPage";
import BGPPage from "@/pages/BGPPage";
import RoutingPage from "@/pages/RoutingPage";
import ConnectionsPage from "@/pages/ConnectionsPage";
import FirewallPage from "@/pages/FirewallPage";
import GenieACSPage from "@/pages/GenieACSPage";
import BillingPage from "@/pages/BillingPage";
import WallDisplayPage from "@/pages/WallDisplayPage";
import SLAPage from "@/pages/SLAPage";
import IncidentsPage from "@/pages/IncidentsPage";
import AuditLogPage from "@/pages/AuditLogPage";
import BandwidthPage from "@/pages/BandwidthPage";
import TopologyPage from "@/pages/TopologyPage";
import Layout from "@/components/Layout";
import { Toaster } from "@/components/ui/sonner";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("noc_token"));
  const [loading, setLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const res = await api.get("/auth/me");
      setUser(res.data);
    } catch {
      localStorage.removeItem("noc_token");
      localStorage.removeItem("noc_user");
      setToken(null);
      setUser(null);
    }
    setLoading(false);
  }, [token]);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = async (username, password) => {
    const res = await api.post("/auth/login", { username, password });
    const { token: t, user: u } = res.data;
    localStorage.setItem("noc_token", t);
    localStorage.setItem("noc_user", JSON.stringify(u));
    setToken(t);
    setUser(u);
    return u;
  };

  const logout = () => {
    localStorage.removeItem("noc_token");
    localStorage.removeItem("noc_user");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

function ProtectedRoute({ children, allowedRoles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex items-center justify-center min-h-screen bg-background"><div className="text-muted-foreground">Loading...</div></div>;
  if (!user) return <Navigate to="/login" />;
  if (allowedRoles && !allowedRoles.includes(user.role)) return <Navigate to="/" />;
  return children;
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Toaster
          theme="dark"
          toastOptions={{
            classNames: {
              toast: "bg-card border-border text-foreground",
              description: "text-muted-foreground",
            },
          }}
        />
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><Layout /></ProtectedRoute>}>
            <Route index element={<DashboardPage />} />
            <Route path="pppoe" element={<PPPoEUsersPage />} />
            <Route path="hotspot" element={<HotspotUsersPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="devices" element={<DevicesPage />} />
            <Route path="settings" element={<ProtectedRoute allowedRoles={["administrator"]}><SettingsPage /></ProtectedRoute>} />
            <Route path="notifications" element={<ProtectedRoute allowedRoles={["administrator"]}><NotificationsPage /></ProtectedRoute>} />
            <Route path="backups" element={<ProtectedRoute allowedRoles={["administrator"]}><BackupsPage /></ProtectedRoute>} />
            <Route path="syslog" element={<ProtectedRoute allowedRoles={["administrator"]}><SyslogPage /></ProtectedRoute>} />
            <Route path="admin" element={<ProtectedRoute allowedRoles={["administrator"]}><AdminPage /></ProtectedRoute>} />
            <Route path="bgp" element={<BGPPage />} />
            <Route path="routing" element={<RoutingPage />} />
            <Route path="connections" element={<ConnectionsPage />} />
            <Route path="firewall" element={<FirewallPage />} />
            <Route path="genieacs" element={<GenieACSPage />} />
            <Route path="billing" element={<ProtectedRoute allowedRoles={["administrator"]}><BillingPage /></ProtectedRoute>} />
            {/* v3 New Features */}
            <Route path="wallboard" element={<WallDisplayPage />} />
            <Route path="sla" element={<SLAPage />} />
            <Route path="incidents" element={<IncidentsPage />} />
            <Route path="audit" element={<ProtectedRoute allowedRoles={["administrator"]}><AuditLogPage /></ProtectedRoute>} />
            {/* v3.8 New Pages */}
            <Route path="bandwidth" element={<BandwidthPage />} />
            <Route path="topology" element={<TopologyPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
