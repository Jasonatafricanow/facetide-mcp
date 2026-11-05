# Facetide

**Agent-native personal life observation and reflection, implemented as a local-first MCP server.**

Facetide does not calculate a happiness score, replace your memory system, or require daily check-ins. It organizes existing evidence for periodic reflection; only the user decides whether a domain is satisfying, what counts as enough, and whether a goal is worth continuing.

## Current version: 0.4.0 — Longitudinal life-state synthesis

In addition to the MCP protocol, v0.2 includes a **local four-view workbench** with a seven-sector wheel, guided period reviews, selected evidence refs, goal lifecycle editor and immutable history.

Start it separately from the MCP server:

~~~sh
facetide-web
# local URL: http://127.0.0.1:8765
~~~

See [Product workbench and MR-Mem setup](docs/product-workbench.md). The UI and the MCP server share the same SQLite database and can run separately.

**Optional native read-only MR-Mem AML adapter:** specify both `FACETIDE_MRMEM_DIR` and `FACETIDE_MRMEM_USER_ID`. It projects verified canonical memories from existing `memory.sqlite` and `aml_source.sqlite` with scoped fingerprints, no runtime migrations. Missing life-domain classification is left unclassified, not fabricated. This adapter has synthetic-contract tests but not live-production validation.

## Longitudinal state: beyond seven classified event lists

The optional host Agent can now compile a **whole-period state** after source classification. Use `facetide_get_state_context` to obtain cited domain evidence, a prior state baseline, goals and a source-sensitive context token. The Agent then calls `facetide_compile_state_report` with exactly seven domain states and two unscored narrative axes. Each domain can distinguish observed/partial/unobserved evidence, current condition, cautious direction of change, reason, confidence, goal strain, cross-domain tradeoffs and one targeted follow-up question. Without a verified prior baseline, the service rejects invented improvement/decline/stability claims.

State reports are **append-only model proposals**, not user evaluation; their cited sources are rechecked at read time and stale reports are explicitly flagged. The browser review now displays these higher-level state summaries above individual evidence, while satisfaction ratings remain user-only. For details, see [Longitudinal State Contract](docs/longitudinal-state.md).

## The actual 7+2 data pipeline

See [Semantic Assembly](docs/semantic-assembly.md) for the source-backed cross-domain compilation loop. Connect the MCP server to an existing conversational Agent and invoke its `facetide_reflection_guide` prompt. The host Agent calls `facetide_get_compilation_batch`, interprets each item semantically (including irrelevant ones), calls `facetide_compile_batch`, and then queries `facetide_prepare_review`. This creates seven populated evidence cards and two editable, cited narrative axes. **Users only need to assess their own satisfaction scores and final judgment.**

The compiler is a rebuildable materialized projection with source hash validation. It never changes canonical MR-Mem, never promotes agent-generated narratives into user statements, and never auto-scores. The local Web UI alone cannot semantically compile records: the host Agent must trigger the MCP workflow.

### Other MCP sources (opt-in generic bridge)

To include future providers without writing a new native adapter, configure an explicit allowlist:

~~~sh
export FACETIDE_BRIDGE_ALLOWED_SOURCES=calendar,github
~~~

A host Agent can query these other MCP providers and forward **only a compact observation with a real original provider record ID, occurred/known times, and optional domain tags** to `facetide_publish_source_bundle`. The bridge stores revisable source-referenced projections, not full provider data. It is disabled by default. **The host-attested observations are not independently verified by Facetide**, and revisions/deletions must be republished by the host. Do not send full transcripts, clinical records, credentials, or secrets.

## MVP status

- Seven life domains with optional **user-owned 1–5 ratings**.
- Two unscored narrative axes: **personal growth** and **self-realization**.
- Goals with **building / maintaining / reflecting / simplifying** states, "enough" conditions, and optional outcome / driver / guardrail indicators.
- A goal can support multiple life domains.
- Immutable confirmed review snapshots (including goal versions), append-only corrections, score history.
- Read-only **JSONL evidence adapter** with source references, separate occurred/known timestamps, explicit retraction, and cross-domain links.
- Eight stdio MCP tools (including a two-stage semantic compiler and optional host source bridge) plus reflection prompt, local workbench, SQLite persistence, no telemetry.

This is a runnable single-user core and local workbench. Narrow MR-Mem **AML** and Nutrition-Tracker-MCP **recent 7/30-day report** read-only adapters are implemented against their published contracts. Broader historical integrations and live NAS verification remain outstanding.

## Install

Python **3.11+**:

~~~sh
git clone https://github.com/Jasonatafricanow/facetide-mcp.git
cd facetide-mcp
python -m pip install -e .
python -m unittest discover -s tests -v
~~~

Start a local MCP server with:

~~~sh
facetide-mcp
# alternatively: python -m facetide
~~~

