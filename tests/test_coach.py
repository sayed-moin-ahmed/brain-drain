import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from unrot.attention import EXPERIMENT_DAYS, HYGIENE_ITEMS, experiment_progress
from unrot.coach import (
    Experiment, FocusSession, Snapshot, advice, focus_score, hygiene_score, learning_score,
    next_best_action, personal_model,
)
from unrot.content import DONE, REST
from unrot.store import Store

TODAY = date(2026, 10, 21)


def week(**per_day):
    """week(read=[DONE, None, ...]) -> 7 (day, states) pairs, oldest first."""
    days = [TODAY - timedelta(days=6 - i) for i in range(7)]
    out = []
    for i, d in enumerate(days):
        states = {p: v[i] for p, v in per_day.items() if v[i] is not None}
        out.append((d, states))
    return out


def snap(**kw):
    kw.setdefault("week", week())
    return Snapshot(today=TODAY, **kw)


def at(h, m=0, day=TODAY):
    return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)


class ScoreTest(unittest.TestCase):
    def test_empty_week(self):
        s = snap()
        self.assertEqual(focus_score(s).value, 0)
        self.assertEqual(learning_score(s).value, 0)
        self.assertEqual(hygiene_score(s).value, 0)

    def test_focus_uses_minutes_and_finished_sessions(self):
        sessions = [FocusSession(at(10), 50, 50, True), FocusSession(at(14), 50, 10, False)]
        score = focus_score(snap(sessions=sessions))
        # minutes 60/300 = 0.2, finished 1/2 = 0.5 -> average 0.35
        self.assertEqual(score.value, 35)
        self.assertIn("Sessions finished: 1 of 2", score.reasons)

    def test_logged_distractions_never_lower_focus(self):
        sessions = [FocusSession(at(10), 50, 50, True)]
        clean = focus_score(snap(sessions=sessions)).value
        noisy = focus_score(snap(sessions=sessions, distractions=[(at(11), "Phone")] * 20)).value
        self.assertEqual(clean, noisy)

    def test_rest_days_are_neutral(self):
        all_rest = week(read=[REST] * 7, research=[REST] * 7)
        s = learning_score(snap(week=all_rest, library_added=2))
        self.assertEqual(s.value, 100)  # only the library part counts
        self.assertIn("Read for fun: all rest days", s.reasons)
        half = week(read=[DONE, REST, REST, REST, REST, REST, REST])
        self.assertIn("Read for fun: 1 of 1 days", learning_score(snap(week=half)).reasons)

    def test_hygiene_parts(self):
        s = hygiene_score(snap(week=week(phone=[DONE] * 7, boredom=[DONE] * 7),
                               hygiene={i: True for i, _ in HYGIENE_ITEMS}))
        self.assertEqual(s.value, 100)

    def test_old_sessions_outside_week_do_not_count(self):
        old = [FocusSession(at(10, day=TODAY - timedelta(days=10)), 300, 300, True)]
        self.assertEqual(focus_score(snap(sessions=old)).value, 0)


class PersonalModelTest(unittest.TestCase):
    def test_acceptance_is_smoothed(self):
        fb = [(TODAY, "walk", "dismissed")] * 3 + [(TODAY, "read", "done")]
        model = personal_model(snap(feedback=fb))
        self.assertAlmostEqual(model.weight("walk"), 1 / 5)
        self.assertAlmostEqual(model.weight("read"), 2 / 3)
        self.assertEqual(model.weight("never_seen"), 0.5)

    def test_best_focus_hour_needs_three_finished_sessions(self):
        two = [FocusSession(at(10), 50, 50, True)] * 2
        self.assertIsNone(personal_model(snap(sessions=two)).best_focus_hour)
        three = two + [FocusSession(at(15), 25, 25, True)]
        self.assertEqual(personal_model(snap(sessions=three)).best_focus_hour, 10)


