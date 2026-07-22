"""Dependency assembly for authenticated Planner OS cloud requests."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from adapters.cloud import CloudPlannerToolsFactory
from adapters.supabase import (
    SupabaseCalendarConnectionRepository,
    SupabaseExternalLinkRepository,
    SupabaseOAuthStateRepository,
    SupabaseOperationRepository,
    SupabasePreviewRepository,
    SupabaseRestClient,
    SupabaseWorkbookObjectStore,
    SupabaseWorkspaceRepository,
)
from adapters.supabase.client import SupabaseConfig
from planner_platform.auth import AuthenticatedUser
from planner_platform.context import PlannerContext
from planner_platform.google_oauth import (
    CredentialCipher,
    GoogleOAuthService,
    SupabaseGoogleCalendarClientFactory,
)
from planner_platform.workbook_session import WorkbookSession


class CloudRuntime:
    def __init__(self, service_client=None, cipher=None) -> None:
        self.service_client = service_client or SupabaseRestClient(SupabaseConfig.from_env())
        self.cipher = cipher or CredentialCipher.from_env()

    @staticmethod
    def user_client(user: AuthenticatedUser):
        return SupabaseRestClient(SupabaseConfig.from_env(user_access_token=user.access_token))

    def workspaces(self, user: AuthenticatedUser):
        return SupabaseWorkspaceRepository(self.user_client(user))

    def context(self, user: AuthenticatedUser, workspace_id: UUID) -> PlannerContext:
        workspace = self.workspaces(user).get_owned(user.user_id, workspace_id)
        if workspace is None:
            raise ValueError("Planner workspace was not found")
        return PlannerContext(
            user_id=user.user_id,
            workspace_id=workspace.id,
            operation_id=uuid4(),
            workbook_path=Path("request-workbook.xlsx"),
            timezone=workspace.timezone,
            execution_target=workspace.active_execution_target,
            source_revision=workspace.revision,
        )

    def execute(self, user, workspace_id, tool_name, arguments):
        client = self.user_client(user)
        workspaces = SupabaseWorkspaceRepository(client)
        connections = SupabaseCalendarConnectionRepository(client)
        external_links = SupabaseExternalLinkRepository(client)
        google_factory = SupabaseGoogleCalendarClientFactory(
            connections,
            self.cipher,
            external_links,
        )

        def tools_factory_builder(root, context):
            return CloudPlannerToolsFactory(
                state_root=root / "state",
                google_client_factory=google_factory,
                external_links_factory=external_links.bind,
            )

        return WorkbookSession(
            user_id=user.user_id,
            workspace_id=workspace_id,
            workspaces=workspaces,
            storage=SupabaseWorkbookObjectStore(client),
            operations=SupabaseOperationRepository(client),
            tools_factory_builder=tools_factory_builder,
            previews=SupabasePreviewRepository(client),
        ).execute(tool_name, arguments)

    def google_client_factory(self) -> SupabaseGoogleCalendarClientFactory:
        """Service-role Google Calendar client factory for unattended jobs
        (the Postgres→Calendar sync cron), built on the service client."""
        return SupabaseGoogleCalendarClientFactory(
            SupabaseCalendarConnectionRepository(self.service_client),
            self.cipher,
            SupabaseExternalLinkRepository(self.service_client),
        )

    def google_oauth_for_user(self, user: AuthenticatedUser) -> GoogleOAuthService:
        client = self.user_client(user)
        return GoogleOAuthService(
            SupabaseOAuthStateRepository(client, self.service_client),
            SupabaseCalendarConnectionRepository(client),
            self.cipher,
        )

    def google_oauth_callback(self) -> GoogleOAuthService:
        return GoogleOAuthService(
            SupabaseOAuthStateRepository(self.service_client, self.service_client),
            SupabaseCalendarConnectionRepository(self.service_client),
            self.cipher,
        )
