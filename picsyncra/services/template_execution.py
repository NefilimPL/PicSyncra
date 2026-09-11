"""Bounded execution helpers for template work with no Pimcore dependencies."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping, TypeVar

from ..pimcore_templates import placeholder_sources


T = TypeVar("T")


@dataclass(frozen=True)
class MappingDependencies:
    sources: tuple[str, ...]
    independent: bool


def classify_template_operation(mapping: Mapping[str, object]) -> MappingDependencies:
    template = mapping.get("sql_query") or mapping.get("value_template") or ""
    sources = placeholder_sources(template)
    independent = not any(
        source.strip().casefold().startswith(("pimcore:", "pimcore."))
        for source in sources
    )
    return MappingDependencies(sources=sources, independent=independent)


def execute_independent_operations(
    operations: Iterable[Callable[[], T]],
    *,
    max_workers: int = 4,
) -> list[T]:
    queued = list(operations)
    if len(queued) < 2:
        return [operation() for operation in queued]
    with ThreadPoolExecutor(max_workers=max(1, min(4, max_workers))) as executor:
        return list(executor.map(lambda operation: operation(), queued))
