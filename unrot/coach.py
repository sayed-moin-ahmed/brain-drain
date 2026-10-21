"""Measurement engine, cognitive coach, personal model and next best action.

Pure functions over a Snapshot of the user's own logs. No GTK, no SQLite.

    Snapshot ──► scores()           three scores, each a plain average of rates
             ──► personal_model()   per-suggestion acceptance + best focus hour
             ──► advice()           rules that fire for this time of day
                        └──► ranked by priority x acceptance ──► next best action

Everything here is based only on what the user logged. Wayland does not let an app
see which window is in use, so nothing is measured automatically.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .attention import HYGIENE_ITEMS, experiment_progress
from .content import DONE, PRACTICES, REST

MODEL_DAYS = 28  # how far back the personal model looks
FOCUS_GOAL_MIN = 300  # 5 hours of focus a week
LIBRARY_GOAL = 2  # new books or topics a week
BEST_HOUR_MIN_SESSIONS = 3


@dataclass(frozen=True)
class FocusSession:
    started: datetime
    planned_min: int
    done_min: int
    completed: bool


@dataclass(frozen=True)
class Experiment:
    id: int
    title: str
    start: date
    days: int
    checks: dict = field(default_factory=dict)  # date -> kept (bool)


@dataclass
class Snapshot:
    today: date
    week: list  # 7 x (date, {practice: state}), oldest first
    sessions: list = field(default_factory=list)  # FocusSession, last MODEL_DAYS days
    distractions: list = field(default_factory=list)  # (datetime, source), last 7 days
    library_added: int = 0
    hygiene: dict = field(default_factory=dict)  # item id -> bool
    experiment: Experiment = None
    feedback: list = field(default_factory=list)  # (date, rule, response), last MODEL_DAYS days
    journal_today: bool = False

    def week_sessions(self):
        start = self.today - timedelta(days=6)
        return [s for s in self.sessions if s.started.date() >= start]

    def today_state(self, practice_id):
        return self.week[-1][1].get(practice_id)


# Measurement engine


@dataclass(frozen=True)
class Score:
    name: str
    value: object  # int 0-100, or None when there is nothing to score yet
    reasons: tuple


def _practice_rate(week, practice_id, label):
    """Rest days are left out of the count, so they never lower a score."""
    done = sum(1 for _, states in week if states.get(practice_id) == DONE)
    counted = sum(1 for _, states in week if states.get(practice_id) != REST)
    if counted == 0:
        return None, f"{label}: all rest days"
    return done / counted, f"{label}: {done} of {counted} days"


def _score(name, parts, note):
    rates = [rate for rate, _ in parts if rate is not None]
    value = round(100 * sum(rates) / len(rates)) if rates else None
    return Score(name, value, tuple(text for _, text in parts) + (note,))


def _hours(minutes):
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h" if minutes % 60 == 0 else f"{minutes // 60} h {minutes % 60} min"


def focus_score(snap: Snapshot) -> Score:
    sessions = snap.week_sessions()
    minutes = sum(s.done_min for s in sessions)
    parts = [(min(1.0, minutes / FOCUS_GOAL_MIN),
              f"Focus time: {_hours(minutes)} of a {_hours(FOCUS_GOAL_MIN)} weekly goal")]
    if sessions:
        finished = sum(1 for s in sessions if s.completed)
        parts.append((finished / len(sessions), f"Sessions finished: {finished} of {len(sessions)}"))
    return _score("Focus", parts, "Distractions you log never lower this score.")


def learning_score(snap: Snapshot) -> Score:
    parts = [
        _practice_rate(snap.week, "read", "Read for fun"),
        _practice_rate(snap.week, "research", "Explored a topic"),
        (min(1.0, snap.library_added / LIBRARY_GOAL),
         f"New books or topics: {snap.library_added} (goal {LIBRARY_GOAL})"),
    ]
    return _score("Learning", parts, "From your Today ticks and Library.")


def hygiene_score(snap: Snapshot) -> Score:
    setup = sum(1 for item_id, _ in HYGIENE_ITEMS if snap.hygiene.get(item_id))
    parts = [
        _practice_rate(snap.week, "phone", "Phone curfew"),
        _practice_rate(snap.week, "boredom", "Time with no device"),
        (setup / len(HYGIENE_ITEMS), f"Phone setup: {setup} of {len(HYGIENE_ITEMS)} done"),
    ]
    return _score("Digital hygiene", parts, "From your Today ticks and phone setup.")


def scores(snap: Snapshot):
    return [focus_score(snap), learning_score(snap), hygiene_score(snap)]


# Personal model: learns only from the user's own answers and sessions.


@dataclass(frozen=True)
class PersonalModel:
    acceptance: dict  # rule -> share of "Do it" answers, smoothed
    best_focus_hour: object  # int hour, or None until there is enough data

    def weight(self, rule):
        # Laplace smoothing: a rule with no answers yet starts at 0.5, not 0 or 1.
        return self.acceptance.get(rule, 0.5)


def personal_model(snap: Snapshot) -> PersonalModel:
    done, total = Counter(), Counter()
    for _day, rule, response in snap.feedback:
        total[rule] += 1
        if response == "done":
            done[rule] += 1
    acceptance = {rule: (done[rule] + 1) / (total[rule] + 2) for rule in total}

    finished = [s for s in snap.sessions if s.completed]
    best = None
    if len(finished) >= BEST_HOUR_MIN_SESSIONS:
        minutes_by_hour = Counter()
        for s in finished:
            minutes_by_hour[s.started.hour] += s.done_min
        best = minutes_by_hour.most_common(1)[0][0]
    return PersonalModel(acceptance, best)


# Cognitive coach: each rule explains itself (why) and recommends one action.


@dataclass(frozen=True)
class Advice:
    rule: str
    title: str
    why: str
    action: str  # what "Do it" does; see UnrotWindow._do_action
    priority: int


def _open(snap, practice_id):
    return snap.today_state(practice_id) not in (DONE, REST)


def _rule_experiment_check(snap, now, model):
    exp = snap.experiment
    if exp is None or now.hour < 18:
        return None
    day_number, finished = experiment_progress(exp.start, exp.days, snap.today)
    if finished or snap.today in exp.checks:
        return None
    return Advice("experiment_check", f"Did you keep “{exp.title}” today?",
                  f"Day {day_number} of {exp.days} of your experiment.", "experiment_kept", 90)


def _rule_phone_curfew(snap, now, model):
    if now.hour < 20 or not _open(snap, "phone"):
        return None
    return Advice("phone_curfew", "Phone away for the night",
                  "Phone use at bedtime is linked to worse sleep, mostly in studies of teens.",
                  "practice:phone", 85)


def _rule_distracted(snap, now, model):
    today = [source for at, source in snap.distractions if at.date() == snap.today]
    if len(today) < 3 or not 9 <= now.hour < 18:
        return None
    top, count = Counter(today).most_common(1)[0]
    return Advice("distracted", f"Focus session with {top.lower()} out of reach",
                  f"You logged {len(today)} distractions today, {count} from {top.lower()}.",
                  "focus", 80)


def _rule_no_focus(snap, now, model):
    if not 9 <= now.hour < 18:
        return None
    if any(s.started.date() == snap.today for s in snap.sessions):
        return None
    if model.best_focus_hour is not None:
        why = f"You finish most focus time around {model.best_focus_hour:02d}:00."
    else:
        why = "Focus time is the biggest part of your focus score."
    return Advice("no_focus", "Start a focus session", why, "focus", 70)


def _rule_read(snap, now, model):
    if now.hour < 19 or not _open(snap, "read"):
        return None
    return Advice("read", "Read for 10 minutes", "Any book you enjoy. Comics count.", "practice:read", 65)


def _rule_walk(snap, now, model):
    if not 12 <= now.hour < 19 or not _open(snap, "boredom"):
        return None
    return Advice("walk", "Take the 20-minute walk",
                  "No phone. Walking helped people come up with ideas in small experiments.", "walk", 60)


def _rule_write(snap, now, model):
    if now.hour < 20 or not _open(snap, "write") or snap.journal_today:
        return None
    return Advice("write", "Write one story-worthy moment", "One line is enough.", "write", 55)


def _rule_weakest(snap, now, model):
    worst = None
    for p in PRACTICES:
        rate, text = _practice_rate(snap.week, p.id, p.title)
        if rate is not None and rate < 0.5 and _open(snap, p.id) and (worst is None or rate < worst[0]):
            worst = (rate, p, text)
    if worst is None:
        return None
    _rate, p, text = worst
    return Advice("weakest", p.title, f"Your least-done step this week ({text.split(': ')[1]}).",
                  f"practice:{p.id}", 50)


def _rule_hygiene(snap, now, model):
    for item_id, label in HYGIENE_ITEMS:
        if not snap.hygiene.get(item_id):
            return Advice("hygiene", f"Phone setup: {label.lower()}",
                          "A one-time change from step 1 of the book.", f"hygiene:{item_id}", 40)
    return None


def _rule_start_experiment(snap, now, model):
    if snap.experiment is not None:
        return None
    return Advice("start_experiment", "Try a 7-day experiment",
                  "Change one small thing for a week and see how it feels.", "experiment", 30)


def _rule_on_track(snap, now, model):
    return Advice("on_track", "You're on track",
                  "Nothing urgent right now. Pick something from Ideas if you like.", "ideas", 1)


RULES = (
    _rule_experiment_check, _rule_phone_curfew, _rule_distracted, _rule_no_focus, _rule_read,
    _rule_walk, _rule_write, _rule_weakest, _rule_hygiene, _rule_start_experiment, _rule_on_track,
)


def advice(snap: Snapshot, now: datetime, model: PersonalModel = None):
    """All advice that applies now, best first. Never empty (the on-track rule always fires).

    A rule answered today (done or not now) is skipped until tomorrow. The rank adapts:
    priority x (0.5 + acceptance), so rules the user keeps dismissing sink.
    """
    model = model or personal_model(snap)
    answered = {rule for day, rule, _ in snap.feedback if day == snap.today}
    found = [a for rule in RULES if (a := rule(snap, now, model)) and a.rule not in answered]
    if not found:
        found = [_rule_on_track(snap, now, model)]
    return sorted(found, key=lambda a: a.priority * (0.5 + model.weight(a.rule)), reverse=True)


def next_best_action(snap: Snapshot, now: datetime) -> Advice:
    return advice(snap, now)[0]
