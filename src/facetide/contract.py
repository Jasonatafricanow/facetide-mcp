"""Machine-readable handoff v1 JSON Schema returned to the host LLM."""

_TEXT = {"type": "string"}
_REFS = {"type": "array", "items": _TEXT, "maxItems": 100, "uniqueItems": True}
_MEANING = {
    "type": "object",
    "required": ["assessment", "basis", "why", "evidence_refs"],
    "properties": {
        "assessment": {"enum": ["worthwhile", "costly", "mixed", "uncertain"]},
        "basis": {"enum": ["user_explicit", "user_confirmed_history", "agent_hypothesis", "unknown"]},
        "why": _TEXT,
        "evidence_refs": _REFS,
    },
    "additionalProperties": False,
}
HANDOFF_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Facetide Agent Handoff v1",
    "type": "object",
    "required": ["period_start", "period_end", "evidence", "domains", "axes"],
    "properties": {
        "period_start": {"type": "string", "format": "date"},
        "period_end": {"type": "string", "format": "date"},
        "evidence": {
            "type": "array", "maxItems": 100, "items": {
                "type": "object",
                "required": ["evidence_id", "provider", "source_ref", "occurred_at", "summary"],
                "properties": {
                    "evidence_id": _TEXT, "provider": _TEXT, "source_ref": _TEXT,
                    "source_tool": _TEXT, "occurred_at": {"type": "string"},
                    "known_at": {"type": ["string", "null"]},
                    "valid_until": {"type": ["string", "null"]},
                    "status": {"enum": ["active", "resolved", "expired", "retracted", "unknown"]},
                    "kind": {"enum": ["user_statement", "state", "measurement", "event", "model_inference"]},
                    "summary": _TEXT,
                },
                "additionalProperties": False,
            },
        },
        "domains": {
            "type": "array", "minItems": 7, "maxItems": 7,
            "items": {
                "type": "object", "required": [
                    "domain_id", "coverage", "observation", "evidence_refs", "meaning"
                ],
                "properties": {
                    "domain_id": {"enum": [
                        "career", "finance", "health", "family", "social", "leisure", "environment"
                    ]},
                    "coverage": {"enum": ["observed", "partial", "unknown"]},
                    "observation": _TEXT,
                    "evidence_refs": _REFS,
                    "direction": {"enum": ["improving", "stable", "worsening", "mixed", "unknown"]},
                    "comparison_basis": _TEXT,
                    "meaning": _MEANING,
                    "question": _TEXT,
                },
                "additionalProperties": False,
            },
        },
        "axes": {
            "type": "array", "minItems": 2, "maxItems": 2,
            "items": {
                "type": "object",
                "required": ["axis", "status", "narrative", "evidence_refs", "basis"],
                "properties": {
                    "axis": {"enum": ["personal_growth", "self_realization"]},
                    "status": {"enum": ["proposed", "unknown"]},
                    "narrative": _TEXT,
                    "evidence_refs": _REFS,
                    "basis": {"enum": [
                        "user_explicit", "user_confirmed_history", "agent_hypothesis", "unknown"
                    ]},
                },
                "additionalProperties": False,
            },
        },
        "agent_note": _TEXT,
    },
    "additionalProperties": False,
}
