"""Aggregates for the admin analytics page.

Everything is scoped to one organization and one date range. Event forms
(parent_form_id is NULL) count as registrations; their child feedback forms
are counted separately so ratings never inflate registration numbers.
"""

import re
from collections import Counter
from datetime import timedelta

from app.certificates.models import CertificateBatch, CertificateRecord
from app.extensions import db
from app.forms.models import Form, Submission
from app.forms.public_events import RATING_SCORES
from app.utils import utcnow

RANGES = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days", 365: "Last 12 months"}
DEFAULT_RANGE = 30
EMAIL_STATUSES = [
    ("sent", "Delivered", "good"),
    ("failed", "Failed", "critical"),
    ("not_configured", "Not sent (mail off)", "warning"),
]
TOP_LIMIT = 8
INSTITUTION_HINT = re.compile(r"college|institut|universit|organi[sz]ation|company|school", re.I)


def parse_range(value):
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RANGE
    return days if days in RANGES else DEFAULT_RANGE


def _email(submission):
    return (submission.respondent_email or "").strip().lower()


def _delta(current, previous):
    if not previous:
        return None
    return round(100 * (current - previous) / previous)


def _buckets(start, end, days):
    """Contiguous time buckets: daily up to 30 days, weekly for 90, monthly for a year."""
    if days <= 30:
        step, label = "day", "%b %d"
    elif days <= 90:
        step, label = "week", "%b %d"
    else:
        step, label = "month", "%b %Y"
    buckets = []
    if step == "month":
        cursor = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor < end:
            following = (cursor + timedelta(days=32)).replace(day=1)
            buckets.append({"start": cursor, "end": following, "label": cursor.strftime("%b %Y")})
            cursor = following
        return buckets
    width = timedelta(days=1 if step == "day" else 7)
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor < end:
        buckets.append({"start": cursor, "end": cursor + width, "label": cursor.strftime(label)})
        cursor += width
    return buckets


def _institution_fields(form):
    return [
        question.get("id")
        for question in form.questions or []
        if question.get("type") in ("short_text", "choice")
        and INSTITUTION_HINT.search(f"{question.get('id', '')} {question.get('title', '')}")
    ]


def _bar_rows(counter, limit=TOP_LIMIT):
    rows = [{"label": label, "count": count} for label, count in counter.most_common(limit)]
    peak = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["pct"] = round(100 * row["count"] / peak) if peak else 0
    return rows


def _nice_max(value):
    """Round the axis top up to a clean number so ticks read 0 / 5 / 10 …"""
    raw_step = max(value / 4, 1)
    magnitude = 10 ** (len(str(int(raw_step))) - 1)
    for multiple in (1, 2, 5, 10):
        if multiple * magnitude >= raw_step:
            return 4 * multiple * magnitude
    return 4 * 10 * magnitude


