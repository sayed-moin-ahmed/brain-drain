"""Reminder schedules. Pure functions, no GTK, so they are easy to test.

Two kinds:
- daily: once a day at a fixed time (lunch at 13:00)
- interval: every N minutes inside a time window (water every 60 min, 9:00 to 18:00),
  aligned to the window start so times are predictable (9:00, 10:00, ...)
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

DAILY = "daily"
INTERVAL = "interval"

# A reminder missed while the laptop slept fires late only inside this window.
GRACE = timedelta(minutes=10)


@dataclass(frozen=True)
class Reminder:
    id: str
    title: str
    body: str
    kind: str
    at: int = 0  # daily: minutes after midnight
    every: int = 60  # interval: minutes between reminders
    start: int = 9 * 60  # interval window start, minutes after midnight
    end: int = 18 * 60  # interval window end, exclusive
    enabled: bool = True
    action: str = ""  # optional notification button: "walk" or "focus"


DEFAULT_REMINDERS = (
    Reminder("water", "Drink water", "A glass of water, then back to it.", INTERVAL, every=60),
    Reminder("move", "Take a break", "Stand up, stretch, and look away from the screen for two minutes.",
             INTERVAL, every=35),
    # Starts at :10 so it never lands on the hourly water reminder.
    Reminder("eyes", "Rest your eyes", "", INTERVAL, every=20, start=9 * 60 + 10),
    Reminder("focus", "Focus hour", "Turn on Do Not Disturb and do one thing.", DAILY,
             at=10 * 60, action="focus"),
    Reminder("lunch", "Lunch time", "Eat without a screen. It counts as boredom practice.", DAILY,
             at=13 * 60),
    Reminder("walk", "20-minute walk", "No phone. Start the timer and go.", DAILY,
             at=17 * 60 + 30, action="walk"),
    Reminder("read", "Reading time", "Read something you enjoy.", DAILY, at=20 * 60 + 30),
    Reminder("phone", "Phone curfew", "It's 9 pm. Put the phone away until 8 am.", DAILY, at=21 * 60),
    Reminder("write", "Write one moment", "What happened today worth telling?", DAILY,
             at=21 * 60 + 30),
)

EDITABLE_FIELDS = ("enabled", "at", "every", "start", "end")

# Shown one at a time, in turn, by the "eyes" reminder.
EYE_EXERCISES = (
    "20-20-20: look at something about 20 feet (6 m) away for 20 seconds.",
    "Blink slowly 10 times. Screens make us blink less.",
    "Palming: rub your hands warm, cup them over closed eyes, breathe for 20 seconds.",
    "Near and far: focus on your thumb, then on something far away. Repeat 5 times.",
    "Eye circles: look up, right, down, left. Slowly, 5 times each way.",
)

# When both are due at the same moment, only the first is sent:
# a break already includes looking away from the screen.
SUPPRESSED_BY = {"eyes": "move"}


def body_for(reminder: Reminder, now: datetime) -> str:
    """Notification text. The eye reminder rotates through EYE_EXERCISES."""
    if reminder.id == "eyes":
        slot = (now.hour * 60 + now.minute) // max(reminder.every, 1)
        return EYE_EXERCISES[slot % len(EYE_EXERCISES)]
    return reminder.body


def coalesce(due_ids):
    """Drop reminders whose stronger sibling is due at the same time."""
    due = set(due_ids)
    return [rid for rid in due_ids if SUPPRESSED_BY.get(rid) not in due]


def _at(day, minutes):
    return datetime.combine(day, time(minutes // 60, minutes % 60))


def next_due(reminder: Reminder, after: datetime):
    """First scheduled time strictly after `after`, or None if it never fires.

    Checking today and tomorrow is always enough: every schedule repeats daily.
    """
    for offset in (0, 1):
        day = after.date() + timedelta(days=offset)
        if reminder.kind == DAILY:
            times = (reminder.at,)
        else:
            times = range(reminder.start, reminder.end, max(reminder.every, 1))
        for minutes in times:
            when = _at(day, minutes)
            if when > after:
                return when
    return None


def is_due(reminder: Reminder, last_fired, now: datetime, grace=GRACE) -> bool:
    """True when a scheduled time passed since the last firing (or within `grace`)."""
    anchor = now - grace
    if last_fired is not None and last_fired > anchor:
        anchor = last_fired
    when = next_due(reminder, anchor)
    return when is not None and when <= now


def describe(reminder: Reminder) -> str:
    def hm(minutes):
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    if reminder.kind == DAILY:
        return f"Every day at {hm(reminder.at)}"
    return f"Every {reminder.every} min, {hm(reminder.start)} to {hm(reminder.end)}"
