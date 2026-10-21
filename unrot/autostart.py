"""Per-user "start at login" entry (XDG autostart spec). No GTK imports."""

import os
from pathlib import Path

from . import APP_ID

ENTRY = f"""[Desktop Entry]
Type=Application
Name=Unrot
Comment=Reminders and timers for your daily practice
TryExec=unrot
Exec=unrot --background
Icon={APP_ID}
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
"""


def autostart_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if os.path.isabs(xdg) else Path.home() / ".config"
    return base / "autostart" / f"{APP_ID}.desktop"


def set_autostart(enabled: bool, path=None):
    path = Path(path) if path else autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ENTRY, encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
