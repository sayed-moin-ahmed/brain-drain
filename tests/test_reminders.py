import os
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from unrot.autostart import autostart_path, set_autostart
from unrot.reminders import (
    DAILY, DEFAULT_REMINDERS, EYE_EXERCISES, INTERVAL, Reminder, body_for, coalesce, describe, is_due, next_due,
)
from unrot.store import Store

LUNCH = Reminder("lunch", "Lunch", "", DAILY, at=13 * 60)
WATER = Reminder("water", "Water", "", INTERVAL, every=60, start=9 * 60, end=18 * 60)


def at(h, m=0, day=21):
    return datetime(2026, 10, day, h, m)


class NextDueTest(unittest.TestCase):
    def test_daily_today_then_tomorrow(self):
        self.assertEqual(next_due(LUNCH, at(9)), at(13))
        self.assertEqual(next_due(LUNCH, at(13)), at(13, day=22))  # strictly after

    def test_interval_aligned_to_window_start(self):
        self.assertEqual(next_due(WATER, at(7)), at(9))
        self.assertEqual(next_due(WATER, at(9, 1)), at(10))

    def test_interval_end_is_exclusive(self):
        self.assertEqual(next_due(WATER, at(17, 30)), at(9, day=22))

    def test_empty_window_never_fires(self):
        self.assertIsNone(next_due(replace(WATER, start=600, end=600), at(9)))


class IsDueTest(unittest.TestCase):
    def test_fires_once_then_waits_for_next_slot(self):
        self.assertTrue(is_due(WATER, None, at(9, 0)))
        self.assertFalse(is_due(WATER, at(9, 0), at(9, 30)))
        self.assertTrue(is_due(WATER, at(9, 0), at(10, 0)))

    def test_missed_long_ago_is_skipped(self):
        # Laptop asleep over lunch: no stale alert at 15:00.
        self.assertFalse(is_due(LUNCH, None, at(15)))
        self.assertFalse(is_due(LUNCH, at(12, 59, day=20), at(15)))

    def test_missed_inside_grace_still_fires(self):
        self.assertTrue(is_due(LUNCH, None, at(13, 5)))

    def test_after_sleep_interval_fires_once_not_a_burst(self):
        self.assertTrue(is_due(WATER, at(9), at(14, 2)))
        self.assertFalse(is_due(WATER, at(14, 2), at(14, 3)))

    def test_describe(self):
        self.assertEqual(describe(LUNCH), "Every day at 13:00")
        self.assertEqual(describe(WATER), "Every 60 min, 09:00 to 18:00")


class DefaultsTest(unittest.TestCase):
    def test_requested_reminders_exist(self):
        ids = {r.id for r in DEFAULT_REMINDERS}
        self.assertLessEqual({"water", "walk", "focus", "lunch", "read"}, ids)
        self.assertEqual(len(ids), len(DEFAULT_REMINDERS))

    def test_break_every_30_to_40_minutes(self):
        brk = {r.id: r for r in DEFAULT_REMINDERS}["move"]
        self.assertTrue(30 <= brk.every <= 40)
        # 09:00, 09:35, 10:10, ...: never more than 40 minutes apart during the day.
        self.assertEqual(next_due(brk, at(9)), at(9, 35))
        self.assertEqual(next_due(brk, at(9, 35)), at(10, 10))


class EyesTest(unittest.TestCase):
    def setUp(self):
        self.eyes = {r.id: r for r in DEFAULT_REMINDERS}["eyes"]
        self.water = {r.id: r for r in DEFAULT_REMINDERS}["water"]

    def test_every_20_minutes_off_the_hour(self):
        self.assertEqual(self.eyes.every, 20)
        self.assertEqual(next_due(self.eyes, at(9)), at(9, 10))
        self.assertEqual(next_due(self.eyes, at(9, 10)), at(9, 30))
        # Never on the hour, so it never lands on the hourly water reminder.
        times, t = [], at(8)
        while (t := next_due(self.eyes, t)) < at(18):
            times.append(t)
        self.assertTrue(times and all(x.minute != 0 for x in times))

    def test_rotates_exercises(self):
        slots = [at(9, 10) + timedelta(minutes=20 * i) for i in range(len(EYE_EXERCISES))]
        bodies = {body_for(self.eyes, t) for t in slots}
        self.assertEqual(bodies, set(EYE_EXERCISES))
        self.assertEqual(body_for(self.water, at(9)), self.water.body)

    def test_break_wins_over_eyes(self):
        self.assertEqual(coalesce(["water", "move", "eyes"]), ["water", "move"])
        self.assertEqual(coalesce(["eyes"]), ["eyes"])


class StoreRemindersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "unrot.db"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_defaults_without_rows(self):
        self.assertEqual([r for r, _ in self.store.reminders()], list(DEFAULT_REMINDERS))

    def test_edits_and_last_fired_persist(self):
        lunch = dict((r.id, r) for r, _ in self.store.reminders())["lunch"]
        self.store.save_reminder(replace(lunch, at=12 * 60 + 30, enabled=False))
        self.store.mark_fired("lunch", at(12, 30))
        self.store.close()
        self.store = Store(self.path)
        got = dict((r.id, (r, last)) for r, last in self.store.reminders())["lunch"]
        self.assertEqual((got[0].at, got[0].enabled, got[1]), (750, False, at(12, 30)))
        self.assertEqual(got[0].title, lunch.title)  # text still comes from defaults

    def test_mark_fired_keeps_user_edits(self):
        water = DEFAULT_REMINDERS[0]
        self.store.save_reminder(replace(water, every=30))
        self.store.mark_fired(water.id, at(9))
        self.assertEqual(self.store.reminders()[0][0].every, 30)


class AutostartTest(unittest.TestCase):
    def test_write_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp}):
            path = autostart_path()
            self.assertEqual(path.parent, Path(tmp) / "autostart")
            set_autostart(True)
            text = path.read_text()
            self.assertIn("Exec=unrot --background", text)
            self.assertIn("TryExec=unrot", text)  # skipped at login once uninstalled
            set_autostart(False)
            self.assertFalse(path.exists())
            set_autostart(False)  # removing twice is fine


if __name__ == "__main__":
    unittest.main()
