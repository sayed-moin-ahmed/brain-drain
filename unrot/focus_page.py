"""The Focus tab (attention): focus session, distraction log, phone setup."""

from collections import Counter
from datetime import date, datetime, timedelta

from gi.repository import Adw, GLib, Gtk

from .attention import DISTRACTION_SOURCES, HYGIENE_ITEMS


def _minutes(m):
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h" if m % 60 == 0 else f"{m // 60} h {m % 60} min"


class FocusPage(Adw.PreferencesPage):
    def __init__(self, app, toasts):
        super().__init__()
        self.app = app
        self.store = app.store
        self.toasts = toasts
        self._loading = False
        self._display = 0

        # Focus session
        session = Adw.PreferencesGroup(title="Focus session",
                                       description="One task. Phone out of reach.")
        self.minutes_row = Adw.SpinRow.new_with_range(10, 120, 5)
        self.minutes_row.set_title("Minutes")
        self.minutes_row.connect("notify::value", self._on_minutes)
        self.dnd_row = Adw.SwitchRow(title="Turn on Do Not Disturb",
                                     subtitle="Turned back to how it was when the session ends.")
        self.dnd_row.set_sensitive(app.dnd is not None)
        self.dnd_row.connect("notify::active", self._on_dnd)
        self.timer_row = Adw.ActionRow(title="Ready")
        self.start_button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
        self.start_button.add_css_class("suggested-action")
        self.start_button.connect("clicked", self._on_start_stop)
        self.timer_row.add_suffix(self.start_button)
        for row in (self.minutes_row, self.dnd_row, self.timer_row):
            session.add(row)
        self.add(session)

        # Distraction log
        distract = Adw.PreferencesGroup(
            title="Got distracted?",
            description="Tap what pulled you away. No judgment: this never lowers your focus score.")
        # A group always lists its rows first, so the count row sits above the buttons.
        self.distract_row = Adw.ActionRow(title="Today: 0")
        distract.add(self.distract_row)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                           column_spacing=6, row_spacing=6, homogeneous=True, margin_top=10)
        for source in DISTRACTION_SOURCES:
            button = Gtk.Button(label=source)
            button.connect("clicked", self._on_distraction, source)
            flow.append(button)
        distract.add(flow)
        self.add(distract)

        # Digital hygiene: step 1 of the book as a one-time setup
        hygiene = Adw.PreferencesGroup(title="Phone setup", description="From step 1 of the book. Do each once.")
        self.hygiene_checks = {}
        for item_id, label in HYGIENE_ITEMS:
            row = Adw.ActionRow(title=label)
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            check.connect("toggled", self._on_hygiene, item_id)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            hygiene.add(row)
            self.hygiene_checks[item_id] = check
        self.add(hygiene)

    # Refresh

    def refresh(self):
        self.store = self.app.store
        self._loading = True
        try:
            self.minutes_row.set_value(int(self.store.get_setting("focus_minutes", "50")))
            self.dnd_row.set_active(self.app.dnd is not None and self.store.get_setting("focus_dnd", "on") == "on")
            for item_id, done in self.store.hygiene().items():
                self.hygiene_checks[item_id].set_active(done)
        finally:
            self._loading = False
        self._refresh_timer()
        self._refresh_distractions()

    def _refresh_timer(self):
        today = date.today()
        sessions = self.store.focus_sessions(today - timedelta(days=6))
        today_min = sum(s.done_min for s in sessions if s.started.date() == today)
        week_min = sum(s.done_min for s in sessions)
        stats = f"Today {_minutes(today_min)} · this week {_minutes(week_min)}"
        left = self.app.focus_remaining()
        running = left is not None
        self.minutes_row.set_sensitive(not running)
        self.dnd_row.set_sensitive(not running and self.app.dnd is not None)
        if running:
            left = int(left)
            self.timer_row.set_title(f"{left // 60:02d}:{left % 60:02d} left")
            self.start_button.set_label("Stop")
            self.start_button.remove_css_class("suggested-action")
            if not self._display:
                self._display = GLib.timeout_add_seconds(1, self._on_display)
        else:
            self.timer_row.set_title("Ready")
            self.start_button.set_label("Start")
            self.start_button.add_css_class("suggested-action")
        self.timer_row.set_subtitle(stats)

    def _on_display(self):
        self.app.check_focus()
        if self.app.focus_remaining() is None:
            self._display = 0
            return GLib.SOURCE_REMOVE
        self._refresh_timer()
        return GLib.SOURCE_CONTINUE

    def _refresh_distractions(self):
        today = date.today()
        week = self.store.distractions(today - timedelta(days=6))
        today_count = sum(1 for at, _ in week if at.date() == today)
        self.distract_row.set_title(f"Today: {today_count} · this week: {len(week)}")
        if week:
            top, n = Counter(src for _, src in week).most_common(1)[0]
            self.distract_row.set_subtitle(f"Most often this week: {top} ({n})")
        else:
            self.distract_row.set_subtitle("Nothing logged this week.")

    # Handlers

    def _on_minutes(self, row, _param):
        if not self._loading:
            self.store.set_setting("focus_minutes", str(int(row.get_value())))

    def _on_dnd(self, row, _param):
        if not self._loading:
            self.store.set_setting("focus_dnd", "on" if row.get_active() else "off")

    def _on_start_stop(self, _button):
        if self.app.focus_remaining() is None:
            self.app.start_focus()
        else:
            self.app.stop_focus()

    def _on_distraction(self, _button, source):
        distraction_id = self.store.add_distraction(datetime.now(), source)
        self._refresh_distractions()
        toast = Adw.Toast(title=f"Logged: {source}", button_label="Undo")
        toast.connect("button-clicked", lambda _t: self._undo(distraction_id))
        self.toasts.add_toast(toast)

    def _undo(self, distraction_id):
        self.store.delete_distraction(distraction_id)
        self._refresh_distractions()

    def _on_hygiene(self, check, item_id):
        if not self._loading:
            self.store.set_hygiene(item_id, check.get_active())
            self.get_root().refresh_coach()