def column_chart(buckets, width=960, height=260):
    """Geometry for an SVG column chart: 4px rounded caps, square at the baseline."""
    left, right, top, bottom = 40, 8, 14, 30
    plot_w, plot_h = width - left - right, height - top - bottom
    peak = max((bucket["count"] for bucket in buckets), default=0)
    axis_max = _nice_max(peak)
    slot = plot_w / max(len(buckets), 1)
    bar_w = max(min(24, slot * 0.62), 2)
    radius = min(4, bar_w / 2)
    label_every = max(1, -(-len(buckets) // 8))
    baseline = top + plot_h
    columns = []
    for index, bucket in enumerate(buckets):
        x = left + slot * index + (slot - bar_w) / 2
        bar_h = plot_h * bucket["count"] / axis_max if axis_max else 0
        y = baseline - bar_h
        r = min(radius, bar_h)
        path = None
        if bar_h > 0:
            path = (
                f"M{x:.1f},{baseline:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
                f"H{x + bar_w - r:.1f}Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f}"
                f"V{baseline:.1f}Z"
            )
        columns.append(
            {
                "path": path,
                "hit_x": round(left + slot * index, 1),
                "hit_w": round(slot, 1),
                "label_x": round(x + bar_w / 2, 1),
                "value_y": round(y - 6, 1),
                "show_label": index % label_every == 0,
                "is_peak": peak > 0 and bucket["count"] == peak,
                "label": bucket["label"],
                "count": bucket["count"],
            }
        )
    # Only the first peak gets a direct value label.
    seen_peak = False
    for column in columns:
        if column["is_peak"] and not seen_peak:
            seen_peak = True
        else:
            column["is_peak"] = False
    ticks = [
        {"value": axis_max * step // 4, "y": round(baseline - plot_h * step / 4, 1)}
        for step in range(5)
    ]
    return {
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "baseline": baseline,
        "label_y": height - 10,
        "ticks": ticks,
        "columns": columns,
    }


def build_analytics(organization_id, days=DEFAULT_RANGE, now=None):
    now = now or utcnow()
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)

    forms = db.session.scalars(
        db.select(Form).where(Form.organization_id == organization_id)
    ).all()
    events = [form for form in forms if form.parent_form_id is None]
    feedback_forms = {form.parent_form_id: form for form in forms if form.parent_form_id}
    event_ids = [form.id for form in events]
    feedback_ids = [form.id for form in feedback_forms.values()]

    registrations = []
    if event_ids:
        registrations = db.session.scalars(
            db.select(Submission).where(Submission.form_id.in_(event_ids))
        ).all()
    feedback = []
    if feedback_ids:
        feedback = db.session.scalars(
            db.select(Submission).where(Submission.form_id.in_(feedback_ids))
        ).all()

    in_range = [item for item in registrations if item.submitted_at >= start]
    previous = [item for item in registrations if previous_start <= item.submitted_at < start]
    feedback_in_range = [item for item in feedback if item.submitted_at >= start]

    # Attendees: one person per email address. Returning = registered for 2+ events ever.
    events_per_email = {}
    for item in registrations:
        email = _email(item)
        if email:
            events_per_email.setdefault(email, set()).add(item.form_id)
    attendees = {_email(item) for item in in_range if _email(item)}
    previous_attendees = {_email(item) for item in previous if _email(item)}
    returning = sum(1 for email in attendees if len(events_per_email.get(email, ())) > 1)

    scores = [
        RATING_SCORES[item.answers.get("rating")]
        for item in feedback_in_range
        if (item.answers or {}).get("rating") in RATING_SCORES
    ]
    rating_counts = Counter(
        item.answers.get("rating")
        for item in feedback_in_range
        if (item.answers or {}).get("rating") in RATING_SCORES
    )
    rating_peak = max(rating_counts.values(), default=0)
    ratings = [
        {
            "label": label,
            "count": rating_counts.get(label, 0),
            "pct": round(100 * rating_counts.get(label, 0) / rating_peak) if rating_peak else 0,
        }
        for label in RATING_SCORES
    ]

    certificates = db.session.execute(
        db.select(CertificateRecord.status, CertificateRecord.created_at, CertificateBatch.source_form_id)
        .join(CertificateBatch, CertificateRecord.batch_id == CertificateBatch.id)
        .where(CertificateBatch.organization_id == organization_id)
    ).all()
    issued = [row for row in certificates if row.status == "generated"]
    issued_in_range = sum(1 for row in issued if row.created_at >= start)
    issued_by_event = Counter(row.source_form_id for row in issued if row.source_form_id)

    # Email delivery for registration confirmations in range (feedback sends none).
    email_counts = Counter(item.email_status for item in in_range)
    attempted = email_counts.get("sent", 0) + email_counts.get("failed", 0)
    email_total = sum(email_counts.get(key, 0) for key, _, _ in EMAIL_STATUSES)
    email_rows = [
        {
            "key": key,
            "label": label,
            "status": status,
            "count": email_counts.get(key, 0),
            "pct": round(100 * email_counts.get(key, 0) / email_total) if email_total else 0,
        }
        for key, label, status in EMAIL_STATUSES
    ]

    buckets = _buckets(start, now, days)
    for bucket in buckets:
        bucket["count"] = sum(
            1 for item in in_range if bucket["start"] <= item.submitted_at < bucket["end"]
        )
    peak = max((bucket["count"] for bucket in buckets), default=0)

    titles = {form.id: form.title for form in events}
    by_event = _bar_rows(Counter(titles[item.form_id] for item in in_range))
    # Institutions come from any institution-like question, registration or feedback,
    # counted once per person so attendees who did both aren't doubled.
    institution_fields = {form.id: _institution_fields(form) for form in forms}
    institution_by_person = {}
    for item in in_range + feedback_in_range:
        for field in institution_fields.get(item.form_id, ()):
            value = " ".join(str((item.answers or {}).get(field) or "").split())[:80]
            if value:
                institution_by_person.setdefault(_email(item) or f"#{item.id}", value)
                break
    institutions = _bar_rows(Counter(institution_by_person.values()))

    registrations_by_form = Counter(item.form_id for item in registrations)
    range_by_form = Counter(item.form_id for item in in_range)
    feedback_by_form = Counter(item.form_id for item in feedback)
    feedback_scores = {}
    for item in feedback:
        rating = (item.answers or {}).get("rating")
        if rating in RATING_SCORES:
            feedback_scores.setdefault(item.form_id, []).append(RATING_SCORES[rating])

    event_rows = []
    for form in sorted(events, key=lambda form: form.event_start_at or form.created_at, reverse=True):
        child = feedback_forms.get(form.id)
        total = registrations_by_form.get(form.id, 0)
        responses = feedback_by_form.get(child.id, 0) if child else 0
        form_scores = feedback_scores.get(child.id, []) if child else []
        if form.closed_at:
            state = "Completed"
        elif form.is_published:
            state = "Open"
        else:
            state = "Draft"
        event_rows.append(
            {
                "form": form,
                "state": state,
                "date": form.event_start_at,
                "registrations": total,
                "in_range": range_by_form.get(form.id, 0),
                "feedback": responses,
                "response_rate": round(100 * responses / total) if total and child else None,
                "rating": round(sum(form_scores) / len(form_scores), 1) if form_scores else None,
                "certificates": issued_by_event.get(form.id, 0),
            }
        )

    return {
        "days": days,
        "range_label": RANGES[days],
        "ranges": RANGES,
        "start": start,
        "now": now,
        "kpis": {
            "registrations": len(in_range),
            "registrations_delta": _delta(len(in_range), len(previous)),
            "attendees": len(attendees),
            "attendees_delta": _delta(len(attendees), len(previous_attendees)),
            "returning": returning,
            "events_total": len(events),
            "events_open": sum(1 for form in events if form.is_published and not form.closed_at),
            "events_completed": sum(1 for form in events if form.closed_at),
            "rating": round(sum(scores) / len(scores), 1) if scores else None,
            "feedback": len(feedback_in_range),
            "certificates": issued_in_range,
            "certificates_total": len(issued),
            "delivery_rate": round(100 * email_counts.get("sent", 0) / attempted) if attempted else None,
            "emails_attempted": attempted,
        },
        "timeline": buckets,
        "timeline_peak": peak,
        "timeline_chart": column_chart(buckets),
        "by_event": by_event,
        "institutions": institutions,
        "ratings": ratings,
        "email_rows": email_rows,
        "email_total": email_total,
        "event_rows": event_rows,
    }
