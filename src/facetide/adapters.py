"""Optional read-only upstream sources. No dependency on MR-Mem runtime.

MR-Mem AML store contract: canonical_memory.payload + scoped native messages.
The caller must explicitly configure the store path and user_id. Source
verification follows Atlas's read-only MR-Mem reader, not a raw text index.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable

from .sources import calendar_date, normalize_evidence


class CompositeSource:
    def __init__(self, sources: Iterable):
        self.sources = list(sources)

    def query(self, period_start, period_end, domains):
        records, warnings = [], []
        seen = set()
        for source in self.sources:
            try:
                items, problems = source.query(period_start, period_end, domains)
                warnings.extend(problems)
                for item in items:
                    ident = (item["source_type"], item["source_ref"])
                    if ident not in seen:
                        seen.add(ident)
                        records.append(item)
                    else:
                        warnings.append(f"Duplicate evidence reference ignored: {ident}")
            except (OSError, sqlite3.Error, ValueError) as exc:
                warnings.append(f"{type(source).__name__} unavailable: {exc}")
        records.sort(key=lambda x: (x["occurred_at"], x["source_type"], x["source_ref"]))
        return records, warnings[:40]


class MrMemAmlSource:
    """Read-only projection of MR-Mem AML canonical data with native verification.

    Requires the explicit AML storage pair as documented by ATLAS:
      memory.sqlite / canonical_memory(payload JSON)
      aml_source.sqlite / messages
    No MemoryRuntime construction, migrations, search or recompilation.
    """

    def __init__(self, root: str | Path, user_id: str, max_items: int = 2000):
        self.root = Path(root).expanduser().resolve()
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("MR-Mem requires an explicit scoped user ID")
        self.user_id = user_id.strip()
        self.max_items = max_items

    def _connect(self, filename):
        path = self.root / filename
        if not path.is_file():
            raise OSError(f"missing MR-Mem store: {filename}")
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _verify(self, db, ref):
        if not isinstance(ref, dict) or ref.get("source_namespace") != "aml":
            raise ValueError("unsupported MR-Mem source namespace")
        fingerprint = ref.get("fingerprint")
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise ValueError("unversioned native source")
        row = db.execute(
            "SELECT occurred_at,time_given,fingerprint,content FROM messages "
            "WHERE user_id=? AND session_id=? AND record_id=?",
            (self.user_id, ref.get("session_id"), ref.get("record_id")),
        ).fetchone()
        if row is None or row["fingerprint"] != fingerprint:
            raise ValueError("current native source unavailable or revised")
        digest = hashlib.sha256(row["content"].encode("utf-8")).hexdigest()
        if digest != fingerprint:
            raise ValueError("native source content fingerprint mismatch")
        return row

    def query(self, period_start, period_end, domains):
        if not (self.root / "memory.sqlite").is_file():
            return [], ["MR-Mem store missing: memory.sqlite"]
        if not (self.root / "aml_source.sqlite").is_file():
            return [], ["MR-Mem AML source missing: aml_source.sqlite"]
        records, warnings = [], []
        with closing(self._connect("memory.sqlite")) as memory_db, closing(self._connect("aml_source.sqlite")) as source_db:
            for index, row in enumerate(memory_db.execute("SELECT payload FROM canonical_memory")):
                if index >= 100000:
                    warnings.append("MR-Mem canonical scan capped at 100000 rows")
                    break
                try:
                    mem = json.loads(row["payload"])
                    scope = mem.get("scope", {})
                    if (scope.get("domain") != "user" or scope.get("user_id") != self.user_id):
                        continue
                    refs = mem.get("provenance", {}).get("source_refs", [])
                    if not refs:
                        continue
                    occurred = []
                    for ref in refs:
                        src = self._verify(source_db, ref)
                        if bool(src["time_given"]) and src["occurred_at"]:
                            occurred.append(src["occurred_at"])
                    if not occurred:
                        # No known event date: never substitute commit or ordering time.
                        continue
                    timestamp = min(occurred)
                    day = calendar_date(timestamp)
                    if not period_start <= day <= period_end:
                        continue
                    lifecycle = mem.get("lifecycle", "")
                    status = "active" if lifecycle == "active" else "retracted"
                    raw_attributes = mem.get("attributes") or {}
                    attributes = raw_attributes if isinstance(raw_attributes, dict) else dict(raw_attributes)
                    tagged = attributes.get("facetide_domains", [])
                    matched = [d for d in tagged if d in domains] if isinstance(tagged, list) else []
                    known_at = mem.get("committed_at") or None
                    if known_at:
                        calendar_date(known_at)
                    raw_text = mem.get("content", "")
                    if not isinstance(raw_text, str):
                        raise ValueError("semantic memory content is not a string")
                    item = normalize_evidence({
                        "source_type": "mrmem",
                        "source_ref": str(mem["memory_id"]),
                        "occurred_at": timestamp,
                        "known_at": known_at,
                        "domain_ids": matched,
                        # The host-admitted semantic statement is not independently
                        # verified as an external fact; preserve the uncertainty.
                        "evidence_kind": "inference",
                        "resolution_status": status,
                        "change": None,
                        "summary": raw_text[:500],
                    }, domains)
                    records.append(item)
                except (ValueError, KeyError, TypeError, AttributeError) as exc:
                    if len(warnings) < 30:
                        warnings.append(f"MR-Mem row {index + 1}: {exc}")
            records.sort(key=lambda x: (x["occurred_at"], x["source_ref"]))
            if len(records) > self.max_items:
                warnings.append(f"MR-Mem evidence capped at {self.max_items}; use a narrower period")
                records = records[:self.max_items]
        return records, warnings


class NutritionMcpSource:
    """Read-only, bounded recent 7/30-day summary from Nutrition-Tracker-MCP.

    The upstream tool exposes *rolling* windows, not arbitrary past intervals.
    A report is only returned when its exact upstream coverage fits entirely
    inside the requested Facetide review window. No interpolation or invented
    missing days. Authentication is read from an explicit environment variable.
    """

    def __init__(self, url: str, member_id: str | None = None,
                 token_env: str = "FACETIDE_NUTRITION_TOKEN"):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme not in {"https", "http"} or
            (parsed.scheme == "http" and not local) or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path != "/mcp" or not parsed.netloc):
            raise ValueError("Nutrition MCP URL must be https://host/mcp or loopback http://host/mcp")
        self.url = url
        self.member_id = member_id or None
        self.token_env = token_env

    async def _report(self, days):
        import os
        import asyncio
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        token = os.environ.get(self.token_env)
        if not token:
            raise ValueError(f"Missing Nutrition MCP bearer token in {self.token_env}")
        args = {"view": "report", "days": days}
        if self.member_id:
            args["memberId"] = self.member_id
        async with asyncio.timeout(18):
            async with streamablehttp_client(
                self.url, headers={"Authorization": f"Bearer {token}"}
            ) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    response = await session.call_tool("nutrition_query", arguments=args)
                if response.isError:
                    raise ValueError("Nutrition MCP refused report query")
                payload = response.structuredContent
                if not payload:
                    for part in response.content:
                        if getattr(part, "type", None) == "text":
                            try:
                                payload = json.loads(part.text)
                                break
                            except (ValueError, TypeError):
                                pass
                if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], dict):
                    payload = payload["data"]
                if not isinstance(payload, dict) or payload.get("ok") is not True:
                    raise ValueError("Nutrition MCP report response contract changed")
                return payload

    def query(self, period_start, period_end, domains):
        import asyncio
        import concurrent.futures
        from datetime import date, datetime, timezone
        days = (date.fromisoformat(period_end) - date.fromisoformat(period_start)).days + 1
        if days <= 0:
            raise ValueError("invalid report period")
        if days > 30:
            return [], ["Nutrition MCP only supports recent 7/30-day reports, not long-range history"]
        report_days = 7 if days <= 7 else 30
        try:
            # A separate event loop avoids collision with an async MCP host.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                report = pool.submit(lambda: asyncio.run(self._report(report_days))).result(timeout=35)
        except Exception as exc:
            return [], [f"Nutrition MCP report unavailable: {type(exc).__name__}"]
        try:
            from_date = calendar_date(report["fromDate"])
            to_date = calendar_date(report["toDate"])
            if from_date > to_date:
                raise ValueError("invalid source range")
            if from_date < period_start or to_date > period_end:
                return [], [
                    f"Nutrition report covers {from_date}..{to_date}; requested {period_start}..{period_end}. "
                    "No partial-window statistics inferred."
                ]
            details = [("nutrition", report.get("nutrition")), ("health", report.get("health"))]
            result = []
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for category, values in details:
                if not isinstance(values, dict):
                    continue
                # Bounded, factual coverage and quantities only. Do not generate
                # wellness scores or treat unrecorded days as zeros.
                fields = []
                for label, value in values.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        fields.append(f"{label}: {value}")
                if not fields:
                    continue
                summary = (f"Nutrition MCP {category} {from_date}..{to_date} "
                           f"({report_days}-day rolling report): " + "; ".join(fields))
                result.append(normalize_evidence({
                    "source_type": "nutrition-mcp",
                    "source_ref": f"{category}:{self.member_id or 'single'}:{from_date}:{to_date}",
                    "occurred_at": to_date, "known_at": now,
                    "domain_ids": ["health"], "evidence_kind": "fact",
                    "resolution_status": "active", "change": None,
                    "summary": summary[:500]
                }, domains))
            return result, []
        except (ValueError, KeyError, TypeError) as exc:
            return [], [f"Nutrition report invalid: {exc}"]
