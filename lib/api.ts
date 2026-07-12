import type { Envelope, PlannerTool, Workspace } from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_PLANNER_API_URL?.replace(/\/$/, "")
  ?? (process.env.NODE_ENV === "development" ? "http://127.0.0.1:8000" : "");

async function request<T>(path: string, token: string, init?: RequestInit): Promise<Envelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  const body = (await response.json()) as Envelope<T>;
  if (!response.ok || !body.success) throw new Error(body.message || "Planner request failed");
  return body;
}

export const plannerApi = {
  workspaces: (token: string) =>
    request<{ workspaces: Workspace[] }>("/api/workspaces", token),
  tools: (token: string) => request<{ tools: PlannerTool[]; count: number }>("/api/v1/tools", token),
  createWorkspace: (token: string, body: { name: string; timezone: string; workbook_base64: string }) =>
    request<{ workspace: Workspace }>("/api/workspaces", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  activateWorkspace: (token: string, workspaceId: string) =>
    request<{ workspace: Workspace }>(`/api/workspaces/${workspaceId}/activate`, token, { method: "POST" }),
  invoke: (token: string, workspaceId: string, tool: string, args: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/v1/tools/${tool}/invoke`, token, {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, arguments: args }),
    }),
  calendarStatus: (token: string, workspaceId: string) =>
    request<{ connected: boolean; status: string; calendar_id: string | null }>(
      `/api/workspaces/${workspaceId}/google-calendar/status`, token,
    ),
  connectCalendar: (token: string, workspaceId: string) =>
    request<{ authorization_url: string; expires_in_seconds: number }>(
      `/api/workspaces/${workspaceId}/google-calendar/connect`, token, { method: "POST" },
    ),
  disconnectCalendar: (token: string, workspaceId: string) =>
    request<Record<string, never>>(`/api/workspaces/${workspaceId}/google-calendar`, token, { method: "DELETE" }),
  workbookUrl: (workspaceId: string) => `${API_BASE}/api/workspaces/${workspaceId}/workbook`,
};
