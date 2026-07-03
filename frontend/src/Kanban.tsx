import { useCallback, useEffect, useState } from "react";
import { api, inr } from "./api";
import type { Deal, Kanban as KanbanData, LostReason, Paginated, Pipeline } from "./types";

export default function Kanban() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [pid, setPid] = useState<number | null>(null);
  const [board, setBoard] = useState<KanbanData | null>(null);
  const [reasons, setReasons] = useState<LostReason[]>([]);
  const [err, setErr] = useState("");

  const load = useCallback(async (p: number) => {
    setBoard(await api<KanbanData>(`/pipelines/${p}/kanban/`));
  }, []);

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
    const dealId = e.dataTransfer.getData("text/plain");
    try {
      await api(`/deals/${dealId}/move/`, { method: "POST", body: { stage_id: stageId } });
      setErr("");
    } catch {
      setErr("Move failed");
    }
    refresh();
  };

  const onWon = async (deal: Deal) => {
    if (!confirm(`Mark "${deal.title}" as WON?`)) return;
    await api(`/deals/${deal.id}/won/`, { method: "POST" });
    refresh();
  };

  const onLost = async (deal: Deal) => {
    const labels = reasons.map((r, i) => `${i + 1}. ${r.label}`).join("\n");
    const pick = prompt(`Lost reason (required):\n${labels}\nEnter number:`);
    const reason = reasons[Number(pick) - 1];
    if (!reason) return;
    await api(`/deals/${deal.id}/lost/`, { method: "POST", body: { lost_reason_id: reason.id } });
    refresh();
  };

  const quickAdd = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const title = f.get("title") as string;
    if (!title || pid === null) return;
    await api("/deals/", {
      method: "POST",
      body: { title, value: (f.get("value") as string) || "0", pipeline: pid },
    });
    e.currentTarget.reset();
    refresh();
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
        <span className="err">{err}</span>
      </div>
      <form className="quickadd" onSubmit={quickAdd}>
        <input name="title" placeholder="New deal title…" />
        <input name="value" type="number" placeholder="Value (INR)" />
        <button>Add deal</button>
      </form>
      <div className="board">
        {board?.columns.map((c) => (
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
                title={d.is_rotten ? "Rotting: no recent activity" : ""}
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
    </div>
  );
}
