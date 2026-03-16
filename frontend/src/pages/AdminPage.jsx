import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import { useAuth } from "@/App";
import { Plus, Pencil, Trash2, RefreshCw, Shield, Eye, User, Server, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";

const roleConfig = {
  administrator: { icon: Shield, color: "text-red-500", bg: "bg-red-500/10 border-red-500/20", desc: "Full access to all devices" },
  viewer: { icon: Eye, color: "text-blue-500", bg: "bg-blue-500/10 border-blue-500/20", desc: "View only selected devices" },
  user: { icon: User, color: "text-green-500", bg: "bg-green-500/10 border-green-500/20", desc: "Manage selected devices" },
};

export default function AdminPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [devices, setDevices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ username: "", password: "", full_name: "", role: "user", allowed_devices: [] });

  const fetchUsers = useCallback(async () => {
    try {
      const res = await api.get("/admin/users");
      setUsers(res.data);
    } catch (err) {
      toast.error("Failed to fetch users");
    }
    setLoading(false);
  }, []);

  const fetchDevices = useCallback(async () => {
    try {
      const res = await api.get("/devices/all");
      setDevices(res.data);
    } catch (err) {
      console.error("Failed to fetch devices for admin");
    }
  }, []);

  useEffect(() => {
    fetchUsers();
    fetchDevices();
  }, [fetchUsers, fetchDevices]);

  const openAdd = () => {
    setEditing(null);
    setForm({ username: "", password: "", full_name: "", role: "user", allowed_devices: [] });
    setDialogOpen(true);
  };

  const openEdit = (u) => {
    setEditing(u);
    setForm({ 
      username: u.username, 
      password: "", 
      full_name: u.full_name, 
      role: u.role,
      allowed_devices: u.allowed_devices || []
    });
    setDialogOpen(true);
  };

  const toggleDevice = (deviceId) => {
    setForm(prev => ({
      ...prev,
      allowed_devices: prev.allowed_devices.includes(deviceId)
        ? prev.allowed_devices.filter(id => id !== deviceId)
        : [...prev.allowed_devices, deviceId]
    }));
  };

  const selectAllDevices = () => {
    setForm(prev => ({
      ...prev,
      allowed_devices: devices.map(d => d.id)
    }));
  };

  const clearAllDevices = () => {
    setForm(prev => ({
      ...prev,
      allowed_devices: []
    }));
  };

  const handleSave = async () => {
    try {
      if (editing) {
        const data = { 
          full_name: form.full_name, 
          role: form.role,
          allowed_devices: form.role === "administrator" ? [] : form.allowed_devices
        };
        if (form.password) data.password = form.password;
        await api.put(`/admin/users/${editing.id}`, data);
        toast.success("User updated");
      } else {
        if (!form.username || !form.password || !form.full_name) {
          toast.error("All fields are required");
          return;
        }
        const data = {
          ...form,
          allowed_devices: form.role === "administrator" ? [] : form.allowed_devices
        };
        await api.post("/admin/users", data);
        toast.success("User created");
      }
      setDialogOpen(false);
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Operation failed");
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm("Delete this user?")) return;
    try {
      await api.delete(`/admin/users/${id}`);
      toast.success("User deleted");
      fetchUsers();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Delete failed");
    }
  };

  const getDeviceNames = (allowedDevices) => {
    if (!allowedDevices || allowedDevices.length === 0) return "-";
    return devices
      .filter(d => allowedDevices.includes(d.id))
      .map(d => d.name)
      .join(", ") || "-";
  };

  return (
    <div className="space-y-6" data-testid="admin-page">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold font-['Rajdhani'] tracking-tight">User Management</h1>
          <p className="text-xs sm:text-sm text-muted-foreground mt-1">Manage system users, roles, and device access</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="icon" onClick={fetchUsers} className="rounded-sm" data-testid="admin-refresh-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
          <Button onClick={openAdd} className="rounded-sm gap-2" data-testid="add-admin-user-btn">
            <Plus className="w-4 h-4" /> <span className="hidden sm:inline">Add User</span>
          </Button>
        </div>
      </div>

      {/* Role Summary */}
      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        {["administrator", "viewer", "user"].map((role) => {
          const config = roleConfig[role];
          const count = users.filter((u) => u.role === role).length;
          return (
            <div key={role} className="bg-card border border-border rounded-sm p-3 sm:p-4">
              <div className="flex items-center gap-2 mb-2">
                <config.icon className={`w-4 h-4 ${config.color}`} />
                <span className="text-[10px] sm:text-xs text-muted-foreground capitalize">{role}s</span>
              </div>
              <p className="text-xl sm:text-2xl font-bold font-['Rajdhani']">{count}</p>
            </div>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-sm overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="text-xs">Full Name</TableHead>
              <TableHead className="text-xs hidden sm:table-cell">Username</TableHead>
              <TableHead className="text-xs">Role</TableHead>
              <TableHead className="text-xs hidden md:table-cell">Allowed Devices</TableHead>
              <TableHead className="text-xs text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground py-8">Loading...</TableCell></TableRow>
            ) : users.length === 0 ? (
              <TableRow><TableCell colSpan={5} className="text-center text-muted-foreground py-8">No users found</TableCell></TableRow>
            ) : (
              users.map((u) => {
                const config = roleConfig[u.role] || roleConfig.user;
                return (
                  <TableRow key={u.id} data-testid={`admin-row-${u.username}`}>
                    <TableCell className="font-medium text-xs sm:text-sm">
                      {u.full_name}
                      <span className="block sm:hidden text-[10px] text-muted-foreground font-mono">{u.username}</span>
                    </TableCell>
                    <TableCell className="font-mono text-xs hidden sm:table-cell">{u.username}</TableCell>
                    <TableCell>
                      <Badge className={`rounded-sm text-[10px] sm:text-xs border capitalize ${config.bg} ${config.color}`}>
                        <config.icon className="w-3 h-3 mr-1 hidden sm:inline" />{u.role}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-xs text-muted-foreground max-w-[200px] truncate">
                      {u.role === "administrator" ? (
                        <span className="text-primary">All Devices</span>
                      ) : (
                        getDeviceNames(u.allowed_devices)
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(u)} data-testid={`admin-edit-${u.username}`}>
                          <Pencil className="w-3.5 h-3.5" />
                        </Button>
                        {u.id !== currentUser?.id && (
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive" onClick={() => handleDelete(u.id)} data-testid={`admin-delete-${u.username}`}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
        </Table>
      </div>

      <p className="text-xs text-muted-foreground">Total: {users.length} users</p>

      {/* Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="rounded-sm bg-card border-border max-w-lg max-h-[90vh] overflow-y-auto" data-testid="admin-user-dialog">
          <DialogHeader>
            <DialogTitle className="font-['Rajdhani'] text-xl">{editing ? "Edit User" : "Add User"}</DialogTitle>
            <DialogDescription>
              {editing ? "Update user details, role, and device access." : "Create a new system user with device permissions."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {!editing && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Username</Label>
                <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className="rounded-sm bg-background" data-testid="admin-form-username" />
              </div>
            )}
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Full Name</Label>
              <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className="rounded-sm bg-background" data-testid="admin-form-fullname" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">{editing ? "New Password (leave empty to keep)" : "Password"}</Label>
              <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className="rounded-sm bg-background" placeholder={editing ? "(unchanged)" : ""} data-testid="admin-form-password" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs text-muted-foreground">Role</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger className="rounded-sm bg-background" data-testid="admin-form-role">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="administrator">
                    <div className="flex items-center gap-2">
                      <Shield className="w-3 h-3 text-red-500" />
                      <span>Administrator</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="viewer">
                    <div className="flex items-center gap-2">
                      <Eye className="w-3 h-3 text-blue-500" />
                      <span>Viewer</span>
                    </div>
                  </SelectItem>
                  <SelectItem value="user">
                    <div className="flex items-center gap-2">
                      <User className="w-3 h-3 text-green-500" />
                      <span>User</span>
                    </div>
                  </SelectItem>
                </SelectContent>
              </Select>
              <p className="text-[10px] text-muted-foreground">{roleConfig[form.role]?.desc}</p>
            </div>

            {/* Device Access - Only show for non-admin roles */}
            {form.role !== "administrator" && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-muted-foreground">Allowed Devices</Label>
                  <div className="flex gap-2">
                    <Button type="button" variant="ghost" size="sm" className="h-6 text-[10px]" onClick={selectAllDevices}>
                      Select All
                    </Button>
                    <Button type="button" variant="ghost" size="sm" className="h-6 text-[10px]" onClick={clearAllDevices}>
                      Clear
                    </Button>
                  </div>
                </div>
                <div className="border border-border rounded-sm p-3 max-h-48 overflow-y-auto bg-background/50 space-y-2">
                  {devices.length === 0 ? (
                    <p className="text-xs text-muted-foreground text-center py-2">No devices found</p>
                  ) : (
                    devices.map((device) => (
                      <div 
                        key={device.id} 
                        className={`flex items-center gap-3 p-2 rounded-sm cursor-pointer transition-colors ${
                          form.allowed_devices.includes(device.id) 
                            ? 'bg-primary/10 border border-primary/30' 
                            : 'hover:bg-secondary/50'
                        }`}
                        onClick={() => toggleDevice(device.id)}
                      >
                        <div className={`w-5 h-5 rounded-sm border flex items-center justify-center ${
                          form.allowed_devices.includes(device.id) 
                            ? 'bg-primary border-primary' 
                            : 'border-border'
                        }`}>
                          {form.allowed_devices.includes(device.id) && (
                            <Check className="w-3 h-3 text-primary-foreground" />
                          )}
                        </div>
                        <Server className="w-4 h-4 text-muted-foreground" />
                        <div className="flex-1 min-w-0">
                          <p className="text-xs font-medium truncate">{device.name}</p>
                          <p className="text-[10px] text-muted-foreground font-mono">{device.ip_address}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Selected: {form.allowed_devices.length} of {devices.length} devices
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)} className="rounded-sm" data-testid="admin-form-cancel">Cancel</Button>
            <Button onClick={handleSave} className="rounded-sm" data-testid="admin-form-save">{editing ? "Update" : "Create"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
