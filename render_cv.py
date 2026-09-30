import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from model import FinalCV

# --- Look and feel ---------------------------------------------------------------

ACCENT = colors.HexColor("#1D4E89")   # headings, name, links
TEXT = colors.HexColor("#1F2328")
MUTED = colors.HexColor("#5B6470")    # dates, tech stacks, contact line
RULE = colors.HexColor("#C9D3E0")

MARGIN = 17 * mm
PAGE_WIDTH, PAGE_HEIGHT = A4
FRAME_PADDING = 6  # SimpleDocTemplate's frame pads each side by 6pt; tables must fit inside it
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN - 2 * FRAME_PADDING
DATE_COL_WIDTH = 42 * mm

MAX_TECH_SHOWN = 8  # long LLM tech lists turn into a wall of text; the first few carry the signal

_NAME = ParagraphStyle("CVName", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=ACCENT)
_CONTACT = ParagraphStyle("CVContact", fontName="Helvetica", fontSize=9, leading=13, textColor=MUTED, spaceBefore=3)
_SECTION = ParagraphStyle("CVSection", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=ACCENT)
_BODY = ParagraphStyle("CVBody", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=TEXT)
_ENTRY_TITLE = ParagraphStyle("CVEntryTitle", parent=_BODY, fontName="Helvetica-Bold", fontSize=10.5, leading=13.5)
_ENTRY_SUB = ParagraphStyle("CVEntrySub", parent=_BODY, fontName="Helvetica-Oblique", textColor=MUTED, leading=12.5)
_DATE = ParagraphStyle("CVDate", parent=_BODY, fontSize=9, textColor=MUTED, alignment=TA_RIGHT)
_BULLET = ParagraphStyle("CVBullet", parent=_BODY, spaceAfter=1.5)

_MONTHS = {"January": "Jan", "February": "Feb", "March": "Mar", "April": "Apr", "June": "Jun", "July": "Jul",
           "August": "Aug", "September": "Sep", "Sept": "Sep", "October": "Oct", "November": "Nov",
           "December": "Dec"}
_SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with"}


# --- Text helpers -------------------------------------------------------------------

def _clean(text: str | None) -> str:
    """Trim and collapse the stray whitespace hand-typed profile fields tend to carry."""
    text = re.sub(r"\s+", " ", text or "").strip()
    return re.sub(r" +([,.;:])", r"\1", text)


def _date(text: str | None) -> str:
    """'· November 2025 – February 2026' (pasted from LinkedIn) -> 'Nov 2025 – Feb 2026', so it fits one line."""
    text = _clean(text).lstrip("·•|-–— ")
    return re.sub(r"\b(" + "|".join(_MONTHS) + r")\b", lambda m: _MONTHS[m.group(1)], text)


def _e(text: str | None) -> str:
    return escape(_clean(text))


def _display_url(url: str) -> str:
    """https://www.github.com/user?tab=repositories -> github.com/user"""
    url = re.sub(r"^https?://(www\.)?", "", _clean(url))
    return url.split("?")[0].split("#")[0].rstrip("/")


def _link(url: str, label: str | None = None) -> str:
    href = _clean(url)
    if not re.match(r"^(https?://|mailto:)", href):
        href = "https://" + href
    return f'<link href="{escape(href)}" color="#1D4E89">{escape(label or _display_url(url))}</link>'


def _pretty_project_name(name: str) -> str:
    """Repo slugs like IMAGE-AND-SHAPE-DETECTION or my_cool_repo read better as titles."""
    name = _clean(name)
    if " " in name or not re.search(r"[-_]", name):
        return name
    words = re.split(r"[-_]+", name)
    if name.isupper() or name.islower():
        words = [w.lower() if i and w.lower() in _SMALL_WORDS else w.capitalize() for i, w in enumerate(words)]
    return " ".join(words)


# --- Building blocks ----------------------------------------------------------------

def _section(title: str) -> list:
    parts = [
        Spacer(1, 9),
        Paragraph(escape(title.upper()), _SECTION),
        HRFlowable(width="100%", thickness=0.6, color=RULE, spaceBefore=2, spaceAfter=5),
    ]
    for part in parts:
        part.keepWithNext = True  # never leave a heading stranded at the bottom of a page
    return parts


def _two_col(left, right: str | None) -> Table:
    """Left-aligned content with a right-aligned date column, e.g. job title | May 2025 – July 2025."""
    right_cell = Paragraph(escape(_date(right)), _DATE) if _date(right) else ""
    table = Table([[left, right_cell]], colWidths=[CONTENT_WIDTH - DATE_COL_WIDTH, DATE_COL_WIDTH])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _bullet_list(bullets: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_e(b), _BULLET), leftIndent=11, value="•") for b in bullets if _clean(b)],
        bulletType="bullet",
        bulletFontSize=7,
        bulletColor=ACCENT,
        bulletOffsetY=-1,
        leftIndent=11,
        spaceBefore=2,
    )


