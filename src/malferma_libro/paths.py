"""Shared user data location, with safe access to existing libraries."""

import os
from pathlib import Path


def user_data_directory() -> Path:
    configured = Path(os.environ.get("XDG_DATA_HOME", ""))
    base = configured if configured.is_absolute() else Path.home() / ".local/share"
    current = base / "malferma-libro"
    # Existing records contain absolute managed-book paths. Keep their folder
    # intact instead of renaming it and silently breaking those references.
    if not current.exists():
        for name in ("malferna-libro", "otkrytaya-kniga"):
            legacy = base / name
            if legacy.is_dir():
                return legacy
    return current
