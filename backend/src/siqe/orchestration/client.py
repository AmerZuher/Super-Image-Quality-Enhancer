"""Connecting to Temporal and making sure our namespace exists."""

import asyncio
from datetime import timedelta

from google.protobuf.duration_pb2 import Duration
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, RegisterNamespaceRequest
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from siqe.core.config import Settings
from siqe.core.errors import ServiceUnavailableError
from siqe.core.logging import get_logger

log = get_logger(__name__)


async def connect(settings: Settings, *, attempts: int | None = None, namespace: str | None = None) -> Client:
    """Connect with exponential backoff. ``attempts=None`` keeps trying (workers at startup)."""
    delay = 1.0
    attempt = 0
    while True:
        attempt += 1
        try:
            return await Client.connect(
                settings.temporal_address, namespace=namespace or settings.temporal_namespace
            )
        except Exception as exc:
            if attempts is not None and attempt >= attempts:
                raise
            log.info("temporal.waiting", address=settings.temporal_address, error=str(exc), retry_in=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)


async def ensure_namespace(
    client: Client, namespace: str, retention_days: int, wait_seconds: float = 60
) -> None:
    """Register the namespace if it does not exist, then wait until it is usable."""
    try:
        await client.workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=namespace,
                description="SIQE Studio",
                workflow_execution_retention_period=Duration(
                    seconds=int(timedelta(days=retention_days).total_seconds())
                ),
            )
        )
        log.info("temporal.namespace_registered", namespace=namespace)
    except RPCError as exc:
        if exc.status != RPCStatusCode.ALREADY_EXISTS:
            raise
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        try:
            await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=namespace))
            return
        except RPCError:
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(1)


class TemporalGateway:
    """Lazily connected client for the API. Failing to connect becomes a typed 503."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def client(self) -> Client:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                try:
                    self._client = await connect(self._settings, attempts=2)
                except Exception as exc:
                    raise ServiceUnavailableError(
                        "temporal.unavailable",
                        "The job engine (Temporal) is not reachable, so jobs can't start right now.",
                        title="Job engine unavailable",
                        fix="Run `docker compose ps` and check that the temporal container is healthy.",
                    ) from exc
        return self._client

    async def healthy(self) -> bool:
        try:
            client = await self.client()
            return bool(await client.service_client.check_health())
        except Exception:
            return False
