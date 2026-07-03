import { useCallback, useEffect, useState } from "react";
import { api } from "./api";

interface Condition { field: string; op: string; value: string }
interface Action { type: string; [k: string]: unknown }
interface Rule {
  id: number;
  name: string;
  trigger: string;
  pipeline_name: string | null;
  conditions: { all?: Condition[]; any?: Condition[] };
  actions: Action[];
  is_active: boolean;
}
interface Run {
  id: number;
  event_type: string;
  status: string;
  detail: { results?: string[]; errors?: string[] };
  created_at: string;
}

const TRIGGERS = ["deal.created", "deal.stage_changed", "deal.won", "deal.lost",
  "lead.created", "lead.converted", "activity.completed"];
const OPS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains"];
const ACTION_TYPES = ["create_activity", "notify", "move_stage", "change_owner",
  "update_field"];

function describeAction(a: Action): string {
  switch (a.type) {
    case "create_activity": return `➕ activity “${a.subject ?? "task"}” (+${a.due_in_days ?? 1}d)`;
    case "notify": return `🔔 notify: ${a.title ?? ""}`;
    case "move_stage": return `→ stage ${a.stage_name}`;
    case "change_owner": return `👤 owner → ${a.username ?? "round robin"}`;
    case "update_field": return `✎ ${a.field} = ${a.value}`;
    default: return a.type;
  }
}

/** AU-1/AU-4: rules list + toggle + simple builder + run log (admin config). */
export default function Automations({ isAdmin }: { isAdmin: boolean }) {
  const [rules, setRules] = useState<Rule[]>([]);
  const [runsFor, setRunsFor] = useState<{ rule: Rule; runs: Run[] } | null>(null);
  const [creating, setCreating] = useState(false);
  const [err, setErr] = useState("");

  const load = useCallback(async () => setRules(await api<Rule[]>("/automations/")), []);
  useEffect(() => { void load(); }, [load]);

  const toggle = async (r: Rule) => {
    await api(`/automations/${r.id}/`, { method: "PATCH",
      body: { is_active: !r.is_active } });
    void load();
  };

  const showRuns = async (rule: Rule) => {
    setRunsFor({ rule, runs: await api<Run[]>(`/automations/${rule.id}/runs/`) });
  };

  const create = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const conditions: { all: Condition[] } = { all: [] };
    if (f.get("cf") && f.get("cv")) {
      conditions.all.push({ field: f.get("cf") as string,
        op: f.get("co") as string, value: f.get("cv") as string });
    }
    const type = f.get("atype") as string;
    const action: Action = { type };
    if (type === "create_activity") {
      action.subject = f.get("aparam") || "Automated task";
      action.due_in_days = 1;
    } else if (type === "notify") action.title = f.get("aparam") || "Automation";
    else if (type === "move_stage") action.stage_name = f.get("aparam");
    else if (type === "change_owner") action.username = f.get("aparam") || "round_robin";
    else if (type === "update_field") {
      const [field, value] = String(f.get("aparam") ?? "").split("=");
      action.field = field; action.value = value;
    }
    try {
      await api("/automations/", { method: "POST", body: {
        name: f.get("name"), trigger: f.get("trigger"), conditions, actions: [action],
      } });
      setCreating(false);
      setErr("");
      void load();
    } catch { setErr("Invalid rule — check action parameters"); }
  };

  return (
    <div style={{ padding: 20, maxWidth: 860 }}>
      <h2 style={{ marginTop: 0 }}>
        Automations{" "}
        {isAdmin && (
          <button className="ghost" onClick={() => setCreating(!creating)}>
            {creating ? "Cancel" : "+ New rule"}
          </button>
        )}
      </h2>
      {creating && (
        <form onSubmit={create} style={{ display: "flex", flexWrap: "wrap", gap: 8,
          background: "#fff", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          <input name="name" placeholder="Rule name *" required style={{ flex: "1 1 100%" }} />
          <label>When <select name="trigger">{TRIGGERS.map((t) =>
            <option key={t}>{t}</option>)}</select></label>
          <label>if <input name="cf" placeholder="field (e.g. value or custom.venue)" />
            <select name="co">{OPS.map((o) => <option key={o}>{o}</option>)}</select>
            <input name="cv" placeholder="value" style={{ width: 90 }} /></label>
          <label>then <select name="atype">{ACTION_TYPES.map((a) =>
            <option key={a}>{a}</option>)}</select>
            <input name="aparam" placeholder="subject / title / stage / user / field=value" /></label>
          <button>Create</button>
          <span className="err">{err}</span>
        </form>
      )}
      <table className="leads" style={{ margin: 0 }}>
        <thead><tr><th>Rule</th><th>Trigger</th><th>Conditions</th><th>Actions</th>
          <th>Active</th><th></th></tr></thead>
        <tbody>
          {rules.map((r) => (
            <tr key={r.id}>
              <td>{r.name}{r.pipeline_name ? ` (${r.pipeline_name})` : ""}</td>
              <td><span className="pill new">{r.trigger}</span></td>
              <td style={{ fontSize: 12 }}>
                {(r.conditions.all ?? []).concat(r.conditions.any ?? [])
                  .map((c, i) => <div key={i}>{c.field} {c.op} {String(c.value)}</div>)}
                {!(r.conditions.all?.length || r.conditions.any?.length) && "always"}
              </td>
              <td style={{ fontSize: 12 }}>
                {r.actions.map((a, i) => <div key={i}>{describeAction(a)}</div>)}
              </td>
              <td>
                <input type="checkbox" checked={r.is_active} disabled={!isAdmin}
                  onChange={() => void toggle(r)} />
              </td>
              <td><button className="ghost" onClick={() => void showRuns(r)}>Runs</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {runsFor && (
        <div style={{ marginTop: 16, background: "#fff", padding: 12, borderRadius: 8 }}>
          <h3 style={{ margin: "0 0 8px", fontSize: 14 }}>
            Recent runs — {runsFor.rule.name}{" "}
            <button className="ghost" onClick={() => setRunsFor(null)}>Close</button>
          </h3>
          {runsFor.runs.length === 0 && <p style={{ color: "var(--muted)" }}>No runs yet.</p>}
          {runsFor.runs.map((run) => (
            <div key={run.id} style={{ fontSize: 12, padding: "4px 0",
              borderBottom: "1px solid var(--line)" }}>
              <span className={`pill ${run.status === "success" ? "qualified"
                : run.status === "failed" ? "disqualified" : ""}`}>{run.status}</span>{" "}
              {run.event_type} · {new Date(run.created_at).toLocaleString("en-IN")}
              {run.detail.results?.map((x, i) => <div key={i}>✓ {x}</div>)}
              {run.detail.errors?.map((x, i) => <div key={i} className="err">✗ {x}</div>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
