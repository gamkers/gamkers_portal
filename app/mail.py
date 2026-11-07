import base64
import hashlib
import html
import ipaddress
import json
import re
import socket
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import bleach
import markdown
from flask import current_app, render_template
from markupsafe import Markup
from premailer import transform

from app.security import decrypt_smtp_password

EMAIL_TAGS = {
    "a", "b", "blockquote", "br", "code", "em", "h1", "h2", "h3", "hr",
    "i", "li", "ol", "p", "pre", "strong", "table", "tbody", "td", "th",
    "thead", "tr", "u", "ul",
}
EMAIL_ATTRIBUTES = {"a": ["href", "title"]}
EMAIL_PROTOCOLS = {"http", "https", "mailto"}


MARKDOWN_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~>])")


def escape_for_email(value, content_format):
    """Make untrusted text (e.g. a respondent's answer) inert inside an email body.

    Admin-written templates may use HTML or Markdown; values typed by the public
    must never add links, images or markup, only plain text.
    """
    value = str(value)
    if content_format == "html":
        return html.escape(value, quote=True)
    if content_format == "markdown":
        return MARKDOWN_SPECIAL.sub(r"\\\1", html.escape(value, quote=False))
    return value  # plain-text emails are escaped as a whole later on


def _sanitize_email_html(content, content_format):
    if content_format == "markdown":
        content = markdown.markdown(content, extensions=["extra", "nl2br"])
    elif content_format == "text":
        content = "<p>" + "<br>\n".join(
            html.escape(line) for line in content.splitlines()
        ) + "</p>"
    elif content_format != "html":
        raise ValueError("Unsupported confirmation email format.")
    return bleach.clean(
        content,
        tags=EMAIL_TAGS,
        attributes=EMAIL_ATTRIBUTES,
        protocols=EMAIL_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )


def _email_css_for_inliner(css):
    marker = "@layer email{"
    layer_start = css.find(marker)
    if layer_start < 0:
        raise RuntimeError("The compiled Tailwind email styles are missing.")
    start = layer_start + len(marker)
    depth = 1
    for end in range(start, len(css)):
        if css[end] == "{":
            depth += 1
        elif css[end] == "}":
            depth -= 1
            if depth == 0:
                css = css[start:end]
                break
    else:
        raise RuntimeError("The compiled Tailwind email styles are malformed.")

    css = re.sub(
        r"var\(--tw-leading,\s*var\(--text-base--line-height\)\)",
        "1.5",
        css,
    )
    css = re.sub(
        r"var\(--tw-leading,\s*var\(--text-xs--line-height\)\)",
        "1.3333",
        css,
    )
    css = re.sub(
        r"calc\(var\(--spacing\)\s*\*\s*([0-9.]+)\)",
        lambda match: f"{float(match.group(1)) * 0.25:g}rem",
        css,
    )
    values = {
        "spacing": "0.25rem",
        "font-sans": "Arial, Helvetica, sans-serif",
        "font-mono": "monospace",
        "font-weight-bold": "700",
        "font-weight-extrabold": "800",
        "font-weight-semibold": "600",
        "radius-2xl": "1rem",
        "radius-xl": "0.75rem",
        "radius-lg": "0.5rem",
        "radius-md": "0.375rem",
        "text-xs": "0.75rem",
        "text-base": "1rem",
        "color-white": "#ffffff",
        "color-email-ink": "#202a23",
        "color-email-muted": "#667168",
        "color-email-green": "#16a34a",
        "color-email-line": "#e2e8e2",
        "tw-border-style": "solid",
    }
    for name, value in values.items():
        css = css.replace(f"var(--{name})", value)
    css = re.sub(r"--[\w-]+:[^;]+;", "", css)
    for logical, physical in (
        ("padding-inline", ("padding-left", "padding-right")),
        ("padding-block", ("padding-top", "padding-bottom")),
        ("margin-inline", ("margin-left", "margin-right")),
        ("margin-block", ("margin-top", "margin-bottom")),
    ):
        css = re.sub(
            rf"{logical}:([^;]+);",
            lambda match: "".join(
                f"{property_name}:{match.group(1)};"
                for property_name in physical
            ),
            css,
        )
    return css.replace("text-decoration-line:", "text-decoration:")


def _calendar_utc_datetime(value, event_timezone):
    local_time = value.replace(tzinfo=ZoneInfo(event_timezone))
    return local_time.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _calendar_url(calendar_event):
    dates = (
        f"{_calendar_utc_datetime(calendar_event['start'], calendar_event['timezone'])}/"
        f"{_calendar_utc_datetime(calendar_event['end'], calendar_event['timezone'])}"
    )
    description = calendar_event.get("description", "")
    if calendar_event.get("url"):
        description = f"{description}\n\nEvent details: {calendar_event['url']}"
    parameters = {
        "action": "TEMPLATE",
        "text": calendar_event["title"],
        "dates": dates,
        "details": description,
        "location": calendar_event.get("location", ""),
        "ctz": calendar_event["timezone"],
    }
    return "https://calendar.google.com/calendar/render?" + urlencode(parameters)


