"""Shared HTTP client for network-based acquisition adapters.

Wraps :class:`httpx.Client` with explicit connect/read timeouts, an identifying User-Agent and
retry with exponential backoff (plus jitter) for transient failures: transport errors, HTTP 429
and HTTP 5xx. Other 4xx responses fail immediately because retrying them cannot succeed.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from retail_data_platform.config import Settings, SourceMode
from retail_data_platform.observability import get_logger

log = get_logger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class AcquisitionError(RuntimeError):
    """Raised when a source cannot be fetched after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryingHttpClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        max_retries: int,
        backoff_base_seconds: float,
        backoff_max_seconds: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._backoff_base = backoff_base_seconds
        self._backoff_max = backoff_max_seconds
        self._sleep = sleep
        self.request_count = 0

    def backoff_delay(self, attempt: int, retry_after: str | None = None) -> float:
        """Delay before retry ``attempt`` (1-based): Retry-After if given, else exp. + jitter."""
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), self._backoff_max)
        exponential = self._backoff_base * (2 ** (attempt - 1))
        jitter = random.uniform(0, self._backoff_base)  # noqa: S311 - not used for security
        return float(min(self._backoff_max, exponential + jitter))

    def get(self, url: str, params: Mapping[str, Any] | None = None) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            self.request_count += 1
            try:
                response = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt > self._max_retries:
                    raise AcquisitionError(
                        f"GET {url} failed after {attempt} attempts: {type(exc).__name__}: {exc}"
                    ) from exc
                delay = self.backoff_delay(attempt)
                log.warning(
                    "http.retry",
                    url=url,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    exception_type=type(exc).__name__,
                )
                self._sleep(delay)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt <= self._max_retries:
                delay = self.backoff_delay(attempt, response.headers.get("Retry-After"))
                log.warning(
                    "http.retry",
                    url=url,
                    attempt=attempt,
                    status_code=response.status_code,
                    delay_seconds=round(delay, 2),
                )
                self._sleep(delay)
                continue

            if response.is_error:
                raise AcquisitionError(
                    f"GET {url} returned HTTP {response.status_code} after {attempt} attempt(s)",
                    status_code=response.status_code,
                )
            return response

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RetryingHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def build_http_client(
    settings: Settings,
    *,
    replay_transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> RetryingHttpClient:
    """Create the client used by network adapters.

    In ``replay`` mode the supplied transport serves committed fixtures; the rest of the stack
    (retries, parsing, validation, loading) is exactly the code that runs against live sources.
    """
    transport = replay_transport if settings.source_mode is SourceMode.REPLAY else None
    if settings.source_mode is SourceMode.REPLAY and transport is None:
        raise ValueError("replay mode requires a replay transport")
    client = httpx.Client(
        timeout=httpx.Timeout(
            connect=settings.http_connect_timeout_seconds,
            read=settings.http_read_timeout_seconds,
            write=settings.http_read_timeout_seconds,
            pool=settings.http_connect_timeout_seconds,
        ),
        headers={"User-Agent": settings.http_user_agent, "Accept-Encoding": "gzip"},
        follow_redirects=True,
        transport=transport,
    )
    return RetryingHttpClient(
        client,
        max_retries=settings.http_max_retries,
        backoff_base_seconds=settings.http_backoff_base_seconds,
        backoff_max_seconds=settings.http_backoff_max_seconds,
        sleep=sleep,
    )
