"""Durable local SQL worker. Temporal can call the same fenced execution function."""

import logging
import threading
import time

from metaforge_verification.artifacts import artifact_store
from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.engine import evaluate, registry

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
    started = time.monotonic()
    try:
        request = VerificationRequest.model_validate(row["request"])
        baseline = None
        if request.baseline_id:
            baseline = store.get_baseline(row["tenant"], request.baseline_id)
            if baseline is None or baseline["revoked"] is not None:
                store.finish(row, error="Approved baseline was revoked before execution")
                return True
        report = evaluate(
            row["id"],
            request,
            artifact_store(store.settings, row["tenant"]),
            checks=registry(store.settings.load_plugins),
            cancelled=lambda: not owns_lease(store, row),
        )
        if baseline:
            report.approval = {
                "status": "service_checked_at_admission_and_execution",
                "baseline_id": baseline["id"],
                "fingerprint": baseline["fingerprint"],
                "reviewer": baseline["reviewer"],
                "approved_at": baseline["created"],
            }
        store.finish(
            row, report=report.model_dump(mode="json"), compute_seconds=time.monotonic() - started
        )
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


def owns_lease(store, row):
    current = store.get_internal(row["id"])
    return (
        current is not None
        and current["state"] == "running"
        and current["lease_token"] == row["lease_token"]
        and current["lease_until"] >= time.time()
    )
