"""Period-level 7+2 observations, not satisfaction scoring.

Unlike per-event labelling, a state report considers a whole period against an
explicit earlier baseline. Agent proposals are append-only, source-anchored
and invalidated when any cited source changes or disappears.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .compiler import AXES, DOMAINS, SemanticAssembler, digest, refkey
from .core import ValidationError, _period, _utc_now

STATE_COVERAGE = {"observed", "partial", "unobserved"}
DIRECTIONS = {"initial", "improved", "stable", "declined", "mixed", "uncertain"}
GOAL_FIT = {"not_assessed", "building", "enough", "strained", "no_goal"}
CONFIDENCE = {"high", "medium", "low", "unknown"}
MAX_REFERENCES = 20


def string(value, field, limit=700):
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"{field} must be a string <= {limit} characters")
    return value.strip()


def refs_checked(value, sources, field, min_count=0):
    if not isinstance(value, list) or len(value) > MAX_REFERENCES:
        raise ValidationError(f"{field} must contain <= {MAX_REFERENCES} source references")
    found, seen = [], set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"source_type", "source_ref"}:
            raise ValidationError(f"{field} requires exact source_type/source_ref")
        key = (raw["source_type"], raw["source_ref"])
        item = sources.get(key)
        if item is None or item["resolution_status"] != "active":
            raise ValidationError(f"{field} cites absent or inactive source: {key}")
        if key not in seen:
            seen.add(key)
            found.append({"source_type": key[0], "source_ref": key[1]})
    if len(found) < min_count:
        raise ValidationError(f"{field} needs at least {min_count} current source(s)")
    return found


def _row_report(row):
    if row is None:
        return None
    body = json.loads(row["body_json"])
    return {
        "report_id": row["id"], "period_start": row["period_start"],
        "period_end": row["period_end"], "created_at": row["created_at"],
        "baseline_report_id": row["baseline_id"],
        "supersedes": row["supersedes"],
        "status": "agent_proposal",
        "domains": body["domains"], "axes": body["axes"],
        "source_hashes": json.loads(row["source_hashes_json"]),
    }


class StateSynthesis:
    def __init__(self, store):
        self.store = store

    def _previous(self, start):
        with self.store._connection() as db:
            return _row_report(db.execute(
                """SELECT * FROM state_reports WHERE period_end < ?
                   ORDER BY period_end DESC, created_at DESC, rowid DESC LIMIT 1""",
                (start,)).fetchone())

    def _latest(self, start, end):
        with self.store._connection() as db:
            return _row_report(db.execute(
                """SELECT * FROM state_reports WHERE period_start=? AND period_end=?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""", (start, end)
            ).fetchone())

    def _context(self, start, end):
        _period(start, end)
        assembler = SemanticAssembler(self.store)
        current, warnings = assembler._items(start, end)
        previous = self._previous(start)
        older, older_warnings = ([], [])
        if previous:
            older, older_warnings = assembler._items(previous["period_start"], previous["period_end"])
        sources = {refkey(x): x for x in older}
        sources.update({refkey(x): x for x in current})
        hashes = sorted(
            [[type_, ref, digest(obj)] for (type_, ref), obj in sources.items()],
            key=lambda x: (x[0], x[1]),
        )
        goals = self.store.get_snapshot()["goals"]
        versioned_goals = sorted([[g["goal_id"], g["version"]] for g in goals])
        token = digest({
            "period_start": start, "period_end": end,
            "current": sorted([[*refkey(x), digest(x)] for x in current]),
            "baseline_id": previous["report_id"] if previous else None,
            "baseline_sources": hashes,
            "goals": versioned_goals,
        })
        return {
            "current": current, "earlier": older, "previous": previous,
            "all_sources": sources, "hashes": hashes, "goals": goals,
            "token": token, "warnings": warnings + older_warnings,
        }

    def get_context(self, period_start, period_end):
        data = self._context(period_start, period_end)
        from .compiler import SemanticAssembler
        assembled = SemanticAssembler(self.store).assemble(period_start, period_end, data["current"])
        previous = data["previous"]
        prior_health = None
        if previous:
            prior_health = self._check_sources(previous)
        return {
            "period_start": period_start, "period_end": period_end,
            "context_token": data["token"],
            "previous_state": previous,
            "previous_sources_healthy": prior_health,
            "domain_evidence": assembled["domains"],
            "axis_evidence": assembled["axes"],
            "goals": data["goals"],
            "source_count": len(data["current"]),
            "source_coverage": assembled["counts"],
            "warnings": data["warnings"],
            "rules": (
                "Prepare ONE state entry for each of seven domains and TWO axes. "
                "State description is an agent hypothesis, not a satisfaction score. "
                "Distinguish current condition from comparison to an actual prior "
                "state. Only direction initial/uncertain is allowed without a valid "
                "previous state. Never infer decline from absence. Cite live records "
                "for any assertion. Explain cross-domain tradeoffs and goal strain "
                "when supported. Ask a targeted question only for consequential "
                "uncertainty; do not require seven user answers."
            ),
        }

    def _check_sources(self, report):
        data = self._context_sources_only(report)
        current = data
        missing = []
        for provider, source_ref, source_hash in report["source_hashes"]:
            item = current.get((provider, source_ref))
            if not item or item["resolution_status"] != "active" or digest(item) != source_hash:
                missing.append({"source_type": provider, "source_ref": source_ref})
        return {"valid": not missing, "stale_refs": missing}

    def _context_sources_only(self, report):
        assembler = SemanticAssembler(self.store)
        items, _ = assembler._items(report["period_start"], report["period_end"])
        parent = None
        if report["baseline_report_id"]:
            with self.store._connection() as db:
                row = db.execute(
                    "SELECT period_start,period_end FROM state_reports WHERE id=?",
                    (report["baseline_report_id"],),
                ).fetchone()
                if row:
                    parent = assembler._items(row["period_start"], row["period_end"])[0]
        return {refkey(x): x for x in (parent or []) + items}

    def get_latest(self, period_start, period_end):
        _period(period_start, period_end)
        report = self._latest(period_start, period_end)
        if report is None:
            return {"report": None, "validation": None}
        return {"report": report, "validation": self._check_sources(report)}

    def compile(self, period_start, period_end, context_token, domains, axes):
        ctx = self._context(period_start, period_end)
        if not isinstance(context_token, str) or ctx["token"] != context_token:
            raise ValidationError("State input changed; fetch a new context before compiling")
        sources = ctx["all_sources"]
        previous = ctx["previous"]
        previous_healthy = self._check_sources(previous)["valid"] if previous else False
        if not isinstance(domains, list) or len(domains) != len(DOMAINS):
            raise ValidationError("State must cover all seven domains (unknown is valid)")
        seen = set()
        normalized = []
        cited = {}
        goals_by_id = {g["goal_id"]: g for g in ctx["goals"]}
        for row in domains:
            if not isinstance(row, dict):
                raise ValidationError("Domain state must be a JSON object")
            domain = row.get("domain_id")
            if domain not in DOMAINS or domain in seen:
                raise ValidationError("Exactly one state per recognized domain")
            seen.add(domain)
            coverage = row.get("coverage")
            direction = row.get("direction")
            confidence = row.get("confidence", "unknown")
            goal_fit = row.get("goal_fit", "not_assessed")
            if coverage not in STATE_COVERAGE or direction not in DIRECTIONS or confidence not in CONFIDENCE:
                raise ValidationError("Invalid domain coverage, direction or confidence")
            if goal_fit not in GOAL_FIT:
                raise ValidationError("Invalid goal_fit")
            statement = string(row.get("picture", ""), "picture", 800)
            why = string(row.get("direction_reason", ""), "direction_reason", 600)
            question = string(row.get("question", ""), "question", 280)
            refs = refs_checked(row.get("evidence_refs", []), sources, "domain evidence")
            if coverage == "unobserved" and (refs or statement):
                raise ValidationError("Unobserved state must not assert unsupported facts")
            if coverage != "unobserved" and (not refs or not statement):
                raise ValidationError("Observed or partial state requires a claim and citations")
            if direction in {"improved", "stable", "declined", "mixed"}:
                if not previous or not previous_healthy:
                    raise ValidationError("Trend requires a valid previous state report")
                prior = next((x for x in previous["domains"] if x["domain_id"] == domain), None)
                if not prior or prior["coverage"] == "unobserved":
                    raise ValidationError(f"No valid previous domain baseline for {domain}")
                if not why or not refs:
                    raise ValidationError("Trend needs rationale and citations")
            target_goals = row.get("goal_ids", [])
            if not isinstance(target_goals, list) or len(target_goals) != len(set(target_goals)):
                raise ValidationError("goal_ids must be unique goal IDs")
            for goal_id in target_goals:
                if goal_id not in goals_by_id or domain not in goals_by_id[goal_id]["domain_ids"]:
                    raise ValidationError(f"Goal {goal_id} is not linked to domain {domain}")
            if goal_fit != "not_assessed" and goal_fit != "no_goal" and not target_goals:
                raise ValidationError("Goal-fit assessment requires linked goals")
            if goal_fit == "no_goal" and target_goals:
                raise ValidationError("no_goal conflicts with linked goal_ids")
            tradeoffs = row.get("tradeoffs", [])
            if not isinstance(tradeoffs, list) or len(tradeoffs) > 4:
                raise ValidationError("At most four cross-domain tradeoffs")
            parsed_tradeoffs = []
            for x in tradeoffs:
                if not isinstance(x, dict) or x.get("other_domain") not in DOMAINS:
                    raise ValidationError("tradeoff must name another recognized domain")
                if x["other_domain"] == domain:
                    raise ValidationError("tradeoff must cross domains")
                claim = string(x.get("claim", ""), "tradeoff claim", 500)
                evid = refs_checked(x.get("evidence_refs", []), sources, "tradeoff", min_count=1)
                if not claim:
                    raise ValidationError("tradeoff requires a claim")
                parsed_tradeoffs.append({"other_domain": x["other_domain"], "claim": claim,
                                         "evidence_refs": evid})
            for r in refs + [v for t in parsed_tradeoffs for v in t["evidence_refs"]]:
                k = (r["source_type"], r["source_ref"])
                cited[k] = sources[k]
            normalized.append({
                "domain_id": domain, "coverage": coverage, "picture": statement,
                "direction": direction, "direction_reason": why,
                "confidence": confidence, "goal_fit": goal_fit,
                "goal_ids": target_goals, "evidence_refs": refs,
                "tradeoffs": parsed_tradeoffs, "question": question,
            })
        if set(seen) != set(DOMAINS):
            raise ValidationError("Domain report must cover every life domain")
        if not isinstance(axes, list) or len(axes) != len(AXES):
            raise ValidationError("Report must contain exactly two narrative axes")
        axis_rows, seen_axes = [], set()
        for row in axes:
            if not isinstance(row, dict) or row.get("axis") not in AXES or row["axis"] in seen_axes:
                raise ValidationError("Exactly one known narrative axis per entry")
            seen_axes.add(row["axis"])
            status = row.get("status")
            if status not in {"unknown", "proposed"}:
                raise ValidationError("Axis status must be unknown or proposed")
            claim = string(row.get("narrative", ""), "axis narrative", 800)
            refs = refs_checked(row.get("evidence_refs", []), sources, "axis evidence")
            if status == "proposed" and (not claim or not refs):
                raise ValidationError("Proposed axis requires a narrative and source citations")
            if status == "unknown" and (claim or refs):
                raise ValidationError("Unknown axis cannot assert a narrative")
            for r in refs:
                key = (r["source_type"], r["source_ref"])
                cited[key] = sources[key]
            axis_rows.append({"axis": row["axis"], "status": status,
                              "narrative": claim, "evidence_refs": refs})
        body = {"domains": sorted(normalized, key=lambda x: DOMAINS.index(x["domain_id"])),
                "axes": sorted(axis_rows, key=lambda x: AXES.index(x["axis"]))}
        hashlist = sorted(
            [[*key, digest(x)] for key, x in cited.items()],
            key=lambda r: (r[0], r[1]),
        )
        with self.store._connection() as db:
            last = db.execute(
                """SELECT * FROM state_reports WHERE period_start=? AND period_end=?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""", (period_start, period_end),
            ).fetchone()
            if last and (json.loads(last["body_json"]) == body and
                         json.loads(last["source_hashes_json"]) == hashlist and
                         last["baseline_id"] == (previous["report_id"] if previous else None)):
                return {**_row_report(last), "unchanged": True, "validation": {"valid": True, "stale_refs": []}}
            ident = str(uuid.uuid4())
            db.execute(
                """INSERT INTO state_reports(
                     id,period_start,period_end,created_at,baseline_id,supersedes,
                     body_json,source_hashes_json
                   ) VALUES(?,?,?,?,?,?,?,?)""",
                (ident, period_start, period_end, _utc_now(),
                 previous["report_id"] if previous else None,
                 last["id"] if last else None,
                 json.dumps(body, ensure_ascii=False, sort_keys=True),
                 json.dumps(hashlist, ensure_ascii=False, sort_keys=True))
            )
            report = _row_report(db.execute("SELECT * FROM state_reports WHERE id=?", (ident,)).fetchone())
        return {**report, "unchanged": False, "validation": {"valid": True, "stale_refs": []}}
