from app.extensions import db
from app.utils import utcnow

STATUS_INVITED = "invited"
STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"


class TeamProfile(db.Model):
    """A GAMKERS team contributor. Only admins create these (by invitation)."""

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id = db.Column(db.String(16), nullable=False, unique=True, index=True)
    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False, default="")
    role_title = db.Column(db.String(120), nullable=False, default="")
    bio = db.Column(db.Text, nullable=False, default="")
    photo_path = db.Column(db.String(80))
    socials = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(16), nullable=False, default=STATUS_INVITED)
    invited_by_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    joined_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    tokens = db.relationship(
        "TeamProfileToken", back_populates="profile", cascade="all, delete-orphan"
    )
    __table_args__ = (
        db.UniqueConstraint("organization_id", "email", name="uq_team_profile_email"),
        # Team IDs come from this id; never reuse one (MariaDB already doesn't).
        {"sqlite_autoincrement": True},
    )

    @property
    def is_active(self):
        return self.status == STATUS_ACTIVE

    @property
    def display_name(self):
        return self.name or self.email.split("@")[0]


class TeamProfileToken(db.Model):
    """Single-use invite and sign-in links; only the SHA-256 of the token is stored."""

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(
        db.Integer, db.ForeignKey("team_profile.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose = db.Column(db.String(12), nullable=False)  # "invite" or "login"
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    profile = db.relationship("TeamProfile", back_populates="tokens")
