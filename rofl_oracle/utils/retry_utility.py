"""Retry utilities with exponential backoff and circuit breaker pattern.

This module provides robust error handling for RPC calls and transaction submissions.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RetryConfig:
    """Configuration for retry behavior.

    Attributes:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay in seconds between retries
        exponential_base: Base for exponential backoff calculation
        jitter: Whether to add random jitter to prevent thundering herd
    """

    max_attempts: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker pattern.

    Attributes:
        failure_threshold: Number of failures before opening circuit
        success_threshold: Number of successes needed to close circuit from half-open
        timeout: Seconds to wait before attempting half-open state
        window_size: Number of recent calls to track for failure rate
    """

    failure_threshold: int = 5
    success_threshold: int = 2
    timeout: float = 60.0
    window_size: int = 10


class CircuitBreaker:
    """Circuit breaker for preventing cascading failures.

    Tracks failures and prevents calls when failure threshold is exceeded,
    giving the downstream service time to recover.
    """

    def __init__(self, config: CircuitBreakerConfig, name: str = "circuit"):
        """Initialize circuit breaker.

        Args:
            config: Circuit breaker configuration
            name: Name for logging purposes
        """
        self.config = config
        self.name = name
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.recent_results: list[bool] = []

    def record_success(self) -> None:
        """Record a successful call."""
        self.recent_results.append(True)
        if len(self.recent_results) > self.config.window_size:
            self.recent_results.pop(0)

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                logger.info(
                    f"Circuit breaker '{self.name}' closing (recovered)"
                )
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        self.recent_results.append(False)
        if len(self.recent_results) > self.config.window_size:
            self.recent_results.pop(0)

        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.CLOSED:
            failure_rate = self._calculate_failure_rate()
            if (
                self.failure_count >= self.config.failure_threshold
                or failure_rate > 0.5
            ):
                logger.warning(
                    f"Circuit breaker '{self.name}' opening (failure threshold reached)"
                )
                self.state = CircuitState.OPEN
                self.success_count = 0

        elif self.state == CircuitState.HALF_OPEN:
            logger.warning(
                f"Circuit breaker '{self.name}' reopening (half-open test failed)"
            )
            self.state = CircuitState.OPEN
            self.success_count = 0

    def _calculate_failure_rate(self) -> float:
        """Calculate current failure rate from recent results."""
        if not self.recent_results:
            return 0.0
        failures = sum(1 for result in self.recent_results if not result)
        return failures / len(self.recent_results)

    def can_proceed(self) -> bool:
        """Check if calls are allowed based on circuit state."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if (
                self.last_failure_time
                and time.time() - self.last_failure_time >= self.config.timeout
            ):
                logger.info(
                    f"Circuit breaker '{self.name}' attempting half-open"
                )
                self.state = CircuitState.HALF_OPEN
                self.success_count = 0
                return True
            return False

        return True

    def get_status(self) -> dict[str, Any]:
        """Get current circuit breaker status."""
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_rate": self._calculate_failure_rate(),
            "last_failure_time": self.last_failure_time,
        }


async def retry_with_backoff[T](
    func: Callable[..., T],
    *args: Any,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    error_types: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Execute function with exponential backoff retry logic.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: Retry configuration (uses defaults if None)
        circuit_breaker: Optional circuit breaker to check
        error_types: Tuple of exception types to retry on
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function call

    Raises:
        Exception: The last exception if all retries failed
    """
    if config is None:
        config = RetryConfig()

    last_exception: Exception | None = None

    for attempt in range(config.max_attempts):
        if circuit_breaker and not circuit_breaker.can_proceed():
            raise Exception(
                f"Circuit breaker '{circuit_breaker.name}' is OPEN - not attempting call"
            )

        try:
            result = await func(*args, **kwargs)
            if circuit_breaker:
                circuit_breaker.record_success()
            return result

        except error_types as e:
            last_exception = e

            if circuit_breaker:
                circuit_breaker.record_failure()

            if attempt < config.max_attempts - 1:
                delay = min(
                    config.initial_delay * (config.exponential_base**attempt),
                    config.max_delay,
                )

                if config.jitter:
                    import random

                    delay = delay * (0.5 + random.random())

                logger.warning(
                    f"Attempt {attempt + 1}/{config.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {config.max_attempts} attempts failed. Last error: {e}"
                )

    if last_exception:
        raise last_exception
    raise Exception("Retry failed with no exception recorded")


def sync_retry_with_backoff[T](
    func: Callable[..., T],
    *args: Any,
    config: RetryConfig | None = None,
    circuit_breaker: CircuitBreaker | None = None,
    error_types: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Execute synchronous function with exponential backoff retry logic.

    Args:
        func: Synchronous function to execute
        *args: Positional arguments for func
        config: Retry configuration (uses defaults if None)
        circuit_breaker: Optional circuit breaker to check
        error_types: Tuple of exception types to retry on
        **kwargs: Keyword arguments for func

    Returns:
        Result from successful function call

    Raises:
        Exception: The last exception if all retries failed
    """
    if config is None:
        config = RetryConfig()

    last_exception: Exception | None = None

    for attempt in range(config.max_attempts):
        if circuit_breaker and not circuit_breaker.can_proceed():
            raise Exception(
                f"Circuit breaker '{circuit_breaker.name}' is OPEN - not attempting call"
            )

        try:
            result = func(*args, **kwargs)
            if circuit_breaker:
                circuit_breaker.record_success()
            return result

        except error_types as e:
            last_exception = e

            if circuit_breaker:
                circuit_breaker.record_failure()

            if attempt < config.max_attempts - 1:
                delay = min(
                    config.initial_delay * (config.exponential_base**attempt),
                    config.max_delay,
                )

                if config.jitter:
                    import random

                    delay = delay * (0.5 + random.random())

                logger.warning(
                    f"Attempt {attempt + 1}/{config.max_attempts} failed: {e}. "
                    f"Retrying in {delay:.2f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(
                    f"All {config.max_attempts} attempts failed. Last error: {e}"
                )

    if last_exception:
        raise last_exception
    raise Exception("Retry failed with no exception recorded")
