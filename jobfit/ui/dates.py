"""Month + year pickers, date badges and date checks for the profile form."""
from datetime import date

import streamlit as st

from jobfit.formatting import format_month

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
PAST_YEARS = list(range(date.today().year, 1969, -1))
FUTURE_YEARS = list(range(date.today().year, date.today().year + 9))


# Dates are picked as month + year and stored as "YYYY-MM". A picker with only one of the
# two filled in returns a partial value (e.g. "2024-"), which date_problem reports on save.

def is_full_date(value: str | None) -> bool:
    return value is not None and len(value) == len("YYYY-MM")


def month_year_picker(label: str, value: str | None, key: str, years: list[int], cols=None) -> str | None:
    """A month and a year dropdown side by side, labelled once; "YYYY-MM", a partial value, or None.

    cols is the (month, year) column pair to draw them in; by default the left half of a row.
    """
    year, month = (int(value[:4]), int(value[5:])) if value else (None, None)
    if year is not None and year not in years:
        years = sorted({*years, year}, reverse=years[0] > years[-1])
    month_col, year_col = cols or st.columns(4)[:2]
    month = month_col.selectbox(label, range(1, 13), index=month - 1 if month else None,
                                format_func=lambda m: MONTH_NAMES[m - 1], placeholder="Month", key=f"{key}_month")
    # A short hidden label: a long one still wraps invisibly and pushes the row down.
    year = year_col.selectbox("Year", years, index=years.index(year) if year else None,
                              placeholder="Year", label_visibility="hidden", key=f"{key}_year")
    if month is None and year is None:
        return None
    return f"{year or ''}-{month:02d}" if month else f"{year}-"


def date_range_fields(entry: dict, key, present_label: str, expected_graduation: bool = False) -> dict:
    """A "present" toggle over one row of From and To pickers; end is None while present is on.

    While present is on, the To slot shows "Present", or for education (expected_graduation=True)
    the expected graduation pickers, which are then required.
    """
    present = st.toggle(present_label, value=bool(entry.get("start")) and not entry.get("end"), key=key("present"))
    cols = st.columns(4, vertical_alignment="bottom")
    values = {"start": month_year_picker("From", entry.get("start"), key("start"), PAST_YEARS, cols[:2]),
              "end": None, "present": present}
    if not present:
        values["end"] = month_year_picker("To", entry.get("end"), key("end"), PAST_YEARS, cols[2:])
    elif expected_graduation:
        values["expected_graduation"] = month_year_picker("Expected graduation", entry.get("expected_graduation"),
                                                          key("expected_graduation"), FUTURE_YEARS, cols[2:])
    else:
        cols[2].text_input("To", value="Present", disabled=True, key=key("end_present"))
    return values


def date_badge(card: dict, required: bool) -> str:
    """Card-header badge with the dates as the CV shows them; a warning while required ones are missing."""
    start, end, completed = card.get("start"), card.get("end"), card.get("date")
    if is_full_date(start) and card.get("present"):
        badge = f":green-badge[:material/schedule: {format_month(start)} – Present]"
        if is_full_date(card.get("expected_graduation")):
            badge += f" :violet-badge[:material/school: Graduating {format_month(card['expected_graduation'])}]"
        return badge
    if is_full_date(start) and is_full_date(end):
        return f":blue-badge[:material/calendar_month: {format_month(start)} – {format_month(end)}]"
    if is_full_date(completed):
        return f":blue-badge[:material/calendar_month: {format_month(completed)}]"
    return ":orange-badge[:material/warning: Dates needed]" if required else ""


def date_problem(value: str | None, what: str, required: bool) -> str | None:
    if value is None:
        return f"needs {what}" if required else None
    if not is_full_date(value):
        return f"needs both the month and the year of {what}"
    return None


def range_problems(label: str, entry: dict, present_label: str) -> list[str]:
    """Missing, partial or out-of-order dates of one education or experience card."""
    if entry["present"]:
        later_field, later_name = "expected_graduation", "expected graduation date"
    else:
        later_field, later_name = "end", f"end date (or turn on \"{present_label}\")"
    problems = [date_problem(entry["start"], "a start date", required=True)]
    if later_field in entry:  # experience has no expected graduation
        problems.append(date_problem(entry[later_field], f"an {later_name}", required=True))
    problems = [f"{label} {p}." for p in problems if p]
    later = entry.get(later_field)
    if not problems and later and later < entry["start"]:
        problems.append(f"{label}: the {later_field.replace('_', ' ')} date is before the start date.")
    return problems
