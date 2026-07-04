/** UI primitives — replaces every browser prompt()/confirm() in the app. */
import { useCallback, useEffect, useRef, useState } from "react";

/* ---------- Toasts (module-level bus, no context needed) ---------- */

export interface Toast { id: number; kind: "ok" | "err" | "info"; text: string }
type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
let listeners: Listener[] = [];
let nextId = 1;

function push(kind: Toast["kind"], text: string) {
  const t = { id: nextId++, kind, text };
  toasts = [...toasts, t];
  listeners.forEach((l) => l(toasts));
  window.setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== t.id);
    listeners.forEach((l) => l(toasts));
  }, 3800);
}

export const toast = {
  ok: (text: string) => push("ok", text),
  err: (text: string) => push("err", text),
  info: (text: string) => push("info", text),
};

export function Toasts() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const l: Listener = (t) => setItems(t);
    listeners.push(l);
    return () => { listeners = listeners.filter((x) => x !== l); };
  }, []);
  return (
    <div style={{ position: "fixed", bottom: 18, left: "50%", transform: "translateX(-50%)",
      zIndex: 200, display: "flex", flexDirection: "column", gap: 8, alignItems: "center" }}>
      {items.map((t) => (
        <div key={t.id} role="status" style={{
          background: t.kind === "err" ? "var(--rot)" : t.kind === "ok" ? "#172b4d" : "var(--accent)",
          color: "#fff", padding: "10px 18px", borderRadius: 8, fontSize: 13.5,
          boxShadow: "0 6px 20px rgba(9,30,66,.35)", maxWidth: 420,
          animation: "toast-in .18s ease-out" }}>
          {t.kind === "ok" ? "✓ " : t.kind === "err" ? "✗ " : ""}{t.text}
        </div>
      ))}
    </div>
  );
}

/* ---------- Modal ---------- */

export function Modal({ title, onClose, children, width = 380 }: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  width?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    // focus first focusable element
    const el = ref.current?.querySelector<HTMLElement>(
      "button, input, select, textarea, [tabindex]");
    el?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 100,
      background: "rgba(9,30,66,.45)", display: "flex", alignItems: "center",
      justifyContent: "center" }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", borderRadius: 10, padding: "20px 22px",
          width: `min(${width}px, 92vw)`, boxShadow: "0 12px 40px rgba(9,30,66,.35)" }}>
        <h3 style={{ margin: "0 0 12px", fontSize: 16 }}>{title}</h3>
        {children}
      </div>
    </div>
  );
}

/* ---------- ConfirmDialog ---------- */

export function ConfirmDialog({ title, body, confirmLabel = "Confirm", danger = false,
  onConfirm, onClose }: {
  title: string;
  body: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <p style={{ margin: "0 0 16px", fontSize: 13.5, color: "var(--muted)" }}>{body}</p>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="ghost" onClick={onClose}>Cancel</button>
        <button className={danger ? "danger" : ""} disabled={busy}
          onClick={async () => { setBusy(true); await onConfirm(); onClose(); }}>
          {busy ? "…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/* ---------- SelectDialog (pick one option — reasons, users, …) ---------- */

export function SelectDialog({ title, body, options, confirmLabel = "Confirm",
  danger = false, onConfirm, onClose }: {
  title: string;
  body?: string;
  options: { id: number; label: string }[];
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: (id: number) => void | Promise<void>;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState<number | null>(options[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      {body && <p style={{ margin: "0 0 10px", fontSize: 13.5,
        color: "var(--muted)" }}>{body}</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: 6,
        maxHeight: 260, overflowY: "auto", marginBottom: 16 }}>
        {options.map((o) => (
          <label key={o.id} style={{ display: "flex", gap: 9, alignItems: "center",
            padding: "8px 10px", borderRadius: 7, cursor: "pointer",
            border: `1.5px solid ${picked === o.id ? "var(--accent)" : "var(--line)"}`,
            background: picked === o.id ? "#deebff44" : "#fff", fontSize: 13.5 }}>
            <input type="radio" name="pick" checked={picked === o.id}
              onChange={() => setPicked(o.id)} />
            {o.label}
          </label>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button className="ghost" onClick={onClose}>Cancel</button>
        <button className={danger ? "danger" : ""} disabled={busy || picked === null}
          onClick={async () => {
            if (picked === null) return;
            setBusy(true);
            await onConfirm(picked);
            onClose();
          }}>
          {busy ? "…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/* ---------- Loading + Empty ---------- */

export function Skeleton({ rows = 3, height = 54 }: { rows?: number; height?: number }) {
  return (
    <div aria-busy="true" style={{ padding: "14px 20px", display: "flex",
      flexDirection: "column", gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ height, borderRadius: 8,
          background: "linear-gradient(90deg,#ebecf0 25%,#f4f5f7 50%,#ebecf0 75%)",
          backgroundSize: "400% 100%", animation: "shimmer 1.3s infinite" }} />
      ))}
    </div>
  );
}

export function EmptyState({ icon, title, body, action }: {
  icon: string;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div style={{ textAlign: "center", padding: "56px 20px", color: "var(--muted)" }}>
      <div style={{ fontSize: 42, marginBottom: 10 }}>{icon}</div>
      <div style={{ fontSize: 16, fontWeight: 650, color: "var(--ink)",
        marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 13.5, maxWidth: 380, margin: "0 auto 16px" }}>{body}</div>
      {action}
    </div>
  );
}

/** Wraps async loads into loading/error/empty/content states. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, setState] = useState<{ loading: boolean; error: string; data: T | null }>(
    { loading: true, error: "", data: null });
  const reload = useCallback(() => {
    setState((s) => ({ ...s, loading: s.data === null, error: "" }));
    fn().then((data) => setState({ loading: false, error: "", data }))
      .catch(() => setState((s) => ({ ...s, loading: false,
        error: "Couldn't load — check your connection." })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { reload(); }, [reload]);
  return { ...state, reload };
}
