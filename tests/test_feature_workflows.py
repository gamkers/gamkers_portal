import base64
import csv
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.certificates.services import read_recipients
from app.extensions import db
from app.mail import _calendar_invite, _calendar_url, _styled_email, send_email
from app.models import CertificateBatch, CertificateRecord, Form, Submission
from app.utils import utcnow


def _register(client):
    result = client.application.test_cli_runner().invoke(
        args=[
            "create-admin",
            "--name",
            "Event Admin",
            "--email",
            "event-admin@example.com",
        ],
        input="safe-test-password-2026\nsafe-test-password-2026\n",
    )
    assert result.exit_code == 0, result.output
    return client.post(
        "/login",
        data={"email": "event-admin@example.com", "password": "safe-test-password-2026"},
        follow_redirects=True,
    )


def _published_event(client):
    questions = [
        {
            "id": "email",
            "title": "Email",
            "type": "email",
            "required": True,
            "options": [],
        },
        {
            "id": "name",
            "title": "Name",
            "type": "short_text",
            "required": True,
            "options": [],
        },
    ]
    client.post(
        "/forms/new",
        data={
            "title": "Security Summit",
            "questions": json.dumps(questions),
            "confirmation_subject": "You're registered for {form_title}",
            "confirmation_body": "Hello {name}",
            "confirmation_format": "markdown",
            "publish": "yes",
        },
    )
    return Form.query.filter_by(title="Security Summit").first()


def test_application_requires_mysql_connection_settings(monkeypatch):
    from app import create_app
    from config import Config

    monkeypatch.setattr(Config, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(Config, "SQLALCHEMY_DATABASE_URI", None)
    monkeypatch.setattr(Config, "DB_HOST", None)
    monkeypatch.setattr(Config, "DB_PORT", "3306")
    monkeypatch.setattr(Config, "DB_NAME", None)
    monkeypatch.setattr(Config, "DB_USER", None)
    monkeypatch.setattr(Config, "DB_PASSWORD", None)
    with pytest.raises(RuntimeError, match="DB_HOST"):
        create_app()


def test_mysql_connection_settings_escape_password_special_characters():
    from app import create_app
    from sqlalchemy.engine import make_url

    app = create_app(
        {
            "SECRET_KEY": "test-secret",
            "DB_HOST": "db.example",
            "DB_PORT": "3307",
            "DB_NAME": "forms_db",
            "DB_USER": "forms_user",
            "DB_PASSWORD": "safe:@/password?#",
        }
    )
    database_url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])
    assert database_url.drivername == "mysql+pymysql"
    assert database_url.host == "db.example"
    assert database_url.port == 3307
    assert database_url.database == "forms_db"
    assert database_url.username == "forms_user"
    assert database_url.password == "safe:@/password?#"
    assert database_url.query["charset"] == "utf8mb4"


def test_wsgi_entrypoints_start_the_flask_application(monkeypatch):
    import runpy

    import app as app_package
    from flask import Flask

    original_create_app = app_package.create_app
    created_apps = []
    started_apps = []

    def create_test_app():
        app = original_create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "wsgi-smoke-test",
                "SQLALCHEMY_DATABASE_URI": "sqlite://",
            }
        )
        created_apps.append(app)
        return app

    monkeypatch.setattr(app_package, "create_app", create_test_app)
    monkeypatch.setattr(Flask, "run", lambda application: started_apps.append(application))

    runpy.run_path("wsgi.py", run_name="__main__")
    runpy.run_path("passenger_wsgi.py", run_name="__main__")

    assert len(created_apps) == 2
    assert started_apps == created_apps


def test_published_forms_save_changes_without_republishing_or_unpublishing(client):
    _register(client)
    event_form = _published_event(client)

    editor = client.get(f"/forms/{event_form.id}/edit")
    assert b"Save changes" in editor.data
    assert b"Publish form" not in editor.data

    questions = [
        {
            "id": "email",
            "title": "Email",
            "type": "email",
            "required": True,
            "options": [],
        },
        {
            "id": "name",
            "title": "Name",
            "type": "short_text",
            "required": True,
            "options": [],
        },
    ]
    response = client.post(
        f"/forms/{event_form.id}/edit",
        data={
            "title": "Security Summit Updated",
            "questions": json.dumps(questions),
            "confirmation_subject": "Thanks",
            "confirmation_body": "Thanks {name}",
            "confirmation_format": "markdown",
        },
    )
    assert response.status_code == 302
    db.session.refresh(event_form)
    assert event_form.is_published
    assert event_form.title == "Security Summit Updated"


