# Facetide

**Agent-native personal life observation and reflection, implemented as a local-first MCP server.**

Facetide does not calculate a happiness score, replace your memory system, or require daily check-ins. It organizes existing evidence for periodic reflection; only the user decides whether a domain is satisfying, what counts as enough, and whether a goal is worth continuing.

## Current version: 0.2.0 — Agent core + browser workbench

In addition to the MCP protocol, v0.2 includes a **local four-view workbench** with a seven-sector wheel, guided period reviews, selected evidence refs, goal lifecycle editor and immutable history.

Start it separately from the MCP server:

~~~sh
facetide-web
# local URL: http://127.0.0.1:8765
~~~

See [Product workbench and MR-Mem setup](docs/product-workbench.md). The UI and the MCP server share the same SQLite database and can run separately.

**Optional native read-only MR-Mem AML adapter:** specify both `FACETIDE_MRMEM_DIR` and `FACETIDE_MRMEM_USER_ID`. It projects verified canonical memories from existing `memory.sqlite` and `aml_source.sqlite` with scoped fingerprints, no runtime migrations. Missing life-domain classification is left unclassified, not fabricated. This adapter has synthetic-contract tests but not live-production validation.

## MVP status

- Seven life domains with optional **user-owned 1–5 ratings**.
- Two unscored narrative axes: **personal growth** and **self-realization**.
- Goals with **building / maintaining / reflecting / simplifying** states, "enough" conditions, and optional outcome / driver / guardrail indicators.
- A goal can support multiple life domains.
- Immutable confirmed review snapshots (including goal versions), append-only corrections, score history.
- Read-only **JSONL evidence adapter** with source references, separate occurred/known timestamps, explicit retraction, and cross-domain links.
- Five stdio MCP tools plus a reflection prompt, local workbench, SQLite persistence, no telemetry.

This is a runnable single-user core and local workbench. A narrow MR-Mem **AML read-only adapter** is implemented, using Atlas's published storage contract; Nutrition-Tracker-MCP native integration and broader MR-Mem contracts are deferred.

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
