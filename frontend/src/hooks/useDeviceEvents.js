/**
 * useDeviceEvents — SSE hook untuk real-time device status dari backend
 * EventSource ke /api/events/devices, auto-reconnect jika disconnect.
 *
 * Returns:
 *   devices     : array device terbaru
 *   summary     : { total, online, offline }
 *   connected   : boolean
 *   lastUpdate  : ISO string timestamp update terakhir
 */
import { useState, useEffect, useRef, useCallback } from "react";

const SSE_URL = "/api/events/devices";
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

export default function useDeviceEvents() {
  const [devices, setDevices] = useState([]);
  const [summary, setSummary] = useState({ total: 0, online: 0, offline: 0 });
  const [connected, setConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  const esRef = useRef(null);
  const reconnectTimer = useRef(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (esRef.current) {
      esRef.current.close();
    }

    // Ambil token dari localStorage (sama dengan api.js)
    const token = localStorage.getItem("noc_token");
    if (!token) return;

    // SSE tidak support custom headers — kirim token via query param
    const url = `${SSE_URL}?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("device_status", (ev) => {
      if (!mountedRef.current) return;
      try {
        const data = JSON.parse(ev.data);
        setDevices(data.devices || []);
        setSummary(data.summary || { total: 0, online: 0, offline: 0 });
        setLastUpdate(data.timestamp || new Date().toISOString());
        attemptRef.current = 0; // reset pada sukses
      } catch (err) {
        console.warn("[SSE] parse error:", err);
      }
    });

    es.addEventListener("heartbeat", () => {
      // heartbeat diterima — koneksi masih hidup
      if (!mountedRef.current) return;
      setConnected(true);
    });

    es.onopen = () => {
      if (!mountedRef.current) return;
      setConnected(true);
      attemptRef.current = 0;
    };

    es.onerror = () => {
      if (!mountedRef.current) return;
      setConnected(false);
      es.close();

      if (attemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
        console.warn("[SSE] Max reconnect attempts reached, giving up");
        return;
      }

      const delay = Math.min(RECONNECT_DELAY_MS * (attemptRef.current + 1), 30_000);
      attemptRef.current += 1;
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current);
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [connect]);

  return { devices, summary, connected, lastUpdate };
}
