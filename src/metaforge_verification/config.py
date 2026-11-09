import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = "sqlite:///./data/verification.db"
    artifact_root: Path = Path("./data/artifacts")
    artifact_backend: str = "local"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    auth_mode: str = "tokens"
    tokens: dict[str, str] = field(default_factory=dict)
    review_tokens: dict[str, str] = field(default_factory=dict)
    require_approved_baseline: bool = False
    webhook_destinations: dict[str, dict[str, str]] = field(default_factory=dict)
    lease_seconds: int = 120
    max_attempts: int = 3
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pending_per_tenant: int = 20
    max_running_jobs: int = 2
    max_running_per_tenant: int = 1
    load_plugins: bool = False

    def validate(self):
        if self.auth_mode not in {"tokens", "local"}:
            raise ValueError("Unknown auth mode")
        if self.artifact_backend not in {"local", "s3"}:
            raise ValueError("Unknown artifact backend")
        if self.artifact_backend == "s3" and not self.s3_bucket:
            raise ValueError("S3 artifact storage requires a bucket")
        if self.s3_endpoint_url:
            from urllib.parse import urlsplit

            endpoint = urlsplit(self.s3_endpoint_url)
            if (
                endpoint.username
                or endpoint.password
                or (
                    endpoint.scheme != "https"
                    and endpoint.hostname not in {"localhost", "127.0.0.1"}
                )
            ):
                raise ValueError(
                    "S3 endpoint requires HTTPS (except explicit loopback development)"
                )
        if self.auth_mode == "tokens" and (
            not (self.tokens or self.review_tokens)
            or any(
                len(k) < 16 or not isinstance(v, str) or not v
                for k, v in (self.tokens | self.review_tokens).items()
            )
        ):
            raise ValueError("VERIFICATION_TOKENS must map >=16-character tokens to tenant IDs")
        if set(self.tokens) & set(self.review_tokens):
            raise ValueError("Submitter and reviewer tokens must be distinct")
        from urllib.parse import urlsplit

        for destination in self.webhook_destinations.values():
            url = urlsplit(destination.get("url", ""))
            if (
                url.scheme != "https"
                or len(destination.get("url", "")) > 2048
                or not url.hostname
                or url.username
                or url.password
                or url.fragment
                or len(destination.get("secret", "")) < 32
            ):
                raise ValueError(
                    "Operator webhook destinations require HTTPS and >=32-character secrets"
                )
        if self.lease_seconds < 1 or self.max_attempts < 1:
            raise ValueError("Invalid worker limits")
        if min(self.max_running_jobs, self.max_running_per_tenant, self.max_pending_per_tenant) < 1:
            raise ValueError("Execution/admission limits must be positive")
        return self

    @classmethod
    def from_env(cls):
        return cls(
            database_url=os.getenv("VERIFICATION_DATABASE_URL", cls.database_url),
            artifact_root=Path(os.getenv("VERIFICATION_ARTIFACT_ROOT", "./data/artifacts")),
            artifact_backend=os.getenv("VERIFICATION_ARTIFACT_BACKEND", "local"),
            s3_bucket=os.getenv("VERIFICATION_S3_BUCKET"),
            s3_endpoint_url=os.getenv("VERIFICATION_S3_ENDPOINT_URL"),
            s3_region=os.getenv("VERIFICATION_S3_REGION", "us-east-1"),
            auth_mode=os.getenv("VERIFICATION_AUTH_MODE", "tokens"),
            tokens=json.loads(os.getenv("VERIFICATION_TOKENS", "{}")),
            review_tokens=json.loads(os.getenv("VERIFICATION_REVIEW_TOKENS", "{}")),
            require_approved_baseline=os.getenv("VERIFICATION_REQUIRE_APPROVED_BASELINE") == "true",
            webhook_destinations=json.loads(os.getenv("VERIFICATION_WEBHOOK_DESTINATIONS", "{}")),
            max_running_jobs=int(os.getenv("VERIFICATION_MAX_RUNNING_JOBS", "2")),
            max_running_per_tenant=int(os.getenv("VERIFICATION_MAX_RUNNING_PER_TENANT", "1")),
            load_plugins=os.getenv("VERIFICATION_LOAD_PLUGINS") == "true",
        ).validate()
