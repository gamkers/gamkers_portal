"""Read-only helpers for the public event pages and the landing page.

Registration counts, feedback summaries and calendar/map links. Feedback
quotes are only exposed when the respondent explicitly consented on the
feedback form; anonymous rating totals are always safe to show.
"""

from datetime import timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func

from app.extensions import db
from app.forms.models import Form, Submission

RATING_SCORES = {"Excellent": 5, "Good": 4, "Average": 3, "Needs improvement": 2}
CONSENT_QUESTION_ID = "public_consent"
CONSENT_YES = "Yes, you can feature my feedback publicly"
CONSENT_NO = "No, keep my feedback private"


def registration_count(form):
    return db.session.scalar(
        db.select(func.count(Submission.id)).where(Submission.form_id == form.id)
    ) or 0


def feedback_form_for(event):
    return db.session.scalar(db.select(Form).where(Form.parent_form_id == event.id))


def _display_name(full_name):
    parts = full_name.split()
    if not parts:
        return "Attendee"
    if len(parts) == 1:
        return parts[0][:40]
    return f"{parts[0][:40]} {parts[-1][0]}."


def feedback_summary(event, quote_limit=6):
    """Rating average/distribution for an event plus consented public quotes."""
    feedback_form = feedback_form_for(event)
    summary = {
        "count": 0,
        "average": None,
        "distribution": [],
        "quotes": [],
        "feedback_form": feedback_form,
    }
    if feedback_form is None:
        return summary
    submissions = db.session.scalars(
        db.select(Submission)
        .where(Submission.form_id == feedback_form.id)
        .order_by(Submission.submitted_at.desc())
    ).all()
    scores = []
    distribution = {label: 0 for label in RATING_SCORES}
    for submission in submissions:
        answers = submission.answers or {}
        rating = answers.get("rating")
        if rating in RATING_SCORES:
            scores.append(RATING_SCORES[rating])
            distribution[rating] += 1
        text = str(answers.get("feedback") or "").strip()
        if (
            text
            and answers.get(CONSENT_QUESTION_ID) == CONSENT_YES
            and len(summary["quotes"]) < quote_limit
        ):
            summary["quotes"].append(
                {
                    "name": _display_name(str(answers.get("certificate_name") or "")),
                    "org": str(answers.get("college_name") or "").strip()[:80],
                    "rating": RATING_SCORES.get(rating),
                    "text": text[:600],
                    "event": event,
                }
            )
    count = len(scores)
    summary["count"] = count
    if count:
        summary["average"] = round(sum(scores) / count, 1)
    summary["distribution"] = [
        {"label": label, "count": value, "pct": round(100 * value / count) if count else 0}
        for label, value in distribution.items()
    ]
    return summary


def _utc_range(event):
    if not event.event_start_at:
        return None
    try:
        zone = ZoneInfo(event.event_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    start = event.event_start_at.replace(tzinfo=zone).astimezone(timezone.utc)
    end = (
        event.event_end_at.replace(tzinfo=zone).astimezone(timezone.utc)
        if event.event_end_at
        else start + timedelta(hours=1)
    )
    return start, end


def timezone_label(event):
    if not event.event_start_at:
        return event.event_timezone
    try:
        return event.event_start_at.replace(tzinfo=ZoneInfo(event.event_timezone)).tzname()
    except (ZoneInfoNotFoundError, ValueError):
        return event.event_timezone


def google_calendar_link(event, page_url):
    times = _utc_range(event)
    if times is None:
        return None
    fmt = "%Y%m%dT%H%M%SZ"
    details = (event.description or "")[:800] + f"\n\nDetails & registration: {page_url}"
    params = {
        "action": "TEMPLATE",
        "text": event.title,
        "dates": f"{times[0].strftime(fmt)}/{times[1].strftime(fmt)}",
        "details": details,
        "location": event.event_location or "",
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(params)


def maps_link(event):
    location = (event.event_location or "").strip()
    if not location or location.lower().startswith(("online", "http", "virtual", "discord", "zoom", "google meet")):
        return None
    return "https://www.google.com/maps/search/?" + urlencode({"api": 1, "query": location})
