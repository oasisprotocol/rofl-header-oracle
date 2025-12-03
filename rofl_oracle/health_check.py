"""Health check and monitoring endpoints for the ROFL Oracle.

Provides HTTP health endpoints for container orchestration and monitoring.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from aiohttp import web

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    status: HealthStatus
    message: str
    last_check: float
    details: dict[str, Any] | None = None


@dataclass
class SystemHealth:
    """Overall system health status."""

    status: HealthStatus
    uptime_seconds: float
    components: dict[str, ComponentHealth]
    timestamp: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "uptime_seconds": self.uptime_seconds,
            "timestamp": self.timestamp,
            "components": {
                name: {
                    "status": comp.status.value,
                    "message": comp.message,
                    "last_check": comp.last_check,
                    "details": comp.details,
                }
                for name, comp in self.components.items()
            },
        }


class HealthCheckServer:
    """HTTP server for health checks and metrics.

    Provides endpoints for:
    - /health - Overall health status
    - /health/live - Liveness probe (is service running)
    - /health/ready - Readiness probe (is service ready to accept work)
    """

    def __init__(
        self, port: int = 8080, oracle_instance: Any | None = None
    ) -> None:
        """Initialize health check server.

        Args:
            port: Port to listen on
            oracle_instance: Reference to HeaderOracle instance for health checks
        """
        self.port = port
        self.oracle = oracle_instance
        self.app = web.Application()
        self.start_time = time.time()
        self.runner: web.AppRunner | None = None

        self.app.router.add_get("/health", self.health_check)
        self.app.router.add_get("/health/live", self.liveness_check)
        self.app.router.add_get("/health/ready", self.readiness_check)

    async def health_check(self, request: web.Request) -> web.Response:
        """Overall health check endpoint.

        Returns:
            JSON response with system health status
        """
        health = await self._check_system_health()
        status_code = 200 if health.status == HealthStatus.HEALTHY else 503

        return web.json_response(health.to_dict(), status=status_code)

    async def liveness_check(self, request: web.Request) -> web.Response:
        """Liveness probe - is the service running.

        Returns:
            200 if service is alive, 503 if dead
        """
        return web.json_response(
            {
                "status": "alive",
                "uptime_seconds": time.time() - self.start_time,
                "timestamp": time.time(),
            },
            status=200,
        )

    async def readiness_check(self, request: web.Request) -> web.Response:
        """Readiness probe - is the service ready to handle requests.

        Returns:
            200 if ready, 503 if not ready
        """
        health = await self._check_system_health()
        is_ready = health.status in (
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
        )
        status_code = 200 if is_ready else 503

        return web.json_response(
            {
                "status": "ready" if is_ready else "not_ready",
                "health_status": health.status.value,
                "timestamp": time.time(),
            },
            status=status_code,
        )

    async def _check_system_health(self) -> SystemHealth:
        """Check overall system health.

        Returns:
            SystemHealth object with component statuses
        """
        components: dict[str, ComponentHealth] = {}
        current_time = time.time()

        if self.oracle:
            components["source_rpc"] = await self._check_source_rpc()
            components["target_rpc"] = await self._check_target_rpc()

            if (
                hasattr(self.oracle, "event_listener")
                and self.oracle.event_listener
            ):
                components["event_listener"] = self._check_event_listener()

            if hasattr(self.oracle, "block_submitter"):
                components["block_submitter"] = ComponentHealth(
                    status=HealthStatus.HEALTHY,
                    message="Block submitter initialized",
                    last_check=current_time,
                )

        overall_status = self._determine_overall_status(components)

        return SystemHealth(
            status=overall_status,
            uptime_seconds=current_time - self.start_time,
            components=components,
            timestamp=current_time,
        )

    async def _check_source_rpc(self) -> ComponentHealth:
        """Check source RPC connectivity."""
        current_time = time.time()
        try:
            if self.oracle and hasattr(self.oracle, "source_w3"):
                is_connected = self.oracle.source_w3.is_connected()
                if is_connected:
                    block_number = self.oracle.source_w3.eth.block_number
                    return ComponentHealth(
                        status=HealthStatus.HEALTHY,
                        message="Connected",
                        last_check=current_time,
                        details={"latest_block": block_number},
                    )

            return ComponentHealth(
                status=HealthStatus.UNHEALTHY,
                message="Not connected",
                last_check=current_time,
            )

        except Exception as e:
            return ComponentHealth(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                last_check=current_time,
            )

    async def _check_target_rpc(self) -> ComponentHealth:
        """Check target RPC connectivity."""
        current_time = time.time()
        try:
            if self.oracle and hasattr(self.oracle, "contract_utility"):
                is_connected = self.oracle.contract_utility.w3.is_connected()
                if is_connected:
                    return ComponentHealth(
                        status=HealthStatus.HEALTHY,
                        message="Connected",
                        last_check=current_time,
                    )

            return ComponentHealth(
                status=HealthStatus.UNHEALTHY,
                message="Not connected",
                last_check=current_time,
            )

        except Exception as e:
            return ComponentHealth(
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {e}",
                last_check=current_time,
            )

    def _check_event_listener(self) -> ComponentHealth:
        """Check event listener status."""
        current_time = time.time()
        try:
            if self.oracle and hasattr(self.oracle, "event_listener"):
                listener = self.oracle.event_listener
                if hasattr(listener, "is_running") and listener.is_running:
                    return ComponentHealth(
                        status=HealthStatus.HEALTHY,
                        message="Running",
                        last_check=current_time,
                        details={
                            "last_processed_block": getattr(
                                listener, "last_processed_block", None
                            )
                        },
                    )

            return ComponentHealth(
                status=HealthStatus.DEGRADED,
                message="Not running (may be in different mode)",
                last_check=current_time,
            )

        except Exception as e:
            return ComponentHealth(
                status=HealthStatus.DEGRADED,
                message=f"Check failed: {e}",
                last_check=current_time,
            )

    def _determine_overall_status(
        self, components: dict[str, ComponentHealth]
    ) -> HealthStatus:
        """Determine overall health from component statuses.

        Args:
            components: Dictionary of component health statuses

        Returns:
            Overall system health status
        """
        if not components:
            return HealthStatus.HEALTHY

        unhealthy_count = sum(
            1
            for comp in components.values()
            if comp.status == HealthStatus.UNHEALTHY
        )
        degraded_count = sum(
            1
            for comp in components.values()
            if comp.status == HealthStatus.DEGRADED
        )

        if unhealthy_count > 0:
            return HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    async def start(self) -> None:
        """Start the health check server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        logger.info(f"Health check server started on port {self.port}")

    async def stop(self) -> None:
        """Stop the health check server."""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Health check server stopped")
