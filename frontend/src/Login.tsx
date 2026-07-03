import { useState } from "react";
import { api, ApiError } from "./api";
import type { Auth } from "./types";

export default function Login({ onAuth }: { onAuth: (a: Auth) => void }) {
  const [err, setErr] = useState("");
  const [mode, setMode] = useState<"login" | "signup">("login");

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const a = await api<Auth>("/auth/login/", {
        method: "POST",
        body: { username: f.get("u"), password: f.get("p") },
      });
      onAuth(a);
    } catch {
      setErr("Invalid credentials");
    }
  };

  const signup = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    try {
      const a = await api<Auth>("/signup/", { method: "POST", body: {
        company: f.get("company"), subdomain: f.get("subdomain"),
        username: f.get("u"), email: f.get("email"), password: f.get("p"),
      } });
      onAuth(a);
    } catch (ex) {
      setErr(ex instanceof ApiError
        ? (JSON.parse(ex.body) as { detail?: string }).detail ?? "Signup failed"
        : "Signup failed");
    }
  };

  if (mode === "signup") {
    return (
      <form className="login" onSubmit={signup}>
        <h1>Create workspace</h1>
        <input name="company" placeholder="Company name" required autoFocus />
        <input name="subdomain" placeholder="Workspace ID (e.g. acme-events)" required />
        <input name="u" placeholder="Your username" required />
        <input name="email" type="email" placeholder="Email" required />
        <input name="p" type="password" placeholder="Password (10+ chars)" required />
        <div className="err">{err}</div>
        <button>Start 14-day trial</button>
        <a href="#" style={{ fontSize: 13, textAlign: "center" }}
          onClick={(e) => { e.preventDefault(); setMode("login"); setErr(""); }}>
          Back to sign in
        </a>
      </form>
    );
  }

  return (
    <form className="login" onSubmit={submit}>
      <h1>PipelineOS</h1>
      <input name="u" placeholder="Username" autoFocus required />
      <input name="p" type="password" placeholder="Password" required />
      <div className="err">{err}</div>
      <button>Sign in</button>
      <a href="#" style={{ fontSize: 13, textAlign: "center" }}
        onClick={(e) => { e.preventDefault(); setMode("signup"); setErr(""); }}>
        New here? Create a workspace
      </a>
    </form>
  );
}
