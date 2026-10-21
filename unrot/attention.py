"""Attention and behavior content: distraction sources, the book's phone setup,
and 7-day experiments. Plain data and pure functions, no GTK."""

from datetime import date, timedelta

DISTRACTION_SOURCES = ("Phone", "Social media", "Video", "News", "Chat", "Other")

# Step 1 of the book, "Break up with your phone", as a one-time setup.
HYGIENE_ITEMS = (
    ("grayscale", "Phone in grayscale mode"),
    ("widget", "Screen-time widget on the phone's home screen"),
    ("alerts", "Non-essential notifications off, or batched a few times a day"),
    ("bedroom", "Phone charges outside the bedroom"),
)

EXPERIMENT_DAYS = 7
EXPERIMENT_PRESETS = (
    "No phone at lunch",
    "No phone in bed",
    "Grayscale all day",
    "Walk without my phone",
    "No social media before noon",
    "Read 10 pages before any screen",
)


def experiment_progress(start: date, days: int, today: date):
    """Return (day_number, finished). Day 1 is the start day."""
    day_number = (today - start).days + 1
    return day_number, day_number > days


def experiment_days(start: date, days: int):
    return [start + timedelta(days=i) for i in range(days)]
