from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.auth.models import User
from app.extensions import db
from app.main.analytics import build_analytics, parse_range
from app.permissions import requires_permission
from app.forms.models import Form, Submission
from app.forms.public_events import feedback_summary, registration_count

main = Blueprint("main", __name__)


@main.get("/admin")
@main.get("/admin/")
def admin():
    """Admin entry point: the forms workspace, or the sign-in page first."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login", next=url_for("main.dashboard")))


@main.get("/")
def home():
    # The public site is shown to everyone; admins reach the workspace via /admin.
    # Public events = published, top-level (non-feedback) forms. Open ones are
    # upcoming/registerable; closed ones are shown as past events.
    upcoming_events = (
        Form.query.filter(
            Form.is_published.is_(True),
            Form.parent_form_id.is_(None),
            Form.closed_at.is_(None),
        )
        .order_by(
            Form.event_start_at.is_(None),  # dated events first
            Form.event_start_at.asc(),
            Form.created_at.desc(),
        )
        .limit(12)
        .all()
    )
    past_events = (
        Form.query.filter(
            Form.parent_form_id.is_(None),
            Form.closed_at.isnot(None),
        )
        .order_by(Form.closed_at.desc())
        .limit(6)
        .all()
    )
    # "Next event" ticket: the event an admin chose to feature, otherwise the
    # soonest event that has not started yet. Event times are stored naive in
    # the event's own timezone.
    next_event, next_event_iso = None, None
    now_utc = datetime.now(timezone.utc)
    candidates = sorted(upcoming_events, key=lambda event: not event.is_featured)
    for event in candidates:
        if not event.event_start_at:
            continue
        try:
            starts = event.event_start_at.replace(tzinfo=ZoneInfo(event.event_timezone))
        except (ZoneInfoNotFoundError, ValueError):
            continue
        if starts > now_utc:
            next_event, next_event_iso = event, starts.isoformat()
            break
    # Completed events with anonymous rating totals and consented quotes.
    completed = []
    testimonials = []
    for event in past_events:
        summary = feedback_summary(event, quote_limit=3)
        completed.append(
            {"event": event, "feedback": summary, "registrations": registration_count(event)}
        )
        testimonials.extend(summary["quotes"])
    return render_template(
        "landing.html",
        upcoming_events=upcoming_events,
        past_events=past_events,
        completed_events=completed,
        testimonials=testimonials[:6],
        next_event=next_event,
        next_event_iso=next_event_iso,
    )


@main.get("/products/ghostchip")
def product_ghostchip():
    return render_template("community/ghostchip.html")


@main.get("/products/phantom32")
def product_phantom32():
    return render_template("community/phantom32.html")


@main.get("/dashboard")
@login_required
def dashboard():
    forms = (
        Form.query.filter_by(organization_id=current_user.organization_id)
        .order_by(Form.updated_at.desc())
        .all()
    )
    response_counts = {}
    if forms:
        response_counts = dict(
            db.session.query(Submission.form_id, func.count(Submission.id))
            .filter(Submission.form_id.in_([form.id for form in forms]))
            .group_by(Submission.form_id)
            .all()
        )
    total_responses = sum(response_counts.values())
    member_count = User.query.filter_by(organization_id=current_user.organization_id).count()
    return render_template(
        "dashboard.html",
        forms=forms,
        member_count=member_count,
        response_counts=response_counts,
        total_responses=total_responses,
        can_manage_forms=current_user.has_permission("forms.manage"),
        can_view_responses=current_user.has_permission("responses.view"),
        can_export_responses=current_user.has_permission("responses.export"),
    )


@main.get("/analytics")
@login_required
@requires_permission("responses.view")
def analytics():
    days = parse_range(request.args.get("range"))
    return render_template(
        "analytics.html", data=build_analytics(current_user.organization_id, days)
    )
