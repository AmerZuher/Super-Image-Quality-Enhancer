"""Workflows must pass Temporal's determinism sandbox; this catches bad imports early."""

from temporalio.worker import Replayer

from siqe.workers.runner import WORKFLOWS


def test_workflows_pass_sandbox_validation() -> None:
    Replayer(workflows=WORKFLOWS)
