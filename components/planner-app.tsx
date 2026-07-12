"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { Download, FileSpreadsheet, Menu, RefreshCw } from "lucide-react";
import { AuthPanel } from "@/components/auth-panel";
import { CalendarPanel } from "@/components/calendar-panel";
import { PlannerConsole } from "@/components/planner-console";
import { ResultPanel } from "@/components/result-panel";
import { WorkbookDialog } from "@/components/workbook-dialog";
import { WorkspaceSidebar } from "@/components/workspace-sidebar";
import { plannerApi } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";
import type { Envelope, Workspace } from "@/lib/types";

interface CalendarStatus {
  connected: boolean;
  status: string;
  calendar_id: string | null;
}

const emptyCalendar: CalendarStatus = { connected: false, status: "not_connected", calendar_id: null };

export function PlannerApp() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [calendar, setCalendar] = useState<CalendarStatus>(emptyCalendar);
  const [result, setResult] = useState<Envelope | null>(null);
  const [message, setMessage] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const supabase = getSupabase();
    async function applySession(nextSession: Session | null) {
      setSession(nextSession);
      if (!nextSession) {
        setWorkspaces([]);
        setActiveId(null);
        return;
      }
      try {
        const response = await plannerApi.workspaces(nextSession.access_token);
        setWorkspaces(response.data.workspaces);
        const active = response.data.workspaces.find((item) => item.is_active) ?? response.data.workspaces[0];
        setActiveId(active?.id ?? null);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Could not load workspaces");
      }
    }
    void supabase.auth.getSession().then(({ data }) => applySession(data.session).finally(() => setReady(true)));
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => { void applySession(nextSession); });
    return () => data.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session || !activeId) return;
    void plannerApi.calendarStatus(session.access_token, activeId)
      .then((response) => setCalendar(response.data))
      .catch((error: Error) => setMessage(error.message));
  }, [session, activeId]);

  async function activate(workspaceId: string) {
    if (!session) return;
    try {
      await plannerApi.activateWorkspace(session.access_token, workspaceId);
      setActiveId(workspaceId);
      setWorkspaces((items) => items.map((item) => ({ ...item, is_active: item.id === workspaceId })));
      setMenuOpen(false);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not activate workspace"); }
  }

  async function createWorkspace(name: string, timezone: string, file: File) {
    if (!session) return;
    const workbook_base64 = await fileToBase64(file);
    try {
      const response = await plannerApi.createWorkspace(session.access_token, { name, timezone, workbook_base64 });
      setWorkspaces((items) => [...items.map((item) => ({ ...item, is_active: false })), response.data.workspace]);
      setActiveId(response.data.workspace.id);
      setMessage("Workspace created");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not create workspace"); }
  }

  async function invoke(tool: string, args: Record<string, unknown>): Promise<Envelope> {
    if (!session || !activeId) throw new Error("Choose a workspace first");
    try {
      return await plannerApi.invoke(session.access_token, activeId, tool, args);
    } catch (error) {
      const failure = failureEnvelope(error instanceof Error ? error.message : "Planner operation failed", tool);
      setResult(failure);
      return failure;
    }
  }

  async function downloadWorkbook() {
    if (!session || !activeId) return;
    const response = await fetch(plannerApi.workbookUrl(activeId), { headers: { Authorization: `Bearer ${session.access_token}` } });
    if (!response.ok) { setMessage("Could not download workbook"); return; }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url; link.download = "planner-os.xlsx"; link.click(); URL.revokeObjectURL(url);
  }

  async function connectCalendar() {
    if (!session || !activeId) return;
    try {
      const response = await plannerApi.connectCalendar(session.access_token, activeId);
      window.location.assign(response.data.authorization_url);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not connect calendar"); }
  }

  async function disconnectCalendar() {
    if (!session || !activeId) return;
    try {
      await plannerApi.disconnectCalendar(session.access_token, activeId);
      setCalendar(emptyCalendar);
      setMessage("Google Calendar disconnected");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not disconnect calendar"); }
  }

  if (!ready) return <main className="loading-screen"><RefreshCw className="spin" aria-label="Loading" /></main>;
  if (!session) return <AuthPanel message={message} onMessage={setMessage} />;

  const active = workspaces.find((item) => item.id === activeId) ?? null;
  return (
    <div className="app-shell">
      <div className={menuOpen ? "mobile-scrim visible" : "mobile-scrim"} onClick={() => setMenuOpen(false)} />
      <div className={menuOpen ? "sidebar-wrap open" : "sidebar-wrap"}>
        <WorkspaceSidebar workspaces={workspaces} activeId={activeId} onActivate={activate} onCreate={() => setDialogOpen(true)} onSignOut={() => void getSupabase().auth.signOut()} />
      </div>
      <main className="workspace-main">
        <header className="topbar">
          <button className="icon-button mobile-menu" onClick={() => setMenuOpen(true)} title="Open navigation" type="button"><Menu size={19} /></button>
          <div className="workspace-heading"><p className="eyebrow">Active workspace</p><h1>{active?.name ?? "No workspace"}</h1></div>
          {active && <div className="topbar-meta"><span>Revision {active.revision}</span><span>{active.timezone}</span></div>}
          <button className="secondary-button" disabled={!active} onClick={downloadWorkbook} type="button"><Download size={16} />Workbook</button>
        </header>
        {message && <div className="notice" role="status">{message}<button type="button" onClick={() => setMessage("")}>Dismiss</button></div>}
        {!active ? (
          <section className="empty-workspace"><FileSpreadsheet size={30} /><h2>No workbook attached</h2><button className="primary-button" onClick={() => setDialogOpen(true)} type="button">Create workspace</button></section>
        ) : (
          <div className="workspace-content">
            <CalendarPanel connected={calendar.connected} status={calendar.status} onConnect={connectCalendar} onDisconnect={disconnectCalendar} />
            <div className="work-grid"><PlannerConsole onInvoke={invoke} onResult={setResult} /><ResultPanel result={result} /></div>
          </div>
        )}
      </main>
      <WorkbookDialog open={dialogOpen} onClose={() => setDialogOpen(false)} onSubmit={createWorkspace} />
    </div>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function failureEnvelope(message: string, operation: string): Envelope {
  return { success: false, message, data: {}, warnings: [], errors: [message], preview_id: null, requires_confirmation: false, operation, target: null, decision_id: null };
}
