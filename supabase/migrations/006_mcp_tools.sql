-- Migration: Create public.mcp_tools table for enterprise MCP integrations.
-- This table stores tools discovered from registered MCP servers and connections.

CREATE TABLE IF NOT EXISTS public.mcp_tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    description TEXT,
    parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure user has only one tool schema per provider and tool name
ALTER TABLE public.mcp_tools
    DROP CONSTRAINT IF EXISTS mcp_tools_user_provider_tool_name_key;

ALTER TABLE public.mcp_tools
    ADD CONSTRAINT mcp_tools_user_provider_tool_name_key UNIQUE (user_id, provider, tool_name);

-- Create index for quick lookup by user and provider
CREATE INDEX IF NOT EXISTS mcp_tools_user_provider_idx
    ON public.mcp_tools (user_id, provider);

-- Enable Row-Level Security (RLS)
ALTER TABLE public.mcp_tools ENABLE ROW LEVEL SECURITY;

-- Policy: Authenticated users can manage (select, insert, update, delete) only their own rows
DROP POLICY IF EXISTS mcp_tools_owner_all ON public.mcp_tools;
CREATE POLICY mcp_tools_owner_all ON public.mcp_tools
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