def _escape_ical(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(",", "\\,")
        .replace(";", "\\;")
    )


def _fold_ical_line(line):
    chunks = []
    current = ""
    current_size = 0
    for character in line:
        char_size = len(character.encode("utf-8"))
        if current_size + char_size > 75:
            chunks.append(current)
            current = character
            current_size = char_size
        else:
            current += character
            current_size += char_size
    chunks.append(current)
    return "\r\n ".join(chunks)


def _calendar_invite(calendar_event):
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//GAMKERS PORTAL//Event Confirmation//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{_escape_ical(calendar_event['uid'])}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART:{_calendar_utc_datetime(calendar_event['start'], calendar_event['timezone'])}",
        f"DTEND:{_calendar_utc_datetime(calendar_event['end'], calendar_event['timezone'])}",
        f"SUMMARY:{_escape_ical(calendar_event['title'])}",
        f"DESCRIPTION:{_escape_ical(calendar_event.get('description', ''))}",
        f"LOCATION:{_escape_ical(calendar_event.get('location', ''))}",
    ]
    if calendar_event.get("url"):
        lines.append(f"URL:{_escape_ical(calendar_event['url'])}")
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(_fold_ical_line(line) for line in lines)


def _styled_email(
    recipient,
    subject,
    body,
    organization,
    content_format,
    event_details=None,
    event_title=None,
    event_url=None,
    calendar_url=None,
):
    settings = hostinger_settings() or smtp_settings(organization)
    if not settings:
        return None, None, None
    safe_html = _sanitize_email_html(body, content_format)
    email_html = render_template(
        "emails/message.html",
        organization_name=getattr(organization, "name", None)
        or current_app.config.get("DEFAULT_SMTP_SENDER", "GAMKERS PORTAL"),
        subject=subject,
        message_html=Markup(safe_html),
        event_details=event_details,
        event_title=event_title,
        event_url=event_url,
        calendar_url=calendar_url,
    )
    css_path = Path(current_app.config["EMAIL_CSS_PATH"])
    if not css_path.is_file():
        raise RuntimeError("Build the Tailwind stylesheet before sending email.")
    styled_html = transform(
        email_html,
        css_text=_email_css_for_inliner(css_path.read_text(encoding="utf-8")),
        disable_link_rewrites=True,
        allow_network=False,
        keep_style_tags=False,
        remove_classes=False,
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings["sender"]
    message["To"] = recipient
    message.set_content(styled_html, subtype="html")
    logo_path = Path(current_app.static_folder) / "img" / "email-logo.png"
    if not logo_path.is_file():
        raise RuntimeError("The GAMKERS Portal email logo is missing.")
    message.add_related(
        logo_path.read_bytes(),
        maintype="image",
        subtype="png",
        cid="<gamkers-portal-logo>",
        filename="gamkers-portal-logo.png",
        disposition="inline",
    )
    return message, settings, ssl.create_default_context()


HOSTINGER_TIMEOUT_SECONDS = 20
_hostinger_mailbox_cache = {}  # sha256(token) -> mailbox resource ID


def hostinger_settings():
    """Hostinger Mail API settings, or None when no API token is configured."""
    config = current_app.config
    token = (config.get("HOSTINGER_MAIL_API_TOKEN") or "").strip()
    if not token:
        return None
    display_name = config.get("HOSTINGER_MAIL_DISPLAY_NAME") or "GAMKERS"
    return {
        "transport": "hostinger",
        "token": token,
        "mailbox_id": (config.get("HOSTINGER_MAIL_MAILBOX_ID") or "").strip() or None,
        "base_url": (config.get("HOSTINGER_MAIL_API_URL") or "https://api.mail.hostinger.com").rstrip("/"),
        "display_name": display_name,
        "sender": display_name,
    }


def _hostinger_request(settings, method, path, payload=None):
    if not settings["base_url"].startswith("https://"):
        raise ValueError("The Hostinger Mail API URL must use HTTPS.")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {settings['token']}",
        "Accept": "application/json",
        # Cloudflare in front of the API rejects Python's default User-Agent (error 1010).
        "User-Agent": "GAMKERS-Portal/1.0 (+https://gamkers.in)",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        settings["base_url"] + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=HOSTINGER_TIMEOUT_SECONDS) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as error:
        # Report the status and the API's message, never the request (it carries the token).
        detail = error.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"Hostinger Mail API returned HTTP {error.code}: {detail}") from None


def hostinger_mailboxes(settings):
    """Mailboxes the API token may send from: [{"resourceId": "AC...", "address": ...}]."""
    _, payload = _hostinger_request(settings, "GET", "/api/v1/me")
    return ((payload or {}).get("data") or {}).get("mailboxes") or []


