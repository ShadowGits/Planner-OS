-- Migration 0015: Project Widgets
-- Creates a dynamic layout table for projects to store widget configurations

CREATE TABLE project_widgets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    widget_type TEXT NOT NULL, -- 'qna', 'csv', 'text'
    title TEXT,
    file_id TEXT,
    config JSONB DEFAULT '{}'::jsonb,
    order_index INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS
ALTER TABLE project_widgets ENABLE ROW LEVEL SECURITY;

-- Standard RLS policies restricting access to user_id
CREATE POLICY "Users can manage their own project widgets" 
ON project_widgets FOR ALL 
USING (auth.uid() = user_id);

-- Indexes for performance
CREATE INDEX idx_project_widgets_project_id ON project_widgets(project_id);
CREATE INDEX idx_project_widgets_user_id ON project_widgets(user_id);
CREATE INDEX idx_project_widgets_workspace_id ON project_widgets(workspace_id);
