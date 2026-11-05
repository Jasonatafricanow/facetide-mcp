"""SQLite-backed Facetide domain, goal and immutable review services."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .sources import EmptySource, EvidenceSource, JsonlSource
from .adapters import CompositeSource, MrMemAmlSource, NutritionMcpSource

DOMAINS = {
    "career": "Work & career",
    "finance": "Finance & security",
    "health": "Body & health",
    "family": "Love & family",
    "social": "Friends & social",
    "leisure": "Rest & play",
    "environment": "Home & environment",
}
DOMAIN_IDS = frozenset(DOMAINS)
GOAL_STATES = frozenset({"building", "maintaining", "reflecting", "simplifying"})
CHANGE_TYPES = frozenset({"new", "stable", "receding"})


class ValidationError(ValueError):
    """Unconfirmed or invalid product input."""


class GoalConflict(ValidationError):
    """Optimistic concurrency prevented a lost goal edit."""


def _day(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Use YYYY-MM-DD dates") from exc
    if parsed.isoformat() != value:
        raise ValidationError("Use YYYY-MM-DD dates")
    return value


def _period(start: str, end: str) -> None:
    _day(start)
    _day(end)
    if start > end:
        raise ValidationError("period_start must be <= period_end")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _domain_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or not values or any(x not in DOMAIN_IDS for x in values):
        raise ValidationError("domain_ids must contain one or more known life domains")
    return sorted(set(values))


def _text(value: str, field: str, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValidationError(f"{field} must be nonempty and <= {max_length} characters")
    return value.strip()


def _review_text(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) > 10000:
        raise ValidationError(f"{field} must be a string <= 10000 characters")
    return value


class LifeStore:
    """Single-user, local-first store; evidence remains owned by its source."""

    def __init__(self, path: str | Path | None = None, source: EvidenceSource | None = None):
        default = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "facetide" / "facetide.sqlite3"
        self.path = Path(path or os.environ.get("FACETIDE_DB_PATH", str(default))).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if source is not None:
            self.source = source
        else:
            sources = []
            mr_dir = os.environ.get("FACETIDE_MRMEM_DIR")
            mr_user = os.environ.get("FACETIDE_MRMEM_USER_ID")
            if bool(mr_dir) != bool(mr_user):
                raise ValidationError("MR-Mem integration requires both FACETIDE_MRMEM_DIR and FACETIDE_MRMEM_USER_ID")
            if mr_dir:
                sources.append(MrMemAmlSource(mr_dir, mr_user))
            nutrition_url = os.environ.get("FACETIDE_NUTRITION_MCP_URL")
            if nutrition_url:
                sources.append(NutritionMcpSource(
                    nutrition_url, member_id=os.environ.get("FACETIDE_NUTRITION_MEMBER_ID")))
            evidence_file = os.environ.get("FACETIDE_EVIDENCE_FILE")
            if evidence_file:
                sources.append(JsonlSource(evidence_file))
            self.source = CompositeSource(sources) if sources else EmptySource()
        self._initialize()

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS goals (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    enough_condition TEXT NOT NULL,
                    status TEXT NOT NULL,
                    indicators_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS goal_domains (
                    goal_id TEXT NOT NULL REFERENCES goals(id) ON DELETE CASCADE,
                    domain_id TEXT NOT NULL,
                    PRIMARY KEY (goal_id, domain_id)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    period_start TEXT NOT NULL,
                    period_end TEXT NOT NULL,
                    confirmed_at TEXT NOT NULL,
                    scores_json TEXT NOT NULL,
                    goals_snapshot_json TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    evidence_refs_json TEXT NOT NULL,
                    growth_reflection TEXT NOT NULL,
                    realization_reflection TEXT NOT NULL,
                    user_notes TEXT NOT NULL,
                    revision_of TEXT REFERENCES reviews(id)
                );
                CREATE INDEX IF NOT EXISTS ix_reviews_period
                    ON reviews(period_end DESC, confirmed_at DESC);
            """)
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    @staticmethod
    def _goals(db: sqlite3.Connection) -> list[dict]:
        rows = db.execute("SELECT * FROM goals ORDER BY created_at, id").fetchall()
        result = []
        for r in rows:
            dims = [x["domain_id"] for x in db.execute(
                "SELECT domain_id FROM goal_domains WHERE goal_id=? ORDER BY domain_id", (r["id"],))]
            result.append({
                "goal_id": r["id"], "title": r["title"],
                "enough_condition": r["enough_condition"],
                "status": r["status"], "indicators": json.loads(r["indicators_json"]),
                "domain_ids": dims, "version": r["version"],
                "created_at": r["created_at"], "updated_at": r["updated_at"],
            })
        return result

    @staticmethod
    def _review(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return {
            "review_id": row["id"],
            "period_start": row["period_start"], "period_end": row["period_end"],
            "confirmed_at": row["confirmed_at"],
            "domain_scores": json.loads(row["scores_json"]),
            "goals_snapshot": json.loads(row["goals_snapshot_json"]),
            "change_band": json.loads(row["changes_json"]),
            "evidence_refs": json.loads(row["evidence_refs_json"]),
            "personal_growth": row["growth_reflection"],
            "self_realization": row["realization_reflection"],
            "user_notes": row["user_notes"],
            "revision_of": row["revision_of"],
        }

    def get_snapshot(self) -> dict:
        with self._connection() as db:
            latest = self._review(db.execute(
                "SELECT * FROM reviews ORDER BY period_end DESC, confirmed_at DESC, rowid DESC LIMIT 1"
            ).fetchone())
            goals = self._goals(db)
        scores = latest["domain_scores"] if latest else {}
        return {
            "domains": [{"domain_id": d, "name": name, "score": scores.get(d)}
                        for d, name in DOMAINS.items()],
            "goals": goals, "latest_review": latest,
            "score_ownership": "user_only",
        }

    def upsert_goal(self, *, title: str, enough_condition: str,
                    domain_ids: list[str], status: str = "building",
                    indicators: dict | None = None, user_confirmed: bool = False,
                    goal_id: str | None = None, expected_version: int | None = None) -> dict:
        if user_confirmed is not True:
            raise ValidationError("Goal changes require explicit user confirmation")
        title = _text(title, "title", 200)
        enough_condition = _text(enough_condition, "enough_condition", 2000)
        dims = _domain_ids(domain_ids)
        if status not in GOAL_STATES:
            raise ValidationError(f"status must be one of {sorted(GOAL_STATES)}")
        if indicators is None:
            indicators = {}
        if not isinstance(indicators, dict) or any(x not in {"outcome", "driver", "guardrail"} for x in indicators):
            raise ValidationError("indicators accepts only outcome, driver and guardrail")
        encoded_indicators = _json(indicators)
        now = _utc_now()
        with self._connection() as db:
            if goal_id is None:
                if expected_version is not None:
                    raise ValidationError("expected_version applies only to updates")
                goal_id, version = str(uuid.uuid4()), 1
                db.execute("INSERT INTO goals VALUES (?,?,?,?,?,?,?,?)",
                           (goal_id, title, enough_condition, status, encoded_indicators, version, now, now))
            else:
                if not isinstance(goal_id, str) or not goal_id.strip():
                    raise ValidationError("invalid goal_id")
                if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
                    raise ValidationError("Updates require expected_version >= 1")
                row = db.execute("SELECT version FROM goals WHERE id=?", (goal_id,)).fetchone()
                if row is None:
                    raise ValidationError("goal_id not found")
                if row["version"] != expected_version:
                    raise GoalConflict(f"Goal version conflict: expected {expected_version}, actual {row['version']}")
                version = expected_version + 1
                db.execute("""UPDATE goals SET title=?, enough_condition=?, status=?,
                              indicators_json=?, version=?, updated_at=? WHERE id=? AND version=?""",
                           (title, enough_condition, status, encoded_indicators, version,
                            now, goal_id, expected_version))
                db.execute("DELETE FROM goal_domains WHERE goal_id=?", (goal_id,))
            db.executemany("INSERT INTO goal_domains (goal_id, domain_id) VALUES (?,?)",
                           [(goal_id, d) for d in dims])
            return next(g for g in self._goals(db) if g["goal_id"] == goal_id)

    def _evidence(self, start: str, end: str) -> tuple[list[dict], list[str]]:
        return self.source.query(start, end, DOMAIN_IDS)

    def prepare_review(self, period_start: str, period_end: str) -> dict:
        _period(period_start, period_end)
        items, warnings = self._evidence(period_start, period_end)
        with self._connection() as db:
            previous = self._review(db.execute(
                """SELECT * FROM reviews WHERE period_end < ?
                   ORDER BY period_end DESC, confirmed_at DESC, rowid DESC LIMIT 1""",
                (period_start,)).fetchone())
            goals = self._goals(db)
        groups = {d: [] for d in CHANGE_TYPES}
        for item in items:
            if item["resolution_status"] == "active" and item["change"] in groups:
                groups[item["change"]].append({
                    "source_type": item["source_type"], "source_ref": item["source_ref"],
                    "domain_ids": item["domain_ids"], "summary": item["summary"],
                    "evidence_kind": item["evidence_kind"],
                })
        return {
            "period_start": period_start, "period_end": period_end,
            "previous_review": previous, "goals": goals, "evidence": items,
            "change_candidates": {k: v[:40] for k, v in groups.items()},
            "warnings": warnings,
            "guidance": "Evidence is not a satisfaction score; ask user to confirm every rating and interpretation.",
        }

    def save_review(self, *, period_start: str, period_end: str,
                    domain_scores: dict[str, int],
                    user_confirmed: bool = False,
                    change_band: dict[str, list[str]] | None = None,
                    evidence_refs: list[dict[str, str]] | None = None,
                    personal_growth: str = "", self_realization: str = "",
                    user_notes: str = "", revision_of: str | None = None) -> dict:
        if user_confirmed is not True:
            raise ValidationError("Review scores and interpretation require user confirmation")
        _period(period_start, period_end)
        if not isinstance(domain_scores, dict) or any(
            d not in DOMAIN_IDS or type(score) is not int or not 1 <= score <= 5
            for d, score in domain_scores.items()
        ):
            raise ValidationError("domain_scores must be a subset of seven domains, integers 1..5")
        personal_growth = _review_text(personal_growth, "personal_growth")
        self_realization = _review_text(self_realization, "self_realization")
        user_notes = _review_text(user_notes, "user_notes")
        changes = change_band if change_band is not None else {}
        if not isinstance(changes, dict) or any(
            key not in CHANGE_TYPES or not isinstance(lines, list)
            or any(not isinstance(line, str) or not line.strip() or len(line) > 500 for line in lines)
            for key, lines in changes.items()
        ):
            raise ValidationError("change_band must map new/stable/receding to short strings")
        if not domain_scores and not any((personal_growth, self_realization, user_notes, changes)):
            raise ValidationError("Cannot save an empty review")
        refs = evidence_refs if evidence_refs is not None else []
        if not isinstance(refs, list):
            raise ValidationError("evidence_refs must be a list")
        available, _ = self._evidence(period_start, period_end)
        by_ref = {(x["source_type"], x["source_ref"]): x for x in available
                  if x["resolution_status"] == "active"}
        selected, seen = [], set()
        for ref in refs:
            if not isinstance(ref, dict):
                raise ValidationError("evidence_refs items must be objects")
            key = (ref.get("source_type"), ref.get("source_ref"))
            if key not in by_ref:
                raise ValidationError(f"Evidence missing, revoked or out of range: {key}")
            if key not in seen:
                item = by_ref[key]
                selected.append({k: item[k] for k in (
                    "source_type", "source_ref", "occurred_at", "known_at",
                    "domain_ids", "evidence_kind")})
                seen.add(key)
        with self._connection() as db:
            if revision_of:
                prior = db.execute("SELECT period_start,period_end FROM reviews WHERE id=?",
                                   (revision_of,)).fetchone()
                if prior is None or (prior["period_start"], prior["period_end"]) != (period_start, period_end):
                    raise ValidationError("revision_of must point to a review of the same period")
            review_id, now = str(uuid.uuid4()), _utc_now()
            db.execute("""INSERT INTO reviews (
                id, period_start, period_end, confirmed_at, scores_json,
                goals_snapshot_json, changes_json, evidence_refs_json,
                growth_reflection, realization_reflection, user_notes, revision_of
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                review_id, period_start, period_end, now, _json(domain_scores),
                _json(self._goals(db)), _json(changes), _json(selected),
                personal_growth, self_realization, user_notes, revision_of,
            ))
            return self._review(db.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone())

    def get_history(self, domain_id: str | None = None, limit: int = 12) -> dict:
        if domain_id is not None and domain_id not in DOMAIN_IDS:
            raise ValidationError("Unknown domain_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValidationError("limit must be an integer 1..100")
        with self._connection() as db:
            reviews = [self._review(row) for row in db.execute(
                "SELECT * FROM reviews ORDER BY period_end DESC, confirmed_at DESC, rowid DESC")]
        if domain_id:
            reviews = [review for review in reviews if domain_id in review["domain_scores"]]
        return {"domain_id": domain_id, "reviews": reviews[:limit], "total": len(reviews)}
