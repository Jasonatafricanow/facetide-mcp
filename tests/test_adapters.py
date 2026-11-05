"""Real MR-Mem AML schema read test using synthetic scoped stores."""
from contextlib import closing
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from facetide.adapters import CompositeSource, MrMemAmlSource
from facetide.sources import JsonlSource


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with closing(sqlite3.connect(self.root / "memory.sqlite")) as db, db:
            db.execute("CREATE TABLE canonical_memory (payload TEXT NOT NULL)")
        with closing(sqlite3.connect(self.root / "aml_source.sqlite")) as db, db:
            db.execute("CREATE TABLE messages (record_id TEXT,user_id TEXT,session_id TEXT, "
                       "occurred_at TEXT,time_given INTEGER,fingerprint TEXT,content TEXT)")
        self.content = "A user said they want steadier sleep"
        self.fingerprint = hashlib.sha256(self.content.encode()).hexdigest()

    def insert(self, mid, user="alice", lifecycle="active", day="2026-10-09", valid=True):
        with closing(sqlite3.connect(self.root / "aml_source.sqlite")) as db, db:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                       (mid, user, "thread-1", day, 1,
                        self.fingerprint if valid else "f" * 64, self.content))
        mem = {
            "memory_id": mid, "scope": {"domain": "user", "user_id": user},
            "lifecycle": lifecycle, "content": "I would like better sleep",
            "committed_at": "2026-11-01T10:00:00+00:00",
            "provenance": {"source_refs": [{
                "source_namespace": "aml", "record_id": mid, "session_id": "thread-1",
                "fingerprint": self.fingerprint
            }]},
            "attributes": [["facetide_domains", ["health", "leisure"]]]
        }
        with closing(sqlite3.connect(self.root / "memory.sqlite")) as db, db:
            db.execute("INSERT INTO canonical_memory(payload) VALUES (?)", (json.dumps(mem),))

    def test_scope_version_time_and_lifecycle(self):
        self.insert("a")
        self.insert("b", user="bob")
        self.insert("c", lifecycle="invalidated")
        source = MrMemAmlSource(self.root, "alice")
        items, warnings = source.query("2026-10-01", "2026-10-31",
                                       frozenset({"health", "leisure"}))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["known_at"], "2026-11-01T10:00:00+00:00")
        self.assertEqual(items[0]["domain_ids"], ["health", "leisure"])
        self.assertEqual(items[0]["evidence_kind"], "inference")
        self.assertEqual(items[1]["resolution_status"], "retracted")
        self.assertEqual(warnings, [])

    def test_changed_native_source_excluded(self):
        self.insert("a", valid=False)
        items, warnings = MrMemAmlSource(self.root, "alice").query(
            "2026-10-01", "2026-10-31", frozenset({"health"}))
        self.assertEqual(items, [])
        self.assertTrue(warnings)

    def test_malformed_source_does_not_break_other_adapters(self):
        self.insert("a", valid=False)
        src = CompositeSource([MrMemAmlSource(self.root, "alice"), JsonlSource(self.root / "missing")])
        items, warnings = src.query("2026-10-01", "2026-10-31", frozenset({"health"}))
        self.assertEqual(items, [])
        self.assertGreaterEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