def _hostinger_mailbox_id(settings):
    if settings["mailbox_id"]:
        return settings["mailbox_id"]
    key = hashlib.sha256(settings["token"].encode("utf-8")).hexdigest()
    if key not in _hostinger_mailbox_cache:
        mailboxes = hostinger_mailboxes(settings)
        if not mailboxes:
            raise RuntimeError("The Hostinger Mail API token cannot manage any mailbox.")
        _hostinger_mailbox_cache[key] = mailboxes[0]["resourceId"]
    return _hostinger_mailbox_cache[key]


def _plain_text_body(body, content_format):
    if content_format != "html":
        return body  # plain text and Markdown already read well as text
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr)>", "\n", body)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _send_via_hostinger(message, recipient, settings, text_body):
    """Deliver an already-built EmailMessage through the Hostinger Mail API."""
    payload = {
        "to": [recipient],
        "subject": str(message["Subject"]),
        "displayName": settings["display_name"],
        "text": text_body,
    }
    attachments = []
    for part in message.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        if (
            content_type == "text/html"
            and part.get_content_disposition() is None
            and "html" not in payload
        ):
            payload["html"] = part.get_content()
            continue
        attachment = {
            "filename": part.get_filename() or "attachment",
            "content": base64.b64encode(part.get_payload(decode=True) or b"").decode("ascii"),
            "contentType": content_type,
            "encoding": "base64",
        }
        content_id = part.get("Content-ID")
        if content_id:  # inline image referenced from the HTML as cid:...
            attachment["cid"] = content_id.strip().strip("<>")
        attachments.append(attachment)
    if attachments:
        payload["attachments"] = attachments
    mailbox_id = quote(_hostinger_mailbox_id(settings), safe="")
    status, _ = _hostinger_request(
        settings, "POST", f"/api/v1/mailboxes/{mailbox_id}/send", payload
    )
    return status in (200, 202, 204)


def smtp_settings(organization=None):
    if organization and organization.smtp_host and organization.smtp_sender:
        return {
            "host": organization.smtp_host,
            "port": organization.smtp_port or 587,
            "username": organization.smtp_username,
            "password": (
                decrypt_smtp_password(organization.smtp_password_encrypted)
                if organization.smtp_password_encrypted
                else None
            ),
            "sender": organization.smtp_sender,
            "security": organization.smtp_security,
        }
    config = current_app.config
    if config.get("DEFAULT_SMTP_HOST") and config.get("DEFAULT_SMTP_SENDER"):
        return {
            "host": config["DEFAULT_SMTP_HOST"],
            "port": config["DEFAULT_SMTP_PORT"],
            "username": config.get("DEFAULT_SMTP_USERNAME"),
            "password": config.get("DEFAULT_SMTP_PASSWORD"),
            "sender": config["DEFAULT_SMTP_SENDER"],
            "security": config.get("DEFAULT_SMTP_SECURITY", "starttls"),
        }
    return None


def send_email(
    recipient,
    subject,
    body,
    organization=None,
    content_format="text",
    event_details=None,
    event_title=None,
    event_url=None,
    calendar_event=None,
):
    calendar_url = _calendar_url(calendar_event) if calendar_event else None
    message, settings, context = _styled_email(
        recipient,
        subject,
        body,
        organization,
        content_format,
        event_details=event_details,
        event_title=event_title,
        event_url=event_url,
        calendar_url=calendar_url,
    )
    if not settings:
        return False
    if calendar_event:
        message.add_attachment(
            _calendar_invite(calendar_event).encode("utf-8"),
            maintype="text",
            subtype="calendar",
            params={"method": "PUBLISH", "charset": "UTF-8"},
            filename="event.ics",
        )
    if settings.get("transport") == "hostinger":
        return _send_via_hostinger(
            message, recipient, settings, _plain_text_body(body, content_format)
        )
    if settings["security"] not in {"starttls", "ssl"}:
        raise ValueError("SMTP must use STARTTLS or SSL/TLS.")
    addresses = socket.getaddrinfo(
        settings["host"], settings["port"], type=socket.SOCK_STREAM
    )
    public_addresses = []
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("SMTP host must resolve only to public IP addresses.")
        if ip not in public_addresses:
            public_addresses.append(ip)
    if not public_addresses:
        raise OSError("SMTP host did not resolve to an address.")
    server_host = str(public_addresses[0])
    if settings["security"] == "ssl":
        server = smtplib.SMTP_SSL(timeout=15, context=context)
    else:
        server = smtplib.SMTP(timeout=15)
    # Connect to the checked IP while retaining the configured host for TLS verification.
    server._host = settings["host"]
    server.connect(server_host, settings["port"])
    with server:
        server.ehlo()
        if settings["security"] == "starttls":
            server.starttls(context=context)
            server.ehlo()
        if settings["username"]:
            server.login(settings["username"], settings["password"] or "")
        server.send_message(message)
    return True
