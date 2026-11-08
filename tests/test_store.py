import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import update

from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.store import Store, jobs


def test_duplicate_concurrent_submissions_accept_one(settings, payload):
    store = Store(settings)
    request = VerificationRequest.model_validate(payload)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: store.submit("a", "same", request), range(16)))
    assert len({row["id"] for row, _ in results}) == 1
    assert sum(created for _, created in results) == 1


def test_stale_attempt_cannot_overwrite_reclaimed_result(settings, payload):
    store = Store(settings)
    row, _ = store.submit("a", "one", VerificationRequest.model_validate(payload))
    first = store.claim()
    with store.engine.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.id == row["id"]).values(lease_until=time.time() - 1))
    second = store.claim()
    assert second["attempt"] == 2
    assert not store.finish(first, report={"old": True})
    assert store.finish(second, report={"new": True})
    assert store.get("a", row["id"])["report"] == {"new": True}


def test_cancel_invalidates_running_lease(settings, payload):
    store = Store(settings)
    row, _ = store.submit("a", "one", VerificationRequest.model_validate(payload))
    attempt = store.claim()
    store.cancel("a", row["id"])
    assert not store.heartbeat(attempt)
    assert not store.finish(attempt, report={})


def test_expired_attempt_limit_reaches_terminal_failure(settings, payload):
    settings.max_attempts = 1
    store = Store(settings)
    row, _ = store.submit("a", "one", VerificationRequest.model_validate(payload))
    store.claim()
    with store.engine.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.id == row["id"]).values(lease_until=0))
    assert store.claim() is None
    assert store.get("a", row["id"])["state"] == "failed"


def test_one_hundred_tenant_namespaces_do_not_share_jobs(settings, payload):
    store = Store(settings)
    request = VerificationRequest.model_validate(payload)
    accepted = [store.submit(f"organization-{i}", "same-key", request)[0] for i in range(100)]
    assert len({r["id"] for r in accepted}) == 100
    for i, row in enumerate(accepted):
        assert store.get(f"organization-{i}", row["id"]) is not None
        assert store.get(f"organization-{(i + 1) % 100}", row["id"]) is None
