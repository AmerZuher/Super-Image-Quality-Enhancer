import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from siqe.activities.flows import (
        ItemFinish,
        StepCall,
        flow_ai_cpu,
        flow_ai_gpu,
        flow_condition,
        flow_edit,
        flow_item_finish,
        flow_item_start,
        flow_next_items,
        flow_output,
        flow_run_finish,
        flow_run_start,
    )
    from siqe.core.config import CPU_TASK_QUEUE, GPU_TASK_QUEUE
    from siqe.flows.catalog import NODES_BY_TYPE
    from siqe.flows.document import input_node, node_by_id, steps_after

QUICK = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))
STEP = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=3))
# A watched run waits this long for more images before it finishes.
WATCH_IDLE = timedelta(seconds=60)
# Start afresh (continue-as-new) after this many images, to keep the event history small.
PAGE_LIMIT = 200


def _failure(exc: BaseException) -> dict[str, Any]:
    cause: BaseException | None = exc
    while isinstance(cause, ActivityError | ChildWorkflowError) and cause.cause is not None:
        cause = cause.cause
    if isinstance(cause, ApplicationError):
        details = cause.details[0] if cause.details else {}
        fix = details.get("fix") if isinstance(details, dict) else None
        return {"code": cause.type or "flow.step_failed", "message": cause.message, "fix": fix}
    return {"code": "flow.step_failed", "message": str(cause or exc)}


@workflow.defn
class FlowItemWorkflow:
    """Walk one image through a flow, block by block; a failure stops only this image."""

    def __init__(self) -> None:
        self._outputs = 0
        self._doc: dict[str, Any] = {}
        self._run_id = ""
        self._item_id = ""
        self._dry_run = False

    async def _step(self, node: dict[str, Any], src: str | None, size: tuple[int, int], key: str) -> None:
        spec = NODES_BY_TYPE[node["type"]]
        call = StepCall(
            run_id=self._run_id,
            item_id=self._item_id,
            node_id=node["id"],
            node_type=node["type"],
            params=node.get("params", {}),
            label=node.get("label") or spec.label,
            src=src,
            width=size[0],
            height=size[1],
            key=key,
            dry_run=self._dry_run,
        )
        port: str | None = "out"
        if spec.category == "condition":
            decision: dict[str, Any] = await workflow.execute_activity(
                flow_condition,
                call,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=QUICK,
            )
            port = decision["port"]  # None stops this image here; the step records why
        elif spec.transforms:
            if spec.category == "ai":
                activity = flow_ai_gpu if spec.queue == "gpu" else flow_ai_cpu
                queue = GPU_TASK_QUEUE if spec.queue == "gpu" else CPU_TASK_QUEUE
                timeout = timedelta(hours=2)
            else:
                activity, queue, timeout = flow_edit, CPU_TASK_QUEUE, timedelta(minutes=30)
            result: dict[str, Any] = await workflow.execute_activity(
                activity,
                call,
                task_queue=queue,
                start_to_close_timeout=timeout,
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=STEP,
            )
            src, size = result["path"], (result["width"], result["height"])
        else:  # outputs
            await workflow.execute_activity(
                flow_output,
                call,
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=STEP,
            )
            self._outputs += 1
        if port is None:
            return
        for index, target in enumerate(steps_after(self._doc, node["id"], port)):
            await self._step(node_by_id(self._doc, target), src, size, f"{key}.{index}")

    @workflow.run
    async def run(self, run_id: str, item_id: str, document: dict[str, Any], dry_run: bool) -> str:
        self._doc, self._run_id, self._item_id, self._dry_run = document, run_id, item_id, dry_run
        state, error = "done", None
        try:
            info: dict[str, Any] = await workflow.execute_activity(
                flow_item_start,
                args=[run_id, item_id],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=QUICK,
            )
            start = input_node(document)
            for index, target in enumerate(steps_after(document, start)):
                await self._step(
                    node_by_id(document, target), None, (info["width"], info["height"]), f"s{index}"
                )
            if self._outputs == 0:
                state = "skipped"
        except asyncio.CancelledError:
            raise
        except (ActivityError, ChildWorkflowError, ApplicationError) as exc:
            state, error = "failed", _failure(exc)
        await workflow.execute_activity(
            flow_item_finish,
            ItemFinish(run_id, item_id, state, error),
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=QUICK,
        )
        return state


@workflow.defn
class FlowRunWorkflow:
    """Run a flow over its images, a few at a time; watched runs wait for more before finishing."""

    def __init__(self) -> None:
        self._more = False

    @workflow.signal
    def more(self) -> None:
        self._more = True

    @workflow.run
    async def run(self, run_id: str, handled: int = 0, concurrency: int = 4) -> dict[str, Any]:
        info: dict[str, Any] = await workflow.execute_activity(
            flow_run_start,
            run_id,
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=QUICK,
        )
        watch, dry_run, document = info["kind"] == "watch", bool(info["dry_run"]), info["document"]
        concurrency = max(1, min(32, concurrency))
        try:
            while True:
                self._more = False
                items: list[str] = await workflow.execute_activity(
                    flow_next_items,
                    args=[run_id, concurrency],
                    task_queue=CPU_TASK_QUEUE,
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=QUICK,
                )
                if not items:
                    if not watch:
                        break
                    try:
                        await workflow.wait_condition(lambda: self._more, timeout=WATCH_IDLE)
                    except TimeoutError:
                        break
                    continue
                await asyncio.gather(
                    *(
                        workflow.execute_child_workflow(
                            FlowItemWorkflow.run,
                            args=[run_id, item, document, dry_run],
                            id=f"flowitem-{item}",
                            task_queue=CPU_TASK_QUEUE,
                            parent_close_policy=ParentClosePolicy.REQUEST_CANCEL,
                        )
                        for item in items
                    ),
                    return_exceptions=True,  # each image records its own failure; keep going
                )
                handled += len(items)
                if handled >= PAGE_LIMIT and not self._more:
                    workflow.continue_as_new(args=[run_id, 0, concurrency])
        except asyncio.CancelledError:
            await workflow.execute_activity(
                flow_run_finish,
                args=[run_id, True],
                task_queue=CPU_TASK_QUEUE,
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=QUICK,
            )
            raise
        result: dict[str, Any] = await workflow.execute_activity(
            flow_run_finish,
            args=[run_id, False],
            task_queue=CPU_TASK_QUEUE,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=QUICK,
        )
        return result
