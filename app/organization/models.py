from app.extensions import db
from app.utils import utcnow


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    website = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    smtp_host = db.Column(db.String(255))
    smtp_port = db.Column(db.Integer)
    smtp_username = db.Column(db.String(255))
    smtp_password_encrypted = db.Column(db.Text)
    smtp_sender = db.Column(db.String(255))
    smtp_security = db.Column(db.String(12), nullable=False, default="starttls")
    users = db.relationship("User", back_populates="organization", cascade="all, delete-orphan")
    forms = db.relationship("Form", back_populates="organization", cascade="all, delete-orphan")
