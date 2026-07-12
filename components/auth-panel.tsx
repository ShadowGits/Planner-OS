"use client";

import { useState, type FormEvent } from "react";
import { ArrowRight, CalendarCheck } from "lucide-react";
import { getSupabase } from "@/lib/supabase";

interface AuthPanelProps {
  message: string;
  onMessage: (message: string) => void;
}

export function AuthPanel({ message, onMessage }: AuthPanelProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const creatingAccount = submitter?.value === "signup";
    setBusy(true);
    const credentials = { email: email.trim(), password };
    const { error } = creatingAccount
      ? await getSupabase().auth.signUp(credentials)
      : await getSupabase().auth.signInWithPassword(credentials);
    setBusy(false);
    onMessage(error ? error.message : creatingAccount
      ? "Check your email to finish creating your account"
      : "Signed in");
  }

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="sign-in-title">
        <div className="brand-mark"><CalendarCheck size={22} aria-hidden="true" /></div>
        <p className="eyebrow">Planner OS</p>
        <h1 id="sign-in-title">Sign in to your planner</h1>
        <p className="muted">Your workbook stays the source of truth.</p>
        {message && <p className="auth-message" role="status">{message}</p>}
        <form onSubmit={submit} className="auth-form">
          <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={6} required /></label>
          <button className="primary-button" disabled={busy} type="submit" name="auth-action" value="signin">
            {busy ? "Signing in..." : "Sign in"}<ArrowRight size={17} aria-hidden="true" />
          </button>
          <button className="text-button" type="submit" name="auth-action" value="signup" disabled={busy}>Create an account</button>
        </form>
      </section>
    </main>
  );
}
