# Unrot

A small Ubuntu desktop app based on the guide "How to Unrot Your Brain" by Colby Kultgen.
It turns the five steps into a calm daily checklist:

1. Phone curfew, 9 pm to 8 am
2. 20 minutes with no device
3. Write one story-worthy moment
4. Explore a topic
5. Read for fun

No streaks. Rest days never count against you. Each step has an (i) button that says
honestly how strong the evidence is (see `docs/research/report.md`).

## Install

Works on Ubuntu 24.04 LTS, 26.04 LTS, 26.10 and Debian 13 (needs libadwaita 1.5 or newer).

```sh
sudo apt install ./unrot_0.3.0_all.deb
```

Use `apt`, not `dpkg -i`, so the GTK libraries are installed for you.
Open **Unrot** from the app menu, or run `unrot`. Remove it with `sudo apt remove unrot`.

## Focus, scores and coach

```
 ATTENTION (Focus tab)          BEHAVIOR                     MEASUREMENT (Week tab)
 focus session + optional DND   5 daily steps, rest days     Focus     = avg(minutes / 5 h, sessions finished)
 one-tap distraction log        7-day experiment             Learning  = avg(read days, topic days, new books/topics / 2)
 phone setup checklist          breaks, eyes, walk           Digital   = avg(phone curfew days, no-device days, setup / 4)
                 \________________________|_________________________/
                                           v
          COACH (Today tab): rules for this time of day, each with a "why"
          PERSONAL MODEL: how often you accept each suggestion, your best focus hour
          NEXT BEST ACTION: highest priority x (0.5 + acceptance); "Not now" skips it until tomorrow
```

- Scores use only what you log. Wayland does not let apps see which window you use.
- Rest days are left out of every rate, so they never lower a score.
- Logging a distraction never lowers your focus score, so honest logging is safe.
- Ending a focus session puts Do Not Disturb back to how it was before.

## Your data

One SQLite file per user: `~/.local/share/unrot/unrot.db` (or `$XDG_DATA_HOME/unrot/`).
Nothing leaves your computer. Removing the package does not delete this file.

## Reminders and background mode

Unrot keeps running after you close the window, so reminders and the walk timer keep working.
On first run it also adds itself to "start at login" (hidden). Change both in
**Menu > Reminders and preferences**. **Ctrl+Q** quits fully.

Default reminders (each can be turned off or retimed):

| Reminder | When |
|---|---|
| Drink water | every 60 min, 09:00 to 18:00 |
| Take a break | every 35 min, 09:00 to 18:00 |
| Rest your eyes (20-20-20 rule and 4 more exercises, in turn) | every 20 min, 09:10 to 18:00 |
| Focus hour (button turns on Do Not Disturb for 60 min, GNOME only) | 10:00 |
| Lunch | 13:00 |
| 20-minute walk (button starts the timer) | 17:30 |
| Reading time | 20:30 |
| Phone curfew | 21:00 |
| Write one moment | 21:30 |

If a break and an eye reminder land at the same time, only the break is sent.
If the laptop was asleep, a reminder fires late only within 10 minutes; older ones are skipped.
The walk timer's end time is saved, so it survives closing the app, quitting, or a reboot.

To remove fully: `sudo apt remove unrot`. The login entry
`~/.config/autostart/io.github.unrot.Unrot.desktop` is then ignored (it has `TryExec`);
delete it if you want a clean home folder.

## Develop

```sh
python3 -m unittest            # 68 tests; UI tests skip without a display
python3 -m unrot.main          # run from source
./packaging/build.sh           # builds dist/unrot_<version>_all.deb
./packaging/check-distros.sh   # installs and tests it on Ubuntu 24.04/26.04/26.10 + Debian 13
```

Code layout:

```
unrot/content.py   the book's steps, ideas, and evidence notes (plain data)
unrot/store.py     SQLite storage, no GTK (easy to test)
unrot/reminders.py reminder schedules (pure functions)
unrot/autostart.py start-at-login file
unrot/attention.py distraction sources, phone setup, experiments
unrot/coach.py     scores, coach rules, personal model (pure functions)
unrot/focus_page.py the Focus tab
unrot/main.py      GTK 4 + libadwaita window, preferences, background app
packaging/         .desktop, icon, AppStream metainfo, control, build.sh
```
