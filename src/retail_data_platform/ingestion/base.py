"""Acquisition source abstraction.

An adapter is anything that satisfies the :class:`SourceAdapter` protocol (structural typing, no
inheritance required):

* ``extract()`` yields :class:`SourceRecord` objects exactly as the source provided them;
* ``normalize()`` maps one record onto the canonical :class:`ProductObservation` contract and
  raises ``pydantic.ValidationError`` / ``ValueError`` when the record violates it.

Validation, rejection handling, hashing, loading and operational metadata are source-agnostic
and live in :mod:`retail_data_platform.ingestion.pipeline`, so every source is held to the same
rules.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from retail_data_platform.models import ProductObservation, SourceName


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """A single, untouched record as delivered by a source."""

    payload: dict[str, Any]
    extracted_at: datetime
    source_url: str | None = None
    #: Best-effort source identifier (product id, CSV line...) used to reference rejects.
    ref: str | None = None


class SourceSchemaError(RuntimeError):
    """The source's envelope/structure changed so much that no record can be trusted.

    Unlike per-record contract violations (which are rejected individually), this aborts the
    whole source run.
    """


class SourceAdapter(Protocol):
    source: SourceName

    def extract(self) -> Iterator[SourceRecord]: ...

    def normalize(self, record: SourceRecord) -> ProductObservation: ...
