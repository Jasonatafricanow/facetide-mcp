# Facetide v0.1 — architecture and invariants

## Scope

Facetide is an **external observational projection**, not a memory authority or a behavioral optimization engine. It records user-confirmed evaluation while referencing facts owned by specialist systems.

### Data flow

~~~text
Chat / MR-MEM events           Nutrition / other professional metrics
          |                                |
          +------ verified source adapters +
                           |
                  EvidenceSource.query
                           |
               prepare_review(period)
                           |
           Agent presents evidence + gaps
                           |
                    user judgment
                           |
              save_review(confirmed)
                           |
              immutable SQLite snapshot
~~~

The demo JSONL source stands in for verified upstream APIs. It is NOT a presumed MR-MEM wire protocol.

## Life domains and narrative axes

Seven domains: career, finance, health, family, social, leisure, environment.

The two narrative axes, personal growth and self-realization, are free-text reflection fields: **not** scored and **not** mutually exclusive with domains.

Satisfaction uses 1–5 integer scores, supplied only by a user. Absence is NULL/omitted, never zero and never an inferred decline. Facetide does not create a composite index.

## Goal lifecycle

- building — a desirable condition has not yet been achieved.
- maintaining — the enough condition is stably met; find minimum maintenance.
- reflecting — user reviews whether the objective and cost still make sense.
- simplifying — user eliminates expired or unnecessary process.

Lifecycle updates are explicit edits with expected_version to prevent accidental lost updates. Each goal may belong to multiple domains.

## Evidence invariants

- No raw conversations, nutrition reports, or clinical records are copied into Facetide's database.
- Every imported candidate has \`source_type\`, \`source_ref\`, \`occurred_at\`, and potentially \`known_at\`.
- Evidence may span multiple domains and is referenced once.
- \`evidence_kind\` distinguishes fact, user statement, inference.
- Retraction and supersession remain visible; neither is selectable as active evidence in a fresh review.
- JSONL is a deliberately simple bridge; production adapters must implement origin-specific permissions, paging, and failure semantics.
- No evidence is treated as an instruction to the Agent.
- Incomplete upstream timelines must not be "fixed" with guessed timestamps.

## Review invariants

- User confirmation is required for every persisted review.
- Snapshot freezes the goal definitions/versions at the time of confirmation, as well as ratings and selected evidence metadata.
- A correction creates a new record linked via \`revision_of\`, not a SQL UPDATE.
- The system stores the original review for historical truth, not merely the newest target.
- Candidate change bands are suggestions, not objective truth: the user approves what to keep.
- Date scoping applies to \`occurred_at\`; \`known_at\` remains separately available to understand late discovery.

## Security and privacy

SQLite file is local-only and chmod 600 on POSIX. External evidence JSONL is read-only. There is no telemetry and no network listener in v0.1.

The \`user_confirmed\` argument is necessary but not sufficient to verify actual user consent; MCP clients must honor the tool descriptions and obtain confirmation in their UI before invoking mutations.

For multi-user deployment, secure per-user isolation and authentication must be designed separately. Do not share the single-user database among unrelated users.

## Deferred

Native MR-MEM and Nutrition API clients; streaming HTTP transport and authentication; a standalone wheel UI; multiple profiles; social features; automatic sentiment rating; periodic background scheduler. None are required for the local MVP.
