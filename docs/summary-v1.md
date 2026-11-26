# facetide.summary.v1 — read-only life summary for an outside dashboard

Consumer: Agent-WorkBench (`LifeStateAdapter`, Life view). Facetide stays the only authority for life
reviews, scores and goals; the consumer may cache the response for display but never treats it as its
own data and never writes back.

## Endpoint

```
GET /api/summary/v1            (on the local Facetide web server, `facetide-web`)
Authorization: Bearer <FACETIDE_SUMMARY_TOKEN>
```

- The route exists only when `FACETIDE_SUMMARY_TOKEN` (at least 24 characters) is set when the server
  starts; otherwise it answers 404.
- Wrong or missing token: 401. The browser session token from `/api/bootstrap` is **not** accepted.
- GET only, no query parameters, no write path (POST to this path is 404).
- The server still only answers loopback `Host` headers (`127.0.0.1` / `localhost`), as every other route.

### Service listener (dashboard in another container)

`FACETIDE_SUMMARY_LISTEN=host:port` (for example `0.0.0.0:8875`) opens a second socket next to the
loopback UI. It serves **only** `GET /api/summary/v1` with the same bearer token; every other path and
method is 404, there is no UI and no `/api/bootstrap`. Its Host header is not checked, so keep the port
behind a firewall that only lets the LAN/Docker in. It starts only when the summary token is set.

## Response

```json
{
  "contract": "facetide.summary.v1",
  "generated_at": "2026-11-17T08:00:00Z",
  "score_scale": {"min": 0, "max": 10, "step": 0.5},
  "domains": [{"domain_id": "career", "name": "Work & career"}, "... seven in total"],
  "latest": {
    "review_id": "…", "period_start": "2026-11-01", "period_end": "2026-11-15",
    "confirmed_at": "…",
    "domain_scores": {"career": 7.5, "finance": null, "...": "all seven keys, null when not scored"},
    "personal_growth": "user's own reflection text, or null",
    "self_realization": "user's own reflection text, or null"
  },
  "previous": "same shape: latest confirmed review of the period before `latest`, or null",
  "goals": [{"goal_id": "…", "title": "…", "enough_condition": "…", "status": "building",
             "domain_ids": ["health"], "updated_at": "…"}]
}
```

Rules:

- Only user-confirmed reviews exist in the `reviews` table; agent drafts, compiled evidence and the
  longitudinal state report are never read by this route.
- `latest` is the newest confirmed revision of the most recent period; `previous` is the newest
  confirmed revision of an *earlier* period (a revision of the same period is not "previous").
- `personal_growth` / `self_realization` are text, not scores.
- Not returned: evidence refs, user notes, approved draft bodies, goal indicators, goals snapshots,
  raw conversation, nutrition or clinical data.
