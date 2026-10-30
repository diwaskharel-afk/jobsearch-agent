"""Saved jobs: one JSON file per entry in data/history/, written only when the user clicks Save.
An entry is the run snapshot (job_run.run_snapshot) plus the name the user gave it."""
import json
import os
from pathlib import Path

# In data/, like the profile, so it stays out of git.
HISTORY_DIR = Path("data/history")


def _path(entry_id: str) -> Path:
    return HISTORY_DIR / f"{entry_id}.json"


def list_entries() -> list[tuple[str, dict | None]]:
    """(id, run) for every entry, most recently saved first; run is None for a file that can't be read."""
    entries = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            run = None
        entries.append((path.stem, run if isinstance(run, dict) else None))
    return sorted(entries, key=lambda entry: ((entry[1] or {}).get("saved_at") or "", entry[0]), reverse=True)


def save(entry_id: str, run: dict) -> None:
    """Write the entry through a temporary file, so a crash never leaves half a file."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(entry_id)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def delete(entry_id: str) -> None:
    _path(entry_id).unlink(missing_ok=True)
