import { useCallback, useEffect, useState } from "react";
import { api, inr } from "./api";
import CustomFields from "./CustomFields";
import LineItems from "./LineItems";
import ScheduleDialog from "./ScheduleDialog";
import type { Deal } from "./types";

interface TimelineEvent {
  kind: string;
  at: string | null;
  by: string | null;
  summary: string;
  activity_id?: number;
  done?: boolean;
}

const ICON: Record<string, string> = {
  created: "✦", stage: "→", note: "📝", activity_planned: "☐",
  activity_done: "☑", won: "🏆", lost: "✗",
};

/** D-9/C-4: deal header + full timeline, with note-add and schedule-next. */
export default function DealDetail({ dealId, onClose, onChanged }: {
  dealId: number;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [deal, setDeal] = useState<Deal | null>(null);
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [scheduling, setScheduling] = useState(false);

  const load = useCallback(async () => {
    const r = await api<{ deal: Deal; events: TimelineEvent[] }>(`/deals/${dealId}/timeline/`);
    setDeal(r.deal);
    setEvents(r.events);
  }, [dealId]);

  useEffect(() => { void load(); }, [load]);

  const addNote = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = (f.get("body") as string).trim();
    if (!body) return;
    await api(`/deals/${dealId}/add_note/`, { method: "POST", body: { body } });
    e.currentTarget.reset();
    void load();
  };

  const completeActivity = async (id: number) => {
    const r = await api<{ prompt_next: boolean }>(`/activities/${id}/complete/`, {
      method: "POST", body: {},
    });
    if (r.prompt_next) setScheduling(true); // D-5
    void load();
    onChanged();
  };

  const fmt = (iso: string | null) => iso
    ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short",
        year: "numeric", hour: "2-digit", minute: "2-digit" })
    : "";

  if (!deal) return null;

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(9,30,66,.4)", zIndex: 10 }}
      onClick={onClose}>
      <aside onClick={(e) => e.stopPropagation()} style={{ position: "absolute", right: 0,
        top: 0, bottom: 0, width: "min(520px, 95vw)", background: "#fff", padding: 20,
        overflowY: "auto", boxShadow: "-4px 0 16px rgba(9,30,66,.2)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
          <div>
            <h2 style={{ margin: "0 0 4px" }}>{deal.title}</h2>
            <div style={{ color: "var(--muted)", fontSize: 13 }}>
              {deal.organization_name ?? "No organization"} · {inr(deal.value)} ·{" "}
              owner {deal.owner_name} · <span className={`pill ${deal.status}`}>{deal.status}</span>
              {deal.is_rotten && <span className="badge"> · 🥀 rotting</span>}
              {deal.needs_next_activity && <span className="badge"> · ⚠ no next activity</span>}
            </div>
          </div>
          <button className="ghost" onClick={onClose}>Close</button>
        </div>
        <div style={{ display: "flex", gap: 8, margin: "14px 0" }}>
          <button onClick={() => setScheduling(true)}>+ Schedule activity</button>
        </div>
        <CustomFields dealId={deal.id} pipelineId={deal.pipeline}
          values={deal.custom ?? {}} onSaved={() => { void load(); onChanged(); }} />
        <LineItems dealId={deal.id} valueAuto={deal.value_auto}
          onChanged={() => { void load(); onChanged(); }} />
        <form onSubmit={addNote} style={{ display: "flex", gap: 8 }}>
          <input name="body" placeholder="Add a note…" style={{ flex: 1 }} />
          <button className="ghost">Add</button>
        </form>
        <h3 style={{ fontSize: 14, margin: "18px 0 8px" }}>Timeline</h3>
        {events.map((e, i) => (
          <div key={i} style={{ display: "flex", gap: 10, padding: "7px 0",
            borderBottom: "1px solid var(--line)", fontSize: 13 }}>
            <span>{ICON[e.kind] ?? "·"}</span>
            <div style={{ flex: 1 }}>
              <div>{e.summary}</div>
              <div style={{ color: "var(--muted)", fontSize: 11 }}>
                {fmt(e.at)}{e.by ? ` · ${e.by}` : ""}
              </div>
            </div>
            {e.kind === "activity_planned" && e.activity_id !== undefined && (
              <button className="ghost" style={{ padding: "2px 8px", alignSelf: "center" }}
                onClick={() => void completeActivity(e.activity_id!)}>Done ✓</button>
            )}
          </div>
        ))}
        {scheduling && (
          <ScheduleDialog dealId={deal.id} dealTitle={deal.title} open
            onClose={() => setScheduling(false)}
            onScheduled={() => { void load(); onChanged(); }} />
        )}
      </aside>
    </div>
  );
}
