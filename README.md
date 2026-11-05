# Facetide

**Agent-native personal life observation and reflection, implemented as a local-first MCP server.**

Facetide does not calculate a happiness score, replace your memory system, or require daily check-ins. It organizes existing evidence for periodic reflection; only the user decides whether a domain is satisfying, what counts as enough, and whether a goal is worth continuing.

## Current version: 0.5.1 — Compact MCP tool discovery

In addition to the MCP protocol, v0.2 includes a **local four-view workbench** with a seven-sector wheel, guided period reviews, selected evidence refs, goal lifecycle editor and immutable history.

Start it separately from the MCP server:

~~~sh
facetide-web
# local URL: http://127.0.0.1:8765
~~~

See [Product workbench and MR-Mem setup](docs/product-workbench.md). The UI and the MCP server share the same SQLite database and can run separately.

**Optional native read-only MR-Mem AML adapter:** specify both `FACETIDE_MRMEM_DIR` and `FACETIDE_MRMEM_USER_ID`. It projects verified canonical memories from existing `memory.sqlite` and `aml_source.sqlite` with scoped fingerprints, no runtime migrations. Missing life-domain classification is left unclassified, not fabricated. This adapter has synthetic-contract tests but not live-production validation.

## Default MCP interface: exactly three tools

The core Agent workflow is exposed with three tools, not the old fifteen:

| Tool | When to use |
| --- | --- |
| `facetide_context(period_start,period_end,history_limit=0)` | Start/resume a period. Returns protocol, goals, earlier user assessments, latest staged draft, current-period confirmed review with its frozen 7+2 draft, optional review history |
| `facetide_draft(period_start,period_end,evidence,domains,axes)` | After the **host LLM** reads StateBar/MR-MEM/other data and interprets what it means to the user, stage exactly 7+2 sourced observations |
| `facetide_confirm(draft_id,expected_hash,domain_scores,user_confirmed)` | Only after explicit user approval, freeze their ratings and narrative against the exact draft |

The browser's goal editor remains available without exposing another Agent tool.
When user-directed goal edits through chat are required, opt in to one additional
tool with `FACETIDE_ENABLE_GOAL_TOOL=1`.

All fifteen original MCP tool names still exist for migration only:

~~~sh
FACETIDE_TOOL_PROFILE=legacy facetide-mcp
~~~

Default is `FACETIDE_TOOL_PROFILE=compact`. Setting `legacy` exposes the
three current tools **plus all fifteen original tools**, not only the original
tools. No changes to SQLite schemas or old Python method imports are required.

The `facetide_reflection_guide` MCP prompt explains the three-tool workflow,
and `facetide_context` returns the full handoff JSON Schema **only on demand**.
The host LLM still performs semantic interpretation. This is *progressive
disclosure*: the default tool inventory is small while the protocol's deep
requirements are provided when the Agent needs them.

**Important:** Fewer exposed tools is a discovery-surface improvement, not a
measured improvement in live Agent tool accuracy. Real-world turn counts,
parameter errors, and correction rates still need evaluation.

## Recommended: Agent-led 7+2 standardization


Facetide is **not** an additional cognition engine. The host LLM calls any
connected StateBar-MCP, MR-MEM / ATLAS and specialist MCP tools, interprets
the conversation using the user's expressed values, then submits one
standardized 7+2 review draft.

The normative workflow is [Agent Handoff v1](docs/agent-handoff-v1.md).

- `facetide_context`: returns previous confirmed review, user goals,
  machine-readable JSON Schema and the latest staged draft.
- `facetide_draft`: stages exactly seven domain observations and two unscored
  axes with provider-scoped sources and explicit value-judgment attribution.
- `facetide_confirm`: links the explicitly approved draft to an immutable
  review containing the user's own optional 1–5 ratings.

Existing `facetide_compile_batch` and `facetide_compile_state_report`
are retained for backward compatibility, **not the recommended Agent workflow**.
Their semantic pipeline should not be required in a normal Facetide integration.

## Legacy experimental longitudinal state synthesis

The optional host Agent can now compile a **whole-period state** after source classification. Use `facetide_get_state_context` to obtain cited domain evidence, a prior state baseline, goals and a source-sensitive context token. The Agent then calls `facetide_compile_state_report` with exactly seven domain states and two unscored narrative axes. Each domain can distinguish observed/partial/unobserved evidence, current condition, cautious direction of change, reason, confidence, goal strain, cross-domain tradeoffs and one targeted follow-up question. Without a verified prior baseline, the service rejects invented improvement/decline/stability claims.

State reports are **append-only model proposals**, not user evaluation; their cited sources are rechecked at read time and stale reports are explicitly flagged. The browser review now displays these higher-level state summaries above individual evidence, while satisfaction ratings remain user-only. For details, see [Longitudinal State Contract](docs/longitudinal-state.md).

## Legacy optional semantic compilation

Requires `FACETIDE_TOOL_PROFILE=legacy`. See [Semantic Assembly](docs/semantic-assembly.md) for the source-backed cross-domain compilation loop. Connect the MCP server to an existing conversational Agent and explicitly request the legacy compilation workflow. The default reflection prompt uses the three-tool handoff. In legacy mode the host Agent calls `facetide_get_compilation_batch`, interprets each item semantically (including irrelevant ones), calls `facetide_compile_batch`, and then queries `facetide_prepare_review`. This creates seven populated evidence cards and two editable, cited narrative axes. **Users only need to assess their own satisfaction scores and final judgment.**

The compiler is a rebuildable materialized projection with source hash validation. It never changes canonical MR-Mem, never promotes agent-generated narratives into user statements, and never auto-scores. The local Web UI alone cannot semantically compile records: the host Agent must trigger the MCP workflow.

### Legacy host source bridge (opt-in)

For the legacy bridge tool, enable `FACETIDE_TOOL_PROFILE=legacy` and configure an explicit allowlist. The default handoff instead accepts host-supplied evidence directly in `facetide_draft`:

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
- Three default stdio MCP tools, optional goal-edit tool, opt-in legacy tools, reflection prompt, local workbench, SQLite persistence, no telemetry.

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

## Legacy tool reference

The following compatibility tools require `FACETIDE_TOOL_PROFILE=legacy`; they are not the default workflow.

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

## First review (default profile)

1. Call `facetide_context(period_start, period_end)` to read the schema, goals and prior confirmed review.
2. The host Agent reads its connected upstream tools and stages a sourced 7+2 interpretation with `facetide_draft`.
3. Present the draft and attribution to the user; only the user supplies optional satisfaction ratings.
4. After explicit approval, call `facetide_confirm` with the exact draft ID and hash.
5. Resume with `facetide_context` for the same period: `confirmed_review.approved_draft` is the frozen interpretation; `latest_draft` may be a newer, unapproved proposal. Use `history_limit=1..20` for additional confirmed reviews.

Confirmed review narratives contain any user corrections. The linked `approved_draft` retains the original staged interpretation and host-attested provenance, not independently verified source truth. Earlier-period reviews and history also include their linked drafts. Manual legacy reviews have `approved_draft=null`.

For corrections, pass the earlier `review_id` as `revision_of` for the same period. Existing snapshots are never overwritten. Goal editing is available in the workbench or through the opt-in goal tool.

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
