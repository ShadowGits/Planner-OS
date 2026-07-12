"use client";

import { useState } from "react";
import { CalendarRange, Play, RotateCcw, Sparkles } from "lucide-react";
import type { Envelope } from "@/lib/types";

interface PlannerConsoleProps {
  onInvoke: (tool: string, args: Record<string, unknown>) => Promise<Envelope>;
  onResult: (result: Envelope) => void;
}

const planTools = {
  day: ["preview_day_replan", "apply_day_replan"],
  week: ["preview_week_plan", "apply_week_plan"],
  month: ["preview_month_plan", "apply_month_plan"],
} as const;

export function PlannerConsole({ onInvoke, onResult }: PlannerConsoleProps) {
  const [command, setCommand] = useState("");
  const [scope, setScope] = useState<keyof typeof planTools>("day");
  const [previewId, setPreviewId] = useState("");
  const [parsedCommand, setParsedCommand] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  async function invoke(tool: string, args: Record<string, unknown>) {
    setBusy(true);
    try {
      const result = await onInvoke(tool, args);
      const foundPreview = result.preview_id ?? findPreviewId(result.data);
      if (foundPreview) setPreviewId(foundPreview);
      onResult(result);
    } finally {
      setBusy(false);
    }
  }

  async function parseCommand() {
    if (!command.trim()) return;
    setBusy(true);
    try {
      const result = await onInvoke("parse_common_intent", { text: command.trim() });
      const parsed = result.data.command;
      setParsedCommand(parsed && typeof parsed === "object" ? parsed as Record<string, unknown> : null);
      onResult(result);
    } finally {
      setBusy(false);
    }
  }

  async function previewPlan() {
    const month = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric" }).format(new Date());
    const request: Record<string, unknown> = scope === "day"
      ? { month, target_date: new Date().toISOString().slice(0, 10), current_datetime: new Date().toISOString() }
      : scope === "week"
        ? { relative_week: "next" }
        : { month, planning_mode: "remaining_month", preview_only: true };
    await invoke(planTools[scope][0], { request });
  }

  return (
    <section className="console-panel" aria-labelledby="command-title">
      <header><div className="section-icon"><Sparkles size={19} /></div><div><h2 id="command-title">Planner command</h2></div></header>
      <textarea value={command} onChange={(event) => setCommand(event.target.value)} placeholder="e.g. Plan my coming week" rows={4} />
      <div className="command-actions">
        <button className="primary-button" disabled={busy || !command.trim()} onClick={parseCommand} type="button"><Play size={16} />Parse command</button>
        <button className="secondary-button" disabled={busy || !parsedCommand} onClick={() => invoke("route_planner_command", { command: { ...parsedCommand, requires_confirmation: false } })} type="button"><Sparkles size={16} />Confirm and run</button>
      </div>
      <div className="divider" />
      <div className="plan-controls">
        <div className="segmented" aria-label="Plan scope">
          {(["day", "week", "month"] as const).map((item) => <button className={scope === item ? "selected" : ""} onClick={() => setScope(item)} type="button" key={item}>{item}</button>)}
        </div>
        <button className="secondary-button" disabled={busy} onClick={previewPlan} type="button"><CalendarRange size={16} />Preview</button>
        <button className="secondary-button" disabled={busy || !previewId} onClick={() => invoke(planTools[scope][1], { preview_id: previewId })} type="button"><RotateCcw size={16} />Apply preview</button>
      </div>
    </section>
  );
}

function findPreviewId(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  if ("preview_id" in value && typeof value.preview_id === "string") return value.preview_id;
  for (const nested of Object.values(value)) {
    const found = findPreviewId(nested);
    if (found) return found;
  }
  return null;
}
