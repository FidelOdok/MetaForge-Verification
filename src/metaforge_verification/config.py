import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = "sqlite:///./data/verification.db"
    artifact_root: Path = Path("./data/artifacts")
    auth_mode: str = "tokens"
    tokens: dict[str, str] = field(default_factory=dict)
    lease_seconds: int = 120
    max_attempts: int = 3
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pending_per_tenant: int = 20
    load_plugins: bool = False

    def validate(self):
        if self.auth_mode not in {"tokens", "local"}:
            raise ValueError("Unknown auth mode")
        if self.auth_mode == "tokens" and (
            not self.tokens
            or any(len(k) < 16 or not isinstance(v, str) or not v for k, v in self.tokens.items())
        ):
            raise ValueError("VERIFICATION_TOKENS must map >=16-character tokens to tenant IDs")
        if self.lease_seconds < 1 or self.max_attempts < 1:
            raise ValueError("Invalid worker limits")
        return self

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.getenv("VERIFICATION_DATABASE_URL", cls.database_url),
            artifact_root=Path(os.getenv("VERIFICATION_ARTIFACT_ROOT", "./data/artifacts")),
            auth_mode=os.getenv("VERIFICATION_AUTH_MODE", "tokens"),
            tokens=json.loads(os.getenv("VERIFICATION_TOKENS", "{}")),
            load_plugins=os.getenv("VERIFICATION_LOAD_PLUGINS") == "true",
        ).validate()
