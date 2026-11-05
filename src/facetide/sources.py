"""Optional, read-only evidence source adapters.

The JSONL bridge is intentionally not an MR-MEM API client: each external
system must publish/transform evidence using its own verified contract.
Raw chat transcripts and health metrics never enter Facetide's database.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

KINDS = frozenset({"fact", "user_statement", "inference"})
STATUSES = frozenset({"active", "superseded", "retracted"})
CHANGES = frozenset({"new", "stable", "receding"})


def calendar_date(value: str) -> str:
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError("date must be ISO 8601")
    day = date.fromisoformat(value[:10])
    if value[:10] != day.isoformat():
        raise ValueError("date must be ISO 8601")
    if len(value) > 10:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    return day.isoformat()


def normalize_evidence(row: dict, domains: frozenset[str]) -> dict:
    if not isinstance(row, dict):
        raise ValueError("evidence must be an object")
    source_type, source_ref = row.get("source_type"), row.get("source_ref")
    if not all(isinstance(x, str) and x.strip() and len(x) <= 200 for x in (source_type, source_ref)):
        raise ValueError("evidence requires source_type and source_ref (max 200 chars)")
    day = calendar_date(row.get("occurred_at"))
    known = row.get("known_at")
    if known is not None:
        calendar_date(known)
    dims = row.get("domain_ids", [])
    if not isinstance(dims, list) or any(d not in domains for d in dims):
        raise ValueError("invalid evidence domain_ids")
    kind = row.get("evidence_kind", "fact")
    status = row.get("resolution_status", "active")
    change = row.get("change")
    if kind not in KINDS or status not in STATUSES or (change is not None and change not in CHANGES):
        raise ValueError("invalid evidence kind, status or change")
    summary = row.get("summary", "")
    if not isinstance(summary, str) or len(summary) > 500:
        raise ValueError("summary must be a string <= 500 characters")
    return {
        "source_type": source_type.strip(),
        "source_ref": source_ref.strip(),
        "occurred_at": row["occurred_at"],
        "known_at": known,
        "domain_ids": sorted(set(dims)),
        "evidence_kind": kind,
        "resolution_status": status,
        "change": change,
        "summary": summary,
    }


class EvidenceSource(Protocol):
    def query(self, period_start: str, period_end: str, domains: frozenset[str]) -> tuple[list[dict], list[str]]: ...


class EmptySource:
    def query(self, period_start: str, period_end: str, domains: frozenset[str]) -> tuple[list[dict], list[str]]:
        return [], []


class JsonlSource:
    """Read-only bridge: one JSON object per line, UTF-8, no network calls."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def query(self, period_start: str, period_end: str, domains: frozenset[str]) -> tuple[list[dict], list[str]]:
        if not self.path.exists():
            return [], [f"Evidence file is missing: {self.path}"]
        latest: dict[tuple[str, str], dict] = {}
        warnings: list[str] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                if line_number > 100_000:
                    warnings.append("Evidence file exceeded 100000 lines; remaining rows skipped")
                    break
                try:
                    item = normalize_evidence(json.loads(line), domains)
                    key = (item["source_type"], item["source_ref"])
                    # Later entries supersede older versions of the same source ref.
                    latest[key] = item
                except (ValueError, TypeError, KeyError) as exc:
                    if len(warnings) < 20:
                        warnings.append(f"line {line_number}: {exc}")
        items = [item for item in latest.values()
                 if period_start <= calendar_date(item["occurred_at"]) <= period_end]
        items.sort(key=lambda item: (item["occurred_at"], item["source_type"], item["source_ref"]))
        return items, warnings
