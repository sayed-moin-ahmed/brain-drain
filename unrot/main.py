"""GTK 4 + libadwaita UI.

Only uses widgets available in libadwaita 1.5 (Ubuntu 24.04) that are not
deprecated in 1.9/1.10 (Ubuntu 26.04/26.10).
"""

import random
import sys
import time
from dataclasses import replace
from datetime import date, datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, VERSION  # noqa: E402
from .attention import EXPERIMENT_DAYS, EXPERIMENT_PRESETS, experiment_days, experiment_progress  # noqa: E402
from .autostart import autostart_path, set_autostart  # noqa: E402
from .coach import next_best_action, scores  # noqa: E402
from .content import IDEAS, PRACTICES, WALK_MINUTES  # noqa: E402
from .focus_page import FocusPage  # noqa: E402
from .reminders import DAILY, GRACE, body_for, coalesce, describe, is_due  # noqa: E402
from .store import DONE, REST, Store, default_db_path  # noqa: E402

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TICK_SECONDS = 15
DND_SCHEMA = "org.gnome.desktop.notifications"


def _boxed_list():
    box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
    box.add_css_class("boxed-list")
    return box


class UnrotWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Unrot", default_width=560, default_height=720,
                         width_request=360, height_request=400)
        self.store = app.store
        self.today = date.today()
        self._loading = False
        self._rows = {}
        self._walk_display = 0
        # In background mode, closing the window only hides it, so timers and reminders keep running.
        self.set_hide_on_close(app.background)

        self.toasts = Adw.ToastOverlay()
        self.stack = stack = Adw.ViewStack()
        self.focus_page = FocusPage(app, self.toasts)
        stack.add_titled_with_icon(self._build_today(), "today", "Today", "weather-clear-symbolic")
        stack.add_titled_with_icon(self.focus_page, "focus", "Focus", "find-location-symbolic")
        stack.add_titled_with_icon(self._build_week(), "week", "Week", "x-office-calendar-symbolic")
        stack.add_titled_with_icon(self._build_journal(), "journal", "Journal", "document-edit-symbolic")
        stack.add_titled_with_icon(self._build_library(), "library", "Library", "accessories-dictionary-symbolic")
        stack.add_titled_with_icon(self._build_ideas(), "ideas", "Ideas", "starred-symbolic")

        menu = Gio.Menu()
        menu.append("Start focus session", "app.focus-hour")
        menu.append("Reminders and preferences", "app.preferences")
        menu.append("About Unrot", "app.about")
        menu.append("Quit", "app.quit")
        switcher = Adw.ViewSwitcher(stack=stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header = Adw.HeaderBar(title_widget=switcher)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))

        # On narrow windows the switcher moves to a bottom bar.
        bottom = Adw.ViewSwitcherBar(stack=stack)
        view = Adw.ToolbarView(content=stack)
        view.add_top_bar(header)
        view.add_bottom_bar(bottom)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 500sp"))
        bp.add_setter(bottom, "reveal", True)
        bp.add_setter(switcher, "visible", False)
        self.add_breakpoint(bp)

        self.refresh_all()

    # Today

    def _build_today(self):
        page = Adw.PreferencesPage()

        # Cognitive coach: one suggestion at a time, with its reason.
        coach = Adw.PreferencesGroup(title="Next best action")
        self.nba_row = Adw.ActionRow(subtitle_lines=3)
        skip = Gtk.Button(label="Not now", valign=Gtk.Align.CENTER)
        skip.add_css_class("flat")
        skip.connect("clicked", self._on_advice, False)
        self.nba_do = Gtk.Button(valign=Gtk.Align.CENTER)
        self.nba_do.add_css_class("suggested-action")
        self.nba_do.connect("clicked", self._on_advice, True)
        self.nba_row.add_suffix(skip)
        self.nba_row.add_suffix(self.nba_do)
        coach.add(self.nba_row)
        page.add(coach)

        # Behavior: today's check for the running experiment.
        self.exp_today = Adw.PreferencesGroup(title="Experiment")
        self.exp_today_row = Adw.ActionRow(subtitle="Did you keep it today?")
        self.exp_yes = Gtk.ToggleButton(label="Yes", valign=Gtk.Align.CENTER)
        self.exp_no = Gtk.ToggleButton(label="No", valign=Gtk.Align.CENTER)
        for button, kept in ((self.exp_yes, True), (self.exp_no, False)):
            button.connect("toggled", self._on_exp_check, kept)
            self.exp_today_row.add_suffix(button)
        self.exp_today.add(self.exp_today_row)
        page.add(self.exp_today)

        self.steps_group = Adw.PreferencesGroup(title="The five steps")
        for p in PRACTICES:
            row = Adw.ActionRow(title=p.title, subtitle=p.how)
            why = Gtk.Button(icon_name="dialog-information-symbolic", valign=Gtk.Align.CENTER,
                             tooltip_text="What the evidence says")
            why.add_css_class("flat")
            why.connect("clicked", self._show_why, p)
            rest = Gtk.ToggleButton(label="Rest", valign=Gtk.Align.CENTER,
                                    tooltip_text="Rest day: never counts against you")
            rest.add_css_class("flat")
            done = Gtk.CheckButton(valign=Gtk.Align.CENTER, tooltip_text="Done today")
            done.connect("toggled", self._on_toggled, p.id, DONE)
            rest.connect("toggled", self._on_toggled, p.id, REST)
            row.add_suffix(why)
            row.add_suffix(rest)
            row.add_suffix(done)
            row.set_activatable_widget(done)
            self.steps_group.add(row)
            self._rows[p.id] = (done, rest)
        page.add(self.steps_group)

        moment = Adw.PreferencesGroup(title="One story-worthy moment",
                                      description="Press Enter to save. Saving marks “Write” as done.")
        self.moment_row = Adw.EntryRow(title="What happened today worth telling?", show_apply_button=True)
        self.moment_row.connect("apply", self._on_moment_apply)
        moment.add(self.moment_row)
        page.add(moment)

        walk = Adw.PreferencesGroup(title="No-device timer")
        self.walk_row = Adw.ActionRow(title=f"{WALK_MINUTES}-minute walk or quiet time",
                                      subtitle="Start it, then leave your screens behind.")
        self.walk_button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
        self.walk_button.add_css_class("suggested-action")
        self.walk_button.connect("clicked", self._on_walk_clicked)
        self.walk_row.add_suffix(self.walk_button)
        walk.add(self.walk_row)
        page.add(walk)
        return page

    def _refresh_today(self):
        self.steps_group.set_description(self.today.strftime("%A %-d %B"))
        states = self.store.states_for(self.today)
        self._loading = True
        try:
            for pid, (done, rest) in self._rows.items():
                done.set_active(states.get(pid) == DONE)
                rest.set_active(states.get(pid) == REST)
            self.moment_row.set_text(self.store.journal(self.today)["moment"])
        finally:
            self._loading = False

    def _on_toggled(self, button, practice_id, state):
        if self._loading:
            return
        self.store.set_state(self.today, practice_id, state if button.get_active() else None)
        self._refresh_today()
        self._refresh_week()
        self.refresh_coach()

    def _show_why(self, _button, practice):
        dialog = Adw.AlertDialog(heading=practice.title, body=practice.why)
        dialog.add_response("ok", "Got it")
        dialog.present(self)

    def _on_moment_apply(self, row):
        text = row.get_text().strip()
        self.store.save_journal(self.today, moment=text)
        if text:
            self.store.set_state(self.today, "write", DONE)
        self.refresh_all()
        self.toasts.add_toast(Adw.Toast(title="Moment saved"))

    def _on_walk_clicked(self, _button):
        app = self.get_application()
        if app.walk_remaining() is None:
            app.start_walk()
        else:
            app.stop_walk()
            self.refresh_walk("Timer stopped. No pressure.")

    def refresh_walk(self, idle_text="Start it, then leave your screens behind."):
        """Show the saved timer. The app owns it, so it survives closing the window."""
        left = self.get_application().walk_remaining()
        if left is None:
            # The 1-second display source stops itself on its next run.
            self.walk_button.set_label("Start")
            self.walk_button.add_css_class("suggested-action")
            self.walk_row.set_subtitle(idle_text)
            return
        left = int(left)
        self.walk_button.set_label("Stop")
        self.walk_button.remove_css_class("suggested-action")
        self.walk_row.set_subtitle(f"{left // 60:02d}:{left % 60:02d} left")
        if not self._walk_display:
            self._walk_display = GLib.timeout_add_seconds(1, self._on_walk_display)

    def _on_walk_display(self):
        app = self.get_application()
        app.check_walk()
        if app.walk_remaining() is None:
            self._walk_display = 0
            return GLib.SOURCE_REMOVE
        self.refresh_walk()
        return GLib.SOURCE_CONTINUE

    # Week

    def _build_week(self):
        page = Adw.PreferencesPage()

        # Measurement engine: three scores, each explained.
        scores_group = Adw.PreferencesGroup(title="This week's scores",
                                            description="Based only on what you logged in Unrot.")
        self.score_rows = []
        for _ in range(3):
            row = Adw.ActionRow(subtitle_lines=2)
            bar = Gtk.LevelBar(min_value=0, max_value=100, valign=Gtk.Align.CENTER, width_request=90)
            value = Gtk.Label(width_chars=3, xalign=1)
            info = Gtk.Button(icon_name="dialog-information-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="How this score works")
            info.add_css_class("flat")
            info.connect("clicked", self._show_score, len(self.score_rows))
            for widget in (bar, value, info):
                row.add_suffix(widget)
            scores_group.add(row)
            self.score_rows.append((row, bar, value))
        page.add(scores_group)

        self.week_group = Adw.PreferencesGroup(title="Last 7 days")
        self.week_grid = Gtk.Grid(column_spacing=12, row_spacing=10, halign=Gtk.Align.CENTER,
                                  margin_top=12, margin_bottom=12)
        frame = Gtk.Frame(child=self.week_grid)
        self.week_group.add(frame)
        page.add(self.week_group)
        note = Adw.PreferencesGroup(
            description="No streaks here. A missed day is just a day. Rest days are shown with a pause sign.")
        page.add(note)

        self.exp_group = Adw.PreferencesGroup(title="7-day experiment",
                                              description="Change one small thing for a week and see how it feels.")
        self._exp_rows = []
        page.add(self.exp_group)
        return page

    def _show_score(self, _button, index):
        score = self._scores[index]
        dialog = Adw.AlertDialog(heading=f"{score.name} score", body="\n".join(score.reasons))
        dialog.add_response("ok", "Got it")
        dialog.present(self)

    # Behavior: experiments

    def _refresh_experiment(self):
        for row in self._exp_rows:
            self.exp_group.remove(row)
        self._exp_rows = []
        exp = self.store.current_experiment()
        self.exp_today.set_visible(False)
        if exp is None:
            self._exp_choice = Adw.ComboRow(title="Pick one", model=Gtk.StringList.new(list(EXPERIMENT_PRESETS)))
            self._exp_custom = Adw.EntryRow(title="Or write your own")
            start = Adw.ActionRow(title=f"Run it for {EXPERIMENT_DAYS} days, starting today")
            button = Gtk.Button(label="Start", valign=Gtk.Align.CENTER)
            button.add_css_class("suggested-action")
            button.connect("clicked", self._on_exp_start)
            start.add_suffix(button)
            self._add_exp_rows(self._exp_choice, self._exp_custom, start)
            return

        day_number, finished = experiment_progress(exp.start, exp.days, self.today)
        kept = sum(1 for k in exp.checks.values() if k)
        days = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        for day in experiment_days(exp.start, exp.days):
            if day in exp.checks:
                icon = "object-select-symbolic" if exp.checks[day] else "window-close-symbolic"
                cell = Gtk.Image(icon_name=icon, tooltip_text=day.strftime("%a %-d %b"))
                cell.add_css_class("success" if exp.checks[day] else "error")
            else:
                cell = Gtk.Label(label="·", width_chars=2)
            days.append(cell)
        title = GLib.markup_escape_text(exp.title)
        if finished:
            summary = Adw.ActionRow(title=f"Finished: {title}",
                                    subtitle=f"You kept it {kept} of {exp.days} days. Keep it, change it, or drop it.")
            label = "Start a new one"
        else:
            summary = Adw.ActionRow(title=title, subtitle=f"Day {day_number} of {exp.days} · kept {kept} so far")
            label = "End early"
            self.exp_today.set_visible(True)
            self.exp_today_row.set_title(title)
            self._loading = True
            try:
                self.exp_yes.set_active(exp.checks.get(self.today) is True)
                self.exp_no.set_active(exp.checks.get(self.today) is False)
            finally:
                self._loading = False
        summary.add_suffix(days)
        end = Adw.ActionRow(title="Done with this one?" if finished else "Not working for you?")
        button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b: (self.store.end_experiment(exp.id), self.refresh_all()))
        end.add_suffix(button)
        self._add_exp_rows(summary, end)

    def _add_exp_rows(self, *rows):
        for row in rows:
            self.exp_group.add(row)
            self._exp_rows.append(row)

    def _on_exp_start(self, _button):
        title = self._exp_custom.get_text().strip() or EXPERIMENT_PRESETS[self._exp_choice.get_selected()]
        self.store.start_experiment(title, self.today, EXPERIMENT_DAYS)
        self.refresh_all()

    def _on_exp_check(self, button, kept):
        if self._loading:
            return
        exp = self.store.current_experiment()
        if exp is None:
            return
        if button.get_active():
            self.store.set_experiment_check(exp.id, self.today, kept)
        elif exp.checks.get(self.today) is kept:
            self.store.set_experiment_check(exp.id, self.today, None)
        self.refresh_all()

    # Coach and measurement

    ACTION_LABELS = {"focus": "Start", "walk": "Start walk", "practice": "Mark done", "write": "Write now",
                     "experiment_kept": "Yes, kept it"}

    def refresh_coach(self):
        snap = self.store.snapshot(self.today)
        self._scores = scores(snap)
        for (row, bar, value), score in zip(self.score_rows, self._scores):
            row.set_title(score.name)
            row.set_subtitle(GLib.markup_escape_text(score.reasons[0]))
            bar.set_value(score.value or 0)
            value.set_label("—" if score.value is None else str(score.value))
        self._advice = next_best_action(snap, datetime.now())
        self.nba_row.set_title(GLib.markup_escape_text(self._advice.title))
        self.nba_row.set_subtitle(GLib.markup_escape_text(self._advice.why))
        kind = self._advice.action.partition(":")[0]
        self.nba_do.set_label(self.ACTION_LABELS.get(kind, "Show me"))

    def _on_advice(self, _button, accepted):
        advice = self._advice
        self.store.add_feedback(self.today, advice.rule, "done" if accepted else "dismissed")
        if accepted:
            self._do_action(advice.action)
        self.refresh_all()

    def _do_action(self, action):
        kind, _, arg = action.partition(":")
        app = self.get_application()
        if kind == "focus":
            app.start_focus()
            self.stack.set_visible_child_name("focus")
        elif kind == "walk":
            app.start_walk()
        elif kind == "practice":
            self.store.set_state(self.today, arg, DONE)
        elif kind == "write":
            self.moment_row.grab_focus()
        elif kind == "experiment_kept":
            exp = self.store.current_experiment()
            if exp is not None:
                self.store.set_experiment_check(exp.id, self.today, True)
        elif kind in ("hygiene", "experiment", "ideas"):
            self.stack.set_visible_child_name({"hygiene": "focus", "experiment": "week"}.get(kind, kind))

    def _refresh_week(self):
        while (child := self.week_grid.get_first_child()) is not None:
            self.week_grid.remove(child)
        week = self.store.week(self.today)
        for col, (day, _) in enumerate(week, start=1):
            label = Gtk.Label(label=DAY_NAMES[day.weekday()])
            if day == self.today:
                label.add_css_class("heading")
            self.week_grid.attach(label, col, 0, 1, 1)
        for row, p in enumerate(PRACTICES, start=1):
            self.week_grid.attach(Gtk.Label(label=p.title.split(",")[0], xalign=0), 0, row, 1, 1)
            for col, (day, states) in enumerate(week, start=1):
                state = states.get(p.id)
                if state == DONE:
                    cell = Gtk.Image(icon_name="object-select-symbolic", tooltip_text="Done")
                    cell.add_css_class("success")
                elif state == REST:
                    cell = Gtk.Image(icon_name="media-playback-pause-symbolic", tooltip_text="Rest")
                else:
                    cell = Gtk.Label(label="·")
                self.week_grid.attach(cell, col, row, 1, 1)
        active = self.store.active_days(self.today)
        self.week_group.set_description(f"Active days: {active} of 7")

    # Journal

    def _build_journal(self):
        page = Adw.PreferencesPage()
        today = Adw.PreferencesGroup(title="Today's notes",
                                     description="Write by hand on paper if you can. This is the backup.")
        self.notes_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                       left_margin=8, right_margin=8)
        scroller = Gtk.ScrolledWindow(child=self.notes_view, min_content_height=160)
        today.add(Gtk.Frame(child=scroller))
        save = Gtk.Button(label="Save notes", halign=Gtk.Align.END, margin_top=8)
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save_notes)
        today.add(save)
        page.add(today)

        past = Adw.PreferencesGroup(title="Past entries")
        self.journal_list = _boxed_list()
        past.add(self.journal_list)
        page.add(past)
        return page

    def _refresh_journal(self):
        self.notes_view.get_buffer().set_text(self.store.journal(self.today)["notes"])
        self.journal_list.remove_all()
        entries = self.store.recent_journal()
        if not entries:
            self.journal_list.append(Adw.ActionRow(title="Nothing yet", subtitle="Your moments will appear here."))
        for e in entries:
            text = e["moment"] or e["notes"]
            row = Adw.ActionRow(title=e["day"].strftime("%a %-d %b %Y"), subtitle=GLib.markup_escape_text(text),
                                subtitle_lines=3)
            self.journal_list.append(row)

    def _on_save_notes(self, _button):
        buf = self.notes_view.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        self.store.save_journal(self.today, notes=text)
        if text.strip():
            self.store.set_state(self.today, "write", DONE)
        self.refresh_all()
        self.toasts.add_toast(Adw.Toast(title="Notes saved"))

    # Library: books and research topics

    def _build_library(self):
        page = Adw.PreferencesPage()
        self.lists = {}
        for kind, title, prompt in (
            ("book", "Books I enjoy", "Add a book (comics count)"),
            ("topic", "Topics to explore", "Add a topic you know nothing about"),
        ):
            group = Adw.PreferencesGroup(title=title)
            entry = Adw.EntryRow(title=prompt, show_apply_button=True)
            entry.connect("apply", self._on_add_entry, kind)
            group.add(entry)
            listbox = _boxed_list()
            listbox.set_margin_top(8)
            group.add(listbox)
            page.add(group)
            self.lists[kind] = listbox
        return page

    def _refresh_library(self):
        for kind, listbox in self.lists.items():
            listbox.remove_all()
            for e in self.store.entries(kind):
                row = Adw.ActionRow(title=GLib.markup_escape_text(e["title"]),
                                    subtitle=e["day"].strftime("Added %-d %b %Y"))
                delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove")
                delete.add_css_class("flat")
                delete.connect("clicked", self._on_delete_entry, e["id"])
                row.add_suffix(delete)
                listbox.append(row)

    def _on_add_entry(self, row, kind):
        text = row.get_text().strip()
        if not text:
            return
        self.store.add_entry(self.today, kind, text)
        row.set_text("")
        self._refresh_library()

    def _on_delete_entry(self, _button, entry_id):
        self.store.delete_entry(entry_id)
        self._refresh_library()

    # Ideas

    def _build_ideas(self):
        self.idea_page = Adw.StatusPage(icon_name="starred-symbolic",
                                        description="Another way to unrot your brain, from the book.")
        button = Gtk.Button(label="Another idea", halign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.connect("clicked", lambda _b: self._next_idea())
        self.idea_page.set_child(button)
        self._next_idea()
        return self.idea_page

    def _next_idea(self):
        current = self.idea_page.get_title()
        self.idea_page.set_title(random.choice([i for i in IDEAS if i != current]))

    # Shared

    def refresh_all(self):
        self._refresh_today()
        self._refresh_week()
        self._refresh_journal()
        self._refresh_library()
        self._refresh_experiment()
        self.focus_page.refresh()
        self.refresh_coach()
        self.refresh_walk()

    def check_new_day(self):
        if date.today() != self.today:
            self.today = date.today()
            self.refresh_all()


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, app):
        super().__init__(title="Preferences")
        self.app = app
        page = Adw.PreferencesPage(title="Reminders", icon_name="alarm-symbolic")

        general = Adw.PreferencesGroup(
            title="Background",
            description="Reminders and the walk timer work only while Unrot runs. Ctrl+Q quits fully.")
        background = Adw.SwitchRow(title="Keep running when the window is closed", active=app.background)
        self.login = Adw.SwitchRow(title="Start at login", subtitle="Starts hidden, so reminders survive a restart.",
                                   active=autostart_path().exists(), sensitive=app.background)
        background.connect("notify::active", self._on_background)
        self.login.connect("notify::active", lambda row, _p: set_autostart(row.get_active()))
        test = Adw.ActionRow(title="Send a test notification")
        send = Gtk.Button(label="Send", valign=Gtk.Align.CENTER)
        send.connect("clicked", lambda _b: app.send_alert("test", "Unrot", "Notifications work."))
        test.add_suffix(send)
        for row in (background, self.login, test):
            general.add(row)
        page.add(general)

        group = Adw.PreferencesGroup(title="Reminders", description="Turn each one on or off and set its time.")
        for reminder, _last in app.store.reminders():
            group.add(self._reminder_row(reminder))
        page.add(group)
        self.add(page)

    def _on_background(self, row, _param):
        enabled = row.get_active()
        self.app.set_background(enabled)
        self.login.set_sensitive(enabled)
        if not enabled:
            # A hidden start with no background mode would exit at once.
            self.login.set_active(False)

    def _reminder_row(self, reminder):
        row = Adw.ExpanderRow(title=reminder.title, subtitle=describe(reminder),
                              show_enable_switch=True, enable_expansion=reminder.enabled)
        current = [reminder]

        def save(**changes):
            current[0] = replace(current[0], **changes)
            self.app.store.save_reminder(current[0])
            row.set_subtitle(describe(current[0]))

        row.connect("notify::enable-expansion", lambda r, _p: save(enabled=r.get_enable_expansion()))
        if reminder.kind == DAILY:
            row.add_row(_time_row("Time", reminder.at, lambda m: save(at=m)))
        else:
            every = Adw.SpinRow.new_with_range(5, 240, 5)
            every.set_title("Every (minutes)")
            every.set_value(reminder.every)
            every.connect("notify::value", lambda r, _p: save(every=int(r.get_value())))
            row.add_row(every)
            row.add_row(_time_row("From", reminder.start, lambda m: save(start=m)))
            row.add_row(_time_row("Until", reminder.end, lambda m: save(end=m)))
        return row


