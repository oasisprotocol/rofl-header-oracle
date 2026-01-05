"""Structured logging utilities for the ROFL Oracle.

Provides JSON-formatted logging and performance timing decorators.
"""

import asyncio
import functools
import json
import logging
import time
import types
from collections.abc import Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Outputs logs in JSON format for easier parsing and analysis.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra"):
            log_data["extra"] = record.extra

        return json.dumps(log_data)


def setup_structured_logging(
    level: str = "INFO", use_json: bool = False
) -> None:
    """Configure structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: Whether to use JSON formatting
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if use_json:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    logging.getLogger("web3").setLevel(logging.WARNING)
    logging.getLogger("web3.providers").setLevel(logging.WARNING)
    logging.getLogger("web3.RequestManager").setLevel(logging.WARNING)
    logging.getLogger("web3.manager").setLevel(logging.WARNING)
    logging.getLogger("web3._utils").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def timed[T](func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to time function execution and log performance.

    Works with both sync and async functions.

    Args:
        func: Function to time

    Returns:
        Wrapped function that logs execution time
    """
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start_time
                logger.debug(
                    f"{func.__name__} completed in {elapsed:.3f}s",
                    extra={
                        "function": func.__name__,
                        "duration_seconds": elapsed,
                    },
                )
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start_time
                logger.error(
                    f"{func.__name__} failed after {elapsed:.3f}s: {e}",
                    extra={
                        "function": func.__name__,
                        "duration_seconds": elapsed,
                        "error": str(e),
                    },
                )
                raise

        return async_wrapper
    else:

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start_time
                logger.debug(
                    f"{func.__name__} completed in {elapsed:.3f}s",
                    extra={
                        "function": func.__name__,
                        "duration_seconds": elapsed,
                    },
                )
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start_time
                logger.error(
                    f"{func.__name__} failed after {elapsed:.3f}s: {e}",
                    extra={
                        "function": func.__name__,
                        "duration_seconds": elapsed,
                        "error": str(e),
                    },
                )
                raise

        return sync_wrapper


class PerformanceTimer:
    """Context manager for timing code blocks.

    Example:
        with PerformanceTimer("fetch_block"):
            block = fetch_block(123)
    """

    def __init__(self, operation_name: str, log_level: int = logging.DEBUG):
        """Initialize performance timer.

        Args:
            operation_name: Name of the operation being timed
            log_level: Log level for timing messages
        """
        self.operation_name = operation_name
        self.log_level = log_level
        self.start_time: float = 0

    def __enter__(self) -> "PerformanceTimer":
        """Start timing."""
        self.start_time = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop timing and log result."""
        elapsed = time.perf_counter() - self.start_time

        if exc_type is None:
            logger.log(
                self.log_level,
                f"{self.operation_name} completed in {elapsed:.3f}s",
                extra={
                    "operation": self.operation_name,
                    "duration_seconds": elapsed,
                    "success": True,
                },
            )
        else:
            logger.error(
                f"{self.operation_name} failed after {elapsed:.3f}s: {exc_val}",
                extra={
                    "operation": self.operation_name,
                    "duration_seconds": elapsed,
                    "success": False,
                    "error": str(exc_val),
                },
            )


class AsyncPerformanceTimer:
    """Async context manager for timing async code blocks.

    Example:
        async with AsyncPerformanceTimer("fetch_block"):
            block = await fetch_block(123)
    """

    def __init__(self, operation_name: str, log_level: int = logging.DEBUG):
        """Initialize async performance timer.

        Args:
            operation_name: Name of the operation being timed
            log_level: Log level for timing messages
        """
        self.operation_name = operation_name
        self.log_level = log_level
        self.start_time: float = 0

    async def __aenter__(self) -> "AsyncPerformanceTimer":
        """Start timing."""
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Stop timing and log result."""
        elapsed = time.perf_counter() - self.start_time

        if exc_type is None:
            logger.log(
                self.log_level,
                f"{self.operation_name} completed in {elapsed:.3f}s",
                extra={
                    "operation": self.operation_name,
                    "duration_seconds": elapsed,
                    "success": True,
                },
            )
        else:
            logger.error(
                f"{self.operation_name} failed after {elapsed:.3f}s: {exc_val}",
                extra={
                    "operation": self.operation_name,
                    "duration_seconds": elapsed,
                    "success": False,
                    "error": str(exc_val),
                },
            )
