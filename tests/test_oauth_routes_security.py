import asyncio
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.shared.auth import OAuthClientInformationFull

from planner_api.app import create_app
from planner_api.mcp import ApiKeyOAuthProvider

API_KEY = "k" * 40
REDIRECT = "https://client.test/callback?existing=yes&other=1"


@pytest.fixture
def oauth_client(monkeypatch):
    import planner_api.app as app_module
    # Importing through the package can select its exported app instance.
    import importlib
    app_module = importlib.import_module("planner_api.app")
    user_id = uuid4()
    provider = ApiKeyOAuthProvider({API_KEY: str(user_id)}, "https://api.test")
    asyncio.run(provider.register_client(OAuthClientInformationFull(client_id="registered", redirect_uris=[REDIRECT])))
    server = SimpleNamespace(_tool_manager=SimpleNamespace(_tools={}))
    monkeypatch.setenv("MCP_API_KEY", API_KEY)
    monkeypatch.setenv("PLANNER_API_URL", "https://api.test")
    monkeypatch.setattr(app_module, "create_cloud_mcp", lambda _: (server, FastAPI(), provider))
    verifier = SimpleNamespace(verify=lambda _: SimpleNamespace(user_id=user_id, access_token=None))
    return TestClient(create_app(runtime=SimpleNamespace(), verifier=verifier)), provider


def _params(**changes):
    return {"client_id": "registered", "redirect_uri": REDIRECT, "state": "safe-state",
            "code_challenge": "c" * 43, "redirect_uri_provided_explicitly": "true", **changes}


def test_confirmation_escapes_html_in_state(oauth_client):
    client, provider = oauth_client
    attack = '\"><script>alert("key theft")</script>'
    response = client.get("/oauth/authorize/confirm", params=_params(state=attack))
    assert response.status_code == 200
    assert "<script>" not in response.text
    assert "&lt;script&gt;" in response.text
    class HiddenInputs(HTMLParser):
        fields = {}
        def handle_starttag(self, tag, attrs):
            if tag == "input":
                attr = dict(attrs)
                if attr.get("name") == "state":
                    self.fields = attr
    parser = HiddenInputs()
    parser.feed(response.text)
    assert parser.fields == {"type": "hidden", "name": "state", "value": attack}


def test_confirmation_and_submit_reject_unregistered_redirect(oauth_client):
    client, provider = oauth_client
    attack = _params(redirect_uri="https://attacker.test/stolen-code")
    assert client.get("/oauth/authorize/confirm", params=attack).status_code == 400
    assert client.post("/oauth/authorize/submit", data={**attack, "api_key": API_KEY}).status_code == 400
    assert not any(kind == "auth_code" for kind, _ in provider._store._records)


def test_submit_preserves_registered_redirect_query(oauth_client):
    client, provider = oauth_client
    response = client.post("/oauth/authorize/submit", data={**_params(), "api_key": API_KEY}, follow_redirects=False)
    assert response.status_code == 302
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["existing"] == ["yes"]
    assert query["other"] == ["1"]
    assert query["state"] == ["safe-state"]
    assert len(query["code"]) == 1
