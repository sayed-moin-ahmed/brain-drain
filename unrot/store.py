"""SQLite storage. No GTK imports here, so it can be tested anywhere."""

import os
import sqlite3
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from .attention import HYGIENE_ITEMS
from .coach import MODEL_DAYS, Experiment, FocusSession, Snapshot
from .content import DONE, PRACTICE_IDS, REST
from .reminders import DEFAULT_REMINDERS, EDITABLE_FIELDS

STATES = (DONE, REST)
LOG_KINDS = ("book", "topic")

SCHEMA = """
CREATE TABLE IF NOT EXISTS practice_log (
    day      TEXT NOT NULL,
    practice TEXT NOT NULL,
    state    TEXT NOT NULL CHECK (state IN ('done', 'rest')),
    PRIMARY KEY (day, practice)
);
CREATE TABLE IF NOT EXISTS journal (
    day    TEXT PRIMARY KEY,
    moment TEXT NOT NULL DEFAULT '',
    notes  TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS log_entry (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    day   TEXT NOT NULL,
    kind  TEXT NOT NULL CHECK (kind IN ('book', 'topic')),
    title TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS log_entry_kind_day ON log_entry (kind, day DESC, id DESC);
CREATE TABLE IF NOT EXISTS setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_session (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started     TEXT NOT NULL,
    planned_min INTEGER NOT NULL,
    done_min    INTEGER NOT NULL,
    completed   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS focus_session_started ON focus_session (started);
CREATE TABLE IF NOT EXISTS distraction (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS distraction_at ON distraction (at);
CREATE TABLE IF NOT EXISTS experiment (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    title     TEXT NOT NULL,
    start_day TEXT NOT NULL,
    days      INTEGER NOT NULL,
    ended     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS experiment_check (
    experiment_id INTEGER NOT NULL,
    day           TEXT NOT NULL,
    kept          INTEGER NOT NULL,
    PRIMARY KEY (experiment_id, day)
);
CREATE TABLE IF NOT EXISTS coach_feedback (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    day      TEXT NOT NULL,
    rule     TEXT NOT NULL,
    response TEXT NOT NULL CHECK (response IN ('done', 'dismissed'))
);
CREATE INDEX IF NOT EXISTS coach_feedback_day ON coach_feedback (day);
CREATE TABLE IF NOT EXISTS reminder (
    id         TEXT PRIMARY KEY,
    enabled    INTEGER,
    at         INTEGER,
    every      INTEGER,
    start      INTEGER,
    end        INTEGER,
    last_fired TEXT
);
"""


def default_db_path() -> Path:
    """Same rule as GLib.get_user_data_dir(), plus a test override."""
    override = os.environ.get("UNROT_DATA_DIR")
    if override:
        return Path(override) / "unrot.db"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    # The XDG spec says relative paths must be ignored.
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".local" / "share"
    return base / "unrot" / "unrot.db"


def is_active_day(states: dict) -> bool:
    """A day counts as active when at least one practice was done.

    Rest days are neutral: they never make a day count as missed.
    """
    return any(s == DONE for s in states.values())


