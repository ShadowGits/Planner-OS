-- Add parent_task_id to support multiple time slots per conceptual task
ALTER TABLE planner_tasks 
ADD COLUMN parent_task_id uuid REFERENCES planner_tasks(id) ON DELETE CASCADE;

CREATE INDEX idx_planner_tasks_parent_task_id ON planner_tasks(parent_task_id);
