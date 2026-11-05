"""Agent-assisted, source-anchored 7+2 semantic projection.

Facetide does not run a second LLM or silently synthesize user judgements.
The *host Agent* compiles semantic evidence by reading batches and returning
structured annotations. SQLite stores only rebuildable projection metadata;
external memories and health systems remain the source of truth.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

DOMAINS = ("career", "finance", "health", "family", "social", "leisure", "environment")
AXES = ("personal_growth", "self_realization")
CHANGES = ("new", "stable", "receding", "unknown")
CONFIDENCE = ("high", "medium", "low")
MAX_BATCH = 50
MAX_ITEMS = 2500


class CompilationError(ValueError):
    pass


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def refkey(item):
    return (item["source_type"], item["source_ref"])


def strict_text(value, field, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise CompilationError(f"{field} must be text <= {limit} characters")
    return value.strip()


def normalize_refs(refs, available, require_active=True):
    if not isinstance(refs, list) or len(refs) > 12:
        raise CompilationError("evidence_refs must contain at most 12 references")
    result, seen = [], set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"source_type", "source_ref"}:
            raise CompilationError("reference requires exact source_type and source_ref")
        key = refkey(ref)
        item = available.get(key)
        if not item or (require_active and item["resolution_status"] != "active"):
            raise CompilationError(f"source reference not current and active: {key}")
        if key not in seen:
            seen.add(key)
            result.append({"source_type": key[0], "source_ref": key[1], "source_hash": digest(item)})
    return result


class SemanticAssembler:
    def __init__(self, store):
        self.store = store

    def _items(self, start, end):
        from .core import _period
        _period(start, end)
        records, warnings = self.store._evidence(start, end)
        if len(records) > MAX_ITEMS:
            warnings.append(f"Only first {MAX_ITEMS} evidence records considered; narrow the period")
            records = records[:MAX_ITEMS]
        by_key = {}
        for item in records:
            key = refkey(item)
            if key in by_key:
                warnings.append(f"duplicate source identity in aggregate: {key}")
                continue
            by_key[key] = item
        return list(by_key.values()), warnings

    @staticmethod
    def _slice(items, offset, limit):
        if type(offset) is not int or offset < 0 or offset > MAX_ITEMS:
            raise CompilationError("offset must be 0..2500")
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH:
            raise CompilationError("limit must be 1..50")
        return items[offset:offset+limit]

    def _annotations(self, db):
        return {(r["source_type"], r["source_ref"]): r
                for r in db.execute("SELECT * FROM compiled_evidence")}

    def get_batch(self, start: str, end: str, offset: int = 0, limit: int = 25) -> dict:
        items, warnings = self._items(start, end)
        chunk = self._slice(items, offset, limit)
        with self.store._connection() as db:
            annotations = self._annotations(db)
        records = []
        for item in chunk:
            key = refkey(item)
            prior = annotations.get(key)
            current = bool(prior and prior["source_hash"] == digest(item)
                           and item["resolution_status"] == "active")
            records.append({**item, "source_hash": digest(item),
                            "classification": "compiled" if current else
                                              "invalid" if item["resolution_status"] != "active" else "pending"})
        return {
            "period_start": start, "period_end": end,
            "offset": offset, "limit": limit, "total": len(items),
            "next_offset": offset + len(chunk) if offset + len(chunk) < len(items) else None,
            "batch_fingerprint": digest(chunk),
            "evidence": records, "warnings": warnings,
            "instructions": (
                "Classify every active evidence item into zero or more of the seven "
                "life domains. Use empty domains when genuinely not relevant. "
                "Do not infer a subjective satisfaction score. Distinguish user "
                "statement, evidence, and model inference. If causal links support "
                "personal_growth or self_realization, propose source-cited axis "
                "insights. This is a revisable projection, not authoritative memory."
            ),
        }

    def compile_batch(self, period_start: str, period_end: str, offset: int,
                      limit: int, batch_fingerprint: str, annotations: list[dict],
                      axis_insights: list[dict] | None = None) -> dict:
        items, warnings = self._items(period_start, period_end)
        chunk = self._slice(items, offset, limit)
        if not isinstance(batch_fingerprint, str) or digest(chunk) != batch_fingerprint:
            raise CompilationError("Evidence batch changed; re-fetch before compiling")
        active = {refkey(item): item for item in chunk if item["resolution_status"] == "active"}
        full = {refkey(item): item for item in items}
        if not isinstance(annotations, list) or len(annotations) > MAX_BATCH:
            raise CompilationError("annotations must be a bounded list")
        checked = {}
        for row in annotations:
            if not isinstance(row, dict):
                raise CompilationError("annotation must be a JSON object")
            key = refkey(row) if "source_type" in row and "source_ref" in row else (None, None)
            if key not in active or key in checked:
                raise CompilationError(f"annotation source missing, inactive or repeated: {key}")
            domains = row.get("domain_ids")
            if (not isinstance(domains, list) or len(domains) > 7 or
                any(d not in DOMAINS for d in domains) or len(domains) != len(set(domains))):
                raise CompilationError("domain_ids must be unique known domains, or []")
            axes = row.get("axis_ids", [])
            if (not isinstance(axes, list) or len(axes) > 2 or
                any(a not in AXES for a in axes) or len(axes) != len(set(axes))):
                raise CompilationError("axis_ids must contain only two narrative axes")
            change, confidence = row.get("change", "unknown"), row.get("confidence", "low")
            if change not in CHANGES or confidence not in CONFIDENCE:
                raise CompilationError("invalid change or confidence value")
            observation = strict_text(row.get("observation", ""), "observation", 360)
            why = strict_text(row.get("reason", ""), "reason", 400)
            if (domains or axes) and not observation:
                raise CompilationError("mapped evidence requires an observation")
            checked[key] = {
                "domains": sorted(domains), "axes": sorted(axes),
                "change": change, "confidence": confidence,
                "observation": observation, "reason": why,
            }
        if set(checked) != set(active):
            raise CompilationError("One classification per active item is required; [] marks out-of-scope")
        if axis_insights is None:
            axis_insights = []
        if not isinstance(axis_insights, list) or len(axis_insights) > 12:
            raise CompilationError("axis_insights must be a list <=12")
        axis_rows = []
        for row in axis_insights:
            if not isinstance(row, dict) or row.get("axis") not in AXES:
                raise CompilationError("invalid axis insight")
            summary = strict_text(row.get("summary", ""), "axis summary", 500)
            if not summary:
                raise CompilationError("axis summary cannot be empty")
            refs = normalize_refs(row.get("evidence_refs", []), full)
            if not refs:
                raise CompilationError("axis insight requires current source citations")
            axis_rows.append((row["axis"], summary, refs))
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.store._connection() as db:
            for key, info in checked.items():
                item = active[key]
                db.execute("""
                    INSERT INTO compiled_evidence(
                      source_type,source_ref,source_hash,domains_json,axes_json,
                      change_kind,confidence,observation,reason,compiled_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_type,source_ref) DO UPDATE SET
                      source_hash=excluded.source_hash, domains_json=excluded.domains_json,
                      axes_json=excluded.axes_json, change_kind=excluded.change_kind,
                      confidence=excluded.confidence, observation=excluded.observation,
                      reason=excluded.reason, compiled_at=excluded.compiled_at
                """, (key[0], key[1], digest(item), json.dumps(info["domains"]),
                      json.dumps(info["axes"]), info["change"], info["confidence"],
                      info["observation"], info["reason"], timestamp))
            for axis, summary, refs in axis_rows:
                # One source-backed projection per distinct set of cited refs.
                signature = digest({"axis": axis, "refs": sorted(
                    [f'{r["source_type"]}:{r["source_ref"]}:{r["source_hash"]}' for r in refs])})
                db.execute("""
                    INSERT INTO compiled_axes(
                      period_start,period_end,axis,signature,summary,evidence_refs_json,compiled_at
                    ) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(period_start,period_end,axis,signature) DO UPDATE
                    SET summary=excluded.summary, compiled_at=excluded.compiled_at
                """, (period_start,period_end,axis,signature,summary,json.dumps(refs),timestamp))
        return {
            "accepted": len(checked), "axis_insights": len(axis_rows),
            "period_start": period_start, "period_end": period_end,
            "next_offset": offset+len(chunk) if offset+len(chunk)<len(items) else None,
            "warnings": warnings,
            "note": "Compiled views are model proposals; satisfaction ratings remain user-only.",
        }

    def assemble(self, start: str, end: str, items: list[dict] | None = None) -> dict:
        if items is None:
            items, warnings = self._items(start, end)
        else:
            warnings = []
        current = {refkey(item): item for item in items}
        with self.store._connection() as db:
            compiled = self._annotations(db)
            axis_rows = db.execute(
                """SELECT * FROM compiled_axes
                   WHERE period_start=? AND period_end=?
                   ORDER BY compiled_at DESC, rowid DESC""", (start, end)).fetchall()
        domains = {d: {"domain_id": d, "evidence": [], "source_tagged": 0,
                       "compiled": 0, "status": "no_evidence"} for d in DOMAINS}
        axes = {a: {"axis_id": a, "insights": [], "status": "no_evidence"} for a in AXES}
        changes = {c: [] for c in CHANGES if c != "unknown"}
        pending, stale, unclassified = [], [], []
        for item in items:
            key = refkey(item)
            if item["resolution_status"] != "active":
                continue
            annotation = compiled.get(key)
            valid = bool(annotation and annotation["source_hash"] == digest(item))
            if annotation and not valid:
                stale.append({"source_type": key[0], "source_ref": key[1]})
            if not valid:
                pending.append({"source_type": key[0], "source_ref": key[1]})
            tags = json.loads(annotation["domains_json"]) if valid else item["domain_ids"]
            if not tags:
                unclassified.append({"source_type": key[0], "source_ref": key[1]})
            summary = annotation["observation"] if valid and annotation["observation"] else item["summary"]
            candidate = {
                "source_type": key[0], "source_ref": key[1],
                "occurred_at": item["occurred_at"], "known_at": item["known_at"],
                "evidence_kind": item["evidence_kind"],
                "summary": summary, "domain_ids": tags,
                "classification": "agent_compiled" if valid else "source_tagged",
                "confidence": annotation["confidence"] if valid else None,
                "reason": annotation["reason"] if valid else None,
                "change": annotation["change_kind"] if valid else item["change"],
            }
            for d in tags:
                domain = domains[d]
                domain["evidence"].append(candidate)
                domain["compiled" if valid else "source_tagged"] += 1
                domain["status"] = "compiled" if valid else ("source_only" if domain["status"]!="compiled" else "compiled")
            if candidate["change"] in changes:
                changes[candidate["change"]].append(candidate)
            if valid:
                for a in json.loads(annotation["axes_json"]):
                    axes[a]["insights"].append({
                        "summary": candidate["summary"],
                        "evidence_refs": [{"source_type": key[0], "source_ref": key[1]}],
                        "confidence": candidate["confidence"], "kind": "event_marker",
                    })
        for row in axis_rows:
            refs = json.loads(row["evidence_refs_json"])
            if not all((r["source_type"], r["source_ref"]) in current
                       and current[(r["source_type"], r["source_ref"])]["resolution_status"] == "active"
                       and digest(current[(r["source_type"], r["source_ref"])]) == r["source_hash"]
                       for r in refs):
                continue
            axes[row["axis"]]["insights"].append({
                "summary": row["summary"],
                "evidence_refs": [{"source_type": r["source_type"], "source_ref": r["source_ref"]} for r in refs],
                "kind": "cross_event_inference",
            })
        for domain in domains.values():
            domain["evidence"].sort(key=lambda x: (x["occurred_at"],x["source_type"],x["source_ref"]),reverse=True)
            domain["total_evidence"] = len(domain["evidence"])
            domain["evidence"] = domain["evidence"][:20]
        for axis in axes.values():
            axis["status"] = "compiled" if axis["insights"] else "no_evidence"
            axis["insights"] = axis["insights"][:12]
        return {
            "domains": domains, "axes": axes,
            "change_candidates": {k: v[:40] for k,v in changes.items()},
            "unclassified": unclassified[:100],
            "pending": pending[:100], "stale_annotations": stale[:100],
            "counts": {
                "source_items": len(items),
                "active_items": sum(e["resolution_status"] == "active" for e in items),
                "compiled_items": sum(1 for i in items if i["resolution_status"]=="active"
                    and (a:=compiled.get(refkey(i))) is not None and a["source_hash"] == digest(i)),
                "unclassified": len(unclassified),
                "pending": len(pending),
                "stale": len(stale),
            }, "warnings": warnings,
            "rating_policy": "Only the user may score any of the seven domains. Axes are unscored proposals.",
        }