class CoachTest(unittest.TestCase):
    def test_daytime_without_focus_suggests_focus(self):
        self.assertEqual(next_best_action(snap(), at(10)).rule, "no_focus")

    def test_best_hour_explains_focus_advice(self):
        sessions = [FocusSession(at(9, day=TODAY - timedelta(days=d)), 50, 50, True) for d in (1, 2, 3)]
        a = next_best_action(snap(sessions=sessions), at(10))
        self.assertIn("09:00", a.why)

    def test_many_distractions_beat_no_focus(self):
        d = [(at(9, m), "Phone") for m in (1, 2, 3)]
        a = next_best_action(snap(distractions=d), at(10))
        self.assertEqual(a.rule, "distracted")
        self.assertIn("phone", a.title)

    def test_evening_phone_curfew_then_reading(self):
        ranked = [a.rule for a in advice(snap(), at(21))]
        self.assertEqual(ranked[:2], ["phone_curfew", "read"])

    def test_dismissed_today_is_skipped(self):
        fb = [(TODAY, "phone_curfew", "dismissed")]
        self.assertNotEqual(next_best_action(snap(feedback=fb), at(21)).rule, "phone_curfew")

    def test_often_dismissed_rule_sinks(self):
        past = TODAY - timedelta(days=1)
        fb = [(past, "phone_curfew", "dismissed")] * 8 + [(past, "read", "done")] * 3
        self.assertEqual(next_best_action(snap(feedback=fb), at(21)).rule, "read")

    def test_experiment_check_in_evening(self):
        exp = Experiment(1, "No phone at lunch", TODAY - timedelta(days=2), EXPERIMENT_DAYS)
        a = next_best_action(snap(experiment=exp), at(19))
        self.assertEqual((a.rule, a.why), ("experiment_check", "Day 3 of 7 of your experiment."))
        checked = Experiment(1, "x", TODAY, 7, {TODAY: True})
        self.assertNotIn("experiment_check", [x.rule for x in advice(snap(experiment=checked), at(19))])

    def test_never_empty(self):
        everything_done = week(**{p: [DONE] * 7 for p in ("phone", "boredom", "write", "research", "read")})
        fb = [(TODAY, "on_track", "dismissed"), (TODAY, "hygiene", "dismissed"),
              (TODAY, "start_experiment", "dismissed")]
        a = next_best_action(snap(week=everything_done, feedback=fb, journal_today=True), at(23))
        self.assertEqual(a.rule, "on_track")


class ExperimentTest(unittest.TestCase):
    def test_progress(self):
        self.assertEqual(experiment_progress(TODAY, 7, TODAY), (1, False))
        self.assertEqual(experiment_progress(TODAY, 7, TODAY + timedelta(days=6)), (7, False))
        self.assertEqual(experiment_progress(TODAY, 7, TODAY + timedelta(days=7)), (8, True))


class StoreAttentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "u.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_snapshot_round_trip(self):
        s = self.store
        s.add_focus_session(at(10), 50, 50, True)
        did = s.add_distraction(at(11), "Phone")
        s.add_distraction(at(12), "News")
        s.delete_distraction(did)
        s.set_hygiene("grayscale", True)
        exp = s.start_experiment("No phone at lunch", TODAY, 7)
        s.set_experiment_check(exp, TODAY, True)
        s.add_feedback(TODAY, "walk", "dismissed")
        s.add_entry(TODAY, "book", "Dune")
        snapshot = s.snapshot(TODAY)
        self.assertEqual(len(snapshot.sessions), 1)
        self.assertEqual([src for _, src in snapshot.distractions], ["News"])
        self.assertTrue(snapshot.hygiene["grayscale"])
        self.assertEqual(snapshot.experiment.checks, {TODAY: True})
        self.assertEqual(snapshot.feedback, [(TODAY, "walk", "dismissed")])
        self.assertEqual(snapshot.library_added, 1)

    def test_one_experiment_at_a_time(self):
        self.store.start_experiment("A", TODAY, 7)
        second = self.store.start_experiment("B", TODAY, 7)
        self.assertEqual(self.store.current_experiment().id, second)
        self.store.end_experiment(second)
        self.assertIsNone(self.store.current_experiment())
        with self.assertRaises(ValueError):
            self.store.start_experiment("  ", TODAY, 7)


if __name__ == "__main__":
    unittest.main()
