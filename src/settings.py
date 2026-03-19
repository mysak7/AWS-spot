import json
from typing import Any

from config import NETBIRD_SETUP_KEY_DEFAULT, SETTINGS_FILE

_DEFAULTS: dict[str, Any] = {
    "netbird_setup_key": NETBIRD_SETUP_KEY_DEFAULT,
}


def load_settings() -> dict[str, Any]:
    """Load settings.json; return defaults for any missing keys."""
    if not SETTINGS_FILE.exists():
        return _DEFAULTS.copy()
    try:
        with open(SETTINGS_FILE) as f:
            data: dict[str, Any] = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _DEFAULTS.copy()
    return {**_DEFAULTS, **data}


def save_settings(settings: dict[str, Any]) -> None:
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
