from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol

import jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from opspilot.workflow.models import Actor

Role = Literal[
    "investigator",
    "remediation_proposer",
    "remediation_approver",
    "remediation_executor",
    "auditor",
    "admin",
]

_KNOWN_ROLES: frozenset[str] = frozenset(
    {
        "investigator",
        "remediation_proposer",
        "remediation_approver",
        "remediation_executor",
        "auditor",
        "admin",
    }
)


class AuthenticationError(RuntimeError):
    """A deliberately detail-free authentication failure."""


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(pattern=r"^[a-zA-Z0-9_.:@/-]{3,160}$")
    display_name: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{2,63}$")
    actor_type: Literal["human", "service"]
    roles: frozenset[Role] = Field(min_length=1, max_length=6)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, roles: frozenset[Role]) -> frozenset[Role]:
        if not set(roles) <= _KNOWN_ROLES:
            raise ValueError("token contains an unsupported role")
        return roles

    def actor(self) -> Actor:
        return Actor(
            actor_type=self.actor_type,
            actor_id=self.subject,
            display_name=self.display_name,
        )

    def has_any_role(self, required: frozenset[Role]) -> bool:
        return "admin" in self.roles or bool(self.roles & required)


class Authenticator(Protocol):
    def authenticate(self, token: str) -> Principal: ...


class JWKSAuthenticator:
    """Validate asymmetric OIDC access tokens against a cached JWKS endpoint."""

    def __init__(
        self,
        *,
        jwks_url: str,
        issuer: str,
        audience: str,
        algorithms: tuple[str, ...] = ("RS256",),
        cache_ttl_seconds: int = 300,
        request_timeout_seconds: float = 5.0,
    ) -> None:
        if not jwks_url.startswith("https://"):
            raise ValueError("JWKS URL must use HTTPS")
        if not issuer or not audience:
            raise ValueError("token issuer and audience are required")
        if not algorithms or any(algorithm not in {"RS256", "ES256"} for algorithm in algorithms):
            raise ValueError("only RS256 and ES256 token algorithms are supported")
        self._issuer = issuer
        self._audience = audience
        self._algorithms = algorithms
        self._client = jwt.PyJWKClient(
            jwks_url,
            cache_jwk_set=True,
            lifespan=cache_ttl_seconds,
            cache_keys=False,
            timeout=request_timeout_seconds,
        )

    def authenticate(self, token: str) -> Principal:
        if not token or len(token) > 16_384:
            raise AuthenticationError("invalid_token")
        try:
            signing_key = self._client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=list(self._algorithms),
                audience=self._audience,
                issuer=self._issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            return self._principal_from_claims(claims)
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("invalid_token") from exc

    @staticmethod
    def _principal_from_claims(claims: Mapping[str, object]) -> Principal:
        raw_roles = claims.get("roles")
        if not isinstance(raw_roles, list) or not all(isinstance(role, str) for role in raw_roles):
            raise ValueError("roles claim must be a string array")
        display_name = claims.get("name", claims.get("sub"))
        return Principal.model_validate(
            {
                "subject": claims["sub"],
                "display_name": display_name,
                "tenant_id": claims["tenant_id"],
                "actor_type": claims["actor_type"],
                "roles": raw_roles,
            }
        )


class StaticTokenAuthenticator:
    """Credential-free deterministic adapter used only through test dependency overrides."""

    def __init__(self, tokens: Mapping[str, Principal]) -> None:
        self._tokens = dict(tokens)

    def authenticate(self, token: str) -> Principal:
        try:
            return self._tokens[token]
        except KeyError as exc:
            raise AuthenticationError("invalid_token") from exc
