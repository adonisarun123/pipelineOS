import { useEffect, useState } from "react";
import { api } from "./api";
import type { CustomFieldDef } from "./types";

/** CF-1/CF-2: render + edit custom fields on a deal. Important fields flagged. */
export default function CustomFields({ dealId, pipelineId, values, onSaved }: {
  dealId: number;
  pipelineId: number;
  values: Record<string, unknown>;
  onSaved: () => void;
}) {
  const [defs, setDefs] = useState<CustomFieldDef[]>([]);
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [err, setErr] = useState("");

  useEffect(() => {
    void api<CustomFieldDef[]>("/custom-fields/?entity=deal").then((d) =>
      setDefs(d.filter((f) => f.pipeline === null || f.pipeline === pipelineId)),
    );
  }, [pipelineId]);

  if (defs.length === 0) return null;

  const set = (key: string, v: unknown) => setDraft((d) => ({ ...d, [key]: v }));
  const val = (key: string) => (key in draft ? draft[key] : values[key]) ?? "";

  const save = async () => {
    if (Object.keys(draft).length === 0) return;
    setErr("");
    try {
      await api(`/deals/${dealId}/set_custom/`, { method: "POST", body: draft });
      setDraft({});
      onSaved();
    } catch {
      setErr("Invalid value — check types/options");
    }
  };

  const input = (f: CustomFieldDef) => {
    switch (f.field_type) {
      case "single_select":
        return (
          <select value={String(val(f.key))} onChange={(e) => set(f.key, e.target.value)}>
            <option value="">—</option>
            {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        );
      case "checkbox":
        return <input type="checkbox" checked={Boolean(val(f.key))}
          onChange={(e) => set(f.key, e.target.checked)} />;
      case "number":
      case "currency":
        return <input type="number" value={String(val(f.key))}
          onChange={(e) => set(f.key, e.target.value)} />;
      case "date":
        return <input type="date" value={String(val(f.key))}
          onChange={(e) => set(f.key, e.target.value)} />;
      case "long_text":
        return <textarea rows={2} value={String(val(f.key))}
          onChange={(e) => set(f.key, e.target.value)} />;
      default:
        return <input value={String(val(f.key))}
          onChange={(e) => set(f.key, e.target.value)} />;
    }
  };

  return (
    <div style={{ margin: "14px 0" }}>
      <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>Details</h3>
      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 8,
        alignItems: "center", fontSize: 13 }}>
        {defs.map((f) => (
          <span key={`l${f.id}`} style={{ display: "contents" }}>
            <label style={{ color: "var(--muted)" }}>
              {f.name}{f.is_important && !values[f.key]
                ? <span className="badge" title="Important field is empty"> ⚠</span> : ""}
            </label>
            {input(f)}
          </span>
        ))}
      </div>
      <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <button className="ghost" disabled={Object.keys(draft).length === 0}
          onClick={() => void save()}>Save details</button>
        <span className="err">{err}</span>
      </div>
    </div>
  );
}
