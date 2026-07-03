import { useState } from "react";
import { api } from "./api";
import type { Auth } from "./types";

export default function Login({ onAuth }: { onAuth: (a: Auth) => void }) {
  const [err, setErr] = useState("");

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

  return (
    <form className="login" onSubmit={submit}>
      <h1>PipelineOS</h1>
      <input name="u" placeholder="Username" autoFocus required />
      <input name="p" type="password" placeholder="Password" required />
      <div className="err">{err}</div>
      <button>Sign in</button>
    </form>
  );
}
