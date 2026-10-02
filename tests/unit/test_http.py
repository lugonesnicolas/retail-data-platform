from __future__ import annotations

import httpx
import pytest

from retail_data_platform.ingestion.http import AcquisitionError, RetryingHttpClient


def client_for(
    handler: httpx.MockTransport, *, max_retries: int = 3
) -> tuple[RetryingHttpClient, list[float]]:
    sleeps: list[float] = []
    client = RetryingHttpClient(
        httpx.Client(transport=handler),
        max_retries=max_retries,
        backoff_base_seconds=1.0,
        backoff_max_seconds=5.0,
        sleep=sleeps.append,
    )
    return client, sleeps


def sequence_transport(responses: list[httpx.Response | Exception]) -> httpx.MockTransport:
    calls = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = next(calls)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler)


def test_retries_transient_status_then_succeeds() -> None:
    client, sleeps = client_for(
        sequence_transport([httpx.Response(503), httpx.Response(502), httpx.Response(200, json={})])
    )
    assert client.get("https://example.test/x").status_code == 200
    assert client.request_count == 3
    assert len(sleeps) == 2
    # Exponential: attempt 1 in [1, 2), attempt 2 in [2, 3)
    assert 1 <= sleeps[0] < 2
    assert 2 <= sleeps[1] < 3


def test_retries_transport_errors() -> None:
    client, sleeps = client_for(
        sequence_transport([httpx.ConnectTimeout("boom"), httpx.Response(200, text="ok")])
    )
    assert client.get("https://example.test/x").text == "ok"
    assert len(sleeps) == 1


def test_honours_retry_after_and_caps_backoff() -> None:
    client, sleeps = client_for(
        sequence_transport(
            [httpx.Response(429, headers={"Retry-After": "120"}), httpx.Response(200)]
        )
    )
    client.get("https://example.test/x")
    assert sleeps == [5.0]  # capped at backoff_max_seconds


def test_client_errors_fail_fast() -> None:
    client, sleeps = client_for(sequence_transport([httpx.Response(404)]))
    with pytest.raises(AcquisitionError) as excinfo:
        client.get("https://example.test/missing")
    assert excinfo.value.status_code == 404
    assert sleeps == []


def test_gives_up_after_max_retries() -> None:
    client, sleeps = client_for(sequence_transport([httpx.ReadTimeout("slow")] * 3), max_retries=2)
    with pytest.raises(AcquisitionError, match="after 3 attempts"):
        client.get("https://example.test/slow")
    assert len(sleeps) == 2


def test_persistent_server_error_surfaces_status() -> None:
    client, _ = client_for(sequence_transport([httpx.Response(500)] * 3), max_retries=2)
    with pytest.raises(AcquisitionError) as excinfo:
        client.get("https://example.test/x")
    assert excinfo.value.status_code == 500
