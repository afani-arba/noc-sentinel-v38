"""
Unified MikroTik API client supporting both:
  - RouterOS 6.x: MikroTik API protocol (port 8728/8729)
  - RouterOS 7.x: REST API (port 443/80)
Both implementations share the same interface.
"""
import ssl
import requests
import asyncio
import logging
import urllib3
import routeros_api
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


# ── Custom SSL Adapter for MikroTik ROS 7.x ──────────────────────────────────
# MikroTik ROS 7.x uses TLS ciphers/versions that OpenSSL 3.x rejects by default.
# SECLEVEL=0 allows ALL ciphers; MINIMUM_SUPPORTED allows TLS 1.0/1.1/1.2/1.3.
# OP_LEGACY_SERVER_CONNECT: OpenSSL 3.x bridging flag for legacy server hello.
# This fixes: "sslv3 alert handshake failure" / "Cipher is (NONE)" errors.

class MikroTikSSLAdapter(HTTPAdapter):
    """Custom HTTPS adapter with maximal SSL permissiveness for MikroTik ROS 7.x."""

    def _make_ssl_ctx(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except ssl.SSLError:
            pass
        try:
            ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        except (AttributeError, ValueError):
            pass
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        except AttributeError:
            pass
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._make_ssl_ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        proxy_kwargs["ssl_context"] = self._make_ssl_ctx()
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _make_session() -> requests.Session:
    """Create a requests.Session with MikroTik-compatible SSL settings."""
    session = requests.Session()
    session.mount("https://", MikroTikSSLAdapter())
    return session



# ── Base interface ──
class MikroTikBase:
    async def test_connection(self): raise NotImplementedError
    async def list_pppoe_secrets(self): raise NotImplementedError
    async def create_pppoe_secret(self, data): raise NotImplementedError
    async def update_pppoe_secret(self, mt_id, data): raise NotImplementedError
    async def delete_pppoe_secret(self, mt_id): raise NotImplementedError
    async def list_pppoe_active(self): raise NotImplementedError
    async def disable_pppoe_user(self, username): raise NotImplementedError
    async def enable_pppoe_user(self, username): raise NotImplementedError
    async def list_hotspot_users(self): raise NotImplementedError
    async def create_hotspot_user(self, data): raise NotImplementedError
    async def update_hotspot_user(self, mt_id, data): raise NotImplementedError
    async def delete_hotspot_user(self, mt_id): raise NotImplementedError
    async def list_hotspot_active(self): raise NotImplementedError
    async def disable_hotspot_user(self, username): raise NotImplementedError
    async def enable_hotspot_user(self, username): raise NotImplementedError
    async def list_pppoe_profiles(self): raise NotImplementedError
    async def list_hotspot_profiles(self): raise NotImplementedError
    async def list_hotspot_servers(self): raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# RouterOS 7+ REST API
# ═══════════════════════════════════════════════════════════
class MikroTikRestAPI(MikroTikBase):
    def __init__(self, host, username, password, port=443, use_ssl=True):
        scheme = "https" if use_ssl else "http"
        self.base_url = f"{scheme}://{host}:{port}/rest"
        self.auth = (username, password)
        self.verify = False
        self.timeout = 30  # Increased timeout to 30 seconds
        self.host = host
        self.port = port
        self.use_ssl = use_ssl

    def _request(self, method, path, data=None):
        url = f"{self.base_url}/{path}"
        logger.info(f"REST API request: {method} {url}")
        try:
            # Use custom session with MikroTik-compatible SSL ciphers
            session = _make_session()
            resp = session.request(method, url, auth=self.auth, json=data,
                                   verify=False, timeout=self.timeout)
            logger.info(f"REST API response: {resp.status_code}")
            if resp.status_code == 401:
                raise Exception("Authentication failed - check API username/password")
            if resp.status_code == 400:
                detail = resp.json() if resp.content else {}
                raise Exception(f"Bad request: {detail.get('detail', detail.get('message', resp.text))}")
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL Error: {e}")
            err = str(e)
            if "handshake" in err.lower() or "cipher" in err.lower() or "alert" in err.lower():
                raise Exception(f"SSL Handshake gagal ke {self.host}:{self.port} - cipher mismatch antara server dan MikroTik. Coba ganti ke HTTP (port 80) di konfigurasi device.")
            raise Exception(f"SSL Error - pastikan pilih protokol yang benar (HTTP/HTTPS)")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection Error to {url}: {e}")
            error_msg = str(e)
            if "Connection refused" in error_msg:
                raise Exception(f"Connection refused - pastikan www service aktif di port {self.port} dan tidak ada firewall yang memblokir")
            elif "No route to host" in error_msg:
                raise Exception(f"No route to host - periksa IP address dan jaringan")
            else:
                raise Exception(f"Tidak dapat terhubung ke {self.host}:{self.port} - pastikan: 1) www service aktif, 2) port {self.port} tidak diblokir firewall, 3) IP server monitoring diizinkan di MikroTik")
        except requests.exceptions.Timeout:
            raise Exception(f"Connection timeout ke {self.host}:{self.port} - periksa: 1) Firewall MikroTik, 2) www service address restriction, 3) Koneksi jaringan")
        except Exception as e:
            if any(k in str(e) for k in ["Authentication", "Bad request", "Cannot connect", "timeout", "SSL Error", "Connection refused", "No route"]):
                raise
            raise Exception(f"REST API error: {e}")

    async def _async_req(self, method, path, data=None):
        return await asyncio.to_thread(self._request, method, path, data)

    async def test_connection(self):
        try:
            r = await self._async_req("GET", "system/identity")
            return {"success": True, "identity": r.get("name", ""), "mode": "REST API (RouterOS 7+)"}
        except Exception as e:
            return {"success": False, "error": str(e), "mode": "REST API (RouterOS 7+)"}

    async def list_pppoe_secrets(self):
        return await self._async_req("GET", "ppp/secret")

    async def create_pppoe_secret(self, data):
        return await self._async_req("PUT", "ppp/secret", data)

    async def update_pppoe_secret(self, mt_id, data):
        return await self._async_req("PATCH", f"ppp/secret/{mt_id}", data)

    async def delete_pppoe_secret(self, mt_id):
        return await self._async_req("DELETE", f"ppp/secret/{mt_id}")

    async def list_pppoe_active(self):
        return await self._async_req("GET", "ppp/active")

    async def disable_pppoe_user(self, username):
        """Disable PPPoE secret by username. ROS 7.x REST API: disabled = true (boolean JSON)."""
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                # ROS 7.x REST API needs boolean true, not string "true"
                return await self._async_req("PATCH", f"ppp/secret/{mt_id}", {"disabled": True})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    async def enable_pppoe_user(self, username):
        """Enable PPPoE secret by username."""
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                return await self._async_req("PATCH", f"ppp/secret/{mt_id}", {"disabled": False})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    async def list_hotspot_users(self):
        return await self._async_req("GET", "ip/hotspot/user")

    async def create_hotspot_user(self, data):
        return await self._async_req("PUT", "ip/hotspot/user", data)

    async def update_hotspot_user(self, mt_id, data):
        return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", data)

    async def delete_hotspot_user(self, mt_id):
        return await self._async_req("DELETE", f"ip/hotspot/user/{mt_id}")

    async def list_hotspot_active(self):
        return await self._async_req("GET", "ip/hotspot/active")

    async def disable_hotspot_user(self, username):
        """Disable Hotspot user. ROS 7.x REST API: disabled = true (boolean)."""
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", {"disabled": True})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def enable_hotspot_user(self, username):
        """Enable Hotspot user."""
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await self._async_req("PATCH", f"ip/hotspot/user/{mt_id}", {"disabled": False})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def list_pppoe_profiles(self):
        try:
            return await self._async_req("GET", "ppp/profile")
        except Exception:
            return []

    async def list_hotspot_profiles(self):
        """ROS 7.x: /ip/hotspot/user-profile (bukan /user/profile)"""
        try:
            return await self._async_req("GET", "ip/hotspot/user-profile")
        except Exception:
            try:
                # fallback lama
                return await self._async_req("GET", "ip/hotspot/user/profile")
            except Exception:
                return []

    async def list_hotspot_servers(self):
        try:
            return await self._async_req("GET", "ip/hotspot")
        except Exception:
            return []

    # ── BGP — ROS 7.x pakai /routing/bgp/connection, ROS 6 pakai /routing/bgp/peer ──
    async def list_bgp_peers(self):
        try:
            # ROS 7.x
            return await self._async_req("GET", "routing/bgp/connection")
        except Exception:
            try:
                # ROS 6.x fallback
                return await self._async_req("GET", "routing/bgp/peer")
            except Exception:
                return []

    async def list_bgp_sessions(self):
        try:
            return await self._async_req("GET", "routing/bgp/session")
        except Exception:
            return []

    # ── System Resource (ROS 7.x REST API) ──
    async def get_system_resource(self):
        """Ambil CPU, memory, uptime dari /rest/system/resource."""
        try:
            return await self._async_req("GET", "system/resource")
        except Exception:
            return {}

    # ── System Health (ROS 7.x: temperature, voltage, power) ──
    async def get_system_health(self):
        """
        Ambil data sensor hardware dari /rest/system/health.
        Field nyata dari MikroTik ROS 7.x:
          {name: cpu-temperature, value: 47, type: C}
          {name: sfp-temperature, value: 38, type: C}
          {name: switch-temperature, value: 39, type: C}
          {name: board-temperature1, value: 39, type: C}
          {name: fan1-speed, value: 4080, type: RPM}
          {name: fan-state, value: ok}
          {name: psu1-state, value: fail}
          {name: psu2-state, value: ok}
          {name: voltage, value: 240, type: dV}   (some devices)
        """
        try:
            items = await self._async_req("GET", "system/health")
            if not isinstance(items, list):
                return {}

            result = {
                "cpu_temp": 0,
                "board_temp": 0,
                "sfp_temp": 0,
                "switch_temp": 0,
                "voltage": 0,
                "power": 0,
                "fans": {},        # {fan1: 4080, fan2: 4020, ...}
                "fan_state": "",   # "ok" / "fail"
                "psu": {},         # {psu1: "ok", psu2: "fail", ...}
                "extra_temps": {}, # {sfp: 38, switch: 39, ...}
            }

            for item in items:
                name = (item.get("name") or "").lower()
                raw_val = item.get("value", "")
                unit = (item.get("type") or "").upper()

                # Try numeric conversion
                try:
                    num_val = float(str(raw_val))
                except (ValueError, TypeError):
                    num_val = None

                # ── Temperatures ──────────────────────────────────
                if name == "cpu-temperature":
                    result["cpu_temp"] = num_val or 0

                elif name.startswith("board-temperature"):
                    # board-temperature, board-temperature1, board-temperature2
                    if result["board_temp"] == 0:
                        result["board_temp"] = num_val or 0

                elif name == "sfp-temperature":
                    result["sfp_temp"] = num_val or 0
                    result["extra_temps"]["sfp"] = num_val or 0

                elif name == "switch-temperature":
                    result["switch_temp"] = num_val or 0
                    result["extra_temps"]["switch"] = num_val or 0

                elif "temperature" in name:
                    # catch-all for other temperature sensors
                    key = name.replace("-temperature", "").replace("-temp", "")
                    result["extra_temps"][key] = num_val or 0
                    if result["board_temp"] == 0:
                        result["board_temp"] = num_val or 0

                # ── Voltage ───────────────────────────────────────
                elif "voltage" in name:
                    if num_val is not None:
                        # MikroTik may return dV (deci-volt): 240 dV = 24.0 V
                        voltage = num_val / 10.0 if unit == "DV" or num_val > 100 else num_val
                        result.setdefault("voltage", round(voltage, 1))

                # ── Power ─────────────────────────────────────────
                elif "power" in name and "psu" not in name:
                    result.setdefault("power", num_val or 0)

                # ── Current ───────────────────────────────────────
                elif name == "current":
                    result["current"] = num_val or 0

                # ── Fan speed (fan1-speed, fan2-speed ...) ────────
                elif name.endswith("-speed") and "fan" in name:
                    fan_key = name.replace("-speed", "")  # fan1, fan2, ...
                    result["fans"][fan_key] = int(num_val) if num_val else 0

                # ── Fan state (ok / fail) ─────────────────────────
                elif name == "fan-state":
                    result["fan_state"] = str(raw_val).lower()

                # ── PSU state (psu1-state, psu2-state) ───────────
                elif name.endswith("-state") and "psu" in name:
                    psu_key = name.replace("-state", "")  # psu1, psu2, ...
                    result["psu"][psu_key] = str(raw_val).lower()

            return result
        except Exception:
            return {}

    # ── Interface List ──
    async def list_interfaces(self):
        """List semua interface beserta status running/disabled."""
        try:
            ifaces = await self._async_req("GET", "interface")
            return ifaces if isinstance(ifaces, list) else []
        except Exception:
            return []

    # ── Interface Traffic (monitor-traffic via POST, ROS 7.x) ──
    async def get_interface_traffic(self, interface_name: str = "ether1", duration: int = 1):
        """
        Ambil traffic realtime via /rest/interface/monitor-traffic.
        ROS 7.x: POST dengan body {"interface": "ether1", "once": ""}
        Return: {"rx-bits-per-second": ..., "tx-bits-per-second": ...}
        """
        try:
            result = await self._async_req(
                "POST", "interface/monitor-traffic",
                {"interface": interface_name, "once": ""}
            )
            if isinstance(result, list):
                return result[0] if result else {}
            return result
        except Exception:
            return {}

    # ── IP Address List ──
    async def list_ip_addresses(self):
        """List semua IP address yang dikonfigurasi."""
        try:
            return await self._async_req("GET", "ip/address")
        except Exception:
            return []

    # ── OSPF ──
    async def list_ospf_neighbors(self):
        try:
            return await self._async_req("GET", "routing/ospf/neighbor")
        except Exception:
            return []

    async def list_ospf_instances(self):
        try:
            return await self._async_req("GET", "routing/ospf/instance")
        except Exception:
            return []

    # ── IP Routes ──
    async def list_ip_routes(self, limit: int = 200):
        try:
            routes = await self._async_req("GET", "ip/route")
            return routes[:limit] if isinstance(routes, list) else []
        except Exception:
            return []

    # ── Active Connections ──
    async def list_connections(self, limit: int = 500):
        try:
            conns = await self._async_req("GET", "ip/firewall/connection")
            return conns[:limit] if isinstance(conns, list) else []
        except Exception:
            return []

    # ── Firewall ──
    async def list_firewall_filter(self):
        try:
            return await self._async_req("GET", "ip/firewall/filter")
        except Exception:
            return []

    async def list_firewall_nat(self):
        try:
            return await self._async_req("GET", "ip/firewall/nat")
        except Exception:
            return []

    async def list_firewall_mangle(self):
        try:
            return await self._async_req("GET", "ip/firewall/mangle")
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
# RouterOS 6.x+ MikroTik API Protocol (port 8728/8729)
# ═══════════════════════════════════════════════════════════
class MikroTikRouterAPI(MikroTikBase):
    def __init__(self, host, username, password, port=8728, use_ssl=False, plaintext_login=True):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.use_ssl = use_ssl
        self.plaintext_login = plaintext_login

    def _get_connection(self):
        """Create a new connection to the router."""
        try:
            pool = routeros_api.RouterOsApiPool(
                host=self.host,
                username=self.username,
                password=self.password,
                port=self.port,
                use_ssl=self.use_ssl,
                ssl_verify=False,
                plaintext_login=self.plaintext_login,
            )
            return pool
        except Exception as e:
            raise Exception(f"Cannot connect to MikroTik API at {self.host}:{self.port} - {e}")

    def _execute(self, callback):
        """Execute a callback with a connection, ensuring cleanup."""
        pool = self._get_connection()
        try:
            api = pool.get_api()
            result = callback(api)
            return result
        finally:
            try:
                pool.disconnect()
            except Exception:
                pass

    def _list_resource(self, path):
        def cb(api):
            resource = api.get_resource(path)
            return resource.get()
        return self._execute(cb)

    def _add_resource(self, path, data):
        def cb(api):
            resource = api.get_resource(path)
            # routeros_api uses keyword arguments
            resource.add(**data)
            return {"success": True}
        return self._execute(cb)

    def _set_resource(self, path, mt_id, data):
        def cb(api):
            resource = api.get_resource(path)
            resource.set(id=mt_id, **data)
            return {"success": True}
        return self._execute(cb)

    def _remove_resource(self, path, mt_id):
        def cb(api):
            resource = api.get_resource(path)
            resource.remove(id=mt_id)
            return {"success": True}
        return self._execute(cb)

    # Normalize RouterOS 6 API response to match REST API format
    def _normalize_items(self, items):
        """RouterOS API returns list of dicts with 'id' key. Normalize to match REST format."""
        result = []
        for item in items:
            normalized = {}
            for k, v in item.items():
                normalized[k] = v
            # Ensure .id field exists (RouterOS API uses 'id')
            if "id" in normalized and ".id" not in normalized:
                normalized[".id"] = normalized["id"]
            result.append(normalized)
        return result

    async def test_connection(self):
        try:
            def cb(api):
                resource = api.get_resource("/system/identity")
                return resource.get()
            result = await asyncio.to_thread(self._execute, cb)
            name = result[0].get("name", "") if result else ""
            return {"success": True, "identity": name, "mode": "API Protocol (RouterOS 6+)"}
        except Exception as e:
            return {"success": False, "error": str(e), "mode": "API Protocol (RouterOS 6+)"}

    # ── PPPoE ──
    async def list_pppoe_secrets(self):
        items = await asyncio.to_thread(self._list_resource, "/ppp/secret")
        return self._normalize_items(items)

    async def create_pppoe_secret(self, data):
        return await asyncio.to_thread(self._add_resource, "/ppp/secret", data)

    async def update_pppoe_secret(self, mt_id, data):
        return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, data)

    async def delete_pppoe_secret(self, mt_id):
        return await asyncio.to_thread(self._remove_resource, "/ppp/secret", mt_id)

    async def list_pppoe_active(self):
        items = await asyncio.to_thread(self._list_resource, "/ppp/active")
        return self._normalize_items(items)

    async def disable_pppoe_user(self, username):
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, {"disabled": "true"})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    async def enable_pppoe_user(self, username):
        secrets = await self.list_pppoe_secrets()
        for s in secrets:
            if s.get("name") == username:
                mt_id = s.get(".id") or s.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ppp/secret", mt_id, {"disabled": "false"})
        raise Exception(f"PPPoE user '{username}' tidak ditemukan")

    # ── Hotspot ──
    async def list_hotspot_users(self):
        items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user")
        return self._normalize_items(items)

    async def create_hotspot_user(self, data):
        return await asyncio.to_thread(self._add_resource, "/ip/hotspot/user", data)

    async def update_hotspot_user(self, mt_id, data):
        return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, data)

    async def delete_hotspot_user(self, mt_id):
        return await asyncio.to_thread(self._remove_resource, "/ip/hotspot/user", mt_id)

    async def list_hotspot_active(self):
        items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/active")
        return self._normalize_items(items)

    async def disable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, {"disabled": "true"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def enable_hotspot_user(self, username):
        users = await self.list_hotspot_users()
        for u in users:
            if u.get("name") == username:
                mt_id = u.get(".id") or u.get("id", "")
                return await asyncio.to_thread(self._set_resource, "/ip/hotspot/user", mt_id, {"disabled": "false"})
        raise Exception(f"Hotspot user '{username}' tidak ditemukan")

    async def list_pppoe_profiles(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ppp/profile")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_hotspot_profiles(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user-profile")
            return self._normalize_items(items)
        except Exception:
            try:
                items = await asyncio.to_thread(self._list_resource, "/ip/hotspot/user/profile")
                return self._normalize_items(items)
            except Exception:
                return []

    async def list_hotspot_servers(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/hotspot")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── System Resource ──
    async def get_system_resource(self):
        """Ambil CPU, memory, uptime dari /system/resource."""
        try:
            items = await asyncio.to_thread(self._list_resource, "/system/resource")
            return items[0] if items else {}
        except Exception:
            return {}

    # ── Interface List ──
    async def list_interfaces(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/interface")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── Interface Traffic (RouterOS 6 API) ──
    async def get_interface_traffic(self, interface_name: str = "ether1", duration: int = 1):
        """ROS 6: monitor traffic via API command."""
        try:
            def cb(api):
                resource = api.get_resource("/interface")
                cmd = api.get_binary_resource("/")
                return cmd.call(
                    "interface/monitor-traffic",
                    {"interface": interface_name, "once": ""}
                )
            items = await asyncio.to_thread(self._execute, cb)
            return items[0] if items else {}
        except Exception:
            return {}

    # ── IP Address List ──
    async def list_ip_addresses(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/address")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── BGP ──
    async def list_bgp_peers(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/bgp/peer")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_bgp_sessions(self):
        return []  # RouterOS 6 doesn't have separate sessions

    # ── OSPF ──
    async def list_ospf_neighbors(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/ospf/neighbor")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_ospf_instances(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/routing/ospf/instance")
            return self._normalize_items(items)
        except Exception:
            return []

    # ── IP Routes ──
    async def list_ip_routes(self, limit: int = 200):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/route")
            return self._normalize_items(items)[:limit]
        except Exception:
            return []

    # ── Active Connections ──
    async def list_connections(self, limit: int = 500):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/connection")
            return self._normalize_items(items)[:limit]
        except Exception:
            return []

    # ── Firewall ──
    async def list_firewall_filter(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/filter")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_firewall_nat(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/nat")
            return self._normalize_items(items)
        except Exception:
            return []

    async def list_firewall_mangle(self):
        try:
            items = await asyncio.to_thread(self._list_resource, "/ip/firewall/mangle")
            return self._normalize_items(items)
        except Exception:
            return []


# ═══════════════════════════════════════════════════════════
# Factory function
# ═══════════════════════════════════════════════════════════
def get_api_client(device: dict) -> MikroTikBase:
    """Create the appropriate MikroTik API client based on device config."""
    mode = device.get("api_mode", "rest")

    if mode == "api":
        # RouterOS 6+ API protocol
        port = device.get("api_port") or 8728
        return MikroTikRouterAPI(
            host=device["ip_address"],
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=device.get("api_ssl", False),
            plaintext_login=device.get("api_plaintext_login", True),
        )
    else:
        # RouterOS 7+ REST API
        port = device.get("api_port") or 443
        # Gunakan use_https dari form, default False (HTTP)
        use_https = device.get("use_https", False)
        
        logger.info(f"Creating REST API client: host={device['ip_address']}, port={port}, https={use_https}")
        
        return MikroTikRestAPI(
            host=device["ip_address"],
            username=device.get("api_username", "admin"),
            password=device.get("api_password", ""),
            port=port,
            use_ssl=use_https,
        )
