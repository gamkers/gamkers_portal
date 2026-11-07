import hashlib
import secrets

from cryptography.fernet import Fernet, InvalidToken
from email_validator import EmailNotValidError, validate_email
from flask import current_app


def new_token():
    return secrets.token_urlsafe(32)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def encrypt_smtp_password(password):
    key = current_app.config.get("SMTP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("Set SMTP_ENCRYPTION_KEY before saving SMTP credentials.")
    try:
        return Fernet(key.encode("ascii")).encrypt(password.encode("utf-8")).decode("ascii")
    except (ValueError, TypeError) as error:
        raise RuntimeError("SMTP_ENCRYPTION_KEY must be a valid Fernet key.") from error


def decrypt_smtp_password(encrypted):
    key = current_app.config.get("SMTP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("Set SMTP_ENCRYPTION_KEY before sending organization email.")
    try:
        return Fernet(key.encode("ascii")).decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as error:
        raise RuntimeError("Unable to decrypt SMTP credentials; verify SMTP_ENCRYPTION_KEY.") from error


def valid_email(value):
    if not value or len(value) > 255:
        return False
    try:
        validate_email(value, check_deliverability=False)
        return True
    except EmailNotValidError:
        return False
