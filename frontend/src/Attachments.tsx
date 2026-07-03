import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Paginated } from "./types";

interface FileRow {
  id: number;
  name: string;
  size: number;
  uploaded_by_name: string | null;
  created_at: string;
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export default function Attachments({ dealId }: { dealId: number }) {
  const [files, setFiles] = useState<FileRow[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setFiles((await api<Paginated<FileRow>>(`/files/?deal=${dealId}`)).results);
  }, [dealId]);

  useEffect(() => { void load(); }, [load]);

  const auth = JSON.parse(localStorage.getItem("auth") ?? "null") as
    { token: string } | null;

  const upload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f || !auth) return;
    setBusy(true);
    setErr("");
    const fd = new FormData();
    fd.append("file", f);
    fd.append("deal", String(dealId));
    const r = await fetch(`${BASE}/api/v1/files/`, {
      method: "POST", headers: { Authorization: `Token ${auth.token}` }, body: fd,
    });
    if (!r.ok) setErr((await r.json() as { detail?: string }).detail ?? "Upload failed");
    setBusy(false);
    e.target.value = "";
    void load();
  };

  const download = async (f: FileRow) => {
    if (!auth) return;
    const r = await fetch(`${BASE}/api/v1/files/${f.id}/download/`, {
      headers: { Authorization: `Token ${auth.token}` },
    });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = f.name;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const kb = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB`
    : `${Math.max(1, Math.round(n / 1024))} KB`);

  return (
    <div style={{ margin: "14px 0" }}>
      <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>
        Attachments{" "}
        <label className="ghost" style={{ fontSize: 12, fontWeight: 400,
          cursor: "pointer", border: "1px solid var(--line)", borderRadius: 4,
          padding: "2px 8px" }}>
          {busy ? "Uploading…" : "+ Upload"}
          <input type="file" hidden onChange={(e) => void upload(e)} disabled={busy} />
        </label>
      </h3>
      <span className="err">{err}</span>
      {files.map((f) => (
        <div key={f.id} style={{ display: "flex", justifyContent: "space-between",
          fontSize: 13, padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
          <a href="#" onClick={(e) => { e.preventDefault(); void download(f); }}>
            📎 {f.name}
          </a>
          <span style={{ color: "var(--muted)" }}>
            {kb(f.size)}{f.uploaded_by_name ? ` · ${f.uploaded_by_name}` : ""}
          </span>
        </div>
      ))}
      {files.length === 0 && (
        <span style={{ color: "var(--muted)", fontSize: 13 }}>No files yet.</span>
      )}
    </div>
  );
}
