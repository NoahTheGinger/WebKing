"""Network log analyzers for WebKing."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field


class NetworkInsightRequest(BaseModel):
    """Filter options for network analysis."""

    model_config = ConfigDict(extra="forbid")

    path_contains: str | None = Field(
        default=None,
        description="Substring filter for URLs (case-insensitive).",
    )
    method: str | None = Field(default=None, description="HTTP method filter (e.g., GET, POST).")
    status_min: int | None = Field(default=None, description="Minimum status code inclusive.")
    status_max: int | None = Field(default=None, description="Maximum status code inclusive.")
    include_bodies: bool = Field(
        default=False,
        description="Whether to include request bodies in the analysis output (can be large).",
    )


def _normalize_method(method: str | None) -> str | None:
    return method.upper() if method else None


def _filter_entry(entry: dict[str, Any], request: NetworkInsightRequest) -> bool:
    if request.path_contains and request.path_contains.lower() not in entry["url"].lower():
        return False
    if request.method and entry.get("method") != request.method:
        return False
    status = entry.get("status")
    if request.status_min is not None and (status or 0) < request.status_min:
        return False
    if request.status_max is not None and (status or 999) > request.status_max:
        return False
    return True


def analyze_network_log(
    network_entries: Iterable[dict[str, Any]],
    request: NetworkInsightRequest,
) -> dict[str, Any]:
    """Produce aggregated insights from network entries."""
    request.method = _normalize_method(request.method)
    filtered = [entry for entry in network_entries if _filter_entry(entry, request)]

    grouped_by_host: dict[str, list[dict[str, Any]]] = defaultdict(list)
    methods_count: dict[str, int] = defaultdict(int)
    status_buckets: dict[int, int] = defaultdict(int)

    for entry in filtered:
        host = entry["url"].split("//")[-1].split("/")[0]
        grouped_by_host[host].append(entry)
        methods_count[entry["method"]] += 1
        if entry.get("status") is not None:
            status_buckets[int(entry["status"])] += 1

    sample_payloads: list[dict[str, Any]] = []
    if request.include_bodies:
        for entry in filtered[:10]:
            sample_payloads.append(
                {
                    "url": entry["url"],
                    "method": entry["method"],
                    "status": entry.get("status"),
                    "post_data": entry.get("post_data"),
                }
            )

    top_hosts = sorted(grouped_by_host.items(), key=lambda item: len(item[1]), reverse=True)

    return {
        "total_filtered": len(filtered),
        "top_hosts": [
            {
                "host": host,
                "request_count": len(entries),
                "methods": sorted({entry["method"] for entry in entries}),
                "status_codes": sorted({entry.get("status") for entry in entries if entry.get("status")}),
            }
            for host, entries in top_hosts[:10]
        ],
        "methods_count": dict(sorted(methods_count.items(), key=lambda kv: kv[1], reverse=True)),
        "status_buckets": dict(sorted(status_buckets.items())),
        "sample_payloads": sample_payloads,
    }
