# Facetide Agent Handoff v1 — normative protocol

Facetide is a structured **output, review and history** MCP. The host LLM,
not Facetide, performs semantic interpretation using the tools it already has.
It must explain **why a state is or is not worthwhile to this particular user**
and distinguish what the user said from the Agent's hypothesis.

## Ownership

- Host LLM: dialog understanding, relevant information selection, 7+2
  classification, subjective value explanation, source-based synthesis.
- MR-MEM / ATLAS: long-term memory and original source history.
- StateBar-MCP: short-lived current state, state validity, plans and changes.
- Nutrition and other MCPs: professional facts and metrics.
- Facetide: standardized handoff protocol, structural/source-reference checks,
  provisional drafts, user confirmation, immutable review history.

## Mandatory Agent interaction

1. Call `facetide_agent_brief(start,end)`. It returns the user's prior confirmed
   review, existing goals and the *machine-readable handoff schema*.
2. Call the upstream tools **as the host Agent**. If StateBar is connected,
   use real documented MCP tools and a known scoped `subject_id`:
   - `user_state.snapshot({subject_id,query?})` — bounded current context.
   - `user_state.get_state({subject_id,category?,key?})` — current states,
     stable state IDs, validity, certainty and status.
   - `user_state.context_candidates({subject_id})` — relevant current buckets.
   Do not call `user_state.observe` simply to produce a review. StateBar's
   snapshot is limited and does NOT replace MR-MEM history.
3. Bring in long-term memories and specialist MCP records if these systems
   are actually available. Never invent an uncalled source or provider ID.
4. The LLM reasons over facts, explicit preferences, goals and costs. Submit
   exactly seven domain records and two narrative axes using
   `facetide_stage_agent_review`. The output is a *draft*, not user truth.
5. Show the proposed observation and its attribution to the user. Ask only
   about material uncertainty. Solicit 1–5 satisfaction ratings for whichever
   domains the user wants to rate; allow omissions.
6. Call `facetide_confirm_agent_review` only after the user approves the
   exact draft, any narrative edits and the ratings. Preserve the immutable
   draft linkage and confirmed review.

No second LLM service or recurring semantic recompiler is required. Earlier
`facetide_compile_batch` and `facetide_compile_state_report` remain available
for compatibility, but are not the recommended workflow.

## Shared evidence registry

Each candidate is referenced once with a short unique `evidence_id`.
For example:

~~~json
{
  "evidence_id": "sb1",
  "provider": "statebar",
  "source_ref": "real-state-id",
  "source_tool": "user_state.get_state",
  "occurred_at": "2026-11-03T10:00:00+00:00",
  "known_at": "2026-11-03T10:00:00+00:00",
  "valid_until": "2026-11-05T18:00:00+00:00",
  "status": "active",
  "kind": "state",
  "summary": "Concise sourced observation, not raw user transcript"
}
~~~

The only certainty Facetide itself can assert is that the host supplied an
ID, time and summary consistent with its schema: `host_attested`.
Native providers may change or revoke records later; Facetide does **not**
independently verify their existence. The caller must not silently treat an
expired StateBar plan as a current lifelong condition.

## One of seven domain records

~~~json
{
  "domain_id": "career",
  "coverage": "partial",
  "observation": "The user is working on a project; results are not yet known",
  "evidence_refs": ["sb1"],
  "direction": "unknown",
  "comparison_basis": "",
  "meaning": {
    "assessment": "mixed",
    "basis": "agent_hypothesis",
    "why": "Based on the user's previously expressed limits, this may be worthwhile but costly",
    "evidence_refs": ["mem1"]
  },
  "question": "Is the time cost still acceptable?"
}
~~~

`meaning` deliberately separates factual events from subjective usefulness.

- `assessment`: worthwhile / costly / mixed / uncertain.
- `basis`: user_explicit / user_confirmed_history / agent_hypothesis / unknown.
- `why`: explanation relative to this user's values and accepted costs.
- `evidence_refs`: IDs in the same staged evidence registry.

The *Agent* makes these judgments, not Facetide. A hypothesis remains
provisional, never automatically labeled as a user-endorsed value.
An unknown domain has no asserted observation or source; absence of a
record is not evidence of deterioration.

## Two qualitative axes

- `personal_growth`: how experience has changed the user's capacities,
  perspective, boundaries or commitments.
- `self_realization`: the user's actions and outcomes relative to values
  they have personally expressed.

Each axis has status proposed/unknown, narrative, evidence_refs and basis.
A proposed axis needs sourced reasoning; otherwise use unknown. Neither
axis receives a numerical score.

## Ratings and immutability

`facetide_stage_agent_review` never accepts or writes subjective satisfaction
ratings. It returns an immutable draft_id and draft_hash.

`facetide_confirm_agent_review` requires the draft ID/hash and explicit
user confirmation, accepts their own optional 1–5 scores and narrative
corrections, writes a confirmed review, and links the approved draft.
Changing an Agent's interpretation produces a new draft, not a silent
overwrite of the old one.

## Limitations

- MCP tool descriptions and schemas guide Agents but cannot compel an
  external LLM to invoke another MCP, nor prove it followed instructions.
- Facetide performs structural validation but cannot establish semantic
  truth or prove a value was really expressed by a user; citations in an
  Agent handoff are provider IDs and are **host-attested**.
- The present StateBar public interface exposes current state, not a full
  arbitrary-period transition query; longitudinal data must come from
  other available sources or explicitly indicate unknown.
- Real multi-MCP production evaluation is still required.
