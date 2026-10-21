"""Drives the real widgets. Skipped when no display or no GTK is available."""

import os
import tempfile
import time
import unittest
from datetime import date, datetime
from pathlib import Path

from unrot.store import Store

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk

    HAVE_GTK = Gtk.init_check()
except (ImportError, ValueError):
    HAVE_GTK = False


@unittest.skipUnless(HAVE_GTK, "needs GTK 4, libadwaita and a display")
class WindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from unrot.main import UnrotApp

        Adw.init()
        cls.app_tmp = tempfile.TemporaryDirectory()
        cls.app_store = Store(Path(cls.app_tmp.name) / "app.db")
        # Registered once: an app ID can be exported on D-Bus only one time.
        # NON_UNIQUE so the test never talks to a running Unrot instance.
        cls.app = UnrotApp(cls.app_store)
        cls.app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
        cls.app.register(None)

    @classmethod
    def tearDownClass(cls):
        cls.app_store.close()
        cls.app_tmp.cleanup()

    def setUp(self):
        from unrot.main import UnrotWindow

        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "unrot.db")
        self.app.store = self.store
        # Memory-only settings: tests must never flip the real Do Not Disturb.
        backend = Gio.memory_settings_backend_new()
        self.app.dnd = Gio.Settings.new_with_backend("org.gnome.desktop.notifications", backend) \
            if Gio.SettingsSchemaSource.get_default().lookup("org.gnome.desktop.notifications", True) else None
        self.app.send_alert = lambda *a, **k: self.alerts.append(a)
        self.alerts = []
        self.win = UnrotWindow(self.app)
        self.app.window = self.win

    def tearDown(self):
        self.app.window = None
        self.win.destroy()
        self.store.close()
        self.tmp.cleanup()

    def test_ticking_done_saves_and_rest_clears_done(self):
        done, rest = self.win._rows["read"]
        done.set_active(True)
        self.assertEqual(self.store.states_for(date.today()), {"read": "done"})
        rest.set_active(True)
        self.assertEqual(self.store.states_for(date.today()), {"read": "rest"})
        self.assertFalse(done.get_active())
        rest.set_active(False)
        self.assertEqual(self.store.states_for(date.today()), {})

    def test_moment_saves_journal_and_marks_write_done(self):
        self.win.moment_row.set_text("Saw a heron <b>")
        self.win._on_moment_apply(self.win.moment_row)
        self.assertEqual(self.store.journal(date.today())["moment"], "Saw a heron <b>")
        self.assertEqual(self.store.states_for(date.today()).get("write"), "done")
        self.assertTrue(self.win._rows["write"][0].get_active())

    def test_week_summary_counts_active_days(self):
        self.win._rows["phone"][0].set_active(True)
        self.assertEqual(self.win.week_group.get_description(), "Active days: 1 of 7")

    def test_library_add_and_delete(self):
        entry_id = self.store.add_entry(date.today(), "book", "Dune & <friends>")
        self.win._refresh_library()
        self.assertIsNotNone(self.win.lists["book"].get_row_at_index(0))
        self.win._on_delete_entry(None, entry_id)
        self.assertIsNone(self.win.lists["book"].get_row_at_index(0))

    def test_walk_timer_start_stop(self):
        self.win._on_walk_clicked(None)
        self.assertGreater(self.app.walk_remaining(), 19 * 60)
        self.assertEqual(self.win.walk_button.get_label(), "Stop")
        self.win._on_walk_clicked(None)
        self.assertIsNone(self.app.walk_remaining())
        self.assertEqual(self.win.walk_button.get_label(), "Start")

    def test_walk_timer_survives_closing_the_app(self):
        self.app.start_walk()
        end = float(self.store.get_setting("walk_end"))
        self.store.close()
        self.store = Store(Path(self.tmp.name) / "unrot.db")  # like a fresh process
        self.app.store = self.win.store = self.store
        self.assertAlmostEqual(self.app.walk_remaining(), end - time.time(), delta=2)
        # Ends while closed: marked done on its day, alert only if recent.
        self.assertTrue(self.app.check_walk(now=end + 60))
        self.assertEqual(self.store.states_for(date.fromtimestamp(end)).get("boredom"), "done")
        self.assertEqual(len(self.alerts), 1)
        self.app.start_walk()
        self.assertTrue(self.app.check_walk(now=time.time() + 3 * 3600))
        self.assertEqual(len(self.alerts), 1)  # stale: no alert hours later
        self.assertFalse(self.app.check_walk())

    def test_focus_hour_turns_dnd_on_then_off(self):
        if self.app.dnd is None:
            self.skipTest("GNOME notification schema not installed")
        self.app.start_focus(minutes=60)
        self.assertFalse(self.app.dnd.get_boolean("show-banners"))
        self.assertFalse(self.app.check_focus(now=time.time() + 30 * 60))
        self.assertTrue(self.app.check_focus(now=time.time() + 61 * 60))
        self.assertTrue(self.app.dnd.get_boolean("show-banners"))

    def test_tick_sends_due_reminders_once(self):
        noon = datetime.combine(date.today(), datetime.min.time()).replace(hour=13, minute=1)
        self.app._tick(now=noon)
        sent = [a[0] for a in self.alerts]
        self.assertIn("lunch", sent)
        self.assertIn("water", sent)
        self.alerts.clear()
        self.app._tick(now=noon)
        self.assertEqual(self.alerts, [])

    def test_tick_drops_eyes_when_break_is_due_too(self):
        # 10:10 is both a break slot (9:00 + 2 x 35) and an eye slot (9:10 + 3 x 20).
        slot = datetime.combine(date.today(), datetime.min.time()).replace(hour=10, minute=10)
        self.app._tick(now=slot)
        sent = [a[0] for a in self.alerts]
        self.assertIn("move", sent)
        self.assertNotIn("eyes", sent)
        self.alerts.clear()
        self.app._tick(now=slot.replace(minute=11))
        self.assertEqual(self.alerts, [])  # the dropped eye reminder does not come back

    def test_preferences_dialog_builds_and_saves(self):
        from unrot.main import PreferencesDialog

        dialog = PreferencesDialog(self.app)
        lunch = dict((r.id, r) for r, _ in self.store.reminders())["lunch"]
        row = dialog._reminder_row(lunch)
        row.set_enable_expansion(False)
        saved = dict((r.id, r) for r, _ in self.store.reminders())["lunch"]
        self.assertFalse(saved.enabled)
        self.assertEqual(saved.at, 13 * 60)

    def test_focus_restores_users_own_dnd_setting(self):
        if self.app.dnd is None:
            self.skipTest("GNOME notification schema not installed")
        self.app.dnd.set_boolean("show-banners", False)  # user already had DND on
        self.app.start_focus(minutes=25, dnd=True)
        self.app.stop_focus()
        self.assertFalse(self.app.dnd.get_boolean("show-banners"))  # still on, as before
        self.app.dnd.set_boolean("show-banners", True)

    def test_stopping_early_logs_partial_session(self):
        self.app.start_focus(minutes=50, dnd=False)
        self.store.set_setting("focus_start", repr(time.time() - 600))  # started 10 min ago
        self.app.stop_focus()
        (session,) = self.store.focus_sessions(date.today())
        self.assertEqual((session.planned_min, session.done_min, session.completed), (50, 10, False))
        self.assertIsNone(self.app.focus_remaining())

    def test_distraction_logged_and_undone(self):
        page = self.win.focus_page
        page._on_distraction(None, "Phone")
        self.assertEqual(len(self.store.distractions(date.today())), 1)
        self.assertTrue(page.distract_row.get_title().startswith("Today: 1"))
        did = self.store._db.execute("SELECT id FROM distraction").fetchone()[0]
        page._undo(did)
        self.assertEqual(self.store.distractions(date.today()), [])

    def test_not_now_records_feedback_and_shows_next(self):
        first = self.win._advice
        self.win._on_advice(None, False)
        self.assertEqual(self.store.feedback(date.today())[-1][1:], (first.rule, "dismissed"))
        self.assertNotEqual(self.win._advice.rule, first.rule)

    def test_tick_repicks_advice_as_time_passes(self):
        self.win.present()
        morning = datetime.combine(date.today(), datetime.min.time()).replace(hour=10)
        self.app._tick(now=morning)
        self.store.add_feedback(date.today(), self.win._advice.rule, "dismissed")
        before = self.win._advice.rule
        self.app._tick(now=morning)
        self.assertNotEqual(self.win._advice.rule, before)

    def test_scores_shown(self):
        self.store.add_focus_session(datetime.now(), 50, 50, True)
        self.win.refresh_all()
        row, _bar, value = self.win.score_rows[0]
        self.assertEqual(row.get_title(), "Focus")
        self.assertEqual(value.get_label(), "58")  # (50/300 + 1/1) / 2

    def test_experiment_start_check_and_end(self):
        self.win._exp_custom.set_text("No phone at lunch")
        self.win._on_exp_start(None)
        exp = self.store.current_experiment()
        self.assertEqual(exp.title, "No phone at lunch")
        self.assertTrue(self.win.exp_today.get_visible())
        self.win.exp_yes.set_active(True)
        self.assertEqual(self.store.current_experiment().checks, {date.today(): True})
        self.store.end_experiment(exp.id)
        self.win.refresh_all()
        self.assertFalse(self.win.exp_today.get_visible())

    def test_ideas_change(self):
        first = self.win.idea_page.get_title()
        self.win._next_idea()
        self.assertNotEqual(first, self.win.idea_page.get_title())


if __name__ == "__main__":
    unittest.main()
