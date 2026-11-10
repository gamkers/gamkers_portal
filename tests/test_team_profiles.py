import io
import re

import pytest
from PIL import Image

from app.extensions import db
from app.team_profiles.models import TeamProfile, TeamProfileToken

ADMIN_EMAIL = "team-admin@example.com"
ADMIN_PASSWORD = "safe-test-password-2026"


@pytest.fixture
def outbox(monkeypatch):
    sent = []

    def fake_send(recipient, subject, body, organization=None, **kwargs):
        sent.append({"to": recipient, "subject": subject, "body": body})
        return True

    monkeypatch.setattr("app.team_profiles.routes.send_email", fake_send)
    return sent


def _sign_in_admin(client):
    result = client.application.test_cli_runner().invoke(
        args=["create-admin", "--name", "Team Admin", "--email", ADMIN_EMAIL],
        input=f"{ADMIN_PASSWORD}\n{ADMIN_PASSWORD}\n",
    )
    assert result.exit_code == 0, result.output
    client.post("/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})


def _link_from(mail):
    match = re.search(r"https://forms\.example(/portal/link/[\w-]+)", mail["body"])
    assert match, mail["body"]
    return match.group(1)


def _png(size=(900, 600), color=(30, 160, 80)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _invite_and_join(client, outbox, email="dev@example.com", name=""):
    client.post("/team-profiles/invite", data={"email": email, "name": name, "role_title": ""})
    profile = TeamProfile.query.filter_by(email=email).one()
    link = _link_from(outbox[-1])
    client.post("/logout")  # members use their own session, not the admin login
    assert client.post(link).status_code == 302
    return profile


def test_admin_invites_team_members_with_sequential_ids(client, outbox):
    assert client.get("/team-profiles").status_code == 302  # admin sign-in required
    _sign_in_admin(client)

    response = client.post(
        "/team-profiles/invite",
        data={"email": "Priya@Example.com", "name": "Priya Raman", "role_title": "VAPT Lead"},
        follow_redirects=True,
    )
    assert b"GMK-0001" in response.data
    client.post("/team-profiles/invite", data={"email": "arun@example.com"})
    assert [p.team_id for p in TeamProfile.query.order_by(TeamProfile.id)] == ["GMK-0001", "GMK-0002"]

    first = TeamProfile.query.filter_by(team_id="GMK-0001").one()
    assert first.email == "priya@example.com" and first.status == "invited"
    assert outbox[0]["to"] == "priya@example.com"
    assert "GMK-0001" in outbox[0]["subject"] and "https://forms.example/team/GMK-0001" in outbox[0]["body"]

    duplicate = client.post(
        "/team-profiles/invite", data={"email": "PRIYA@example.com"}, follow_redirects=True
    )
    assert b"already has a team profile" in duplicate.data
    assert TeamProfile.query.count() == 2


def test_invite_link_activates_once_and_mail_scanners_cannot_use_it(client, outbox):
    _sign_in_admin(client)
    client.post("/team-profiles/invite", data={"email": "dev@example.com"})
    link = _link_from(outbox[-1])
    client.post("/logout")

    page = client.get(link)  # a link scanner prefetching the URL
    assert page.status_code == 200 and b"GMK-0001" in page.data
    assert TeamProfile.query.one().status == "invited"

    assert client.post(link).headers["Location"].endswith("/portal")
    profile = TeamProfile.query.one()
    assert profile.status == "active" and profile.joined_at is not None
    assert client.get("/portal").status_code == 200

    client.post("/portal/logout")
    assert client.post(link).status_code == 410  # single use
    assert client.get("/portal").status_code == 302


def test_profile_editor_validates_links_and_publishes_verified_page(client, outbox):
    _sign_in_admin(client)
    profile = _invite_and_join(client, outbox)
    assert client.get("/team/GMK-0001").status_code == 404  # hidden until set up

    bad = client.post("/portal", data={
        "name": "Dev Kumar", "role_title": "Hardware Lead",
        "linkedin": "https://linkedin.com.evil.example/in/dev",
        "website": "javascript:alert(1)",
    })
    assert bad.status_code == 400
    assert b"LinkedIn links must point to linkedin.com" in bad.data
    assert b"Enter a valid Website link." in bad.data
    assert b'value="Dev Kumar"' in bad.data  # typed values are kept

    saved = client.post("/portal", data={
        "name": "Dev Kumar", "role_title": "Hardware Lead",
        "bio": "Builds <b>badges</b> & RF tools.",
        "linkedin": "linkedin.com/in/devkumar",
        "github": "https://github.com/devk",
        "photo": (_png(), "me.png"),
    }, content_type="multipart/form-data")
    assert saved.status_code == 302
    db.session.refresh(profile)
    assert profile.socials == {
        "linkedin": "https://linkedin.com/in/devkumar",
        "github": "https://github.com/devk",
    }

    client.post("/portal/logout")
    page = client.get("/team/GMK-0001")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "Verified GAMKERS team member" in html and "Hardware Lead" in html
    assert "https://github.com/devk" in html
    assert "&lt;b&gt;badges&lt;/b&gt;" in html  # bio is escaped, never rendered as HTML
    assert "dev@example.com" not in html  # email stays private
    assert 'property="og:image"' in html

    photo = client.get(f"/team/GMK-0001/photo?v={profile.photo_path[:8]}")
    assert photo.status_code == 200 and photo.mimetype == "image/jpeg"
    with Image.open(io.BytesIO(photo.data)) as image:
        assert image.size == (640, 640) and not image.getexif()

    assert client.get("/team/gmk-0001").headers["Location"].endswith("/team/GMK-0001")
    assert client.get("/team?team_id=gmk-0001").status_code == 302


def test_sign_in_link_only_goes_to_team_emails(client, outbox):
    _sign_in_admin(client)
    _invite_and_join(client, outbox)
    outbox.clear()
    client.post("/portal/logout")

    stranger = client.post("/portal/login", data={"email": "stranger@example.com"})
    member = client.post("/portal/login", data={"email": "DEV@example.com"})
    assert b"Check your inbox" in stranger.data and b"Check your inbox" in member.data
    assert [mail["to"] for mail in outbox] == ["dev@example.com"]
    assert client.post(_link_from(outbox[0])).headers["Location"].endswith("/portal")


def test_suspended_id_shows_inactive_and_ends_portal_access(client, outbox):
    _sign_in_admin(client)
    profile = _invite_and_join(client, outbox)
    client.post("/portal", data={"name": "Dev Kumar", "role_title": "Hardware Lead"})
    assert client.get("/team/GMK-0001").status_code == 200

    client.post("/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    client.post(f"/team-profiles/{profile.id}/status", data={"action": "suspend"})
    inactive = client.get("/team/GMK-0001")
    assert inactive.status_code == 410
    assert b"no longer active" in inactive.data and b"Dev Kumar" not in inactive.data
    assert client.get("/portal").status_code == 302  # their session no longer works
    assert db.session.scalar(
        db.select(db.func.count(TeamProfileToken.id)).where(TeamProfileToken.used_at.is_(None))
    ) == 0

    outbox.clear()
    client.post("/portal/login", data={"email": "dev@example.com"})
    assert outbox == []  # suspended IDs can't request sign-in links

    client.post(f"/team-profiles/{profile.id}/status", data={"action": "reactivate"})
    assert client.get("/team/GMK-0001").status_code == 200
    client.post(f"/team-profiles/{profile.id}/delete")
    assert client.get("/team/GMK-0001").status_code == 404
    assert TeamProfile.query.count() == 0


def test_deleted_team_ids_are_never_reissued(client, outbox):
    _sign_in_admin(client)
    client.post("/team-profiles/invite", data={"email": "first@example.com"})
    client.post("/team-profiles/invite", data={"email": "second@example.com"})
    newest = TeamProfile.query.filter_by(team_id="GMK-0002").one()
    client.post(f"/team-profiles/{newest.id}/delete")

    client.post("/team-profiles/invite", data={"email": "third@example.com"})
    assert TeamProfile.query.filter_by(email="third@example.com").one().team_id == "GMK-0003"
    assert client.get("/team/GMK-0002").status_code == 404


def test_old_id_links_redirect_to_team_pages(client):
    assert client.get("/id/GMK-0007").headers["Location"].endswith("/team/GMK-0007")
    assert client.get("/id/GMK-0007").status_code == 301
    assert client.get("/id/GMK-0007/photo?v=ab").headers["Location"].endswith("/team/GMK-0007/photo?v=ab")
    assert client.get("/id?team_id=GMK-0007").headers["Location"].endswith("/team?team_id=GMK-0007")
