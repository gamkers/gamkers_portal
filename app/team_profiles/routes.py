"""GAMKERS team portal.

Three areas share this blueprint:
- Admin (/team-profiles): invite team contributors by email, manage their IDs.
- Team portal (/portal): passwordless sign-in by emailed link; edit your profile.
- Public (/team/<team ID>): the shareable, verifiable team profile page.

Only people an admin invited can ever sign in; there is no public sign-up.
"""

from functools import wraps

from flask import (
    Blueprint,
    abort,
    current_app,
    make_response,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db, limiter
from app.mail import send_email
from app.organization.models import Organization
from app.permissions import requires_permission
from app.security import valid_email
from app.team_profiles.models import (
    STATUS_ACTIVE,
    STATUS_INVITED,
    STATUS_SUSPENDED,
    TeamProfile,
)
from app.team_profiles.services import (
    BIO_LIMIT,
    NAME_LIMIT,
    ROLE_LIMIT,
    SOCIAL_PLATFORMS,
    clean_social_url,
    create_profile,
    find_token,
    issue_token,
    normalize_team_id,
    photo_file,
    remove_photo,
    save_photo,
    social_links,
)
from app.urls import absolute_app_url
from app.utils import utcnow

team_profiles = Blueprint("team_profiles", __name__)
SESSION_KEY = "team_profile_id"


# ── Shared helpers ──────────────────────────────────────────────────────

def _one_line(value, limit):
    value = " ".join((value or "").split())
    return value if len(value) <= limit else None


def _public_url(profile):
    try:
        return absolute_app_url("team_profiles.public_profile", team_id=profile.team_id)
    except RuntimeError:
        return url_for("team_profiles.public_profile", team_id=profile.team_id, _external=True)


def _photo_url(profile, external=False):
    if not profile.photo_path:
        return None
    values = {"team_id": profile.team_id, "v": profile.photo_path[:8]}
    if external:
        try:
            return absolute_app_url("team_profiles.profile_photo", **values)
        except RuntimeError:
            return None
    return url_for("team_profiles.profile_photo", **values)


def _is_public(profile):
    return profile.status == STATUS_ACTIVE and bool(profile.name and profile.role_title)


def _send(profile, subject, body):
    organization = db.session.get(Organization, profile.organization_id)
    try:
        return send_email(profile.email, subject, body, organization)
    except Exception:
        current_app.logger.exception("Team profile email delivery failed.")
        return False


def _send_invite(profile):
    token = issue_token(profile, "invite")
    try:
        link = absolute_app_url("team_profiles.use_link", token=token)
    except RuntimeError:
        current_app.logger.exception("APPLICATION_BASE_URL is not configured.")
        return False
    greeting = f"Hi {profile.name}," if profile.name else "Hi,"
    body = (
        f"{greeting}\n\n"
        "You've been added to the GAMKERS team.\n\n"
        f"Your GAMKERS team ID is {profile.team_id}.\n\n"
        "Set up your team profile (photo, role and social links) within 7 days:\n"
        f"{link}\n\n"
        "Once it's set up, your profile is public at:\n"
        f"{_public_url(profile)}\n"
        "Share that link as proof that you're part of the GAMKERS team.\n\n"
        "Later, sign in at any time from the team portal with this email address."
    )
    return _send(profile, f"Welcome to the GAMKERS team · {profile.team_id}", body)


def _admin_profile(profile_id):
    profile = db.session.get(TeamProfile, profile_id)
    if profile is None or profile.organization_id != current_user.organization_id:
        abort(404)
    return profile


# ── Admin: invite and manage ────────────────────────────────────────────

@team_profiles.get("/team-profiles")
@login_required
@requires_permission("team_profiles.manage")
def admin_index():
    profiles = db.session.scalars(
        db.select(TeamProfile)
        .where(TeamProfile.organization_id == current_user.organization_id)
        .order_by(TeamProfile.team_id)
    ).all()
    counts = {
        status: sum(1 for profile in profiles if profile.status == status)
        for status in (STATUS_ACTIVE, STATUS_INVITED, STATUS_SUSPENDED)
    }
    return render_template(
        "team_profiles/admin.html",
        profiles=profiles,
        counts=counts,
        is_public=_is_public,
        photo_url=_photo_url,
    )


@team_profiles.post("/team-profiles/invite")
@login_required
@requires_permission("team_profiles.manage")
@limiter.limit("30 per hour")
def admin_invite():
    email = request.form.get("email", "").strip().lower()
    name = _one_line(request.form.get("name"), NAME_LIMIT)
    role_title = _one_line(request.form.get("role_title"), ROLE_LIMIT)
    if not valid_email(email):
        flash("Enter a valid email address.", "error")
    elif name is None or role_title is None:
        flash("Keep the name and role under 120 characters.", "error")
    elif db.session.scalar(
        db.select(TeamProfile.id).where(
            TeamProfile.organization_id == current_user.organization_id,
            func.lower(TeamProfile.email) == email,
        )
    ):
        flash("That email already has a team profile.", "error")
    else:
        try:
            profile = create_profile(
                current_user.organization_id, email, current_user.id, name, role_title
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("team_profiles.admin_index"))
        if _send_invite(profile):
            flash(f"Invitation sent to {email}. Their team ID is {profile.team_id}.", "success")
        else:
            flash(
                f"{profile.team_id} was created, but the invitation email could not be sent. "
                "Check the email settings, then use Resend invite.",
                "error",
            )
    return redirect(url_for("team_profiles.admin_index"))


@team_profiles.post("/team-profiles/<int:profile_id>/resend")
@login_required
@requires_permission("team_profiles.manage")
@limiter.limit("30 per hour")
def admin_resend(profile_id):
    profile = _admin_profile(profile_id)
    if profile.status == STATUS_SUSPENDED:
        flash("Reactivate this team ID before sending an invitation.", "error")
    elif _send_invite(profile):
        flash(f"Invitation re-sent to {profile.email}.", "success")
    else:
        flash("The invitation email could not be sent. Check the email settings.", "error")
    return redirect(url_for("team_profiles.admin_index"))


@team_profiles.post("/team-profiles/<int:profile_id>/update")
@login_required
@requires_permission("team_profiles.manage")
def admin_update(profile_id):
    profile = _admin_profile(profile_id)
    name = _one_line(request.form.get("name"), NAME_LIMIT)
    role_title = _one_line(request.form.get("role_title"), ROLE_LIMIT)
    if name is None or role_title is None:
        flash("Keep the name and role under 120 characters.", "error")
    else:
        profile.name, profile.role_title = name, role_title
        db.session.commit()
        flash(f"{profile.team_id} updated.", "success")
    return redirect(url_for("team_profiles.admin_index"))


@team_profiles.post("/team-profiles/<int:profile_id>/status")
@login_required
@requires_permission("team_profiles.manage")
def admin_status(profile_id):
    profile = _admin_profile(profile_id)
    action = request.form.get("action")
    if action == "suspend":
        profile.status = STATUS_SUSPENDED
        for token in profile.tokens:
            token.used_at = token.used_at or utcnow()
        flash(f"{profile.team_id} suspended. Its public page now shows it as inactive.", "success")
    elif action == "reactivate":
        profile.status = STATUS_ACTIVE if profile.joined_at else STATUS_INVITED
        flash(f"{profile.team_id} reactivated.", "success")
    else:
        abort(400)
    db.session.commit()
    return redirect(url_for("team_profiles.admin_index"))


@team_profiles.post("/team-profiles/<int:profile_id>/delete")
@login_required
@requires_permission("team_profiles.manage")
def admin_delete(profile_id):
    profile = _admin_profile(profile_id)
    team_id, photo = profile.team_id, profile.photo_path
    db.session.delete(profile)
    db.session.commit()
    remove_photo(photo)
    flash(f"{team_id} deleted. Its public link no longer works.", "success")
    return redirect(url_for("team_profiles.admin_index"))


# ── Team portal: sign-in by emailed link ────────────────────────────────

def current_profile():
    profile_id = session.get(SESSION_KEY)
    if not profile_id:
        return None
    profile = db.session.get(TeamProfile, profile_id)
    if profile is None or profile.status != STATUS_ACTIVE:
        session.pop(SESSION_KEY, None)
        return None
    return profile


def team_login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        profile = current_profile()
        if profile is None:
            return redirect(url_for("team_profiles.login"))
        return view(profile, *args, **kwargs)

    return wrapped


@team_profiles.route("/portal/login", methods=["GET", "POST"])
@limiter.limit("5 per minute;20 per hour", methods=["POST"])
def login():
    if current_profile():
        return redirect(url_for("team_profiles.portal"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not valid_email(email):
            flash("Enter a valid email address.", "error")
            return render_template("team_profiles/login.html", email=email), 400
        profile = db.session.scalar(
            db.select(TeamProfile).where(
                func.lower(TeamProfile.email) == email,
                TeamProfile.status.in_((STATUS_ACTIVE, STATUS_INVITED)),
            )
        )
        if profile is not None:
            token = issue_token(profile, "login")
            try:
                link = absolute_app_url("team_profiles.use_link", token=token)
                _send(
                    profile,
                    "Your GAMKERS team portal sign-in link",
                    "Use this link to sign in to the GAMKERS team portal. "
                    "It works once and expires in 20 minutes:\n"
                    f"{link}\n\n"
                    "If you didn't ask to sign in, you can ignore this email.",
                )
            except RuntimeError:
                current_app.logger.exception("APPLICATION_BASE_URL is not configured.")
        # Same response either way, so the form can't be used to find team emails.
        return render_template("team_profiles/link_sent.html", email=email)
    return render_template("team_profiles/login.html", email="")


@team_profiles.route("/portal/link/<token>", methods=["GET", "POST"])
@limiter.limit("20 per minute")
def use_link(token):
    record = find_token(token)
    if record is None or record.profile.status == STATUS_SUSPENDED:
        return render_template("team_profiles/link_invalid.html"), 410
    profile = record.profile
    # GET only shows a button: mail scanners that prefetch links can't use them up.
    if request.method == "GET":
        return render_template(
            "team_profiles/link_confirm.html", profile=profile, purpose=record.purpose
        )
    now = utcnow()
    record.used_at = now
    if profile.status == STATUS_INVITED:
        profile.status = STATUS_ACTIVE
        profile.joined_at = now
    profile.last_login_at = now
    db.session.commit()
    session[SESSION_KEY] = profile.id
    if record.purpose == "invite":
        flash(f"Welcome to the GAMKERS team! Set up your profile for {profile.team_id}.", "success")
    return redirect(url_for("team_profiles.portal"))


@team_profiles.post("/portal/logout")
def logout():
    session.pop(SESSION_KEY, None)
    flash("You've signed out of the team portal.", "success")
    return redirect(url_for("team_profiles.login"))


@team_profiles.route("/portal", methods=["GET", "POST"])
@team_login_required
def portal(profile):
    values = {
        "name": profile.name,
        "role_title": profile.role_title,
        "bio": profile.bio,
        **{platform["key"]: (profile.socials or {}).get(platform["key"], "") for platform in SOCIAL_PLATFORMS},
    }
    if request.method == "POST":
        values.update({key: request.form.get(key, "") for key in values})
        errors = []
        name = _one_line(values["name"], NAME_LIMIT)
        role_title = _one_line(values["role_title"], ROLE_LIMIT)
        bio = (values["bio"] or "").strip().replace("\r\n", "\n")
        if not name:
            errors.append("Enter your name (up to 120 characters).")
        if not role_title:
            errors.append("Enter your role in the team (up to 120 characters).")
        if len(bio) > BIO_LIMIT:
            errors.append(f"Keep your bio under {BIO_LIMIT} characters.")
        socials = {}
        for platform in SOCIAL_PLATFORMS:
            try:
                url = clean_social_url(values[platform["key"]], platform)
            except ValueError as error:
                errors.append(str(error))
                continue
            if url:
                socials[platform["key"]] = url
        new_photo = None
        upload = request.files.get("photo")
        if not errors and upload and upload.filename:
            try:
                new_photo = save_photo(upload)
            except ValueError as error:
                errors.append(str(error))
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "team_profiles/portal.html", profile=profile, values=values, **_portal_context(profile)
            ), 400
        old_photo = profile.photo_path
        profile.name, profile.role_title, profile.bio = name, role_title, bio
        profile.socials = socials
        if new_photo:
            profile.photo_path = new_photo
        elif request.form.get("remove_photo") == "yes":
            profile.photo_path = None
        db.session.commit()
        if old_photo and old_photo != profile.photo_path:
            remove_photo(old_photo)
        flash("Profile saved. Your public page is up to date.", "success")
        return redirect(url_for("team_profiles.portal"))
    return render_template(
        "team_profiles/portal.html", profile=profile, values=values, **_portal_context(profile)
    )


def _portal_context(profile):
    return {
        "platforms": SOCIAL_PLATFORMS,
        "public_url": _public_url(profile),
        "photo_url": _photo_url(profile),
        "is_public": _is_public(profile),
        "bio_limit": BIO_LIMIT,
    }


# ── Public: shareable profile by team ID ────────────────────────────────

@team_profiles.get("/team")
def lookup():
    raw = request.args.get("team_id", "")
    if raw:
        team_id = normalize_team_id(raw)
        if team_id:
            return redirect(url_for("team_profiles.public_profile", team_id=team_id))
        flash("Team IDs look like GMK-0001.", "error")
    return render_template("team_profiles/lookup.html", query=raw)


@team_profiles.get("/team/<team_id>")
def public_profile(team_id):
    response = make_response(_render_public_profile(team_id))
    # Verification pages must never be served stale: a suspended ID has to stop
    # looking "verified" for everyone straight away.
    response.headers["Cache-Control"] = "no-cache, max-age=0, must-revalidate"
    return response


def _render_public_profile(team_id):
    normalized = normalize_team_id(team_id)
    if normalized and normalized != team_id:
        return redirect(url_for("team_profiles.public_profile", team_id=normalized), 301)
    profile = (
        db.session.scalar(db.select(TeamProfile).where(TeamProfile.team_id == normalized))
        if normalized
        else None
    )
    if profile is None or (profile.status != STATUS_SUSPENDED and not _is_public(profile)):
        return render_template("team_profiles/lookup.html", query=team_id, not_found=True), 404
    if profile.status == STATUS_SUSPENDED:
        return render_template("team_profiles/inactive.html", team_id=profile.team_id), 410
    return render_template(
        "team_profiles/public.html",
        profile=profile,
        links=social_links(profile),
        photo_url=_photo_url(profile),
        og_image=_photo_url(profile, external=True),
        public_url=_public_url(profile),
        is_owner=session.get(SESSION_KEY) == profile.id,
    )


@team_profiles.get("/team/<team_id>/photo")
def profile_photo(team_id):
    profile = db.session.scalar(
        db.select(TeamProfile).where(TeamProfile.team_id == normalize_team_id(team_id))
    )
    if profile is None or not profile.photo_path:
        abort(404)
    is_owner = session.get(SESSION_KEY) == profile.id
    is_manager = current_user.is_authenticated and current_user.has_permission(
        "team_profiles.manage"
    )
    if not (_is_public(profile) or is_owner or is_manager):
        abort(404)
    path = photo_file(profile.photo_path)
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype="image/jpeg", max_age=86400)
    if not _is_public(profile):
        response.cache_control.public = False
        response.cache_control.private = True
    return response


# Old /id addresses (shared before profiles moved to /team) redirect permanently.
@team_profiles.get("/id", endpoint="legacy_lookup")
@team_profiles.get("/id/<team_id>", endpoint="legacy_profile")
@team_profiles.get("/id/<team_id>/photo", endpoint="legacy_photo")
def legacy_id_redirect(team_id=None):
    path = request.path.replace("/id", "/team", 1)
    query = request.query_string.decode("utf-8", "ignore")
    return redirect(path + (f"?{query}" if query else ""), 301)
