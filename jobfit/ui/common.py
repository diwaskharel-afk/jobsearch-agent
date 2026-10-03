"""Small text helpers shared by the UI modules."""
import re

from jobfit.render_cv import _clean


def safe_filename(text: str | None, fallback: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "")).strip("_") or fallback


def md(text: str | None) -> str:
    """CV text as literal markdown: "$50k" isn't maths and "C#" or "snake_case" isn't formatting."""
    return re.sub(r"([\\`*_\[\]<>#~|$])", r"\\\1", _clean(text))


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
