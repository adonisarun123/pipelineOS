import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ConfirmDialog, SelectDialog, toast } from "./ui";

interface UserRow {
  id: number;
  username: string;
  email: string;
  role: string;
  team_name: string | null;
  is_active: boolean;
}

/** U-3: admin panel — deactivate (kills tokens) + one-click record transfer. */
export default function Team({ selfId }: { selfId: number }) {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [msg, setMsg] = useState("");
  const [deactivating, setDeactivating] = useState<UserRow | null>(null);
  const [transferring, setTransferring] = useState<UserRow | null>(null);

  const load = useCallback(async () => setUsers(await api<UserRow[]>("/users/")), []);
  useEffect(() => { void load(); }, [load]);

  const deactivate = (u: UserRow) => setDeactivating(u);
  const transfer = (u: UserRow) => setTransferring(u);

  return (
    <div style={{ padding: "0 20px" }}>
      <h2>Team</h2>
      <p style={{ color: "var(--ok)", minHeight: "1em" }}>{msg}</p>
      <table className="leads" style={{ margin: 0 }}>
        <thead><tr><th>User</th><th>Email</th><th>Role</th><th>Team</th>
          <th>Status</th><th>Actions</th></tr></thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td><td>{u.email}</td><td>{u.role}</td>
              <td>{u.team_name ?? "—"}</td>
              <td><span className={`pill ${u.is_active ? "qualified" : "disqualified"}`}>
                {u.is_active ? "active" : "deactivated"}</span></td>
              <td>
                {u.id !== selfId && u.is_active && (
                  <>
                    <button className="ghost" onClick={() => void transfer(u)}>Transfer records</button>{" "}
                    <button className="danger" onClick={() => void deactivate(u)}>Deactivate</button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {deactivating && (
        <ConfirmDialog title={`Deactivate ${deactivating.username}?`} danger
          body="Their sessions and API tokens are revoked the same second. Their records stay — transfer them first if someone else should own them."
          confirmLabel="Deactivate now"
          onConfirm={async () => {
            await api(`/users/${deactivating.id}/deactivate/`,
              { method: "POST", body: {} });
            toast.ok(`${deactivating.username} deactivated — tokens revoked.`);
            void load();
          }}
          onClose={() => setDeactivating(null)} />
      )}
      {transferring && (
        <SelectDialog title={`Transfer ${transferring.username}'s records`}
          body="Every lead, deal, contact and activity they own moves in one step. This is audit-logged."
          confirmLabel="Transfer everything"
          options={users.filter((x) => x.id !== transferring.id && x.is_active)
            .map((x) => ({ id: x.id, label: `${x.username} (${x.role})` }))}
          onConfirm={async (targetId) => {
            const r = await api<{ transferred: Record<string, number>;
              to_user: string }>(
              `/users/${transferring.id}/transfer/`,
              { method: "POST", body: { to_user_id: targetId } });
            const detail = Object.entries(r.transferred)
              .filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}s`).join(", ");
            setMsg(`Moved to ${r.to_user}: ${detail || "nothing owned"}`);
            toast.ok(`Records transferred to ${r.to_user}.`);
            void load();
          }}
          onClose={() => setTransferring(null)} />
      )}
    </div>
  );
}
