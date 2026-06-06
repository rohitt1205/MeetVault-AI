-- Migration: Create public.mcp_connections table for enterprise MCP integrations.
-- This table stores credentials and status of external tool connections securely under user's UUID.

CREATE TABLE IF NOT EXISTS public.mcp_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_user_id TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at TIMESTAMPTZ,
    connected BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ensure a user has only one connection per provider
ALTER TABLE public.mcp_connections
    DROP CONSTRAINT IF EXISTS mcp_connections_user_provider_key;

ALTER TABLE public.mcp_connections
    ADD CONSTRAINT mcp_connections_user_provider_key UNIQUE (user_id, provider);

-- Create index for quick lookup by user and provider
CREATE INDEX IF NOT EXISTS mcp_connections_user_provider_idx
    ON public.mcp_connections (user_id, provider);

-- Enable Row-Level Security (RLS)
ALTER TABLE public.mcp_connections ENABLE ROW LEVEL SECURITY;

-- Policy: Authenticated users can manage (select, insert, update, delete) only their own rows
DROP POLICY IF EXISTS mcp_connections_owner_all ON public.mcp_connections;
CREATE POLICY mcp_connections_owner_all ON public.mcp_connections
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
