"""Local/bootstrap identity. Cloud code may inject an Authenticator, not vice versa."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    permissions: frozenset[str] = frozenset({"submit", "read"})
    actor_id: str = "external"


class Authenticator(Protocol):
    def authenticate(self, authorization: str | None) -> Principal | None: ...


class TokenAuthenticator:
    def __init__(self, settings):
        self.local = settings.auth_mode == "local"
        self.tokens = [
            (hashlib.sha256(token.encode()).digest(), tenant, frozenset({"submit", "read"}))
            for token, tenant in settings.tokens.items()
        ] + [
            (hashlib.sha256(token.encode()).digest(), tenant, frozenset({"review", "read"}))
            for token, tenant in settings.review_tokens.items()
        ]

    def authenticate(self, authorization):
        if self.local:
            return Principal("local", frozenset({"submit", "review", "read"}), "local")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        digest = hashlib.sha256(token.encode()).digest()
        matched = None
        for expected, tenant, permissions in self.tokens:
            if hmac.compare_digest(expected, digest):
                matched = Principal(tenant, permissions, digest.hex()[:16])
        return matched
