"""Minimal dependency-free Supabase REST and Storage gateway."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode
from urllib.request import Request, urlopen


class SupabaseError(RuntimeError):
    """Sanitized Supabase transport or response error."""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SupabaseGateway(Protocol):
    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, Any],
        columns: str = "*",
        limit: int | None = None,
        query_string: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def insert(self, table: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]: ...

    def update(
        self,
        table: str,
        payload: Mapping[str, Any],
        *,
        filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]: ...

    def delete(self, table: str, *, filters: Mapping[str, Any]) -> None: ...

    def rpc(self, function: str, payload: Mapping[str, Any]) -> Any: ...

    def storage_download(self, bucket: str, object_key: str) -> bytes: ...

    def storage_upload(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
        upsert: bool,
    ) -> None: ...


@dataclass(frozen=True, repr=False)
class SupabaseConfig:
    url: str
    api_key: str
    access_token: str | None = None
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.url.startswith("https://"):
            raise ValueError("SUPABASE_URL must use HTTPS")
        if not self.api_key:
            raise ValueError("Supabase API key is required")

    def __repr__(self) -> str:
        return (
            f"SupabaseConfig(url={self.url!r}, api_key='<redacted>', "
            f"access_token={'<redacted>' if self.access_token else None!r}, "
            f"timeout_seconds={self.timeout_seconds})"
        )

    @classmethod
    def from_env(cls, *, user_access_token: str | None = None) -> "SupabaseConfig":
        url = os.environ.get("SUPABASE_URL", "")
        key_name = "SUPABASE_ANON_KEY" if user_access_token else "SUPABASE_SERVICE_ROLE_KEY"
        key = os.environ.get(key_name, "")
        if not url or not key:
            raise ValueError(f"SUPABASE_URL and {key_name} are required")
        return cls(url=url.rstrip("/"), api_key=key, access_token=user_access_token)


class SupabaseRestClient:
    """Call PostgREST and private Storage without importing an SDK."""

    def __init__(self, config: SupabaseConfig) -> None:
        self.config = config

    def select(
        self,
        table: str,
        *,
        filters: Mapping[str, Any],
        columns: str = "*",
        limit: int | None = None,
        query_string: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, str] = {"select": columns}
        for key, value in filters.items():
            if isinstance(value, bool):
                query[key] = f"eq.{'true' if value else 'false'}"
            elif isinstance(value, list):
                query[key] = f"in.({','.join(str(v) for v in value)})"
            else:
                query[key] = f"eq.{value}"
        if limit is not None:
            query["limit"] = str(limit)
        url = f"/rest/v1/{self._identifier(table)}?{urlencode(query)}"
        if query_string:
            url += f"&{query_string}"
        extra = dict(parse_qsl(query_string or "", keep_blank_values=True))
        if limit is not None or "limit" in extra or "offset" in extra:
            return self._json_request("GET", url)
        # PostgREST caps every response (normally at 1000), including a query
        # without a limit. Sync and dedup need every row, not the first page.
        # Ordering makes offset pages deterministic; retain caller ordering
        # and add the primary key as a stable tie breaker.
        order = extra.get("order")
        if not order:
            url += "&order=" + ("kind.asc,record_key.asc" if table == "mcp_oauth_records" else "id.asc")
        elif "id" not in {item.split(".")[0] for item in order.split(",")}:
            # Replace just the caller's order value, preserving repeated
            # date filters and all other query syntax.
            parts = parse_qsl(query_string or "", keep_blank_values=True)
            parts = [(key, value + ",id.asc" if key == "order" else value) for key, value in parts]
            url = f"/rest/v1/{self._identifier(table)}?{urlencode(query)}&{urlencode(parts)}"
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self._json_request("GET", f"{url}&limit=1000&offset={offset}")
            if not isinstance(page, list):
                raise SupabaseError("Supabase select returned an invalid page")
            if not page:
                return rows
            rows.extend(page)
            # Fetch until an empty page even if the server's cap is lower
            # than ours. Any failed later page aborts the whole snapshot.
            offset += len(page)

    def insert(self, table: str, payload: Mapping[str, Any] | list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return self._json_request(
            "POST",
            f"/rest/v1/{self._identifier(table)}",
            payload,
            prefer="return=representation",
        )

    def update(
        self,
        table: str,
        payload: Mapping[str, Any],
        *,
        filters: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        query_parts = {}
        for key, value in filters.items():
            if isinstance(value, bool):
                query_parts[key] = f"eq.{'true' if value else 'false'}"
            elif isinstance(value, list):
                query_parts[key] = f"in.({','.join(str(v) for v in value)})"
            else:
                query_parts[key] = f"eq.{value}"
        query = urlencode(query_parts)
        return self._json_request(
            "PATCH",
            f"/rest/v1/{self._identifier(table)}?{query}",
            payload,
            prefer="return=representation",
        )

    def delete(self, table: str, *, filters: Mapping[str, Any]) -> None:
        if not filters:
            raise ValueError("Refusing to delete without filters")
        query_parts = {}
        for key, value in filters.items():
            if isinstance(value, bool):
                query_parts[key] = f"eq.{'true' if value else 'false'}"
            elif isinstance(value, list):
                query_parts[key] = f"in.({','.join(str(v) for v in value)})"
            else:
                query_parts[key] = f"eq.{value}"
        self._json_request(
            "DELETE",
            f"/rest/v1/{self._identifier(table)}?{urlencode(query_parts)}",
        )

    def delete_returning(self, table: str, *, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Atomically remove matching rows and return only rows actually deleted.

        PostgREST's return=representation maps to SQL DELETE RETURNING. A
        concurrent OAuth redemption therefore cannot read a token twice.
        """
        if not filters:
            raise ValueError("Refusing to delete without filters")
        query = urlencode({key: f"eq.{value}" for key, value in filters.items()})
        return self._json_request(
            "DELETE", f"/rest/v1/{self._identifier(table)}?{query}",
            prefer="return=representation",
        )

    def rpc(self, function: str, payload: Mapping[str, Any]) -> Any:
        return self._json_request(
            "POST",
            f"/rest/v1/rpc/{self._identifier(function)}",
            payload,
        )

    def storage_download(self, bucket: str, object_key: str) -> bytes:
        import time
        return self._request(
            "GET",
            f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_key, safe='/')}?t={time.time()}",
        )

    def storage_upload(
        self,
        bucket: str,
        object_key: str,
        content: bytes,
        *,
        content_type: str,
        upsert: bool,
    ) -> None:
        self._request(
            "POST",
            f"/storage/v1/object/{quote(bucket, safe='')}/{quote(object_key, safe='/')}",
            content,
            headers={"Content-Type": content_type, "x-upsert": str(upsert).lower()},
        )

    def _json_request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | list[Any] | None = None,
        *,
        prefer: str | None = None,
    ) -> Any:
        headers = {"Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        response = self._request(method, path, body, headers=headers)
        return json.loads(response.decode("utf-8")) if response else []

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        token = self.config.access_token or self.config.api_key
        request_headers = {
            "apikey": self.config.api_key,
            "Authorization": f"Bearer {token}",
            **dict(headers or {}),
        }
        request = Request(
            f"{self.config.url.rstrip('/')}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                return response.read()
        except HTTPError as error:
            # PostgREST errors can echo SQL values and credential metadata.
            # Preserve a useful status without propagating response bodies to
            # user-facing domain exceptions or the configuration health route.
            raise SupabaseError(f"Supabase request failed with HTTP {error.code}", status_code=error.code) from error
        except URLError as error:
            raise SupabaseError("Supabase request could not be completed") from error

    @staticmethod
    def _identifier(value: str) -> str:
        if not value.replace("_", "").isalnum():
            raise ValueError("Invalid Supabase identifier")
        return value
