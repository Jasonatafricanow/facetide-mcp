# Longitudinal State — Facetide v0.4

## Problem corrected

A semantic tag is not a persistent state. Earlier releases tagged each memory
but did not explain continuing conditions, comparisons against a reliable
baseline, goal strain, cross-domain costs, or consequential uncertainty.

## Two authoritative layers

- **Proposed observation**: source-cited current condition, possible trajectory,
  tradeoff, and two narrative axes. May be revised or withdrawn after source
  changes; the Agent is responsible for structured interpretation.
- **User-confirmed judgment**: personal 1–5 satisfaction, goal changes and final
  meaning of the period. No model-generated metrics or automatic goal escalation.

## Pipeline

1. Run source adapters and classify evidence with the existing semantic
   compilation tools.
2. Call `facetide_get_state_context` with the exact period. This returns
   seven evidence sets, two unscored axis candidates, existing user-owned goals,
   a previous-period state (if it exists), and an integrity token.
3. Prepare a **complete seven-domain state proposal**. Each domain may be
   unobserved. Do not assert progress or decline without an earlier,
   currently valid same-domain baseline.
4. Prepare two unscored axis narratives or leave them unknown. Any proposed
   claim requires verifiable source references.
5. Submit with `facetide_compile_state_report`. The service rejects a stale
   context token or invalid source citations. The resulting model proposal is
   append-only; interpretation edits create superseding versions.
6. The browser review displays this state above per-event evidence.
7. Ask the user only about consequential uncertainty and their *own* rating
   and interpretation. Confirmed snapshots are still separate immutable records.

## Domain-state representation

Each of the seven domains contains:

- `domain_id`: career / finance / health / family / social / leisure / environment
- `coverage`: observed, partial, or unobserved
- `picture`: short period-level condition based on cited evidence
- `direction`: initial, improved, stable, declined, mixed, or uncertain
- `direction_reason`: explicit explanation of meaningful change
- `confidence`: high, medium, low, unknown
- `evidence_refs`: original active source_type/source_ref pairs
- `goal_fit`: not_assessed, building, enough, strained, no_goal
- `goal_ids`: preexisting user goals, with no new goals silently created
- `tradeoffs`: another domain, its cost or benefit, and source citations
- `question`: one optional question about unresolved high-value uncertainty

A trend claim is **rejected** without a prior state report whose live source
references still validate. An unobserved domain cannot assert a sourced
condition. Evidence count is never a proxy for success, happiness, or
satisfaction.

## Two axes

`personal_growth` examines how life experience changed capabilities,
preferences, reasoning, commitments or boundaries. `self_realization`
examines actions/outcomes that manifest the user's own endorsed values. Both
are qualitative and *unscored*. A task completed does not by itself prove
self-realization.

## Integrity and version behavior

Every cited source is stored with a content fingerprint and revalidated on
reads. Stale sources mark the model proposal invalid and require recompilation.
Recompiling an identical period reuses its version; changed interpretation
appends a new proposal and preserves the earlier version. Changes to source
records, existing goals, or baseline change the context token.

## What still needs work

- A first-class long-lived **condition ledger** with validity intervals and
  episode semantics (to handle an ongoing condition when no event occurs in
  the current month). Current state reports are period-scoped proposals.
- User-calibrated domain importance, subjective values, enough/acceptable
  costs; feedback correction of wrong Agent hypotheses.
- Comparative causal interpretation on a real longitudinal dataset.
- Live MR-Mem and Nutrition NAS integration and semantic quality evaluation.
- Automatic triggering by the host Agent. A stdio MCP server cannot subscribe
  to every unrelated conversation, so the current process remains host-driven.

Do not mistake successful synthetic contract tests for production validation.
