import { useState } from "react";
import Activities from "./Activities";
import { getAuth, setAuth } from "./api";
import DealDetail from "./DealDetail";
import ImportWizard from "./ImportWizard";
import Kanban from "./Kanban";
import Leads from "./Leads";
import Login from "./Login";
import SearchBox from "./SearchBox";
import type { Auth } from "./types";

type View = "activities" | "pipeline" | "leads" | "import";

export default function App() {
  const [auth, setAuthState] = useState<Auth | null>(getAuth());
  const [view, setView] = useState<View>("pipeline");
  const [searchDeal, setSearchDeal] = useState<number | null>(null);

  if (!auth) {
    return <Login onAuth={(a) => { setAuth(a); setAuthState(a); }} />;
  }

  return (
    <div>
      <header>
        <h1>PipelineOS</h1>
        <nav>
          <a className={view === "activities" ? "active" : ""} onClick={() => setView("activities")}>
            My Activities
          </a>
          <a className={view === "pipeline" ? "active" : ""} onClick={() => setView("pipeline")}>
            Pipeline
          </a>
          <a className={view === "leads" ? "active" : ""} onClick={() => setView("leads")}>
            Leads
          </a>
          {(auth.role === "admin" || auth.role === "manager") && (
            <a className={view === "import" ? "active" : ""} onClick={() => setView("import")}>
              Import
            </a>
          )}
        </nav>
        <SearchBox onOpenDeal={setSearchDeal} />
        <span style={{ marginLeft: "auto", color: "var(--muted)" }}>
          {auth.username} ({auth.role}){" "}
          <button className="ghost" onClick={() => { setAuth(null); setAuthState(null); }}>
            Sign out
          </button>
        </span>
      </header>
      {view === "activities" && <Activities />}
      {view === "pipeline" && <Kanban />}
      {view === "leads" && <Leads />}
      {view === "import" && <ImportWizard />}
      {searchDeal !== null && (
        <DealDetail dealId={searchDeal} onClose={() => setSearchDeal(null)}
          onChanged={() => undefined} />
      )}
    </div>
  );
}
