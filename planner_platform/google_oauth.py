"""Per-workspace Google Calendar web OAuth and credential materialization."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from adapters.supabase.calendar import (
    SupabaseCalendarConnectionRepository,
    SupabaseOAuthStateRepository,
)
from planner_integrations.google_calendar import GoogleCalendarClient, SCOPES
from planner_platform.context import PlannerContext


class GoogleConnectionRequiredError(ValueError):
    pass


class CredentialCipher:
    """Authenticated encryption for OAuth credentials stored in Supabase."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("Credential encryption key must contain 32 bytes")
        self._cipher = AESGCM(key)

    @classmethod
    def from_env(cls) -> "CredentialCipher":
        configured = os.environ.get("PLANNER_CREDENTIAL_ENCRYPTION_KEY", "")
        if configured:
            try:
                return cls(base64.urlsafe_b64decode(configured.encode("ascii")))
            except Exception as error:
                raise ValueError("PLANNER_CREDENTIAL_ENCRYPTION_KEY is invalid") from error
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if not service_key:
            raise ValueError("Credential encryption configuration is required")
        return cls(hashlib.sha256(b"planner-os-google-oauth-v1\0" + service_key.encode()).digest())

    def encrypt(self, plaintext: bytes, *, context: PlannerContext) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._cipher.encrypt(nonce, plaintext, self._aad(context))

    def decrypt(self, ciphertext: bytes, *, context: PlannerContext) -> bytes:
        if len(ciphertext) < 29:
            raise ValueError("Encrypted Google credentials are invalid")
        return self._cipher.decrypt(ciphertext[:12], ciphertext[12:], self._aad(context))

    @staticmethod
    def _aad(context: PlannerContext) -> bytes:
        return f"{context.user_id}:{context.workspace_id}:google_calendar".encode()


@dataclass(frozen=True)
class GoogleOAuthStart:
    authorization_url: str
    expires_in_seconds: int = 600


class GoogleOAuthService:
    def __init__(
        self,
        states: SupabaseOAuthStateRepository,
        connections: SupabaseCalendarConnectionRepository,
        cipher: CredentialCipher,
        *,
        flow_factory: Callable[[str, str | None, str], Any] | None = None,
    ) -> None:
        self.states = states
        self.connections = connections
        self.cipher = cipher
        self.flow_factory = flow_factory or self._google_flow
        self.client_id = os.environ.get("GOOGLE_WEB_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("GOOGLE_WEB_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get(
            "GOOGLE_OAUTH_REDIRECT_URI",
            "http://localhost:8000/auth/google/callback",
        )
        if not self.client_id or not self.client_secret:
            raise ValueError("Google web OAuth client configuration is required")

    def start(self, context: PlannerContext) -> GoogleOAuthStart:
        code_verifier = secrets.token_urlsafe(64)
        state = self.states.create(context, self.redirect_uri, code_verifier)
        flow = self.flow_factory(self.redirect_uri, state, code_verifier)
        url, returned_state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        if returned_state != state:
            raise RuntimeError("Google OAuth state binding failed")
        return GoogleOAuthStart(url)

    def complete(self, *, state: str, code: str) -> PlannerContext:
        stored = self.states.consume(state)
        context = PlannerContext(
            user_id=stored.user_id,
            workspace_id=stored.workspace_id,
            operation_id=uuid4(),
            workbook_path=Path("oauth-callback.xlsx"),
            timezone="UTC",
            execution_target="google_calendar",
            source_revision=0,
        )
        flow = self.flow_factory(stored.redirect_uri, state, stored.code_verifier)
        flow.fetch_token(code=code)
        encrypted = self.cipher.encrypt(flow.credentials.to_json().encode("utf-8"), context=context)
        self.connections.save(context, encrypted)
        return context

    def _google_flow(self, redirect_uri: str, state: str | None, code_verifier: str):
        from google_auth_oauthlib.flow import Flow

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [redirect_uri],
                }
            },
            scopes=SCOPES,
            state=state,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )
        flow.redirect_uri = redirect_uri
        return flow


class SupabaseGoogleCalendarClientFactory:
    def __init__(self, connections, cipher, external_links=None) -> None:
        self.connections = connections
        self.cipher = cipher
        self.external_links = external_links

    def __call__(self, context: PlannerContext) -> GoogleCalendarClient:
        connection = self.connections.get(context.user_id, context.workspace_id)
        if connection is None or connection.status != "active":
            raise GoogleConnectionRequiredError("Connect Google Calendar for this workspace first")
        try:
            data = json.loads(self.cipher.decrypt(connection.encrypted_credentials, context=context))
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            credentials = Credentials.from_authorized_user_info(data, SCOPES)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                self.connections.save(
                    context,
                    self.cipher.encrypt(credentials.to_json().encode(), context=context),
                    target_calendar_id=connection.target_calendar_id,
                    provider_account_id=connection.provider_account_id,
                )
            if not credentials.valid:
                raise GoogleConnectionRequiredError("Google Calendar authorization has expired; reconnect it")
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        except GoogleConnectionRequiredError:
            raise
        except Exception as error:
            self.connections.set_status(context, "error")
            raise GoogleConnectionRequiredError("Google Calendar credentials could not be used") from error
        links = self.external_links.bind(context) if self.external_links else None
        return GoogleCalendarClient(
            calendar_id=connection.target_calendar_id,
            timezone=context.timezone,
            service=service,
            external_links_store=links,
        )
