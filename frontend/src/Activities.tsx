import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import ScheduleDialog from "./ScheduleDialog";
import { EmptyState, Skeleton, toast } from "./ui";

interface MyActivity {
  id: number;
  type_name: string;
  subject: string;
  due_at: string;
  deal: number | null;
  deal_title: string | null;
  note: string;
}

type Buckets = Record<"overdue" | "today" | "this_week" | "planned", MyActivity[]>;

const LABELS: [keyof Buckets, string][] = [
  ["overdue", "Overdue"], ["today", "Today"], ["this_week", "This week"], ["planned", "Planned"],
];
const OUTCOMES = ["connected", "no_answer", "busy", "wrong_number"] as const;

/** A-2: a rep's homepage. */
export default function Activities() {
  const [buckets, setBuckets] = useState<Buckets | null>(null);
  const [scheduleFor, setScheduleFor] = useState<{ id: number; title: string } | null>(null);

  const load = useCallback(async () => {
    setBuckets(await api<Buckets>("/activities/my/"));
  }, []);

  useEffect(() => { void load(); }, [load]);

  const complete = async (a: MyActivity, outcome = "") => {
    const r = await api<{ prompt_next: boolean }>(`/activities/${a.id}/complete/`, {
      method: "POST", body: { outcome },
    });
    toast.ok(`${a.type_name} done${outcome ? ` — ${outcome.replace("_", " ")}` : ""}.`);
    if (r.prompt_next && a.deal !== null) {
      setScheduleFor({ id: a.deal, title: a.deal_title ?? "deal" }); // D-5 prompt
    }
    void load();
  };

  const fmt = (iso: string) =>
    new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short",
      hour: "2-digit", minute: "2-digit" });

  if (!buckets) return <Skeleton rows={4} height={58} />;

  const total = Object.values(buckets).reduce((n, b) => n + b.length, 0);
  if (total === 0) {
    return (
      <EmptyState icon="✅" title="All clear — nothing due"
        body="No overdue or scheduled activities. Check the Pipeline for deals flagged ⚠ without a next step, or work the Leads inbox." />
    );
  }

  return (
    <div style={{ padding: "0 20px" }}>
      {LABELS.map(([key, label]) => (
        <section key={key}>
          <h2 style={{ fontSize: 15, margin: "18px 0 6px",
            color: key === "overdue" && buckets[key].length ? "var(--rot)" : "var(--ink)" }}>
            {label} ({buckets[key].length})
          </h2>
          {buckets[key].length === 0 && <p style={{ color: "var(--muted)", margin: 0 }}>Nothing here.</p>}
          {buckets[key].map((a) => (
            <div key={a.id} className="deal" style={{ cursor: "default",
              borderLeftColor: key === "overdue" ? "var(--rot)" : "transparent" }}>
              <div className="t">{a.type_name}: {a.subject}</div>
              <div className="sub">
                <span>{a.deal_title ? `Deal: ${a.deal_title} · ` : ""}{fmt(a.due_at)}</span>
                <span>
                  {a.type_name === "Call"
                    ? OUTCOMES.map((o) => (
                        <button key={o} className="ghost" style={{ marginLeft: 4, padding: "2px 8px" }}
                          onClick={() => void complete(a, o)}>
                          {o.replace("_", " ")}
                        </button>
                      ))
                    : <button className="ghost" style={{ padding: "2px 8px" }}
                        onClick={() => void complete(a)}>Done ✓</button>}
                </span>
              </div>
            </div>
          ))}
        </section>
      ))}
      {scheduleFor && (
        <ScheduleDialog dealId={scheduleFor.id} dealTitle={scheduleFor.title} open
          onClose={() => setScheduleFor(null)} onScheduled={() => void load()} />
      )}
    </div>
  );
}
