"""Provider-neutral content-addressed artifact factory and S3-compatible implementation."""

import hashlib
import io

from metaforge_verification.store import LocalArtifactStore


class S3ArtifactStore:
    def __init__(self, bucket, tenant, client, max_bytes=10 * 1024**2):
        self.bucket, self.client, self.max_bytes = bucket, client, max_bytes
        self.prefix = "verification/" + hashlib.sha256(tenant.encode()).hexdigest() + "/"

    def key(self, artifact_id):
        if len(artifact_id) != 64 or any(c not in "0123456789abcdef" for c in artifact_id):
            raise FileNotFoundError("Invalid artifact ID")
        return self.prefix + artifact_id

    def put(self, data):
        if not data or len(data) > self.max_bytes:
            raise ValueError("Artifact size outside configured limits")
        digest = hashlib.sha256(data).hexdigest()
        self.client.put_object(
            Bucket=self.bucket,
            Key=self.key(digest),
            Body=io.BytesIO(data),
            ContentLength=len(data),
            ContentType="application/octet-stream",
            Metadata={"sha256": digest},
        )
        return digest

    def read(self, artifact_id):
        try:
            result = self.client.get_object(Bucket=self.bucket, Key=self.key(artifact_id))
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise FileNotFoundError("Artifact not found") from None
            raise
        body = result["Body"]
        try:
            data = body.read(self.max_bytes + 1)
        finally:
            body.close()
        if len(data) > self.max_bytes or hashlib.sha256(data).hexdigest() != artifact_id:
            raise FileNotFoundError("Artifact integrity or size violation")
        return data


def artifact_store(settings, tenant):
    if settings.artifact_backend == "local":
        return LocalArtifactStore(settings.artifact_root, tenant, settings.max_upload_bytes)
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2}),
    )
    return S3ArtifactStore(settings.s3_bucket, tenant, client, settings.max_upload_bytes)
