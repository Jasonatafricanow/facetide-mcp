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
