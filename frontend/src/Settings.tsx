import { useCallback, useEffect, useState } from "react";
import { api, getAuth } from "./api";
import { ConfirmDialog, toast } from "./ui";

interface ApiKeyRow {
  id: number;
  name: string;
  prefix_hint: string;
  scope: string;
  is_active: boolean;
  acting_user: string;
  last_used_at: string | null;
}

function ApiKeys() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [fresh, setFresh] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<ApiKeyRow | null>(null);

  const load = useCallback(async () => setKeys(await api<ApiKeyRow[]>("/api-keys/")), []);
  useEffect(() => { void load(); }, [load]);

  const create = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const r = await api<{ key: string }>("/api-keys/", { method: "POST",
      body: { name: f.get("name"), scope: f.get("scope") } });
    setFresh(r.key);
    e.currentTarget.reset();
    void load();
  };

  const revoke = (k: ApiKeyRow) => setRevoking(k);

  return (
    <>
      <h3 style={{ fontSize: 15, marginTop: 24 }}>API keys</h3>
      <p style={{ color: "var(--muted)", fontSize: 13 }}>
        For integrations (app.trebound.com, CHAP, Zapier). Docs at{" "}
        <a href="/api/v1/docs/" target="_blank" rel="noreferrer">/api/v1/docs/</a>.
        Rate limit: 600 requests/hour per workspace.
      </p>
      <form onSubmit={create} style={{ display: "flex", gap: 8 }}>
        <input name="name" placeholder="Key name (e.g. proposal-builder)" required
          style={{ flex: 1 }} />
        <select name="scope"><option value="read">read</option>
          <option value="write">write</option></select>
        <button>Create key</button>
      </form>
      {fresh && (
        <div className="dupewarn" style={{ marginTop: 8, wordBreak: "break-all" }}>
          Copy now — shown only once: <code>{fresh}</code>{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); setFresh(null); }}>dismiss</a>
        </div>
      )}
      <table className="leads" style={{ margin: "12px 0 0", width: "100%" }}>
        <thead><tr><th>Name</th><th>Key</th><th>Scope</th><th>Last used</th>
          <th>Status</th><th></th></tr></thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k.id}>
              <td>{k.name}</td><td><code>{k.prefix_hint}</code></td><td>{k.scope}</td>
              <td>{k.last_used_at
                ? new Date(k.last_used_at).toLocaleString("en-IN") : "never"}</td>
              <td><span className={`pill ${k.is_active ? "qualified" : "disqualified"}`}>
                {k.is_active ? "active" : "revoked"}</span></td>
              <td>{k.is_active && (
                <button className="danger" onClick={() => void revoke(k)}>Revoke</button>
              )}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {revoking && (
        <ConfirmDialog title={`Revoke "${revoking.name}"?`} danger
          body="Any integration using this key stops immediately. This cannot be undone — you'd create a new key instead."
          confirmLabel="Revoke key"
          onConfirm={async () => {
            await api(`/api-keys/${revoking.id}/revoke/`, { method: "POST", body: {} });
            toast.ok(`Key "${revoking.name}" revoked.`);
            void load();
          }}
          onClose={() => setRevoking(null)} />
      )}
    </>
  );
}

interface EmailAccount {
  status: string;
  address?: string;
  provider?: string;
  sync_scope?: string;
  last_sync_at?: string | null;
  next_step?: string;
}

/** E-1 groundwork: connect mailbox. Live Gmail sync needs tenant OAuth creds. */
export default function Settings() {
  const [acct, setAcct] = useState<EmailAccount | null>(null);
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    setAcct(await api<EmailAccount>("/email-account/"));
  }, []);

  useEffect(() => { void load(); }, [load]);

  const connect = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const r = await api<EmailAccount>("/email-account/", {
      method: "POST", body: { address: f.get("address") },
    });
    setMsg(r.next_step ?? "");
    void load();
  };

  const disconnect = async () => {
    await api("/email-account/", { method: "DELETE" });
    setMsg("");
    void load();
  };

  if (!acct) return null;
  const connected = acct.status === "connected";
  const pending = acct.status === "pending";

  return (
    <div style={{ padding: 20, maxWidth: 640 }}>
      <h2 style={{ marginTop: 0 }}>Settings</h2>
      <h3 style={{ fontSize: 15 }}>Mailbox (Gmail)</h3>
      {acct.status === "not_connected" || acct.status === "disabled" ? (
        <form onSubmit={connect} style={{ display: "flex", gap: 8 }}>
          <input name="address" type="email" placeholder="you@company.com" required
            style={{ flex: 1 }} />
          <button>Connect mailbox</button>
        </form>
      ) : (
        <p>
          <span className={`pill ${connected ? "qualified" : "contacted"}`}>
            {acct.status}
          </span>{" "}
          {acct.address}
          {pending && " — awaiting Google authorization (admin: see docs/GMAIL-SETUP.md)"}
          {" "}<button className="ghost" onClick={() => void disconnect()}>Disconnect</button>
        </p>
      )}
      {msg && <div className="dupewarn" style={{ marginTop: 8 }}>{msg}</div>}
      <p style={{ color: "var(--muted)", fontSize: 13 }}>
        Once connected (Phase 2 sync), mail linked to your CRM contacts appears on deal
        and contact timelines. Privacy default: only mail matching CRM contacts is synced.
      </p>
      <h3 style={{ fontSize: 15, marginTop: 24 }}>Daily digest</h3>
      <p style={{ color: "var(--muted)", fontSize: 13 }}>
        A morning email with overdue activities, today's schedule, and new leads.
        Sent automatically at 08:00 if there's anything to report.
      </p>
      {getAuth()?.role === "admin" && <Billing />}
      {getAuth()?.role === "admin" && <ApiKeys />}
    </div>
  );
}

interface Usage {
  plan: string; seats_used: number; seats_limit: number;
  trial_ends_at: string | null; writable: boolean; deals: number; leads: number;
  storage_bytes: number; price_inr_month: number; razorpay_configured: boolean;
}

function Billing() {
  const [u, setU] = useState<Usage | null>(null);
  useEffect(() => { void api<Usage>("/billing/usage/").then(setU); }, []);
  if (!u) return null;
  return (
    <>
      <h3 style={{ fontSize: 15, marginTop: 24 }}>Plan & usage</h3>
      <p>
        <span className="pill new">{u.plan}</span>{" "}
        {u.trial_ends_at && `trial ends ${new Date(u.trial_ends_at)
          .toLocaleDateString("en-IN")}`}
        {!u.writable && <strong style={{ color: "var(--rot)" }}> — read-only (expired)</strong>}
      </p>
      <p style={{ fontSize: 13, color: "var(--muted)" }}>
        Seats {u.seats_used}/{u.seats_limit} · {u.deals} deals · {u.leads} leads ·{" "}
        {(u.storage_bytes / 1048576).toFixed(1)} MB files
      </p>
      {!u.razorpay_configured && (
        <p className="dupewarn" style={{ fontSize: 12 }}>
          Payments not configured — set RAZORPAY_KEY_ID / RAZORPAY_WEBHOOK_SECRET on the
          server to enable upgrades.
        </p>
      )}
    </>
  );
}
