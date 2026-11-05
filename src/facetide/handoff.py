"""Facetide Agent handoff contract.

Facetide intentionally does NO semantic inference here. The host Agent
calls whichever upstream tools it can actually access (StateBar, MR-MEM,
Nutrition, etc.), then submits one structured interpretation. This module
checks structural completeness, citations, user-judgment attribution and
write integrity. It does NOT certify the truth of Agent-provided sources.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from .core import DOMAINS, ValidationError, _period, _utc_now
from .contract import HANDOFF_SCHEMA

AXES = ("personal_growth", "self_realization")
COVERAGE = {"observed", "partial", "unknown"}
DIRECTIONS = {"improving", "stable", "worsening", "mixed", "unknown"}
VALUES = {"worthwhile", "costly", "mixed", "uncertain"}
BASES = {"user_explicit", "user_confirmed_history", "agent_hypothesis", "unknown"}
SOURCE_STATUS = {"active", "resolved", "expired", "retracted", "unknown"}
SOURCE_KINDS = {"user_statement", "state", "measurement", "event", "model_inference"}
MAX_EVIDENCE = 100


def _text(value, label, limit=800):
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"{label} must be a string <= {limit} characters")
    return value.strip()


def _date(value, label):
    from datetime import date
    if not isinstance(value, str):
        raise ValidationError(f"{label} needs YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ValidationError(f"Invalid {label}") from exc
    if value[:10] != parsed.isoformat():
        raise ValidationError(f"Invalid {label}")
    return value


def _refs(refs, sources, label):
    if not isinstance(refs, list) or len(refs) > MAX_EVIDENCE:
        raise ValidationError(f"{label} must be a list of at most {MAX_EVIDENCE} refs")
    if any(not isinstance(x, str) or x not in sources for x in refs) or len(set(refs)) != len(refs):
        raise ValidationError(f"{label} must reference unique evidence IDs from the handoff")
    return list(refs)


def _validate_evidence(items):
    if not isinstance(items, list) or len(items) > MAX_EVIDENCE:
        raise ValidationError("evidence must be a list of at most 100 brief source records")
    sources = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValidationError("evidence item must be a JSON object")
        ident = _text(item.get("evidence_id"), "evidence_id", 120)
        provider = _text(item.get("provider"), "provider", 80)
        source_id = _text(item.get("source_ref"), "source_ref", 200)
        tool = _text(item.get("source_tool", ""), "source_tool", 120)
        day = _date(item.get("occurred_at"), "occurred_at")
        known_at = item.get("known_at")
        if known_at is not None:
            _date(known_at, "known_at")
        until = item.get("valid_until")
        if until is not None:
            _date(until, "valid_until")
            if until[:10] < day[:10]:
                raise ValidationError("valid_until cannot precede occurred_at")
        status = item.get("status", "unknown")
        kind = item.get("kind", "model_inference")
        if status not in SOURCE_STATUS or kind not in SOURCE_KINDS:
            raise ValidationError("Unsupported evidence status or kind")
        summary = _text(item.get("summary", ""), "evidence summary", 450)
        if not ident or not provider or not source_id or not summary:
            raise ValidationError("Evidence needs ID, provider, provider source_ref and brief summary")
        if ident in sources:
            raise ValidationError(f"Duplicate evidence_id {ident}")
        sources[ident] = {
            "evidence_id": ident, "provider": provider,
            "source_ref": source_id, "source_tool": tool,
            "occurred_at": day, "known_at": known_at, "valid_until": until,
            "status": status, "kind": kind, "summary": summary,
            # The data is supplied by the host Agent. Facetide cannot
            # independently inspect upstream provider records.
            "verification": "host_attested",
        }
    return sources


def _meaning(raw, sources, label):
    if not isinstance(raw, dict):
        raise ValidationError(f"{label} requires a meaning object")
    verdict = raw.get("assessment", "uncertain")
    basis = raw.get("basis", "unknown")
    why = _text(raw.get("why", ""), f"{label}.why", 1200)
    refs = _refs(raw.get("evidence_refs", []), sources, label + ".evidence_refs")
    if verdict not in VALUES or basis not in BASES:
        raise ValidationError("Unknown value assessment or attribution basis")
    if verdict != "uncertain" and (not why or not refs or basis == "unknown"):
        raise ValidationError("A claim about what is worthwhile/costly needs explanation, citations and attribution")
    if basis == "unknown" and verdict != "uncertain":
        raise ValidationError("Unknown user basis cannot imply a value preference")
    # User-explicit is itself host-attested, NOT a verified user confirmation.
    return {"assessment": verdict, "basis": basis, "why": why, "evidence_refs": refs}


def _domains(items, sources):
    if not isinstance(items, list) or len(items) != 7:
        raise ValidationError("Exactly seven domain records required; unknown is a valid record")
    domains = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValidationError("Domain record must be an object")
        domain = raw.get("domain_id")
        if domain not in DOMAINS or domain in seen:
            raise ValidationError("Exactly one record for each recognized life domain")
        seen.add(domain)
        coverage = raw.get("coverage")
        if coverage not in COVERAGE:
            raise ValidationError("Invalid coverage")
        observation = _text(raw.get("observation", ""), "observation", 900)
        evidence_refs = _refs(raw.get("evidence_refs", []), sources, "domain evidence_refs")
        if coverage == "unknown" and (observation or evidence_refs):
            raise ValidationError("An unknown domain cannot assert observations or citations")
        if coverage != "unknown" and (not observation or not evidence_refs):
            raise ValidationError("An observed domain requires evidence and a description")
        direction = raw.get("direction", "unknown")
        if direction not in DIRECTIONS:
            raise ValidationError("Invalid direction")
        comparison = _text(raw.get("comparison_basis", ""), "comparison_basis", 400)
        if direction != "unknown" and (not comparison or not evidence_refs):
            raise ValidationError("Non-unknown trend requires explicit comparison rationale and citations")
        meaning = _meaning(raw.get("meaning", {}), sources, "meaning")
        # Unknown domain cannot claim a value judgment from nothing.
        if coverage == "unknown" and meaning["assessment"] != "uncertain":
            raise ValidationError("Unknown domain cannot assert a value judgment")
        question = _text(raw.get("question", ""), "question", 280)
        domains.append({
            "domain_id": domain, "coverage": coverage,
            "observation": observation, "evidence_refs": evidence_refs,
            "direction": direction, "comparison_basis": comparison,
            "meaning": meaning, "question": question,
        })
    return sorted(domains, key=lambda row: list(DOMAINS).index(row["domain_id"]))


def _axes(items, sources):
    if not isinstance(items, list) or len(items) != 2:
        raise ValidationError("Exactly two qualitative axis records required")
    result = []
    seen = set()
    for raw in items:
        if not isinstance(raw, dict):
            raise ValidationError("Axis record must be an object")
        axis = raw.get("axis")
        if axis not in AXES or axis in seen:
            raise ValidationError("Unknown or duplicate narrative axis")
        seen.add(axis)
        status = raw.get("status")
        if status not in {"proposed", "unknown"}:
            raise ValidationError("Axis status must be proposed or unknown")
        narrative = _text(raw.get("narrative", ""), "narrative", 1200)
        refs = _refs(raw.get("evidence_refs", []), sources, "axis evidence_refs")
        basis = raw.get("basis", "unknown")
        if basis not in BASES:
            raise ValidationError("Unknown axis attribution")
        if status == "proposed" and (not narrative or not refs or basis == "unknown"):
            raise ValidationError("Proposed axis requires narrative, citations, attribution")
        if status == "unknown" and (narrative or refs):
            raise ValidationError("Unknown axis must not claim an explanation")
        result.append({
            "axis": axis, "status": status, "narrative": narrative,
            "evidence_refs": refs, "basis": basis,
        })
    return sorted(result, key=lambda row: AXES.index(row["axis"]))


def _hash(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AgentHandoff:
    def __init__(self, store):
        self.store = store

    def brief(self, period_start, period_end):
        _period(period_start, period_end)
        with self.store._connection() as db:
            latest = self.store._review(db.execute(
                """SELECT * FROM reviews WHERE period_end < ?
                   ORDER BY period_end DESC, confirmed_at DESC, rowid DESC LIMIT 1""",
                (period_start,)).fetchone())
            goals = self.store._goals(db)
        return {
            "protocol": "facetide.agent_handoff.v1",
            "period_start": period_start, "period_end": period_end,
            "previous_user_review": latest, "user_goals": goals,
            "domains": list(DOMAINS), "axes": list(AXES),
            "schema": HANDOFF_SCHEMA,
            "source_tools": {
                "statebar": ["user_state.snapshot", "user_state.get_state",
                             "user_state.context_candidates"],
                "long_term_memory": "Use the host's connected MR-MEM/ATLAS history reader",
                "specialist_sources": "Use whatever specialist MCP tools are actually connected",
            },
            "process": [
                "The host Agent, not Facetide, calls available upstream MCP tools. Never claim an uncalled source.",
                "Do semantic interpretation in the LLM. Keep source references, temporal validity and epistemic status.",
                "Return exactly seven domain observations (unknown allowed) and two qualitative axes.",
                "Distinguish observation from why the state is worthwhile/costly TO THIS USER.",
                "Attribute value explanations to explicit user expression, confirmed history, or an Agent hypothesis.",
                "Never infer subjective 1-5 satisfaction scores. Ask for those only at confirmation.",
                "StateBar snapshot is bounded and current-only, not a complete historical timeline.",
                "Submit one draft with facetide_stage_agent_review, then review it with the user.",
                "Freeze only the user's explicitly approved interpretation and ratings.",
            ],
            "note": "This endpoint is a normative schema/brief, not an LLM or an automatic tool orchestrator.",
        }

    def stage(self, period_start, period_end, evidence, domains, axes, agent_note=""):
        _period(period_start, period_end)
        sources = _validate_evidence(evidence)
        normalized_domains = _domains(domains, sources)
        normalized_axes = _axes(axes, sources)
        agent_note = _text(agent_note, "agent_note", 1000)
        body = {
            "protocol": "facetide.agent_handoff.v1",
            "period_start": period_start, "period_end": period_end,
            "evidence": list(sources.values()),
            "domains": normalized_domains, "axes": normalized_axes,
            "agent_note": agent_note,
        }
        draft_id = str(uuid.uuid4())
        created = _utc_now()
        body_hash = _hash(body)
        with self.store._connection() as db:
            db.execute(
                """INSERT INTO agent_handoff_drafts
                   (id,period_start,period_end,created_at,body_json,body_hash)
                   VALUES(?,?,?,?,?,?)""",
                (draft_id, period_start, period_end, created,
                 json.dumps(body, ensure_ascii=False, sort_keys=True), body_hash),
            )
        return {
            "draft_id": draft_id, "draft_hash": body_hash, "created_at": created,
            "status": "agent_proposal", "verification": "host_attested",
            "domain_count": 7, "axis_count": 2, "evidence_count": len(sources),
            "message": "Ready for review; no user ratings or goals were changed.",
        }

    def get(self, period_start, period_end):
        _period(period_start, period_end)
        with self.store._connection() as db:
            row = db.execute(
                """SELECT * FROM agent_handoff_drafts
                   WHERE period_start=? AND period_end=?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (period_start, period_end),
            ).fetchone()
        if row is None:
            return {"draft": None}
        return {
            "draft": {
                "draft_id": row["id"], "draft_hash": row["body_hash"],
                "created_at": row["created_at"],
                "status": "agent_proposal", "verification": "host_attested",
                **json.loads(row["body_json"]),
            },
        }

    def confirm(self, draft_id, expected_hash, domain_scores, user_confirmed,
                user_notes="", personal_growth=None, self_realization=None,
                revision_of=None):
        if user_confirmed is not True:
            raise ValidationError("Explicit user confirmation required")
        with self.store._connection() as db:
            row = db.execute("SELECT * FROM agent_handoff_drafts WHERE id=?", (draft_id,)).fetchone()
            if row is None:
                raise ValidationError("Unknown handoff draft")
            if row["body_hash"] != expected_hash:
                raise ValidationError("Draft hash changed, confirmation refused")
            body = json.loads(row["body_json"])
        if not isinstance(domain_scores, dict):
            raise ValidationError("domain_scores must be an object")
        growth = next(a for a in body["axes"] if a["axis"] == "personal_growth")
        realization = next(a for a in body["axes"] if a["axis"] == "self_realization")
        growth_text = growth["narrative"] if personal_growth is None else personal_growth
        realization_text = realization["narrative"] if self_realization is None else self_realization
        review = self.store.save_review(
            period_start=body["period_start"], period_end=body["period_end"],
            domain_scores=domain_scores, user_confirmed=True, user_notes=user_notes,
            personal_growth=growth_text, self_realization=realization_text,
            revision_of=revision_of,
        )
        # The approved draft remains immutable. Short host-attested source
        # summaries are referenced through the associated frozen draft; these
        # are NOT silently converted into independently verified facts.
        with self.store._connection() as db:
            db.execute(
                """INSERT INTO agent_review_links(review_id,draft_id,draft_hash)
                   VALUES(?,?,?)""",
                (review["review_id"], draft_id, expected_hash),
            )
        return {"review": review, "approved_draft_id": draft_id,
                "draft_hash": expected_hash, "verification": "host_attested"}
