import { useCallback, useEffect, useState } from "react";
import { api, inr } from "./api";
import DealDetail from "./DealDetail";
import ScheduleDialog from "./ScheduleDialog";
import { ConfirmDialog, EmptyState, SelectDialog, Skeleton, toast } from "./ui";
import type {
  Deal, Kanban as KanbanData, LostReason, Paginated, Pipeline, PipelineSummary,
} from "./types";

function ExportButton({ pid }: { pid: number | null }) {
  const auth = JSON.parse(localStorage.getItem("auth") ?? "null") as
    { token: string; role: string } | null;
  if (!auth || (auth.role !== "admin" && auth.role !== "manager")) return null;
  const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";
  const download = async () => {
    const r = await fetch(`${BASE}/api/v1/deals/export/${pid ? `?pipeline=${pid}` : ""}`, {
      headers: { Authorization: `Token ${auth.token}` },
    });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "deals.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return <button className="ghost" onClick={() => void download()}>Export CSV</button>;
}

export default function Kanban() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [board, setBoard] = useState<KanbanData | null>(null);
  const [reasons, setReasons] = useState<LostReason[]>([]);
  const [openDeal, setOpenDeal] = useState<number | null>(null);
  const [scheduleFor, setScheduleFor] = useState<{ id: number; title: string } | null>(null);
  const [mineOnly, setMineOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [winning, setWinning] = useState<Deal | null>(null);
  const [losing, setLosing] = useState<Deal | null>(null);
  const [summary, setSummary] = useState<PipelineSummary | null>(null);
  const [nudges, setNudges] = useState<string[]>([]);

  const load = useCallback(async (p: number, mine = mineOnly) => {
    try {
      setBoard(await api<KanbanData>(`/pipelines/${p}/kanban/${mine ? "?owner=me" : ""}`));
      setSummary(await api<PipelineSummary>(`/pipelines/${p}/summary/`));
    } catch {
      toast.err("Couldn't load the board — check your connection.");
    } finally {
      setLoading(false);
    }
  }, [mineOnly]);

  useEffect(() => {
    void api<Paginated<Pipeline>>("/pipelines/").then((d) => {
      setPipelines(d.results);
      if (d.results.length > 0) {
        setPid(d.results[0].id);
        void load(d.results[0].id);
      }
    });
    void api<LostReason[]>("/lost-reasons/").then(setReasons);
  }, [load]);

  const refresh = () => pid !== null && void load(pid);

  const onDrop = async (e: React.DragEvent<HTMLDivElement>, stageId: number) => {
    e.preventDefault();
    e.currentTarget.classList.remove("dragover");
    const dealId = Number(e.dataTransfer.getData("text/plain"));
    if (!board) return;
    // Optimistic: move the card locally NOW, roll back on failure.
    const prev = board;
    let moved: Deal | undefined;
    const stripped = board.columns.map((c) => {
      const hit = c.deals.find((d) => d.id === dealId);
      if (hit) moved = hit;
      return { ...c, deals: c.deals.filter((d) => d.id !== dealId) };
    });
    if (!moved) return;
    setBoard({ ...board, columns: stripped.map((c) =>
      c.stage.id === stageId
        ? { ...c, deals: [{ ...moved!, stage: stageId }, ...c.deals],
            count: c.count + 1 }
        : { ...c, count: c.deals.length }) });
    try {
      const r = await api<Deal & { nudges: string[] }>(
        `/deals/${dealId}/move/`, { method: "POST", body: { stage_id: stageId } });
      setNudges(r.nudges ?? []); // CF-2: prompt, don't block
      refresh(); // reconcile totals/flags
    } catch {
      setBoard(prev); // rollback
      toast.err("Move failed — the card is back where it was.");
    }
  };

  const onWon = (deal: Deal) => setWinning(deal);
  const onLost = (deal: Deal) => setLosing(deal);

  const quickAdd = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const title = f.get("title") as string;
    if (!title || pid === null) return;
    const created = await api<Deal>("/deals/", {
      method: "POST",
      body: { title, value: (f.get("value") as string) || "0", pipeline: pid },
    });
    e.currentTarget.reset();
    refresh();
    setScheduleFor({ id: created.id, title: created.title }); // D-5: prompt on creation
  };

  return (
    <div>
      <div className="toolbar">
        <select
          value={pid ?? ""}
          onChange={(e) => { const v = Number(e.target.value); setPid(v); void load(v); }}
        >
          {pipelines.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <label style={{ color: "var(--muted)", display: "flex", gap: 4, alignItems: "center" }}>
          <input type="checkbox" checked={mineOnly}
            onChange={(e) => { setMineOnly(e.target.checked); if (pid !== null) void load(pid, e.target.checked); }} />
          My deals only
        </label>
        <ExportButton pid={pid} />
        {summary && (
          <span style={{ marginLeft: "auto", color: "var(--muted)", fontSize: 13 }}>
            {summary.open_count} open · {inr(summary.open_value)} · forecast{" "}
            {inr(summary.weighted_forecast)} ·{" "}
            <span style={{ color: summary.rotting ? "var(--rot)" : "inherit" }}>
              🥀 {summary.rotting}
            </span>{" "}
            · ⚠ {summary.needs_next_activity} · W {summary.won_this_month.count}/L{" "}
            {summary.lost_this_month.count} this month
          </span>
        )}
      </div>
      {nudges.length > 0 && (
        <div className="dupewarn" style={{ margin: "8px 20px 0" }}>
          ⚠ Before this stage, fill in: <strong>{nudges.join(", ")}</strong>{" "}
          <a href="#" onClick={(e) => { e.preventDefault(); setNudges([]); }}>dismiss</a>
        </div>
      )}
      <form className="quickadd" onSubmit={quickAdd}>
        <input name="title" placeholder="New deal title…" />
        <input name="value" type="number" placeholder="Value (INR)" />
        <button>Add deal</button>
      </form>
      {loading && <Skeleton rows={3} height={90} />}
      {!loading && board && board.columns.every((c) => c.count === 0) && (
        <EmptyState icon="📊" title="Your pipeline is empty"
          body="Add your first deal above, or convert a lead from the Leads tab. Deals move left to right as they progress — and turn red when they need attention." />
      )}
      <div className="board">
        {!loading && board?.columns.map((c) => (
          <div
            key={c.stage.id}
            className="col"
            onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add("dragover"); }}
            onDragLeave={(e) => e.currentTarget.classList.remove("dragover")}
            onDrop={(e) => void onDrop(e, c.stage.id)}
          >
            <h3>{c.stage.name}</h3>
            <p className="meta">
              {c.count} deals · {inr(c.total_value)}
              {c.stage.rot_days ? ` · rot ${c.stage.rot_days}d` : ""}
            </p>
            {c.deals.map((d) => (
              <div
                key={d.id}
                className={`deal ${d.is_rotten ? "rotten" : ""}`}
                draggable
                onDragStart={(e) => e.dataTransfer.setData("text/plain", String(d.id))}
                onClick={() => setOpenDeal(d.id)}
                title={d.is_rotten ? "Rotting: no recent activity" : "Click for details"}
              >
                <div className="t">{d.title}</div>
                <div className="sub">
                  <span>{d.organization_name ?? "—"}</span>
                  <span>{inr(d.value)}</span>
                </div>
                <div className="sub">
                  <span>{d.owner_name}</span>
                  <span>
                    {d.needs_next_activity && <span className="badge">⚠ no next activity </span>}
                    <a href="#" style={{ color: "var(--ok)" }}
                      onClick={(e) => { e.preventDefault(); void onWon(d); }}>✓</a>{" "}
                    <a href="#" style={{ color: "var(--rot)" }}
                      onClick={(e) => { e.preventDefault(); void onLost(d); }}>✗</a>
                  </span>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>
      {openDeal !== null && (
        <DealDetail dealId={openDeal} onClose={() => setOpenDeal(null)} onChanged={refresh} />
      )}
      {scheduleFor && (
        <ScheduleDialog dealId={scheduleFor.id} dealTitle={scheduleFor.title} open
          onClose={() => setScheduleFor(null)} onScheduled={refresh} />
      )}
      {winning && (
        <ConfirmDialog title="Mark deal as won 🎉"
          body={`"${winning.title}" (${inr(winning.value)}) will move to Won and count toward this month's revenue.`}
          confirmLabel="Mark won"
          onConfirm={async () => {
            await api(`/deals/${winning.id}/won/`, { method: "POST" });
            toast.ok(`${winning.title} won — nice work.`);
            refresh();
          }}
          onClose={() => setWinning(null)} />
      )}
      {losing && (
        <SelectDialog title="Mark deal as lost" danger confirmLabel="Mark lost"
          body={`Why was "${losing.title}" lost? This feeds the lost-reasons report.`}
          options={reasons.map((r) => ({ id: r.id, label: r.label }))}
          onConfirm={async (reasonId) => {
            await api(`/deals/${losing.id}/lost/`,
              { method: "POST", body: { lost_reason_id: reasonId } });
            toast.info(`${losing.title} marked lost.`);
            refresh();
          }}
          onClose={() => setLosing(null)} />
      )}
    </div>
  );
}
