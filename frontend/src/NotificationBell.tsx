import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Paginated } from "./types";

interface Notif {
  id: number;
  kind: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

const ICON: Record<string, string> = {
  assigned: "👤", overdue: "⏰", rotting: "🥀", transfer: "📦", system: "ℹ️",
};

/** N-1: in-app notification center. Polls every 60s. */
export default function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notif[]>([]);
  const ref = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    const r = await api<{ count: number }>("/notifications/unread_count/");
    setCount(r.count);
  }, []);

  useEffect(() => {
    void poll();
    const t = window.setInterval(() => void poll(), 60000);
    return () => window.clearInterval(t);
  }, [poll]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const toggle = async () => {
    if (!open) {
      setItems((await api<Paginated<Notif>>("/notifications/")).results.slice(0, 15));
    }
    setOpen(!open);
  };

  const markAll = async () => {
    await api("/notifications/read_all/", { method: "POST", body: {} });
    setCount(0);
    setItems((it) => it.map((n) => ({ ...n, read_at: n.read_at ?? "now" })));
  };

  const fmt = (iso: string) =>
    new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short",
      hour: "2-digit", minute: "2-digit" });

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="ghost" onClick={() => void toggle()} title="Notifications">
        🔔{count > 0 && (
          <span style={{ background: "var(--rot)", color: "#fff", borderRadius: 10,
            fontSize: 11, padding: "1px 6px", marginLeft: 4 }}>{count}</span>
        )}
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: "115%", width: 340,
          background: "#fff", border: "1px solid var(--line)", borderRadius: 8,
          boxShadow: "0 8px 24px rgba(9,30,66,.2)", zIndex: 40, maxHeight: 420,
          overflowY: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between",
            padding: "8px 12px", borderBottom: "1px solid var(--line)" }}>
            <strong style={{ fontSize: 13 }}>Notifications</strong>
            <a href="#" style={{ fontSize: 12 }}
              onClick={(e) => { e.preventDefault(); void markAll(); }}>Mark all read</a>
          </div>
          {items.length === 0 && (
            <div style={{ padding: 12, color: "var(--muted)", fontSize: 13 }}>
              Nothing yet.
            </div>
          )}
          {items.map((n) => (
            <div key={n.id} style={{ padding: "8px 12px", fontSize: 13,
              borderBottom: "1px solid var(--line)",
              background: n.read_at ? "#fff" : "#deebff44" }}>
              <div>{ICON[n.kind] ?? "·"} {n.title}</div>
              <div style={{ color: "var(--muted)", fontSize: 11 }}>
                {n.body ? `${n.body} · ` : ""}{fmt(n.created_at)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