def test_form_banner_upload_is_validated_private_and_served_with_public_form(
    app, client, tmp_path
):
    from PIL import Image

    _register(client)
    event_form = _published_event(client)
    app.config["FORM_BANNER_STORAGE_PATH"] = str(tmp_path / "private-banners")
    image = io.BytesIO()
    Image.new("RGB", (640, 240), "#234567").save(image, format="PNG")

    response = client.post(
        f"/forms/{event_form.id}/edit",
        data={
            "title": event_form.title,
            "description": "Banner test",
            "questions": json.dumps(event_form.questions),
            "confirmation_subject": "Thanks",
            "confirmation_body": "Thanks {name}",
            "confirmation_format": "text",
            "banner_image": (io.BytesIO(image.getvalue()), "event.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    db.session.refresh(event_form)
    banner_path = Path(app.config["FORM_BANNER_STORAGE_PATH"]) / event_form.banner_image_path
    assert banner_path.is_file()
    public_page = client.get(f"/f/{event_form.public_id}")
    assert b"public_form_banner" not in public_page.data
    assert f"/f/{event_form.public_id}/banner".encode() in public_page.data
    banner = client.get(f"/f/{event_form.public_id}/banner")
    assert banner.status_code == 200
    assert banner.mimetype == "image/png"
    assert banner.data.startswith(b"\x89PNG")

    response = client.post(
        f"/forms/{event_form.id}/edit",
        data={
            "title": event_form.title,
            "questions": json.dumps(event_form.questions),
            "confirmation_subject": "Thanks",
            "confirmation_body": "Thanks {name}",
            "confirmation_format": "text",
            "banner_image": (io.BytesIO(b"not an image"), "fake.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert b"valid image" in response.data
    assert banner_path.is_file()


def test_closing_registration_creates_feedback_form_and_generates_permanent_certificates(
    app, client, tmp_path, monkeypatch
):
    app.config["CERTIFICATE_STORAGE_PATH"] = str(tmp_path / "private-certificates")
    mailed = []
    feedback_mail = []
    monkeypatch.setattr(
        "app.certificates.services.send_email",
        lambda *args: mailed.append(args) or True,
    )
    monkeypatch.setattr(
        "app.forms.routes.send_email",
        lambda *args, **kwargs: feedback_mail.append((args, kwargs)) or True,
    )
    _register(client)
    event_form = _published_event(client)
    response = client.post(
        f"/forms/{event_form.id}/close",
        data={"closed_message": "Registration is closed. Thank you."},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Copy link" in response.data

    feedback_form = Form.query.filter_by(parent_form_id=event_form.id).one()
    assert feedback_form.is_published
    assert len(feedback_form.questions) == 6
    consent = feedback_form.questions[-1]
    assert consent["id"] == "public_consent"
    assert consent["type"] == "choice" and consent["required"] is False

    closed_page = client.get(f"/f/{event_form.public_id}")
    assert b"Registration is closed. Thank you." in closed_page.data
    assert b"Share feedback" not in closed_page.data
    assert feedback_form.public_id.encode() not in closed_page.data
    closed_post = client.post(
        f"/f/{event_form.public_id}",
        data={"name": "late attendee", "email": "late@example.com"},
    )
    assert b"Registration is closed" in closed_post.data
    assert Submission.query.filter_by(form_id=event_form.id).count() == 0

    response = client.post(
        f"/f/{feedback_form.public_id}",
        data={
            "certificate_name": "Alex Attendee",
            "college_name": "Northstar Institute",
            "email": "alex@example.com",
            "rating": "Excellent",
            "feedback": "Great workshop!",
        },
    )
    assert response.status_code == 200
    feedback_submission = Submission.query.filter_by(form_id=feedback_form.id).one()
    assert feedback_submission.email_status == "skipped"
    assert feedback_mail == []
    feedback_csv = client.get(f"/forms/{feedback_form.id}/export.csv")
    rows = list(
        csv.DictReader(io.StringIO(feedback_csv.data.decode("utf-8-sig")))
    )
    assert rows[0]["name"] == "Alex Attendee"
    assert rows[0]["college_name"] == "Northstar Institute"
    assert rows[0]["email"] == "alex@example.com"
    assert rows[0]["rating"] == "Excellent"
    assert read_recipients(
        io.BytesIO(feedback_csv.data), f"feedback_{feedback_form.id}.csv"
    )[0] == {
        "name": "Alex Attendee",
        "college_name": "Northstar Institute",
        "email": "alex@example.com",
    }

    response = client.post(
        f"/certificates/forms/{event_form.id}/generate",
        data={
            "title": "Certificate of Participation",
            "description": "Presented to {name} from {college_name}. No. {certificate_number}.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    certificate = CertificateRecord.query.one()
    batch = CertificateBatch.query.one()
    assert batch.generated_records == 1
    assert certificate.recipient_name == "Alex Attendee"
    assert certificate.notification_status == "sent"
    assert len(mailed) == 1
    assert mailed[0][0] == "alex@example.com"
    assert certificate.public_token in mailed[0][2]
    assert certificate.pdf_path
    pdf_path = Path(app.config["CERTIFICATE_STORAGE_PATH"]) / certificate.pdf_path
    assert pdf_path.is_file()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    assert b"/Subtype /Image" not in pdf_path.read_bytes()

    public_page = client.get(f"/certificates/public/{certificate.public_token}")
    assert b"Alex Attendee" in public_page.data
    assert (
        f"/certificates/public/{certificate.public_token}/pdf".encode()
        in public_page.data
    )
    assert b"<iframe" in public_page.data
    # The issuer is GAMKERS; the attendee's own institution is shown as theirs only.
    assert b"Northstar Institute" in public_page.data
    assert b"Issued by Northstar" not in public_page.data
    assert re.search(rb"Issued by</span><b[^>]*>.*?GAMKERS", public_page.data, re.S)
    public_pdf = client.get(f"/certificates/public/{certificate.public_token}/pdf")
    assert public_pdf.status_code == 200
    assert public_pdf.data.startswith(b"%PDF")
    assert public_pdf.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in public_pdf.headers["Content-Security-Policy"]
    downloaded_pdf = client.get(
        f"/certificates/public/{certificate.public_token}/download"
    )
    assert downloaded_pdf.status_code == 200
    assert downloaded_pdf.data == public_pdf.data == pdf_path.read_bytes()
    public_pdf.close()
    downloaded_pdf.close()

    verified = client.get(
        f"/certificates/verify?number={certificate.certificate_number}"
    )
    assert b"AUTHENTIC CERTIFICATE" in verified.data
    assert b"Alex Attendee" in verified.data

    certificate.pdf_expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    cleanup = client.application.test_cli_runner().invoke(
        args=["cleanup-expired-certificate-pdfs"]
    )
    assert cleanup.exit_code == 0, cleanup.output
    assert "Deleted 1 expired certificate PDF" in cleanup.output
    assert not pdf_path.exists()
    assert certificate.pdf_deleted_at is not None
    assert client.get(
        f"/certificates/verify?number={certificate.certificate_number}"
    ).status_code == 200
    assert b"Alex Attendee" in client.get(
        f"/certificates/verify?number={certificate.certificate_number}"
    ).data
    assert client.get(
        f"/certificates/public/{certificate.public_token}/pdf"
    ).status_code == 410

    second_batch = client.post(
        f"/certificates/forms/{event_form.id}/generate",
        data={"title": "Duplicate", "description": "No duplicate."},
        follow_redirects=True,
    )
    assert b"No eligible feedback responses" in second_batch.data
    assert CertificateRecord.query.count() == 1


def test_admin_entry_point_requires_sign_in_and_opens_workspace(client):
    response = client.get("/admin")
    assert response.status_code == 302
    location = urlparse(response.headers["Location"])
    assert location.path == "/admin/login"
    assert parse_qs(location.query) == {"next": ["/dashboard"]}

    login_page = client.get("/admin/login")
    assert login_page.status_code == 200 and b'type="password"' in login_page.data

    _register(client)  # creates the admin and signs in
    response = client.get("/admin")
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/dashboard"
    # Signed-in admins can still view the public site.
    assert client.get("/").status_code == 200


def test_past_event_page_shows_ratings_and_only_consented_feedback(client, monkeypatch):
    monkeypatch.setattr("app.forms.routes.send_email", lambda *args, **kwargs: True)
    _register(client)
    event_form = _published_event(client)
    client.post(
        f"/forms/{event_form.id}/close",
        data={"closed_message": "Thanks for coming."},
    )
    feedback_form = Form.query.filter_by(parent_form_id=event_form.id).one()

    def give_feedback(name, rating, text, consent=None):
        data = {
            "certificate_name": name,
            "college_name": "Northstar Institute",
            "email": f"{name.split()[0].lower()}@example.com",
            "rating": rating,
            "feedback": text,
        }
        if consent:
            data["public_consent"] = consent
        assert client.post(f"/f/{feedback_form.public_id}", data=data).status_code == 200

    give_feedback("Private Person", "Good", "Do not publish this sentence.")
    give_feedback("Opted Out", "Average", "Also keep this private.", "No, keep my feedback private")
    give_feedback("Sam Rivera", "Excellent", "Brilliant hands-on labs.",
                  "Yes, you can feature my feedback publicly")

    page = client.get(f"/f/{event_form.public_id}")
    assert page.status_code == 200
    assert b"Event completed" in page.data
    assert b"3 ratings" in page.data
    assert b"4.0" in page.data  # (4 + 3 + 5) / 3
    assert b"Brilliant hands-on labs." in page.data
    assert b"Sam R." in page.data and b"Sam Rivera" not in page.data
    assert b"Do not publish this sentence." not in page.data
    assert b"Also keep this private." not in page.data
    assert b"@example.com" not in page.data
    assert feedback_form.public_id.encode() not in page.data

    client.post("/logout")  # signed-in admins are redirected to the dashboard
    landing = client.get("/")
    assert landing.status_code == 200
    assert b"Brilliant hands-on labs." in landing.data
    assert b"Do not publish this sentence." not in landing.data


def test_uploaded_recipient_preview_generation_and_exports_are_tenant_scoped(
    app, client, tmp_path, monkeypatch
):
    app.config["CERTIFICATE_STORAGE_PATH"] = str(tmp_path / "private-certificates")
    monkeypatch.setattr("app.certificates.services.send_email", lambda *args: False)
    _register(client)
    response = client.post(
        "/certificates/upload",
        data={
            "recipient_file": (
                io.BytesIO(
                    b"name,college_name,email\nTaylor Example,Northstar Institute,taylor@example.com\n"
                ),
                "recipients.csv",
            )
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    preview_url = urlparse(response.headers["Location"]).path
    preview = client.get(preview_url)
    assert b"Taylor Example" in preview.data
    upload_id = preview_url.rsplit("/", 1)[-1]

    response = client.post(
        f"/certificates/uploads/{upload_id}/generate",
        data={
            "title": "Workshop certificate",
            "description": "Awarded to {name} at {college_name}.",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    batch = CertificateBatch.query.one()
    assert batch.source_filename == "recipients.csv"
    record = CertificateRecord.query.one()
    assert record.recipient_email == "taylor@example.com"
    assert record.notification_status == "not_configured"
    assert CertificateBatch.query.count() == 1

    csv_export = client.get(f"/certificates/batches/{batch.id}/export.csv")
    assert csv_export.status_code == 200
    assert b"taylor" not in csv_export.data
    assert b"/certificates/public/" in csv_export.data
    xlsx_export = client.get(f"/certificates/batches/{batch.id}/export.xlsx")
    assert xlsx_export.status_code == 200
    assert xlsx_export.mimetype == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )



def test_recipient_reader_accepts_csv_and_rejects_missing_institution(app):
    with app.app_context():
        good = io.BytesIO(b"Student Name,Institution Name\nTaylor Example,Northstar Institute\n")
        records = read_recipients(good, "participants.csv")
        assert records == [
            {
                "name": "Taylor Example",
                "college_name": "Northstar Institute",
                "email": None,
            }
        ]
        bad = io.BytesIO(b"name,email\nTaylor Example,taylor@example.com\n")
        try:
            read_recipients(bad, "participants.csv")
        except ValueError as error:
            assert "institution column" in str(error)
        else:
            raise AssertionError("A recipient file without an institution must be rejected.")


def test_confirmation_html_and_markdown_are_sanitised_and_tailwind_styled(app):
    with app.app_context():
        organisation = type(
            "Organisation",
            (),
            {
                "name": "Northstar Events",
                "smtp_host": "mail.example.com",
                "smtp_port": 587,
                "smtp_username": None,
                "smtp_password_encrypted": None,
                "smtp_sender": "no-reply@example.com",
                "smtp_security": "starttls",
            },
        )()
        message, settings, _context = _styled_email(
            "alex@example.com",
            "Thanks",
            "<p>Hello <strong>Alex</strong></p><img src=x onerror=alert(1)>",
            organisation,
            "html",
        )
        assert settings["host"] == "mail.example.com"
        assert message.is_multipart()
        assert message.get_body(preferencelist=("plain",)) is None
        html_part = message.get_body(preferencelist=("html",)).get_content()
        assert "<strong>Alex</strong>" in html_part
        assert "cid:gamkers-portal-logo" in html_part
        assert "GAMKERS PORTAL" in html_part
        assert "Thanks" in html_part
        assert "onerror" not in html_part
        assert "style=" in html_part
        assert "overflow-wrap" in html_part
        assert "word-wrap" not in html_part
        assert "var(--" not in html_part
        logo = next(
            part for part in message.iter_attachments()
            if part.get_content_type() == "image/png"
        )
        assert logo["Content-ID"] == "<gamkers-portal-logo>"
        assert logo.get_content_disposition() == "inline"
        assert len(logo.get_content()) <= 100_000

        message, _, _ = _styled_email(
            "alex@example.com",
            "Thanks",
            "**Hello Alex**\n\nWelcome to [the event](javascript:alert(1)).",
            organisation,
            "markdown",
        )
        html_part = message.get_body(preferencelist=("html",)).get_content()
        assert "<strong>Hello Alex</strong>" in html_part
        assert "javascript:" not in html_part


def test_registration_confirmation_includes_event_details_and_calendar_links(
    app, client, monkeypatch
):
    _register(client)
    questions = [
        {
            "id": "email",
            "title": "Email",
            "type": "email",
            "required": True,
            "options": [],
        }
    ]
    response = client.post(
        "/forms/new",
        data={
            "title": "Modern Web Summit",
            "description": "A full day of talks.",
            "questions": json.dumps(questions),
            "confirmation_subject": "You're registered for {form_title}",
            "confirmation_body": (
                "Your session is {event_date} at {event_time} in {event_location}."
            ),
            "confirmation_format": "text",
            "event_start_at": "2027-04-15T09:00",
            "event_end_at": "2027-04-15T17:30",
            "event_timezone": "Asia/Kolkata",
            "event_location": "Bengaluru Tech Park",
            "event_url": "https://events.example.com/modern-web-summit",
            "publish": "yes",
        },
    )
    assert response.status_code == 302
    event_form = Form.query.filter_by(title="Modern Web Summit").one()
    sent = []

    def fake_send(*args, **kwargs):
        sent.append((args, kwargs))
        return True

    monkeypatch.setattr("app.forms.routes.send_email", fake_send)
    response = client.post(
        f"/f/{event_form.public_id}",
        data={"email": "attendee@example.com"},
    )
    assert response.status_code == 200
    event_kwargs = sent[0][1]
    # Placeholders are filled in the subject too, never sent raw.
    assert sent[0][0][1] == "You're registered for Modern Web Summit"
    assert "{" not in sent[0][0][1] and "{" not in sent[0][0][2]
    assert "15 April 2027" in sent[0][0][2]
    assert "Bengaluru Tech Park" in sent[0][0][2]
    assert event_kwargs["event_details"]["date"] == "Thursday, 15 April 2027"
    assert event_kwargs["event_details"]["location"] == "Bengaluru Tech Park"
    assert event_kwargs["event_url"] == "https://events.example.com/modern-web-summit"
    assert (
        event_kwargs["calendar_event"]["url"]
        == "https://events.example.com/modern-web-summit"
    )
    assert event_kwargs["calendar_event"]["timezone"] == "Asia/Kolkata"


def test_form_rejects_non_https_event_url(client):
    _register(client)
    response = client.post(
        "/forms/new",
        data={
            "title": "Unsafe event link",
            "questions": json.dumps(
                [{"id": "email", "title": "Email", "type": "email", "required": True}]
            ),
            "confirmation_subject": "Thanks",
            "confirmation_body": "Received",
            "event_url": "javascript:alert(1)",
            "publish": "no",
        },
    )

    assert response.status_code == 400
    assert b"valid HTTPS event URL" in response.data


def test_calendar_confirmation_has_styled_google_link_and_ics_attachment(app, monkeypatch):
    with app.app_context():
        organization = SimpleNamespace(
            name="Northstar Events",
            smtp_host="mail.example.com",
            smtp_port=587,
            smtp_username=None,
            smtp_password_encrypted=None,
            smtp_sender="no-reply@example.com",
            smtp_security="starttls",
        )
        calendar_event = {
            "uid": "event-7@forms.gamkers",
            "title": "Northstar Summit",
            "start": datetime(2027, 4, 15, 9),
            "end": datetime(2027, 4, 15, 10),
            "timezone": "Asia/Kolkata",
            "location": "Bengaluru",
            "description": "A summit",
            "url": "https://forms.example/f/abc123",
        }
        details = {
            "date": "Thursday, 15 April 2027",
            "start_time": "09:00 AM",
            "end_time": "10:00 AM",
            "timezone": "Asia/Kolkata",
            "timezone_label": "IST",
            "location": "Bengaluru",
        }
        message, _, _ = _styled_email(
            "attendee@example.com",
            "Registration confirmed",
            "You're registered.",
            organization,
            "text",
            event_details=details,
            event_title=calendar_event["title"],
            event_url=calendar_event["url"],
            calendar_url=_calendar_url(calendar_event),
        )
        html_part = message.get_body(preferencelist=("html",)).get_content()
        assert "Add to Google Calendar" in html_part
        assert "Bengaluru" in html_part
        assert "var(--" not in html_part

        invite = _calendar_invite(calendar_event)
        assert "DTSTART:20270415T033000Z" in invite
        assert "DTEND:20270415T043000Z" in invite
        assert "LOCATION:Bengaluru" in invite
        assert "forms.example/f/abc123" in invite

        sent_messages = []

        class FakeSMTP:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, host, port):
                return 220, b"ready"

            def ehlo(self):
                return 250, b"ready"

            def starttls(self, context=None):
                return 220, b"ready"

            def send_message(self, sent_message):
                sent_messages.append(sent_message)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        monkeypatch.setattr("app.mail.socket.getaddrinfo", lambda *a, **k: [
            (2, 1, 6, "", ("8.8.8.8", 587))
        ])
        monkeypatch.setattr("app.mail.smtplib.SMTP", FakeSMTP)
        assert send_email(
            "attendee@example.com",
            "Registration confirmed",
            "You're registered.",
            organization,
            event_details=details,
            event_title=calendar_event["title"],
            event_url=calendar_event["url"],
            calendar_event=calendar_event,
        )
        attachments = list(sent_messages[0].walk())
        calendar_attachment = next(
            part for part in attachments
            if part.get_content_type() == "text/calendar"
        )
        inline_logo = next(
            part for part in attachments if part.get_content_type() == "image/png"
        )
        assert "DTSTART:20270415T033000Z" in calendar_attachment.get_content()
        assert inline_logo["Content-ID"] == "<gamkers-portal-logo>"
        assert sent_messages[0].get_body(preferencelist=("plain",)) is None
        assert sent_messages[0].get_body(preferencelist=("html",)).get_content_type() == "text/html"


def test_hostinger_mail_api_transport_delivers_styled_email(app, monkeypatch):
    from app import mail

    class FakeResponse:
        def __init__(self, status, body=b""):
            self.status, self._body = status, body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/v1/me"):
            return FakeResponse(200, json.dumps({"data": {
                "orderResourceId": "OR123",
                "mailboxes": [{"resourceId": "ACmailbox1", "address": "hello@gamkers.in"}],
            }}).encode())
        return FakeResponse(204)

    monkeypatch.setattr(mail.urllib.request, "urlopen", fake_urlopen)
    mail._hostinger_mailbox_cache.clear()
    app.config.update(HOSTINGER_MAIL_API_TOKEN="test-token", HOSTINGER_MAIL_MAILBOX_ID=None)
    calendar_event = {
        "uid": "event-9@forms.gamkers", "title": "CTF Night",
        "start": datetime(2027, 1, 10, 18), "end": datetime(2027, 1, 10, 21),
        "timezone": "Asia/Kolkata", "location": "Online", "description": "CTF",
        "url": "https://forms.example/f/xyz",
    }
    with app.app_context():
        assert send_email("alex@example.com", "You're registered", "See you **soon**",
                          None, content_format="markdown", calendar_event=calendar_event)

    # 1) mailbox auto-discovered via /me, 2) message sent to that mailbox
    assert [r.full_url for r in requests] == [
        "https://api.mail.hostinger.com/api/v1/me",
        "https://api.mail.hostinger.com/api/v1/mailboxes/ACmailbox1/send",
    ]
    send = requests[1]
    assert send.get_method() == "POST"
    assert send.get_header("Authorization") == "Bearer test-token"
    payload = json.loads(send.data)
    assert payload["to"] == ["alex@example.com"]
    assert payload["subject"] == "You're registered"
    assert payload["displayName"] == "GAMKERS"
    assert payload["text"] == "See you **soon**"
    assert "cid:gamkers-portal-logo" in payload["html"]
    by_type = {a["contentType"]: a for a in payload["attachments"]}
    assert by_type["image/png"]["cid"] == "gamkers-portal-logo"
    assert by_type["text/calendar"]["filename"] == "event.ics"
    assert "BEGIN:VCALENDAR" in base64.b64decode(by_type["text/calendar"]["content"]).decode()


def test_hostinger_mail_api_errors_never_leak_the_token(app, monkeypatch):
    import urllib.error
    from app import mail

    def failing_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"Unauthenticated."}')
        )

    monkeypatch.setattr(mail.urllib.request, "urlopen", failing_urlopen)
    app.config.update(HOSTINGER_MAIL_API_TOKEN="secret-token-value", HOSTINGER_MAIL_MAILBOX_ID="ACx")
    with app.app_context():
        with pytest.raises(RuntimeError) as error:
            send_email("alex@example.com", "Hi", "Body", None)
    assert "HTTP 401" in str(error.value) and "Unauthenticated" in str(error.value)
    assert "secret-token-value" not in str(error.value)


def test_same_email_cannot_register_twice_and_honeypot_drops_bots(client, monkeypatch):
    mailed = []
    monkeypatch.setattr(
        "app.forms.routes.send_email", lambda *args, **kwargs: mailed.append(args) or True
    )
    _register(client)
    event_form = _published_event(client)
    client.post("/logout")
    url = f"/f/{event_form.public_id}"

    first = client.post(url, data={"email": "Sam@Example.com", "name": "Sam"})
    assert first.status_code == 200 and len(mailed) == 1

    # Same address (different case): rejected, nothing stored, no second email.
    again = client.post(url, data={"email": "sam@example.com", "name": "Sam again"})
    assert again.status_code == 409
    assert b"already registered for this event" in again.data
    assert Submission.query.filter_by(form_id=event_form.id).count() == 1
    assert len(mailed) == 1

    # A different person can still register.
    assert client.post(url, data={"email": "ria@example.com", "name": "Ria"}).status_code == 200
    assert Submission.query.filter_by(form_id=event_form.id).count() == 2

    # Honeypot filled: looks like success to the bot, but nothing is stored or sent.
    bot = client.post(url, data={"email": "bot@spam.test", "name": "Bot", "hp_website": "http://spam"})
    assert bot.status_code == 200
    assert Submission.query.filter_by(respondent_email="bot@spam.test").count() == 0
    assert len(mailed) == 2

    # The rendered form carries the hidden honeypot and the double-submit guard.
    page = client.get(url).data
    assert b'name="hp_website"' in page and b"data-submit-once" in page


def test_feedback_form_accepts_one_response_per_email(client, monkeypatch):
    monkeypatch.setattr("app.forms.routes.send_email", lambda *args, **kwargs: True)
    _register(client)
    event_form = _published_event(client)
    client.post(f"/forms/{event_form.id}/close", data={"closed_message": "Thanks!"})
    feedback_form = Form.query.filter_by(parent_form_id=event_form.id).one()
    data = {"certificate_name": "Alex A", "college_name": "Northstar", "email": "alex@example.com",
            "rating": "Good", "feedback": "Nice"}
    assert client.post(f"/f/{feedback_form.public_id}", data=data).status_code == 200
    second = client.post(f"/f/{feedback_form.public_id}", data=data)
    assert second.status_code == 409
    assert b"already received feedback" in second.data
    assert Submission.query.filter_by(form_id=feedback_form.id).count() == 1


def test_answers_with_html_tags_are_rejected_but_plain_text_is_kept():
    from app.forms.validation import validate_answers

    questions = [{"id": "name", "title": "Name", "type": "short_text", "required": True, "options": []},
                 {"id": "note", "title": "Note", "type": "long_text", "required": False, "options": []}]

    class Form(dict):
        def getlist(self, key):
            return [self[key]] if key in self else []

    for attack in ('<a href="https://evil.example">Verify</a>', "<script>alert(1)</script>",
                   "<img src=x onerror=alert(1)>", "Sam</b>", "<!-- hidden -->"):
        with pytest.raises(ValueError, match="remove HTML tags"):
            validate_answers(questions, Form(name=attack))
    answers, _ = validate_answers(questions, Form(name="Sam <3 CTFs", note="2 < 3 and 5 > 4"))
    assert answers == {"name": "Sam <3 CTFs", "note": "2 < 3 and 5 > 4"}


@pytest.mark.parametrize("content_format", ["markdown", "html"])
def test_respondent_text_cannot_inject_links_or_markup_into_emails(client, monkeypatch, content_format):
    from app.mail import _sanitize_email_html

    sent = []
    monkeypatch.setattr("app.forms.routes.send_email", lambda *args, **kwargs: sent.append(args) or True)
    _register(client)
    questions = [{"id": "email", "title": "Email", "type": "email", "required": True, "options": []},
                 {"id": "name", "title": "Name", "type": "short_text", "required": True, "options": []}]
    template = "Hi {name}, see you at **{form_title}**!" if content_format == "markdown" \
        else "<p>Hi {name}, see you at <strong>{form_title}</strong>!</p>"
    client.post("/forms/new", data={
        "title": "Safe Summit", "questions": json.dumps(questions),
        "confirmation_subject": "Hello {name}", "confirmation_body": template,
        "confirmation_format": content_format, "publish": "yes"})
    form = Form.query.filter_by(title="Safe Summit").one()
    client.post("/logout")
    hostile_name = "[Verify your account](https://evil.example) **now** & _then_"
    assert client.post(f"/f/{form.public_id}", data={"email": "victim@example.com", "name": hostile_name}).status_code == 200

    with client.application.app_context():
        email_html = _sanitize_email_html(sent[0][2], content_format)
    assert "<a" not in email_html and "evil.example" in email_html   # shown as text, not a link
    assert "<em>" not in email_html                                    # respondent text adds no formatting
    assert "<strong>Safe Summit</strong>" in email_html                # the admin's own formatting still works
    assert "**now**" in email_html and "&amp;" in email_html


def test_analytics_requires_sign_in_and_aggregates_event_activity(client, monkeypatch):
    assert client.get("/analytics").status_code == 302
    monkeypatch.setattr("app.forms.routes.send_email", lambda *args, **kwargs: True)
    _register(client)
    event_form = _published_event(client)
    other_event = Form(
        organization_id=event_form.organization_id,
        creator_id=event_form.creator_id,
        title="Hardware Night",
        public_id="hardware-night-analytics",
        questions=[],
        is_published=True,
    )
    db.session.add(other_event)
    db.session.flush()
    now = utcnow()

    def add(form, email, days_ago, status="sent", **answers):
        db.session.add(
            Submission(
                form_id=form.id,
                respondent_email=email,
                email_status=status,
                submitted_at=now - timedelta(days=days_ago),
                answers={"email": email, **answers},
            )
        )

    add(event_form, "ana@example.com", 1, college_name="Northstar Institute")
    add(event_form, "ben@example.com", 2, status="failed", college_name="Northstar  Institute")
    add(event_form, "cy@example.com", 40, college_name="Old College")  # previous period
    add(other_event, "ana@example.com", 3, status="not_configured", college_name="Harbor Tech")
    db.session.commit()

    client.post(f"/forms/{event_form.id}/close", data={"closed_message": "Thanks."})
    feedback_form = Form.query.filter_by(parent_form_id=event_form.id).one()
    # Institutions only count from forms that ask for one (the feedback form here),
    # once per person, with whitespace normalised.
    add(feedback_form, "ana@example.com", 0, status="skipped", rating="Excellent",
        college_name="Northstar Institute")
    add(feedback_form, "ben@example.com", 0, status="skipped", rating="Good",
        college_name="Northstar  Institute")
    db.session.commit()

    from app.main.analytics import build_analytics

    data = build_analytics(event_form.organization_id, 30)
    kpis = data["kpis"]
    assert kpis["registrations"] == 3  # feedback excluded, 40-day-old row outside range
    assert kpis["registrations_delta"] == 200
    assert kpis["attendees"] == 2 and kpis["returning"] == 1
    assert kpis["events_total"] == 2 and kpis["events_completed"] == 1
    assert kpis["rating"] == 4.5 and kpis["feedback"] == 2
    assert kpis["delivery_rate"] == 50  # 1 sent of 2 attempted
    assert sum(bucket["count"] for bucket in data["timeline"]) == 3
    assert data["institutions"][0] == {"label": "Northstar Institute", "count": 2, "pct": 100}
    summit = next(row for row in data["event_rows"] if row["form"].id == event_form.id)
    assert summit["registrations"] == 3 and summit["feedback"] == 2
    assert summit["response_rate"] == 67 and summit["state"] == "Completed"

    page = client.get("/analytics?range=30")
    assert page.status_code == 200
    assert b"Registrations over time" in page.data
    assert b"Northstar Institute" in page.data
    assert b"style=" not in page.data  # strict CSP: no inline style attributes
    assert client.get("/analytics?range=bogus").status_code == 200


def test_featured_event_fills_the_landing_ticket_and_only_one_is_featured(client, monkeypatch):
    _register(client)
    questions = json.dumps([
        {"id": "email", "title": "Email", "type": "email", "required": True, "options": []},
    ])
    soon = (utcnow() + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    later = (utcnow() + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")

    def create(title, start, featured):
        data = {
            "title": title,
            "questions": questions,
            "confirmation_subject": "Registered",
            "confirmation_body": "Thanks",
            "confirmation_format": "text",
            "event_start_at": start,
            "event_timezone": "UTC",
            "publish": "yes",
        }
        if featured:
            data["is_featured"] = "yes"
        client.post("/forms/new", data=data)
        return Form.query.filter_by(title=title).one()

    create("Soonest Meetup", soon, False)
    flagship = create("Flagship Conference", later, True)
    client.post("/logout")

    def ticket_title():
        page = client.get("/").get_data(as_text=True)
        match = re.search(r'class="ticket-main".*?<h2>(.*?)</h2>', page, re.S)
        return match.group(1) if match else None

    assert ticket_title() == "Flagship Conference"  # featured beats the soonest event

    client.post("/login", data={"email": "event-admin@example.com", "password": "safe-test-password-2026"})
    other = create("Hardware Day", later, True)
    db.session.expire_all()
    assert db.session.get(Form, other.id).is_featured
    assert not db.session.get(Form, flagship.id).is_featured  # featuring one unfeatures the rest

    # Unticking it on save returns the ticket to the soonest event.
    client.post(f"/forms/{other.id}/edit", data={
        "title": "Hardware Day", "questions": questions, "confirmation_subject": "Registered",
        "confirmation_body": "Thanks", "confirmation_format": "text",
        "event_start_at": later, "event_timezone": "UTC",
    })
    db.session.expire_all()
    assert not db.session.get(Form, other.id).is_featured
    client.post("/logout")
    assert ticket_title() == "Soonest Meetup"
