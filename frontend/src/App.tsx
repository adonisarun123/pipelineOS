import { useState } from "react";
import Activities from "./Activities";
import { getAuth, setAuth } from "./api";
import Automations from "./Automations";
import Contacts from "./Contacts";
import DealDetail from "./DealDetail";
import ImportWizard from "./ImportWizard";
import Kanban from "./Kanban";
import Leads from "./Leads";
import Login from "./Login";
import NotificationBell from "./NotificationBell";
import Reports from "./Reports";
import SearchBox from "./SearchBox";
import Settings from "./Settings";
import Team from "./Team";
import type { Auth } from "./types";

type View = "activities" | "pipeline" | "leads" | "contacts" | "import" | "team"
  | "settings" | "automations" | "reports";

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
          <a className={view === "contacts" ? "active" : ""} onClick={() => setView("contacts")}>
            Contacts
          </a>
          <a className={view === "reports" ? "active" : ""} onClick={() => setView("reports")}>
            Reports
          </a>
          {(auth.role === "admin" || auth.role === "manager") && (
            <a className={view === "import" ? "active" : ""} onClick={() => setView("import")}>
              Import
            </a>
          )}
          {(auth.role === "admin" || auth.role === "manager") && (
            <a className={view === "automations" ? "active" : ""}
              onClick={() => setView("automations")}>
              Automations
            </a>
          )}
          {auth.role === "admin" && (
            <a className={view === "team" ? "active" : ""} onClick={() => setView("team")}>
              Team
            </a>
          )}
        </nav>
        <SearchBox onOpenDeal={setSearchDeal} />
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center",
          color: "var(--muted)" }}>
          <NotificationBell />
          <a style={{ cursor: "pointer" }} onClick={() => setView("settings")}>⚙</a>
          {auth.username} ({auth.role}){" "}
          <button className="ghost" onClick={() => { setAuth(null); setAuthState(null); }}>
            Sign out
          </button>
        </span>
      </header>
      {view === "activities" && <Activities />}
      {view === "pipeline" && <Kanban />}
      {view === "leads" && <Leads />}
      {view === "contacts" && <Contacts />}
      {view === "import" && <ImportWizard />}
      {view === "team" && <Team selfId={auth.user_id} />}
      {view === "settings" && <Settings />}
      {view === "automations" && <Automations isAdmin={auth.role === "admin"} />}
      {view === "reports" && <Reports />}
      {searchDeal !== null && (
        <DealDetail dealId={searchDeal} onClose={() => setSearchDeal(null)}
          onChanged={() => undefined} />
      )}
    </div>
  );
}
