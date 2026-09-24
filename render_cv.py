from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    ListFlowable,
    ListItem,
)

from model import FinalCV

_styles = getSampleStyleSheet()
_NAME_STYLE = ParagraphStyle("CVName", parent=_styles["Title"], alignment=TA_CENTER, spaceAfter=2)
_CONTACT_STYLE = ParagraphStyle("CVContact", parent=_styles["Normal"], alignment=TA_CENTER, spaceAfter=12)
_SECTION_STYLE = ParagraphStyle(
    "CVSection", parent=_styles["Heading2"], spaceBefore=10, spaceAfter=4,
    borderPadding=0, borderWidth=0,
)
_ENTRY_HEADER_STYLE = ParagraphStyle("CVEntryHeader", parent=_styles["Normal"], fontName="Helvetica-Bold", spaceBefore=6)
_ENTRY_SUBHEADER_STYLE = ParagraphStyle("CVEntrySubheader", parent=_styles["Normal"], fontSize=9, textColor=colors.HexColor("#444444"))
_BODY_STYLE = _styles["Normal"]
_BULLET_STYLE = ParagraphStyle("CVBullet", parent=_styles["Normal"], spaceAfter=1)


def _e(text: str) -> str:
    return escape(text or "")


def _bullet_list(bullets: list[str]) -> ListFlowable:
    return ListFlowable(
        [ListItem(Paragraph(_e(b), _BULLET_STYLE)) for b in bullets],
        bulletType="bullet",
        leftIndent=14,
    )


def render_cv_pdf(cv: FinalCV) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        leftMargin=0.65 * inch,
        rightMargin=0.65 * inch,
    )
    story = []

    if cv.name:
        story.append(Paragraph(_e(cv.name), _NAME_STYLE))

    contact_parts = []
    if cv.contact:
        if cv.contact.email:
            contact_parts.append(cv.contact.email)
        if cv.contact.phone:
            contact_parts.append(cv.contact.phone)
        if cv.contact.address:
            contact_parts.append(cv.contact.address)
    if contact_parts:
        story.append(Paragraph(_e(" | ".join(contact_parts)), _CONTACT_STYLE))

    if cv.objective:
        story.append(Paragraph("Objective", _SECTION_STYLE))
        story.append(Paragraph(_e(cv.objective), _BODY_STYLE))

    if cv.skills:
        story.append(Paragraph("Skills", _SECTION_STYLE))
        story.append(Paragraph(_e(", ".join(cv.skills)), _BODY_STYLE))

    if cv.experience:
        story.append(Paragraph("Experience", _SECTION_STYLE))
        for exp in cv.experience:
            header = f"{exp.title} — {exp.organization}"
            if exp.duration:
                header += f" ({exp.duration})"
            story.append(Paragraph(_e(header), _ENTRY_HEADER_STYLE))
            if exp.bullets:
                story.append(_bullet_list(exp.bullets))

    if cv.projects:
        story.append(Paragraph("Projects", _SECTION_STYLE))
        for project in cv.projects:
            story.append(Paragraph(_e(project.name), _ENTRY_HEADER_STYLE))
            subheader_parts = []
            if project.tech_stack:
                subheader_parts.append(", ".join(project.tech_stack))
            if project.repo_url:
                subheader_parts.append(project.repo_url)
            if subheader_parts:
                story.append(Paragraph(_e(" | ".join(subheader_parts)), _ENTRY_SUBHEADER_STYLE))
            if project.bullets:
                story.append(_bullet_list(project.bullets))

    if cv.education:
        story.append(Paragraph("Education", _SECTION_STYLE))
        for edu in cv.education:
            header = edu.course_name
            if edu.institution:
                header += f" — {edu.institution}"
            if edu.duration:
                header += f" ({edu.duration})"
            story.append(Paragraph(_e(header), _ENTRY_HEADER_STYLE))
            if edu.description:
                story.append(Paragraph(_e(edu.description), _BODY_STYLE))

    doc.build(story)
    return buffer.getvalue()
