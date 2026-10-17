"""On-screen preview of a cover letter, optionally with its text as boxes."""
import re

import streamlit as st

from jobfit.models import CoverLetter
from jobfit.render_cv import _clean
from jobfit.render_letter import subject_line
from jobfit.ui.common import md


def render_letter_preview(letter: CoverLetter, edit: bool = False, version: int = 0) -> dict | None:
    """With edit, the greeting, body and sign-off become boxes and the edits come back as a dict
    for apply_letter_edits; call it inside a form. Keys carry the version, so the boxes refill."""
    with st.container(border=not edit):
        if _clean(letter.name):
            st.markdown(f"## {md(letter.name)}", anchors=False)
        contact = letter.contact
        parts = [md(value) for value in (contact.email, contact.phone, contact.address) if _clean(value)] \
            if contact else []
        if parts:
            st.caption(" &nbsp;|&nbsp; ".join(parts))
        if _clean(letter.date):
            st.caption(md(letter.date))
        if subject := subject_line(letter):
            st.markdown(f"**{md(subject)}**")

        if edit:
            greeting = st.text_input("Greeting", value=letter.greeting, key=f"letter_greeting_{version}")
            body = st.text_area("Letter", value="\n\n".join(letter.paragraphs), key=f"letter_body_{version}",
                                height=460, help="Leave an empty line between paragraphs.")
            closing = st.text_input("Sign-off", value=letter.closing, key=f"letter_closing_{version}")
            return {"greeting": greeting, "paragraphs": re.split(r"\n\s*\n", body), "closing": closing}

        st.markdown(md(letter.greeting))
        for paragraph in letter.paragraphs:
            st.markdown(md(paragraph))
        st.markdown(md(letter.closing) + (f"  \n{md(letter.name)}" if _clean(letter.name) else ""))
    words = sum(len(p.split()) for p in letter.paragraphs)
    st.caption(f"{words} words in the body")
    return None


def apply_letter_edits(letter: CoverLetter, edits: dict) -> CoverLetter:
    """Hand edits applied to a copy; an emptied box keeps what was there. Unlike the AI's
    body, a hand-written one keeps every paragraph."""
    paragraphs = [" ".join(p.split()) for p in edits["paragraphs"] if p.strip()]
    return letter.model_copy(update={
        "greeting": edits["greeting"].strip() or letter.greeting,
        "paragraphs": paragraphs or letter.paragraphs,
        "closing": edits["closing"].strip() or letter.closing,
    })
