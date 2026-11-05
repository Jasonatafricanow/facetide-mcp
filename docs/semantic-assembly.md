# Semantic Assembly — the missing Facetide 7+2 pipeline

## Problem corrected

The original workbench had seven blank rating forms and two blank narrative fields. MR-Mem returned source-verified semantic memories, but few native items had \`facetide_domains\` tags. As a result, more source data did not fill the life cards. This version introduces a **real compilation handoff** from host Agent to a sourced, rebuildable Facetide view.

Do not confuse the two kinds of state:

- **Evidence projection (machine-compiled):** Life domain associations, extracted observation, possible changes, cross-event growth/self-realization inferences, uncertainty, source references.
- **User judgment (user-confirmed):** 1–5 satisfaction, whether a goal is enough, the final narrative reflection.

The first is automatically assembled *when an MCP-enabled host Agent invokes the compilation workflow*. The second remains owned by the user. The standalone Web UI has no autonomous LLM and cannot compile unclassified memories by itself.

## Multi-source pipeline

\`\`\`text
Existing chat / MR-Mem AML       Nutrition Tracker 7/30d       optional JSONL
         |                               |                         |
         +----------- scoped read-only source adapters -----------+
                                 |
                      Identity + source revision check
                                 |
                facetide_get_compilation_batch (paged, 25)
                                 |
             Host Agent semantic classifier (not keyword rules)
                |         |                       |
            7 domains    change          2 cross-event axes
                |         |                       |
                +--- facetide_compile_batch -------+
                         | source hash checked
                   compiled_evidence / compiled_axes
                      (rebuildable, scoped metadata)
                                 |
                    facetide_prepare_review
                         |
           Seven populated evidence cards + two axis drafts
                         |
             User sees/edits/sets satisfaction scores
                         |
            facetide_save_review (confirmed snapshot)
\`\`\`

### What the host Agent does

1. Read the current review period and \`facetide_get_compilation_batch\` with offset 0, limit 25. This is a **bounded** view over already compiled MR-Mem semantics, not a replay of raw chat.
2. For each **active** event assign 0..7 domain IDs, with evidence preserved. If genuinely irrelevant use \`domain_ids: []\`. Never guess a life domain based only on a source's provider name.
3. Explain the observation briefly; distinguish what the user **said**, what the source **measured**, and what an Agent **inferred**. Assign \`change\` only if supported by temporal comparison; otherwise \`unknown\`. Use confidence low/medium/high.
4. Identify meaningful changes in the person's interpretation or in the world that were **actually supported by the events**. Supply \`axis_insights\` with current citations, not generic personal-growth platitudes.
5. Call \`facetide_compile_batch\` using the exact batch fingerprint and a classification for **every active event**, including explicit out-of-scope ones. Repeat for \`next_offset\` until null.
6. Read \`facetide_prepare_review\`. Seven domain cards and two axes now contain source-anchored suggestions. Show the user the synthesis, but **never create/confirm ratings or long-term goals without their judgment**.

The classifier can run in whatever host Agent already serves the user's conversations. Facetide does not need to buy another inference model, save raw chat transcripts or invent a separate personality profile.

### Protocol example (synthetic)

First, \`facetide_get_compilation_batch({"period_start":"2026-10-01","period_end":"2026-10-31","offset":0,"limit":25})\`.

For each active returned record, the Agent provides:

\`\`\`json
{
  "source_type": "mrmem",
  "source_ref": "memory-17",
  "domain_ids": ["career", "finance"],
  "axis_ids": ["personal_growth"],
  "observation": "User changed role and began valuing working time differently",
  "reason": "The semantic memory explicitly describes the job transition",
  "change": "unknown",
  "confidence": "medium"
}
\`\`\`

It submits the array via \`facetide_compile_batch\` with matching dates/offset/limit/fingerprint. A cross-event axis insight is also supported:

\`\`\`json
{
  "axis": "personal_growth",
  "summary": "A role change prompted a more explicit boundary around working time",
  "evidence_refs": [
    {"source_type":"mrmem","source_ref":"memory-17"},
    {"source_type":"mrmem","source_ref":"memory-23"}
  ]
}
\`\`\`

Values, sources and events are illustrative, not user's real records.

## Guaranteed properties

- Seven domains always exist as evidence **slots**, even when empty.
- A source can affect several domains. The same memory remains one source identity.
- Two narrative axes are unscored; every compiled axis insight has one or more live citations.
- Semantic assignments do **not** become canonical MR-Mem memory and do **not** change user satisfaction scores.
- The DB caches only short explanatory projections and source hashes, never full native chat bodies.
- Source modification/retraction invalidates the matching model projection on next read; old confirmed reviews remain immutable.
- Compiling the same record again is idempotent, and a changed batch fingerprint requires refetch.
- Missing records remain marked unknown; unknown does not mean failure, decline, or absent life activity.
- Zero relevant sources correctly yields seven evidence gaps and two unknown axes.

## Not yet solved

- No automatic tool invocations on every host message. The host must explicitly run the provided MCP compilation workflow, possibly as a host-side routine. A stdio MCP server alone cannot subscribe to all conversations.
- An MR-Mem AML semantic store may lack a trusted event time or be capped to 2,000 records per query by its existing adapter. Source coverage is consequently incomplete; warnings and pending counts are surfaced.
- No end-to-end integration on private MR-Mem/Nutrition production deployment, no formal precision/recall benchmark of the host classifier, and no automatic causal truth guarantee.
- Narrative compilations are suggestions, not authenticated user self-reports. Their provenance and uncertainty must be presented honestly.
