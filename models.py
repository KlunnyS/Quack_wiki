"""Database models for Quack Wiki."""

from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash


db = SQLAlchemy()


class User(db.Model, UserMixin):
    """Application account with login data, role, and public profile fields."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    profile_image_url = db.Column(db.String(120), nullable=True)
    public_display_name = db.Column(db.String(80), nullable=True)
    public_bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    role = db.Column(db.String(30), default='user')
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        """Hash and store a new password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check a submitted password against the stored hash."""
        return check_password_hash(self.password_hash, password)


class Article(db.Model):
    """Live article record shown publicly after approval."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), unique=True, nullable=False)
    author = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_url = db.Column(db.String(120), default='default.png')
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    infobox_data = db.Column(db.Text, nullable=True)
    tags = db.Column(db.JSON, default=list)
    status = db.Column(db.String(20), default='pending', nullable=False)
    approved_by = db.Column(db.String(120), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    archived_at = db.Column(db.DateTime, nullable=True)


class ArticleRevision(db.Model):
    """Pending article update awaiting reviewer approval."""

    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    editor = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    title = db.Column(db.String(120), nullable=False)
    summary = db.Column(db.Text)
    content = db.Column(db.Text, nullable=False)
    infobox_data = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(120), default='default.png')
    tags = db.Column(db.JSON, default=list)
    status = db.Column(db.String(20), default='pending', nullable=False)
    article = db.relationship('Article', backref=db.backref('revisions', lazy=True))


class SiteSettings(db.Model):
    """Singleton table for site-wide display settings."""

    id = db.Column(db.Integer, primary_key=True)
    hero_image_url = db.Column(db.String(120), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
