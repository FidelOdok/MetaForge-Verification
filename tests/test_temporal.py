import asyncio

import pytest

pytest.importorskip("temporalio")


def test_workflow_definition_prepares_in_temporal_sandbox():
    from temporalio import workflow
    from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

    from metaforge_verification.temporal_runtime import VerificationWorkflow

    async def prepare():
        SandboxedWorkflowRunner().prepare_workflow(
            workflow._Definition.must_from_class(VerificationWorkflow)
        )

    asyncio.run(prepare())
