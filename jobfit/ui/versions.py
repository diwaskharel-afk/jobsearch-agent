"""Versions of a generated document (the CV, the cover letter): AI revisions, hand edits, Undo and Redo."""
import textwrap
from typing import Any, Callable

import streamlit as st

from jobfit.ui.common import md

# Each document keeps all its versions in session state, with a pointer to the current one.
# A change that actually alters the document becomes a new version; Undo and Redo move the
# pointer, and a change made after an Undo drops the versions after it, as in any editor.
# "rev" goes up on every move, so the edit boxes and the version picker refill.
# The log keeps every request, applied or not, for the run download.

Render = Callable[..., Any]   # render(data, edit=..., version=...) -> edits when edit, else None


def _state(doc: str) -> dict | None:
    return st.session_state.get(f"doc_{doc}")


def has(doc: str) -> bool:
    return _state(doc) is not None


def current(doc: str) -> dict | None:
    state = _state(doc)
    return state["versions"][state["index"]]["data"] if state else None


def log(doc: str) -> list[dict]:
    state = _state(doc)
    return state["log"] if state else []


def position(doc: str) -> tuple[int, int]:
    """(index of the current version, number of versions)."""
    state = _state(doc)
    return state["index"], len(state["versions"])


def last_change(doc: str) -> dict | None:
    """What the latest revision or hand edit did; None after Undo, Redo or a fresh document."""
    state = _state(doc)
    return state["last"] if state else None


def is_editing(doc: str) -> bool:
    state = _state(doc)
    return bool(state and state["editing"])


def start(doc: str, data: dict, label: str = "Generated") -> None:
    """A new document with one version; any earlier versions are dropped."""
    st.session_state[f"doc_{doc}"] = {
        "versions": [{"data": data, "label": label}], "index": 0, "rev": 0, "log": [], "last": None, "editing": False,
    }


def reset(doc: str) -> None:
    st.session_state.pop(f"doc_{doc}", None)


def add_version(doc: str, new: dict, request: str, changes: list[str], not_done: list[str]) -> None:
    """Make `new` the current version. An unchanged document makes no new version."""
    state = _state(doc)
    applied = new != current(doc)
    if applied:
        del state["versions"][state["index"] + 1:]
        state["versions"].append({"data": new, "label": request})
        state["index"] += 1
        state["rev"] += 1
    last = {"request": request, "applied": applied, "changes": changes if applied else [], "not_done": not_done}
    state["last"] = last
    state["log"].append(last)


def go_to(doc: str, index: int) -> None:
    state = _state(doc)
    if 0 <= index < len(state["versions"]) and index != state["index"]:
        state["log"].append({"go_to": index + 1, "from": state["index"] + 1})
        state["index"] = index
        state["rev"] += 1
        state["last"] = None


def set_editing(doc: str, editing: bool) -> None:
    _state(doc)["editing"] = editing


# --- UI pieces ----------------------------------------------------------------------

def version_label(state: dict, index: int) -> str:
    label = textwrap.shorten(state["versions"][index]["label"], 40, placeholder="…")
    return f"Version {index + 1} of {len(state['versions'])} · {label}"


def toolbar(doc: str, downloads: list[dict], regenerate_help: str) -> bool:
    """Version picker, Undo, Redo, Edit, Regenerate and the download buttons in one row.
    True when Regenerate was clicked; the caller runs it, so its spinner and errors show in place."""
    state = _state(doc)
    editing, index, total = state["editing"], state["index"], len(state["versions"])
    picker_key = f"{doc}_version_{state['rev']}"  # a new key per move, so the picker shows the current version
    with st.container(horizontal=True, vertical_alignment="center"):
        st.selectbox("Version", range(total), index=index, key=picker_key, width=330,
                     format_func=lambda i: version_label(state, i), label_visibility="collapsed",
                     disabled=editing or total == 1,
                     on_change=lambda: go_to(doc, st.session_state[picker_key]))
        st.button("Undo", icon=":material/undo:", key=f"{doc}_undo", disabled=editing or index == 0,
                  on_click=go_to, args=(doc, index - 1))
        st.button("Redo", icon=":material/redo:", key=f"{doc}_redo", disabled=editing or index == total - 1,
                  on_click=go_to, args=(doc, index + 1))
        st.button("Edit", icon=":material/edit:", key=f"{doc}_edit", disabled=editing,
                  on_click=set_editing, args=(doc, True), help="Change the text by hand. No AI involved.")
        regenerate = st.button("Regenerate", icon=":material/refresh:", key=f"{doc}_regenerate", disabled=editing,
                               help=regenerate_help)
        st.space("stretch")
        for n, download in enumerate(downloads):
            st.download_button(key=f"{doc}_download_{n}", disabled=editing, on_click="ignore",
                               type="primary" if n == 0 else "secondary", **download)
    return regenerate


def editable_preview(doc: str, render: Render, apply_edits: Callable[[dict, Any], dict]) -> bool:
    """The current version, or while editing its text as boxes in a form. Saving applies the edits
    as a new version (no AI call). True once saved, so the caller can redraw."""
    state = _state(doc)
    data = current(doc)
    if not state["editing"]:
        render(data, edit=False, version=state["rev"])
        return False
    with st.form(f"{doc}_edit_{state['rev']}", border=False):
        edits = render(data, edit=True, version=state["rev"])
        with st.container(horizontal=True):
            saved = st.form_submit_button("Save changes", type="primary", icon=":material/check:")
            st.form_submit_button("Cancel", on_click=set_editing, args=(doc, False))
    if not saved:
        return False
    set_editing(doc, False)
    add_version(doc, apply_edits(data, edits), "Manual edit", ["Edited by hand"], [])
    return True


def revise_panel(doc: str, revise: Callable[[str], None], placeholder: str, help: str, spinner: str) -> None:
    """A note for the AI to apply to the current version, and what the last change did."""
    state = _state(doc)
    st.markdown("**Revise with AI**")
    with st.form(f"{doc}_revise_form", clear_on_submit=True):
        request = st.text_area("What should change?", placeholder=placeholder, help=help, height=130)
        submitted = st.form_submit_button("Apply", type="primary", icon=":material/auto_awesome:",
                                          disabled=state["editing"])
    if state["editing"]:
        st.caption("Save or cancel your hand edits first.")
    if submitted:
        if not request.strip():
            st.warning("Write what should change first.")
        else:
            try:
                with st.spinner(spinner):
                    revise(request.strip())
            except Exception as exc:
                st.error("Something went wrong with this revision:")
                st.code(str(exc))
            else:
                st.rerun()  # the preview is drawn before this panel, so draw it again with the new version
    if state["last"]:
        render_revision_result(state["last"])


def render_revision_result(last: dict) -> None:
    if not last["applied"]:
        st.info("Nothing changed.")
    elif last["changes"]:
        st.success("**Changed:**\n" + "\n".join(f"- {md(c)}" for c in last["changes"]))
    else:
        st.success("Updated.")
    if last["not_done"]:
        st.warning("**Not done:**\n" + "\n".join(f"- {md(n)}" for n in last["not_done"]))
