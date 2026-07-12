"""Supabase access-token verification for the cloud API boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import UUID


class AuthenticationError(ValueError):
    """Raised when an API bearer token cannot be trusted."""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    access_token: str = field(repr=False)

    def __repr__(self) -> str:
        return f"AuthenticatedUser(user_id={self.user_id!r}, access_token='<redacted>')"


TokenDecoder = Callable[[str, str, str], Mapping[str, Any]]


class SupabaseJWTVerifier:
    """Verify Supabase JWT signature, issuer, audience, expiry, and subject."""

    def __init__(
        self,
        *,
        issuer: str | None = None,
        audience: str | None = None,
        decoder: TokenDecoder | None = None,
    ) -> None:
        base_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        self.issuer = (issuer or os.environ.get("SUPABASE_JWT_ISSUER") or f"{base_url}/auth/v1").rstrip("/")
        self.audience = audience or os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated")
        if not self.issuer.startswith("https://"):
            raise ValueError("A valid Supabase JWT issuer is required")
        self.jwks_url = f"{self.issuer}/.well-known/jwks.json"
        self._decoder = decoder

    def verify(self, token: str) -> AuthenticatedUser:
        if not token or len(token) > 16_384:
            raise AuthenticationError("A valid bearer token is required")
        try:
            claims = dict(
                self._decoder(token, self.issuer, self.audience)
                if self._decoder
                else self._decode_with_jwks(token)
            )
            user_id = UUID(str(claims["sub"]))
        except AuthenticationError:
            raise
        except Exception as error:
            raise AuthenticationError("Bearer token verification failed") from error
        if claims.get("role") not in {None, "authenticated"}:
            raise AuthenticationError("Bearer token is not an authenticated user token")
        return AuthenticatedUser(user_id=user_id, access_token=token)

    def _decode_with_jwks(self, token: str) -> Mapping[str, Any]:
        try:
            import jwt
        except ImportError as error:
            raise AuthenticationError("PyJWT is required for Supabase authentication") from error
        try:
            key = jwt.PyJWKClient(self.jwks_url).get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except Exception as error:
            raise AuthenticationError("Bearer token verification failed") from error


def bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise AuthenticationError("Authorization header is required")
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not token.strip():
        raise AuthenticationError("Authorization must use the Bearer scheme")
    return token.strip()
