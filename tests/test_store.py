import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from unrot.content import IDEAS, PRACTICE_IDS, PRACTICES
from unrot.store import DONE, REST, Store, default_db_path, is_active_day

DAY = date(2026, 10, 21)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "sub" / "unrot.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_set_and_clear_state(self):
        self.store.set_state(DAY, "read", DONE)
        self.assertEqual(self.store.states_for(DAY), {"read": DONE})
        self.store.set_state(DAY, "read", REST)
        self.assertEqual(self.store.states_for(DAY), {"read": REST})
        self.store.set_state(DAY, "read", None)
        self.assertEqual(self.store.states_for(DAY), {})

    def test_rejects_unknown_practice_and_state(self):
        with self.assertRaises(ValueError):
            self.store.set_state(DAY, "tiktok", DONE)
        with self.assertRaises(ValueError):
            self.store.set_state(DAY, "read", "maybe")

    def test_week_is_seven_days_oldest_first(self):
        self.store.set_state(DAY - timedelta(days=6), "write", DONE)
        self.store.set_state(DAY - timedelta(days=7), "write", DONE)  # outside window
        week = self.store.week(DAY)
        self.assertEqual([d for d, _ in week][0], DAY - timedelta(days=6))
        self.assertEqual([d for d, _ in week][-1], DAY)
        self.assertEqual(week[0][1], {"write": DONE})
        self.assertEqual(self.store.active_days(DAY), 1)

    def test_rest_day_is_not_active_and_not_a_miss(self):
        self.assertFalse(is_active_day({"phone": REST}))
        self.assertTrue(is_active_day({"phone": REST, "read": DONE}))
        self.assertFalse(is_active_day({}))

    def test_journal_round_trip_and_partial_update(self):
        self.store.save_journal(DAY, moment="Saw a heron")
        self.store.save_journal(DAY, notes="Long walk by the river")
        self.assertEqual(
            self.store.journal(DAY), {"moment": "Saw a heron", "notes": "Long walk by the river"}
        )
        self.assertEqual(self.store.recent_journal()[0]["day"], DAY)

    def test_empty_journal_is_deleted(self):
        self.store.save_journal(DAY, moment="x")
        self.store.save_journal(DAY, moment="  ", notes="")
        self.assertEqual(self.store.recent_journal(), [])

    def test_entries(self):
        a = self.store.add_entry(DAY, "book", "  Dune ")
        self.store.add_entry(DAY, "topic", "Octopus brains")
        self.assertEqual([e["title"] for e in self.store.entries("book")], ["Dune"])
        self.store.delete_entry(a)
        self.assertEqual(self.store.entries("book"), [])
        with self.assertRaises(ValueError):
            self.store.add_entry(DAY, "book", "   ")
        with self.assertRaises(ValueError):
            self.store.add_entry(DAY, "film", "x")

    def test_settings(self):
        self.assertEqual(self.store.get_setting("reminder", "on"), "on")
        self.store.set_setting("reminder", "off")
        self.assertEqual(self.store.get_setting("reminder", "on"), "off")

    def test_data_dir_is_private(self):
        mode = (Path(self.tmp.name) / "sub").stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)

    def test_data_survives_reopen(self):
        self.store.set_state(DAY, "phone", DONE)
        path = Path(self.tmp.name) / "sub" / "unrot.db"
        self.store.close()
        self.store = Store(path)
        self.assertEqual(self.store.states_for(DAY), {"phone": DONE})


class PathTest(unittest.TestCase):
    def test_override(self):
        with mock.patch.dict(os.environ, {"UNROT_DATA_DIR": "/tmp/x"}):
            self.assertEqual(default_db_path(), Path("/tmp/x/unrot.db"))

    def test_xdg_and_relative_ignored(self):
        env = {k: v for k, v in os.environ.items() if k != "UNROT_DATA_DIR"}
        with mock.patch.dict(os.environ, {**env, "XDG_DATA_HOME": "/data"}, clear=True):
            self.assertEqual(default_db_path(), Path("/data/unrot/unrot.db"))
        with mock.patch.dict(os.environ, {**env, "XDG_DATA_HOME": "rel"}, clear=True):
            self.assertEqual(
                default_db_path(), Path.home() / ".local/share/unrot/unrot.db"
            )


class ContentTest(unittest.TestCase):
    def test_five_practices_with_unique_ids(self):
        self.assertEqual(len(PRACTICES), 5)
        self.assertEqual(len(set(PRACTICE_IDS)), 5)
        for p in PRACTICES:
            self.assertTrue(p.title and p.how and p.why)

    def test_thirteen_ideas_from_book(self):
        self.assertEqual(len(IDEAS), 13)


if __name__ == "__main__":
    unittest.main()
