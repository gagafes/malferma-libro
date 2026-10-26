"""Shared user data location, with safe access to existing libraries."""

import os
from pathlib import Path


def user_data_directory() -> Path:
    configured = Path(os.environ.get("XDG_DATA_HOME", ""))
    base = configured if configured.is_absolute() else Path.home() / ".local/share"
    current = base / "malferma-libro"
    # Existing records contain absolute managed-book paths. Keep their folder
    # intact instead of renaming it and silently breaking those references.
    previous_spelling = base / "malferna-libro"
    if not current.exists() and previous_spelling.is_dir():
        return previous_spelling
    return current
