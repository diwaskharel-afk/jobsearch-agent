import json
import re
from pathlib import Path

from model import StructuredProfile

# Single-user local app for now: one fixed file. Multi-user later just means
# keying this path by user id/email instead — no other structural change needed.
PROFILE_PATH = Path("data/profile.json")

# (profile attribute, id prefix)
ID_PREFIXES = (("projects", "proj"), ("experience", "exp"), ("certifications", "cert"), ("education", "edu"))


def assign_profile_ids(profile: StructuredProfile) -> StructuredProfile:
    """Give every entry a unique id, keeping existing ones. Idempotent; numbers are never reused."""
    for attr, prefix in ID_PREFIXES:
        pattern = re.compile(rf"^{prefix}_(\d+)$")
        entries = getattr(profile, attr)
        highest = profile.id_counters.get(prefix, 0)
        seen = set()
        for entry in entries:
            match = pattern.match(entry.id or "")
            if match and entry.id not in seen:
                seen.add(entry.id)
                highest = max(highest, int(match.group(1)))
            else:
                entry.id = None
        for entry in entries:
            if entry.id is None:
                highest += 1
                entry.id = f"{prefix}_{highest}"
        profile.id_counters[prefix] = highest
    return profile


def load_profile() -> StructuredProfile | None:
    if not PROFILE_PATH.exists():
        return None
    # assign_profile_ids is idempotent; it backfills ids for profiles saved before ids existed.
    return assign_profile_ids(StructuredProfile.model_validate_json(PROFILE_PATH.read_text()))


def save_profile(profile: StructuredProfile) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile.model_dump(), indent=2))

