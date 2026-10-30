"""The cover letter as a PDF, with the CV's header so the two look like a set, and as plain text."""
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from jobfit.models import CoverLetter
from jobfit.render_cv import MARGIN, MUTED, TEXT, _clean, _e, _header

_BODY = ParagraphStyle("LetterBody", fontName="Helvetica", fontSize=10.5, leading=15.5, textColor=TEXT, spaceAfter=9)
_DATE = ParagraphStyle("LetterDate", parent=_BODY, fontSize=9.5, textColor=MUTED, spaceAfter=4)
_SUBJECT = ParagraphStyle("LetterSubject", parent=_BODY, fontName="Helvetica-Bold", spaceAfter=12)


def subject_line(letter: CoverLetter) -> str:
    """"Application for Data Analyst at Acme"; "" without a job title."""
    if not _clean(letter.job_title):
        return ""
    company = _clean(letter.company)
    return f"Application for {_clean(letter.job_title)}" + (f" at {company}" if company else "")


def render_letter_pdf(letter: CoverLetter) -> bytes:
    buffer = BytesIO()
    name = _clean(letter.name)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        title=f"{name} – Cover letter" if name else "Cover letter",
        author=name,
    )

    story = _header(letter) + [Spacer(1, 14)]
    if _clean(letter.date):
        story.append(Paragraph(_e(letter.date), _DATE))
    if subject := subject_line(letter):
        story.append(Paragraph(_e(subject), _SUBJECT))
    story.append(Paragraph(_e(letter.greeting), _BODY))
    story += [Paragraph(_e(p), _BODY) for p in letter.paragraphs if _clean(p)]
    story.append(Spacer(1, 4))
    story.append(Paragraph(_e(letter.closing) + (f"<br/>{_e(name)}" if name else ""), _BODY))
    doc.build(story)
    return buffer.getvalue()


def letter_text(letter: CoverLetter) -> str:
    """Greeting, body and sign-off, for pasting into an application form."""
    parts = [_clean(letter.greeting), *(_clean(p) for p in letter.paragraphs if _clean(p)),
             "\n".join(part for part in (_clean(letter.closing), _clean(letter.name)) if part)]
    return "\n\n".join(part for part in parts if part) + "\n"
