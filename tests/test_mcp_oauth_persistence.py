"""MCP OAuth state survives provider restarts via the pluggable store."""

from __future__ import annotations

import asyncio
import unittest

from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull

from adapters.supabase.oauth_state import MemoryOAuthStateStore
from planner_api.mcp import ApiKeyOAuthProvider


API_KEY = "k" * 40
USER_ID = "11111111-1111-1111-1111-111111111111"


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="claude-web",
        redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
    )


def _params() -> AuthorizationParams:
    return AuthorizationParams(
        state="state-1",
        scopes=[],
        code_challenge="c" * 43,
        redirect_uri="https://claude.ai/api/mcp/auth_callback",
        redirect_uri_provided_explicitly=True,
    )


class OAuthPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryOAuthStateStore()
        self.provider = ApiKeyOAuthProvider({API_KEY: USER_ID}, "https://api.test", store=self.store)

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _authorize(self, provider: ApiKeyOAuthProvider) -> str:
        client = _client()
        self._run(provider.register_client(client))
        code = self._run(provider.create_authorization_code(client, _params(), USER_ID))
        auth_code = self._run(provider.load_authorization_code(client, code))
        self.assertIsNotNone(auth_code)
        token = self._run(provider.exchange_authorization_code(client, auth_code))
        return token

    def test_full_flow_round_trip(self) -> None:
        token = self._authorize(self.provider)
        access = self._run(self.provider.load_access_token(token.access_token))
        self.assertIsNotNone(access)
        self.assertEqual(access.subject, USER_ID)

    def test_tokens_survive_provider_restart(self) -> None:
        token = self._authorize(self.provider)
        restarted = ApiKeyOAuthProvider({API_KEY: USER_ID}, "https://api.test", store=self.store)
        access = self._run(restarted.load_access_token(token.access_token))
        self.assertIsNotNone(access)
        self.assertEqual(access.subject, USER_ID)
        client = self._run(restarted.get_client("claude-web"))
        self.assertIsNotNone(client)
        refresh = self._run(restarted.load_refresh_token(client, token.refresh_token))
        self.assertIsNotNone(refresh)
        rotated = self._run(restarted.exchange_refresh_token(client, refresh, []))
        self.assertIsNotNone(self._run(restarted.load_access_token(rotated.access_token)))

    def test_auth_code_is_single_use(self) -> None:
        client = _client()
        self._run(self.provider.register_client(client))
        code = self._run(self.provider.create_authorization_code(client, _params(), USER_ID))
        auth_code = self._run(self.provider.load_authorization_code(client, code))
        self._run(self.provider.exchange_authorization_code(client, auth_code))
        self.assertIsNone(self._run(self.provider.load_authorization_code(client, code)))

    def test_reusing_loaded_authorization_code_is_rejected(self) -> None:
        client = _client()
        code = self._run(self.provider.create_authorization_code(client, _params(), USER_ID))
        loaded = self._run(self.provider.load_authorization_code(client, code))
        self._run(self.provider.exchange_authorization_code(client, loaded))
        with self.assertRaises(TokenError):
            self._run(self.provider.exchange_authorization_code(client, loaded))

    def test_concurrent_authorization_code_exchange_only_mints_once(self) -> None:
        client = _client()
        code = self._run(self.provider.create_authorization_code(client, _params(), USER_ID))
        loaded = self._run(self.provider.load_authorization_code(client, code))
        async def race():
            return await asyncio.gather(
                self.provider.exchange_authorization_code(client, loaded),
                self.provider.exchange_authorization_code(client, loaded),
                return_exceptions=True,
            )
        results = self._run(race())
        self.assertEqual(sum(not isinstance(result, Exception) for result in results), 1)

    def test_unregistered_redirect_and_bad_pkce_are_rejected(self) -> None:
        params = _params().model_copy(update={"redirect_uri": "https://attacker.test/callback"})
        with self.assertRaises(ValueError):
            self._run(self.provider.create_authorization_code(_client(), params, USER_ID))
        params = _params().model_copy(update={"code_challenge": "bad"})
        with self.assertRaises(ValueError):
            self._run(self.provider.create_authorization_code(_client(), params, USER_ID))

    def test_authorize_url_encodes_state_instead_of_injecting_parameters(self) -> None:
        from urllib.parse import parse_qs, urlsplit
        params = _params().model_copy(update={"state": "abc&client_id=attacker"})
        result = self._run(self.provider.authorize(_client(), params))
        query = parse_qs(urlsplit(result).query)
        self.assertEqual(query["client_id"], ["claude-web"])
        self.assertEqual(query["state"], ["abc&client_id=attacker"])

    def test_refresh_cannot_replay_or_increase_scope(self) -> None:
        token = self._authorize(self.provider)
        client = _client()
        refresh = self._run(self.provider.load_refresh_token(client, token.refresh_token))
        with self.assertRaises(TokenError):
            self._run(self.provider.exchange_refresh_token(client, refresh, ["admin"]))
        self._run(self.provider.exchange_refresh_token(client, refresh, []))
        with self.assertRaises(TokenError):
            self._run(self.provider.exchange_refresh_token(client, refresh, []))

    def test_refresh_token_rotation_invalidates_old_token(self) -> None:
        token = self._authorize(self.provider)
        client = _client()
        refresh = self._run(self.provider.load_refresh_token(client, token.refresh_token))
        self._run(self.provider.exchange_refresh_token(client, refresh, []))
        self.assertIsNone(self._run(self.provider.load_refresh_token(client, token.refresh_token)))

    def test_revoked_access_token_is_rejected(self) -> None:
        token = self._authorize(self.provider)
        access = self._run(self.provider.load_access_token(token.access_token))
        self._run(self.provider.revoke_token(access))
        self.assertIsNone(self._run(self.provider.load_access_token(token.access_token)))

    def test_raw_secrets_are_not_stored(self) -> None:
        token = self._authorize(self.provider)
        for (kind, key), (payload, _expires) in self.store._records.items():
            self.assertNotEqual(key, token.access_token)
            self.assertNotEqual(key, token.refresh_token)
            if kind in {"access_token", "refresh_token", "auth_code"}:
                self.assertNotIn("token", payload)
                self.assertNotIn("code", payload)

    def test_api_key_fallback_still_works(self) -> None:
        access = self._run(self.provider.load_access_token(API_KEY))
        self.assertIsNotNone(access)
        self.assertEqual(access.subject, USER_ID)


if __name__ == "__main__":
    unittest.main()
