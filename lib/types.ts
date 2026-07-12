export interface Envelope<T = Record<string, unknown>> {
  success: boolean;
  message: string;
  data: T;
  warnings: string[];
  errors: string[];
  preview_id: string | null;
  requires_confirmation: boolean;
  operation: string | null;
  target: string | null;
  decision_id: string | null;
}

export interface Workspace {
  id: string;
  name: string;
  timezone: string;
  active_execution_target: "google_calendar" | "apple_calendar" | "none";
  revision: number;
  is_active: boolean;
}

export interface ToolParameter {
  name: string;
  annotation: string;
  required: boolean;
  default?: string | null;
}

export interface PlannerTool {
  name: string;
  description: string;
  parameters: ToolParameter[];
  effect: string;
  confirmation: string;
  available: boolean;
  unavailable_reason: string | null;
}
