"""Two writers reading the same version must not mix goal fields."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
import tempfile
import unittest

from facetide.core import LifeStore, GoalConflict


class GoalConcurrencyTest(unittest.TestCase):
    def test_losing_writer_cannot_replace_domain_links(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LifeStore(Path(directory) / "goals.sqlite3")
            goal = store.upsert_goal(title="original", enough_condition="enough",
                                     domain_ids=["career"], user_confirmed=True)
            barrier = Barrier(2)
            connection = store._connection

            class VersionCursor:
                def __init__(self, cursor):
                    self.cursor = cursor

                def fetchone(self):
                    row = self.cursor.fetchone()
                    barrier.wait(timeout=10)
                    return row

            class SynchronizedConnection:
                def __init__(self, db):
                    self.db = db

                def execute(self, sql, *args):
                    cursor = self.db.execute(sql, *args)
                    return (VersionCursor(cursor) if sql.startswith("SELECT version FROM goals")
                            else cursor)

                def __getattr__(self, name):
                    return getattr(self.db, name)

            @contextmanager
            def synchronized_connection():
                with connection() as db:
                    yield SynchronizedConnection(db)

            store._connection = synchronized_connection

            def update(domain):
                try:
                    return store.upsert_goal(title=domain, enough_condition=domain,
                        domain_ids=[domain], goal_id=goal["goal_id"], expected_version=1,
                        user_confirmed=True)
                except GoalConflict:
                    return None

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(update, ["health", "social"]))
            winners = [result for result in results if result is not None]
            self.assertEqual(len(winners), 1)
            final = store.get_snapshot()["goals"][0]
            self.assertEqual(final, winners[0])
            self.assertEqual(final["domain_ids"], [final["title"]])
            self.assertEqual(final["version"], 2)
