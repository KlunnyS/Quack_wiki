"""Initial admin seeding for Quack Wiki installs."""

from datetime import datetime
import os

from sqlalchemy.exc import IntegrityError

from models import User, db


def _build_user(username: str, email: str, role: str, password: str) -> User:
    """Create a User object with a hashed password ready for insertion."""
    user = User(
        username=username,
        email=email,
        created_at=datetime.utcnow(),
        role=role,
    )
    user.set_password(password)
    return user


def seed_admin():
    """Create the initial admin from environment variables when configured."""
    username = os.environ.get('QUACK_ADMIN_USERNAME', 'MainAdmin').strip()
    email = os.environ.get('QUACK_ADMIN_EMAIL', '').strip()
    password = os.environ.get('QUACK_ADMIN_PASSWORD', '')

    if not username or not email or not password:
        return 0

    exists = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()
    if exists:
        return 0

    db.session.add(_build_user(username, email, 'admin', password))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return 0
    return 1
