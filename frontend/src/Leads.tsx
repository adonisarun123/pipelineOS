import { useCallback, useEffect, useRef, useState } from "react";
import { api, inr } from "./api";
import type { Lead, LeadSource, LeadStatus, LostReason, Paginated, Pipeline } from "./types";

const OPEN_STATUSES: LeadStatus[] = ["new", "attempted", "contacted"];

interface Dupes {
  leads: Lead[];
  people: { id: number; first_name: string; last_name: string }[];
}

export default function Leads() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState<string>("open");
  const [sources, setSources] = useState<LeadSource[]>([]);
  const [reasons, setReasons] = useState<LostReason[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [dupes, setDupes] = useState<Dupes | null>(null);
  const [converting, setConverting] = useState<Lead | null>(null);
  const [callLog, setCallLog] = useState<Lead | null>(null);  // M-3 assist
  const pendingCall = useRef<Lead | null>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [views, setViews] = useState<{ id: number; name: string; params: { status?: string } }[]>([]);

  const loadViews = () =>
    void api<{ id: number; name: string; params: { status?: string } }[]>(
      "/saved-views/?entity=lead").then(setViews);

  const saveView = async () => {
    const name = prompt("Save current filter as (name):");
    if (!name) return;
    const shared = confirm("Share this view with your team?");
    await api("/saved-views/", { method: "POST",
      body: { name, entity: "lead", params: { status: filter }, is_shared: shared } });
    loadViews();
  };

  const load = useCallback(async () => {
    if (filter === "open") {
      const batches = await Promise.all(
        OPEN_STATUSES.map((s) => api<Paginated<Lead>>(`/leads/?status=${s}`)),
      );
      setLeads(batches.flatMap((b) => b.results).sort((a, b) => b.id - a.id));
    } else {
      setLeads((await api<Paginated<Lead>>(`/leads/?status=${filter}`)).results);
    }
  }, [filter]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    // M-3: returning from a tel:/wa.me jump → offer to log the call
    const onVisible = () => {
      if (document.visibilityState === "visible" && pendingCall.current) {
        setCallLog(pendingCall.current);
        pendingCall.current = null;
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  useEffect(() => {
    void api<LeadSource[]>("/lead-sources/").then(setSources);
    void api<LostReason[]>("/lost-reasons/").then(setReasons);
    void api<Paginated<Pipeline>>("/pipelines/").then((d) => setPipelines(d.results));
    loadViews();
  }, []);

  const checkDupes = async (phone: string, email: string) => {
    if (!phone && !email) return setDupes(null);
    const d = await api<Dupes>(
      `/leads/duplicates/?phone=${encodeURIComponent(phone)}&email=${encodeURIComponent(email)}`,
    );
    setDupes(d.leads.length || d.people.length ? d : null);
  };

  const createLead = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await api("/leads/", {
      method: "POST",
      body: {
        name: f.get("name"), organization_name: f.get("org") ?? "",
        phone_raw: f.get("phone") ?? "", email: f.get("email") ?? "",
        source: f.get("source") || null,
      },
    });
    e.currentTarget.reset();
    setDupes(null);
    void load();
  };

  const logCall = async (lead: Lead, outcome: string) => {
    const types = await api<{ id: number; name: string }[]>("/activity-types/");
    const call = types.find((t) => t.name === "Call") ?? types[0];
    const created = await api<{ id: number }>("/activities/", { method: "POST",
      body: { type: call.id, subject: `Call: ${lead.name}`,
        due_at: new Date().toISOString(), lead: lead.id } });
    await api(`/activities/${created.id}/complete/`, { method: "POST",
      body: { outcome } });
    if (lead.status === "new") {
      await api(`/leads/${lead.id}/set_status/`, { method: "POST",
        body: { status: "attempted" } });
    }
    setCallLog(null);
    void load();
  };

  const setStatus = async (lead: Lead, status: LeadStatus) => {
    await api(`/leads/${lead.id}/set_status/`, { method: "POST", body: { status } });
    void load();
  };

  const disqualify = async (lead: Lead) => {
    const labels = reasons.map((r, i) => `${i + 1}. ${r.label}`).join("\n");
    const pick = prompt(`Disqualify reason (required):\n${labels}\nEnter number:`);
    const reason = reasons[Number(pick) - 1];
    if (!reason) return;
    await api(`/leads/${lead.id}/disqualify/`, { method: "POST", body: { reason_id: reason.id } });
    void load();
  };

  const convert = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!converting) return;
    const f = new FormData(e.currentTarget);
    await api(`/leads/${converting.id}/convert/`, {
      method: "POST",
      body: {
        pipeline_id: Number(f.get("pipeline")),
        deal_title: f.get("title") ?? "",
        value: (f.get("value") as string) || "0",
      },
    });
    dialogRef.current?.close();
    setConverting(null);
    void load();
  };

  return (
    <div>
      <form className="quickadd" onSubmit={createLead}>
        <input name="name" placeholder="Lead name *" required style={{ flex: 1 }} />
        <input name="org" placeholder="Organization" />
        <input name="phone" placeholder="Phone"
          onBlur={(e) => void checkDupes(e.target.value, "")} />
        <input name="email" placeholder="Email" type="email"
          onBlur={(e) => void checkDupes("", e.target.value)} />
        <select name="source" defaultValue="">
          <option value="">Source…</option>
          {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button>Add lead</button>
      </form>
      {dupes && (
        <div className="dupewarn" style={{ margin: "8px 20px 0" }}>
          ⚠ Possible duplicates: {dupes.leads.map((l) => `lead “${l.name}”`).join(", ")}
          {dupes.leads.length > 0 && dupes.people.length > 0 ? "; " : ""}
          {dupes.people.map((p) => `contact “${p.first_name} ${p.last_name}”`).join(", ")}
        </div>
      )}
      <div className="toolbar">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="open">Open (new/attempted/contacted)</option>
          <option value="new">New</option>
          <option value="attempted">Attempted</option>
          <option value="contacted">Contacted</option>
          <option value="qualified">Qualified (converted)</option>
          <option value="disqualified">Disqualified</option>
        </select>
        <span style={{ color: "var(--muted)" }}>{leads.length} leads</span>
        {views.length > 0 && (
          <select defaultValue="" onChange={(e) => {
            const v = views.find((x) => x.id === Number(e.target.value));
            if (v) setFilter(v.params.status ?? "open");
          }}>
            <option value="" disabled>Saved views…</option>
            {views.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        )}
        <button className="ghost" onClick={() => void saveView()}>Save view</button>
      </div>
      <table className="leads">
        <thead>
          <tr><th>Name</th><th>Organization</th><th>Phone</th><th>Source</th>
            <th>Owner</th><th>Status</th><th>Actions</th></tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr key={l.id}>
              <td>{l.name}</td>
              <td>{l.organization_name || "—"}</td>
              <td>
                {l.phone_normalized ? (
                  <>
                    <a className="calllink" href={`tel:${l.phone_normalized}`}
                      onClick={() => { pendingCall.current = l; }}>
                      📞 {l.phone_normalized}
                    </a>{" "}
                    <a className="calllink" title="WhatsApp" target="_blank" rel="noreferrer"
                      href={`https://wa.me/${l.phone_normalized.replace("+", "")}`}>💬</a>
                  </>
                ) : (l.phone_raw || "—")}
              </td>
              <td>{l.source_name ?? "—"}</td>
              <td>{l.owner_name ?? "—"}</td>
              <td><span className={`pill ${l.status}`}>{l.status}</span></td>
              <td>
                {OPEN_STATUSES.includes(l.status) && (
                  <>
                    {l.status !== "contacted" && (
                      <button className="ghost" onClick={() => void setStatus(l, "contacted")}>
                        Contacted
                      </button>
                    )}{" "}
                    <button onClick={() => {
                      setConverting(l);
                      requestAnimationFrame(() => dialogRef.current?.showModal());
                    }}>
                      Convert
                    </button>{" "}
                    <button className="danger" onClick={() => void disqualify(l)}>DQ</button>
                  </>
                )}
                {l.status === "qualified" && l.converted_deal && (
                  <span className="pill qualified">deal #{l.converted_deal}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {callLog && (
        <div className="dupewarn" style={{ margin: "8px 20px", display: "flex",
          gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          📞 Log this call with <strong>{callLog.name}</strong>?
          {["connected", "no_answer", "busy", "wrong_number"].map((o) => (
            <button key={o} className="ghost" onClick={() => void logCall(callLog, o)}>
              {o.replace("_", " ")}
            </button>
          ))}
          <a href="#" onClick={(e) => { e.preventDefault(); setCallLog(null); }}>skip</a>
        </div>
      )}
      <dialog ref={dialogRef} onClose={() => setConverting(null)}>
        <form onSubmit={convert}>
          <h3 style={{ margin: 0 }}>Convert “{converting?.name}” to deal</h3>
          <select name="pipeline" required>
            {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input name="title" placeholder={`Deal title (default: ${converting?.organization_name || converting?.name} — new deal)`} />
          <input name="value" type="number" placeholder={`Value (INR, e.g. ${inr(100000)})`} />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="ghost" onClick={() => dialogRef.current?.close()}>
              Cancel
            </button>
            <button>Convert</button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
