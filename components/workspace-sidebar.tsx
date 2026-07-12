"use client";

import { CalendarDays, FileSpreadsheet, LogOut, Plus, Settings } from "lucide-react";
import type { Workspace } from "@/lib/types";

interface WorkspaceSidebarProps {
  workspaces: Workspace[];
  activeId: string | null;
  onActivate: (workspaceId: string) => void;
  onCreate: () => void;
  onSignOut: () => void;
}

export function WorkspaceSidebar({ workspaces, activeId, onActivate, onCreate, onSignOut }: WorkspaceSidebarProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-brand"><CalendarDays size={21} aria-hidden="true" /><strong>Planner OS</strong></div>
      <nav aria-label="Planner workspaces">
        <p className="nav-label">Workspaces</p>
        {workspaces.map((workspace) => (
          <button
            className={`nav-item ${workspace.id === activeId ? "active" : ""}`}
            key={workspace.id}
            onClick={() => onActivate(workspace.id)}
            type="button"
          >
            <FileSpreadsheet size={17} aria-hidden="true" />
            <span>{workspace.name}</span>
          </button>
        ))}
        <button className="nav-item" onClick={onCreate} type="button"><Plus size={17} aria-hidden="true" /><span>New workspace</span></button>
      </nav>
      <div className="sidebar-footer">
        <button className="nav-item" type="button" disabled><Settings size={17} aria-hidden="true" /><span>Settings</span></button>
        <button className="nav-item" onClick={onSignOut} type="button"><LogOut size={17} aria-hidden="true" /><span>Sign out</span></button>
      </div>
    </aside>
  );
}
