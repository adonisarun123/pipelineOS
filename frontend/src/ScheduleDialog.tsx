import { useEffect, useRef, useState } from "react";
import { api } from "./api";

interface ActivityType { id: number; name: string }

/** A-4: schedule-next with sensible defaults (call → follow-up call in 2 days). */
export default function ScheduleDialog({ dealId, dealTitle, open, onClose, onScheduled }: {
  dealId: number;
  dealTitle: string;
  open: boolean;
  onClose: () => void;
  onScheduled: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [types, setTypes] = useState<ActivityType[]>([]);

  useEffect(() => {
    void api<ActivityType[]>("/activity-types/").then(setTypes);
  }, []);

  useEffect(() => {
    if (open) ref.current?.showModal();
    else ref.current?.close();
  }, [open]);

  const defaultDue = (): string => {
    const d = new Date(Date.now() + 2 * 24 * 3600 * 1000); // +2 days default
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  };

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    await api("/activities/", {
      method: "POST",
      body: {
        type: Number(f.get("type")),
        subject: (f.get("subject") as string) || `Follow up: ${dealTitle}`,
        due_at: new Date(f.get("due") as string).toISOString(),
        deal: dealId,
        note: f.get("note") ?? "",
      },
    });
    onScheduled();
    onClose();
  };

  return (
    <dialog ref={ref} onClose={onClose}>
      <form onSubmit={submit}>
        <h3 style={{ margin: 0 }}>Next activity — {dealTitle}</h3>
        <select name="type" required>
          {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <input name="subject" placeholder={`Follow up: ${dealTitle}`} />
        <input name="due" type="datetime-local" defaultValue={defaultDue()} required />
        <textarea name="note" placeholder="Notes (optional)" rows={2} />
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" className="ghost" onClick={onClose}>Skip</button>
          <button>Schedule</button>
        </div>
      </form>
    </dialog>
  );
}
