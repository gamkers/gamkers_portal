import os

import pytest

# Keep real mail credentials from .env out of every test: load_dotenv() never
# overrides variables that are already set, so blank them before the app imports.
os.environ["HOSTINGER_MAIL_API_TOKEN"] = ""
os.environ["HOSTINGER_MAIL_MAILBOX_ID"] = ""

from app import create_app  # noqa: E402
from app.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-key-not-for-production",
            "APPLICATION_BASE_URL": "https://forms.example",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "CERTIFICATE_STORAGE_PATH": str(tmp_path / "certificates"),
            "CERTIFICATE_UPLOAD_PATH": str(tmp_path / "certificate-uploads"),
            "FORM_BANNER_STORAGE_PATH": str(tmp_path / "form-banners"),
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "SMTP_ENCRYPTION_KEY": None,
            "DEFAULT_SMTP_HOST": None,
            "DEFAULT_SMTP_SENDER": None,
            "HOSTINGER_MAIL_API_TOKEN": None,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
