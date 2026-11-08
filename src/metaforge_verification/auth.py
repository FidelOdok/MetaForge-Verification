"""Local/bootstrap identity. Cloud code may inject an Authenticator, not vice versa."""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Principal:
    tenant_id: str


class Authenticator(Protocol):
    def authenticate(self, authorization: str | None) -> Principal | None: ...


class TokenAuthenticator:
    def __init__(self, settings):
        self.local = settings.auth_mode == "local"
        self.tokens = [
            (hashlib.sha256(token.encode()).digest(), tenant)
            for token, tenant in settings.tokens.items()
        ]

    def authenticate(self, authorization):
        if self.local:
            return Principal("local")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        digest = hashlib.sha256(token.encode()).digest()
        matched = None
        for expected, tenant in self.tokens:
            if hmac.compare_digest(expected, digest):
                matched = Principal(tenant)
        return matched
