import { useCallback, useEffect, useState } from "react";
import { api, inr } from "./api";
import type { Paginated, Pipeline } from "./types";

interface FunnelRow {
  stage: string; stage_id: number; entered: number;
  conversion_pct: number | null; median_days: number | null;
}
interface ActivityRow {
  rep: string; total: number; by_type: Record<string, number>;
  calls: number; connect_rate_pct: number | null;
}
interface WonLost {
  by_month: { month: string; won: number; lost: number; won_value: string }[];
  by_owner: { owner: string; won: number; lost: number; won_value: string }[];
  lost_reasons: { reason: string; count: number }[];
}
interface SourceRow {
  source: string; leads: number; qualified: number; won: number;
  won_value: string; lead_to_win_pct: number;
}

function Bar({ pct, color = "var(--accent)" }: { pct: number; color?: string }) {
  return (
    <span style={{ display: "inline-block", width: 120, height: 10,
      background: "#ebecf0", borderRadius: 5, verticalAlign: "middle" }}>
      <span style={{ display: "block", width: `${Math.min(100, pct)}%`, height: "100%",
        background: color, borderRadius: 5 }} />
    </span>
  );
}

/** R-2..R-5 (R-6 widget grids + scheduled digests deferred; R-7 via list links). */
export default function Reports() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [days, setDays] = useState(90);
  const [funnel, setFunnel] = useState<FunnelRow[]>([]);
  const [activity, setActivity] = useState<ActivityRow[]>([]);
  const [wonLost, setWonLost] = useState<WonLost | null>(null);
  const [sources, setSources] = useState<SourceRow[]>([]);

  useEffect(() => {
    void api<Paginated<Pipeline>>("/pipelines/").then((d) => {
      setPipelines(d.results);
      if (d.results.length) setPid(d.results[0].id);
    });
  }, []);

  const load = useCallback(async () => {
    if (pid === null) return;
    const [f, a, w, s] = await Promise.all([
      api<FunnelRow[]>(`/reports/funnel/?pipeline=${pid}&days=${days}`),
      api<ActivityRow[]>(`/reports/activity/?days=${days}`),
      api<WonLost>(`/reports/won-lost/?days=${days}`),
      api<SourceRow[]>(`/reports/sources/?days=${days}`),
    ]);
    setFunnel(f); setActivity(a); setWonLost(w); setSources(s);
  }, [pid, days]);

  useEffect(() => { void load(); }, [load]);

  const maxEntered = Math.max(1, ...funnel.map((r) => r.entered));
  const maxReason = Math.max(1, ...(wonLost?.lost_reasons.map((r) => r.count) ?? [1]));

  return (
    <div style={{ padding: 20, maxWidth: 900 }}>
      <div className="toolbar" style={{ padding: 0, marginBottom: 12 }}>
        <select value={pid ?? ""} onChange={(e) => setPid(Number(e.target.value))}>
          {pipelines.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last 12 months</option>
        </select>
      </div>

      <h3>Conversion funnel</h3>
      <table className="leads" style={{ margin: 0 }}>
        <thead><tr><th>Stage</th><th>Entered</th><th></th><th>→ next</th>
          <th>Median days</th></tr></thead>
        <tbody>
          {funnel.map((r) => (
            <tr key={r.stage_id}>
              <td>{r.stage}</td>
              <td>{r.entered}</td>
              <td><Bar pct={(100 * r.entered) / maxEntered} /></td>
              <td>{r.conversion_pct !== null ? `${r.conversion_pct}%` : "—"}</td>
              <td>{r.median_days ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 style={{ marginTop: 24 }}>Activity by rep</h3>
      <table className="leads" style={{ margin: 0 }}>
        <thead><tr><th>Rep</th><th>Done</th><th>Calls</th><th>Connect rate</th>
          <th>Breakdown</th></tr></thead>
        <tbody>
          {activity.map((r) => (
            <tr key={r.rep}>
              <td>{r.rep}</td><td>{r.total}</td><td>{r.calls}</td>
              <td>{r.connect_rate_pct !== null
                ? <><Bar pct={r.connect_rate_pct} color="var(--ok)" /> {r.connect_rate_pct}%</>
                : "—"}</td>
              <td style={{ fontSize: 12, color: "var(--muted)" }}>
                {Object.entries(r.by_type).map(([t, n]) => `${t}: ${n}`).join(" · ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {wonLost && (
        <>
          <h3 style={{ marginTop: 24 }}>Won / Lost</h3>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
            <table className="leads" style={{ margin: 0, flex: 1 }}>
              <thead><tr><th>Month</th><th>Won</th><th>Lost</th><th>Revenue</th></tr></thead>
              <tbody>
                {wonLost.by_month.map((m) => (
                  <tr key={m.month}><td>{m.month}</td><td>{m.won}</td><td>{m.lost}</td>
                    <td>{inr(m.won_value)}</td></tr>
                ))}
              </tbody>
            </table>
            <table className="leads" style={{ margin: 0, flex: 1 }}>
              <thead><tr><th>Lost reason</th><th></th><th>#</th></tr></thead>
              <tbody>
                {wonLost.lost_reasons.map((r) => (
                  <tr key={r.reason}><td>{r.reason}</td>
                    <td><Bar pct={(100 * r.count) / maxReason} color="var(--rot)" /></td>
                    <td>{r.count}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h3 style={{ marginTop: 24 }}>Lead source ROI</h3>
      <table className="leads" style={{ margin: 0 }}>
        <thead><tr><th>Source</th><th>Leads</th><th>Qualified</th><th>Won</th>
          <th>Revenue</th><th>Lead→win</th></tr></thead>
        <tbody>
          {sources.map((s) => (
            <tr key={s.source}>
              <td>{s.source}</td><td>{s.leads}</td><td>{s.qualified}</td><td>{s.won}</td>
              <td>{inr(s.won_value)}</td>
              <td><Bar pct={s.lead_to_win_pct} color="var(--ok)" /> {s.lead_to_win_pct}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
