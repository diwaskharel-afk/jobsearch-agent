"""Small helpers shared by the UI modules."""
import re
from typing import Callable

import streamlit as st

from jobfit.render_cv import _clean


def safe_filename(text: str | None, fallback: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in (text or "")).strip("_") or fallback


def md(text: str | None) -> str:
    """CV text as literal markdown: "$50k" isn't maths and "C#" or "snake_case" isn't formatting."""
    return re.sub(r"([\\`*_\[\]<>#~|$])", r"\\\1", _clean(text))


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def run_step(spinner: str, action: Callable[[], None], failure: str) -> bool:
    """Run an AI step under a spinner; on failure show the error in place. True if it worked."""
    try:
        with st.spinner(spinner):
            action()
    except Exception as exc:
        st.error(failure)
        st.code(str(exc))
        return False
    return True


def empty_state(title: str, text: str, button: str, icon: str, key: str) -> bool:
    """A card explaining a step that hasn't run yet, with the button that runs it; True when clicked."""
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(text)
        return st.button(button, type="primary", icon=icon, key=key)
