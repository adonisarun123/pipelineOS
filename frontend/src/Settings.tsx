import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

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
    </div>
  );
}
