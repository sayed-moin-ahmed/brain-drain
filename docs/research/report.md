# Research report: building "Unrot" from "How to Unrot Your Brain"

As of 2026-10-21. Tier: Standard (3 parallel research threads). Claim ledger: `ledger.json`.

## Executive summary

- The book's five steps are reasonable habits, but the evidence behind them is uneven. The strongest support is for grayscale mode and batching notifications. Writing, boredom and research rest on weak or no direct evidence. The app's "why" notes say this plainly.
- The book's "recent Nature study" on writing is really an editorial, not a study ([1] https://www.nature.com/articles/s44222-025-00323-4).
- No Linux app combines these five practices. Streak-based trackers draw complaints, so Unrot has no streaks and allows rest days ([8] https://github.com/iSoron/uhabits).
- One `Architecture: all` .deb can target Ubuntu 24.04, 26.04 and 26.10 if the UI sticks to libadwaita 1.5 APIs that are not deprecated later ([12] https://releases.ubuntu.com/26.10/, [14] https://gitlab.gnome.org/GNOME/libadwaita/-/raw/main/NEWS).

## Findings

### Evidence for the book's claims

| Claim | Strength | Note |
|---|---|---|
| "Nature study: writing is thinking" | Misattributed | 2025 editorial in Nature Reviews Bioengineering [1]. It points to a 36-person EEG study that measured brain activity, not learning [2] (https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2023.1219945/full). |
| Grayscale cuts phone use | Moderate | Two teams: about 20 min/day less (https://link.springer.com/article/10.1007/s12144-021-02020-y, https://api.crossref.org/works/10.1177/20501579231212062). Well-being effects are small. |
| Turn off notifications | Weak as worded | Batching 3 times a day helped. Turning all of them off raised anxiety (https://scholars.duke.edu/publication/1402953). |
| Read for pleasure | Moderate (association) | Childhood cohort study, not adults (https://pubmed.ncbi.nlm.nih.gov/?term=Sun+early-initiated+childhood+reading+for+pleasure+Psychological+Medicine&format=pubmed). |
| "Brain rot" | Word only | Oxford Word of the Year 2024, defined as a "supposed" decline (https://corp.oup.com/news/brain-rot-named-oxford-word-of-the-year-2024/). |

### Prior art and design implications

- Friction plus an easy exit works better than a message (https://doi.org/10.1073/pnas.2213114120), so the 9 pm reminder is one short, dismissable notification.
- Per-app screen-time tracking is blocked on GNOME/Wayland (https://docs.activitywatch.net/en/latest/faq.html), so Unrot does not try.
- GNOME 48+ already has screen-time limits (https://release.gnome.org/48/). Ubuntu 24.04 ships Settings 46, so Unrot does not depend on it.

### Packaging

- Python modules go in `/usr/share/unrot`, with byte-compiling in postinst (https://www.debian.org/doc/packaging-manuals/python-policy/).
- Use the Dialog forms from 1.5 (AlertDialog, AboutDialog), not the Window forms deprecated in 1.6 (https://gitlab.gnome.org/GNOME/libadwaita/-/raw/main/NEWS).

## Confidence and caveats

- Many science rows are abstract-only, and the studies are small and short.
- The 26.04 and 26.10 checks ran in containers with a virtual display, not a real GNOME Shell session.

## Open questions

- Does the dock icon match the window on a real 26.10 desktop?
- Is the boredom-creativity effect real? No meta-analysis was found.

## Sources

See `ledger.json` (14 rows, each with its quoted passage, date and fetch path).