class Store:
    def __init__(self, path):
        path = Path(path)
        # The journal is private: other local users must not read it.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(SCHEMA)

    def close(self):
        self._db.close()

    # Practices

    def set_state(self, day: date, practice: str, state):
        if practice not in PRACTICE_IDS:
            raise ValueError(f"unknown practice: {practice}")
        with self._db:
            if state is None:
                self._db.execute(
                    "DELETE FROM practice_log WHERE day = ? AND practice = ?",
                    (day.isoformat(), practice),
                )
            elif state in STATES:
                self._db.execute(
                    "INSERT INTO practice_log (day, practice, state) VALUES (?, ?, ?) "
                    "ON CONFLICT (day, practice) DO UPDATE SET state = excluded.state",
                    (day.isoformat(), practice, state),
                )
            else:
                raise ValueError(f"unknown state: {state}")

    def states_for(self, day: date) -> dict:
        rows = self._db.execute(
            "SELECT practice, state FROM practice_log WHERE day = ?",
            (day.isoformat(),),
        )
        return dict(rows.fetchall())

    def week(self, end: date):
        """The 7 days ending on `end`, oldest first, as (day, states)."""
        start = end - timedelta(days=6)
        rows = self._db.execute(
            "SELECT day, practice, state FROM practice_log WHERE day BETWEEN ? AND ?",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        days = [start + timedelta(days=i) for i in range(7)]
        by_day = {d.isoformat(): {} for d in days}
        for day, practice, state in rows:
            by_day[day][practice] = state
        return [(d, by_day[d.isoformat()]) for d in days]

    def active_days(self, end: date) -> int:
        return sum(1 for _, states in self.week(end) if is_active_day(states))

    # Journal

    def save_journal(self, day: date, moment=None, notes=None):
        current = self.journal(day)
        moment = current["moment"] if moment is None else moment.strip()
        notes = current["notes"] if notes is None else notes.strip()
        with self._db:
            if not moment and not notes:
                self._db.execute("DELETE FROM journal WHERE day = ?", (day.isoformat(),))
                return
            self._db.execute(
                "INSERT INTO journal (day, moment, notes) VALUES (?, ?, ?) "
                "ON CONFLICT (day) DO UPDATE SET moment = excluded.moment, "
                "notes = excluded.notes",
                (day.isoformat(), moment, notes),
            )

    def journal(self, day: date) -> dict:
        row = self._db.execute(
            "SELECT moment, notes FROM journal WHERE day = ?", (day.isoformat(),)
        ).fetchone()
        return {"moment": row[0], "notes": row[1]} if row else {"moment": "", "notes": ""}

    def recent_journal(self, limit=30):
        rows = self._db.execute(
            "SELECT day, moment, notes FROM journal ORDER BY day DESC LIMIT ?", (limit,)
        )
        return [
            {"day": date.fromisoformat(d), "moment": m, "notes": n}
            for d, m, n in rows.fetchall()
        ]

    # Reading and research log

    def add_entry(self, day: date, kind: str, title: str) -> int:
        if kind not in LOG_KINDS:
            raise ValueError(f"unknown kind: {kind}")
        title = title.strip()
        if not title:
            raise ValueError("title is empty")
        with self._db:
            cur = self._db.execute(
                "INSERT INTO log_entry (day, kind, title) VALUES (?, ?, ?)",
                (day.isoformat(), kind, title),
            )
        return cur.lastrowid

    def entries(self, kind: str, limit=50):
        rows = self._db.execute(
            "SELECT id, day, title FROM log_entry WHERE kind = ? "
            "ORDER BY day DESC, id DESC LIMIT ?",
            (kind, limit),
        )
        return [
            {"id": i, "day": date.fromisoformat(d), "title": t} for i, d, t in rows.fetchall()
        ]

    def delete_entry(self, entry_id: int):
        with self._db:
            self._db.execute("DELETE FROM log_entry WHERE id = ?", (entry_id,))

    # Reminders: titles and texts come from DEFAULT_REMINDERS; the table only
    # keeps what the user changed, plus when each reminder last fired.

    def reminders(self):
        """All reminders in default order, as (reminder, last_fired or None)."""
        cols = ", ".join(EDITABLE_FIELDS)
        rows = {
            r[0]: r[1:]
            for r in self._db.execute(f"SELECT id, {cols}, last_fired FROM reminder")
        }
        result = []
        for default in DEFAULT_REMINDERS:
            row = rows.get(default.id)
            if row is None:
                result.append((default, None))
                continue
            changes = {f: v for f, v in zip(EDITABLE_FIELDS, row) if v is not None}
            if "enabled" in changes:
                changes["enabled"] = bool(changes["enabled"])
            last = datetime.fromisoformat(row[-1]) if row[-1] else None
            result.append((replace(default, **changes), last))
        return result

    def save_reminder(self, reminder):
        values = [getattr(reminder, f) for f in EDITABLE_FIELDS]
        values[0] = int(values[0])
        cols = ", ".join(EDITABLE_FIELDS)
        updates = ", ".join(f"{f} = excluded.{f}" for f in EDITABLE_FIELDS)
        with self._db:
            self._db.execute(
                f"INSERT INTO reminder (id, {cols}) VALUES (?, ?, ?, ?, ?, ?) "
                f"ON CONFLICT (id) DO UPDATE SET {updates}",
                (reminder.id, *values),
            )

    def mark_fired(self, reminder_id: str, when: datetime):
        with self._db:
            self._db.execute(
                "INSERT INTO reminder (id, last_fired) VALUES (?, ?) "
                "ON CONFLICT (id) DO UPDATE SET last_fired = excluded.last_fired",
                (reminder_id, when.isoformat(timespec="seconds")),
            )

    # Attention: focus sessions and distractions

    def add_focus_session(self, started: datetime, planned_min: int, done_min: int, completed: bool):
        with self._db:
            self._db.execute(
                "INSERT INTO focus_session (started, planned_min, done_min, completed) VALUES (?, ?, ?, ?)",
                (started.isoformat(timespec="seconds"), planned_min, done_min, int(completed)),
            )

    def focus_sessions(self, since: date):
        rows = self._db.execute(
            "SELECT started, planned_min, done_min, completed FROM focus_session "
            "WHERE started >= ? ORDER BY started",
            (since.isoformat(),),
        )
        return [
            FocusSession(datetime.fromisoformat(s), p, d, bool(c)) for s, p, d, c in rows.fetchall()
        ]

    def add_distraction(self, at: datetime, source: str) -> int:
        with self._db:
            cur = self._db.execute(
                "INSERT INTO distraction (at, source) VALUES (?, ?)",
                (at.isoformat(timespec="seconds"), source),
            )
        return cur.lastrowid

    def delete_distraction(self, distraction_id: int):
        with self._db:
            self._db.execute("DELETE FROM distraction WHERE id = ?", (distraction_id,))

    def distractions(self, since: date):
        rows = self._db.execute(
            "SELECT at, source FROM distraction WHERE at >= ? ORDER BY at", (since.isoformat(),)
        )
        return [(datetime.fromisoformat(a), s) for a, s in rows.fetchall()]

    def hygiene(self) -> dict:
        return {item_id: self.get_setting(f"hygiene:{item_id}") == "on" for item_id, _ in HYGIENE_ITEMS}

    def set_hygiene(self, item_id: str, done: bool):
        self.set_setting(f"hygiene:{item_id}", "on" if done else "off")

    # Behavior: one experiment at a time

    def start_experiment(self, title: str, start: date, days: int) -> int:
        title = title.strip()
        if not title:
            raise ValueError("title is empty")
        with self._db:
            self._db.execute("UPDATE experiment SET ended = 1 WHERE ended = 0")
            cur = self._db.execute(
                "INSERT INTO experiment (title, start_day, days) VALUES (?, ?, ?)",
                (title, start.isoformat(), days),
            )
        return cur.lastrowid

    def current_experiment(self):
        row = self._db.execute(
            "SELECT id, title, start_day, days FROM experiment WHERE ended = 0 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        checks = dict(
            self._db.execute(
                "SELECT day, kept FROM experiment_check WHERE experiment_id = ?", (row[0],)
            ).fetchall()
        )
        return Experiment(
            row[0], row[1], date.fromisoformat(row[2]), row[3],
            {date.fromisoformat(d): bool(k) for d, k in checks.items()},
        )

    def set_experiment_check(self, experiment_id: int, day: date, kept):
        with self._db:
            if kept is None:
                self._db.execute(
                    "DELETE FROM experiment_check WHERE experiment_id = ? AND day = ?",
                    (experiment_id, day.isoformat()),
                )
            else:
                self._db.execute(
                    "INSERT INTO experiment_check (experiment_id, day, kept) VALUES (?, ?, ?) "
                    "ON CONFLICT (experiment_id, day) DO UPDATE SET kept = excluded.kept",
                    (experiment_id, day.isoformat(), int(kept)),
                )

    def end_experiment(self, experiment_id: int):
        with self._db:
            self._db.execute("UPDATE experiment SET ended = 1 WHERE id = ?", (experiment_id,))

    # Coach: what the user did with each suggestion (the personal model learns from this)

    def add_feedback(self, day: date, rule: str, response: str):
        with self._db:
            self._db.execute(
                "INSERT INTO coach_feedback (day, rule, response) VALUES (?, ?, ?)",
                (day.isoformat(), rule, response),
            )

    def feedback(self, since: date):
        rows = self._db.execute(
            "SELECT day, rule, response FROM coach_feedback WHERE day >= ?", (since.isoformat(),)
        )
        return [(date.fromisoformat(d), r, x) for d, r, x in rows.fetchall()]

    def snapshot(self, today: date) -> Snapshot:
        """Everything the measurement engine and coach need, in one read."""
        history = today - timedelta(days=MODEL_DAYS - 1)
        week_start = today - timedelta(days=6)
        added = self._db.execute(
            "SELECT COUNT(*) FROM log_entry WHERE day >= ?", (week_start.isoformat(),)
        ).fetchone()[0]
        return Snapshot(
            today=today,
            week=self.week(today),
            sessions=self.focus_sessions(history),
            distractions=self.distractions(week_start),
            library_added=added,
            hygiene=self.hygiene(),
            experiment=self.current_experiment(),
            feedback=self.feedback(history),
            journal_today=bool(self.journal(today)["moment"] or self.journal(today)["notes"]),
        )

    # Settings

    def get_setting(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self._db:
            self._db.execute(
                "INSERT INTO setting (key, value) VALUES (?, ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