def _entry(title_html: str, date: str | None, subtitle_html: str | None, bullets: list[str],
           description: str | None = None) -> list:
    """The flowables of one experience/project/education block, kept whole by _entries_section."""
    parts = [_two_col(Paragraph(title_html, _ENTRY_TITLE), date)]
    if subtitle_html:
        parts.append(Paragraph(subtitle_html, _ENTRY_SUB))
    if description and _clean(description):
        parts.append(Paragraph(_e(description), _BODY))
    if bullets:
        parts.append(_bullet_list(bullets))
    return parts


def _entries_section(title: str, entries: list[list]) -> list:
    """A heading plus entries, each entry on a single page: one that doesn't fit moves to the next page.

    The heading goes inside the first entry's KeepTogether, because reportlab won't chain a
    keepWithNext heading onto a KeepTogether. An entry taller than a whole page still splits.
    """
    story = []
    for i, entry in enumerate(entries):
        story.append(KeepTogether((_section(title) if i == 0 else []) + entry))
        story.append(Spacer(1, 7))
    return story


def _dot_join(items: list[str]) -> str:
    # Each item and the dot after it stay together, so a wrapped line never starts with a separator.
    return "&nbsp;&nbsp;·&nbsp; ".join(_e(i).replace(" ", "&nbsp;") for i in items if _clean(i))


# --- Sections ----------------------------------------------------------------------

def _header(cv: FinalCV) -> list:
    story = []
    if cv.name:
        story.append(Paragraph(_e(cv.name), _NAME))

    parts = []
    contact = cv.contact
    if contact and _clean(contact.email):
        parts.append(_link("mailto:" + _clean(contact.email), _clean(contact.email)))
    if contact and _clean(contact.phone):
        parts.append(_e(contact.phone))
    if contact and _clean(contact.address):
        parts.append(_e(contact.address))
    if parts:
        story.append(Paragraph("&nbsp;&nbsp;|&nbsp; ".join(parts), _CONTACT))

    story.append(HRFlowable(width="100%", thickness=1.4, color=ACCENT, spaceBefore=6, spaceAfter=2))
    return story


def _experience(cv: FinalCV) -> list:
    return _entries_section("Experience", [
        _entry(_e(exp.title), exp.duration, _e(exp.organization), exp.bullets) for exp in cv.experience
    ])


def _projects(cv: FinalCV) -> list:
    entries = []
    for project in cv.projects:
        title = _e(_pretty_project_name(project.name))
        tech = [t for t in project.tech_stack if _clean(t)]
        shown = _dot_join(tech[:MAX_TECH_SHOWN])
        if project.repo_url:
            label = "GitHub" if "github.com" in project.repo_url else "Link"
            title += f'&nbsp;&nbsp;<font size="8.5">{_link(project.repo_url, label)}</font>'
        entries.append(_entry(title, None, shown or None, project.bullets))
    return _entries_section("Projects", entries)


def _education(cv: FinalCV) -> list:
    return _entries_section("Education", [
        _entry(_e(edu.degree), edu.duration, _e(edu.institution) or None, [], edu.description)
        for edu in cv.education
    ])


def _courses(cv: FinalCV) -> list:
    story = _section("Relevant Courses")
    items = []
    for course in cv.courses:
        line = f"<b>{_e(course.name)}</b>"
        if _clean(course.provider):
            line += f' <font color="#5B6470">— {_e(course.provider)}</font>'
        if _clean(course.date):
            line += f' <font color="#5B6470">({_e(course.date)})</font>'
        items.append(ListItem(Paragraph(line, _BULLET), leftIndent=11, value="•"))
    story.append(ListFlowable(items, bulletType="bullet", bulletFontSize=7, bulletColor=ACCENT,
                              bulletOffsetY=-1, leftIndent=11))
    return story


def _footer(name: str):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        label = f"{name}  ·  Page {doc.page}" if name else f"Page {doc.page}"
        canvas.drawRightString(PAGE_WIDTH - MARGIN, 10 * mm, label)
        canvas.restoreState()
    return draw


def render_cv_pdf(cv: FinalCV) -> bytes:
    buffer = BytesIO()
    name = _clean(cv.name)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        title=f"{name} – CV" if name else "CV",
        author=name,
    )

    story = _header(cv)

    if _clean(cv.objective):
        story += _section("Profile")
        story.append(Paragraph(_e(cv.objective), _BODY))

    if cv.skills:
        story += _section("Skills")
        story.append(Paragraph(_dot_join(cv.skills), _BODY))

    if cv.experience:
        story += _experience(cv)
    if cv.projects:
        story += _projects(cv)
    if cv.education:
        story += _education(cv)
    if cv.courses:
        story += _courses(cv)

    # First page stays clean; later pages get "Name · Page N" so loose pages can be matched up.
    doc.build(story, onLaterPages=_footer(name))
    return buffer.getvalue()
