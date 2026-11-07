from urllib.parse import urljoin, urlsplit

from flask import current_app, url_for


def absolute_app_url(endpoint, **values):
    base_url = current_app.config.get("APPLICATION_BASE_URL")
    parsed = urlsplit(base_url or "")
    allowed_schemes = {"https"}
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        allowed_schemes.add("http")
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("Set APPLICATION_BASE_URL to the canonical HTTPS application URL.")
    path = url_for(endpoint, _external=False, **values).lstrip("/")
    return urljoin(base_url.rstrip("/") + "/", path)
