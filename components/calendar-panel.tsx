"use client";

import { CalendarCheck, Link2, Unlink } from "lucide-react";

interface CalendarPanelProps {
  connected: boolean;
  status: string;
  onConnect: () => void;
  onDisconnect: () => void;
}

export function CalendarPanel({ connected, status, onConnect, onDisconnect }: CalendarPanelProps) {
  return (
    <section className="settings-band" aria-labelledby="calendar-title">
      <div className="section-icon"><CalendarCheck size={19} aria-hidden="true" /></div>
      <div className="section-copy"><h2 id="calendar-title">Google Calendar</h2><p>{connected ? "Connected for this workspace" : "Workbook-only until connected"}</p></div>
      <span className={`status-dot ${connected ? "connected" : ""}`}>{status.replaceAll("_", " ")}</span>
      <button className="secondary-button" type="button" onClick={connected ? onDisconnect : onConnect}>
        {connected ? <Unlink size={16} /> : <Link2 size={16} />}{connected ? "Disconnect" : "Connect"}
      </button>
    </section>
  );
}
