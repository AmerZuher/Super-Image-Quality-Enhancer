"""Temporal worker processes.

* ``cpu`` polls ``siqe-cpu``: all workflows plus CPU activities (imaging, bookkeeping).
* ``gpu`` polls ``siqe-gpu``: GPU activities, strictly one at a time. Running a single GPU
  activity per device is what keeps two jobs from fighting over VRAM; parallelism comes from
  batching inside the activity, not from concurrency.
"""

import asyncio
import os
import signal
from collections.abc import Callable
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from siqe.activities.ai import discard_run_files, register_result, run_background, run_model
from siqe.activities.assets import export_rendition, mark_asset_failed, mark_rendition_failed, prepare_asset
from siqe.activities.jobs import update_job
from siqe.activities.models import install_model, mark_model_failed
from siqe.activities.selftest import cpu_probe, gpu_probe
from siqe.core.config import CPU_TASK_QUEUE, GPU_TASK_QUEUE, get_settings
from siqe.core.logging import configure_logging, get_logger
from siqe.db.session import dispose_engine
from siqe.orchestration.client import connect
from siqe.storage.store import get_store
from siqe.system.resources import cpu_info
from siqe.workers.heartbeat import HeartbeatLoop, WorkerKind
from siqe.workflows.ai import AiRunWorkflow
from siqe.workflows.assets import ExportWorkflow, IngestAssetWorkflow
from siqe.workflows.models import ModelInstallWorkflow
from siqe.workflows.selftest import SelfTestWorkflow

log = get_logger(__name__)

WORKFLOWS = [SelfTestWorkflow, IngestAssetWorkflow, ExportWorkflow, ModelInstallWorkflow, AiRunWorkflow]
CPU_ACTIVITIES: list[Callable[..., Any]] = [
    update_job,
    cpu_probe,
    prepare_asset,
    export_rendition,
    mark_asset_failed,
    mark_rendition_failed,
    install_model,
    mark_model_failed,
    run_background,
    register_result,
    discard_run_files,
]
GPU_ACTIVITIES: list[Callable[..., Any]] = [gpu_probe, run_model]


def build_worker(client: Client, kind: WorkerKind) -> Worker:
    settings = get_settings()
    if kind == "cpu":
        cores = settings.cpu_concurrency or max(1, int(cpu_info().usable_cores))
        return Worker(
            client,
            task_queue=CPU_TASK_QUEUE,
            workflows=WORKFLOWS,
            activities=CPU_ACTIVITIES,
            max_concurrent_activities=cores,
            identity=f"cpu@{os.uname().nodename}",
        )
    return Worker(
        client,
        task_queue=GPU_TASK_QUEUE,
        activities=GPU_ACTIVITIES,
        max_concurrent_activities=1,
        identity=f"gpu@{os.uname().nodename}",
    )


async def run_worker(kind: WorkerKind) -> None:
    settings = get_settings()
    configure_logging(settings)
    log.info("worker.starting", kind=kind, version=settings.version)
    if kind == "cpu":
        removed = await asyncio.to_thread(get_store().clean_tmp)
        if removed:
            log.info("worker.tmp_cleaned", removed=removed)

    client = await connect(settings)
    worker = build_worker(client, kind)
    heartbeat = HeartbeatLoop(kind, settings)
    heartbeat.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    try:
        async with worker:
            log.info("worker.ready", kind=kind, task_queue=worker.task_queue)
            await stop.wait()
            log.info("worker.stopping", kind=kind)
    finally:
        await heartbeat.stop()
        await dispose_engine()
