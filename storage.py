import json
from pathlib import Path

from model import StructuredProfile

# Single-user local app for now: one fixed file. Multi-user later just means
# keying this path by user id/email instead — no other structural change needed.
PROFILE_PATH = Path("data/profile.json")


def load_profile() -> StructuredProfile | None:
    if not PROFILE_PATH.exists():
        return None
    return StructuredProfile.model_validate_json(PROFILE_PATH.read_text())


def save_profile(profile: StructuredProfile) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile.model_dump(), indent=2))
