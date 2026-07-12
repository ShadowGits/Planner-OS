"""Supabase PostgREST and private Storage adapters."""

from adapters.supabase.client import SupabaseConfig, SupabaseGateway, SupabaseRestClient
from adapters.supabase.operations import SupabaseOperationRepository
from adapters.supabase.previews import SupabasePreviewRepository
from adapters.supabase.storage import SupabaseWorkbookObjectStore, workspace_object_key
from adapters.supabase.workspaces import SupabaseWorkspaceRepository
from adapters.supabase.calendar import (
    SupabaseCalendarConnectionRepository,
    SupabaseExternalLinkRepository,
    SupabaseOAuthStateRepository,
)

__all__ = [
    "SupabaseConfig",
    "SupabaseGateway",
    "SupabaseOperationRepository",
    "SupabasePreviewRepository",
    "SupabaseRestClient",
    "SupabaseWorkbookObjectStore",
    "SupabaseWorkspaceRepository",
    "SupabaseCalendarConnectionRepository",
    "SupabaseExternalLinkRepository",
    "SupabaseOAuthStateRepository",
    "workspace_object_key",
]
