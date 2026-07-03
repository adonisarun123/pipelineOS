import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { Deal, Lead } from "./types";

interface SearchResult {
  deals: Deal[];
  people: { id: number; first_name: string; last_name: string }[];
  organizations: { id: number; name: string }[];
  leads: Lead[];
}

/** S-1: global search, `/` shortcut, sub-300ms perceived via 200ms debounce. */
export default function SearchBox({ onOpenDeal }: { onOpenDeal: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const timer = useRef<number>();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "/" && !(e.target instanceof HTMLInputElement)
          && !(e.target instanceof HTMLTextAreaElement)) {
        e.preventDefault();
        inputRef.current?.focus();
      }
      if (e.key === "Escape") { setQ(""); setRes(null); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 2) { setRes(null); return; }
    timer.current = window.setTimeout(() => {
      void api<SearchResult>(`/search/?q=${encodeURIComponent(q)}`).then(setRes);
    }, 200);
  }, [q]);

  const empty = res && !res.deals.length && !res.people.length
    && !res.organizations.length && !res.leads.length;

  return (
    <div style={{ position: "relative", flex: 1, maxWidth: 420 }}>
      <input ref={inputRef} value={q} placeholder="Search ( / )" style={{ width: "100%" }}
        onChange={(e) => setQ(e.target.value)} />
      {res && (
        <div style={{ position: "absolute", top: "110%", left: 0, right: 0, background: "#fff",
          border: "1px solid var(--line)", borderRadius: 6, boxShadow: "0 8px 24px rgba(9,30,66,.2)",
          zIndex: 30, maxHeight: 400, overflowY: "auto", fontSize: 13 }}>
          {empty && <div style={{ padding: 10, color: "var(--muted)" }}>No results</div>}
          {res.deals.length > 0 && <div style={{ padding: "6px 10px", color: "var(--muted)" }}>Deals</div>}
          {res.deals.map((d) => (
            <div key={`d${d.id}`} style={{ padding: "6px 10px", cursor: "pointer" }}
              onMouseDown={() => { onOpenDeal(d.id); setQ(""); setRes(null); }}>
              💼 {d.title} <span style={{ color: "var(--muted)" }}>· {d.status}</span>
            </div>
          ))}
          {res.leads.length > 0 && <div style={{ padding: "6px 10px", color: "var(--muted)" }}>Leads</div>}
          {res.leads.map((l) => (
            <div key={`l${l.id}`} style={{ padding: "6px 10px" }}>
              🎯 {l.name} <span style={{ color: "var(--muted)" }}>· {l.status}</span>
            </div>
          ))}
          {res.people.length > 0 && <div style={{ padding: "6px 10px", color: "var(--muted)" }}>People</div>}
          {res.people.map((p) => (
            <div key={`p${p.id}`} style={{ padding: "6px 10px" }}>
              👤 {p.first_name} {p.last_name}
            </div>
          ))}
          {res.organizations.length > 0
            && <div style={{ padding: "6px 10px", color: "var(--muted)" }}>Organizations</div>}
          {res.organizations.map((o) => (
            <div key={`o${o.id}`} style={{ padding: "6px 10px" }}>🏢 {o.name}</div>
          ))}
        </div>
      )}
    </div>
  );
}