The process communicates over **stdio**. Do not expect a web page or normal console output.

Example MCP host configuration (replace the executable path for your environment):

~~~json
{
  "mcpServers": {
    "facetide": {
      "command": "facetide-mcp",
      "env": {
        "FACETIDE_DB_PATH": "/absolute/private/path/facetide.sqlite3",
        "FACETIDE_EVIDENCE_FILE": "/absolute/private/path/observations.jsonl"
      }
    }
  }
}
~~~

The evidence file environment variable is optional. Without it, Facetide still supports scores, goals, and manual review notes. The database defaults to \`~/.local/share/facetide/facetide.sqlite3\` (or the platform's \`XDG_DATA_HOME\`).

## Tools

| MCP tool | Operation |
| --- | --- |
| \`facetide_get_snapshot\` | Seven domains, latest ratings, goals and status |
| \`facetide_publish_source_bundle\` | Optional host-bridged source projections from allowed providers |
| \`facetide_get_compilation_batch\` | Read bounded multi-source records for host Agent classification |
| \`facetide_compile_batch\` | Persist source-verified provisional 7+2 mappings and narrative proposals |
| \`facetide_prepare_review\` | Time-bounded evidence + previous snapshot + candidate changes |
| \`facetide_upsert_goal\` | Create/replace a user-approved goal, checking version on edits |
| \`facetide_save_review\` | Freeze a user-approved review with source refs |
| \`facetide_get_history\` | Review history and optional domain filter |

Input dates are inclusive \`YYYY-MM-DD\`. Omit unscored domains rather than guessing a value. Every write requires \`user_confirmed=true\` and actual user approval in the calling Agent. The flag is an application contract, not proof of consent.

### First review

1. Use \`facetide_get_snapshot\` to see currently rated domains.
2. Discuss seven life domains, but allow the user to rate just a subset.
3. If the user wants a goal, define its **enough condition** and associate one or more domains before \`facetide_upsert_goal\`.
4. Use \`facetide_prepare_review\` for the desired date interval.
5. Summarize only evidence with its source; treat uncertain/inferred entries as uncertain. Ask for the user's score and interpretation.
6. Call \`facetide_save_review\` only after the user confirms. Query \`facetide_get_history\` for comparison next time.

For corrections, pass the earlier \`review_id\` as \`revision_of\` for the same period. Existing snapshots are never overwritten.

## Read-only evidence bridge

Set \`FACETIDE_EVIDENCE_FILE\` to a UTF-8 **JSONL** file containing one standardized observation per line. A sample is in [examples/evidence.jsonl](examples/evidence.jsonl).

~~~json
{
  "source_type": "mr-memory",
  "source_ref": "event-123",
  "occurred_at": "2026-10-17",
  "known_at": "2026-11-02T10:00:00+00:00",
  "domain_ids": ["health", "leisure"],
  "evidence_kind": "user_statement",
  "resolution_status": "active",
  "change": "new",
  "summary": "A brief and source-grounded description"
}
~~~

Each source decides its own event IDs and truthful timestamps. \`source_type + source_ref\` identifies an observation; a later JSONL line with the same pair supersedes its earlier version. A retracted/superseded record can be reviewed, but cannot be linked as active evidence in a new confirmed review.

\`change\` is an *explicit source-supplied classification*, not Facetide's automatic guess. Valid values: \`new\`, \`stable\`, \`receding\`, or omit it. Missing observations are **not** treated as deterioration.

The adapter reads the file on demand and leaves original evidence under external control. Only minimal reference metadata (no summary/body) is frozen into a confirmed review. Do not export entire private chats or health records unless you explicitly intend to expose them to your Agent host.

For real MR-MEM / ATLAS / Nutrition adapters: implement the \`EvidenceSource.query(start, end, domains)\` protocol in \`src/facetide/sources.py\`; map the upstream source's actual schema and retain original IDs and timing. See [architecture](docs/architecture.md).

## Product boundaries

- **User owns satisfaction ratings, interpretations, and goal changes.** Evidence must not automatically update them.
- **No daily habit gate, gamification, or automatic happiness composite.**
- **No independent chat-memory engine, and no automatic write-back to MR-MEM slow state.**
- **No unverified medical or financial recommendations.**
- Single-user local process; do not expose the stdio service as an unauthenticated network endpoint.

## Tests

~~~sh
python -m unittest discover -s tests -v
~~~

The tests cover partial scores, explicit confirmation, goal version conflict, source retraction, chronological association, and immutable goal/review history.

## Next integration milestone

Wire a verified MR-MEM event read API (including LCE \`occurred_at\` / \`known_at\`, source revision status), then optionally read aggregate health records from Nutrition-Tracker-MCP. Neither upstream system should be made dependent on Facetide.
