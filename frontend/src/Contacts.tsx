import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Paginated } from "./types";

interface PersonRow {
  id: number;
  first_name: string;
  last_name: string;
  job_title: string;
  organization_name: string | null;
  owner_name: string | null;
  phones: { normalized: string }[];
  emails: { email: string }[];
}

interface OrgRow { id: number; name: string; industry: string; website: string }

interface TimelineEvent { kind: string; at: string | null; by: string | null; summary: string }

function PersonPanel({ personId, onClose }: { personId: number; onClose: () => void }) {
  const [person, setPerson] = useState<PersonRow | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);

  useEffect(() => {
    void api<{ person: PersonRow; events: TimelineEvent[] }>(
      `/people/${personId}/timeline/`,
    ).then((r) => { setPerson(r.person); setEvents(r.events); });
  }, [personId]);

  const fmt = (iso: string | null) => iso
    ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : "";

  if (!person) return null;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(9,30,66,.4)", zIndex: 10 }}
      onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} style={{ position: "absolute", right: 0,
        top: 0, bottom: 0, width: "min(460px, 95vw)", background: "#fff", padding: 20,
        overflowY: "auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>{person.first_name} {person.last_name}</h2>
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
        <p style={{ color: "var(--muted)", fontSize: 13 }}>
          {person.job_title || "—"} · {person.organization_name ?? "no organization"}<br />
          {person.phones.length
            ? person.phones.map((p) => (
                <span key={p.normalized}>
                  <a href={`tel:${p.normalized}`}>📞 {p.normalized}</a>{" "}
                  <a href={`https://wa.me/${p.normalized.replace("+", "")}`}
                    target="_blank" rel="noreferrer">💬</a>{" "}
                </span>
              ))
            : "no phone"}
          {" · "}
          {person.emails.map((e) => (
            <a key={e.email} href={`mailto:${e.email}`}>{e.email}</a>
          )).reduce<React.ReactNode[]>((acc, el, i) =>
            i === 0 ? [el] : [...acc, ", ", el], []) as React.ReactNode}
          {person.emails.length === 0 && "no email"}
        </p>
        <h3 style={{ fontSize: 14 }}>Timeline</h3>
        {events.map((e, i) => (
          <div key={i} style={{ padding: "6px 0", borderBottom: "1px solid var(--line)",
            fontSize: 13 }}>
            <div>{e.summary}</div>
            <div style={{ color: "var(--muted)", fontSize: 11 }}>
              {fmt(e.at)}{e.by ? ` · ${e.by}` : ""}
            </div>
          </div>
        ))}
      </aside>
    </div>
  );
}

export default function Contacts() {
  const [mode, setMode] = useState<"people" | "orgs">("people");
  const [q, setQ] = useState("");
  const [people, setPeople] = useState<PersonRow[]>([]);
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [openPerson, setOpenPerson] = useState<number | null>(null);

  const load = useCallback(async () => {
    const qs = q ? `?q=${encodeURIComponent(q)}` : "";
    if (mode === "people") setPeople((await api<Paginated<PersonRow>>(`/people/${qs}`)).results);
    else setOrgs((await api<Paginated<OrgRow>>(`/organizations/${qs}`)).results);
  }, [mode, q]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(t);
  }, [load]);

  return (
    <div>
      <div className="toolbar">
        <select value={mode} onChange={(e) => setMode(e.target.value as "people" | "orgs")}>
          <option value="people">People</option>
          <option value="orgs">Organizations</option>
        </select>
        <input placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)}
          style={{ flex: 1, maxWidth: 300 }} />
      </div>
      {mode === "people" ? (
        <table className="leads">
          <thead><tr><th>Name</th><th>Title</th><th>Organization</th><th>Phone</th>
            <th>Email</th><th>Owner</th></tr></thead>
          <tbody>
            {people.map((p) => (
              <tr key={p.id} style={{ cursor: "pointer" }} onClick={() => setOpenPerson(p.id)}>
                <td>{p.first_name} {p.last_name}</td>
                <td>{p.job_title || "—"}</td>
                <td>{p.organization_name ?? "—"}</td>
                <td>{p.phones[0]?.normalized ?? "—"}</td>
                <td>{p.emails[0]?.email ?? "—"}</td>
                <td>{p.owner_name ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="leads">
          <thead><tr><th>Name</th><th>Industry</th><th>Website</th></tr></thead>
          <tbody>
            {orgs.map((o) => (
              <tr key={o.id}>
                <td>{o.name}</td><td>{o.industry || "—"}</td>
                <td>{o.website ? <a href={o.website} target="_blank" rel="noreferrer">{o.website}</a> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {openPerson !== null && (
        <PersonPanel personId={openPerson} onClose={() => setOpenPerson(null)} />
      )}
    </div>
  );
}