def _time_row(title, minutes, on_change):
    row = Adw.ActionRow(title=title)
    hour = Gtk.SpinButton.new_with_range(0, 23, 1)
    minute = Gtk.SpinButton.new_with_range(0, 55, 5)
    hour.set_value(minutes // 60)
    minute.set_value(minutes % 60)
    for spin in (hour, minute):
        spin.set_valign(Gtk.Align.CENTER)
        spin.set_wrap(True)
        spin.connect("value-changed",
                     lambda _s: on_change(hour.get_value_as_int() * 60 + minute.get_value_as_int()))
        row.add_suffix(spin)
    return row


class UnrotApp(Adw.Application):
    """Owns the store, the walk timer, the focus hour and the reminders.

    In background mode it stays alive without a window, so all of them keep working.
    """

    def __init__(self, store, smoke=False, start_hidden=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.store = store
        self.smoke = smoke
        self.start_hidden = start_hidden
        self.window = None
        self.background = store.get_setting("background", "on") == "on"
        self._held = False
        self.dnd = self._dnd_settings()

        for name, callback in (
            ("show", lambda *_: self.show_window()),
            ("start-walk", lambda *_: self.start_walk()),
            ("focus-hour", lambda *_: self.start_focus()),
            ("stop-focus", lambda *_: self.stop_focus()),
            ("preferences", self._on_preferences),
            ("about", self._on_about),
            ("quit", lambda *_: self.quit()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    @staticmethod
    def _dnd_settings():
        source = Gio.SettingsSchemaSource.get_default()
        if source is None or source.lookup(DND_SCHEMA, True) is None:
            return None  # Not GNOME: there is no Do Not Disturb switch to flip.
        return Gio.Settings.new(DND_SCHEMA)

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.set_background(self.background)
        if not self.smoke:
            GLib.timeout_add_seconds(TICK_SECONDS, self._tick)
            self._tick()

    def do_activate(self):
        if self.start_hidden:
            self.start_hidden = False  # Later launches show the window.
            return
        self.show_window()
        if self.smoke:
            GLib.timeout_add(1000, self._smoke_quit)

    def show_window(self):
        if self.window is None:
            self.window = UnrotWindow(self)
        self.window.present()

    def _smoke_quit(self):
        self.quit()
        return GLib.SOURCE_REMOVE

    def set_background(self, enabled):
        self.background = enabled
        self.store.set_setting("background", "on" if enabled else "off")
        if enabled and not self._held:
            self.hold()
            self._held = True
        elif not enabled and self._held:
            self.release()
            self._held = False
        if self.window is not None:
            self.window.set_hide_on_close(enabled)

    def _tick(self, now=None):
        now = datetime.now() if now is None else now
        if self.window is not None:
            self.window.check_new_day()
            # Coach advice depends on the time of day, so re-pick it as time passes.
            if self.window.get_visible():
                self.window.refresh_coach()
        self.check_walk()
        self.check_focus()
        due = {r.id: r for r, last in self.store.reminders() if r.enabled and is_due(r, last, now)}
        for reminder_id in due:
            # Dropped ones count as fired too, or they would come back next tick.
            self.store.mark_fired(reminder_id, now)
        for reminder_id in coalesce(list(due)):
            r = due[reminder_id]
            self.send_alert(r.id, r.title, body_for(r, now), r.action)
        return GLib.SOURCE_CONTINUE

    def send_alert(self, notification_id, title, body, action=""):
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_default_action("app.show")
        if action == "walk":
            n.add_button("Start timer", "app.start-walk")
        elif action == "focus":
            n.add_button("Start focus session", "app.focus-hour")
        self.send_notification(notification_id, n)

    # Walk timer: the end time is saved as wall-clock seconds, so it survives
    # closing the window, quitting, and even a reboot.

    def walk_remaining(self):
        end = self.store.get_setting("walk_end")
        return max(0.0, float(end) - time.time()) if end else None

    def start_walk(self):
        self.store.set_setting("walk_end", repr(time.time() + WALK_MINUTES * 60))
        if self.window is not None:
            self.window.refresh_walk()

    def stop_walk(self):
        self.store.set_setting("walk_end", "")

    def check_walk(self, now=None):
        """Finish the timer once its end time has passed. Returns True if it finished."""
        end = self.store.get_setting("walk_end")
        now = time.time() if now is None else now
        if not end or now < float(end):
            return False
        end = float(end)
        self.store.set_setting("walk_end", "")
        self.store.set_state(date.fromtimestamp(end), "boredom", DONE)
        if now - end <= GRACE.total_seconds():
            self.send_alert("walk-done", "Time's up", f"{WALK_MINUTES} minutes with no device. Nice.")
        if self.window is not None:
            self.window.refresh_all()
        return True

    # Focus session: optional GNOME Do Not Disturb, restored when it ends.
    # Saved like the walk timer, so a restart still ends it and restores DND.

    def focus_remaining(self):
        until = self.store.get_setting("focus_until")
        return max(0.0, float(until) - time.time()) if until else None

    def start_focus(self, minutes=None, dnd=None):
        if self.focus_remaining() is not None:
            return
        minutes = minutes or int(self.store.get_setting("focus_minutes", "50"))
        dnd = (self.store.get_setting("focus_dnd", "on") == "on") if dnd is None else dnd
        start = time.time()
        self.store.set_setting("focus_start", repr(start))
        self.store.set_setting("focus_planned", str(minutes))
        self.store.set_setting("focus_until", repr(start + minutes * 60))
        # Remember the user's own setting, so ending never turns DND off on them.
        previous = ""
        if dnd and self.dnd is not None:
            previous = "on" if self.dnd.get_boolean("show-banners") else "off"
            self.dnd.set_boolean("show-banners", False)
        self.store.set_setting("focus_banners_before", previous)
        if self.window is not None:
            quiet = " with Do Not Disturb" if previous else ""
            self.window.toasts.add_toast(Adw.Toast(title=f"Focus for {minutes} minutes{quiet}"))
            self.window.refresh_all()

    def stop_focus(self):
        if self.focus_remaining() is not None:
            self._end_focus(time.time(), completed=False)

    def check_focus(self, now=None):
        until = self.store.get_setting("focus_until")
        now = time.time() if now is None else now
        if not until or now < float(until):
            return False
        self._end_focus(float(until), completed=True)
        if now - float(until) <= GRACE.total_seconds():
            self.send_alert("focus-done", "Focus session done", "Nice work. Take a short break.")
        return True

    def _end_focus(self, end, completed):
        start = float(self.store.get_setting("focus_start"))
        planned = int(self.store.get_setting("focus_planned"))
        done = min(planned, max(0, round((end - start) / 60)))
        # A session belongs to the day it started, even if it crosses midnight.
        self.store.add_focus_session(datetime.fromtimestamp(start), planned, done, completed)
        for key in ("focus_start", "focus_planned", "focus_until"):
            self.store.set_setting(key, "")
        previous = self.store.get_setting("focus_banners_before")
        if previous and self.dnd is not None:
            self.dnd.set_boolean("show-banners", previous == "on")
        self.store.set_setting("focus_banners_before", "")
        if self.window is not None:
            self.window.refresh_all()

    def _on_preferences(self, *_args):
        self.show_window()
        PreferencesDialog(self).present(self.window)

    def _on_about(self, *_args):
        self.show_window()
        about = Adw.AboutDialog(
            application_name="Unrot",
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Unrot contributors",
            license_type=Gtk.License.MIT_X11,
            comments=(
                "A small daily practice based on “How to Unrot Your Brain” "
                "by Colby Kultgen.\n\nYour data stays on this computer."
            ),
        )
        about.present(self.window)


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    smoke = "--smoke" in argv
    hidden = "--background" in argv
    argv = [a for a in argv if a not in ("--smoke", "--background")]
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Unrot")
    store = Store(default_db_path())
    if not smoke and store.get_setting("autostart_offered") != "yes":
        # First run: start at login so reminders work after a restart.
        # The user can switch this off in Preferences.
        store.set_setting("autostart_offered", "yes")
        set_autostart(True)
    try:
        return UnrotApp(store, smoke=smoke, start_hidden=hidden).run(argv)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
