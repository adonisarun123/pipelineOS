import { useState } from "react";

// I-1: upload → auto-map → dry-run preview → import → per-row error report.
interface Report {
  mapping: Record<string, string | null>;
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  skipped: number;
  errors: { row: number; error: string }[];
  preview: ({ row: number; action: string } & Record<string, string | number>)[];
}

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function upload(file: File, strategy: string, dryRun: boolean): Promise<Report> {
  const auth = JSON.parse(localStorage.getItem("auth") ?? "null") as { token: string } | null;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("strategy", strategy);
  fd.append("dry_run", String(dryRun));
  const r = await fetch(`${BASE}/api/v1/import/people/`, {
    method: "POST",
    headers: auth ? { Authorization: `Token ${auth.token}` } : {},
    body: fd,
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return (await r.json()) as Report;
}

export default function ImportWizard() {
  const [file, setFile] = useState<File | null>(null);
  const [strategy, setStrategy] = useState("skip");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(true);
    setErr("");
    try {
      setReport(await upload(file, strategy, dryRun));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Import failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: 20, maxWidth: 900 }}>
      <h2 style={{ marginTop: 0 }}>Import contacts (CSV)</h2>
      <p style={{ color: "var(--muted)" }}>
        Columns auto-detected: Name, Company, Email, Phone/Mobile, Designation.
        Duplicates matched on email and normalized phone.
      </p>
      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
        <input type="file" accept=".csv,text/csv"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); }} />
        <select value={strategy} onChange={(e) => setStrategy(e.target.value)}>
          <option value="skip">Duplicates: skip</option>
          <option value="update">Duplicates: update</option>
          <option value="create">Duplicates: create anyway</option>
        </select>
        <button disabled={!file || busy} className="ghost" onClick={() => void run(true)}>
          Dry run
        </button>
        <button disabled={!file || busy || !report?.dry_run} onClick={() => void run(false)}
          title={report?.dry_run ? "" : "Run a dry run first"}>
          Import
        </button>
      </div>
      <div className="err" style={{ marginTop: 8 }}>{err}</div>
      {report && (
        <div style={{ marginTop: 12 }}>
          <p>
            <strong>{report.dry_run ? "Dry run" : "Imported"}:</strong>{" "}
            {report.total} rows → {report.created} create, {report.updated} update,{" "}
            {report.skipped} skip, {report.errors.length} errors.
          </p>
          {report.errors.length > 0 && (
            <div className="dupewarn">
              {report.errors.map((e) => <div key={e.row}>Row {e.row}: {e.error}</div>)}
            </div>
          )}
          {report.preview.length > 0 && (
            <table className="leads" style={{ margin: "12px 0", width: "100%" }}>
              <thead>
                <tr><th>Row</th><th>Action</th><th>First name</th><th>Last name</th>
                  <th>Email</th><th>Phone</th><th>Organization</th></tr>
              </thead>
              <tbody>
                {report.preview.slice(0, 50).map((p) => (
                  <tr key={p.row}>
                    <td>{p.row}</td>
                    <td><span className={`pill ${p.action === "create" ? "new" : ""}`}>{p.action}</span></td>
                    <td>{p.first_name ?? ""}</td><td>{p.last_name ?? ""}</td>
                    <td>{p.email ?? ""}</td><td>{p.phone ?? ""}</td>
                    <td>{p.organization ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
