"""Optional Temporal deployment. Does not import the MetaForge application.

SQL submissions are the durable dispatch outbox. Deterministic workflow IDs
make dispatch replay safe. Shared artifact storage must be available to activities.
"""

import asyncio
import os
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Worker

TASK_QUEUE = "metaforge-verification-v1"


@activity.defn
async def evaluate_job(job_id: str) -> str:
    # Keep heavy imports outside the workflow sandbox.
    from metaforge_verification.config import Settings
    from metaforge_verification.store import Store
    from metaforge_verification.worker import run_once

    store = Store(Settings.from_env())
    try:
        existing = store.get_internal(job_id)
        if existing is None:
            raise ValueError("Unknown internal job")
        if existing["state"] in {"completed", "failed", "canceled"}:
            return existing["state"]
        await asyncio.to_thread(run_once, store, job_id)
        current = store.get_internal(job_id)
        if current["state"] in {"queued", "running"}:
            raise RuntimeError("Attempt lease is still held; retry after lease expiration")
        return current["state"]
    finally:
        store.engine.dispose()


@workflow.defn
class VerificationWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> str:
        return await workflow.execute_activity(
            evaluate_job,
            job_id,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(seconds=30),
                maximum_attempts=20,
            ),
        )


async def connect():
    return await Client.connect(
        os.getenv("VERIFICATION_TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("VERIFICATION_TEMPORAL_NAMESPACE", "default"),
    )


async def serve():
    async with Worker(
        await connect(),
        task_queue=TASK_QUEUE,
        workflows=[VerificationWorkflow],
        activities=[evaluate_job],
        max_concurrent_activities=2,
    ):
        await asyncio.Event().wait()


async def dispatch():
    from sqlalchemy import select

    from metaforge_verification.config import Settings
    from metaforge_verification.store import Store, jobs

    store, client = Store(Settings.from_env()), await connect()
    try:
        while True:
            with store.engine.connect() as conn:
                pending = (
                    conn.execute(
                        select(jobs.c.id)
                        .where(jobs.c.state == "queued")
                        .order_by(jobs.c.created)
                        .limit(100)
                    )
                    .scalars()
                    .all()
                )
            for job_id in pending:
                try:
                    await client.start_workflow(
                        VerificationWorkflow.run,
                        job_id,
                        id=f"verification-{job_id}",
                        task_queue=TASK_QUEUE,
                    )
                except WorkflowAlreadyStartedError:
                    pass
            await asyncio.sleep(2)
    finally:
        store.engine.dispose()
