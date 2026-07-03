import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

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

  const load = useCallback(async () => setUsers(await api<UserRow[]>("/users/")), []);
  useEffect(() => { void load(); }, [load]);

  const deactivate = async (u: UserRow) => {
    if (!confirm(`Deactivate ${u.username}? Their sessions and API tokens die immediately.`)) return;
    await api(`/users/${u.id}/deactivate/`, { method: "POST", body: {} });
    setMsg(`${u.username} deactivated.`);
    void load();
  };

  const transfer = async (u: UserRow) => {
    const others = users.filter((x) => x.id !== u.id && x.is_active);
    const pick = prompt(
      `Transfer ALL of ${u.username}'s records to:\n`
      + others.map((x, i) => `${i + 1}. ${x.username} (${x.role})`).join("\n")
      + "\nEnter number:",
    );
    const target = others[Number(pick) - 1];
    if (!target) return;
    const r = await api<{ transferred: Record<string, number> }>(
      `/users/${u.id}/transfer/`, { method: "POST", body: { to_user_id: target.id } },
    );
    setMsg(`Moved to ${target.username}: `
      + Object.entries(r.transferred).map(([k, v]) => `${v} ${k}s`).join(", "));
  };

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
    </div>
  );
}
