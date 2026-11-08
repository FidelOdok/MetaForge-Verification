"""Durable local SQL worker. Temporal can call the same fenced execution function."""

import logging
import threading
import time

from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.engine import evaluate, registry
from metaforge_verification.store import LocalArtifactStore

logger = logging.getLogger(__name__)


def run_once(store, job_id=None):
    row = store.claim(job_id)
    if row is None:
        return False
    stopped = threading.Event()

    def keep_lease():
        while not stopped.wait(max(0.1, store.settings.lease_seconds / 3)):
            if not store.heartbeat(row):
                return

    heartbeat = threading.Thread(target=keep_lease, daemon=True)
    heartbeat.start()
    try:
        request = VerificationRequest.model_validate(row["request"])
        report = evaluate(
            row["id"],
            request,
            LocalArtifactStore(store.settings.artifact_root, row["tenant"]),
            checks=registry(store.settings.load_plugins),
        )
        store.finish(row, report=report.model_dump(mode="json"))
    except Exception:
        # No arbitrary adapter exception contents in customer-facing responses.
        logger.exception("Verification attempt failed: %s", row["id"])
        store.finish(row, error="Execution failed; inspect operator logs using verification ID")
    finally:
        stopped.set()
        heartbeat.join(timeout=2)
    return True


def serve(store):
    while True:
        if not run_once(store):
            time.sleep(0.5)
